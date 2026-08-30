"""数据库行、payload、cursor 与通用值转换。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._dependencies import *
from .contracts import *


def _protocol_version_from_row(row: Mapping[str, object]) -> TutorInteractionProtocolVersion:
    raw = str(row.get("interaction_protocol_version") or TutorInteractionProtocolVersion.LEGACY_V1.value)
    try:
        return TutorInteractionProtocolVersion(raw)
    except ValueError:
        return TutorInteractionProtocolVersion.LEGACY_V1


def _validate_conversation_event_identity(
    *,
    kind: TutorConversationEventKind,
    payload: Mapping[str, object],
    turn_id: str | None,
    item_id: str | None,
    item_kind: str | None,
) -> None:
    if (item_id is None) != (item_kind is None):
        raise ValueError("conversation event item identity is incomplete")
    if kind in {TutorConversationEventKind.TURN_CREATED, TutorConversationEventKind.TURN_UPDATED}:
        turn = _as_mapping(payload.get("turn"))
        if _optional_string(turn.get("turn_id")) != turn_id or item_id is not None:
            raise ValueError("conversation turn event identity does not match its payload")
        return
    if kind in {TutorConversationEventKind.ITEM_ADDED, TutorConversationEventKind.ITEM_UPDATED}:
        item = _as_mapping(payload.get("item"))
        if (
            _optional_string(item.get("turn_id")) != turn_id
            or _optional_string(item.get("item_id")) != item_id
            or _optional_string(item.get("item_kind")) != item_kind
        ):
            raise ValueError("conversation item event identity does not match its payload")
        return
    if kind is TutorConversationEventKind.TURN_OUTPUT:
        if turn_id is None or item_id is not None:
            raise ValueError("conversation turn-output event requires only a turn identity")
        return
    if kind is TutorConversationEventKind.CONTROL_UPDATED:
        if turn_id is not None or item_id is not None:
            raise ValueError("conversation control event cannot reference a turn or item")
        return
    if turn_id is None:
        raise ValueError("conversation dispatch event requires a turn")
    if kind is TutorConversationEventKind.DISPATCH_DELAYED and item_id is not None:
        raise ValueError("delayed dispatch event cannot reference an item")
    if kind is TutorConversationEventKind.DISPATCH_DEAD and (item_id is None or item_kind != "error"):
        raise ValueError("dead dispatch event requires its public error item identity")


def _conversation_event_from_row(
    row: Mapping[str, object],
    *,
    cursor: str,
) -> TutorConversationEvent:
    kind = TutorConversationEventKind(str(row["kind"]))
    payload = validate_conversation_event_payload(kind, _as_mapping(row.get("payload_json")))
    return TutorConversationEvent(
        event_id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        sequence=_as_int(row.get("event_sequence"), 0),
        event_key=str(row["event_key"]),
        kind=kind,
        turn_id=_optional_string(row.get("turn_id")),
        item_id=_optional_string(row.get("item_id")),
        item_kind=_optional_string(row.get("item_kind")),
        payload=payload,
        occurred_at=_as_datetime(row.get("occurred_at")) or datetime.now(UTC),
        cursor=cursor,
    )


def _interactive_dispatch_job_from_row(row: Mapping[str, object]) -> TutorInteractiveDispatchJob:
    return TutorInteractiveDispatchJob(
        job_id=str(row["id"]),
        run_id=str(row["run_id"]),
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        state=TutorDispatchJobState(str(row["state"])),
        attempt_count=_as_int(row.get("attempt_count"), 0),
        max_attempts=_as_int(row.get("max_attempts"), _DISPATCH_JOB_MAX_ATTEMPTS),
        available_at=_as_datetime(row.get("available_at")) or datetime.now(UTC),
        lease_owner_id=_optional_string(row.get("lease_owner_id")),
        lease_generation=_as_int(row.get("lease_generation"), 0),
        lease_expires_at=_as_datetime(row.get("lease_expires_at")),
        last_error_code=_optional_string(row.get("last_error_code")),
        completed_at=_as_datetime(row.get("completed_at")),
        dead_at=_as_datetime(row.get("dead_at")),
    )


def _trace_from_row(row: Mapping[str, object], *, projector: TutorSafeProjection) -> TutorTraceRecord:
    created_at = _as_datetime(row.get("created_at")) or datetime.now(UTC)
    header = projector.export(
        {
            "trace_id": str(row.get("id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "kind": row.get("kind"),
            "event_from_sequence": _as_int(row.get("event_from_sequence"), 0),
            "event_to_sequence": _as_int(row.get("event_to_sequence"), 0),
        }
    )
    trace_kind = str(header.get("kind") or "")
    return TutorTraceRecord(
        trace_id=str(header.get("trace_id") or "invalid_trace"),
        run_id=str(header.get("run_id") or "invalid_run"),
        kind=trace_kind if trace_kind in _TRACE_KINDS else "invalid_trace",
        event_from_sequence=_as_int(header.get("event_from_sequence"), 0),
        event_to_sequence=_as_int(header.get("event_to_sequence"), 0),
        payload=projector.export(row.get("trace_json")),
        created_at=created_at,
    )


def _event_from_row(row: Mapping[str, object], *, projector: TutorSafeProjection) -> TutorDurableEvent:
    created_at = _as_datetime(row.get("created_at")) or datetime.now(UTC)
    header = projector.export(
        {
            "event_id": str(row.get("id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "event_sequence": _as_int(row.get("event_sequence"), 0),
            "event_key": row.get("event_key"),
            "kind": row.get("kind"),
            "input_revision": _as_int(row.get("input_revision"), 0),
        }
    )
    event_kind = str(header.get("kind") or "")
    return TutorDurableEvent(
        event_id=str(header.get("event_id") or "invalid_event"),
        run_id=str(header.get("run_id") or "invalid_run"),
        event_sequence=_as_int(header.get("event_sequence"), 0),
        event_key=str(header.get("event_key") or "invalid_event_key"),
        kind=event_kind if event_kind in _DURABLE_EVENT_KINDS else "invalid_event",
        input_revision=_as_int(header.get("input_revision"), 0),
        payload=projector.export(row.get("payload_json")),
        created_at=created_at,
    )


def _provider_attempt_record_from_row(row: Mapping[str, object]) -> TutorProviderAttemptRecord:
    usage = None
    if bool(row.get("usage_available")):
        usage = LLMUsage(
            input_tokens=_as_optional_int(row.get("input_tokens")),
            cached_input_tokens=_as_optional_int(row.get("cached_input_tokens")),
            output_tokens=_as_optional_int(row.get("output_tokens")),
            total_tokens=_as_optional_int(row.get("reported_total_tokens")),
            reasoning_tokens=_as_optional_int(row.get("reasoning_tokens")),
        )
    return TutorProviderAttemptRecord(
        receipt_id=str(row["id"]),
        run_id=str(row["run_id"]),
        input_revision=_as_int(row.get("input_revision"), 0),
        decision_iteration=_as_int(row.get("decision_iteration"), 0),
        attempt=TutorProviderAttemptReceipt(
            attempt_index=_as_int(row.get("attempt_index"), 0),
            outcome=TutorProviderAttemptOutcome(str(row["outcome"])),
            provider_type=str(row["provider_type"]),
            protocol=str(row["protocol"]),
            model=str(row["model"]) if row.get("model") is not None else None,
            usage=usage,
            diagnostic_code=(
                str(row["diagnostic_code"])
                if row.get("diagnostic_code") is not None
                else None
            ),
        ),
        created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
    )


def _selection_from_row(row: Mapping[str, object]) -> tuple[str, int, str, str, str, str, str]:
    return (
        str(row["run_id"]),
        _as_int(row["input_revision"], 0),
        str(row["skill_id"]),
        str(row["skill_version"]),
        str(row["manifest_hash"]),
        str(row["instruction_hash"]),
        str(row["evaluation_hash"]),
    )


def _queued_input_from_row(row: Mapping[str, object]) -> TutorQueuedInput:
    return TutorQueuedInput(
        item_id=str(row["id"]),
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        content=str(row.get("content") or ""),
        state=str(row.get("state") or "pending"),
        position=_as_int(row.get("position"), 1),
        version=_as_int(row.get("version"), 1),
        claimed_turn_id=_optional_string(row.get("claimed_turn_id")),
        claimed_input_revision=(
            _as_int(row.get("claimed_input_revision"), 0)
            if row.get("claimed_input_revision") is not None
            else None
        ),
        claimed_mode=_optional_string(row.get("claimed_mode")),
        created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
        updated_at=_as_datetime(row.get("updated_at")) or datetime.now(UTC),
    )


def _interaction_request_from_row(row: Mapping[str, object]) -> TutorInteractionRequestRecord:
    kind = TutorInteractionRequestKind(str(row["kind"]))
    actor = TutorInteractionRequestActor(str(row["actor"]))
    state = TutorInteractionRequestState(str(row["state"]))
    descriptor = _as_mapping(row.get("descriptor_json"))
    presentation = _as_mapping(row.get("presentation_json"))
    prompt = sanitize_summary_text(str(descriptor.get("prompt") or ""), max_length=1_200)
    allowed_actions: list[str]
    if state is not TutorInteractionRequestState.PENDING or actor is TutorInteractionRequestActor.AUTHORITY:
        allowed_actions = []
    elif kind is TutorInteractionRequestKind.APPROVAL:
        allowed_actions = ["approve", "deny"]
    else:
        allowed_actions = ["respond"]
    resolved_at = _as_datetime(row.get("resolved_at"))
    public_item = validate_public_item(
        {
            "kind": public_item_kind(kind),
            "id": str(row["item_id"]),
            "request_id": str(row["id"]),
            "turn_id": str(row["source_turn_id"]),
            "request_kind": kind.value,
            "actor": actor.value,
            "state": state.value,
            "version": _as_int(row.get("version"), 1),
            "required": True,
            "prompt": prompt,
            "public_thinking_text": _public_thinking_text_from_values(
                descriptor.get("public_thinking_text"),
                (),
            ),
            "presentation": presentation,
            "allowed_actions": allowed_actions,
            "answer_turn_id": _optional_string(row.get("answer_turn_id")),
            "created_at": (_as_datetime(row.get("created_at")) or datetime.now(UTC)).astimezone(UTC).isoformat(),
            "resolved_at": resolved_at.astimezone(UTC).isoformat() if resolved_at is not None else None,
        }
    )
    return TutorInteractionRequestRecord(
        request_id=str(row["id"]),
        item_id=str(row["item_id"]),
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        source_turn_id=str(row["source_turn_id"]),
        kind=kind,
        actor=actor,
        state=state,
        version=_as_int(row.get("version"), 1),
        schema_version=str(row.get("schema_version") or TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION),
        catalog_version=_optional_string(row.get("catalog_version")),
        question_key=_optional_string(row.get("question_key")),
        descriptor=descriptor,
        presentation=presentation,
        answer_turn_id=_optional_string(row.get("answer_turn_id")),
        answer_message_id=_optional_string(row.get("answer_message_id")),
        created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
        resolved_at=resolved_at,
        public_item=public_item,
    )


def _snapshot_from_row(row: Mapping[str, object]) -> TutorRunSnapshot:
    policy_data = _as_mapping(row.get("policy_json"))
    deadline = _as_datetime(policy_data.get("deadline"))
    if deadline is None:
        raise TutorPersistenceError("stored Tutor policy is invalid")
    policy = TutorPolicySnapshot(
        deadline=deadline,
        max_iterations=_as_int(policy_data.get("max_iterations"), 0),
        max_model_calls=_as_int(policy_data.get("max_model_calls"), 0),
        max_capability_calls=_as_int(policy_data.get("max_capability_calls"), 0),
        max_effects=_as_int(policy_data.get("max_effects"), 0),
        context_token_budget=_as_int(policy_data.get("context_token_budget"), 1),
        lease_duration_seconds=_as_int(policy_data.get("lease_duration_seconds"), 1),
        context_budget_policy=_context_budget_policy_from_payload(policy_data.get("context_budget_policy")),
    )
    origin = str(row.get("origin") or "")
    if origin not in {"interactive", "proactive"}:
        raise TutorPersistenceError("stored Tutor run origin is invalid")
    expires_at = _as_datetime(row.get("active_lease_expires_at"))
    owner_id = row.get("active_lease_owner_id")
    generation = _as_int(row.get("active_lease_generation"), 0)
    lease = (
        TutorLease(run_id=str(row["id"]), owner_id=str(owner_id), generation=generation, expires_at=expires_at)
        if owner_id and expires_at is not None and generation > 0
        else None
    )
    return TutorRunSnapshot(
        run_id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        user_id=str(row["user_id"]),
        input_revision=_as_int(row["input_revision"], 0),
        policy=policy,
        origin=cast(TutorRunOrigin, origin),
        status=TutorRunStatus(str(row["status"])),
        lease=lease,
        iteration_count=_as_int(row.get("iteration_count"), 0),
        model_call_count=_as_int(row.get("model_call_count"), 0),
        capability_call_count=_as_int(row.get("capability_call_count"), 0),
        effect_count=_as_int(row.get("effect_count"), 0),
        cancelled=row.get("cancelled_at") is not None,
        continuation_kind=(
            TutorContinuationKind(str(row["continuation_kind"]))
            if row.get("continuation_kind") is not None
            else None
        ),
        interaction_protocol_version=_protocol_version_from_row(row).value,
        runtime_kind=cast(
            Literal["harness_v1", "codex_sidecar_v1"],
            str(row.get("runtime_kind") or "harness_v1"),
        ),
    )


def _result_from_row(row: Mapping[str, object]) -> TutorRunResult:
    raw_outcome = row.get("terminal_outcome")
    outcome = TutorTerminalOutcome(str(raw_outcome)) if raw_outcome else None
    return TutorRunResult(
        run_id=str(row["id"]),
        status=TutorRunStatus(str(row["status"])),
        input_revision=_as_int(row["input_revision"], 0),
        iteration_count=_as_int(row.get("iteration_count"), 0),
        model_call_count=_as_int(row.get("model_call_count"), 0),
        capability_call_count=_as_int(row.get("capability_call_count"), 0),
        effect_count=_as_int(row.get("effect_count"), 0),
        terminal_outcome=outcome,
        completion_reason=(
            TutorTurnCompletionReason(str(row["completion_reason"]))
            if row.get("completion_reason") is not None
            else None
        ),
        diagnostic_code=str(row["terminal_diagnostic_code"]) if row.get("terminal_diagnostic_code") else None,
    )


def _policy_payload(policy: TutorPolicySnapshot) -> dict[str, object]:
    return {
        "deadline": policy.deadline,
        "max_iterations": policy.max_iterations,
        "max_model_calls": policy.max_model_calls,
        "max_capability_calls": policy.max_capability_calls,
        "max_effects": policy.max_effects,
        "context_token_budget": policy.context_token_budget,
        "lease_duration_seconds": policy.lease_duration_seconds,
        "context_budget_policy": (
            _context_budget_policy_payload(policy.context_budget_policy)
            if policy.context_budget_policy is not None
            else None
        ),
    }


def _context_budget_policy_payload(policy: TutorContextBudgetPolicy) -> dict[str, object]:
    capability = policy.capability
    return {
        "capability": {
            "context_window_tokens": capability.context_window_tokens,
            "max_output_reserve_tokens": capability.max_output_reserve_tokens,
            "protocol_reserve_tokens": capability.protocol_reserve_tokens,
            "safety_margin_tokens": capability.safety_margin_tokens,
            "maximum_dynamic_target_tokens": capability.maximum_dynamic_target_tokens,
            "capability_version": capability.capability_version,
        },
        "mode_targets": {
            mode.value: target for mode, target in policy.mode_targets
        },
        "warning_ratio": policy.warning_ratio,
        "critical_ratio": policy.critical_ratio,
        "max_expansions": policy.max_expansions,
        "estimator_version": policy.estimator_version,
        "policy_version": policy.policy_version,
        "fixed_mode": policy.fixed_mode.value if policy.fixed_mode is not None else None,
    }


def _context_budget_policy_from_payload(value: object) -> TutorContextBudgetPolicy | None:
    payload = _as_mapping(value)
    if not payload:
        return None
    capability_data = _as_mapping(payload.get("capability"))
    mode_target_data = _as_mapping(payload.get("mode_targets"))
    try:
        capability = TutorProviderContextCapability(
            context_window_tokens=_as_int(capability_data.get("context_window_tokens"), 0),
            max_output_reserve_tokens=_as_int(capability_data.get("max_output_reserve_tokens"), 0),
            protocol_reserve_tokens=_as_int(capability_data.get("protocol_reserve_tokens"), 0),
            safety_margin_tokens=_as_int(capability_data.get("safety_margin_tokens"), 0),
            maximum_dynamic_target_tokens=_as_int(capability_data.get("maximum_dynamic_target_tokens"), 0),
            capability_version=str(capability_data.get("capability_version") or ""),
        )
        fixed_mode_value = payload.get("fixed_mode")
        return TutorContextBudgetPolicy(
            capability=capability,
            mode_targets=tuple(
                (
                    mode,
                    _as_int(mode_target_data.get(mode.value), 0),
                )
                for mode in TutorContextBudgetMode
            ),
            warning_ratio=_as_float(payload.get("warning_ratio"), 0.0),
            critical_ratio=_as_float(payload.get("critical_ratio"), 0.0),
            max_expansions=_as_int(payload.get("max_expansions"), 0),
            estimator_version=str(payload.get("estimator_version") or ""),
            policy_version=str(payload.get("policy_version") or ""),
            fixed_mode=(
                TutorContextBudgetMode(str(fixed_mode_value))
                if fixed_mode_value is not None
                else None
            ),
        )
    except (TypeError, ValueError) as exc:
        raise TutorPersistenceError("stored Tutor context budget policy is invalid") from exc


def _compaction_payload(request: TutorCompactionRequest, *, status: str) -> dict[str, object]:
    return {
        "kind": "compaction_request",
        "status": status,
        "idempotency_key": request.idempotency_key,
        "curation_idempotency_key": request.curation_idempotency_key,
        "run_id": request.run_id,
        "conversation_id": request.conversation_id,
        "input_revision": request.input_revision,
        "trigger": request.trigger.value,
        "projection_kind": request.projection_kind,
        "source_ids": list(request.source_ids),
        "source_hashes": list(request.source_hashes),
        "token_budget": request.token_budget,
        "consumed_tokens": request.consumed_tokens,
        "summary_schema_version": request.summary_schema_version,
        "summary_policy_version": request.summary_policy_version,
        "summary_source_hash": request.summary_source_hash,
        "prior_summary_id": request.prior_summary_id,
        "prior_summary_hash": request.prior_summary_hash,
        "covered_through_created_at": request.covered_through_created_at,
        "covered_through_message_id": request.covered_through_message_id,
    }


def _assert_not_terminal(run: Mapping[str, object]) -> None:
    if _is_terminal(run):
        raise TutorTerminalStateConflict("Tutor run is terminal")


def _assert_not_cancelled(run: Mapping[str, object]) -> None:
    if run.get("cancelled_at") is not None:
        raise TutorTerminalStateConflict("Tutor run is cancelled")


def _assert_not_superseded(run: Mapping[str, object]) -> None:
    if run.get("superseded_by_run_id") is not None:
        raise TutorTerminalStateConflict("Tutor run is superseded")


def _is_terminal(run: Mapping[str, object]) -> bool:
    return str(run.get("status") or "") in _TERMINAL_STATUSES or run.get("terminal_outcome") is not None


def _assert_active_lease(run: Mapping[str, object], *, lease: TutorLease, now: datetime) -> None:
    if not _lease_matches(run, lease=lease, now=now):
        raise TutorLeaseConflict("Tutor lease is stale or unavailable")


def _lease_matches(run: Mapping[str, object], *, lease: TutorLease, now: datetime) -> bool:
    expiry = _as_datetime(run.get("active_lease_expires_at"))
    return (
        str(run.get("active_lease_owner_id") or "") == lease.owner_id
        and _as_int(run.get("active_lease_generation"), 0) == lease.generation
        and expiry is not None
        and expiry > now
    )


def _payload_fields_hash(fields: Sequence[object]) -> str:
    serializable: list[dict[str, str]] = []
    for field in fields:
        key = getattr(field, "key", "")
        value = getattr(field, "value", "")
        serializable.append({"key": str(key), "value": str(value)})
    return _sha256_json(serializable)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _public_thinking_text_from_values(text_value: object, steps_value: object) -> str:
    if isinstance(text_value, str):
        text = text_value.strip()
        if text:
            if len(text) > MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH:
                text = text[:MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH]
            if not check_teaching_output(text).blocked:
                return text
    return "\n\n".join(_public_thinking_steps_from_value(steps_value))


def _public_thinking_steps_from_value(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    steps: list[str] = []
    for raw_step in value[:MAX_TUTOR_PUBLIC_THINKING_STEPS]:
        if not isinstance(raw_step, str):
            continue
        step = sanitize_summary_text(
            raw_step,
            max_length=MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH,
        )
        if step:
            steps.append(step)
    return tuple(steps)


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return _as_mapping(decoded)
    return {}


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return _as_list(decoded)
    return []


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    return _optional_string(row.get(key))


def _as_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None

__all__ = (
    'annotations',
    'base64',
    'hashlib',
    'hmac',
    'json',
    're',
    'Callable',
    'Mapping',
    'Sequence',
    'dataclass',
    'UTC',
    'datetime',
    'timedelta',
    'Final',
    'Literal',
    'cast',
    'uuid4',
    'Connection',
    'ValidationError',
    'EffectDescriptor',
    'default_effect_descriptors',
    'is_exact_semver',
    'MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH',
    'MAX_TUTOR_PUBLIC_THINKING_STEPS',
    'MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH',
    'TutorCapabilityRequest',
    'TutorCapabilityResult',
    'TutorCapabilityStatus',
    'TutorCheckpoint',
    'TutorCompactionRequest',
    'TutorCompactionTrigger',
    'TutorContextBudgetMode',
    'TutorContextBudgetPolicy',
    'TutorContinuationKind',
    'TutorDecision',
    'TutorEffectProposal',
    'TutorEffectResult',
    'TutorEffectStatus',
    'TutorLease',
    'TutorPolicySnapshot',
    'TutorProviderAttemptOutcome',
    'TutorProviderAttemptReceipt',
    'TutorProviderContextCapability',
    'TutorRunResult',
    'TutorRunOrigin',
    'TutorRunSnapshot',
    'TutorRunStatus',
    'TutorTerminalOutcome',
    'TutorTurnCompletionReason',
    'normalize_tutor_conversation_title',
    'payload_mapping_from_fields',
    'CatalogSkillReference',
    'SkillCatalogSnapshot',
    'get_settings',
    'check_teaching_output',
    'sanitize_summary_text',
    'TeachingAuthoritySnapshot',
    'TeachingCheckpointState',
    'TeachingSessionMode',
    'teaching_canonical_hash',
    'reduce_teaching_checkpoint',
    'LLMUsage',
    'TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION',
    'TUTOR_CONVERSATION_SNAPSHOT_VERSION',
    'TUTOR_CONVERSATION_STREAM_CURSOR_VERSION',
    'TUTOR_PUBLIC_THINKING_STREAM_VERSION',
    'TUTOR_RUNTIME_OUTPUT_VERSION',
    'TutorConversationEventKind',
    'TutorDispatchJobState',
    'TutorInteractionProtocolVersion',
    'TutorPublicTurn',
    'validate_public_item',
    'public_turn_status',
    'validate_conversation_event_payload',
    'PLANNING_QUESTION_CATALOG_VERSION',
    'build_planning_question_presentation',
    'format_planning_question_value',
    'validate_planning_question_value',
    'PlanningIntentResolver',
    'TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION',
    'TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION',
    'TutorInteractionRequestActor',
    'TutorInteractionRequestKind',
    'TutorInteractionRequestState',
    'actor_for_request',
    'canonical_payload_hash',
    'completion_reason_for_request',
    'public_item_kind',
    'TutorLifecycleConflict',
    'TutorLifecyclePersistence',
    'TutorRunStore',
    'PUBLIC_THINKING_CHUNK_MAX_LENGTH',
    'TutorPublicThinkingSink',
    'TutorSafeProjection',
    'TutorSkillSelection',
    '_DEFAULT_MEMORY_SETTING_VERSION',
    '_DEFAULT_RETENTION_DAYS',
    '_DEFAULT_STALE_DAYS',
    '_SAFE_KEY',
    '_SHA256',
    '_TERMINAL_STATUSES',
    '_PROPOSAL_KINDS',
    '_PROPOSAL_STATES',
    '_DURABLE_EVENT_KINDS',
    '_TRACE_KINDS',
    '_PUBLIC_PROCESS_VERSION',
    '_PUBLIC_PROCESS_STATES',
    '_PUBLIC_PROCESS_STEP_KEYS',
    '_PUBLIC_PROCESS_STEP_STATES',
    '_PUBLIC_PROCESS_STEP_LABELS',
    '_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS',
    '_CURSOR_VERSION',
    '_CONVERSATION_EVENT_CURSOR_KIND',
    '_DISPATCH_JOB_LEASE_SECONDS',
    '_DISPATCH_JOB_MAX_ATTEMPTS',
    '_QUEUE_MAX_PENDING',
    '_safe_key',
    'TutorPersistenceError',
    'TutorRunNotFound',
    'TutorIdempotencyConflict',
    'TutorTerminalStateConflict',
    'TutorLeaseConflict',
    'TutorCatalogEvidenceError',
    'TutorCursorInvalid',
    'TutorInteractionRequestConflict',
    'TutorInteractionRequestNotFound',
    'TutorDurableEvent',
    'TutorInputAcceptance',
    'TutorRunReadState',
    'TutorPublicProcessState',
    'TutorConversationSummary',
    'TutorQueuedInput',
    'TutorQueueAcceptance',
    'TutorInteractionRequestRecord',
    'TutorInteractionResponseAcceptance',
    'TutorInteractiveTurnAcceptance',
    'TutorPublicForegroundRun',
    'TutorConversationTimelineRecord',
    'TutorConversationEvent',
    'TutorInteractiveDispatchJob',
    'TutorConversationSnapshot',
    'TutorSkillSelectionEvidence',
    'TutorCapabilityInvocationReceipt',
    'TutorEffectCommitReceipt',
    'TutorProviderAttemptRecord',
    'TutorTraceRecord',
    'TutorCurationEnvelope',
    'TutorCurationOutboxReceipt',
    'TutorCurationProposalReceipt',
    'EffectHandler',
    'Failpoint',
    '_protocol_version_from_row',
    '_validate_conversation_event_identity',
    '_conversation_event_from_row',
    '_interactive_dispatch_job_from_row',
    '_trace_from_row',
    '_event_from_row',
    '_provider_attempt_record_from_row',
    '_selection_from_row',
    '_queued_input_from_row',
    '_interaction_request_from_row',
    '_snapshot_from_row',
    '_result_from_row',
    '_policy_payload',
    '_context_budget_policy_payload',
    '_context_budget_policy_from_payload',
    '_compaction_payload',
    '_assert_not_terminal',
    '_assert_not_cancelled',
    '_assert_not_superseded',
    '_is_terminal',
    '_assert_active_lease',
    '_lease_matches',
    '_payload_fields_hash',
    '_sha256_text',
    '_sha256_json',
    '_json',
    '_base64url_encode',
    '_base64url_decode',
    '_public_thinking_text_from_values',
    '_public_thinking_steps_from_value',
    '_as_mapping',
    '_as_list',
    '_as_int',
    '_as_float',
    '_optional_string',
    '_optional_text',
    '_as_optional_int',
    '_as_datetime',
)
