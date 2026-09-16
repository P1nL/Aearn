"""Local operator CLI; metadata by default, decrypted UTF-8 body only with --body."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from app.core.config import Settings, get_settings
from app.services.llm.provider_diagnostics import (
    _PROVIDER_DEBUG_FORMAT_VERSION,
    _PROVIDER_DEBUG_SUFFIX,
    ProviderDiagnosticStore,
)


_ARTIFACT_ID = re.compile(r"[0-9a-f]{32}")
_MAX_LIMIT = 100
# The capture limit is at most 16 MiB; allow base64 expansion and envelope metadata.
_MAX_ENVELOPE_BYTES = 24 * 1024 * 1024
_STRING_FIELDS = (
    "format_version",
    "artifact_id",
    "created_at",
    "run_id",
    "provider_type",
    "protocol",
    "model",
    "diagnostic_code",
    "contract_hash",
)
_INTEGER_FIELDS = ("attempt_index", "captured_bytes")
_OPTIONAL_INTEGER_FIELDS = ("input_revision", "decision_iteration")


class _CliError(Exception):
    """Only fixed, operator-safe messages belong in this exception."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's default errors echo arbitrary arguments, including paths/secrets.
        self.exit(2, "provider-debug: invalid arguments; use --help for usage.\n")


def _artifact_id(value: str) -> str:
    if _ARTIFACT_ID.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected exactly 32 lowercase hex characters")
    return value


def _run_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("expected a run UUID") from None


def _limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an integer limit") from None
    if not 1 <= limit <= _MAX_LIMIT:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100")
    return limit


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="python -m app.services.llm.provider_debug_cli",
        description="Inspect local encrypted provider diagnostics as JSON.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list metadata, newest first")
    listing.add_argument("--run-id", type=_run_id, metavar="UUID")
    listing.add_argument("--limit", type=_limit, default=20, help="1-100 (default: 20)")
    show = commands.add_parser("show", help="show one artifact's metadata")
    show.add_argument("artifact_id", type=_artifact_id, metavar="ARTIFACT_ID")
    show.add_argument(
        "--body",
        action="store_true",
        help="include decrypted UTF-8 body in stdout JSON (may contain sensitive data)",
    )
    return parser


def _directory(settings: Settings) -> Path:
    if settings.tutor_provider_debug_capture_mode != "rejected":
        raise _CliError("provider diagnostic capture is disabled.")
    configured = settings.tutor_provider_debug_capture_path.expanduser().absolute()
    if any(path.is_symlink() for path in (configured, *configured.parents)):
        raise _CliError("unsafe diagnostic directory.")
    # Resolve strictly before constructing the store, which otherwise creates it.
    directory = configured.resolve(strict=True)
    # Windows packaged apps can canonicalize LocalAppData to LocalCache without
    # a symlink. Fence artifact paths against this resolved, operator-owned root.
    if not directory.is_dir():
        raise _CliError("unsafe diagnostic directory.")
    return directory


def _safe_path(path: Path, directory: Path) -> Path:
    if path.is_symlink():
        raise _CliError("unsafe diagnostic artifact.")
    resolved = path.resolve(strict=True)
    if (
        resolved.parent != directory
        or resolved != path
        or resolved.suffix != _PROVIDER_DEBUG_SUFFIX
        or not resolved.is_file()
    ):
        raise _CliError("unsafe diagnostic artifact.")
    return resolved


def _artifact_paths(directory: Path) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    # Inspect all IDs before filtering/limiting, so duplicates cannot be hidden.
    for path in directory.glob(f"*{_PROVIDER_DEBUG_SUFFIX}"):
        path = _safe_path(path, directory)
        artifact_id = path.name.removesuffix(_PROVIDER_DEBUG_SUFFIX).rsplit("-", 1)[-1]
        if _ARTIFACT_ID.fullmatch(artifact_id) is None:
            raise _CliError("invalid diagnostic artifact.")
        if artifact_id in artifacts:
            raise _CliError("duplicate diagnostic artifact ID.")
        artifacts[artifact_id] = path
    return artifacts


def _metadata(path: Path, directory: Path, artifact_id: str) -> dict[str, object]:
    with _safe_path(path, directory).open("rb") as handle:
        encoded = handle.read(_MAX_ENVELOPE_BYTES + 1)
    if len(encoded) > _MAX_ENVELOPE_BYTES:
        raise _CliError("invalid diagnostic artifact.")
    envelope = json.loads(encoded)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("metadata"), dict):
        raise _CliError("invalid diagnostic artifact.")
    metadata = envelope["metadata"]
    if (
        metadata.get("artifact_id") != artifact_id
        or metadata.get("format_version") != _PROVIDER_DEBUG_FORMAT_VERSION
    ):
        raise _CliError("invalid diagnostic artifact.")
    result: dict[str, object] = {}
    for field in _STRING_FIELDS:
        value = metadata.get(field)
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 160
            or not all(char.isalnum() or char in "._:+-" for char in value)
        ):
            raise _CliError("invalid diagnostic metadata.")
        result[field] = value
    for field in (*_INTEGER_FIELDS, *_OPTIONAL_INTEGER_FIELDS):
        if field in _OPTIONAL_INTEGER_FIELDS and metadata.get(field) is None:
            continue  # Legacy captures did not include these fields.
        value = metadata.get(field)
        if type(value) is not int or value < 0:
            raise _CliError("invalid diagnostic metadata.")
        result[field] = value
    if type(metadata.get("truncated")) is not bool:
        raise _CliError("invalid diagnostic metadata.")
    result["truncated"] = metadata["truncated"]
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = get_settings()
        directory = _directory(settings)
        paths = _artifact_paths(directory)
        if args.command == "list":
            rows = [
                _metadata(path, directory, artifact_id)
                for artifact_id, path in paths.items()
            ]
            if args.run_id is not None:
                rows = [row for row in rows if row["run_id"] == args.run_id]
            rows.sort(
                key=lambda row: (str(row["created_at"]), str(row["artifact_id"])),
                reverse=True,
            )
            result: object = rows[: args.limit]
        else:
            path = paths.get(args.artifact_id)
            if path is None:
                raise _CliError("diagnostic artifact not found.")
            metadata = _metadata(path, directory, args.artifact_id)
            if args.body:
                # Metadata-only commands never initialize the capture store or decrypt.
                store = ProviderDiagnosticStore.from_settings(settings, read_only=True)
                if store is None:
                    raise _CliError("provider diagnostic capture is disabled.")
                body = store.decrypt_artifact(_safe_path(path, directory))
                metadata["body"] = body.decode("utf-8", errors="replace")
            result = metadata
        # JSON escaping keeps even explicitly requested bodies from injecting terminal controls.
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except _CliError as exc:
        print(f"provider-debug: {exc}", file=sys.stderr)
    except Exception:
        # Includes settings validation, filesystem, JSON and authentication errors.
        # Never render exception text, paths, ciphertext, keys or partially decoded bodies.
        print(
            "provider-debug: diagnostics unavailable or artifact invalid.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
