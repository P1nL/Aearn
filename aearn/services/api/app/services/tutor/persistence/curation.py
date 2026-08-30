"""Tutor persistence 的 curation 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._namespace import *
from ._mixin import PersistenceMixin


class CurationPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

    def record_curation_proposal(
        self,
        *,
        user_id: str,
        outbox_id: str,
        kind: str,
        state: str,
        payload: Mapping[str, object],
        confidence: str,
        policy_version: str,
        memory_setting_version: str,
        created_at: datetime | None = None,
    ) -> TutorCurationProposalReceipt:
        if kind not in _PROPOSAL_KINDS or state not in _PROPOSAL_STATES:
            raise ValueError("curation proposal kind or state is invalid")
        if confidence not in {"low", "medium", "high"}:
            raise ValueError("curation proposal confidence is invalid")
        _safe_key(policy_version, label="proposal policy version")
        _safe_key(memory_setting_version, label="proposal memory setting version")
        created_at = created_at or datetime.now(UTC)
        safe_payload = self._projector.project({**dict(payload), "kind": kind, "confidence": confidence})
        payload_hash = self._projector.fingerprint(safe_payload)
        with self._conn.transaction():
            outbox = self._conn.execute(
                """
                SELECT outbox.*, runs.user_id, runs.input_revision AS run_input_revision
                FROM tutor_memory_curation_outbox AS outbox
                JOIN tutor_runs AS runs ON runs.id = outbox.run_id
                WHERE outbox.id = %s AND runs.user_id = %s
                FOR UPDATE OF outbox, runs
                """,
                (outbox_id, user_id),
            ).fetchone()
            if outbox is None:
                raise TutorRunNotFound("curation outbox record not found")
            run = self._lock_run(user_id=user_id, run_id=str(outbox["run_id"]))
            current_state = state
            stale_after = _as_datetime(outbox.get("stale_after"))
            if (
                str(outbox["policy_version"]) != policy_version
                or str(outbox["memory_setting_version"]) != memory_setting_version
                or _as_int(outbox["input_revision"], -1) != _as_int(run["input_revision"], -1)
                or (stale_after is not None and stale_after <= created_at)
            ):
                current_state = "stale"
            existing = self._conn.execute(
                "SELECT * FROM tutor_curation_proposals WHERE outbox_id = %s",
                (outbox_id,),
            ).fetchone()
            if existing is not None:
                existing_state = str(existing["state"])
                if current_state == "stale" and existing_state == "pending":
                    self._conn.execute(
                        "UPDATE tutor_curation_proposals SET state = 'stale' WHERE id = %s",
                        (existing["id"],),
                    )
                    self._conn.execute(
                        "UPDATE tutor_memory_curation_outbox SET state = 'stale' WHERE id = %s",
                        (outbox_id,),
                    )
                    existing_state = "stale"
                if (
                    str(existing["kind"]) != kind
                    or str(existing["payload_hash"]) != payload_hash
                    or str(existing["confidence"]) != confidence
                    or str(existing["policy_version"]) != policy_version
                    or str(existing["memory_setting_version"]) != memory_setting_version
                    or existing_state != current_state
                ):
                    raise TutorIdempotencyConflict("outbox already has a different proposal envelope")
                return TutorCurationProposalReceipt(
                    proposal_id=str(existing["id"]),
                    outbox_id=outbox_id,
                    kind=str(existing["kind"]),
                    state=existing_state,
                    replayed=True,
                )
            if current_state != str(outbox["state"]):
                self._conn.execute(
                    "UPDATE tutor_memory_curation_outbox SET state = %s WHERE id = %s",
                    (current_state, outbox_id),
                )
            event = self._append_event_locked(
                run_id=str(outbox["run_id"]),
                event_key=f"proposal:{outbox_id}",
                kind="curation_proposal_recorded",
                input_revision=_as_int(outbox["input_revision"], 0),
                payload={
                    "kind": "curation_proposal_recorded",
                    "outbox_id": outbox_id,
                    "state": current_state,
                    "code": kind,
                    "input_revision": _as_int(outbox["input_revision"], 0),
                    "policy_version": policy_version,
                    "memory_setting_version": memory_setting_version,
                    "payload_hash": payload_hash,
                },
            )
            provenance = self._projector.project(
                {
                    "outbox_id": outbox_id,
                    "run_id": str(outbox["run_id"]),
                    "event_from_sequence": _as_int(outbox["event_from_sequence"], 0),
                    "event_to_sequence": _as_int(outbox["event_to_sequence"], 0),
                    "source_ids": _as_list(outbox.get("source_ids_json")),
                    "source_hashes": _as_list(outbox.get("source_hashes_json")),
                }
            )
            row = self._conn.execute(
                """
                INSERT INTO tutor_curation_proposals (
                  outbox_id, event_id, kind, state, event_from_sequence, event_to_sequence,
                  provenance_json, payload_json, payload_hash, confidence,
                  policy_version, memory_setting_version, retention_until, stale_after, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    outbox_id,
                    event.event_id,
                    kind,
                    current_state,
                    _as_int(outbox["event_from_sequence"], 0),
                    _as_int(outbox["event_to_sequence"], 0),
                    _json(provenance),
                    _json(safe_payload),
                    payload_hash,
                    confidence,
                    policy_version,
                    memory_setting_version,
                    outbox["retention_until"],
                    outbox["stale_after"],
                    created_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("curation proposal insert failed")
            return TutorCurationProposalReceipt(
                proposal_id=str(row["id"]), outbox_id=outbox_id, kind=kind, state=current_state, replayed=False
            )

    def _persist_checkpoint_and_outbox_locked(
        self,
        *,
        run: Mapping[str, object],
        checkpoint: TutorCheckpoint,
        envelope: TutorCurationEnvelope,
        terminal_message_id: str | None = None,
    ) -> TutorTraceRecord:
        metadata = checkpoint.metadata.as_dict()
        safe_checkpoint = self._projector.checkpoint(
            metadata=metadata,
            status=checkpoint.status.value,
            reason=checkpoint.reason.value,
            input_revision=checkpoint.input_revision,
        )
        metadata_hash = self._projector.fingerprint(safe_checkpoint)
        checkpoint_row = self._conn.execute(
            """
            INSERT INTO tutor_run_checkpoints (
              run_id, input_revision, reason, status, metadata_json, metadata_hash, created_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (run_id, input_revision, reason, status) DO NOTHING
            RETURNING id
            """,
            (
                run["id"],
                checkpoint.input_revision,
                checkpoint.reason.value,
                checkpoint.status.value,
                _json(safe_checkpoint),
                metadata_hash,
                checkpoint.created_at,
            ),
        ).fetchone()
        if checkpoint_row is None:
            checkpoint_row = self._conn.execute(
                """
                SELECT id FROM tutor_run_checkpoints
                WHERE run_id = %s AND input_revision = %s AND reason = %s AND status = %s
                """,
                (run["id"], checkpoint.input_revision, checkpoint.reason.value, checkpoint.status.value),
            ).fetchone()
        if checkpoint_row is None:
            raise RuntimeError("checkpoint receipt is missing")
        event_kind = "terminal_result" if checkpoint.reason.value == "terminal" else "checkpoint_saved"
        event_payload: dict[str, object] = {
            **safe_checkpoint,
            "kind": event_kind,
            "run_id": str(run["id"]),
            "catalog_digest": str(run["catalog_digest"]),
            "policy_version": str(run["policy_version"]),
        }
        if terminal_message_id is not None:
            event_payload["message_id"] = terminal_message_id
        event = self._append_event_locked(
            run_id=str(run["id"]),
            event_key=f"checkpoint:{checkpoint.input_revision}:{checkpoint.reason.value}:{checkpoint.status.value}",
            kind=event_kind,
            input_revision=checkpoint.input_revision,
            payload=event_payload,
        )
        self._trip_failpoint("after_event")
        trace = self._insert_trace_locked(
            run_id=str(run["id"]),
            kind="terminal_checkpoint" if event_kind == "terminal_result" else "checkpoint",
            event_sequence=event.event_sequence,
            payload=safe_checkpoint,
            created_at=checkpoint.created_at,
        )
        self._trip_failpoint("after_trace")
        self._upsert_outbox_locked(
            run=run,
            envelope=envelope,
            trace_id=trace.trace_id,
            event_sequence=event.event_sequence,
            created_at=checkpoint.created_at,
        )
        self._trip_failpoint("after_outbox")
        return trace

    def _upsert_outbox_locked(
        self,
        *,
        run: Mapping[str, object],
        envelope: TutorCurationEnvelope,
        trace_id: str,
        event_sequence: int,
        created_at: datetime,
    ) -> TutorCurationOutboxReceipt:
        request = envelope.request
        if request.run_id != str(run["id"]) or request.conversation_id != str(run["conversation_id"]):
            raise TutorPersistenceError("curation request does not match target run scope")
        _safe_key(request.curation_idempotency_key, label="curation idempotency key")
        raw_source_ids = list(request.source_ids)
        expected_source_hashes = [str(value).lower() for value in request.source_hashes]
        safe_sources = self._projector.export(
            {"source_ids": raw_source_ids, "source_hashes": expected_source_hashes}
        )
        safe_source_ids = _as_list(safe_sources.get("source_ids"))
        safe_source_hashes = _as_list(safe_sources.get("source_hashes"))
        if safe_source_ids != raw_source_ids or safe_source_hashes != expected_source_hashes:
            raise TutorPersistenceError("curation request source evidence is unsafe or malformed")
        retention_until = envelope.retention_until or (created_at + timedelta(days=_DEFAULT_RETENTION_DAYS))
        stale_after = envelope.stale_after or (created_at + timedelta(days=_DEFAULT_STALE_DAYS))
        if stale_after > retention_until:
            raise ValueError("curation stale boundary cannot exceed retention")
        payload = self._projector.compaction(
            {
                **_compaction_payload(request, status="pending"),
                "source_ids": safe_source_ids,
                "source_hashes": safe_source_hashes,
                "trace_id": trace_id,
                "event_from_sequence": event_sequence,
                "event_to_sequence": event_sequence,
                "policy_version": str(run["policy_version"]),
                "memory_setting_version": envelope.memory_setting_version,
                "priority": envelope.priority,
                "retention_until": retention_until,
                "stale_after": stale_after,
            }
        )
        row = self._conn.execute(
            """
            INSERT INTO tutor_memory_curation_outbox (
              run_id, conversation_id, input_revision, trigger,
              event_from_sequence, event_to_sequence, trace_id,
              source_ids_json, source_hashes_json, policy_version, memory_setting_version,
              projection_kind, summary_schema_version, summary_policy_version,
              summary_source_hash, prior_summary_id, prior_summary_hash,
              covered_through_created_at, covered_through_message_id,
              priority, retention_until, stale_after, state, idempotency_key, envelope_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, 'pending', %s, %s::jsonb, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id, idempotency_key, state
            """,
            (
                run["id"],
                run["conversation_id"],
                request.input_revision,
                request.trigger.value,
                event_sequence,
                event_sequence,
                trace_id,
                _json(safe_source_ids),
                _json(safe_source_hashes),
                run["policy_version"],
                envelope.memory_setting_version,
                request.projection_kind,
                request.summary_schema_version,
                request.summary_policy_version,
                request.summary_source_hash,
                request.prior_summary_id,
                request.prior_summary_hash,
                request.covered_through_created_at,
                request.covered_through_message_id,
                envelope.priority,
                retention_until,
                stale_after,
                request.curation_idempotency_key,
                _json(payload),
                created_at,
            ),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM tutor_memory_curation_outbox WHERE idempotency_key = %s FOR UPDATE",
                (request.curation_idempotency_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("curation outbox replay row is missing")
            common_conflict = (
                str(row["run_id"]) != str(run["id"])
                or str(row["conversation_id"]) != str(run["conversation_id"])
                or _as_int(row["input_revision"], -1) != request.input_revision
                or _as_list(row.get("source_ids_json")) != safe_source_ids
                or _as_list(row.get("source_hashes_json")) != safe_source_hashes
                or str(row["policy_version"]) != str(run["policy_version"])
                or str(row["memory_setting_version"]) != envelope.memory_setting_version
                or str(row.get("projection_kind") or "memory_or_summary") != request.projection_kind
                or _as_int(row["priority"], -1) != envelope.priority
            )
            structured_conflict = request.projection_kind == "context_summary" and (
                _optional_text(row, "summary_schema_version") != request.summary_schema_version
                or _optional_text(row, "summary_policy_version") != request.summary_policy_version
                or _optional_text(row, "summary_source_hash") != request.summary_source_hash
                or _optional_text(row, "prior_summary_id") != request.prior_summary_id
                or _optional_text(row, "prior_summary_hash") != request.prior_summary_hash
                or _as_datetime(row.get("covered_through_created_at")) != request.covered_through_created_at
                or _optional_text(row, "covered_through_message_id") != request.covered_through_message_id
            )
            legacy_conflict = request.projection_kind == "memory_or_summary" and (
                str(row["trigger"]) != request.trigger.value
                or _as_int(row["event_from_sequence"], -1) != event_sequence
                or _as_int(row["event_to_sequence"], -1) != event_sequence
                or str(row["trace_id"]) != trace_id
            )
            if common_conflict or structured_conflict or legacy_conflict:
                raise TutorIdempotencyConflict("curation idempotency key conflicts with durable evidence")
            return TutorCurationOutboxReceipt(
                outbox_id=str(row["id"]), idempotency_key=str(row["idempotency_key"]), state=str(row["state"]), replayed=True
            )
        return TutorCurationOutboxReceipt(
            outbox_id=str(row["id"]), idempotency_key=str(row["idempotency_key"]), state=str(row["state"]), replayed=False
        )
