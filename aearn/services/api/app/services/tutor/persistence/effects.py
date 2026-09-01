"""Tutor persistence 的 effects 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from typing import TYPE_CHECKING

from ._namespace import *
from ._mixin import PersistenceMixin

if TYPE_CHECKING:
    from app.services.learning.artifacts.repository import LearningArtifactWriteResult
    from app.services.learning.teaching_artifacts import PreparedTeachingArtifact


@dataclass(frozen=True, slots=True)
class _TeachingStepCommit:
    scope: Mapping[str, object]
    next_checkpoint_id: str
    prepared_artifact: PreparedTeachingArtifact | None


class EffectsPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

    def record_skill_selection(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
        selection: TutorSkillSelection,
    ) -> TutorSkillSelectionEvidence:
        if input_revision < 0 or not is_exact_semver(selection.reference.version):
            raise TutorCatalogEvidenceError("Skill selection must use exact reviewed SemVer")
        event_key = f"skill-selection:{input_revision}"
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if input_revision != _as_int(run["input_revision"], 0):
                raise TutorIdempotencyConflict("Skill selection revision is no longer current")
            evaluation_hash = self._catalog_evaluation_hash(
                digest=str(run["catalog_digest"]),
                skill_id=selection.reference.skill_id,
                skill_version=selection.reference.version,
                manifest_hash=selection.manifest_hash,
                instruction_hash=selection.instruction_hash,
            )
            existing = self._conn.execute(
                """
                SELECT *
                FROM tutor_run_skill_selections
                WHERE run_id = %s AND input_revision = %s
                """,
                (run_id, input_revision),
            ).fetchone()
            if existing is not None:
                evidence = _selection_from_row(existing)
                if (
                    evidence[2] != selection.reference.skill_id
                    or evidence[3] != selection.reference.version
                    or evidence[4] != selection.manifest_hash
                    or evidence[5] != selection.instruction_hash
                    or evidence[6] != evaluation_hash
                ):
                    raise TutorIdempotencyConflict("Skill selection conflicts with durable evidence")
                event = self._event_by_key_locked(run_id=run_id, event_key=event_key)
                if event is None:
                    raise RuntimeError("Skill selection event is missing")
                return TutorSkillSelectionEvidence(*evidence, event=event, replayed=True)
            self._conn.execute(
                """
                INSERT INTO tutor_run_skill_selections (
                  run_id, input_revision, skill_id, skill_version,
                  manifest_hash, instruction_hash, evaluation_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    input_revision,
                    selection.reference.skill_id,
                    selection.reference.version,
                    selection.manifest_hash,
                    selection.instruction_hash,
                    evaluation_hash,
                ),
            )
            event = self._append_event_locked(
                run_id=run_id,
                event_key=event_key,
                kind="skill_selected",
                input_revision=input_revision,
                payload={
                    "kind": "skill_selected",
                    "run_id": run_id,
                    "input_revision": input_revision,
                    "catalog_digest": str(run["catalog_digest"]),
                    "skill_id": selection.reference.skill_id,
                    "skill_version": selection.reference.version,
                    "manifest_hash": selection.manifest_hash,
                    "instruction_hash": selection.instruction_hash,
                    "evaluation_hash": evaluation_hash,
                },
            )
            self._advance_public_process_locked(
                run=run,
                step_key="context_prepared",
                occurred_at=event.created_at,
            )
            return TutorSkillSelectionEvidence(
                run_id=run_id,
                input_revision=input_revision,
                skill_id=selection.reference.skill_id,
                skill_version=selection.reference.version,
                manifest_hash=selection.manifest_hash,
                instruction_hash=selection.instruction_hash,
                evaluation_hash=evaluation_hash,
                event=event,
                replayed=False,
            )

    def load_skill_selection(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
    ) -> TutorSkillSelection | None:
        if input_revision < 0:
            raise ValueError("Skill selection revision must be non-negative")
        row = self._conn.execute(
            """
            SELECT selections.skill_id, selections.skill_version,
                   selections.manifest_hash, selections.instruction_hash
            FROM tutor_run_skill_selections AS selections
            JOIN tutor_runs AS runs ON runs.id = selections.run_id
            WHERE selections.run_id = %s
              AND selections.input_revision = %s
              AND runs.user_id = %s
            """,
            (run_id, input_revision, user_id),
        ).fetchone()
        if row is None:
            return None
        try:
            return TutorSkillSelection(
                reference=CatalogSkillReference(
                    skill_id=str(row["skill_id"]),
                    version=str(row["skill_version"]),
                ),
                manifest_hash=str(row["manifest_hash"]),
                instruction_hash=str(row["instruction_hash"]),
            )
        except ValueError as exc:
            raise TutorCatalogEvidenceError("stored Skill selection is invalid") from exc

    def record_capability_invocation(
        self,
        *,
        user_id: str,
        run_id: str,
        lease: TutorLease,
        input_revision: int,
        request: TutorCapabilityRequest,
        result: TutorCapabilityResult,
        capability_version: str,
        catalog_digest: str,
        policy_fingerprint: str,
        duration_ms: int = 0,
    ) -> TutorCapabilityInvocationReceipt:
        if input_revision < 0 or duration_ms < 0 or not is_exact_semver(capability_version):
            raise ValueError("capability receipt metadata is invalid")
        if not _SHA256.fullmatch(catalog_digest) or not _SHA256.fullmatch(policy_fingerprint):
            raise ValueError("capability receipt hash is invalid")
        invocation_key = f"capability:{request.request_id}"
        if result.request_id != request.request_id:
            raise TutorPersistenceError("capability result does not match its request")
        request_hash = _payload_fields_hash(request.arguments)
        result_hash = _payload_fields_hash(result.safe_result)
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=datetime.now(UTC))
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("capability receipt revision is stale")
            if catalog_digest != str(run["catalog_digest"]) or policy_fingerprint != str(run["policy_fingerprint"]):
                raise TutorCatalogEvidenceError("capability receipt catalog or policy evidence is stale")
            existing = self._conn.execute(
                "SELECT * FROM tutor_capability_invocations WHERE run_id = %s AND invocation_key = %s",
                (run_id, invocation_key),
            ).fetchone()
            if existing is not None:
                if (
                    _as_int(existing["input_revision"], -1) != input_revision
                    or str(existing["capability_id"]) != request.capability_id
                    or str(existing["capability_version"]) != capability_version
                    or str(existing["catalog_digest"]) != catalog_digest
                    or str(existing["policy_fingerprint"]) != policy_fingerprint
                    or str(existing["request_hash"]) != request_hash
                    or str(existing["result_hash"]) != result_hash
                    or str(existing["status"]) != result.status.value
                    or str(existing.get("diagnostic_code") or "") != str(result.diagnostic_code or "")
                ):
                    raise TutorIdempotencyConflict("capability invocation conflicts with a prior receipt")
                event = self._event_by_id(str(existing["event_id"]))
                if event is None:
                    raise RuntimeError("capability receipt event is missing")
                return TutorCapabilityInvocationReceipt(str(existing["id"]), event, True)
            selected = self._conn.execute(
                """
                SELECT skill_id, skill_version, manifest_hash, instruction_hash, evaluation_hash
                FROM tutor_run_skill_selections
                WHERE run_id = %s AND input_revision = %s
                """,
                (run_id, input_revision),
            ).fetchone()
            if selected is None:
                raise TutorCatalogEvidenceError("capability receipt requires an exact selected Skill")
            skill_evidence = self._catalog_skill_evidence(
                digest=str(run["catalog_digest"]),
                skill_id=str(selected["skill_id"]),
                skill_version=str(selected["skill_version"]),
                manifest_hash=str(selected["manifest_hash"]),
                instruction_hash=str(selected["instruction_hash"]),
                evaluation_hash=str(selected["evaluation_hash"]),
            )
            if request.capability_id not in _as_list(skill_evidence.get("required_capability_ids")):
                raise TutorCatalogEvidenceError("capability is not declared by the selected Skill")
            event = self._append_event_locked(
                run_id=run_id,
                event_key=invocation_key,
                kind="capability_invoked",
                input_revision=input_revision,
                payload={
                    "kind": "capability_invoked",
                    "run_id": run_id,
                    "input_revision": input_revision,
                    "capability_id": request.capability_id,
                    "capability_version": capability_version,
                    "catalog_digest": catalog_digest,
                    "policy_fingerprint": policy_fingerprint,
                    "status": result.status.value,
                    "diagnostic_code": result.diagnostic_code or "none",
                    "request_hash": request_hash,
                    "result_hash": result_hash,
                    "duration_ms": duration_ms,
                },
            )
            row = self._conn.execute(
                """
                INSERT INTO tutor_capability_invocations (
                  run_id, event_id, input_revision, invocation_key,
                  capability_id, capability_version, catalog_digest, policy_fingerprint,
                  skill_id, skill_version, manifest_hash, instruction_hash,
                  lease_owner_id, lease_generation, status, diagnostic_code,
                  request_hash, result_hash, duration_ms
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run_id,
                    event.event_id,
                    input_revision,
                    invocation_key,
                    request.capability_id,
                    capability_version,
                    catalog_digest,
                    policy_fingerprint,
                    selected["skill_id"],
                    selected["skill_version"],
                    selected["manifest_hash"],
                    selected["instruction_hash"],
                    lease.owner_id,
                    lease.generation,
                    result.status.value,
                    result.diagnostic_code,
                    request_hash,
                    result_hash,
                    duration_ms,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("capability receipt insert failed")
            if result.status is TutorCapabilityStatus.COMPLETED:
                self._advance_public_process_locked(
                    run=run,
                    step_key="authorized_resource_checked",
                    occurred_at=event.created_at,
                )
            return TutorCapabilityInvocationReceipt(str(row["id"]), event, False)

    def commit_effect_if_current(
        self,
        *,
        user_id: str,
        run_id: str,
        lease: TutorLease,
        proposal: TutorEffectProposal,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> TutorEffectCommitReceipt:
        _safe_key(idempotency_key, label="effect idempotency key")
        effective_now = now or datetime.now(UTC)
        payload_hash = _payload_fields_hash(proposal.payload)
        event_key = f"effect:{proposal.effect_id}"
        logical_action_key: str | None = None
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            retry_root = _optional_string(run.get("retry_root_turn_id")) or str(run["id"])
            logical_action_key = _sha256_json({
                "user_id": user_id,
                "conversation_id": str(run["conversation_id"]),
                "retry_root_turn_id": retry_root,
                "effect_type": proposal.effect_type,
                "payload_hash": payload_hash,
            })
            existing = self._conn.execute(
                "SELECT * FROM tutor_effects WHERE run_id = %s AND effect_id = %s",
                (run_id, proposal.effect_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["idempotency_key"]) != idempotency_key
                    or str(existing["effect_type"]) != proposal.effect_type
                    or _as_int(existing["expected_input_revision"], -1) != proposal.expected_input_revision
                    or str(existing["payload_hash"]) != payload_hash
                ):
                    raise TutorIdempotencyConflict("effect identity conflicts with a prior request")
                replay_event = self._event_by_key_locked(run_id=run_id, event_key=event_key)
                if replay_event is None:
                    raise RuntimeError("effect replay event is missing")
                return TutorEffectCommitReceipt(
                    result=TutorEffectResult(
                        effect_id=proposal.effect_id,
                        status=TutorEffectStatus(str(existing["status"])),
                        commit_id=str(existing["commit_id"]) if existing.get("commit_id") else None,
                    ),
                    event=replay_event,
                    replayed=True,
                    committer_invoked=False,
                )

            if run.get("superseded_by_run_id") is not None:
                raise TutorTerminalStateConflict("superseded Tutor run cannot record an effect")
            is_current = (
                not _is_terminal(run)
                and run.get("cancelled_at") is None
                and _as_int(run["input_revision"], 0) == proposal.expected_input_revision
                and _lease_matches(run, lease=lease, now=effective_now)
            )
            if not is_current:
                result = TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.STALE_REJECTED)
                event = self._record_effect_result_locked(
                    run=run,
                    lease=lease,
                    proposal=proposal,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    result=result,
                    event_key=event_key,
                    input_revision=_as_int(run["input_revision"], 0),
                )
                return TutorEffectCommitReceipt(result=result, event=event, replayed=False, committer_invoked=False)

            self._assert_teaching_authority_current_locked(run=run)
            handler = self._effect_handlers.get(proposal.effect_type)
            descriptor = self._effect_descriptors.get(proposal.effect_type)
            payload = payload_mapping_from_fields(proposal.payload)
            descriptor_valid = False
            if descriptor is not None and payload is not None:
                try:
                    descriptor.proposal_model.model_validate(payload)
                    descriptor_valid = True
                except (ValidationError, TypeError, ValueError):
                    descriptor_valid = False
            if (
                handler is None
                or descriptor is None
                or not descriptor_valid
                or not self._selected_skill_allows_effect(
                    run=run,
                    input_revision=proposal.expected_input_revision,
                    effect_type=proposal.effect_type,
                )
            ):
                result = TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)
                event = self._record_effect_result_locked(
                    run=run,
                    lease=lease,
                    proposal=proposal,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    result=result,
                    event_key=event_key,
                    input_revision=proposal.expected_input_revision,
                )
                return TutorEffectCommitReceipt(result=result, event=event, replayed=False, committer_invoked=False)

            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                ("tutor-effect-logical", logical_action_key),
            )
            prior_logical = self._conn.execute(
                "SELECT * FROM tutor_effects WHERE logical_action_key = %s ORDER BY created_at, id LIMIT 1 FOR UPDATE",
                (logical_action_key,),
            ).fetchone()
            if prior_logical is not None and str(prior_logical.get("status")) == "committed":
                result = TutorEffectResult(
                    effect_id=proposal.effect_id,
                    status=TutorEffectStatus.COMMITTED,
                    commit_id=_optional_string(prior_logical.get("commit_id")),
                )
                event = self._append_event_locked(
                    run_id=run_id,
                    event_key=event_key,
                    kind="effect_result",
                    input_revision=proposal.expected_input_revision,
                    payload={
                        "kind": "effect_result",
                        "status": "committed",
                        "effect_id": proposal.effect_id,
                        "logical_replay": True,
                    },
                )
                return TutorEffectCommitReceipt(result=result, event=event, replayed=True, committer_invoked=False)
            if prior_logical is not None:
                raise TutorTerminalStateConflict("logical effect authority is ambiguous")

            provisional = self._conn.execute(
                """
                INSERT INTO tutor_effects (
                  run_id, effect_id, idempotency_key, effect_type, expected_input_revision,
                  payload_hash, logical_action_key, lease_owner_id, lease_generation, status, safe_outcome_json, safe_outcome_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'proposed', %s::jsonb, %s)
                RETURNING id
                """,
                (
                    run_id,
                    proposal.effect_id,
                    idempotency_key,
                    proposal.effect_type,
                    proposal.expected_input_revision,
                    payload_hash,
                    logical_action_key,
                    lease.owner_id,
                    lease.generation,
                    _json(self._projector.project({"effect_id": proposal.effect_id, "status": "proposed"})),
                    self._projector.fingerprint({"effect_id": proposal.effect_id, "status": "proposed"}),
                ),
            ).fetchone()
            if provisional is None:
                raise RuntimeError("effect reservation insert failed")
            result = handler(self._conn, _snapshot_from_row(run), proposal)
            if result.effect_id != proposal.effect_id:
                raise TutorPersistenceError("effect handler returned a mismatched effect id")
            event = self._record_effect_result_locked(
                run=run,
                lease=lease,
                proposal=proposal,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                result=result,
                event_key=event_key,
                input_revision=proposal.expected_input_revision,
                existing_effect_id=str(provisional["id"]),
                increment_effect_counter=True,
            )
            return TutorEffectCommitReceipt(result=result, event=event, replayed=False, committer_invoked=True)

    def record_provider_attempts(
        self,
        *,
        snapshot: TutorRunSnapshot,
        decision_iteration: int,
        attempts: tuple[TutorProviderAttemptReceipt, ...],
        created_at: datetime,
    ) -> None:
        if decision_iteration < 1:
            raise ValueError("provider decision_iteration must be positive")
        if not attempts:
            return
        if len({attempt.attempt_index for attempt in attempts}) != len(attempts):
            raise ValueError("provider attempt indexes must be unique")

        with self._conn.transaction():
            run = self._conn.execute(
                """
                SELECT id, user_id, conversation_id, input_revision
                FROM tutor_runs
                WHERE id = %s AND user_id = %s
                """,
                (snapshot.run_id, snapshot.user_id),
            ).fetchone()
            if run is None:
                raise TutorRunNotFound("tutor run not found")
            if str(run["conversation_id"]) != snapshot.conversation_id:
                raise TutorIdempotencyConflict("provider attempt run scope conflicts with persisted conversation")
            if snapshot.input_revision > _as_int(run["input_revision"], -1):
                raise TutorIdempotencyConflict("provider attempt input revision exceeds persisted run revision")

            for attempt in attempts:
                usage = attempt.usage
                values = (
                    snapshot.run_id,
                    snapshot.user_id,
                    snapshot.conversation_id,
                    snapshot.input_revision,
                    decision_iteration,
                    attempt.attempt_index,
                    attempt.provider_type,
                    attempt.model,
                    attempt.protocol,
                    attempt.outcome.value,
                    attempt.diagnostic_code,
                    usage.input_tokens if usage is not None else None,
                    usage.cached_input_tokens if usage is not None else None,
                    usage.uncached_input_tokens if usage is not None else None,
                    usage.output_tokens if usage is not None else None,
                    usage.total_tokens if usage is not None else None,
                    usage.calculated_total_tokens if usage is not None else None,
                    usage.reasoning_tokens if usage is not None else None,
                    usage is not None and usage.usage_available,
                )
                inserted = self._conn.execute(
                    """
                    INSERT INTO tutor_provider_attempt_receipts (
                      run_id, user_id, conversation_id, input_revision,
                      decision_iteration, attempt_index, provider_type, model, protocol,
                      outcome, diagnostic_code, input_tokens, cached_input_tokens,
                      uncached_input_tokens, output_tokens, reported_total_tokens,
                      calculated_total_tokens, reasoning_tokens, usage_available, created_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (run_id, input_revision, decision_iteration, attempt_index) DO NOTHING
                    RETURNING id
                    """,
                    (*values, created_at),
                ).fetchone()
                if inserted is not None:
                    continue
                replay = self._conn.execute(
                    """
                    SELECT id
                    FROM tutor_provider_attempt_receipts
                    WHERE run_id = %s
                      AND user_id = %s
                      AND conversation_id = %s
                      AND input_revision = %s
                      AND decision_iteration = %s
                      AND attempt_index = %s
                      AND provider_type IS NOT DISTINCT FROM %s
                      AND model IS NOT DISTINCT FROM %s
                      AND protocol IS NOT DISTINCT FROM %s
                      AND outcome IS NOT DISTINCT FROM %s
                      AND diagnostic_code IS NOT DISTINCT FROM %s
                      AND input_tokens IS NOT DISTINCT FROM %s
                      AND cached_input_tokens IS NOT DISTINCT FROM %s
                      AND uncached_input_tokens IS NOT DISTINCT FROM %s
                      AND output_tokens IS NOT DISTINCT FROM %s
                      AND reported_total_tokens IS NOT DISTINCT FROM %s
                      AND calculated_total_tokens IS NOT DISTINCT FROM %s
                      AND reasoning_tokens IS NOT DISTINCT FROM %s
                      AND usage_available IS NOT DISTINCT FROM %s
                    """,
                    values,
                ).fetchone()
                if replay is None:
                    raise TutorIdempotencyConflict(
                        "provider attempt receipt identity conflicts with different safe facts"
                    )

    def list_provider_attempt_receipts(
        self,
        *,
        user_id: str,
        run_id: str,
    ) -> tuple[TutorProviderAttemptRecord, ...]:
        run = self._conn.execute(
            "SELECT id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise TutorRunNotFound("tutor run not found")
        rows = self._conn.execute(
            """
            SELECT *
            FROM tutor_provider_attempt_receipts
            WHERE run_id = %s AND user_id = %s
            ORDER BY decision_iteration, attempt_index, created_at, id
            """,
            (run_id, user_id),
        ).fetchall()
        return tuple(_provider_attempt_record_from_row(row) for row in rows)

    def _assert_teaching_authority_current_locked(self, *, run: Mapping[str, object]) -> None:
        scope = self._conn.execute(
            "SELECT run_id FROM tutor_run_teaching_scopes WHERE run_id=%s AND user_id=%s",
            (run["id"], run["user_id"]),
        ).fetchone()
        if scope is None:
            return
        foreground = self._conn.execute(
            """
            SELECT id
            FROM tutor_runs
            WHERE user_id=%s AND conversation_id=%s AND origin='interactive'
              AND terminal_outcome IS NULL AND cancelled_at IS NULL
              AND superseded_by_run_id IS NULL
            FOR UPDATE
            """,
            (run["user_id"], run["conversation_id"]),
        ).fetchall()
        if (
            str(run.get("origin") or "") != "interactive"
            or len(foreground) != 1
            or str(foreground[0]["id"]) != str(run["id"])
        ):
            raise TutorTerminalStateConflict(
                "Tutor teaching run is no longer the foreground authority"
            )
        live = self._conn.execute(
            """SELECT scopes.*, sessions.current_checkpoint_id, sessions.version AS live_session_version,
                      sessions.status AS live_session_status, tracks.version AS live_track_version,
                      active.revision_id AS live_plan_revision_id, progress.version AS live_progress_version,
                      assignments.id AS live_assignment_id, assignments.assignment_version AS live_assignment_version,
                      documents.id AS live_document_id, documents.content_hash AS live_document_content_hash
               FROM tutor_run_teaching_scopes AS scopes
               JOIN tutor_teaching_sessions AS sessions ON sessions.id=scopes.teaching_session_id
                 AND sessions.user_id=scopes.user_id AND sessions.conversation_id=scopes.conversation_id
               JOIN tutor_learning_tracks AS tracks ON tracks.id=scopes.track_id AND tracks.user_id=scopes.user_id
               JOIN tutor_track_active_plans AS active ON active.track_id=scopes.track_id AND active.user_id=scopes.user_id
               JOIN tutor_track_node_progress AS progress ON progress.track_id=scopes.track_id
                 AND progress.user_id=scopes.user_id AND progress.knowledge_key=scopes.knowledge_key
               JOIN tutor_lesson_assignments AS assignments ON assignments.user_id=scopes.user_id
                 AND assignments.track_id=scopes.track_id AND assignments.knowledge_key=scopes.knowledge_key
                 AND assignments.status='active'
               JOIN tutor_lesson_documents AS documents ON documents.id=assignments.document_id
                 AND documents.user_id=assignments.user_id AND documents.track_id=assignments.track_id
                 AND documents.knowledge_key=assignments.knowledge_key
               JOIN tutor_run_stimulus_events AS stimuli ON stimuli.id=scopes.stimulus_id
                 AND stimuli.run_id=scopes.run_id AND stimuli.user_id=scopes.user_id
                 AND stimuli.conversation_id=scopes.conversation_id AND stimuli.teaching_session_id=scopes.teaching_session_id
               WHERE scopes.run_id=%s AND scopes.user_id=%s
               FOR UPDATE OF sessions,tracks,progress,assignments""",
            (run["id"], run["user_id"]),
        ).fetchone()
        if live is None:
            raise TutorTerminalStateConflict("Tutor teaching authority is unavailable")
        expected = (
            str(live["checkpoint_id"]), _as_int(live["session_version"], 0),
            _as_int(live["track_version"], 0), str(live["active_plan_revision_id"]),
            _as_int(live["progress_version"], 0), str(live["lesson_assignment_id"]),
            _as_int(live["assignment_version"], 0), str(live["document_id"]), str(live["document_content_hash"]),
        )
        observed = (
            str(live["current_checkpoint_id"]), _as_int(live["live_session_version"], 0),
            _as_int(live["live_track_version"], 0), str(live["live_plan_revision_id"]),
            _as_int(live["live_progress_version"], 0), str(live["live_assignment_id"]),
            _as_int(live["live_assignment_version"], 0), str(live["live_document_id"]), str(live["live_document_content_hash"]),
        )
        if expected != observed or str(live["live_session_status"]) not in {"active", "paused"}:
            raise TutorTerminalStateConflict("Tutor teaching authority is stale")

    def _commit_teaching_step_locked(
        self, *, run: Mapping[str, object], result: TutorRunResult,
        checkpoint: TutorCheckpoint, created_at: datetime,
    ) -> _TeachingStepCommit | None:
        scope = self._conn.execute(
            """SELECT scopes.*, sessions.status AS session_status, sessions.version AS live_session_version,
                      sessions.current_checkpoint_id, checkpoints.state_json, stimuli.message_id,
                      progress.status AS progress_status,
                      nodes.required_capabilities_json AS available_capabilities_json
               FROM tutor_run_teaching_scopes AS scopes
               JOIN tutor_teaching_sessions AS sessions ON sessions.id=scopes.teaching_session_id
                 AND sessions.user_id=scopes.user_id AND sessions.conversation_id=scopes.conversation_id
               JOIN tutor_teaching_session_checkpoints AS checkpoints ON checkpoints.id=scopes.checkpoint_id
                 AND checkpoints.teaching_session_id=scopes.teaching_session_id
               JOIN tutor_run_stimulus_events AS stimuli ON stimuli.id=scopes.stimulus_id AND stimuli.run_id=scopes.run_id
               JOIN tutor_track_node_progress AS progress ON progress.track_id=scopes.track_id
                 AND progress.user_id=scopes.user_id AND progress.knowledge_key=scopes.knowledge_key
               JOIN tutor_track_plan_nodes AS nodes ON nodes.revision_id=scopes.active_plan_revision_id
                 AND nodes.track_id=scopes.track_id AND nodes.user_id=scopes.user_id
                 AND nodes.knowledge_key=scopes.knowledge_key
               WHERE scopes.run_id=%s AND scopes.user_id=%s
               FOR UPDATE OF sessions,progress""",
            (run["id"], run["user_id"]),
        ).fetchone()
        if scope is None:
            if result.teaching_step is not None:
                raise TutorTerminalStateConflict("teaching step has no immutable teaching scope")
            return None
        if result.teaching_step is None:
            return None
        if str(scope["current_checkpoint_id"]) != str(scope["checkpoint_id"]):
            raise TutorTerminalStateConflict("teaching checkpoint changed before commit")
        if _as_int(scope["live_session_version"], 0) != _as_int(scope["session_version"], 0):
            raise TutorTerminalStateConflict("teaching session version changed before commit")
        try:
            current_state = TeachingCheckpointState.model_validate(scope["state_json"])
            next_state = reduce_teaching_checkpoint(
                state=current_state, step=result.teaching_step,
                mode=TeachingSessionMode(str(scope["mode"])),
                stimulus_id=str(scope["stimulus_id"]),
                source_message_id=_optional_string(scope.get("message_id")),
            )
            authority = TeachingAuthoritySnapshot(
                track_version=_as_int(scope["track_version"], 0),
                plan_revision_id=str(scope["active_plan_revision_id"]),
                progress_version=_as_int(scope["progress_version"], 0),
                assignment_id=str(scope["lesson_assignment_id"]),
                assignment_version=_as_int(scope["assignment_version"], 0),
                document_id=str(scope["document_id"]),
                document_content_hash=str(scope["document_content_hash"]),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise TutorTerminalStateConflict("teaching checkpoint reduction failed") from exc
        next_version = _as_int(scope["session_version"], 0) + 1
        state_json = next_state.model_dump(mode="json")
        authority_json = authority.model_dump(mode="json")
        source_hash = teaching_canonical_hash({
            "state": state_json, "authority": authority_json, "session_version": next_version,
            "source_run_id": str(run["id"]), "source_stimulus_id": str(scope["stimulus_id"]),
        })
        next_checkpoint = self._conn.execute(
            """INSERT INTO tutor_teaching_session_checkpoints (
                 teaching_session_id,user_id,conversation_id,predecessor_checkpoint_id,session_version,
                 state_json,authority_snapshot_json,source_run_id,source_stimulus_id,source_hash
               ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)
               RETURNING id,source_hash""",
            (scope["teaching_session_id"], scope["user_id"], scope["conversation_id"], scope["checkpoint_id"],
             next_version, _json(state_json), _json(authority_json), run["id"], scope["stimulus_id"], source_hash),
        ).fetchone()
        if next_checkpoint is None:
            raise RuntimeError("teaching checkpoint commit failed")
        completed = str(scope["progress_status"]) == "completed" or result.teaching_step.pause_kind.value == "completion_pause"
        status = "completed" if completed else "paused" if result.teaching_step.pause_kind.value == "session_pause" else "active"
        updated = self._conn.execute(
            """UPDATE tutor_teaching_sessions SET current_checkpoint_id=%s,version=version+1,status=%s,
                 paused_at=CASE WHEN %s='paused' THEN %s ELSE NULL END,
                 completed_at=CASE WHEN %s='completed' THEN COALESCE(completed_at,%s) ELSE completed_at END,
                 last_activity_at=%s,last_mutation_key=%s,last_mutation_hash=%s
               WHERE id=%s AND user_id=%s AND version=%s RETURNING id""",
            (next_checkpoint["id"], status, status, created_at, status, created_at, created_at,
             f"teaching-run:{run['id']}", teaching_canonical_hash(result.teaching_step.model_dump(mode="json")),
             scope["teaching_session_id"], scope["user_id"], scope["session_version"]),
        ).fetchone()
        if updated is None:
            raise TutorTerminalStateConflict("teaching session CAS failed")
        prepared_artifact: PreparedTeachingArtifact | None = None
        interaction = result.teaching_step.interaction
        if interaction is not None and interaction.mode.value == "artifact":
            from app.services.learning.teaching_artifacts import (
                PostgresTeachingArtifactMaterializer,
                TeachingArtifactCommitError,
            )

            try:
                prepared_artifact = PostgresTeachingArtifactMaterializer(
                    self._conn,
                    settings=self._settings,
                ).prepare(
                    step=result.teaching_step,
                    run_id=str(run["id"]),
                    user_id=str(scope["user_id"]),
                    conversation_id=str(scope["conversation_id"]),
                    teaching_session_id=str(scope["teaching_session_id"]),
                    checkpoint_id=str(next_checkpoint["id"]),
                    checkpoint_source_hash=str(next_checkpoint["source_hash"]),
                    session_version=next_version,
                    learning_track_id=str(scope["track_id"]),
                    knowledge_key=str(scope["knowledge_key"]),
                    track_version=_as_int(scope["track_version"], 0),
                    progress_version=_as_int(scope["progress_version"], 0),
                    assignment_version=_as_int(scope["assignment_version"], 0),
                    available_capabilities=tuple(
                        str(item)
                        for item in _as_list(
                            scope.get("available_capabilities_json")
                        )
                    ),
                )
            except (TeachingArtifactCommitError, ValidationError) as exc:
                raise TutorTerminalStateConflict(
                    "teaching Artifact authority changed before commit"
                ) from exc
        return _TeachingStepCommit(
            scope=dict(scope),
            next_checkpoint_id=str(next_checkpoint["id"]),
            prepared_artifact=prepared_artifact,
        )

    def _finalize_teaching_step_locked(
        self,
        *,
        commit: _TeachingStepCommit | None,
        run: Mapping[str, object],
        result: TutorRunResult,
        checkpoint: TutorCheckpoint,
        created_at: datetime,
    ) -> None:
        if commit is None:
            return
        step = result.teaching_step
        if step is None:
            raise TutorTerminalStateConflict(
                "teaching commit lost its authoritative step"
            )
        artifact_result: LearningArtifactWriteResult | None = None
        if commit.prepared_artifact is not None:
            from app.services.learning.teaching_artifacts import (
                PostgresTeachingArtifactMaterializer,
                TeachingArtifactCommitError,
            )

            try:
                artifact_result = PostgresTeachingArtifactMaterializer(
                    self._conn,
                    settings=self._settings,
                ).create(commit.prepared_artifact, occurred_at=created_at)
            except TeachingArtifactCommitError as exc:
                raise TutorTerminalStateConflict(
                    "teaching Artifact failed during atomic commit"
                ) from exc

        response_mode = (
            step.learner_response_mode.value
            if step.learner_response_mode is not None
            else "none"
        )
        is_artifact = response_mode == "artifact"
        if is_artifact != (artifact_result is not None):
            raise TutorTerminalStateConflict(
                "teaching Artifact receipt does not match the committed interaction"
            )
        if is_artifact:
            prepared = commit.prepared_artifact
            if prepared is None or artifact_result is None:
                raise TutorTerminalStateConflict(
                    "teaching Artifact receipt lost prepared authority"
                )
            schema_version = "teaching_action_receipt_v3"
            policy_version = "lesson_teaching_policy_v3"
            interaction_intent: str | None = prepared.interaction_intent.value
            artifact_handle: str | None = prepared.artifact_handle
            artifact_id: str | None = artifact_result.artifact.id
            artifact_event_id: str | None = artifact_result.artifact_event_id
            artifact_event_sequence: int | None = artifact_result.artifact_event_sequence
        else:
            schema_version = "teaching_action_receipt_v2"
            policy_version = "lesson_teaching_policy_v2"
            interaction_intent = None
            artifact_handle = None
            artifact_id = None
            artifact_event_id = None
            artifact_event_sequence = None

        scope = commit.scope
        self._conn.execute(
            """INSERT INTO tutor_teaching_action_receipts (
                 run_id,user_id,conversation_id,teaching_session_id,checkpoint_id,stimulus_id,action,
                 objective_id,focus_id,focus_resolution,pause_kind,source_handles_json,public_message_hash,
                 context_source_ids_json,context_source_hashes_json,teaching_moves_json,learner_response_mode,
                 schema_version,policy_version,interaction_intent,artifact_handle,artifact_id,
                 artifact_event_id,artifact_event_sequence
               ) VALUES (
                 %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,
                 %s,%s,%s,%s,%s,%s,%s
               )""",
            (
                run["id"],
                scope["user_id"],
                scope["conversation_id"],
                scope["teaching_session_id"],
                commit.next_checkpoint_id,
                scope["stimulus_id"],
                step.action.value,
                step.objective_id,
                step.focus_id,
                step.focus_resolution.value,
                step.pause_kind.value,
                _json(list(step.source_handles)),
                hashlib.sha256(step.public_message.encode("utf-8")).hexdigest(),
                _json(list(checkpoint.metadata.source_ids)),
                _json(list(checkpoint.metadata.source_hashes)),
                _json([item.value for item in step.teaching_moves or ()]),
                response_mode,
                schema_version,
                policy_version,
                interaction_intent,
                artifact_handle,
                artifact_id,
                artifact_event_id,
                artifact_event_sequence,
            ),
        )

    def _catalog_skill_evidence(
        self,
        *,
        digest: str,
        skill_id: str,
        skill_version: str,
        manifest_hash: str,
        instruction_hash: str,
        evaluation_hash: str | None = None,
    ) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT manifest_json FROM tutor_catalog_snapshots WHERE digest = %s",
            (digest,),
        ).fetchone()
        if row is None:
            raise TutorCatalogEvidenceError("catalog snapshot is missing")
        manifest = _as_mapping(row.get("manifest_json"))
        skills = manifest.get("skills")
        if not isinstance(skills, list):
            raise TutorCatalogEvidenceError("catalog snapshot evidence is invalid")
        for item in skills:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("skill_id")) != skill_id or str(item.get("skill_version")) != skill_version:
                continue
            if str(item.get("manifest_hash")) != manifest_hash or str(item.get("instruction_hash")) != instruction_hash:
                raise TutorCatalogEvidenceError("Skill hash does not match persisted catalog evidence")
            stored_evaluation_hash = str(item.get("evaluation_hash") or "")
            if not _SHA256.fullmatch(stored_evaluation_hash):
                raise TutorCatalogEvidenceError("catalog evaluation hash is invalid")
            if evaluation_hash is not None and stored_evaluation_hash != evaluation_hash:
                raise TutorCatalogEvidenceError("Skill evaluation hash does not match persisted catalog evidence")
            return {str(key): value for key, value in item.items()}
        raise TutorCatalogEvidenceError("Skill is not present in persisted catalog evidence")

    def _catalog_evaluation_hash(
        self,
        *,
        digest: str,
        skill_id: str,
        skill_version: str,
        manifest_hash: str,
        instruction_hash: str,
    ) -> str:
        evidence = self._catalog_skill_evidence(
            digest=digest,
            skill_id=skill_id,
            skill_version=skill_version,
            manifest_hash=manifest_hash,
            instruction_hash=instruction_hash,
        )
        return str(evidence["evaluation_hash"])

    def _selected_skill_allows_effect(
        self,
        *,
        run: Mapping[str, object],
        input_revision: int,
        effect_type: str,
    ) -> bool:
        selected = self._conn.execute(
            """
            SELECT skill_id, skill_version, manifest_hash, instruction_hash, evaluation_hash
            FROM tutor_run_skill_selections
            WHERE run_id = %s AND input_revision = %s
            """,
            (run["id"], input_revision),
        ).fetchone()
        if selected is None:
            return False
        evidence = self._catalog_skill_evidence(
            digest=str(run["catalog_digest"]),
            skill_id=str(selected["skill_id"]),
            skill_version=str(selected["skill_version"]),
            manifest_hash=str(selected["manifest_hash"]),
            instruction_hash=str(selected["instruction_hash"]),
            evaluation_hash=str(selected["evaluation_hash"]),
        )
        return effect_type in _as_list(evidence.get("allowed_effect_types"))

    def _record_effect_result_locked(
        self,
        *,
        run: Mapping[str, object],
        lease: TutorLease,
        proposal: TutorEffectProposal,
        idempotency_key: str,
        payload_hash: str,
        result: TutorEffectResult,
        event_key: str,
        input_revision: int,
        existing_effect_id: str | None = None,
        increment_effect_counter: bool = False,
    ) -> TutorDurableEvent:
        safe_outcome = self._projector.project(
            {
                "effect_id": result.effect_id,
                "effect_type": proposal.effect_type,
                "status": result.status.value,
                "commit_id": result.commit_id or "none",
                "input_revision": input_revision,
                "lease_generation": lease.generation,
            }
        )
        outcome_hash = self._projector.fingerprint(safe_outcome)
        if existing_effect_id is None:
            row = self._conn.execute(
                """
                INSERT INTO tutor_effects (
                  run_id, effect_id, idempotency_key, effect_type, expected_input_revision,
                  payload_hash, lease_owner_id, lease_generation, status, commit_id,
                  safe_outcome_json, safe_outcome_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING id
                """,
                (
                    run["id"],
                    proposal.effect_id,
                    idempotency_key,
                    proposal.effect_type,
                    proposal.expected_input_revision,
                    payload_hash,
                    lease.owner_id,
                    lease.generation,
                    result.status.value,
                    result.commit_id,
                    _json(safe_outcome),
                    outcome_hash,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("effect receipt insert failed")
        else:
            row = self._conn.execute(
                """
                UPDATE tutor_effects
                SET status = %s, commit_id = %s, safe_outcome_json = %s::jsonb, safe_outcome_hash = %s
                WHERE id = %s
                RETURNING id
                """,
                (result.status.value, result.commit_id, _json(safe_outcome), outcome_hash, existing_effect_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("effect receipt update failed")
        event = self._append_event_locked(
            run_id=str(run["id"]),
            event_key=event_key,
            kind="effect_result",
            input_revision=input_revision,
            payload={
                "kind": "effect_result",
                "run_id": str(run["id"]),
                "input_revision": input_revision,
                "effect_id": proposal.effect_id,
                "effect_type": proposal.effect_type,
                "status": result.status.value,
                "commit_id": result.commit_id or "none",
                "payload_hash": payload_hash,
                "lease_generation": lease.generation,
            },
        )
        if increment_effect_counter:
            self._conn.execute(
                "UPDATE tutor_runs SET effect_count = effect_count + 1 WHERE id = %s",
                (run["id"],),
            )
        return event

    def _insert_trace_locked(
        self,
        *,
        run_id: str,
        kind: str,
        event_sequence: int,
        payload: Mapping[str, object],
        created_at: datetime,
    ) -> TutorTraceRecord:
        _safe_key(kind, label="trace kind")
        if kind not in _TRACE_KINDS:
            raise ValueError("trace kind is not part of the Child 02 durable vocabulary")
        safe_payload = self._projector.project(payload)
        trace_hash = self._projector.fingerprint(safe_payload)
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_run_traces
            WHERE run_id = %s AND event_from_sequence = %s
              AND event_to_sequence = %s AND kind = %s
            """,
            (run_id, event_sequence, event_sequence, kind),
        ).fetchone()
        if existing is not None:
            if str(existing["trace_hash"]) != trace_hash:
                raise TutorIdempotencyConflict("trace identity conflicts with a different safe payload")
            return _trace_from_row(existing, projector=self._projector)
        row = self._conn.execute(
            """
            INSERT INTO tutor_run_traces (
              run_id, event_from_sequence, event_to_sequence, kind,
              trace_json, trace_hash, redaction_version, created_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            RETURNING *
            """,
            (
                run_id,
                event_sequence,
                event_sequence,
                kind,
                _json(safe_payload),
                trace_hash,
                self._projector.version,
                created_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("trace insert failed")
        return _trace_from_row(row, projector=self._projector)
