"""Compatibility exports for the operator fixture API; policy is shared read-only."""
from app.services.grounding.corpus_fixture_policy import (
    FIXTURE_DOMAIN as FIXTURE_DOMAIN,
    FIXTURE_FETCHED_AT as FIXTURE_FETCHED_AT,
    FIXTURE_VERSION as FIXTURE_VERSION,
    FixtureSlice as FixtureSlice,
    digest as digest,
    fixture_registry_digest as fixture_registry_digest,
    fixture_slices as fixture_slices,
)
