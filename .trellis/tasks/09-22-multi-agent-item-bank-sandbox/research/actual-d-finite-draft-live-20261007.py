"""Main-only one real KC planning run through the original parent Harness.

Synthetic learner INPUT is explicit. Provider decisions/drafts/receipts are real.
No source proof, current teaching, confirmation, scoring or readiness is invented.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
from typing import Any, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
RESEARCH = Path(__file__).resolve().parent
TARGET = "python-kc-binding-v1"
NODE = "python.bind"
OUTPUT = ROOT / ".runtime/e-actual-d-finite-draft-20261007"


class Pending(ValueError):
    pass


def require(value: object, reason: str) -> None:
    if not value:
        raise Pending(reason)


def configure_imports() -> None:
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    api = str(ROOT / "aearn/services/api")
    if api not in sys.path:
        sys.path.insert(0, api)


def plan() -> dict[str, Any]:
    configure_imports()
    from app.services.learning.item_supply.finite_course_mapping import finite_node_description
    from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
    from app.services.learning.plan_drafting import CompactPlanModule
    from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput

    target = get_finite_course_target(TARGET)
    module = {"module_key": "m", "title": "Bindings", "nodes": [{"knowledge_key": NODE,
        "title": "Bindings", "description": finite_node_description(TARGET),
        "required_capabilities": list(target.required_capabilities)}]}
    CompactPlanModule.model_validate(module)
    compact = json.dumps(module, ensure_ascii=False, separators=(",", ":"))
    refresher = {"module_key": "r", "title": "Basics", "is_core": False, "is_skippable": True,
        "nodes": [{"knowledge_key": "python.basics", "title": "Basics", "is_core": False,
            "description": "Already-known names and integer literals.",
            "required_capabilities": ["python"]}]}
    CompactPlanModule.model_validate(refresher)
    refresher_compact = json.dumps(refresher, ensure_ascii=False, separators=(",", ":"))
    maximum = next(m.max_length for m in LearningPlanDraftCapabilityInput.model_fields["module_1"].metadata
                   if hasattr(m, "max_length"))
    require(len(compact) <= maximum, "EXACT_FINITE_MODULE_EXCEEDS_ORIGINAL_CAPABILITY_BOUND")
    require(len(refresher_compact) <= maximum, "REFRESHER_EXCEEDS_ORIGINAL_CAPABILITY_BOUND")
    facts = {"language_id": "python", "goal_text": target.goal_text, "target_level": "beginner",
        "weekly_minutes": 60, "experience_level": "beginner", "teaching_preferences": ["examples", "practice"],
        "pace_constraints": "One short session per week, at most 60 minutes."}
    prompt = (
        "Synthetic acceptance learner INPUT; REAL provider draft via normal planning Skill/action. "
        "Facts supplied. Two independent modules, no prerequisites. module_1 optional non-core known-basics refresher: " + refresher_compact +
        " . module_2 ONE core goal, exact description/capabilities (NOT readiness evidence): " + compact +
        " . Compact literal-Unicode JSON, omit defaults, <=360/module. Normal verified action then "
        "turn-completed; never regenerate after verification."
    )
    return {"target_id": TARGET, "node_id": NODE, "language_id": "python", "module": module,
        "module_characters": len(compact), "original_module_bound": maximum, "refresher_module": refresher,
        "refresher_characters": len(refresher_compact), "facts": facts,
        "learner_request": prompt, "input_runs": 1, "max_HTTP_attempts_allowed": 8,
        "monetary_cost": None, "source_proof_created": False, "teaching_selection_created": False}


def load_existing() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    sys.path.insert(0, str(RESEARCH))
    for folder in ("rag-d-live", "rag-c-live", "rag-c-source-control"):
        sys.path.insert(0, str(ROOT / "aearn/infra" / folder))
    parent = importlib.import_module("real_parent")
    source = runpy.run_path(str(RESEARCH / "native-type-live-support-20261006.py"))
    candidate = runpy.run_path(str(RESEARCH / "native-v3-candidate-chain-20261006.py"))
    return parent, source, candidate


def save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)


def validate_finite(parent: dict[str, Any]) -> dict[str, Any]:
    from app.services.learning.contracts import canonical_plan_payload
    from app.services.learning.plan_drafting import draft_artifact_from_row
    artifact = draft_artifact_from_row(parent)
    require(artifact.content_hash == parent["content_hash"], "ORIGINAL_DRAFT_HASH_MISMATCH")
    canonical = cast(dict[str, Any], canonical_plan_payload(artifact.plan))
    modules = canonical["modules"]
    expected = plan()["module"]["nodes"][0]
    require(len(modules) == 2 and all(len(m["nodes"]) == 1 for m in modules), "EXACT_FINITE_COURSE_SHAPE_MISMATCH")
    refresher, core = modules
    known = refresher["nodes"][0]
    require(not refresher["is_core"] and refresher["is_skippable"] and not known["is_core"]
        and known["knowledge_key"] == "python.basics" and not known["prerequisite_keys"], "REFRESHER_SHAPE_MISMATCH")
    node = core["nodes"][0]
    require(core["is_core"] and not core["is_skippable"] and node["is_core"]
        and not node["prerequisite_keys"] and all(node[k] == expected[k] for k in
            ("knowledge_key", "description", "required_capabilities"))
        and artifact.profile.language_id == "python", "EXACT_FINITE_NODE_SEMANTICS_MISMATCH")
    return {"draft_id": str(parent["id"]), "draft_version": int(parent["draft_version"]),
        "source_run_id": str(parent["source_run_id"]), "source_input_revision": int(parent["source_input_revision"]),
        "content_hash": parent["content_hash"], "node_id": NODE, "target_id": TARGET}


def execute(args: argparse.Namespace, prepared: dict[str, Any], output: Path, report: dict[str, Any]) -> None:
    parent, source, candidate = load_existing()
    from psycopg.conninfo import make_conninfo
    from app.core.config import get_settings

    cfg = source["read"](ROOT / ".runtime/item-supply-sandbox-20261001/database.json")
    require(cfg["database"] == source["DB"], "EXACT_ISOLATED_DATABASE_REQUIRED")
    dsn = make_conninfo(host=cfg["host"], port=cfg["port"], dbname=cfg["database"],
                        user=cfg["role"], password=cfg["password"])
    del cfg
    previous_env = {key: os.environ.get(key) for key in
        ("DATABASE_URL", "TUTOR_THREAD_TURN_V2_ENABLED", "TUTOR_CODEX_PLAN_DRAFTING_ENABLED")}
    previous_routes = parent.tutor_route.build_tutor_run_dispatcher, parent.tutor_route.get_settings
    counted = budget = settings = None
    audit: dict[str, Any] = {"format": parent.VERSION, "status": "failed", "stage": "isolated_database",
        "database_name": source["DB"], "subject_id": "route.python", "subject_version": "1.0", "runs": [],
        "profile": "formal", "phase_http_cap": args.max_http, "prior_http_attempts": args.prior_http_attempts,
        "cumulative_http_cap": args.cumulative_http_cap, "monetary_cost": None,
        "declared_synthetic_learner_input": True, "real_provider_required": True}
    try:
        os.environ.update(DATABASE_URL=dsn, TUTOR_THREAD_TURN_V2_ENABLED="true", TUTOR_CODEX_PLAN_DRAFTING_ENABLED="false")
        del dsn
        get_settings.cache_clear()
        with source["connection"]() as conn:
            require(conn.execute("SELECT current_database() AS n").fetchone()["n"] == source["DB"],
                    "EXACT_ISOLATED_DATABASE_REQUIRED")
        # Reuse the existing main provider configuration; no new client/keys/budget owner.
        settings = candidate["settings_for_execute"]().model_copy(update={
            "tutor_thread_turn_v2_enabled": True, "tutor_codex_plan_drafting_enabled": False})
        counted = parent.CountedClient(parent.OpenAICompatibleClient(settings, max_http_attempts=1,
            diagnostic_store=parent.ProviderDiagnosticStore.from_settings(settings)), args.max_http)
        budget = parent.SharedHttpBudget(settings, args.max_http)
        audit.update(provider_type=settings.llm_provider_type, model=counted.model,
            runtime_profile=parent.runtime_profile(settings),
            learner_request_sha256=parent.digest({"request": prepared["learner_request"], "facts": prepared["facts"]}))
        # Same original API deferral as real_parent, NOT a substituted model decision.
        parent.tutor_route.build_tutor_run_dispatcher = lambda _: parent.RecordingTutorDispatcher()
        parent.tutor_route.get_settings = lambda: settings
        deadline = parent.wall_deadline(240) if os.name == "posix" else nullcontext()
        audit["wall_bound"] = "original_posix_240s" if os.name == "posix" else "original_run_deadline_and_HTTP_timeout_cap"
        with parent.TestClient(parent.app) as client, budget.enforce(), deadline:
            audit["stage"] = "original_user_and_harness_gate"
            user = client.post("/api/users", json={"display_name": "Declared synthetic KC acceptance learner"})
            require(user.status_code == 201, "PARENT_USER_API_DENIED")
            user_id = str(user.json()["user"]["id"])
            audit["user_id"] = user_id
            report["user_id"] = user_id
            cutover = client.get("/api/harness/cutover", params={"user_id": user_id})
            capability = client.get("/api/tutor/capabilities/thread-turn-v2", params={"user_id": user_id})
            require(cutover.status_code == 200 and cutover.json().get("state") == "verified"
                and capability.status_code == 200 and capability.json().get("effective_enabled") is True,
                "PARENT_RUNTIME_GATE_NOT_READY")
            audit["stage"] = "original_planning_session_and_single_input"
            session_response = client.post("/api/learning-plan-sessions", json={"user_id": user_id,
                "client_action_id": "actual-d-finite-session-" + uuid4().hex, "preferred_language_id": "python"})
            require(session_response.status_code in {200, 201}, "PARENT_SESSION_API_DENIED")
            session = session_response.json()["session"]
            session_id, conversation_id = str(session["session_id"]), str(session["conversation_id"])
            audit.update(session_id=session_id, conversation_id=conversation_id)
            report.update(session_id=session_id, conversation_id=conversation_id)
            accepted = client.post(f"/api/tutor/conversations/{conversation_id}/inputs", json=parent.action_payload(
                user_id, "actual-d-finite-input-" + uuid4().hex,
                content=prepared["learner_request"], planning_facts=prepared["facts"],
                learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"}))
            require(accepted.status_code == 202, "PARENT_INPUT_API_DENIED")
            coordinate = {"run_id": str(accepted.json()["run_id"]), "input_revision": int(accepted.json()["input_revision"])}
            audit["runs"].append(coordinate)
            report.update(**coordinate)
            dispatcher = parent.TutorInteractiveRunDispatcher(settings=settings, provider_factory=lambda _:
                parent.PrimaryTutorProviderGateway(settings=settings, client=counted,
                    max_output_tokens=settings.tutor_decision_max_output_tokens))
            audit["stage"] = "original_real_provider_dispatch"
            outcome = dispatcher.dispatch(user_id=user_id, run_id=coordinate["run_id"])
            audit.update(run_status=outcome.status.value,
                terminal_outcome=None if outcome.terminal_outcome is None else outcome.terminal_outcome.value)
            with parent.connect() as conn:
                stored = conn.execute("SELECT * FROM tutor_learning_plan_drafts WHERE user_id=%s AND session_id=%s "
                    "AND source_run_id=%s AND source_input_revision=%s", (user_id, session_id,
                    coordinate["run_id"], coordinate["input_revision"])).fetchone()
                require(stored is not None, "ORIGINAL_PROVIDER_DRAFT_NOT_PERSISTED")
                report["stored_draft_id"] = str(stored["id"])  # retain even if model's semantics fail
                audit["stage"] = "original_receipts_and_exact_finite_validation"
                audit.update(parent_draft_id=str(stored["id"]), parent_content_hash=stored["content_hash"],
                    source_run_id=str(stored["source_run_id"]), source_input_revision=stored["source_input_revision"])
                report["finite_draft"] = validate_finite(stored)
                require(outcome.terminal_outcome is parent.TutorTerminalOutcome.COMPLETED
                    and outcome.capability_call_count >= 1, "PARENT_RUN_INCOMPLETE")
                audit.update(status="parent_persisted", model_http_attempts=budget.count, client_calls=counted.count,
                    usage_per_call=counted.usage, response_models=counted.response_models,
                    provider_receipts=parent.load_receipts(conn, user_id=user_id,
                        conversation_id=conversation_id, runs=audit["runs"]))
                proof = parent.verify_parent_provenance(conn, audit=audit, parent=stored,
                    database_name=source["DB"], conversation_id=conversation_id,
                    subject_id="route.python", subject_version="1.0", expected_runtime_profile=parent.runtime_profile(settings),
                    profile="formal", prior_http_attempts=args.prior_http_attempts, cumulative_http_cap=args.cumulative_http_cap)
                report.update(status="passed_real_finite_draft_only", parent_kind=proof["parent_kind"])
    finally:
        if budget is not None and counted is not None:
            audit.update(model_http_attempts=budget.count, client_calls=counted.count, usage_per_call=counted.usage,
                response_models=counted.response_models, unknown_usage_count=budget.count-sum(v is not None for v in counted.usage))
            report.update(model_http_attempts=budget.count, usage_per_call=counted.usage,
                prior_http_attempts=args.prior_http_attempts, cumulative_HTTP_observed=args.prior_http_attempts+budget.count,
                monetary_cost=None, unknown_usage_count=audit["unknown_usage_count"])
        if audit.get("runs"):
            try:
                with parent.connect() as conn:
                    audit["provider_receipts"] = parent.load_receipts(conn, user_id=audit["user_id"],
                        conversation_id=audit["conversation_id"], runs=audit["runs"])
                    run = audit["runs"][0]
                    audit["provider_receipts_full"] = conn.execute("SELECT * FROM tutor_provider_attempt_receipts "
                        "WHERE user_id=%s AND run_id=%s AND input_revision=%s ORDER BY decision_iteration,attempt_index",
                        (audit["user_id"], run["run_id"], run["input_revision"])).fetchall()
                    audit["action_receipts"] = conn.execute("SELECT * FROM tutor_action_receipts WHERE user_id=%s "
                        "AND run_id=%s AND input_revision=%s ORDER BY invocation_id",
                        (audit["user_id"], run["run_id"], run["input_revision"])).fetchall()
                    audit["input_receipts"] = conn.execute("SELECT * FROM tutor_run_input_events WHERE run_id=%s "
                        "AND input_revision=%s AND conversation_id=%s",
                        (run["run_id"], run["input_revision"], audit["conversation_id"])).fetchall()
                    if report["status"] == "passed_real_finite_draft_only":
                        require(any(r["action_id"] == "learning.plan.draft" and r["status"] == "verified"
                            and r["verification_status"] == "verified" and r["authority_kind"] == "plan_draft"
                            and r["authority_id"] == report["finite_draft"]["draft_id"]
                            and r["authority_hash"] == report["finite_draft"]["content_hash"] for r in audit["action_receipts"]),
                            "ORIGINAL_VERIFIED_PLAN_ACTION_MISSING")
            except Exception:
                audit["status"] = "failed"
                report.update(status="pending", safe_reason="ORIGINAL_RECEIPT_EXPORT_OR_VERIFICATION_FAILED")
        try:
            save(output / "receipt-audit.json", audit)
        finally:
            parent.tutor_route.build_tutor_run_dispatcher, parent.tutor_route.get_settings = previous_routes
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--execute", action="store_true", help="Main only; original API/provider writes are durable")
    parser.add_argument("--max-http", type=int, default=8)
    parser.add_argument("--prior-http-attempts", type=int)
    parser.add_argument("--cumulative-http-cap", type=int)
    args = parser.parse_args(argv)
    prepared = plan()
    report: dict[str, Any] = {"status": "not_executed_zero_io_plan", "database_io": False,
        "provider_calls": 0, "GETs": 0, "signing_key_reads": 0, "monetary_cost": None,
        "draft_created": False, "confirmation": "not_executed", "teaching_selection": "not_executed",
        "actual_D_proof_bridge_mapping": "not_executed", "public_release": False, "E_complete": False}
    if not args.execute:
        print(json.dumps(report | {"plan": prepared}, ensure_ascii=False))
        return 0
    if (not 1 <= args.max_http <= 8 or args.prior_http_attempts is None or args.prior_http_attempts < 0
            or args.cumulative_http_cap is None or args.prior_http_attempts+args.max_http > args.cumulative_http_cap):
        parser.error("explicit existing prior HTTP count and approved cumulative cap required; no budget reset")
    output = OUTPUT / ("draft-" + uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    save(output / "intent.json", prepared | {"prior_http_attempts": args.prior_http_attempts,
        "cumulative_http_cap": args.cumulative_http_cap, "phase_http_cap": args.max_http})
    report.update(status="pending", database_io=True)
    try:
        execute(args, prepared, output, report)
    except BaseException as exc:
        report.update(status="failed_retained_no_retry", error_type=type(exc).__name__,
            safe_reason=str(exc) if type(exc) is Pending else "DETAILS_WITHHELD")
    report["draft_created"] = "stored_draft_id" in report
    report["provider_calls"] = report.get("model_http_attempts", 0)
    save(output / "result.json", report)
    print(json.dumps(report, ensure_ascii=False))
    print(str(output / "result.json"))
    return 0 if report["status"] == "passed_real_finite_draft_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
