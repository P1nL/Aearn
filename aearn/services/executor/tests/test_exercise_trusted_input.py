from __future__ import annotations

import hashlib
import json
from typing import cast

import pytest
from aearn_shared.execution import ExecutionJobState, ExecutionJobV1
from psycopg import Connection

from aearn_executor.runtime import TrustedInputResolutionError
from aearn_executor.trusted_input import PostgresTrustedInputResolver


def _reference_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, row):
        self.row = row
        self.queries: list[str] = []

    def execute(self, query, parameters=()):
        del parameters
        self.queries.append(str(query))
        return _Result(self.row)


def _job() -> ExecutionJobV1:
    return ExecutionJobV1(
        job_id="00000000-0000-0000-0000-000000000001",
        intent_proof_id="00000000-0000-0000-0000-000000000002",
        user_id="00000000-0000-0000-0000-000000000003",
        runtime_id="python-stdout-v1",
        owner_kind="exercise_attempt",
        exercise_attempt_id="00000000-0000-0000-0000-000000000004",
        lock_fingerprint="a" * 64,
        state=ExecutionJobState.PENDING,
    )


def test_exercise_attempt_trusted_input_loads_private_artifacts_only_after_claim_scope() -> None:
    submission_id = "00000000-0000-0000-0000-000000000005"
    rubric_hash = "b" * 64
    connection = _Connection(
        {
            "action": "test",
            "submission": "value = 3\nprint(value)",
            "submission_id": submission_id,
            "rubric_hash": rubric_hash,
            "source_reference_hash": _reference_hash(submission_id),
            "test_reference_hash": _reference_hash(rubric_hash),
            "private_test_bundle_json": [
                {
                    "case_type": "visible",
                    "input": {},
                    "expected": {"stdout": "3\n"},
                    "assertion": "stdout == '3\n'",
                    "timeout_ms": 1000,
                    "order_index": 0,
                },
                {
                    "case_type": "hidden",
                    "input": {},
                    "expected": {"stdout": "3\n"},
                    "assertion": "hidden assertion",
                    "timeout_ms": 1000,
                    "order_index": 1,
                },
            ],
        }
    )
    resolver = PostgresTrustedInputResolver(cast(Connection[dict[str, object]], connection))
    resolved = resolver.load(job=_job())

    assert resolved.submission == "value = 3\nprint(value)"
    assert resolved.action.value == "test"
    assert json.loads(resolved.visible_test_bundle_json)[0]["case_type"] == "visible"
    assert json.loads(resolved.hidden_test_bundle_json)[0]["assertion"] == "hidden assertion"
    assert any("tutor_exercise_private_rubrics" in query for query in connection.queries)
    assert all("tutor_messages" not in query for query in connection.queries)


def _model_review_job() -> ExecutionJobV1:
    return ExecutionJobV1(
        job_id="00000000-0000-0000-0000-000000000011",
        intent_proof_id="00000000-0000-0000-0000-000000000012",
        user_id="00000000-0000-0000-0000-000000000013",
        runtime_id="python-stdout-v1",
        owner_kind="model_review_validation",
        conversation_id="00000000-0000-0000-0000-000000000014",
        run_id="00000000-0000-0000-0000-000000000015",
        model_review_validation_id="00000000-0000-0000-0000-000000000016",
        lock_fingerprint="e" * 64,
        state=ExecutionJobState.PENDING,
    )


def test_model_review_trusted_input_strips_template_metadata_before_sandbox() -> None:
    candidate_hash = "a" * 64
    private_hash = "b" * 64
    connection = _Connection(
        {
            "action": "test",
            "submission": "def average(total, count):\n    return total / count",
            "candidate_hash": candidate_hash,
            "private_hash": private_hash,
            "source_reference_hash": _reference_hash(candidate_hash),
            "test_reference_hash": _reference_hash(private_hash),
            "private_test_bundle_json": [
                {
                    "id": "average-normal",
                    "case_type": "visible",
                    "input": {"total": 6, "count": 2},
                    "expected": {"value": 3},
                    "assertion": "",
                    "timeout_ms": 2000,
                    "order_index": 0,
                    "candidate_expected_pass": True,
                    "proof_ids": [],
                },
                {
                    "id": "average-zero",
                    "case_type": "hidden",
                    "input": {"total": 0, "count": 0},
                    "expected": {"value": 0},
                    "assertion": "",
                    "timeout_ms": 2000,
                    "order_index": 1,
                    "candidate_expected_pass": False,
                    "proof_ids": ["proof-zero-division"],
                },
            ],
        }
    )
    resolver = PostgresTrustedInputResolver(cast(Connection[dict[str, object]], connection))

    resolved = resolver.load(job=_model_review_job())
    visible = json.loads(resolved.visible_test_bundle_json)
    hidden = json.loads(resolved.hidden_test_bundle_json)

    assert visible == [
        {
            "case_type": "visible",
            "input": {"total": 6, "count": 2},
            "expected": {"value": 3},
            "assertion": "",
            "timeout_ms": 2000,
            "order_index": 0,
        }
    ]
    assert hidden == [
        {
            "case_type": "hidden",
            "input": {"total": 0, "count": 0},
            "expected": {"value": 0},
            "assertion": "",
            "timeout_ms": 2000,
            "order_index": 1,
        }
    ]
    serialized = resolved.visible_test_bundle_json + resolved.hidden_test_bundle_json
    assert "candidate_expected_pass" not in serialized
    assert "proof-zero-division" not in serialized
    assert "average-zero" not in serialized
    assert any("tutor_model_review_candidates" in query for query in connection.queries)


def test_exercise_attempt_trusted_input_rejects_reference_mismatch() -> None:
    connection = _Connection(
        {
            "action": "run",
            "submission": "print(3)",
            "submission_id": "00000000-0000-0000-0000-000000000005",
            "rubric_hash": "b" * 64,
            "source_reference_hash": "c" * 64,
            "test_reference_hash": "d" * 64,
            "private_test_bundle_json": [],
        }
    )
    with pytest.raises(TrustedInputResolutionError, match="trusted_input_reference_mismatch"):
        resolver = PostgresTrustedInputResolver(cast(Connection[dict[str, object]], connection))
        resolver.load(job=_job())
