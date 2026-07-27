"""Git-owned runtime catalog and immutable image-lock validation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aearn_shared.execution.contracts import RuntimeCatalogEntryV1, RuntimeImageLockV1


RUNTIME_IDS: frozenset[str] = frozenset(
    {
        "python-stdout-v1",
        "browser-preview-v1",
        "node-typescript-v1",
        "sqlite-query-v1",
        "java-managed-v1",
        "go-managed-v1",
        "dotnet-managed-v1",
    }
)


class RuntimeCatalogValidationError(ValueError):
    """Raised when a catalog or image-lock registry is not exact and reviewable."""


class _CatalogFileV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^aearn-executor-runtime-catalog-v1$")
    runtimes: tuple[RuntimeCatalogEntryV1, ...] = Field(min_length=7, max_length=7)


class _ImageLockFileV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^aearn-executor-image-locks-v1$")
    locks: tuple[RuntimeImageLockV1, ...] = Field(default=(), max_length=7)


@dataclass(frozen=True)
class RuntimeCatalogRegistryV1:
    """Validated catalog plus optional real reviewed locks.

    An omitted lock is deliberately unavailable. The registry never invents a
    tag, local image id, or fallback runtime.
    """

    runtimes: tuple[RuntimeCatalogEntryV1, ...]
    locks: tuple[RuntimeImageLockV1, ...]
    catalog_fingerprint: str
    fingerprint: str

    def __post_init__(self) -> None:
        runtime_ids = tuple(runtime.runtime_id for runtime in self.runtimes)
        if set(runtime_ids) != RUNTIME_IDS or len(runtime_ids) != len(set(runtime_ids)):
            raise RuntimeCatalogValidationError("runtime catalog must contain exactly the seven approved runtimes")
        lock_ids = tuple(lock.runtime_id for lock in self.locks)
        if len(lock_ids) != len(set(lock_ids)) or any(runtime_id not in RUNTIME_IDS for runtime_id in lock_ids):
            raise RuntimeCatalogValidationError("image locks must be unique approved runtime entries")
        for fingerprint in (self.catalog_fingerprint, self.fingerprint):
            if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
                raise RuntimeCatalogValidationError("registry fingerprints must be SHA-256 values")
        for lock in self.locks:
            entry = self.runtime(lock.runtime_id)
            if (
                lock.protocol_version != entry.protocol_version
                or lock.fixed_entrypoint != entry.fixed_entrypoint
                or lock.non_root_user != entry.non_root_user
                or lock.limits != entry.limits
            ):
                raise RuntimeCatalogValidationError("image lock does not match its reviewed runtime catalog entry")

    def runtime(self, runtime_id: str) -> RuntimeCatalogEntryV1:
        for entry in self.runtimes:
            if entry.runtime_id == runtime_id:
                return entry
        raise RuntimeCatalogValidationError("unknown runtime id")

    def lock_for(self, runtime_id: str) -> RuntimeImageLockV1 | None:
        for lock in self.locks:
            if lock.runtime_id == runtime_id:
                return lock
        return None

    @property
    def enabled_runtime_ids(self) -> tuple[str, ...]:
        return tuple(lock.runtime_id for lock in self.locks)


def load_runtime_catalog_registry(
    *,
    catalog_path: Path,
    image_locks_path: Path,
) -> RuntimeCatalogRegistryV1:
    """Load two source-controlled JSON files and reject malformed inputs wholly."""

    catalog_data = _read_json(catalog_path, label="runtime catalog")
    locks_data = _read_json(image_locks_path, label="image lock registry")
    try:
        catalog = _CatalogFileV1.model_validate(catalog_data)
        locks = _ImageLockFileV1.model_validate(locks_data)
    except ValidationError as exc:
        raise RuntimeCatalogValidationError("runtime catalog or image locks are invalid") from exc

    catalog_payload = {"schema_version": catalog.schema_version, "runtimes": [item.model_dump(mode="json") for item in catalog.runtimes]}
    lock_payload = {"schema_version": locks.schema_version, "locks": [item.model_dump(mode="json") for item in locks.locks]}
    catalog_fingerprint = _fingerprint(catalog_payload)
    return RuntimeCatalogRegistryV1(
        runtimes=catalog.runtimes,
        locks=locks.locks,
        catalog_fingerprint=catalog_fingerprint,
        fingerprint=_fingerprint({"catalog": catalog_payload, "locks": lock_payload}),
    )


def runtime_id_for_profile(*, runtime_tier: str, language: str) -> str | None:
    """Derive a runtime solely from trusted exercise/runtime-profile metadata."""

    normalized_tier = str(runtime_tier or "").strip().lower()
    normalized_language = str(language or "").strip().lower()
    direct = {
        "python_stdout_test": "python-stdout-v1",
        "browser_preview": "browser-preview-v1",
        "node_typescript_test": "node-typescript-v1",
        "sql_query_test": "sqlite-query-v1",
    }
    if normalized_tier in direct:
        return direct[normalized_tier]
    if normalized_tier != "managed_compiled_test":
        return None
    return {
        "java": "java-managed-v1",
        "go": "go-managed-v1",
        "csharp": "dotnet-managed-v1",
        "c#": "dotnet-managed-v1",
    }.get(normalized_language)


def _read_json(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        if not path.is_file() or path.is_symlink():
            raise RuntimeCatalogValidationError(f"{label} must be a real source-controlled file")
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeCatalogValidationError(f"{label} could not be loaded") from exc
    if not isinstance(decoded, Mapping):
        raise RuntimeCatalogValidationError(f"{label} must contain a JSON object")
    return decoded


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
