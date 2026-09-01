"""Strict filesystem seam for compiled, validated Learning Item artifacts."""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from psycopg import Connection
from pydantic import BaseModel, ConfigDict

from app.services.learning.item_bank.compiler import (
    CompiledLearningItem,
    compile_curated_learning_item_catalog,
)
from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1,
    LearningItemValidationReceiptV1,
    canonical_hash,
    raw_sha256,
)
from app.services.learning.item_bank.repository import (
    LearningItemImportResult,
    PostgresLearningItemBankRepository,
)

CURATED_LEARNING_ITEM_IMPORT_ROOT = Path(__file__).with_name("compiled")
LEARNING_ITEM_IMPORT_SUFFIX = ".learning-item.json"
_MAX_IMPORT_BYTES = 1_048_576
_MAX_IMPORT_FILES = 512
_MAX_IMPORT_TOTAL_BYTES = 16 * 1024 * 1024


class LearningItemImportArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["learning_item_import_artifact_v1"] = "learning_item_import_artifact_v1"
    source: LearningItemSourceV1
    validation_receipt: LearningItemValidationReceiptV1


class LearningItemImportFileError(ValueError):
    """Safe parse/path failure that never echoes file contents."""


class _DuplicateImportKeyError(ValueError):
    pass


def import_curated_learning_item_sources(
    conn: Connection[dict[str, object]],
    *,
    source_root: Path | None = None,
    imported_at: datetime | None = None,
) -> tuple[LearningItemImportResult, ...]:
    occurred_at = imported_at or datetime.now(UTC)
    repository = PostgresLearningItemBankRepository(conn)
    if source_root is None:
        return tuple(
            _import_compiled(repository, item, occurred_at=occurred_at)
            for item in compile_curated_learning_item_catalog().items
        )

    root, candidates = _discover_import_files(source_root)
    results: list[LearningItemImportResult] = []
    for candidate in candidates:
        raw = _read_bounded_import(candidate)
        relative = candidate.relative_to(root).as_posix()
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(payload, Mapping):
                raise ValueError("Learning Item import root must be an object")
            artifact = LearningItemImportArtifactV1.model_validate(dict(payload))
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ):
            raise LearningItemImportFileError(
                "Learning Item import file is invalid"
            ) from None
        import_key = f"curated:{canonical_hash({'source_path': relative})}"
        results.append(
            repository.import_validated_source(
                source=artifact.source,
                validation=artifact.validation_receipt,
                import_key=import_key,
                source_path=relative,
                source_file_hash=raw_sha256(raw),
                imported_at=occurred_at,
            )
        )
    return tuple(results)


def _discover_import_files(source_root: Path) -> tuple[Path, tuple[Path, ...]]:
    unresolved = Path(source_root)
    if _is_link_like(unresolved) or not unresolved.is_dir():
        raise LearningItemImportFileError(
            "Learning Item import root must be a real directory"
        )
    try:
        root = unresolved.resolve(strict=True)
    except OSError:
        raise LearningItemImportFileError(
            "Learning Item import root could not be resolved"
        ) from None

    directories = [root]
    candidates: list[Path] = []
    total_bytes = 0
    while directories:
        directory = directories.pop()
        try:
            children = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
        except OSError:
            raise LearningItemImportFileError(
                "Learning Item import directory could not be read"
            ) from None
        for child in children:
            if _is_link_like(child):
                raise LearningItemImportFileError(
                    "Learning Item import paths cannot contain links or junctions"
                )
            if child.is_dir():
                directories.append(child)
                continue
            if not child.is_file() or not child.name.endswith(LEARNING_ITEM_IMPORT_SUFFIX):
                continue
            try:
                size = child.stat().st_size
            except OSError:
                raise LearningItemImportFileError(
                    "Learning Item import metadata could not be read"
                ) from None
            if size < 1 or size > _MAX_IMPORT_BYTES:
                raise LearningItemImportFileError(
                    "Learning Item import file is empty or too large"
                )
            candidates.append(child)
            total_bytes += size
            if len(candidates) > _MAX_IMPORT_FILES:
                raise LearningItemImportFileError(
                    "Learning Item import directory contains too many files"
                )
            if total_bytes > _MAX_IMPORT_TOTAL_BYTES:
                raise LearningItemImportFileError(
                    "Learning Item import directory exceeds the total byte limit"
                )
    if not candidates:
        raise LearningItemImportFileError(
            "Learning Item import directory contains no import artifacts"
        )
    return root, tuple(sorted(candidates))


def _read_bounded_import(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_IMPORT_BYTES + 1)
    except OSError:
        raise LearningItemImportFileError(
            "Learning Item import file could not be read"
        ) from None
    if not raw or len(raw) > _MAX_IMPORT_BYTES:
        raise LearningItemImportFileError(
            "Learning Item import file is empty or too large"
        )
    return raw


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateImportKeyError("duplicate Learning Item import key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _import_compiled(
    repository: PostgresLearningItemBankRepository,
    item: CompiledLearningItem,
    *,
    occurred_at: datetime,
) -> LearningItemImportResult:
    relative = item.loaded.relative_path
    import_key = f"curated:{canonical_hash({'source_path': relative})}"
    return repository.import_validated_source(
        source=item.loaded.source,
        validation=item.validation,
        import_key=import_key,
        source_path=relative,
        source_file_hash=item.loaded.source_bytes_hash,
        imported_at=occurred_at,
    )


__all__ = (
    "CURATED_LEARNING_ITEM_IMPORT_ROOT",
    "LEARNING_ITEM_IMPORT_SUFFIX",
    "LearningItemImportArtifactV1",
    "LearningItemImportFileError",
    "import_curated_learning_item_sources",
)
