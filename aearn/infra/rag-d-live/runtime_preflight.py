"""Separate, default-off operator preflight for the disposable D runtime gate.

Never imported/called by normal real_parent preparation. State transitions and
migration audit belong solely to TutorThreadTurnCutoverService. No model IO.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

API = Path(__file__).resolve().parents[2] / "services" / "api"
WORKER = API.parent / "worker"
C = Path(__file__).resolve().parents[1] / "rag-c-live"
CONTROL = Path(__file__).resolve().parents[1] / "rag-c-source-control"
for path in (API, WORKER, CONTROL, C):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_DATABASE = re.compile(r"aearn_rag260_c_d_[A-Za-z0-9_]+\Z")
_OPERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,99}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class PreflightDenied(ValueError):
    """Fixed public code only; raw database/file exceptions are never printed."""


def guard_request(*, execute: bool, database_name: str, operation_id: str) -> None:
    if execute is not True:
        raise PreflightDenied("DEFAULT_OFF")
    if (type(database_name) is not str or len(database_name) > 63
            or _DATABASE.fullmatch(database_name) is None):
        raise PreflightDenied("DATABASE_DENIED")
    if type(operation_id) is not str or _OPERATION.fullmatch(operation_id) is None:
        raise PreflightDenied("OPERATION_ID_DENIED")


def guard_config(config: dict[str, Any], dsn: str, *, database_name: str) -> None:
    # A prefix alone is insufficient: independently named target, C config and
    # parsed private DSN must all agree before even opening a database socket.
    if config.get("approved") is not True or config.get("database_name") != database_name:
        raise PreflightDenied("CONTROL_CONFIG_DENIED")
    try:
        parsed = psycopg.conninfo.conninfo_to_dict(dsn)
    except (ValueError, psycopg.ProgrammingError) as exc:
        raise PreflightDenied("DATABASE_DENIED") from exc
    if not dsn or "\n" in dsn or "\r" in dsn or parsed.get("dbname") != database_name:
        raise PreflightDenied("DATABASE_DENIED")


def _clean_inventory(dry_run: dict[str, Any]) -> None:
    summary = dry_run.get("summary")
    if not isinstance(summary, dict) or dry_run.get("would_block") is not False:
        raise PreflightDenied("CUTOVER_INVENTORY_DENIED")
    if any(summary.get(key) is not True for key in (
        "schema_ready", "worker_import_ready", "legacy_post_tombstone", "snapshot_history_readable",
    )):
        raise PreflightDenied("CUTOVER_DEPENDENCIES_NOT_READY")
    # This is a fresh D operator lane, not authorization to terminalize old user
    # work. Reject even safe legacy work rather than let prepare migrate it.
    if any(type(summary.get(key)) is not int or summary[key] != 0 for key in (
        "legacy_nonterminal", "active_legacy_leases", "ambiguous_effects",
    )):
        raise PreflightDenied("CUTOVER_LEGACY_WORK_PRESENT")


def _enabled_audit(conn: Any, *, version: str, generation: int) -> list[str]:
    rows = conn.execute(
        "SELECT kind,state FROM tutor_thread_turn_cutover_events "
        "WHERE cutover_version=%s AND generation=%s ORDER BY occurred_at,event_key",
        (version, generation),
    ).fetchall()
    pairs = {(row["kind"], row["state"]) for row in rows}
    if not {("preparing", "preparing"), ("preflight", "ready"), ("enabled", "enabled")} <= pairs:
        raise PreflightDenied("CUTOVER_SERVICE_AUDIT_MISSING")
    return [str(row["kind"]) for row in rows]


def execute_on_connection(conn: Any, *, execute: bool, database_name: str,
                          operation_id: str) -> dict[str, object]:
    """Caller-owned transaction; rolls back this preflight on any failure.

    CLI owns commit. Tests may call this in a separately guarded fixture DB.
    There is no direct SQL state fill and no automatic rollback/re-enable lane.
    """
    guard_request(execute=execute, database_name=database_name, operation_id=operation_id)
    if conn.autocommit:
        raise PreflightDenied("TRANSACTION_REQUIRED")
    from app.core.config import Settings
    from app.services.tutor.thread_turn_cutover import TutorThreadTurnCutoverService

    settings = Settings(llm_type="disabled", openai_api_key=None, deepseek_api_key=None,
                        tutor_thread_turn_v2_enabled=True, codex_runtime_enabled=False,
                        rag_source_discovery_enabled=False, rag_auto_intake_enabled=False,
                        rag_auto_activation_enabled=False, rag_evidence_consumer_enabled=False)
    with conn.transaction():
        actual = conn.execute("SELECT current_database() AS name").fetchone()
        if actual is None or actual["name"] != database_name:
            raise PreflightDenied("DATABASE_DENIED")
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '15s'")
        service = TutorThreadTurnCutoverService(conn)
        # Same lock ordering as the owner; hold a brief table SHARE lock only to
        # prevent new legacy DML between dry_run and prepare's convergence.
        service._lock()
        conn.execute("LOCK TABLE tutor_runs IN SHARE MODE")
        dry = service.dry_run()
        _clean_inventory(dry)
        before = service.status(settings=settings)
        already = before["state"] == "enabled"
        if not already:
            prepared = service.prepare(expected_generation=int(before["generation"]),
                                       idempotency_key=operation_id + ":prepare")
            summary_hash = prepared.get("summary_hash")
            if (prepared.get("state") != "ready" or not isinstance(summary_hash, str)
                    or _HASH.fullmatch(summary_hash) is None or summary_hash == "0" * 64):
                raise PreflightDenied("CUTOVER_NOT_READY")
            service.enable(expected_generation=int(prepared["generation"]), summary_hash=summary_hash,
                           idempotency_key=operation_id + ":enable")
        final = service.status(settings=settings)
        summary_hash = final.get("summary_hash")
        if (final.get("state") != "enabled" or final.get("effective_enabled") is not True
                or not isinstance(summary_hash, str) or _HASH.fullmatch(summary_hash) is None
                or summary_hash == "0" * 64):
            raise PreflightDenied("CUTOVER_EFFECTIVE_GATE_DENIED")
        service.assert_mutation_allowed(settings=settings)
        events = _enabled_audit(conn, version=str(final["cutover_version"]), generation=int(final["generation"]))
        return {"status": "already_enabled_verified" if already else "enabled_by_service",
                "database_name": database_name, "previous_state": before["state"],
                "cutover_version": final["cutover_version"], "generation": final["generation"],
                "summary_hash": summary_hash, "effective_enabled": True,
                "audit_event_kinds": events, "model_calls": 0,
                "source_admission_checked": False, "public_release": False}


def run(args: argparse.Namespace) -> dict[str, object]:
    guard_request(execute=args.execute, database_name=args.database_name, operation_id=args.operation_id)
    if os.name != "posix" or os.geteuid() != 0:
        raise PreflightDenied("ROOT_OPERATOR_REQUIRED")
    # Set before lazy app/control imports. No provider key/config is accepted.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LLM_TYPE"] = "disabled"
    from control_runtime import CONFIG, _absolute, _root_file, _root_json
    from app.core.config import get_settings
    get_settings.cache_clear()
    config, _ = _root_json(_absolute(args.control_config))
    if set(config) != CONFIG:
        raise PreflightDenied("CONTROL_CONFIG_DENIED")
    raw, _ = _root_file(_absolute(config["dsn_secret_path"]), limit=4096)
    dsn = raw.decode("utf-8").strip()
    guard_config(config, dsn, database_name=args.database_name)
    # Do not install DATABASE_URL or read the ambient application DB. Use only
    # the validated current C private DSN and assert the server's actual name.
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3) as conn:
        result = execute_on_connection(conn, execute=True, database_name=args.database_name,
                                       operation_id=args.operation_id)
    return result  # connection context committed successfully before success output


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--control-config", required=True)
    p.add_argument("--database-name", required=True, help="exact separately declared disposable DB name")
    p.add_argument("--operation-id", required=True, help="nonsecret bounded operator invocation identity")
    return p


def main() -> int:
    try:
        result = run(parser().parse_args())
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        if type(exc) is PreflightDenied:
            code = str(exc)
        else:
            from app.services.tutor.cutover import CutoverError
            code = exc.code if isinstance(exc, CutoverError) else "RUNTIME_PREFLIGHT_FAILED"
        print(json.dumps({"status": "blocked", "phase": "runtime_gate", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
