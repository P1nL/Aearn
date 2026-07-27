"""Trusted raw-input resolver used only after a claimed executor job exists."""
from __future__ import annotations

import json
from collections.abc import Mapping

from aearn_shared.execution import ExecutionAction, ExecutionJobV1, SandboxInputV1
from psycopg import Connection

from aearn_executor.runtime import TrustedInputResolutionError


class PostgresTrustedInputResolver:
    """Loads raw source/tests transiently and never persists or logs either value."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def load(self, *, job: ExecutionJobV1) -> SandboxInputV1:
        row = self._conn.execute(
            """
            SELECT intents.action, messages.content AS submission,
                   jobs.source_reference_hash, jobs.test_reference_hash
            FROM tutor_execution_jobs AS jobs
            JOIN tutor_execution_intents AS intents ON intents.id = jobs.intent_id
            JOIN tutor_messages AS messages ON messages.id = intents.source_message_id
            WHERE jobs.id = %s
              AND jobs.intent_id = %s
              AND jobs.run_id = %s
            """,
            (job.job_id, job.intent_proof_id, job.run_id),
        ).fetchone()
        if row is None:
            raise TrustedInputResolutionError("trusted_input_scope_missing")
        tests = self._conn.execute(
            """
            SELECT test_cases.case_type, test_cases.input_json,
                   test_cases.expected_output_json, test_cases.assertion_code,
                   test_cases.timeout_ms, test_cases.order_index
            FROM tutor_execution_intents AS intents
            JOIN test_cases ON test_cases.exercise_id = intents.exercise_id
            WHERE intents.id = %s
              AND test_cases.archived_at IS NULL
            ORDER BY test_cases.order_index ASC
            """,
            (job.intent_proof_id,),
        ).fetchall()
        visible: list[dict[str, object]] = []
        hidden: list[dict[str, object]] = []
        for test in tests:
            payload = {
                "case_type": str(test["case_type"]),
                "input": test.get("input_json") if isinstance(test.get("input_json"), Mapping) else {},
                "expected": test.get("expected_output_json") if isinstance(test.get("expected_output_json"), Mapping) else {},
                "assertion": str(test.get("assertion_code") or ""),
                "timeout_ms": _as_int(test.get("timeout_ms")),
                "order_index": _as_int(test.get("order_index")),
            }
            (hidden if payload["case_type"] == "hidden" else visible).append(payload)
        try:
            return SandboxInputV1(
                runtime_id=job.runtime_id,
                action=ExecutionAction(str(row["action"])),
                submission=str(row["submission"]),
                visible_test_bundle_json=json.dumps(visible, ensure_ascii=False, separators=(",", ":")),
                hidden_test_bundle_json=json.dumps(hidden, ensure_ascii=False, separators=(",", ":")),
                source_reference_hash=str(row["source_reference_hash"]),
                test_reference_hash=str(row["test_reference_hash"]),
            )
        except (TypeError, ValueError) as exc:
            raise TrustedInputResolutionError("trusted_input_invalid") from exc


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
