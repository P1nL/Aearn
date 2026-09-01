"""Fail-closed compiler for Git-owned Learning Item Bank source files."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError
from yaml.nodes import MappingNode  # type: ignore[import-untyped]
from yaml.resolver import BaseResolver  # type: ignore[import-untyped]
from yaml.tokens import AliasToken, AnchorToken  # type: ignore[import-untyped]

from app.services.learning.item_bank.contracts import (
    LEARNING_ITEM_COMPILER_VERSION,
    LearningItemSourceV1,
    LearningItemValidationReceiptV1,
    LearningItemVersionIdentityV1,
    canonical_hash,
    learning_item_handle,
    learning_item_uuid,
    normalize_newlines,
    raw_sha256,
)
from app.services.learning.item_bank.validation import validate_learning_item


MAX_LEARNING_ITEM_SOURCE_BYTES = 256 * 1024
MAX_LEARNING_ITEM_SOURCE_FILES = 512
MAX_LEARNING_ITEM_SOURCE_TOTAL_BYTES = 16 * 1024 * 1024
MAX_LEARNING_ITEM_SOURCE_DEPTH = 64
MAX_LEARNING_ITEM_SOURCE_NODES = 50_000

_SOURCE_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
_YAML_UNSAFE_TOKENS = (AliasToken, AnchorToken)


class LearningItemSourceError(ValueError):
    """Safe compiler failure that never includes source or private values."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _DuplicateKeyError(ValueError):
    pass


class _UniqueKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError:
            raise _DuplicateKeyError("YAML mapping keys must be scalar") from None
        if duplicate:
            raise _DuplicateKeyError("duplicate YAML mapping key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class LoadedLearningItemSource:
    relative_path: str
    source_format: Literal["json", "yaml"]
    source_bytes_hash: str
    raw_source_hash: str
    source_payload_hash: str
    source: LearningItemSourceV1


@dataclass(frozen=True, slots=True)
class LearningItemCompilationIdentity:
    blueprint_id: UUID
    item_id: UUID
    version_id: UUID
    private_id: UUID
    import_id: UUID
    version: LearningItemVersionIdentityV1


@dataclass(frozen=True, slots=True)
class CompiledLearningItem:
    loaded: LoadedLearningItemSource
    identity: LearningItemCompilationIdentity
    validation: LearningItemValidationReceiptV1


@dataclass(frozen=True, slots=True)
class LearningItemCatalogSnapshot:
    items: tuple[CompiledLearningItem, ...]
    digest: str
    raw_source_digest: str


class LearningItemSourceLoader:
    """Load one UTF-8 JSON/YAML source without following links or escapes."""

    def __init__(self, *, max_source_bytes: int = MAX_LEARNING_ITEM_SOURCE_BYTES) -> None:
        if max_source_bytes < 1:
            raise ValueError("max_source_bytes must be positive")
        self._max_source_bytes = max_source_bytes

    def load(self, source_root: Path, source_path: str | Path) -> LoadedLearningItemSource:
        root = _require_real_directory(source_root)
        candidate, relative_path = _resolve_source_file(root, source_path)
        source_format = _source_format(candidate)
        raw = _read_bounded_bytes(candidate, maximum=self._max_source_bytes)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise LearningItemSourceError(
                "source_encoding_invalid",
                "Learning item source must be UTF-8",
            ) from None

        parse_text = text.removeprefix("\ufeff")
        payload = _parse_source(parse_text, source_format=source_format)
        _require_json_tree(payload)
        if not isinstance(payload, Mapping):
            raise LearningItemSourceError(
                "source_root_object_required",
                "Learning item source root must be an object",
            )
        try:
            source = LearningItemSourceV1.model_validate(dict(payload))
        except (ValidationError, ValueError, TypeError):
            raise LearningItemSourceError(
                "source_schema_invalid",
                "Learning item source does not match the strict source schema",
            ) from None

        canonical_raw = normalize_newlines(parse_text).encode("utf-8")
        return LoadedLearningItemSource(
            relative_path=relative_path,
            source_format=source_format,
            source_bytes_hash=raw_sha256(raw),
            raw_source_hash=raw_sha256(canonical_raw),
            source_payload_hash=canonical_hash(dict(payload)),
            source=source,
        )


class LearningItemCompiler:
    """Compile a whole source directory or fail without a partial snapshot."""

    def __init__(
        self,
        *,
        loader: LearningItemSourceLoader | None = None,
        max_source_files: int = MAX_LEARNING_ITEM_SOURCE_FILES,
        max_total_bytes: int = MAX_LEARNING_ITEM_SOURCE_TOTAL_BYTES,
    ) -> None:
        if max_source_files < 1 or max_total_bytes < 1:
            raise ValueError("compiler source limits must be positive")
        self._loader = loader or LearningItemSourceLoader()
        self._max_source_files = max_source_files
        self._max_total_bytes = max_total_bytes

    def compile_file(
        self,
        source_root: Path,
        source_path: str | Path,
        *,
        require_valid: bool = False,
    ) -> CompiledLearningItem:
        loaded = self._loader.load(source_root, source_path)
        compiled = _compile_loaded_source(loaded)
        if require_valid and not compiled.validation.passed:
            raise LearningItemSourceError(
                "source_validation_failed",
                "Learning item source failed deterministic validation",
            )
        return compiled

    def compile_directory(
        self,
        source_root: Path,
        *,
        require_valid: bool = True,
    ) -> LearningItemCatalogSnapshot:
        root = _require_real_directory(source_root)
        paths = _discover_source_files(
            root,
            max_source_files=self._max_source_files,
            max_total_bytes=self._max_total_bytes,
        )
        if not paths:
            raise LearningItemSourceError(
                "source_catalog_empty",
                "Learning item source directory contains no source files",
            )

        items = tuple(
            self.compile_file(root, path, require_valid=require_valid)
            for path in paths
        )
        _require_unique_versions(items)
        return LearningItemCatalogSnapshot(
            items=items,
            digest=_catalog_digest(items),
            raw_source_digest=_raw_source_digest(items),
        )


def curated_learning_item_source_root() -> Path:
    return Path(__file__).resolve().parent / "sources" / "curated"


def compile_curated_learning_item_catalog() -> LearningItemCatalogSnapshot:
    return LearningItemCompiler().compile_directory(curated_learning_item_source_root())


def _compile_loaded_source(loaded: LoadedLearningItemSource) -> CompiledLearningItem:
    source = loaded.source
    content_hash = source.content_hash
    handle = learning_item_handle(source.public.item_key, source.public.version, content_hash)
    version = LearningItemVersionIdentityV1(
        item_key=source.public.item_key,
        version=source.public.version,
        content_hash=content_hash,
        handle=handle,
    )
    identity = LearningItemCompilationIdentity(
        blueprint_id=learning_item_uuid(
            "blueprint",
            f"{source.blueprint.blueprint_key}@{source.blueprint.version}:{source.blueprint.blueprint_hash}",
        ),
        item_id=learning_item_uuid("item", source.public.item_key),
        version_id=learning_item_uuid("version", handle),
        private_id=learning_item_uuid(
            "private",
            f"{source.private.item_key}@{source.private.version}:{source.private.private_hash}",
        ),
        import_id=learning_item_uuid(
            "import",
            f"{source.public.item_key}@{source.public.version}:{loaded.raw_source_hash}",
        ),
        version=version,
    )
    return CompiledLearningItem(
        loaded=loaded,
        identity=identity,
        validation=validate_learning_item(source),
    )


def _parse_source(
    value: str,
    *,
    source_format: Literal["json", "yaml"],
) -> object:
    if source_format == "json":
        try:
            return json.loads(
                value,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except _DuplicateKeyError:
            raise LearningItemSourceError(
                "source_duplicate_key",
                "Learning item JSON contains a duplicate key",
            ) from None
        except (json.JSONDecodeError, ValueError, TypeError):
            raise LearningItemSourceError(
                "source_parse_invalid",
                "Learning item JSON could not be parsed",
            ) from None

    try:
        if any(isinstance(token, _YAML_UNSAFE_TOKENS) for token in yaml.scan(value)):
            raise LearningItemSourceError(
                "source_yaml_feature_forbidden",
                "Learning item YAML cannot use anchors or aliases",
            )
        return yaml.load(value, Loader=_UniqueKeySafeLoader)
    except LearningItemSourceError:
        raise
    except _DuplicateKeyError:
        raise LearningItemSourceError(
            "source_duplicate_key",
            "Learning item YAML contains a duplicate key",
        ) from None
    except yaml.YAMLError:
        raise LearningItemSourceError(
            "source_parse_invalid",
            "Learning item YAML could not be parsed",
        ) from None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError("duplicate JSON mapping key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _require_json_tree(value: object) -> None:
    node_count = 0
    active: set[int] = set()

    def visit(node: object, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if depth > MAX_LEARNING_ITEM_SOURCE_DEPTH or node_count > MAX_LEARNING_ITEM_SOURCE_NODES:
            raise LearningItemSourceError(
                "source_structure_too_large",
                "Learning item source structure exceeds deterministic limits",
            )
        if node is None or isinstance(node, str | bool | int):
            return
        if isinstance(node, float):
            if not math.isfinite(node):
                raise LearningItemSourceError(
                    "source_number_invalid",
                    "Learning item source contains a non-finite number",
                )
            return
        if isinstance(node, Mapping):
            identity = id(node)
            if identity in active:
                raise LearningItemSourceError(
                    "source_structure_recursive",
                    "Learning item source cannot be recursive",
                )
            active.add(identity)
            try:
                for key, item in node.items():
                    if not isinstance(key, str):
                        raise LearningItemSourceError(
                            "source_mapping_key_invalid",
                            "Learning item source mapping keys must be strings",
                        )
                    visit(item, depth + 1)
            finally:
                active.remove(identity)
            return
        if isinstance(node, list):
            identity = id(node)
            if identity in active:
                raise LearningItemSourceError(
                    "source_structure_recursive",
                    "Learning item source cannot be recursive",
                )
            active.add(identity)
            try:
                for item in node:
                    visit(item, depth + 1)
            finally:
                active.remove(identity)
            return
        raise LearningItemSourceError(
            "source_value_invalid",
            "Learning item source must contain JSON-compatible values only",
        )

    visit(value, 0)


def _require_real_directory(source_root: Path) -> Path:
    unresolved = Path(source_root)
    if _is_link_like(unresolved) or not unresolved.is_dir():
        raise LearningItemSourceError(
            "source_root_invalid",
            "Learning item source root must be a real directory",
        )
    try:
        return unresolved.resolve(strict=True)
    except OSError:
        raise LearningItemSourceError(
            "source_root_invalid",
            "Learning item source root could not be resolved",
        ) from None


def _resolve_source_file(root: Path, source_path: str | Path) -> tuple[Path, str]:
    relative = Path(source_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise LearningItemSourceError(
            "source_path_invalid",
            "Learning item source path must be a safe root-relative path",
        )

    cursor = root
    for part in relative.parts:
        cursor /= part
        if _is_link_like(cursor):
            raise LearningItemSourceError(
                "source_symlink_forbidden",
                "Learning item source paths cannot contain links or junctions",
            )
    try:
        candidate = cursor.resolve(strict=True)
        safe_relative = candidate.relative_to(root).as_posix()
    except (OSError, ValueError):
        raise LearningItemSourceError(
            "source_path_escape",
            "Learning item source path escapes or is missing from the source root",
        ) from None
    if not candidate.is_file() or _is_link_like(candidate):
        raise LearningItemSourceError(
            "source_file_invalid",
            "Learning item source path must identify a regular file",
        )
    return candidate, safe_relative


def _source_format(path: Path) -> Literal["json", "yaml"]:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    raise LearningItemSourceError(
        "source_format_unsupported",
        "Learning item source files must use JSON or YAML",
    )


def _read_bounded_bytes(path: Path, *, maximum: int) -> bytes:
    try:
        if path.stat().st_size > maximum:
            raise LearningItemSourceError(
                "source_file_too_large",
                "Learning item source file exceeds the byte limit",
            )
        with path.open("rb") as stream:
            value = stream.read(maximum + 1)
    except LearningItemSourceError:
        raise
    except OSError:
        raise LearningItemSourceError(
            "source_file_unreadable",
            "Learning item source file could not be read",
        ) from None
    if len(value) > maximum:
        raise LearningItemSourceError(
            "source_file_too_large",
            "Learning item source file exceeds the byte limit",
        )
    if not value.strip():
        raise LearningItemSourceError(
            "source_file_empty",
            "Learning item source file cannot be empty",
        )
    return value


def _discover_source_files(
    root: Path,
    *,
    max_source_files: int,
    max_total_bytes: int,
) -> tuple[str, ...]:
    directories = [root]
    paths: list[str] = []
    total_bytes = 0
    while directories:
        directory = directories.pop()
        try:
            children = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
        except OSError:
            raise LearningItemSourceError(
                "source_catalog_unreadable",
                "Learning item source directory could not be read",
            ) from None
        for child in children:
            if _is_link_like(child):
                raise LearningItemSourceError(
                    "source_symlink_forbidden",
                    "Learning item source directories cannot contain links or junctions",
                )
            if child.is_dir():
                directories.append(child)
                continue
            if not child.is_file() or child.suffix.casefold() not in _SOURCE_SUFFIXES:
                raise LearningItemSourceError(
                    "source_catalog_entry_invalid",
                    "Learning item source directories may contain only JSON/YAML files and directories",
                )
            paths.append(child.relative_to(root).as_posix())
            try:
                total_bytes += child.stat().st_size
            except OSError:
                raise LearningItemSourceError(
                    "source_catalog_unreadable",
                    "Learning item source metadata could not be read",
                ) from None
            if len(paths) > max_source_files:
                raise LearningItemSourceError(
                    "source_file_count_exceeded",
                    "Learning item source directory contains too many files",
                )
            if total_bytes > max_total_bytes:
                raise LearningItemSourceError(
                    "source_total_size_exceeded",
                    "Learning item source directory exceeds the total byte limit",
                )
    return tuple(sorted(paths))


def _require_unique_versions(items: tuple[CompiledLearningItem, ...]) -> None:
    identities = tuple(
        (item.loaded.source.public.item_key, item.loaded.source.public.version)
        for item in items
    )
    if len(identities) != len(set(identities)):
        raise LearningItemSourceError(
            "source_duplicate_version",
            "Learning item source directory contains a duplicate item version",
        )


def _catalog_digest(items: tuple[CompiledLearningItem, ...]) -> str:
    return canonical_hash(
        {
            "compiler_version": LEARNING_ITEM_COMPILER_VERSION,
            "items": [
                {
                    "item_key": item.identity.version.item_key,
                    "version": item.identity.version.version,
                    "content_hash": item.identity.version.content_hash,
                    "handle": item.identity.version.handle,
                    "source_hash": item.loaded.source.source_hash,
                    "validation_hash": item.validation.receipt_hash,
                }
                for item in items
            ],
        }
    )


def _raw_source_digest(items: tuple[CompiledLearningItem, ...]) -> str:
    return canonical_hash(
        [
            {
                "relative_path": item.loaded.relative_path,
                "source_bytes_hash": item.loaded.source_bytes_hash,
                "raw_source_hash": item.loaded.raw_source_hash,
                "source_payload_hash": item.loaded.source_payload_hash,
            }
            for item in items
        ]
    )


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


__all__ = (
    "MAX_LEARNING_ITEM_SOURCE_BYTES",
    "MAX_LEARNING_ITEM_SOURCE_FILES",
    "MAX_LEARNING_ITEM_SOURCE_TOTAL_BYTES",
    "CompiledLearningItem",
    "LearningItemCatalogSnapshot",
    "LearningItemCompilationIdentity",
    "LearningItemCompiler",
    "LearningItemSourceError",
    "LearningItemSourceLoader",
    "LoadedLearningItemSource",
    "compile_curated_learning_item_catalog",
    "curated_learning_item_source_root",
)
