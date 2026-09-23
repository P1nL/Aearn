"""Synthetic, registry-owned phase-I corpus material. Never represents fetched pages."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.grounding.subject_contracts import GroundingSubject

FIXTURE_VERSION = "fixture-v1"
FIXTURE_DOMAIN = "fixtures.aearn.invalid"
FIXTURE_FETCHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FixtureSlice:
    source_id: str
    facet: str
    url: str
    content: str


def fixture_slices(subject: GroundingSubject) -> tuple[FixtureSlice, ...]:
    """One explicitly synthetic, Subject-bound slice for each required facet."""
    return tuple(
        FixtureSlice(
            source_id=f"fixture.{subject.subject_id}.{facet}",
            facet=facet,
            url=f"https://{FIXTURE_DOMAIN}/{subject.subject_id}/{facet}",
            content=(f"Synthetic {subject.subject_id} {facet} fixture. "
                     "Deterministic test material only; not a fetched page, tutorial, "
                     "or evidence of learner-ready coverage."),
        )
        for facet in subject.required_facets
    )


def fixture_registry_digest(subject: GroundingSubject) -> str:
    return digest({"subject": subject.model_dump(mode="json"), "version": FIXTURE_VERSION,
                   "fixtures": [(item.source_id, item.facet, item.url, digest(item.content))
                                for item in fixture_slices(subject)], "policy": "fixture-corpus-v1"})
