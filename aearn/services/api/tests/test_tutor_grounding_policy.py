from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorCapabilityStatus,
    TutorPolicySnapshot,
    TutorRunSnapshot,
    payload_fields_from_mapping,
)
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.tutor.capability_gateway import CatalogCapabilityGateway
from app.services.tutor.capability_policy import CapabilityPolicyContext, InMemoryCapabilityPolicyResolver
from app.services.tutor.grounding_lookup import GroundingLookupItem, InMemoryGroundingLookup
from app.services.tutor.skill_selection import InMemoryTutorSkillSelectionStore, TutorSkillSelection


NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="grounding-run",
        conversation_id="grounding-conversation",
        user_id="grounding-user",
        input_revision=0,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=UTC),
            max_capability_calls=1,
            max_effects=0,
        ),
    )


def _policy(
    catalog,
    run: TutorRunSnapshot,
    *,
    consent_granted: bool = True,
    runtime_available: bool = True,
) -> CapabilityPolicyContext:
    return CapabilityPolicyContext(
        run_id=run.run_id,
        user_id=run.user_id,
        origin="interactive",
        input_revision=run.input_revision,
        catalog_digest=catalog.digest,
        eligible_skill_references=(catalog.skills[0].reference,),
        eligible_capability_ids=("grounding.retrieve",),
        granted_policy_tags=("registry-grounding",),
        allowed_origins=("interactive",),
        consent_granted=consent_granted,
        runtime_available_capability_ids=(("grounding.retrieve",) if runtime_available else ()),
        remaining_capability_budget=1,
        allowed_source_ids=("python-tutorial",),
    )


def _store_with_selection(catalog, run: TutorRunSnapshot) -> InMemoryTutorSkillSelectionStore:
    store = InMemoryTutorSkillSelectionStore()
    skill = catalog.skills[0]
    store.record(
        run_id=run.run_id,
        input_revision=run.input_revision,
        selection=TutorSkillSelection(
            reference=skill.reference,
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )
    return store


def _request(**overrides: object) -> TutorCapabilityRequest:
    arguments: dict[str, object] = {
        "language_id_or_alias": "python",
        "query_text": "How does a function return a value?",
        "topic_tags": ["functions"],
        "top_k": 1,
    }
    arguments.update(overrides)
    return TutorCapabilityRequest(
        request_id="grounding-1",
        capability_id="grounding.retrieve",
        arguments=payload_fields_from_mapping(arguments),
    )


def _chunk(*, source_id: str = "python-tutorial") -> GroundingChunk:
    return GroundingChunk(
        chunk_id="python-functions",
        source_id=source_id,
        language_id="python",
        title="Functions",
        section_path=("Python Tutorial", "Functions"),
        canonical_url="https://docs.python.org/3/tutorial/controlflow.html",
        source_type="tutorial",
        source_trust_tier="official",
        fetched_at=NOW,
        content_hash="a" * 64,
        text="A function can return a value to its caller with the return statement.",
        topic_tags=("functions",),
    )


def _gateway(catalog, run: TutorRunSnapshot, resolver, selection_store, lookup) -> CatalogCapabilityGateway:
    return CatalogCapabilityGateway(
        catalog=catalog,
        policy_resolver=resolver,
        selection_store=selection_store,
        grounding_lookup=lookup,
    )


def test_grounding_retrieve_uses_registry_scope_and_returns_bounded_citation_facts() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    selection_store = _store_with_selection(catalog, run)
    lookup = InMemoryGroundingLookup((_chunk(),))

    result = _gateway(catalog, run, resolver, selection_store, lookup).dispatch(run=run, request=_request())

    assert result.status is TutorCapabilityStatus.COMPLETED
    assert result.diagnostic_code == "grounding_completed"
    assert [field.key for field in result.safe_result] == ["snippet_1", "citation_1", "content_hash_1"]
    citation = json.loads(next(field.value for field in result.safe_result if field.key == "citation_1"))
    assert citation["source_id"] == "python-tutorial"
    assert citation["canonical_url"].startswith("https://docs.python.org/")
    assert next(field.value for field in result.safe_result if field.key == "content_hash_1") == "a" * 64
    assert lookup.calls[0][1] == ("python-tutorial",)


def test_grounding_retrieve_reports_unsupported_language_and_empty_index_without_persistence() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    selection_store = _store_with_selection(catalog, run)
    lookup = InMemoryGroundingLookup()
    gateway = _gateway(catalog, run, resolver, selection_store, lookup)

    unsupported = gateway.dispatch(run=run, request=_request(language_id_or_alias="unsupported-language"))
    empty = gateway.dispatch(run=run, request=_request())

    assert unsupported.status is TutorCapabilityStatus.UNAVAILABLE
    assert unsupported.diagnostic_code == "unsupported_grounding_language"
    assert lookup.calls == [(lookup.calls[0][0], ("python-tutorial",))]
    assert empty.status is TutorCapabilityStatus.COMPLETED
    assert empty.diagnostic_code == "grounding_empty"
    assert empty.safe_result[0].value == "empty"


class _StaticLookup:
    def __init__(self, items: tuple[GroundingLookupItem, ...]) -> None:
        self.items = items
        self.calls: list[tuple[object, tuple[str, ...]]] = []

    def lookup(self, *, query: object, source_ids: tuple[str, ...]) -> tuple[GroundingLookupItem, ...]:
        self.calls.append((query, source_ids))
        return self.items


def test_grounding_filters_lookup_results_that_do_not_match_the_registry_scope() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    selection_store = _store_with_selection(catalog, run)
    valid = GroundingLookupItem(
        source_id="python-tutorial",
        language_id="python",
        citation_id="citation-python",
        title="Functions",
        canonical_url="https://docs.python.org/3/tutorial/controlflow.html",
        section_path=("Functions",),
        trust_tier="official",
        content_hash="b" * 64,
        content="Use return to provide a function result.",
        relevance_score=4.0,
        match_reasons=("query_terms",),
    )
    mismatched = GroundingLookupItem(
        source_id="mdn-javascript-guide",
        language_id="javascript",
        citation_id="citation-js",
        title="Functions",
        canonical_url="https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Functions",
        section_path=("Functions",),
        trust_tier="official",
        content_hash="c" * 64,
        content="This must be filtered.",
        relevance_score=9.0,
        match_reasons=("query_terms",),
    )
    lookup = _StaticLookup((mismatched, valid))

    result = _gateway(catalog, run, resolver, selection_store, lookup).dispatch(run=run, request=_request())

    serialized = json.dumps([(field.key, field.value) for field in result.safe_result])
    assert result.status is TutorCapabilityStatus.COMPLETED
    assert "python-tutorial" in serialized
    assert "mdn-javascript-guide" not in serialized


def test_grounding_rejects_credentialed_registry_urls_and_invalid_lookup_output() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    selection_store = _store_with_selection(catalog, run)
    credentialed = GroundingLookupItem(
        source_id="python-tutorial",
        language_id="python",
        citation_id="citation-credentialed",
        title="Functions",
        canonical_url="https://user:secret@docs.python.org/3/tutorial/controlflow.html",
        section_path=("Functions",),
        trust_tier="official",
        content_hash="d" * 64,
        content="This credentialed URL must not be returned.",
        relevance_score=3.0,
        match_reasons=("query_terms",),
    )
    invalid = GroundingLookupItem(
        source_id="python-tutorial",
        language_id="python",
        citation_id="citation-invalid",
        title="Functions",
        canonical_url="https://docs.python.org/3/tutorial/controlflow.html",
        section_path=("Functions",),
        trust_tier="official",
        content_hash="not-a-sha256",
        content="This malformed lookup result must fail closed.",
        relevance_score=3.0,
        match_reasons=("query_terms",),
    )

    credentialed_result = _gateway(
        catalog,
        run,
        resolver,
        selection_store,
        _StaticLookup((credentialed,)),
    ).dispatch(run=run, request=_request())
    invalid_result = _gateway(
        catalog,
        run,
        resolver,
        selection_store,
        _StaticLookup((invalid,)),
    ).dispatch(run=run, request=_request())

    assert credentialed_result.status is TutorCapabilityStatus.COMPLETED
    assert credentialed_result.diagnostic_code == "grounding_empty"
    assert "secret" not in repr(credentialed_result)
    assert invalid_result.status is TutorCapabilityStatus.UNAVAILABLE
    assert invalid_result.diagnostic_code == "grounding_lookup_invalid_result"


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_id": "python-tutorial"},
        {"url": "https://untrusted.example/doc"},
        {"path": "C:\\temp\\notes.txt"},
        {"image": "diagram.png"},
        {"user_id": "other-user"},
        {"command": "powershell Get-ChildItem"},
        {"query_text": "https://untrusted.example/doc"},
        {"query_text": "SELECT * FROM learner_notes"},
    ],
)
def test_grounding_rejects_extra_or_target_like_input_before_lookup(overrides: dict[str, object]) -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    selection_store = _store_with_selection(catalog, run)
    lookup = InMemoryGroundingLookup((_chunk(),))

    result = _gateway(catalog, run, resolver, selection_store, lookup).dispatch(
        run=run,
        request=_request(**overrides),
    )

    assert result.status is TutorCapabilityStatus.DENIED
    assert lookup.calls == []


def test_grounding_denies_policy_and_reports_runtime_unavailable_without_lookup() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    selection_store = _store_with_selection(catalog, run)
    lookup = InMemoryGroundingLookup((_chunk(),))

    denied = _gateway(
        catalog,
        run,
        InMemoryCapabilityPolicyResolver([_policy(catalog, run, consent_granted=False)]),
        selection_store,
        lookup,
    ).dispatch(run=run, request=_request())
    unavailable = _gateway(
        catalog,
        run,
        InMemoryCapabilityPolicyResolver([_policy(catalog, run, runtime_available=False)]),
        selection_store,
        lookup,
    ).dispatch(run=run, request=_request())

    assert denied.status is TutorCapabilityStatus.DENIED
    assert denied.diagnostic_code == "capability_not_policy_eligible"
    assert unavailable.status is TutorCapabilityStatus.UNAVAILABLE
    assert unavailable.diagnostic_code == "capability_runtime_unavailable"
    assert lookup.calls == []
