"""Server-owned ingestion evidence; registry labels alone never establish origin."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

GroundingOrigin = Literal["unknown", "fixture", "http_fetch"]


@dataclass(frozen=True, slots=True)
class GroundingProvenance:
    kind: GroundingOrigin = "unknown"
    source_id: str = ""
    requested_url: str = ""
    final_url: str = ""
    document_content_hash: str = ""

    def payload(self) -> dict[str, str]:
        return {
            "schema_version": "grounding_provenance_v1",
            "kind": self.kind,
            "source_id": self.source_id,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "document_content_hash": self.document_content_hash,
        }


def provenance_from_metadata(metadata: object) -> GroundingProvenance:
    # Historical rows remain readable, but absence/unsupported shapes grant no authority.
    if not isinstance(metadata, Mapping):
        return GroundingProvenance()
    value = metadata.get("provenance")
    if not isinstance(value, Mapping) or set(value) != set(GroundingProvenance().payload()):
        return GroundingProvenance()
    if value.get("schema_version") != "grounding_provenance_v1":
        return GroundingProvenance()
    if not all(isinstance(item, str) for item in value.values()):
        return GroundingProvenance()
    kind = value.get("kind")
    if kind not in ("unknown", "fixture", "http_fetch"):
        return GroundingProvenance()
    return GroundingProvenance(
        kind=cast(GroundingOrigin, kind), source_id=value["source_id"],
        requested_url=value["requested_url"], final_url=value["final_url"],
        document_content_hash=value["document_content_hash"],
    )
