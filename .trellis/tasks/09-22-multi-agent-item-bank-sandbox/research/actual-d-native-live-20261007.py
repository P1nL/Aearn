"""Main-only read/lock-only actual-D preflight. Default plan performs zero IO.

No signer/oracle/provider, status writes, synthetic input or confirmation.
Observed stored receipts are prerequisites, not a new source authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
from typing import Any, cast
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[4]
DATABASE = "aearn_b1d_sandbox_20261001"
OUTPUT = ROOT / ".runtime/e-actual-d-native-20261007"
TABLES = ("tutor_learning_plan_sessions", "tutor_learning_plan_drafts", "rag_material_selections",
    "rag_plan_material_bindings", "rag_assessment_source_evidence", "rag_actual_d_private_provenance",
    "tutor_item_supply_finite_course_mappings", "tutor_provider_attempt_receipts", "tutor_action_receipts",
    "tutor_item_supply_user_epochs")
ORDER = ("original_draft_ready", "current_whole_draft_teaching_selection", "prepare_actual_d",
    "new_real_source_oracle_and_original_signer", "same_conn_producer_preparation_and_freeze",
    "original_confirm_session_CAS", "confirmed_current_authority", "FiniteCourseMappingOwner.bind_496")


def helper() -> dict[str, Any]:
    return runpy.run_path(str(Path(__file__).with_name("native-type-live-support-20261006.py")))


def save(path: Path, report: dict[str, Any]) -> None:
    with path.open("x", encoding="utf8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)


def base_report() -> dict[str, Any]:
    return {"status": "not_executed_zero_io_plan", "database": DATABASE, "database_io": False,
        "provider_calls": 0, "GETs": 0, "signing_key_reads": 0, "oracle_runs": 0,
        "committed": False, "full_chain": "not_executed", "private_reset_delete": "not_executed",
        "live_D_authorized": False, "public_release": False, "E_complete": False,
        "required_order": list(ORDER)}


def fixture_marked(row: dict[str, Any]) -> bool:
    return any(word in str(row.get(key) or "").lower()
        for key in ("generator_version", "policy_version", "input_source", "run_policy_version")
        for word in ("fixture", "synthetic", "offline"))


def rows(conn: Any, user_id: UUID | None) -> list[dict[str, Any]]:
    return conn.execute("""SELECT d.*,s.conversation_id,s.status AS session_status,
        s.version AS session_version,r.policy_version AS run_policy_version,
        (SELECT i.source FROM tutor_run_input_events i WHERE i.run_id=d.source_run_id
          AND i.input_revision=d.source_input_revision) AS input_source,
        (SELECT count(*) FROM tutor_provider_attempt_receipts p WHERE p.run_id=d.source_run_id
          AND p.user_id=d.user_id AND p.input_revision=d.source_input_revision
          AND p.outcome='accepted') AS provider_count,
        (SELECT count(*) FROM tutor_action_receipts a WHERE a.run_id=d.source_run_id
          AND a.user_id=d.user_id AND a.conversation_id=s.conversation_id
          AND a.input_revision=d.source_input_revision AND a.action_id='learning.plan.draft'
          AND a.status='verified' AND a.verification_status='verified'
          AND a.authority_kind='plan_draft' AND a.authority_id=d.id::text
          AND a.authority_hash=d.content_hash) AS plan_action_count,
        count(*) OVER () AS total
        FROM tutor_learning_plan_sessions s JOIN tutor_learning_plan_drafts d
          ON (d.id,d.session_id,d.user_id)=(s.current_draft_id,s.id,s.user_id)
        JOIN tutor_runs r ON r.id=d.source_run_id JOIN users u ON u.id=d.user_id
        WHERE s.status IN ('draft_ready','confirmed') AND u.deleted_at IS NULL
          AND (%s::uuid IS NULL OR d.user_id=%s) ORDER BY d.id LIMIT 64""", (user_id, user_id)).fetchall()


def inspect_draft(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    from app.services.grounding.material_contracts_v2 import DraftScope
    from app.services.grounding.material_binding_repository import PostgresMaterialBindingRepository, _scope_from_draft, _check_members
    from app.services.learning.plan_drafting import draft_artifact_from_row
    from app.services.learning.contracts import canonical_plan_payload
    from app.services.learning.item_supply.finite_course_mapping import finite_node_description
    from app.services.learning.item_supply.finite_course_targets import finite_course_targets

    draft = DraftScope(user_id=str(row["user_id"]), session_id=str(row["session_id"]),
        conversation_id=str(row["conversation_id"]), draft_id=str(row["id"]),
        draft_version=row["draft_version"], content_hash=row["content_hash"],
        source_run_id=str(row["source_run_id"]), source_input_revision=row["source_input_revision"])
    artifact = draft_artifact_from_row(row)
    item: dict[str, Any] = {"user_id": draft.user_id, "session_id": draft.session_id, "draft_id": draft.draft_id,
        "status": row["session_status"], "fixture_marked": fixture_marked(row),
        "accepted_provider_count": int(row["provider_count"]), "verified_exact_plan_action_count": int(row["plan_action_count"]),
        "draft_hash_valid": artifact.content_hash == draft.content_hash, "live_D_authorized": False}
    if row["session_status"] == "draft_ready":
        _scope_from_draft(conn, draft, lock=False)
    epoch = conn.execute("SELECT epoch,enabled FROM tutor_item_supply_user_epochs WHERE user_id=%s", (row["user_id"],)).fetchone()
    item["owner_epoch"] = None if epoch is None else int(epoch["epoch"])
    item["owner_epoch_enabled"] = epoch is not None and epoch["enabled"] is True
    plan = cast(dict[str, Any], canonical_plan_payload(artifact.plan))
    nodes = [n for m in plan["modules"] for n in m["nodes"]]
    item["finite_nodes"] = [{"node_id": n["knowledge_key"], "target_id": t.target_id}
        for n in nodes for t in finite_course_targets() if n["description"] == finite_node_description(t.target_id)
        and n["required_capabilities"] == list(t.required_capabilities) and row["language_id"] == t.language_id]
    selections = conn.execute("SELECT handle FROM rag_material_selections WHERE draft_id=%s AND user_id=%s ORDER BY handle",
                              (row["id"], row["user_id"])).fetchall()
    item["teaching_selections"] = []
    repo = PostgresMaterialBindingRepository(conn)
    for selected in selections:
        with conn.transaction():
            selection = repo.get_selection(handle=selected["handle"], draft=draft) if row["session_status"] == "draft_ready" else repo._read_selection(selected["handle"], draft)
            _check_members(selection, row)
            main = [r for r in selection.requirements if r.demand.purpose == "main_teaching"]
            entries = {(e.node_id,e.goal_hash,e.purpose): e for e in selection.entries}
            ready = {r.node_id for r in main if entries[(r.node_id,r.goal_hash,"main_teaching")].status == "ready"
                     and entries[(r.node_id,r.goal_hash,"main_teaching")].evidence}
            item["teaching_selections"].append({"handle": selection.handle,
                "whole_draft_ready_shape": ready == {n["knowledge_key"] for n in nodes},
                "current_authorization": "not_executed"})
    return item


def inspect_chain_counts(conn: Any, row: dict[str, Any]) -> dict[str, int]:
    from app.services.grounding.autonomous.actual_d_lifecycle import ACTUAL_D_FORMAT
    scope = (ACTUAL_D_FORMAT, str(row["user_id"]), str(row["id"]))
    owner = "e.signed_proof->'payload'->>'format'=%s AND e.signed_proof->'payload'->'prepared'->'actual_d'->'draft'->>'user_id'=%s AND e.signed_proof->'payload'->'prepared'->'actual_d'->'draft'->>'draft_id'=%s"
    sources = {"private_proof": "rag_assessment_source_evidence e",
        "private_bridge": "rag_actual_d_private_provenance b JOIN rag_assessment_source_evidence e ON e.id=b.private_evidence_id"}
    result = {name: int(conn.execute("SELECT count(*) AS n FROM " + source + " WHERE " + owner,
                                    scope).fetchone()["n"]) for name, source in sources.items()}
    for name, table, extra in (("assessment_binding", "rag_plan_material_bindings", " AND purpose='assessment_evidence'"),
                              ("confirmed_mapping", "tutor_item_supply_finite_course_mappings", "")):
        result[name] = int(conn.execute("SELECT count(*) AS n FROM " + table + " WHERE user_id=%s AND draft_id=%s" + extra,
                                      (row["user_id"], row["id"])).fetchone()["n"])
    return result


def missing_reasons(item: dict[str, Any]) -> list[str]:
    reasons = []
    for failed, reason in (
        (item["fixture_marked"], "EXPLICIT_PREPARATION_FIXTURE_NOT_LIVE_D"),
        (not item["draft_hash_valid"], "ORIGINAL_DRAFT_HASH_MISMATCH"),
        (not item["owner_epoch_enabled"], "ORIGINAL_ACTIVE_USER_EPOCH_MISSING"),
        (not item["accepted_provider_count"] or not item["verified_exact_plan_action_count"], "ORIGINAL_PROVIDER_PLAN_ACTION_EVIDENCE_MISSING"),
        (not item["finite_nodes"], "EXACT_FINITE_NODE_SEMANTICS_MISSING"),
        (not any(s["whole_draft_ready_shape"] for s in item["teaching_selections"]), "WHOLE_DRAFT_READY_TEACHING_SELECTION_MISSING"),
        (not item["chain_counts"]["private_proof"], "NEW_ACTUAL_D_ORACLE_SIGNED_PROOF_MISSING"),
        (not item["chain_counts"]["private_bridge"], "POPULATED_PRIVATE_PUBLIC_BRIDGE_MISSING"),
        (not item["chain_counts"]["assessment_binding"], "ASSESSMENT_PREPARATION_FREEZE_MISSING"),
        (item["status"] != "confirmed", "ORIGINAL_CONFIRM_SESSION_CAS_NOT_EXECUTED"),
        (not item["chain_counts"]["confirmed_mapping"], "496_CONFIRMED_MAPPING_MISSING"),
    ):
        if failed:
            reasons.append(reason)
    reasons.append("CURRENT_TEACHING_AND_CONFIRMED_AUTHORITIES_NOT_ASSEMBLED_IN_THIS_PREFLIGHT")
    return reasons


def preflight(conn: Any, user_id: UUID | None, report: dict[str, Any]) -> None:
    if conn.execute("SELECT current_database() AS name").fetchone()["name"] != DATABASE:
        report.update(status="pending", safe_reason="EXACT_ISOLATED_DATABASE_REQUIRED")
        return
    # Read/lock-only original helpers require a writable READ COMMITTED transaction.
    if conn.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
        report.update(status="pending", safe_reason="READ_COMMITTED_REQUIRED")
        return
    report["missing_tables"] = [name for name in TABLES if not conn.execute(
        "SELECT to_regclass(%s) IS NOT NULL AS installed", ("public." + name,)).fetchone()["installed"]]
    if report["missing_tables"]:
        report.update(status="pending", safe_reason="REQUIRED_SCHEMA_NOT_INSTALLED")
        return
    candidates = rows(conn, user_id)
    report["candidate_count"] = int(candidates[0]["total"]) if candidates else 0
    report["inventory_truncated"] = report["candidate_count"] > len(candidates)
    report["candidates"] = []
    for row in candidates:
        item: dict[str, Any] = {"user_id": str(row["user_id"]), "session_id": str(row["session_id"]), "draft_id": str(row["id"])}
        try:
            with conn.transaction():
                item = inspect_draft(conn, row)
                item["chain_counts"] = inspect_chain_counts(conn, row)
                item["missing"] = missing_reasons(item)
        except Exception as exc:
            item.update(status="failed_preflight_candidate", error_type=type(exc).__name__, safe_reason="DETAILS_WITHHELD")
        report["candidates"].append(item)
    report.update(status="pending_live_D_inputs_and_assembly", inventory_check="completed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--execute", action="store_true", help="Main only, read/lock-only rollback preflight")
    parser.add_argument("--user-id", type=UUID, help="Optional exact owner; no latest-draft substitution")
    args = parser.parse_args(argv)
    report = base_report()
    if not args.execute:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    output = OUTPUT / ("preflight-" + uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    save(output / "intent.json", report)
    report.update(status="pending", database_io=True, database_transaction="read_lock_only_rollback")
    try:
        existing = helper()
        existing["configure_imports"]()
        with existing["connection"]() as conn:
            with conn.transaction(force_rollback=True):
                preflight(conn, args.user_id, report)
        report["rollback_completed"] = True
    except Exception as exc:
        report.update(status="failed_retained_no_retry", error_type=type(exc).__name__, safe_reason="DETAILS_WITHHELD")
    save(output / "result.json", report)
    print(json.dumps(report, ensure_ascii=False))
    print(str(output / "result.json"))
    return 2  # deliberately never declare confirmation/source/mapping acceptance


if __name__ == "__main__":
    raise SystemExit(main())
