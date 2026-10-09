"""One-terminal blind-answer scorer over the existing sealed OS runner.

No provider/DB/Docker imports and no host execution. Raw answers and runner
stdout are ephemeral; issued artifacts contain bindings/hashes/status/usage,
not answer code, expected outputs, hidden datasets or provider bodies.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, cast
from uuid import uuid4

from aearn_shared.execution import SafeExecutionStatus

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import (
    BlindScoreV2, CandidateBindingV2, check_subject,
)
from app.services.learning.item_supply.sandbox.execution import (
    SandboxCandidateExecutionPort, _Request, _candidate_cases, _wire,
)
from app.services.learning.item_supply.sandbox.execution_contracts import (
    EXECUTION_WALL_SECONDS, RunnerPort, RunnerTerminalReceipt,
)
from aearn_shared.execution import SandboxInputV1
from app.services.learning.item_supply.sandbox.python_goal_scorer import source_scorer_version
from app.services.learning.item_supply.sandbox.probe_plans import build_candidate_probe_plan
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1

BLIND_SCORER_IDENTITY = "item-supply-os-blind-scorer"


@dataclass(frozen=True)
class _IssuedScore:
    score: BlindScoreV2
    source_hash: str
    binding_hash: str
    terminal: dict[str, object]
    receipt: RunnerTerminalReceipt
    request: SandboxInputV1


class SandboxBlindAnswerScorer:
    """Implements BlindAnswerScorerPortV2.score without changing review owners.

    The caller reserves ten execution seconds before score; settlement and final
    lease/source/epoch fences remain caller-owned. A launch with no trusted
    terminal retains unknown usage, rather than inventing zero or retrying it.
    """

    def __init__(self, runner: RunnerPort, *, binding: CandidateBindingV2, parent_deadline_at: datetime, clock: Callable[[], datetime] | None = None, finite_spec: FiniteCandidateSpecV1 | None = None) -> None:
        if parent_deadline_at.tzinfo is None:
            raise ValueError("blind_execution_deadline_timezone_required")
        self._runner = runner
        self._finite_spec: FiniteCandidateSpecV1 | None = None
        if finite_spec is not None:
            from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1

            self._finite_spec = checked_model(finite_spec, FiniteCandidateSpecV1)
        self._binding = checked_model(binding, CandidateBindingV2)
        self._binding_hash = canonical_hash(self._binding.model_dump(mode="json"))
        self._deadline = parent_deadline_at
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._issued: dict[str, _IssuedScore] = {}
        self._keys: dict[str, str] = {}
        self._attempted: set[str] = set()
        self._terminals: dict[str, dict[str, object]] = {}

    def _check_deadline(self, seconds: int) -> None:
        if (self._deadline - self._clock()).total_seconds() < seconds:
            raise ValueError("blind_execution_frozen_deadline_exceeded")

    def _source(self, source: LearningItemSourceV1) -> LearningItemSourceV1:
        source = checked_model(source, LearningItemSourceV1)
        check_subject(source, self._binding)
        # Pure plan/oracle validation only. Never validate/run the full profile.
        if self._finite_spec is None:
            build_candidate_probe_plan(source)
        else:
            from app.services.learning.item_supply.sandbox.finite_probe_plans import build_finite_candidate_probe_plan

            build_finite_candidate_probe_plan(source, spec=self._finite_spec)
            if source_scorer_version(source) != self._finite_spec.coverage_blueprint.scope.scorer_version:
                raise ValueError("finite_blind_scorer_mismatch")
        return source

    def resource_plan(self, source: LearningItemSourceV1) -> ResourceAmounts:
        self._source(source)
        self._check_deadline(EXECUTION_WALL_SECONDS + 5)
        return ResourceAmounts(execution_seconds=EXECUTION_WALL_SECONDS + 5)

    def score(self, source: LearningItemSourceV1, *, answer: str) -> BlindScoreV2:
        source = self._source(source)
        if not isinstance(answer, str) or not 1 <= len(answer) <= 48_000:
            raise ValueError("blind_answer_input_invalid")
        answer_hash = canonical_hash({"answer": answer})
        key = canonical_hash({"source_hash": source.source_hash, "binding_hash": self._binding_hash, "answer_hash": answer_hash})
        previous = self._keys.get(key)
        if previous is not None:
            return self._issued[previous].score
        if key in self._attempted:
            raise ValueError("blind_execution_launch_uncertain")
        if self._finite_spec is not None and self._attempted:
            raise ValueError("finite_blind_answer_allowance_spent")
        _, _, cases, tests = _candidate_cases(source)
        # The answer exists only in this local wire during the one runner call.
        wire = _wire(source, answer, cases)
        task = _Request("blind_answer", wire, "pass", tests)
        self._check_deadline(EXECUTION_WALL_SECONDS + 5)
        self._attempted.add(key)
        run_id = uuid4()
        receipt = self._runner.run(request=wire, run_id=run_id, probe_name="blind_answer")
        if (receipt.run_id, receipt.probe_name, receipt.request_hash) != (run_id, "blind_answer", canonical_hash(wire.model_dump(mode="json"))) or not self._runner.verify(receipt, request=wire):
            raise ValueError("blind_runner_terminal_untrusted")
        if not math.isfinite(receipt.elapsed_seconds) or receipt.elapsed_seconds < 0:
            raise ValueError("blind_runner_usage_unknown")
        # No stdout/stderr/raw answer/expected value is copied into artifacts.
        terminal: dict[str, object] = {
            "source_hash": source.source_hash, "content_hash": source.content_hash,
            "binding_hash": self._binding_hash, "answer_hash": answer_hash,
            "run_id": str(receipt.run_id), "probe_name": receipt.probe_name,
            "request_hash": receipt.request_hash, "terminal_hash": canonical_hash(receipt.to_payload()),
            "lock_fingerprint": receipt.lock_fingerprint, "seal": receipt.seal,
            "mode": receipt.mode, "isolation": receipt.isolation,
            "result_status": receipt.result.status.value, "elapsed_seconds": receipt.elapsed_seconds,
        }
        self._terminals[key] = terminal
        self._check_deadline(0)
        if (self._finite_spec is not None
                and receipt.lock_fingerprint != self._finite_spec.coverage_blueprint.scope.runtime_profile_hash):
            raise ValueError("finite_blind_runtime_lock_mismatch")
        if receipt.mode != "live" or receipt.isolation != "approved_os_boundary" or receipt.lock_fingerprint == "0" * 64:
            raise ValueError("blind_execution_live_os_required")
        if receipt.result.status is not SafeExecutionStatus.SUCCESS:
            # No fixed-adapter facts: infrastructure failure is not an answer
            # rejection. Wrong code/query still has a successful facts envelope
            # with per-case python_terminal/sql_rejected outcomes to score.
            terminal["scorer_status"] = "pending"
            raise ValueError("blind_answer_execution_pending")
        # Reuse exactly the existing stdout/SQL comparisons + practice scorer.
        status = SandboxCandidateExecutionPort(self._runner, finite_spec=self._finite_spec)._probe_status(source, task, receipt)
        terminal["scorer_status"] = status
        if status == "pending":
            raise ValueError("blind_answer_execution_pending")
        scorer = source_scorer_version(source)
        receipt_hash = canonical_hash({"binding": self._binding.model_dump(mode="json"), "terminal": terminal, "scorer": scorer})
        score = BlindScoreV2(passed=status == "passed", scorer_identity=BLIND_SCORER_IDENTITY, scorer_version=scorer, receipt_hash=receipt_hash)
        self._issued[receipt_hash] = _IssuedScore(score, source.source_hash, self._binding_hash, terminal, receipt, wire)
        self._keys[key] = receipt_hash
        return score

    def verify(self, score: BlindScoreV2, source: LearningItemSourceV1) -> bool:
        """Authenticate this issuer's already sealed/graded opaque result."""
        try:
            score = checked_model(score, BlindScoreV2)
            source = self._source(source)
            issued = self._issued.get(score.receipt_hash)
            if issued is None or issued.score != score or issued.source_hash != source.source_hash or issued.binding_hash != self._binding_hash:
                return False
            if (self._finite_spec is not None and issued.receipt.lock_fingerprint
                    != self._finite_spec.coverage_blueprint.scope.runtime_profile_hash):
                return False
            if not self._runner.verify(issued.receipt, request=issued.request) or issued.terminal["terminal_hash"] != canonical_hash(issued.receipt.to_payload()):
                return False
            _, _, cases, tests = _candidate_cases(source)
            task = _Request("blind_answer", _wire(source, issued.request.submission, cases), "pass", tests)
            status = SandboxCandidateExecutionPort(self._runner, finite_spec=self._finite_spec)._probe_status(source, task, issued.receipt)
            return (task.wire == issued.request and status != "pending" and score.passed == (status == "passed")
                and score.scorer_version == source_scorer_version(source)
                and score.receipt_hash == canonical_hash({"binding": self._binding.model_dump(mode="json"), "terminal": issued.terminal, "scorer": source_scorer_version(source)}))
        except (ValueError, TypeError, AttributeError):
            return False

    def resource_usage(self, score: BlindScoreV2 | None = None) -> ResourceAmounts:
        if score is not None:
            issued = self._issued.get(score.receipt_hash)
            if issued is None or issued.score != score:
                raise ValueError("blind_runner_usage_unknown")
            terminals = [issued.terminal]
        else:
            if self._attempted - self._terminals.keys():
                raise ValueError("blind_runner_usage_unknown")
            terminals = list(self._terminals.values())
        return ResourceAmounts(execution_seconds=sum(math.ceil(cast(float, terminal["elapsed_seconds"])) for terminal in terminals))

    def receipts(self, score: BlindScoreV2 | None = None) -> tuple[dict[str, object], ...]:
        if score is not None:
            issued = self._issued.get(score.receipt_hash)
            if issued is None or issued.score != score:
                raise ValueError("blind_runner_receipts_unavailable")
            return (dict(issued.terminal),)
        return tuple(dict(terminal) for terminal in self._terminals.values())
