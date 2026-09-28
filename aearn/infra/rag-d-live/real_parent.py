"""Opt-in real parent stage. All learner facts below are declared synthetic input.

No source authority, model output or plan row is fabricated. At most two input
turns and eight real HTTP attempts in total; natural failure stays failure.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.harness.contracts import TutorRunStatus, TutorTerminalOutcome
from app.core.config import Settings
from app.db.connection import connect
from app.main import app
import app.routes.tutor as tutor_route
from app.services.grounding.material_contracts_v2 import DraftScope, digest
from app.services.grounding.subject_registry import get_grounding_subject
from app.services.llm.llm_client import OpenAICompatibleClient
from app.services.llm.provider_diagnostics import ProviderDiagnosticStore
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from tests.support.tutor_public_api_support import RecordingTutorDispatcher, action_payload
from protocol import Scope
from control_runtime import _absolute
from review_operator import _private_output
from parent_provenance import VERSION, ParentProvenanceDenied, load_receipts, verify_parent_provenance
from run import CountedClient, Denied, SharedHttpBudget, SqlRequirements, runtime_profile, wall_deadline

LEARNER_FACTS: dict[str, object] = {
    "language_id": "sql", "goal_text": "Learn SQLite SELECT WHERE filtering and LIMIT using existing tables",
    "target_level": "beginner", "weekly_minutes": 240, "experience_level": "beginner",
    "teaching_preferences": ["examples", "practice"],
    "pace_constraints": "Four focused sessions per week, at most 240 minutes total.",
}
LEARNER_REQUEST = (
    "This is a synthetic learner for an internal acceptance run. Please create my initial SQL learning plan. "
    "I already understand basic tables, columns, types and CREATE TABLE. "
    "I am a beginner specifically in querying existing tables with SQLite SELECT WHERE and LIMIT. "
    "Use English explanations, short worked examples and practice on local SQLite. "
    "My complete declared preferences are supplied as planning_facts. Create exactly two modules: "
    "module_1 is a skippable, non-core independent refresher with one non-core sql.schema node "
    "for already-known table/column basics; module_2 is the core learning module with one core "
    "sql.queries node for WHERE row filtering and LIMIT. Both nodes have empty prerequisite_keys: "
    "sql.queries does not depend on the optional refresher. Do not teach schema creation as a core goal. "
    "The exact node keys are pilot identifiers, not claims of published items. Do not assert "
    "main-material or scoring readiness. Use the normal planning Skill/capability flow to "
    "create the draft, not just prose. If clarification is needed, ask normally; do not invent "
    "answers or source readiness."
)
CLARIFICATION = (
    "My declared answers are unchanged and supplied again in planning_facts. I already know basic schema "
    "creation, tables and columns. Only WHERE filtering and LIMIT remain to learn, using existing SQLite "
    "tables. Please use two independent modules: optional skippable non-core sql.schema refresher "
    "and core sql.queries WHERE/LIMIT on existing tables. Neither node has prerequisites. "
    "English examples and practice. There are no other constraints; create the plan if these facts suffice."
)
REVISION_REQUEST = (
    "Please revise the persisted plan using the current material feedback. Preserve every core node, goal, "
    "prerequisite and my 240-minute weekly budget. I explicitly reopen only the pace constraint: "
    "you may adjust pace_summary to reflect real material availability and gaps. Supplementary excerpts "
    "are not a complete main textbook or scoring evidence."
)


def pilot_nodes(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the two independent pilot modules without repairing model output."""
    modules = plan.get("modules")
    if not isinstance(modules, list) or len(modules) != 2 or any(not isinstance(m, dict) for m in modules):
        raise Denied("PARENT_PILOT_SHAPE_DENIED")
    refresher, core = modules
    schema_nodes, query_nodes = refresher.get("nodes"), core.get("nodes")
    if (refresher.get("is_core") is not False or refresher.get("is_skippable") is not True
            or core.get("is_core") is not True or core.get("is_skippable") is not False
            or not isinstance(schema_nodes, list) or len(schema_nodes) != 1
            or not isinstance(query_nodes, list) or len(query_nodes) != 1
            or not isinstance(schema_nodes[0], dict) or not isinstance(query_nodes[0], dict)):
        raise Denied("PARENT_PILOT_SHAPE_DENIED")
    schema, queries = schema_nodes[0], query_nodes[0]
    if (schema.get("knowledge_key") != "sql.schema" or schema.get("is_core") is not False
            or schema.get("prerequisite_keys") != []
            or queries.get("knowledge_key") != "sql.queries" or queries.get("is_core") is not True
            or queries.get("prerequisite_keys") != []):
        raise Denied("PARENT_PILOT_SHAPE_DENIED")
    return {"sql.schema": schema, "sql.queries": queries}

def drive_parent(*, accept: Callable[..., dict[str, Any]], dispatch: Callable[..., Any],
                 find_draft: Callable[[dict[str, Any]], dict[str, Any] | None],
                 runs: list[dict[str, object]]) -> dict[str, Any]:
    """Small bounded driver; fake callbacks are for offline tests only."""
    for content in (LEARNER_REQUEST, CLARIFICATION):
        accepted = accept(content=content, planning_facts=LEARNER_FACTS)
        coordinate = {"run_id": str(accepted["run_id"]), "input_revision": int(accepted["input_revision"])}
        if coordinate in runs:
            raise Denied("PARENT_INPUT_REPLAY")
        runs.append(coordinate)
        outcome = dispatch(run_id=coordinate["run_id"])
        draft = find_draft(coordinate)
        if draft is not None:
            if (outcome.terminal_outcome is not TutorTerminalOutcome.COMPLETED
                    or outcome.capability_call_count < 1):
                raise Denied("PARENT_RUN_INCOMPLETE")
            return draft
        if (outcome.terminal_outcome not in (None, TutorTerminalOutcome.COMPLETED)
                or outcome.status not in (TutorRunStatus.COMPLETED, TutorRunStatus.WAITING_FOR_INPUT)):
            raise Denied("PARENT_PROVIDER_STAGE_FAILED")
    raise Denied("PARENT_NOT_PERSISTED_AFTER_TWO_INPUTS")


def prepare_real(*, config: dict[str, Any], settings: Settings,
                 provenance_out: str, wall_seconds: int, max_http: int = 8,
                 profile: str = "formal", prior_http_attempts: int = 0,
                 cumulative_http_cap: int = 8) -> dict[str, object]:
    if (not 1 <= max_http <= 8 or type(prior_http_attempts) is not int or prior_http_attempts < 0
            or type(cumulative_http_cap) is not int or prior_http_attempts + max_http > cumulative_http_cap):
        raise Denied("MODEL_BOUND_DENIED")
    source_scope = Scope.from_wire(config["scope"])
    subject = get_grounding_subject("route.sql")
    if (source_scope.subject_id != "route.sql" or source_scope.facets != ("queries",)
            or source_scope.url != "https://www.sqlite.org/lang_select.html"
            or subject is None or subject.version_policy != "operator_locked"
            or not {"queries", "schema"} <= set(subject.required_facets)):
        raise Denied("PARENT_SOURCE_SCOPE_DENIED")
    requirements = SqlRequirements(source_scope.subject_id, source_scope.subject_version)
    path = _private_output(_absolute(provenance_out))
    counted = CountedClient(OpenAICompatibleClient(
        settings, max_http_attempts=1, diagnostic_store=ProviderDiagnosticStore.from_settings(settings)), max_http)
    budget = SharedHttpBudget(settings, max_http)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    audit: dict[str, Any] = {
        "format": VERSION, "status": "failed", "stage": "api_setup",
        "database_name": config["database_name"], "subject_id": source_scope.subject_id,
        "subject_version": source_scope.subject_version, "runs": [],
        "provider_type": settings.llm_provider_type, "model": counted.model,
        "learner_request_sha256": digest({"request": LEARNER_REQUEST, "facts": LEARNER_FACTS}),
        "phase_http_cap": max_http, "prior_http_attempts": prior_http_attempts,
        "cumulative_http_cap": cumulative_http_cap, "profile": profile,
        "runtime_profile": runtime_profile(settings), "wall_seconds": wall_seconds,
    }
    previous = (tutor_route.build_tutor_run_dispatcher, tutor_route.get_settings)
    # Defer only route dispatch; no provider decision is substituted.
    tutor_route.build_tutor_run_dispatcher = lambda _: RecordingTutorDispatcher()
    tutor_route.get_settings = lambda: settings
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            try:
                with TestClient(app) as client, budget.enforce(), wall_deadline(wall_seconds):
                    user_response = client.post("/api/users", json={"display_name": "Declared synthetic SQL learner"})
                    if user_response.status_code != 201:
                        raise Denied("PARENT_USER_API_DENIED")
                    user_id = str(user_response.json()["user"]["id"])
                    cutover = client.get("/api/harness/cutover", params={"user_id": user_id})
                    capability = client.get("/api/tutor/capabilities/thread-turn-v2", params={"user_id": user_id})
                    if (cutover.status_code != 200 or cutover.json().get("state") != "verified"
                            or capability.status_code != 200 or capability.json().get("effective_enabled") is not True):
                        raise Denied("PARENT_RUNTIME_GATE_NOT_READY")
                    response = client.post("/api/learning-plan-sessions", json={
                        "user_id": user_id, "client_action_id": "rag-d-real-parent-" + uuid4().hex,
                        "preferred_language_id": "sql",
                    })
                    if response.status_code not in {200, 201}:
                        raise Denied("PARENT_SESSION_API_DENIED")
                    session = response.json()["session"]
                    session_id, conversation_id = str(session["session_id"]), str(session["conversation_id"])
                    audit.update(user_id=user_id, session_id=session_id, conversation_id=conversation_id)

                    def accept(**input_fields: Any) -> dict[str, Any]:
                        accepted = client.post(f"/api/tutor/conversations/{conversation_id}/inputs", json=action_payload(
                            user_id, "rag-d-real-input-" + uuid4().hex, **input_fields,
                            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"}))
                        if accepted.status_code != 202:
                            raise Denied("PARENT_INPUT_API_DENIED")
                        return accepted.json()

                    def find_draft(run: dict[str, Any]) -> dict[str, Any] | None:
                        with connect() as conn:
                            return conn.execute(
                                "SELECT * FROM tutor_learning_plan_drafts WHERE user_id=%s AND session_id=%s "
                                "AND source_run_id=%s AND source_input_revision=%s",
                                (user_id, session_id, run["run_id"], run["input_revision"])).fetchone()

                    dispatcher = TutorInteractiveRunDispatcher(settings=settings, provider_factory=lambda _: PrimaryTutorProviderGateway(
                        settings=settings, client=counted,
                        max_output_tokens=settings.tutor_decision_max_output_tokens))
                    audit["stage"] = "real_parent_dispatch"
                    parent = drive_parent(accept=accept, dispatch=lambda **kw: dispatcher.dispatch(user_id=user_id, **kw),
                                          find_draft=find_draft, runs=audit["runs"])
                    audit["stage"] = "parent_scope_and_receipts"
                    draft_scope = DraftScope(user_id=user_id, conversation_id=conversation_id, session_id=session_id,
                        draft_id=str(parent["id"]), draft_version=parent["draft_version"], content_hash=parent["content_hash"],
                        source_run_id=str(parent["source_run_id"]), source_input_revision=parent["source_input_revision"])
                    nodes = pilot_nodes(parent["plan_json"])
                    requirements.resolve(draft_scope, parent["profile_json"], nodes)
                    with connect() as conn:
                        receipts = load_receipts(conn, user_id=user_id, conversation_id=conversation_id, runs=audit["runs"])
                        audit.update(status="parent_persisted", parent_draft_id=str(parent["id"]),
                            parent_content_hash=parent["content_hash"], source_run_id=str(parent["source_run_id"]),
                            source_input_revision=parent["source_input_revision"], provider_receipts=receipts,
                            model_http_attempts=budget.count, client_calls=counted.count, usage_per_call=counted.usage,
                            response_models=counted.response_models)
                        try:
                            proof = verify_parent_provenance(conn, audit=audit, parent=parent, database_name=config["database_name"],
                                conversation_id=conversation_id, subject_id=source_scope.subject_id,
                                subject_version=source_scope.subject_version,
                                expected_runtime_profile=runtime_profile(settings), profile=profile,
                                prior_http_attempts=prior_http_attempts, cumulative_http_cap=cumulative_http_cap)
                        except ParentProvenanceDenied as exc:
                            audit["status"] = "failed"
                            raise Denied(str(exc)) from None
                    audit["stage"] = "target_input"
                    target = accept(content=REVISION_REQUEST, reopen_fact_fields=["pace_constraints"])
                    audit["stage"] = "ready_for_real_successor"
                    return {"status": "real_parent_and_pending_target", **proof, "user_id": user_id,
                            "session_id": session_id, "conversation_id": conversation_id,
                            "parent_draft_id": str(parent["id"]), "parent_provenance": str(path),
                            "target_run_id": str(target["run_id"]), "target_input_revision": target["input_revision"]}
            finally:
                audit.update(model_http_attempts=budget.count, client_calls=counted.count, usage_per_call=counted.usage,
                             unknown_usage_count=budget.count - sum(v is not None for v in counted.usage),
                             response_models=counted.response_models)
                output.write(json.dumps(audit, sort_keys=True, separators=(",", ":")))
                output.flush()
                os.fsync(output.fileno())
                print(json.dumps({"phase": "real_parent", "stage": audit["stage"], "status": audit["status"],
                                  "model_http_attempts": budget.count, "usage_per_call": counted.usage,
                                  "phase_http_cap": max_http, "prior_http_attempts": prior_http_attempts,
                                  "cumulative_http_cap": cumulative_http_cap,
                                  "profile": profile, "runtime_profile": runtime_profile(settings)}, sort_keys=True))
    finally:
        tutor_route.build_tutor_run_dispatcher, tutor_route.get_settings = previous
