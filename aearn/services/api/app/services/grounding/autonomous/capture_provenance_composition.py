"""Exact capture routing to independently pinned, same-connection C verifiers."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from psycopg import Connection

from .registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from .source_review_repository import CompleteCapture


class PinnedCaptureProvenanceComposition:
    """Server-owned finite pins; never try another verifier after a denial."""

    def __init__(
        self, conn: Connection[dict[str, Any]], *,
        captures: Mapping[UUID, PostgresCurrentCaptureProvenanceResolver],
    ) -> None:
        if (conn is None or not 1 <= len(captures) <= 8
                or any(type(key) is not UUID
                       or type(value) is not PostgresCurrentCaptureProvenanceResolver
                       or value.conn is not conn for key, value in captures.items())):
            raise ValueError("PROVENANCE_COMPOSITION_DENIED")
        self.conn = conn
        self._captures = MappingProxyType(dict(captures))

    def resolve(self, capture: CompleteCapture) -> str | None:
        if type(capture) is not CompleteCapture:
            return None
        resolver = self._captures.get(capture.capture_id)
        return resolver.resolve(capture) if resolver is not None else None
