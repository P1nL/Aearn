"""Guarded synthetic end-to-end D planning chain; never a live-source acceptance."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import (
    TutorCapabilityRequest, TutorContextSection, TutorDecision, TutorProviderResult,
    TutorProviderAttemptReceipt, TutorProviderAttemptOutcome,
    TutorSkillReference, TutorTerminalOutcome, payload_fields_from_mapping,
)
from app.core.config import Settings, get_settings
from app.db.connection import connect
from app.services.grounding.autonomous.contracts import (
    LearningMaterialDemand, RagEvidenceBinding, SubjectScope,
)
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_binding_repository import (
    PostgresMaterialBindingRepository, goal_hash_for_node,
)
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceBindingV2,
    EvidenceCoordinate, MaterialSelectionEntry, MaterialSelectionResult,
    NodeMaterialRequirement, apply_material_dependencies, digest,
)
from app.services.learning.material_planning_composition import build_internal_material_planning_dispatcher
from app.services.learning.material_selection import PostgresMaterialPlanningConsumer
from app.services.learning.material_semantics import (
    MaterialReviewReceipt, ReviewReason, ReviewVerdict, StrictReviewVerdict,
)
from app.services.llm.contracts import LLMUsage
from app.services.learning.plan_repository import PostgresLearningPlanSessionRepository
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from tests.learning.test_learning_plan_sessions import _capability_input, _create_session
from tests.support.tutor_public_api_support import action_payload, create_tutor_user, RecordingTutorDispatcher

pytest_plugins = ("tests.support.tutor_public_api_support",)


@pytest.fixture
def d_database_guard() -> None:
    guarded = os.getenv("AEARN_RAG_D_TEST_DATABASE_URL")
    if not guarded:
        pytest.skip("D integration requires explicitly provisioned isolated PostgreSQL")
    with psycopg.connect(guarded, connect_timeout=2) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
    assert name.startswith("aearn_rag260_c_d_")
    with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == name


class ImmutableNodePolicy:
    """Test-only approved server mapping. No node/model guesses a source version."""

    def resolve(self, draft: DraftScope, profile: dict[str, object],
                nodes: dict[str, dict[str, object]]) -> tuple[NodeMaterialRequirement, ...]:
        assert profile["language_id"] == "python"
        output: list[NodeMaterialRequirement] = []
        for key, node in nodes.items():
            for purpose, facets in (("main_teaching", ("syntax",)),
                                    ("supplementary_explanation", ("functions",))):
                scope = SubjectScope(subject_id="route.python", subject_version="v1", facets=facets)
                demand = LearningMaterialDemand(
                    scope=scope, demand_hash=digest((draft.draft_id, key, purpose, facets)),
                    plan_ref=f"draft.{draft.draft_id}", node_ref=f"node.{key}",
                    draft_revision=draft.draft_version, purpose=purpose,
                    reading_level="beginner", language="zh",
                )
                output.append(NodeMaterialRequirement(
                    node_id=key, goal_hash=goal_hash_for_node(node),
                    prerequisites=tuple(node["prerequisite_keys"]), demand=demand,
                ))
        return tuple(output)


class SyntheticEvidence(EvidenceSelection):
    """Typed receipt fixture only; does not claim any C current source is ready."""

    def __init__(self, conn: Any, *, ready: bool = False) -> None:
        self.conn = conn
        self.enabled = True
        self.selections = PostgresMaterialBindingRepository(conn)
        self.request_for = lambda _req: None
        self.ready = ready

    def _receipt(self, kind: str, digest_value: str, draft: DraftScope,
                 purposes: tuple[str, ...]) -> CurrentMaterialAuthorizationReceipt:
        now: datetime = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        return CurrentMaterialAuthorizationReceipt(
            kind=kind, object_digest=digest_value, draft=draft,
            purposes=tuple(sorted(set(purposes))), authorization_digest="b" * 64,
            checked_at=now,
        )

    def resolve_evidence(self, draft: DraftScope,
                         requirements: tuple[NodeMaterialRequirement, ...]) -> MaterialSelectionResult:
        entries: list[MaterialSelectionEntry] = []
        for requirement in requirements:
            key = dict(node_id=requirement.node_id, goal_hash=requirement.goal_hash,
                       purpose=requirement.demand.purpose)
            if not self.ready:
                entries.append(MaterialSelectionEntry(**key, status="gap", gaps=("missing_material",)))
                continue
            demand = requirement.demand
            binding = RagEvidenceBinding(
                scope=demand.scope, demand_hash=demand.demand_hash, purpose=demand.purpose,
                source_handle="source.synthetic", document_handle="doc.synthetic",
                document_revision="v1", document_hash="c" * 64,
                admission_receipt_id="admission.synthetic",
            )
            coordinate = EvidenceCoordinate(
                binding=binding, subject_id=demand.scope.subject_id,
                corpus_version_id=str(uuid4()), active_generation=1,
                summary_hash="d" * 64, validation_hash="e" * 64,
                registry_digest="f" * 64, source_review_id=str(uuid4()),
                source_policy_id="synthetic.policy", source_policy_generation=1,
                chunk_id="chunk.synthetic", chunk_hash="1" * 64,
                approved_excerpt_hash="2" * 64, retrieval_hash="3" * 64,
                coverage_hash="4" * 64,
            )
            entries.append(MaterialSelectionEntry(**key, status="ready",
                covered_facets=demand.scope.facets, evidence=(coordinate,)))
        payload = dict(handle=f"selection.{uuid4().hex}", draft=draft,
                       requirements=requirements,
                       entries=apply_material_dependencies(requirements, tuple(entries)))
        raw = MaterialSelectionResult.model_construct(**payload, selection_digest="0" * 64)
        return MaterialSelectionResult(**payload, selection_digest=digest(raw.payload()))

    def authorize_selection(self, conn: Any,
                            selection: MaterialSelectionResult) -> CurrentMaterialAuthorizationReceipt:
        assert conn is self.conn
        return self._receipt("selection", selection.selection_digest, selection.draft,
                             tuple(r.demand.purpose for r in selection.requirements))

    def authorize_binding(self, conn: Any,
                          binding: EvidenceBindingV2) -> CurrentMaterialAuthorizationReceipt:
        assert conn is self.conn
        return self._receipt("binding", binding.binding_digest, binding.draft,
                             (binding.purpose,))


class ConsistentSyntheticReviewer:
    """Deterministic test port; never evidence of a real semantic judgment."""

    def review(self, request: Any) -> MaterialReviewReceipt:
        request.assert_binding()
        return MaterialReviewReceipt(
            request.binding_hash,
            StrictReviewVerdict(verdict=ReviewVerdict.CONSISTENT, reason_code=ReviewReason.SUPPORTED),
            "synthetic-reviewer", LLMUsage(input_tokens=7, output_tokens=2),
        )


@dataclass
class FeedbackProvider:
    calls: list[str] = field(default_factory=list)
    seen_feedback: list[str] = field(default_factory=list)
    seen_parent_parts: dict[int, dict[str, Any]] = field(default_factory=dict)

    def decide(self, *, run: Any, context: Any, thinking_sink: Any = None) -> TutorProviderResult:
        del thinking_sink
        items = [item.content for item in context.items if "material_planning_feedback" in item.content]
        for item in context.items:
            if "material_parent_snapshot" in item.content:
                part = json.loads(item.content)
                self.seen_parent_parts[part["part"]] = part
        if items:
            self.seen_feedback.extend(items)
        self.calls.append(run.run_id)
        if len(self.calls) == 1:
            eligible = [skill for item in context.items
                        if item.section is TutorContextSection.SYSTEM
                        and item.source_id == "catalog:eligible-skills"
                        for skill in json.loads(item.content)["skills"]
                        if skill["id"] == "tutor.learning-plan-draft"]
            assert len(eligible) == 1
            return TutorProviderResult(decision=TutorDecision(
                skill_references=(TutorSkillReference("tutor.learning-plan-draft", eligible[0]["version"]),),
            ))
        if len(self.calls) > 2:
            return TutorProviderResult(decision=TutorDecision(terminal_outcome=TutorTerminalOutcome.COMPLETED))
        draft = self.draft_input().model_dump(exclude_none=True)
        profile = json.loads(draft["profile_json"])
        # Observable safe model revision driven by the gap, while node goals and
        # prerequisite map remain unchanged.
        if items:
            profile["pace_summary"] = (
                "Material gap: proceed cautiously with verified examples."
                if "missing_material" in " ".join(items)
                else "Use the admitted exact material for focused practice."
            )
            draft["profile_json"] = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
        from app.services.tutor.provider_gateway import _selected_plan_draft_version
        capability_version = _selected_plan_draft_version(context)
        return TutorProviderResult(decision=TutorDecision(
            capability_requests=(TutorCapabilityRequest(
                request_id="material-successor", capability_id="learning.plan.draft",
                capability_version=capability_version,
                arguments=payload_fields_from_mapping(draft, capability_id="learning.plan.draft",
                                                     capability_version=capability_version),
            ),),
        ), attempts=(TutorProviderAttemptReceipt(
            attempt_index=1, outcome=TutorProviderAttemptOutcome.ACCEPTED,
            provider_type="synthetic", protocol="responses", model="synthetic-plan-provider",
        ),))

    def draft_input(self) -> Any:
        return _capability_input()


class SqlFeedbackProvider(FeedbackProvider):
    def draft_input(self) -> Any:
        original = _capability_input().model_dump(exclude_none=True)
        profile = json.loads(original["profile_json"])
        profile["language_id"] = "sql"
        profile["goal_text"] = "Learn SQL queries and database schemas"
        original["profile_json"] = json.dumps(profile)
        for index, (key, title) in enumerate((("sql.queries", "Queries"),
                                              ("sql.schema", "Schema")), 1):
            module = json.loads(original[f"module_{index}"])
            node = module["nodes"][0]
            node["knowledge_key"] = key
            node["title"] = title
            node["required_capabilities"] = ["sql"]
            node["prerequisite_keys"] = ["sql.queries"] if index == 2 else []
            original[f"module_{index}"] = json.dumps(module)
        from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
        return LearningPlanDraftCapabilityInput.model_validate(original)


class SqlApprovedNodePolicy:
    def resolve(self, draft: DraftScope, profile: dict[str, object],
                nodes: dict[str, dict[str, object]]) -> tuple[NodeMaterialRequirement, ...]:
        assert profile["language_id"] == "sql"
        results: list[NodeMaterialRequirement] = []
        for key, node in nodes.items():
            scope = SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",))
            demand = LearningMaterialDemand(
                scope=scope, demand_hash=digest((draft.draft_id, key, "main_teaching")),
                plan_ref=f"draft.{draft.draft_id}", node_ref=f"node.{key}",
                draft_revision=draft.draft_version, purpose="main_teaching",
                reading_level="beginner", language="en",
            )
            results.append(NodeMaterialRequirement(node_id=key, goal_hash=goal_hash_for_node(node),
                prerequisites=tuple(node["prerequisite_keys"]), demand=demand))
        return tuple(results)


def test_dispatcher_context_gateway_capability_and_successor_selection(
    d_database_guard: None, monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient, tutor_api_settings: Settings,
) -> None:
    # No real source, provider, search or public release. The D tables and plan
    # repository are real and isolated; C-current contract is a synthetic port.
    # The deterministic fake must declare enough finite input capacity for the
    # complete published planning Skill. Keep production defaults and the
    # required-context overflow gate unchanged.
    fake_provider_settings = tutor_api_settings.model_copy(update={
        "tutor_default_context_window_tokens": 16_384,
        "tutor_context_max_dynamic_target_tokens": 12_000,
    })
    monkeypatch.setattr(tutor_route, "get_settings", lambda: fake_provider_settings)
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher",
                        lambda _settings: RecordingTutorDispatcher())
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "d-parent")
    conversation_id = str(session["conversation_id"])
    def accept(action: str) -> dict[str, object]:
        response = tutor_client.post(f"/api/tutor/conversations/{conversation_id}/inputs",
            json=action_payload(user_id, action, content="Please revise my plan.",
                learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"}))
        assert response.status_code == 202
        return response.json()
    first = accept("d-first")
    # Complete the first run through the ordinary trusted runtime, not a SQL
    # terminal flag or a direct capability append. This releases singleton busy
    # ownership and permits the public route to issue a genuinely new run.
    initial_provider = FeedbackProvider()
    initial_result = TutorInteractiveRunDispatcher(
        settings=fake_provider_settings, provider_factory=lambda _settings: initial_provider,
    ).dispatch(user_id=user_id, run_id=str(first["run_id"]))
    assert initial_result.capability_call_count == 1
    assert initial_result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connect() as conn:
        initial = conn.execute(
            "SELECT id::text AS id,draft_version,content_hash FROM tutor_learning_plan_drafts "
            "WHERE user_id=%s AND source_run_id=%s", (user_id, str(first["run_id"])),
        ).fetchone()
        assert initial is not None
        parent = SimpleNamespace(draft_id=initial["id"],
                                 draft_version=initial["draft_version"],
                                 content_hash=initial["content_hash"])
    second = accept("d-second")
    assert second["run_id"] != first["run_id"]
    with connect() as conn:
        draft = PostgresLearningPlanSessionRepository(conn).draft_for_session(
            user_id=user_id, session_id=str(session["session_id"]), draft_id=parent.draft_id)
        scope = DraftScope(user_id=user_id, conversation_id=conversation_id,
            session_id=str(session["session_id"]), draft_id=parent.draft_id,
            draft_version=parent.draft_version, content_hash=parent.content_hash,
            source_run_id=str(first["run_id"]), source_input_revision=int(first["input_revision"]))
        assert draft["content_hash"] == scope.content_hash
        version = int(conn.execute("SELECT version FROM tutor_learning_plan_sessions WHERE id=%s",
                                   (scope.session_id,)).fetchone()["version"])
        authority = SyntheticEvidence(conn)
        consumer = PostgresMaterialPlanningConsumer(conn, authority=authority,
                                                    requirements=ImmutableNodePolicy())
        ref = consumer.assign_parent_feedback(parent=scope, target_run_id=str(second["run_id"]),
            target_input_revision=int(second["input_revision"]), expected_session_version=version)
        conn.commit()
    assert ref.target_run_id == second["run_id"]
    # New connection proves the exact assignment survives restart. The same
    # target pair reuses the frozen parent selection; a different run is denied.
    with connect() as conn:
        authority = SyntheticEvidence(conn)
        consumer = PostgresMaterialPlanningConsumer(conn, authority=authority,
                                                    requirements=ImmutableNodePolicy())
        snapshot = PostgresTutorRepository(conn).load_snapshot(
            user_id=user_id, run_id=str(second["run_id"]))
        assert snapshot is not None
        current = PostgresLearningPlanSessionRepository(conn).active_session_for_run(
            user_id=user_id, run_id=snapshot.run_id, input_revision=snapshot.input_revision)
        safe = consumer.feedback_for_context(snapshot, current)
        assert safe is not None and safe["entries"][0]["status"] == "gap"
        assert consumer.assign_parent_feedback(parent=scope, target_run_id=snapshot.run_id,
            target_input_revision=snapshot.input_revision,
            expected_session_version=version).assignment_digest == ref.assignment_digest
        with pytest.raises(ValueError):
            consumer.assign_parent_feedback(parent=scope, target_run_id=scope.source_run_id,
                target_input_revision=scope.source_input_revision,
                expected_session_version=version)
    provider = FeedbackProvider()
    # The internal composition is dual-gated and injects the same connection
    # into context + capability. Test evidence factory returns synthetic C port.
    dispatcher = build_internal_material_planning_dispatcher(
        fake_provider_settings.model_copy(update={"rag_evidence_consumer_enabled": True}),
        server_opt_in=True, requirements=ImmutableNodePolicy(),
        evidence_factory=lambda conn: SyntheticEvidence(conn, ready=True),
        provider_factory=lambda _settings: provider,
        semantic_reviewer=ConsistentSyntheticReviewer(),
    )
    result = dispatcher.dispatch(user_id=user_id, run_id=str(second["run_id"]))
    assert provider.seen_feedback and "missing_material" in provider.seen_feedback[0]
    visible_units = [unit for part in provider.seen_parent_parts.values() for unit in part["items"]]
    assert [unit["profile"] for unit in visible_units if "profile" in unit] == [draft["profile_json"]]
    expected_nodes = [node for module in draft["plan_json"]["modules"] for node in module["nodes"]]
    assert [unit["node"] for unit in visible_units if "node" in unit] == expected_nodes
    assert all(unit["goal_hash"] == goal_hash_for_node(unit["node"])
               for unit in visible_units if "node" in unit)
    assert result.capability_call_count == 1
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connect() as conn:
        rows = conn.execute("SELECT draft_version,predecessor_draft_id,content_hash FROM tutor_learning_plan_drafts "
                            "WHERE session_id=%s ORDER BY draft_version", (scope.session_id,)).fetchall()
        assert len(rows) == 2 and str(rows[1]["predecessor_draft_id"]) == parent.draft_id
        assert rows[1]["content_hash"] != parent.content_hash
        assert conn.execute("SELECT count(*) AS n FROM rag_material_selections WHERE user_id=%s",
                            (user_id,)).fetchone()["n"] == 2
        assert str(conn.execute("SELECT target_run_id FROM rag_material_selections WHERE handle=%s",
                            (ref.selection_handle,)).fetchone()["target_run_id"]) == second["run_id"]
        assert conn.execute("SELECT count(*) AS n FROM rag_plan_material_bindings WHERE user_id=%s",
                            (user_id,)).fetchone()["n"] == 4


def test_real_c_facade_reaches_successor_exact_binding_through_dispatcher(
    d_database_guard: None, monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient, tutor_api_settings: Settings,
) -> None:
    """C corpus/review/current resolver is real; quality, actor and provider are fixtures."""
    from app.services.grounding.autonomous.corpus_governance import (
        CorpusGovernance, PostgresCorpusAuthority,
    )
    from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
    from tests.grounding.test_rag_d_evidence import setup_ready

    # setup_ready is a synthetic registered C document and corpus, never a GET.
    # It must commit to become visible to the dispatcher's separate connection.
    fake_provider_settings = tutor_api_settings.model_copy(update={
        "tutor_default_context_window_tokens": 16_384,
        "tutor_context_max_dynamic_target_tokens": 12_000,
    })
    monkeypatch.setattr(tutor_route, "get_settings", lambda: fake_provider_settings)
    with connect() as conn:
        seeded, _unrelated_scope, _req, _policy, candidate = setup_ready(conn)
        verifier = seeded.governance.source_reviews.verifier
        gates = seeded.gates
        actor = seeded.authority_resolver
        request_for = seeded.request_for
        suffix = _policy.removeprefix("policy.")
        conn.commit()

    def c_factory(conn: Any) -> EvidenceSelection:
        governance = CorpusGovernance(
            conn, authority=PostgresCorpusAuthority(),
            source_reviews=SourceReviewRepository(conn, verifier=verifier),
            isolated_operator_enabled=True,
        )
        return EvidenceSelection(
            conn, governance=governance, request_for=request_for,
            selections=PostgresMaterialBindingRepository(conn), gates=gates,
            authority_resolver=actor, enabled=True,
        )

    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher",
                        lambda _settings: RecordingTutorDispatcher())
    user_id = str(create_tutor_user(tutor_client)["id"])
    created = tutor_client.post("/api/learning-plan-sessions", json={
        "user_id": user_id, "client_action_id": "d-c-sql-session-" + suffix,
        "preferred_language_id": "sql",
    })
    assert created.status_code in {200, 201}
    session = created.json()["session"]
    conversation_id = str(session["conversation_id"])

    def accept(action: str) -> dict[str, object]:
        response = tutor_client.post(f"/api/tutor/conversations/{conversation_id}/inputs",
            json=action_payload(user_id, action, content="Revise SQL learning plan.",
                learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"}))
        assert response.status_code == 202 and "run_id" in response.json()
        return response.json()

    first = accept("d-c-sql-first-" + suffix)
    first_result = TutorInteractiveRunDispatcher(
        settings=fake_provider_settings, provider_factory=lambda _settings: SqlFeedbackProvider(),
    ).dispatch(user_id=user_id, run_id=str(first["run_id"]))
    assert first_result.capability_call_count == 1
    assert first_result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    second = accept("d-c-sql-second-" + suffix)
    assert first["run_id"] != second["run_id"]

    sql_provider = SqlFeedbackProvider()
    dispatcher = build_internal_material_planning_dispatcher(
        fake_provider_settings.model_copy(update={"rag_evidence_consumer_enabled": True}),
        server_opt_in=True, requirements=SqlApprovedNodePolicy(),
        evidence_factory=c_factory,
        provider_factory=lambda _settings: sql_provider,
        semantic_reviewer=ConsistentSyntheticReviewer(),
    )
    factory = dispatcher._material_consumer_factory
    assert factory is not None
    with connect() as conn:
        parent = conn.execute("SELECT * FROM tutor_learning_plan_drafts "
                              "WHERE user_id=%s AND source_run_id=%s",
                              (user_id, str(first["run_id"]))).fetchone()
        assert parent is not None
        scope = DraftScope(user_id=user_id, conversation_id=conversation_id,
            session_id=str(session["session_id"]), draft_id=str(parent["id"]),
            draft_version=parent["draft_version"], content_hash=parent["content_hash"],
            source_run_id=str(first["run_id"]), source_input_revision=int(first["input_revision"]))
        version = int(conn.execute("SELECT version FROM tutor_learning_plan_sessions WHERE id=%s",
                                   (scope.session_id,)).fetchone()["version"])
        factory(conn).assign_parent_feedback(parent=scope, target_run_id=str(second["run_id"]),
            target_input_revision=int(second["input_revision"]), expected_session_version=version)
        conn.commit()
    outcome = dispatcher.dispatch(user_id=user_id, run_id=str(second["run_id"]))
    assert outcome.capability_call_count == 1
    assert outcome.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert sql_provider.seen_feedback and "source." in sql_provider.seen_feedback[0]
    actual_nodes = [unit["node"] for part in sql_provider.seen_parent_parts.values()
                    for unit in part["items"] if "node" in unit]
    assert actual_nodes == [node for module in parent["plan_json"]["modules"] for node in module["nodes"]]
    with connect() as conn:
        revised = conn.execute("SELECT pace_summary FROM tutor_learning_plan_drafts "
            "WHERE user_id=%s AND source_run_id=%s",
            (user_id, str(second["run_id"]))).fetchone()
        assert revised is not None
        assert revised["pace_summary"] == "Use the admitted exact material for focused practice."
        rows = conn.execute("SELECT b.binding_json FROM rag_plan_material_bindings b "
            "JOIN tutor_learning_plan_drafts d ON d.id=b.draft_id "
            "WHERE d.user_id=%s AND d.source_run_id=%s ORDER BY b.node_id",
            (user_id, str(second["run_id"]))).fetchall()
        assert len(rows) == 2
        for row in rows:
            exact = row["binding_json"]
            assert exact["purpose"] == "main_teaching"
            assert exact["evidence"][0]["binding"]["document_handle"] == f"document.{suffix}"
            assert exact["evidence"][0]["chunk_id"] == f"chunk.{suffix}"
            assert exact["evidence"][0]["corpus_version_id"] == str(candidate.corpus_id)
