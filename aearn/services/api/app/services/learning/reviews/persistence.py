"""Shared helpers and errors for track-scoped review persistence."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime


class ReviewRepositoryError(ValueError):
    pass


class ReviewNotFound(ReviewRepositoryError):
    pass


class ReviewNotReady(ReviewRepositoryError):
    pass


class ReviewVersionConflict(ReviewRepositoryError):
    pass


class ReviewIdempotencyConflict(ReviewRepositoryError):
    pass


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: object) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def as_mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list | tuple) else []


def as_int(value: object) -> int:
    try:
        return int(str(value or 0))
    except (TypeError, ValueError):
        return 0


def as_float(value: object) -> float:
    try:
        return float(str(value or 0))
    except (TypeError, ValueError):
        return 0.0


def as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ReviewRepositoryError("stored review timestamp is invalid")
    return utc(value)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value: object) -> str | None:
    return as_datetime(value).isoformat() if isinstance(value, datetime) else None
