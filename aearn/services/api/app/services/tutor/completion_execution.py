"""Private execution owner for NEW completion-driven Tutor runs.

Preparation, dispatch and result recording each COMMIT before the next boundary.
Recorded results are DATA, never transferable source/lease/action authority.
The caller supplies an idle autocommit connection; provider I/O stays outside it.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from psycopg import Connection
from psycopg.pq import TransactionStatus
from pydantic import TypeAdapter

from app.agents.harness.contracts import (
    TutorExecutionProfile, TutorLease, TutorPolicySnapshot, TutorProviderResult,
    TutorRunResult, TutorRunSnapshot,
    TutorPlanDraftPayloadField, TutorPlanDraftV110PayloadField,
)
from app.agents.runtime.contracts import RuntimePlanningStepResult
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage

if TYPE_CHECKING:
    from app.core.config import Settings

COMPLETION_BATCH_SECONDS = 2400
COMPLETION_BATCH_DECISIONS = 8
COMPLETION_BATCH_HTTP_ATTEMPTS = 16
COMPLETION_RESULT_RESERVE_SECONDS = 60
COMPLETION_POLICY_VERSION = "tutor_completion_driven_v1"
MAX_PRIVATE_JSON_BYTES = 8 * 1024 * 1024
StepKind = Literal["provider_decision", "sidecar_turn"]
StepState = Literal["prepared", "dispatched", "result_recorded", "accepted", "rejected", "not_sent", "outcome_unknown"]
ExecutionResult = TutorProviderResult | TutorRunResult | RuntimePlanningStepResult
_T = TypeVar("_T")
_PROVIDER_RESULT = TypeAdapter(TutorProviderResult)


@dataclass(frozen=True)
class CompletionNestedHTTPOutcome:
    """Private DATA about a separate semantic send, not a Tutor usage receipt."""
    stage: Literal['material_semantic_review']
    request_binding_hash: str | None
    current_scope_http_attempts: int
    from_dispatched_receipt: bool
    model: str | None
    usage: LLMUsage | None
    response_diagnostics: LLMResponseDiagnostics | None = None
    outcome_unknown: Literal[True] = True


@dataclass(frozen=True)
class CompletionTutorProviderResult(TutorProviderResult):
    # Keeps the public/base provider contract unchanged. Only this private codec
    # and the completion owner persist it; no new table/policy/public field.
    nested_http_outcomes: tuple[CompletionNestedHTTPOutcome, ...] = ()


_COMPLETION_PROVIDER_RESULT = TypeAdapter(CompletionTutorProviderResult)
_RUNTIME_RESULT = TypeAdapter(TutorRunResult)
_PLANNING_RESULT = TypeAdapter(RuntimePlanningStepResult)


def _decode_provider_result(payload: str | bytes) -> TutorProviderResult:
    data = json.loads(payload)
    # Parent dataclass annotations otherwise coerce the existing expanded plan
    # fields to ordinary (truncating) fields. Private codec tags preserve types,
    # including small values; they are never passed to a provider/public DTO.
    if isinstance(data, dict):
        tags = data.pop('_completion_transport_fields', [])
        if not isinstance(tags, list):
            raise CompletionExecutionError('completion_result_shape_invalid')
        for tag in tags:
            if not isinstance(tag, list) or len(tag) != 3:
                raise CompletionExecutionError('completion_result_shape_invalid')
            request_index, field_index, version = tag
            if type(request_index) is not int or type(field_index) is not int or version not in ('1.0.0', '1.1.0'):
                raise CompletionExecutionError('completion_result_shape_invalid')
            try:
                request = data['decision']['capability_requests'][request_index]
                field = request['arguments'][field_index]
                field_type = TutorPlanDraftV110PayloadField if version == '1.1.0' else TutorPlanDraftPayloadField
                request['arguments'][field_index] = field_type(**field)
            except (KeyError, IndexError, TypeError) as exc:
                raise CompletionExecutionError('completion_result_shape_invalid') from exc
    if isinstance(data, dict) and 'nested_http_outcomes' in data:
        return _COMPLETION_PROVIDER_RESULT.validate_python(data)
    return _PROVIDER_RESULT.validate_python(data)


class CompletionExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.safe_code = code


@dataclass(frozen=True)
class ExecutionBatch:
    id: str
    run_id: str
    predecessor_batch_id: str | None
    batch_index: int
    issued_at: datetime
    expires_at: datetime
    decision_count: int
    http_attempt_count: int


@dataclass(frozen=True)
class StepAttempt:
    id: str
    run_id: str
    batch_id: str
    step_key: str
    kind: StepKind
    state: StepState
    input_revision: int
    decision_iteration: int
    attempt_number: int
    owner_id: str
    owner_generation: int
    capability_count_before: int
    effect_count_before: int
    observable_http_count: int
    request: Mapping[str, object]
    dependencies: Mapping[str, object]
    result: ExecutionResult | None


def completion_enabled_for(run: TutorRunSnapshot) -> bool:
    return run.policy.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1


def validate_completion_batch_settings(settings: Settings) -> None:
    """These four operator names describe the fixed v1 protocol, not tuning knobs.

    SQL and all owners share 2400/8/16/60. Reject overrides instead of silently
    ignoring them or changing an already-admitted run's immutable policy.
    """
    expected = {
        'tutor_completion_batch_timeout_seconds': COMPLETION_BATCH_SECONDS,
        'tutor_completion_max_decisions': COMPLETION_BATCH_DECISIONS,
        'tutor_completion_max_http_requests': COMPLETION_BATCH_HTTP_ATTEMPTS,
        'tutor_completion_result_reserve_seconds': COMPLETION_RESULT_RESERVE_SECONDS,
    }
    if any(getattr(settings, name) != value for name, value in expected.items()):
        raise CompletionExecutionError('completion_batch_settings_unsupported')


def completion_admission_policy(policy: TutorPolicySnapshot, *, now: datetime,
                                settings: Settings | None = None) -> TutorPolicySnapshot:
    """Admission only: no persisted policy/MVP upgrade and no extra tool/effect rights."""
    if policy.execution_profile is not None:
        raise ValueError("completion admission requires a new unprofiled policy")
    if settings is not None:
        validate_completion_batch_settings(settings)
    return replace(policy, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
                   deadline=now + timedelta(seconds=COMPLETION_BATCH_SECONDS),
                   max_iterations=COMPLETION_BATCH_DECISIONS, max_model_calls=COMPLETION_BATCH_DECISIONS)


def private_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_PRIVATE_JSON_BYTES:
        raise CompletionExecutionError("completion_private_payload_too_large")
    return encoded


def encode_result(result: ExecutionResult) -> tuple[str, str]:
    if isinstance(result, TutorProviderResult):
        kind = 'tutor_provider_result_v1'
        payload = (_COMPLETION_PROVIDER_RESULT.dump_json(result, warnings='error')
                   if isinstance(result, CompletionTutorProviderResult) else _PROVIDER_RESULT.dump_json(result, warnings='error'))
        tags = [[i, j, '1.1.0' if isinstance(field, TutorPlanDraftV110PayloadField) else '1.0.0']
                for i, request in enumerate(result.decision.capability_requests if result.decision else ())
                for j, field in enumerate(request.arguments) if isinstance(field, TutorPlanDraftPayloadField)]
        if tags:
            data = json.loads(payload)
            data['_completion_transport_fields'] = tags
            payload = private_json(data).encode('utf-8')
        restored: ExecutionResult = _decode_provider_result(payload)
    elif isinstance(result, TutorRunResult):
        kind, payload = "tutor_run_result_v1", _RUNTIME_RESULT.dump_json(result, warnings="error")
        restored = _RUNTIME_RESULT.validate_json(payload)
    elif isinstance(result, RuntimePlanningStepResult):
        kind, payload = "runtime_planning_step_result_v1", _PLANNING_RESULT.dump_json(result, warnings="error")
        restored = _PLANNING_RESULT.validate_json(payload)
    else:
        raise CompletionExecutionError("completion_result_type_invalid")
    if restored != result:
        raise CompletionExecutionError("completion_result_roundtrip_invalid")
    private_json(json.loads(payload))
    return kind, payload.decode("utf-8")


def decode_result(kind: str, payload: object) -> ExecutionResult:
    if kind == "tutor_provider_result_v1":
        result: ExecutionResult = _decode_provider_result(private_json(payload))
    elif kind == "tutor_run_result_v1":
        result = _RUNTIME_RESULT.validate_json(private_json(payload))
    elif kind == "runtime_planning_step_result_v1":
        result = _PLANNING_RESULT.validate_json(private_json(payload))
    else:
        raise CompletionExecutionError("completion_result_type_invalid")
    if json.loads(encode_result(result)[1]) != payload:
        raise CompletionExecutionError("completion_result_shape_invalid")
    return result


class CompletionExecutionOwner:
    """Shared ordinary-loop/sidecar owner; now never overrides postlock DB time."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def _idle(self) -> None:
        if not self._conn.autocommit or self._conn.info.transaction_status != TransactionStatus.IDLE:
            raise CompletionExecutionError("completion_prior_commit_required")

    def _clock(self) -> datetime:
        row = self._conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if row is None or not isinstance(row["now"], datetime):
            raise CompletionExecutionError("completion_clock_unavailable")
        return row["now"]

    def _lock_run(self, run: TutorRunSnapshot, lease: TutorLease) -> tuple[dict[str, object], datetime]:
        if not completion_enabled_for(run):
            raise CompletionExecutionError("completion_profile_required")
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id=%s AND user_id=%s AND conversation_id=%s FOR UPDATE",
            (run.run_id, run.user_id, run.conversation_id),
        ).fetchone()
        now = self._clock()
        policy = row.get("policy_json") if row else None
        if (row is None or not isinstance(policy, dict)
                or policy.get("execution_profile") != TutorExecutionProfile.COMPLETION_DRIVEN_V1.value
                or str(row["policy_version"]) != COMPLETION_POLICY_VERSION
                or row["input_revision"] != run.input_revision or lease.run_id != run.run_id
                or str(row.get("active_lease_owner_id")) != lease.owner_id
                or row.get("active_lease_generation") != lease.generation
                or not isinstance(row.get("active_lease_expires_at"), datetime)
                or cast(datetime, row["active_lease_expires_at"]) <= now
                or row.get("terminal_outcome") is not None or row.get("cancelled_at") is not None
                or row.get("superseded_by_run_id") is not None):
            raise CompletionExecutionError("completion_current_owner_required")
        return row, now

    def _step(self, run: TutorRunSnapshot, step: StepAttempt) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_run_step_attempts WHERE id=%s AND run_id=%s AND user_id=%s AND conversation_id=%s FOR UPDATE",
            (step.id, run.run_id, run.user_id, run.conversation_id),
        ).fetchone()
        if row is None or row["input_revision"] != run.input_revision:
            raise CompletionExecutionError("completion_step_scope_invalid")
        return row

    def assert_current(self, *, run: TutorRunSnapshot, lease: TutorLease) -> None:
        self._idle()
        with self._conn.transaction():
            self._lock_run(run, lease)

    def ensure_batch(self, *, run: TutorRunSnapshot, lease: TutorLease,
                     now: datetime | None = None, minimum_seconds: float = 0,
                     minimum_http_attempts: int = 1) -> ExecutionBatch:
        del now
        if not 0 <= minimum_seconds <= COMPLETION_BATCH_SECONDS - COMPLETION_RESULT_RESERVE_SECONDS:
            raise CompletionExecutionError("completion_stage_window_invalid")
        if not 0 <= minimum_http_attempts <= COMPLETION_BATCH_HTTP_ATTEMPTS:
            raise CompletionExecutionError("completion_http_window_invalid")
        self._idle()
        with self._conn.transaction():
            facts, fresh = self._lock_run(run, lease)
            latest = self._conn.execute(
                "SELECT * FROM tutor_run_execution_batches WHERE run_id=%s ORDER BY batch_index DESC LIMIT 1 FOR UPDATE",
                (run.run_id,),
            ).fetchone()
            if latest is not None:
                batch = _batch(latest)
                if (batch.expires_at > fresh + timedelta(seconds=minimum_seconds + COMPLETION_RESULT_RESERVE_SECONDS)
                        and latest["owner_id"] == lease.owner_id and latest["owner_generation"] == lease.generation
                        and batch.decision_count < COMPLETION_BATCH_DECISIONS
                        and batch.http_attempt_count + minimum_http_attempts <= COMPLETION_BATCH_HTTP_ATTEMPTS):
                    return batch
            unresolved = self._conn.execute(
                "SELECT id FROM tutor_run_step_attempts WHERE run_id=%s AND state IN ('prepared','dispatched','outcome_unknown') LIMIT 1",
                (run.run_id,),
            ).fetchone()
            if unresolved is not None:
                raise CompletionExecutionError("completion_unresolved_attempt")
            fresh = self._clock()
            row = self._conn.execute(
                """INSERT INTO tutor_run_execution_batches
                (run_id,user_id,conversation_id,input_revision,predecessor_batch_id,batch_index,
                 owner_id,owner_generation,policy_fingerprint,issued_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (run.run_id, run.user_id, run.conversation_id, run.input_revision,
                 latest["id"] if latest else None, int(cast(int, latest["batch_index"])) + 1 if latest else 1,
                 lease.owner_id, lease.generation, facts["policy_fingerprint"], fresh,
                 fresh + timedelta(seconds=COMPLETION_BATCH_SECONDS)),
            ).fetchone()
            return _batch(_required(row))

    def pending_step(self, *, run: TutorRunSnapshot, lease: TutorLease) -> StepAttempt | None:
        self._idle()
        with self._conn.transaction():
            self._lock_run(run, lease)
            row = self._conn.execute(
                "SELECT * FROM tutor_run_step_attempts WHERE run_id=%s AND state IN ('prepared','dispatched','result_recorded','outcome_unknown') FOR UPDATE",
                (run.run_id,),
            ).fetchone()
            return _attempt(row) if row is not None else None

    def prepare_step(self, *, run: TutorRunSnapshot, lease: TutorLease, batch: ExecutionBatch,
                     step_key: str, kind: StepKind, request: Mapping[str, object],
                     dependencies: Mapping[str, object], now: datetime | None = None) -> StepAttempt:
        del now
        request_json, deps_json = private_json(request), private_json(dependencies)
        if kind not in ("provider_decision", "sidecar_turn") or not 1 <= len(step_key) <= 160:
            raise CompletionExecutionError("completion_step_identity_invalid")
        self._idle()
        with self._conn.transaction():
            facts, _ = self._lock_run(run, lease)
            previous = self._conn.execute(
                "SELECT * FROM tutor_run_step_attempts WHERE run_id=%s AND step_key=%s ORDER BY attempt_number DESC LIMIT 1 FOR UPDATE",
                (run.run_id, step_key),
            ).fetchone()
            if previous is None and "progress_identity" in request:
                repeated = self._conn.execute(
                    """SELECT id FROM tutor_run_step_attempts WHERE run_id=%s AND state IN ('accepted','rejected')
                    AND request_json->'progress_identity'=%s::jsonb AND dependencies_json=%s::jsonb LIMIT 1""",
                    (run.run_id, private_json(request["progress_identity"]), deps_json),
                ).fetchone()
                if repeated is not None:
                    raise CompletionExecutionError("completion_no_progress")
            if previous is not None:
                if (previous["request_json"] != json.loads(request_json)
                        or previous["dependencies_json"] != json.loads(deps_json) or previous["kind"] != kind):
                    raise CompletionExecutionError("completion_step_identity_conflict")
                if previous["state"] in ("result_recorded", "accepted"):
                    return _attempt(previous)
                if previous["state"] == "prepared":
                    if previous["owner_id"] == lease.owner_id and previous["owner_generation"] == lease.generation:
                        return _attempt(previous)
                    self._conn.execute(
                        "UPDATE tutor_run_step_attempts SET state='not_sent',diagnostic_code='prepared_owner_replaced' WHERE id=%s",
                        (previous["id"],),
                    )
                elif previous["state"] != "not_sent":
                    raise CompletionExecutionError("completion_unresolved_attempt")
            row = self._conn.execute(
                """INSERT INTO tutor_run_step_attempts
                (run_id,user_id,conversation_id,input_revision,batch_id,step_key,kind,decision_iteration,
                 attempt_number,predecessor_attempt_id,owner_id,owner_generation,request_json,dependencies_json,
                 capability_count_before,effect_count_before,prepared_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s) RETURNING *""",
                (run.run_id, run.user_id, run.conversation_id, run.input_revision, batch.id, step_key, kind,
                 previous["decision_iteration"] if previous else int(cast(int, facts["model_call_count"])) + 1,
                 int(cast(int, previous["attempt_number"])) + 1 if previous else 1,
                 previous["id"] if previous else None, lease.owner_id, lease.generation,
                 request_json, deps_json, facts["capability_call_count"], facts["effect_count"], self._clock()),
            ).fetchone()
            return _attempt(_required(row))

    def mark_dispatched(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt,
                        now: datetime | None = None) -> StepAttempt:
        del now
        self._idle()
        with self._conn.transaction():
            self._lock_run(run, lease)
            current = self._step(run, step)
            if (current["state"] != "prepared" or current["owner_id"] != lease.owner_id
                    or current["owner_generation"] != lease.generation):
                raise CompletionExecutionError("completion_dispatch_fenced")
            row = self._conn.execute(
                "UPDATE tutor_run_step_attempts SET state='dispatched',dispatched_at=clock_timestamp() WHERE id=%s RETURNING *", (step.id,),
            ).fetchone()
            self._conn.execute(
                "UPDATE tutor_runs SET model_call_count=GREATEST(model_call_count,%s),iteration_count=GREATEST(iteration_count,%s) WHERE id=%s",
                (step.decision_iteration, step.decision_iteration, run.run_id),
            )
            return _attempt(_required(row))

    def record_http_attempt(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt,
                            batch: ExecutionBatch | None = None) -> None:
        """Observable send intent; transport starts only AFTER this COMMIT."""
        self._idle()
        with self._conn.transaction():
            self._lock_run(run, lease)
            current = self._step(run, step)
            if (current["state"] not in ("dispatched", "result_recorded")
                    or (current["state"] == "dispatched" and (
                        current["owner_id"] != lease.owner_id or current["owner_generation"] != lease.generation))):
                raise CompletionExecutionError("completion_dispatch_fenced")
            self._conn.execute(
                """UPDATE tutor_run_step_attempts SET observable_http_count=observable_http_count+1,
                http_batch_ids_json=http_batch_ids_json || jsonb_build_array(%s::uuid) WHERE id=%s""",
                (batch.id if batch is not None else step.batch_id, step.id),
            )

    def record_result(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt,
                      result: ExecutionResult, outcome_unknown: bool = False) -> StepAttempt:
        """Late original workers can record facts, never consume with an old lease."""
        outcome_unknown = outcome_unknown or (
            isinstance(result, CompletionTutorProviderResult)
            and any(item.outcome_unknown for item in result.nested_http_outcomes)
        ) or (
            isinstance(result, TutorProviderResult) and result.safe_code is not None
            and '_http_unknown_' in result.safe_code
        )
        result_type, payload = encode_result(result)
        if (step.kind == "provider_decision") != isinstance(result, TutorProviderResult):
            raise CompletionExecutionError("completion_result_type_invalid")
        self._idle()
        with self._conn.transaction():
            current = self._step(run, step)
            if lease.run_id != run.run_id or current["owner_id"] != lease.owner_id or current["owner_generation"] != lease.generation:
                raise CompletionExecutionError("completion_dispatch_fenced")
            if current["result_json"] is not None:
                if (current["result_json"] != json.loads(payload) or current["result_type"] != result_type
                        or (current["state"] == "outcome_unknown") != outcome_unknown):
                    raise CompletionExecutionError("completion_result_immutable")
                return _attempt(current)
            if current["state"] != "dispatched":
                raise CompletionExecutionError("completion_result_without_dispatch")
            row = self._conn.execute(
                """UPDATE tutor_run_step_attempts SET state=%s,result_type=%s,result_json=%s::jsonb,
                result_recorded_at=clock_timestamp() WHERE id=%s RETURNING *""",
                ("outcome_unknown" if outcome_unknown else "result_recorded", result_type, payload, step.id),
            ).fetchone()
            return _attempt(_required(row))

    def mark_unknown(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt) -> None:
        self._idle()
        with self._conn.transaction():
            current = self._step(run, step)
            if lease.run_id != run.run_id or current["owner_id"] != lease.owner_id or current["owner_generation"] != lease.generation:
                raise CompletionExecutionError("completion_dispatch_fenced")
            if current["state"] != "dispatched":
                raise CompletionExecutionError("completion_unknown_transition_invalid")
            self._conn.execute("UPDATE tutor_run_step_attempts SET state='outcome_unknown' WHERE id=%s", (step.id,))

    def mark_not_sent(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt) -> None:
        self._idle()
        with self._conn.transaction():
            self._lock_run(run, lease)
            if self._step(run, step)["state"] != "prepared":
                raise CompletionExecutionError("completion_no_send_proof_required")
            self._conn.execute(
                "UPDATE tutor_run_step_attempts SET state='not_sent',diagnostic_code='prepared_not_dispatched' WHERE id=%s", (step.id,),
            )

    def accept_result(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt, batch: ExecutionBatch,
                      dependencies: Mapping[str, object], validate: Callable[[], None],
                      consume: Callable[[], _T]) -> _T:
        """Fresh validation + DB-only lawful consumer + acceptance COMMIT together.

        Capability owners execute beforehand using their original stable receipt
        identity. On crash these owners read receipts, never replay side effects.
        """
        self._idle()
        with self._conn.transaction():
            self._lock_run(run, lease)
            current = self._step(run, step)
            if current["state"] != "result_recorded" or current["dependencies_json"] != dict(dependencies):
                raise CompletionExecutionError("completion_result_not_consumable")
            validate()
            self._lock_run(run, lease)
            self._conn.execute(
                """UPDATE tutor_run_step_attempts SET state='accepted',accepted_at=clock_timestamp(),
                accepted_owner_id=%s,accepted_owner_generation=%s,acceptance_batch_id=%s WHERE id=%s""",
                (lease.owner_id, lease.generation, batch.id, step.id),
            )
            self._conn.execute(
                "UPDATE tutor_runs SET capability_call_count=GREATEST(capability_call_count,%s),effect_count=GREATEST(effect_count,%s) WHERE id=%s",
                (run.capability_call_count, run.effect_count, run.run_id),
            )
            return consume()

    def action_progress(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt,
                        capability_count: int | None = None, effect_count: int | None = None,
                        request_id: str | None = None) -> TutorRunSnapshot:
        """Reconcile logical action ordinals without resetting cumulative counters.

        Capability intents are charged before entering their original owner. Its
        durable invocation without a terminal receipt is UNKNOWN, not retryable.
        DB-only effects are reconciled AFTER their original atomic commit, which
        already increments the physical counter. Neither path executes an action.
        """
        self._idle()
        with self._conn.transaction():
            facts, _ = self._lock_run(run, lease)
            current = self._step(run, step)
            if current['state'] != 'result_recorded' or current['kind'] != 'provider_decision':
                raise CompletionExecutionError('completion_action_without_result')
            if request_id is not None:
                action = self._conn.execute(
                    """SELECT a.id,r.receipt_json,r.diagnostic_code FROM tutor_action_invocations a
                    LEFT JOIN tutor_action_receipts r ON r.invocation_id=a.id
                    WHERE a.run_id=%s AND a.user_id=%s AND a.input_revision=%s AND a.idempotency_key=%s""",
                    (run.run_id, run.user_id, run.input_revision, request_id),
                ).fetchone()
                diagnostic = str(action.get('diagnostic_code') or '') if action is not None else ''
                if action is not None and (action['receipt_json'] is None or '_http_unknown_' in diagnostic
                                           or 'outcome_unknown' in diagnostic):
                    raise CompletionExecutionError('completion_action_outcome_unknown')
            capabilities = max(int(cast(int, facts['capability_call_count'])), run.capability_call_count,
                               capability_count if capability_count is not None else 0)
            effects = max(int(cast(int, facts['effect_count'])), run.effect_count,
                          effect_count if effect_count is not None else 0)
            if capabilities > run.policy.max_capability_calls or effects > run.policy.max_effects:
                raise CompletionExecutionError('completion_action_budget_exhausted')
            self._conn.execute(
                "UPDATE tutor_runs SET capability_call_count=GREATEST(capability_call_count,%s),effect_count=GREATEST(effect_count,%s) WHERE id=%s",
                (capabilities, effects, run.run_id),
            )
            return replace(run, capability_call_count=capabilities, effect_count=effects)

    def reject_result(self, *, run: TutorRunSnapshot, lease: TutorLease, step: StepAttempt, diagnostic_code: str) -> None:
        if not diagnostic_code.isascii() or not diagnostic_code.replace("_", "").isalnum() or len(diagnostic_code) > 120:
            raise ValueError("completion diagnostic must be a safe code")
        self._idle()
        with self._conn.transaction():
            self._lock_run(run, lease)
            if self._step(run, step)["state"] != "result_recorded":
                raise CompletionExecutionError("completion_result_not_rejectable")
            self._conn.execute("UPDATE tutor_run_step_attempts SET state='rejected',diagnostic_code=%s WHERE id=%s", (diagnostic_code, step.id))


def _required(row: dict[str, object] | None) -> dict[str, object]:
    if row is None:
        raise CompletionExecutionError("completion_write_missing")
    return row


def _batch(row: Mapping[str, object]) -> ExecutionBatch:
    return ExecutionBatch(str(row["id"]), str(row["run_id"]),
                          str(row["predecessor_batch_id"]) if row["predecessor_batch_id"] else None,
                          int(cast(int, row["batch_index"])), cast(datetime, row["issued_at"]),
                          cast(datetime, row["expires_at"]), int(cast(int, row["decision_count"])),
                          int(cast(int, row["http_attempt_count"])))


def _attempt(row: Mapping[str, object]) -> StepAttempt:
    return StepAttempt(
        id=str(row["id"]), run_id=str(row["run_id"]), batch_id=str(row["batch_id"]),
        step_key=str(row["step_key"]), kind=cast(StepKind, row["kind"]), state=cast(StepState, row["state"]),
        input_revision=int(cast(int, row["input_revision"])), decision_iteration=int(cast(int, row["decision_iteration"])),
        attempt_number=int(cast(int, row["attempt_number"])), owner_id=str(row["owner_id"]),
        owner_generation=int(cast(int, row["owner_generation"])),
        capability_count_before=int(cast(int, row["capability_count_before"])),
        effect_count_before=int(cast(int, row["effect_count_before"])),
        observable_http_count=int(cast(int, row["observable_http_count"])),
        request=cast(Mapping[str, object], row["request_json"]), dependencies=cast(Mapping[str, object], row["dependencies_json"]),
        result=decode_result(str(row["result_type"]), row["result_json"]) if row["result_json"] is not None else None,
    )
