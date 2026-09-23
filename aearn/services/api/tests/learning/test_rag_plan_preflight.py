"""Offline shadow preflight contracts. No provider, bootstrap or public route."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast
from uuid import UUID

import pytest
from psycopg import Connection

from app.services.grounding.coverage import unavailable_report
from app.services.grounding.retrieval_contracts import (
    CoverageReport, GroundingRetrievalResultV2, stable_hash,
)
from app.services.grounding.subject_registry import capability_projection
from app.services.grounding.subject_contracts import SubjectCapabilityProjection
from app.services.learning.contracts import LearningPlan, LearningPlanModule, LearningPlanNode
from app.services.learning.plan_coverage import (
    NodeCapabilityFacts, NodeSourceRequirement, PlanCoveragePreflightService,
    PlanPreflightConflict, PlanCoverageShadowAdapter, PostgresPlanFactReader,
)
from app.services.learning.plan_migration import PlanRepairProposalBuilder
from app.services.learning.item_bank.repository import PostgresLearningItemBankRepository

SUMMARY = "a" * 64
CORPUS_ID = UUID("00000000-0000-0000-0000-000000000011")


def plan(*, core: bool = True, key: str = "python-basics", catalog: str | None = None) -> LearningPlan:
    return LearningPlan(
        title="Python learning", target_level="beginner", generator_version="fixture-v1",
        policy_version="fixture-v1", change_reason="initial",
        modules=(LearningPlanModule(
            module_key="m1", title="Basics", description="", order_index=0,
            is_core=core, is_skippable=not core,
            nodes=(LearningPlanNode(
                knowledge_key=key, title="Python concepts", description="",
                order_index=0, is_core=core, prerequisite_keys=(),
                required_capabilities=("lesson",), catalog_knowledge_key=catalog,
            ),),
        ),),
    )


def requirement(*, key: str = "python-basics", subject: str = "route.python",
                facets: tuple[str, ...] = ("fundamentals",),
                capabilities: tuple[str, ...] = ("lesson", "practice")) -> NodeSourceRequirement:
    return NodeSourceRequirement(
        knowledge_key=key, subject_id=subject, subject_version="fixture-v1",
        required_facets=facets, required_capabilities=capabilities,
        expected_corpus_generation=1, expected_corpus_summary_hash=SUMMARY,
    )


def coverage(req: NodeSourceRequirement, *, status: str = "satisfied",
             stale: bool = False) -> CoverageReport:
    missing = req.required_facets if status != "satisfied" else ()
    fields = {
        "request_hash": "b" * 64, "corpus_summary_hash": SUMMARY,
        "registry_digest": "c" * 64, "status": status,
        "subject_id": req.subject_id, "subject_version": req.subject_version,
        "corpus_id": CORPUS_ID, "required_facets": req.required_facets,
        "covered_facets": () if missing else req.required_facets,
        "missing_facets": missing, "source_count": 0 if missing else 1,
        "trust_tiers": () if missing else ("official",),
        "freshness_state": "stale" if stale else "current", "version_state": "exact",
        "budget_state": "within", "used_characters": 0,
        "used_estimated_tokens": 0, "used_chunks": 0,
        "reason_codes": ("CORPUS_STALE",) if stale else (("FACET_MISSING",) if missing else ()),
    }
    return CoverageReport.model_validate({**fields, "report_hash": stable_hash(fields)})


@dataclass
class FakeFacts:
    status: str = "satisfied"
    synthetic: bool = False
    stale: bool = False
    handles: tuple[str, ...] = ()
    projection_override: SubjectCapabilityProjection | None = None

    def read(self, req: NodeSourceRequirement, *, query_text: str,
             item_knowledge_key: str | None,
             item_capabilities: tuple[str, ...]) -> NodeCapabilityFacts:
        projection = self.projection_override or capability_projection(req.subject_id)
        assert projection is not None
        result = coverage(req, status=self.status, stale=self.stale)
        payload = {
            "coverage_hash": result.report_hash, "projection": projection.model_dump(mode="json"),
            "handles": self.handles, "generation": req.expected_corpus_generation,
            "synthetic_fixture": self.synthetic, "runtime_verified": False,
        }
        return NodeCapabilityFacts(
            coverage=result, projection=projection, published_item_handles=self.handles,
            source_generation=req.expected_corpus_generation,
            synthetic_fixture=self.synthetic, runtime_verified=False, facts_hash=stable_hash(payload),
        )


def test_core_and_optional_shadows_never_activate() -> None:
    facts = FakeFacts(status="partial", synthetic=True)
    for core in (True, False):
        draft = plan(core=core)
        report = PlanCoveragePreflightService(facts).evaluate(
            draft, (requirement(),), expected_plan_hash=draft.content_hash,
        )
        assert report.status == "partial"
        assert report.activation_blocked is core
        proposal = PlanRepairProposalBuilder().build(draft, report)
        assert proposal.activation_allowed is False
        assert proposal.node_diffs[0].action == ("wait_for_release" if core else "defer_subject")
        assert proposal.node_diffs[0].source_summary_hash == SUMMARY
        assert proposal.node_diffs[0].capability_hash == report.nodes[0].capability_hash
        assert proposal.node_diffs[0].before_required_assessments == ("lesson", "practice")
        assert proposal.proposal_hash == PlanRepairProposalBuilder().build(draft, report).proposal_hash


def test_uncovered_core_and_fixture_only_ecosystem() -> None:
    draft = plan(key="lc-overview")
    req = requirement(key="lc-overview", subject="python.ai-applications", facets=("langchain-core",))
    report = PlanCoveragePreflightService(FakeFacts(status="insufficient", synthetic=True)).evaluate(
        draft, (req,), expected_plan_hash=draft.content_hash,
    )
    assert report.activation_blocked
    assert report.nodes[0].status == "unavailable"
    assert "SYNTHETIC_FIXTURE_ONLY" in report.nodes[0].reason_codes
    proposal = PlanRepairProposalBuilder().build(draft, report)
    assert proposal.state == "blocked"
    assert proposal.node_diffs[0].action == "wait_for_release"
    assert proposal.node_diffs[0].after_subject_id == "python.ai-applications"


def test_missing_node_stale_plan_and_stale_corpus_fail_closed() -> None:
    draft = plan()
    service = PlanCoveragePreflightService(FakeFacts())
    with pytest.raises(PlanPreflightConflict, match="exact plan"):
        service.evaluate(draft, (), expected_plan_hash=draft.content_hash)
    with pytest.raises(PlanPreflightConflict, match="assessment scope omitted"):
        service.evaluate(draft, (requirement(capabilities=("lesson",)),),
                         expected_plan_hash=draft.content_hash)
    with pytest.raises(PlanPreflightConflict, match="revision changed"):
        service.evaluate(draft, (requirement(),), expected_plan_hash="0" * 64)
    with pytest.raises(PlanPreflightConflict, match="pointer changed"):
        PlanCoveragePreflightService(FakeFacts(stale=True)).evaluate(
            draft, (requirement(),), expected_plan_hash=draft.content_hash,
        )


def test_no_item_cannot_grant_practice_even_with_subject_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.learning.plan_coverage as module

    original = capability_projection("route.python")
    assert original is not None
    implemented = original.model_copy(update={
        "release_state": "implemented", "public_release": "implemented",
        "public_course_admissible": True, "source_coverage": "implemented", "lesson_generation": "implemented",
        "practice_generation": "implemented", "execution": "implemented",
    })
    monkeypatch.setattr(module, "capability_projection", lambda _id: implemented)
    draft = plan()
    report = PlanCoveragePreflightService(FakeFacts(projection_override=implemented)).evaluate(
        draft, (requirement(capabilities=("lesson", "practice")),), expected_plan_hash=draft.content_hash,
    )
    assert report.nodes[0].status == "partial"
    assert report.nodes[0].missing_capabilities == ("practice",)
    assert "PUBLISHED_ITEM_MISSING" in report.nodes[0].reason_codes


def test_postgres_fact_reader_uses_exact_selector_without_writes() -> None:
    req = requirement()
    observed: list[object] = []

    class PointerConnection:
        def execute(self, sql: str, args: object) -> PointerConnection:
            assert sql.startswith("SELECT")
            assert args == ("route.python",)
            return self

        def fetchone(self) -> dict[str, object]:
            return {"generation": 1, "corpus_version_id": CORPUS_ID}

    def retrieve(_conn: Connection[dict[str, object]], request: object) -> GroundingRetrievalResultV2:
        observed.append(request)
        from app.services.grounding.retrieval_contracts import GroundingRetrievalRequest
        assert isinstance(request, GroundingRetrievalRequest)
        assert request.corpus_selector.expected_generation == 1
        assert request.corpus_selector.expected_summary_hash == SUMMARY
        result = unavailable_report(request, "CORPUS_MISSING")
        return GroundingRetrievalResultV2(
            request_hash=result.request_hash, plan=None, evidence=(),
            coverage=result, result_hash=stable_hash((result.request_hash, result.report_hash)),
        )

    reader = PostgresPlanFactReader(cast(Connection[dict[str, object]], PointerConnection()), retrieve=retrieve)
    facts = reader.read(req, query_text="Python concepts", item_knowledge_key=None,
                        item_capabilities=("python",))
    assert facts.coverage.status == "unavailable"
    assert len(observed) == 1


def test_unavailable_report_is_not_success() -> None:
    from app.services.grounding.retrieval_contracts import GroundingRetrievalRequest, ActiveCorpusSelector
    req = requirement()
    retrieval = GroundingRetrievalRequest(
        subject_id=req.subject_id, subject_version=req.subject_version,
        corpus_selector=ActiveCorpusSelector(expected_generation=1, expected_summary_hash=SUMMARY),
        query_text="Python", required_facets=req.required_facets, stage="plan_preflight",
    )
    assert unavailable_report(retrieval, "CORPUS_MISSING").status == "unavailable"


def test_tampered_report_status_hash_and_core_actions_fail_closed() -> None:
    draft = plan()
    report = PlanCoveragePreflightService(FakeFacts(status="partial")).evaluate(
        draft, (requirement(),), expected_plan_hash=draft.content_hash,
    )
    builder = PlanRepairProposalBuilder()
    with pytest.raises(PlanPreflightConflict, match="report hash changed"):
        builder.build(draft, report.model_copy(update={"activation_blocked": False}))
    with pytest.raises(PlanPreflightConflict, match="report hash changed"):
        builder.build(draft, report.model_copy(update={"status": "supported"}))
    forged = report.nodes[0].model_copy(update={"allowed_actions": ("delete_optional_node",)})
    with pytest.raises(PlanPreflightConflict, match="report hash changed"):
        builder.build(draft, report.model_copy(update={"nodes": (forged,)}))


def test_lc_overview_draft_cannot_rebind_to_plain_python() -> None:
    draft = plan(key="lc-overview")
    with pytest.raises(PlanPreflightConflict, match="legacy ecosystem mapping"):
        PlanCoveragePreflightService(FakeFacts()).evaluate(
            draft, (requirement(key="lc-overview", subject="route.python"),),
            expected_plan_hash=draft.content_hash,
        )


def test_future_public_supported_requires_published_item_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.learning.plan_coverage as module

    original = capability_projection("route.python")
    assert original is not None
    implemented = original.model_copy(update={
        "release_state": "implemented", "public_release": "implemented",
        "public_course_admissible": True, "source_coverage": "implemented",
        "lesson_generation": "implemented", "practice_generation": "implemented",
    })
    monkeypatch.setattr(module, "capability_projection", lambda _id: implemented)
    draft = plan(catalog="python.fundamentals")
    report = PlanCoveragePreflightService(FakeFacts(
        handles=("published-item-handle",), projection_override=implemented,
    )).evaluate(draft, (requirement(),), expected_plan_hash=draft.content_hash)
    assert report.status == "supported" and not report.activation_blocked
    assert report.nodes[0].published_item_handles == ("published-item-handle",)
    assert not PlanRepairProposalBuilder().build(draft, report).node_diffs


def test_published_exercise_is_counted_by_real_fact_reader() -> None:
    from types import SimpleNamespace
    from app.services.grounding.retrieval_contracts import GroundingRetrievalRequest

    req = requirement()

    class PointerConnection:
        def execute(self, sql: str, args: object) -> PointerConnection:
            assert sql.startswith("SELECT")
            return self

        def fetchone(self) -> None:
            return None

    class PublishedItems:
        def published_candidates(self, **kwargs: object) -> tuple[object, ...]:
            assert kwargs["knowledge_key"] == "python.fundamentals"
            assert kwargs["language_id"] == "python"
            assert kwargs["available_capabilities"] == ("python.variables",)
            return (SimpleNamespace(handle="item-1", purpose="exercise"),)

    def retrieve(_conn: Connection[dict[str, object]], request: GroundingRetrievalRequest) -> GroundingRetrievalResultV2:
        result = unavailable_report(request, "CORPUS_MISSING")
        return GroundingRetrievalResultV2(
            request_hash=result.request_hash, plan=None, evidence=(),
            coverage=result, result_hash=stable_hash((result.request_hash, result.report_hash)),
        )

    reader = PostgresPlanFactReader(cast(Connection[dict[str, object]], PointerConnection()), retrieve=retrieve)
    reader._items = cast(PostgresLearningItemBankRepository, PublishedItems())
    facts = reader.read(req, query_text="Python concepts", item_knowledge_key="python.fundamentals",
                        item_capabilities=("python.variables",))
    assert facts.published_item_handles == ("item-1",)
    assert facts.source_generation == 0


def test_shadow_adapter_is_default_off_with_zero_fact_reads() -> None:
    class CountingFacts(FakeFacts):
        reads = 0

        def read(self, req: NodeSourceRequirement, *, query_text: str,
                 item_knowledge_key: str | None,
             item_capabilities: tuple[str, ...]) -> NodeCapabilityFacts:
            self.reads += 1
            return super().read(req, query_text=query_text, item_knowledge_key=item_knowledge_key,
                                item_capabilities=item_capabilities)

    facts = CountingFacts()
    draft = plan()
    preflight = PlanCoveragePreflightService(facts)
    assert PlanCoverageShadowAdapter(preflight).evaluate(
        draft, (requirement(),), expected_plan_hash=draft.content_hash,
    ) is None
    assert facts.reads == 0
    report = PlanCoverageShadowAdapter(preflight, enabled=True).evaluate(
        draft, (requirement(),), expected_plan_hash=draft.content_hash,
    )
    assert report is not None and report.plan_hash == draft.content_hash
    assert facts.reads == 1


def test_required_single_node_module_blocks_even_if_node_optional() -> None:
    initial = plan(core=False)
    module = replace(initial.modules[0], is_core=True, is_skippable=False)
    draft = replace(initial, modules=(module,))
    report = PlanCoveragePreflightService(FakeFacts(status="partial")).evaluate(
        draft, (requirement(),), expected_plan_hash=draft.content_hash,
    )
    assert report.activation_blocked
    assert not report.nodes[0].is_core
    assert report.nodes[0].required_for_activation
    assert report.nodes[0].allowed_actions == ("wait_for_release",)
    proposal = PlanRepairProposalBuilder().build(draft, report)
    assert proposal.state == "blocked"
    assert proposal.node_diffs[0].action == "wait_for_release"


def test_optional_deletions_preserve_nonempty_modules() -> None:
    initial = plan(core=False)
    lone_report = PlanCoveragePreflightService(FakeFacts(status="partial")).evaluate(
        initial, (requirement(),), expected_plan_hash=initial.content_hash,
    )
    assert "delete_optional_node" not in lone_report.nodes[0].allowed_actions
    assert PlanRepairProposalBuilder().build(initial, lone_report).node_diffs[0].action == "defer_subject"

    second = replace(initial.nodes[0], knowledge_key="python-extra", order_index=1)
    module = replace(initial.modules[0], nodes=(initial.nodes[0], second))
    draft = replace(initial, modules=(module,))
    report = PlanCoveragePreflightService(FakeFacts(status="partial")).evaluate(
        draft, (requirement(), requirement(key="python-extra")),
        expected_plan_hash=draft.content_hash,
    )
    proposal = PlanRepairProposalBuilder().build(draft, report)
    assert tuple(diff.action for diff in proposal.node_diffs) == (
        "delete_optional_node", "defer_subject",
    )
    assert proposal.node_diffs[0].after_required_assessments is None
    assert proposal.node_diffs[1].after_required_assessments == ("lesson", "practice")


def test_required_multi_node_module_without_core_markers_has_blocked_anchor() -> None:
    initial = plan(core=False)
    second = replace(initial.nodes[0], knowledge_key="python-extra", order_index=1)
    module = replace(initial.modules[0], is_core=False, is_skippable=False,
                     nodes=(initial.nodes[0], second))
    draft = replace(initial, modules=(module,))
    report = PlanCoveragePreflightService(FakeFacts(status="partial")).evaluate(
        draft, (requirement(), requirement(key="python-extra")),
        expected_plan_hash=draft.content_hash,
    )
    assert report.activation_blocked
    assert tuple(result.required_for_activation for result in report.nodes) == (True, False)
    assert tuple(diff.action for diff in PlanRepairProposalBuilder().build(draft, report).node_diffs) == (
        "wait_for_release", "delete_optional_node",
    )


def test_downgrade_requires_real_public_lesson_and_exact_assessment_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.learning.plan_coverage as module

    original = capability_projection("route.python")
    assert original is not None
    future = original.model_copy(update={
        "release_state": "implemented", "public_release": "implemented",
        "public_course_admissible": True, "source_coverage": "implemented",
        "lesson_generation": "implemented", "practice_generation": "unavailable",
    })
    monkeypatch.setattr(module, "capability_projection", lambda _id: future)
    draft = plan(core=False, catalog="python.variables")
    requirements = (requirement(),)
    service = PlanCoveragePreflightService(FakeFacts(
        handles=("published-item-handle",), projection_override=future,
    ))
    report = service.evaluate(draft, requirements, expected_plan_hash=draft.content_hash)
    assert report.nodes[0].missing_capabilities == ("practice",)
    proposal = PlanRepairProposalBuilder().build(draft, report)
    diff = proposal.node_diffs[0]
    assert diff.action == "downgrade_assessment"
    assert diff.before_required_assessments == ("lesson", "practice")
    assert diff.after_required_assessments == ("lesson",)
    assert not proposal.activation_allowed

    fixture_report = PlanCoveragePreflightService(FakeFacts(
        handles=("published-item-handle",), projection_override=future, synthetic=True,
    )).evaluate(draft, requirements, expected_plan_hash=draft.content_hash)
    assert "downgrade_assessment" not in fixture_report.nodes[0].allowed_actions
    unreleased = future.model_copy(update={"public_course_admissible": False})
    monkeypatch.setattr(module, "capability_projection", lambda _id: unreleased)
    unreleased_report = PlanCoveragePreflightService(FakeFacts(
        handles=("published-item-handle",), projection_override=unreleased,
    )).evaluate(draft, requirements, expected_plan_hash=draft.content_hash)
    assert "downgrade_assessment" not in unreleased_report.nodes[0].allowed_actions
