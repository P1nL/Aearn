"""Explicit PRIVATE diagnostic DATA. No disk IO, peer input or issuer authority."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from typing import Literal, Protocol

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.review_contracts_v2 import (
    BlindScoreV2, BlindSolveInputV2, BlindSolveResultV2, CandidateBindingV2,
)

PRIVATE_BLIND_EVENT_MAX_BYTES = 262_144
PRIVATE_BLIND_RAW_MAX_CHARS = 48_000
PrivateBlindEventKind = Literal["run_started", "answer_received", "finite_static_evaluation", "score_completed", "failure"]
PrivateBlindFailureStage = Literal["solver_call", "result_binding", "scoring", "score_receipt", "blind_receipt"]


class PrivateBlindAuditSink(Protocol):
    def __call__(self, event: Mapping[str, object]) -> None:
        """Exclusive bounded private write; return only after persistence acknowledgement.

        Raise on any write/fsync failure. Core suppresses exception prose and
        reports missing acknowledgement separately, never upgrades a score.
        """
        ...


class PrivateBlindAudit:
    """One original blind operation. Retains only metadata/status, never raw answers."""
    def __init__(self, sink: PrivateBlindAuditSink, *, operation: Mapping[str, object] | None = None) -> None:
        self._sink = sink
        self._operation = dict(operation or {})
        self._context: dict[str, object] = {}
        self._sequence = 0
        self._write_failures = 0
        self._build_failures = 0
        self._status: dict[str, object] = dict(schema_version="private_blind_audit_status_v1", enabled=True,
            binding_verified=False, raw_answer_write_acknowledged=False,
            scorer_details_available=False, scorer_details_write_acknowledged=False,
            score_result_write_acknowledged=False, sink_write_failures=0, diagnostic_build_failures=0,
            failure_stage=None, scoring_state="not_entered", audit_failure_code=None,
            private_data_only=True, accounting_authority=False, dispatch_authority=False)

    def _emit(self, kind: PrivateBlindEventKind, details: Mapping[str, object]) -> bool:
        self._sequence += 1
        try:
            event = dict(schema_version="private_blind_diagnostic_event_v1", event_kind=kind,
                sequence=self._sequence, operation=self._operation, **self._context,
                details=dict(details), private_only=True, data_only=True,
                admission_eligible=False, publication_enabled=False,
                accounting_authority=False, dispatch_authority=False)
            encoded = json.dumps(event,ensure_ascii=False,allow_nan=False,separators=(",", ":"))
            if len(encoded.encode("utf8"))>PRIVATE_BLIND_EVENT_MAX_BYTES:
                self._build_failures += 1
                self._status["diagnostic_build_failures"] = self._build_failures
                self._status["audit_failure_code"] = "private_event_bytes_limit"
                return False
            detached = json.loads(encoded)  # Sink cannot mutate scorer/owner objects.
        except Exception:
            self._build_failures += 1
            self._status["diagnostic_build_failures"] = self._build_failures
            self._status["audit_failure_code"] = "private_diagnostic_build_failed"
            return False
        try:
            self._sink(detached)
        except Exception:
            # Failure may follow a partial write: do NOT claim either retained or absent.
            self._write_failures += 1
            self._status["sink_write_failures"] = self._write_failures
            self._status["audit_failure_code"] = "private_sink_write_failed"
            return False
        return True

    def started(self, source: LearningItemSourceV1, binding: CandidateBindingV2, request: BlindSolveInputV2) -> None:
        try:
            binding_data = binding.model_dump(mode="json")
            self._context = dict(binding=binding_data,binding_hash=canonical_hash(binding_data),
                source_hash=source.source_hash,content_hash=source.content_hash,
                request_schema_version=request.schema_version,request_input_hash=request.input_hash,
                run=None,run_hash=None,solution_hash=None)
            self._emit("run_started",dict(checked_result_available=False,raw_answer_state="unavailable"))
        except Exception:
            self._build_failures += 1
            self._status["diagnostic_build_failures"] = self._build_failures
            self._status["audit_failure_code"] = "private_diagnostic_build_failed"

    def before_scoring(self, source: LearningItemSourceV1, binding: CandidateBindingV2,
                       request: BlindSolveInputV2, result: BlindSolveResultV2) -> None:
        """Called ONLY after the original run/result binding verification."""
        self._status["binding_verified"] = True
        try:
            if type(result.answer) is not str or not 1<=len(result.answer)<=PRIVATE_BLIND_RAW_MAX_CHARS:
                raise ValueError("private_answer_limit")
            binding_data,run_data = binding.model_dump(mode="json"),result.run.model_dump(mode="json")
            self._context = dict(binding=binding_data,binding_hash=canonical_hash(binding_data),
                source_hash=source.source_hash,content_hash=source.content_hash,
                request_schema_version=request.schema_version,request_input_hash=request.input_hash,
                run=run_data,run_hash=canonical_hash(run_data),solution_hash=canonical_hash(result.answer))
            self._status["raw_answer_write_acknowledged"] = self._emit("answer_received",dict(
                raw_answer=result.answer,answer_chars=len(result.answer),scorer_reason_state="not_evaluated"))
        except Exception:
            self._build_failures += 1
            self._status["diagnostic_build_failures"] = self._build_failures
            self._status["audit_failure_code"] = "private_diagnostic_build_failed"
        self._status["scoring_state"] = "entered"

    def finite_evaluation(self, details: Mapping[str, object]) -> None:
        self._status["scorer_details_available"] = True
        self._status["scorer_details_write_acknowledged"] = self._emit("finite_static_evaluation",details)

    def finite_details_unavailable(self) -> None:
        self._build_failures += 1
        self._status["diagnostic_build_failures"] = self._build_failures
        self._status["audit_failure_code"] = "finite_diagnostic_unavailable"

    def scored(self, score: BlindScoreV2) -> None:
        self._status["scoring_state"] = "returned"
        self._status["score_result_write_acknowledged"] = self._emit("score_completed",dict(
            score=score.model_dump(mode="json"),score_hash=canonical_hash(score.model_dump(mode="json")),
            scorer_reason_state="computed" if self._status["scorer_details_available"] else "unavailable",
            scorer_details_write_acknowledged=self._status["scorer_details_write_acknowledged"],
            semantic_cause="not_asserted"))

    def failed(self, stage: PrivateBlindFailureStage, observation: Mapping[str, object]) -> None:
        self._status["failure_stage"] = stage
        if stage in {"scoring", "score_receipt"}:
            self._status["scoring_state"] = "exception"
        self._emit("failure",dict(failure_stage=stage,cause="unavailable",
            checked_result_binding_verified=self._status["binding_verified"],
            raw_answer_write_acknowledged=self._status["raw_answer_write_acknowledged"],
            raw_HTTP_or_malformed_JSON_retained=False,
            original_failure_observation=dict(observation)))

    def status(self) -> dict[str, object]:
        return deepcopy(self._status)
