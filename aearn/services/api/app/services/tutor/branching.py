"""Durable depth-one clarification branches anchored to blocking Artifacts."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from psycopg import Connection
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from app.services.tutor.branch_contracts import (
    BranchAssistanceKind,
    BranchAssistanceReceiptKind,
    BranchControlKind,
    BranchMessageClassification,
    BranchResponseDisposition,
    TutorPublicBranchGroupV1,
    TutorPublicBranchGroupV2,
    TutorPublicBranchGroup,
    TutorPublicBranchItemReferenceV1,
    branch_response_policy,
    classify_branch_message,
)
from app.services.tutor.continuation import (
    ContinuationIntentRecord,
    PostgresTutorContinuationIntentRepository,
)


_STABLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,199}$")
_BRANCH_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://aearn.local/contracts/tutor-conversation-branch-v1",
)


class TutorBranchError(ValueError):
    pass


class TutorBranchNotFound(TutorBranchError):
    pass


class TutorBranchConflict(TutorBranchError):
    pass


class TutorBranchStale(TutorBranchError):
    pass


@dataclass(frozen=True, slots=True)
class TutorBranchRecord:
    branch_id: str
    user_id: str
    conversation_id: str
    learning_track_id: str
    knowledge_key: str
    teaching_session_id: str
    checkpoint_id: str
    artifact_id: str
    predecessor_branch_id: str | None
    state: str
    version: int
    round_count: int
    latest_disposition: BranchResponseDisposition | None
    opened_turn_id: str
    opened_message_id: str
    opened_input_revision: int
    resolved_turn_id: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    superseded_by_session_id: str | None = None
    superseded_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TutorBranchTurnBinding:
    branch: TutorBranchRecord
    run_id: str
    message_id: str
    input_revision: int
    classification: BranchMessageClassification
    control_kind: BranchControlKind | None
    continuation: ContinuationIntentRecord | None
    replayed: bool


class PostgresTutorBranchRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def bind_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str,
        message_id: str,
        input_revision: int,
        control_kind: BranchControlKind | str | None = None,
        occurred_at: datetime | None = None,
    ) -> TutorBranchTurnBinding | None:
        if input_revision < 1:
            raise ValueError("branch input revision must be positive")
        classification, control = classify_branch_message(control_kind)
        now = _utc(occurred_at or datetime.now(UTC))
        with self._conn.transaction():
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            existing_scope = self._conn.execute(
                """
                SELECT scopes.*, branches.*
                FROM tutor_run_branch_scopes AS scopes
                JOIN tutor_conversation_branches AS branches
                  ON branches.id = scopes.branch_id
                 AND branches.user_id = scopes.user_id
                 AND branches.conversation_id = scopes.conversation_id
                 AND branches.artifact_id = scopes.artifact_id
                WHERE scopes.run_id = %s AND scopes.user_id = %s
                  AND scopes.conversation_id = %s
                FOR UPDATE OF branches
                """,
                (run_id, user_id, conversation_id),
            ).fetchone()
            if existing_scope is not None:
                if (
                    str(existing_scope["source_message_id"]) != message_id
                    or _integer(existing_scope["source_input_revision"]) != input_revision
                    or str(existing_scope["message_classification"])
                    != classification.value
                    or _optional(existing_scope.get("control_kind"))
                    != (control.value if control is not None else None)
                ):
                    raise TutorBranchConflict(
                        "Tutor Turn is already bound to a different branch input"
                    )
                return TutorBranchTurnBinding(
                    branch=self._record(existing_scope),
                    run_id=run_id,
                    message_id=message_id,
                    input_revision=input_revision,
                    classification=classification,
                    control_kind=control,
                    continuation=None,
                    replayed=True,
                )
            scope = self._active_artifact_scope(
                user_id=user_id,
                conversation_id=conversation_id,
                run_id=run_id,
                message_id=message_id,
                input_revision=input_revision,
            )
            if scope is None:
                return None
            active = self._conn.execute(
                """
                SELECT * FROM tutor_conversation_branches
                WHERE artifact_id = %s AND user_id = %s AND conversation_id = %s
                  AND state = 'active'
                FOR UPDATE
                """,
                (scope["artifact_id"], user_id, conversation_id),
            ).fetchone()
            if active is None:
                branch = self._open_branch(
                    scope=scope,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    message_id=message_id,
                    input_revision=input_revision,
                    classification=classification,
                    control_kind=control,
                    occurred_at=now,
                )
            else:
                branch = self._bind_additional_turn(
                    row=active,
                    run_id=run_id,
                    message_id=message_id,
                    input_revision=input_revision,
                    classification=classification,
                    control_kind=control,
                    occurred_at=now,
                )
            try:
                self._conn.execute(
                    """
                    INSERT INTO tutor_run_branch_scopes (
                      run_id, user_id, conversation_id, branch_id, artifact_id,
                      teaching_session_id, checkpoint_id, learning_track_id,
                      knowledge_key, branch_version, branch_round,
                      source_message_id, source_input_revision,
                      message_classification, control_kind, created_at
                    ) VALUES (
                      %s, %s, %s, %s, %s,
                      %s, %s, %s,
                      %s, %s, %s,
                      %s, %s,
                      %s, %s, %s
                    )
                    """,
                    (
                        run_id,
                        user_id,
                        conversation_id,
                        branch["id"],
                        branch["artifact_id"],
                        branch["teaching_session_id"],
                        scope["run_checkpoint_id"],
                        branch["learning_track_id"],
                        branch["knowledge_key"],
                        branch["version"],
                        branch["round_count"],
                        message_id,
                        input_revision,
                        classification.value,
                        control.value if control is not None else None,
                        now,
                    ),
                )
                self._append_item(
                    branch=branch,
                    run_id=run_id,
                    branch_round=_integer(branch["round_count"]),
                    item_kind="message",
                    item_id=message_id,
                    item_role="learner",
                    occurred_at=now,
                )
                self._append_item(
                    branch=branch,
                    run_id=run_id,
                    branch_round=_integer(branch["round_count"]),
                    item_kind="process",
                    item_id=run_id,
                    item_role="process",
                    occurred_at=now,
                )
            except (CheckViolation, ForeignKeyViolation) as exc:
                raise TutorBranchStale(
                    "Tutor branch Turn scope is stale or mismatched"
                ) from exc
            except UniqueViolation as exc:
                raise TutorBranchConflict(
                    "Tutor branch membership conflicts with durable evidence"
                ) from exc
            return TutorBranchTurnBinding(
                branch=self._record(branch),
                run_id=run_id,
                message_id=message_id,
                input_revision=input_revision,
                classification=classification,
                control_kind=control,
                continuation=None,
                replayed=False,
            )

    def complete_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str,
        response_message_id: str,
        assistance_kind: BranchAssistanceKind | str = BranchAssistanceKind.NONE,
        assistance_receipt_kind: BranchAssistanceReceiptKind | str | None = None,
        assistance_receipt_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> TutorBranchRecord | None:
        assistance = BranchAssistanceKind(str(assistance_kind))
        receipt_kind = (
            BranchAssistanceReceiptKind(str(assistance_receipt_kind))
            if assistance_receipt_kind is not None
            else None
        )
        if assistance is BranchAssistanceKind.NONE:
            if receipt_kind is not None or assistance_receipt_id is not None:
                raise ValueError(
                    "branch response without assistance cannot carry a receipt"
                )
        elif receipt_kind is None or assistance_receipt_id is None:
            raise ValueError(
                "branch assistance requires exactly one authoritative receipt"
            )
        now = _utc(occurred_at or datetime.now(UTC))
        with self._conn.transaction():
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            row = self._conn.execute(
                """
                SELECT branches.*, scopes.branch_round, scopes.source_message_id,
                       scopes.source_input_revision, scopes.message_classification,
                       scopes.control_kind, runs.terminal_outcome,
                       processes.tutor_message_id
                FROM tutor_run_branch_scopes AS scopes
                JOIN tutor_conversation_branches AS branches
                  ON branches.id = scopes.branch_id
                 AND branches.user_id = scopes.user_id
                 AND branches.conversation_id = scopes.conversation_id
                 AND branches.artifact_id = scopes.artifact_id
                JOIN tutor_runs AS runs
                  ON runs.id = scopes.run_id AND runs.user_id = scopes.user_id
                 AND runs.conversation_id = scopes.conversation_id
                JOIN tutor_run_public_processes AS processes
                  ON processes.run_id = scopes.run_id
                 AND processes.user_id = scopes.user_id
                 AND processes.conversation_id = scopes.conversation_id
                WHERE scopes.run_id = %s AND scopes.user_id = %s
                  AND scopes.conversation_id = %s
                FOR UPDATE OF branches
                """,
                (run_id, user_id, conversation_id),
            ).fetchone()
            if row is None:
                return None
            if str(row.get("terminal_outcome") or "") != "completed":
                raise TutorBranchConflict(
                    "Tutor branch response requires a completed Turn"
                )
            if str(row.get("tutor_message_id") or "") != response_message_id:
                raise TutorBranchConflict(
                    "Tutor branch response message is not authoritative for the Turn"
                )
            existing = self._conn.execute(
                """
                SELECT * FROM tutor_conversation_branch_events
                WHERE branch_id = %s AND event_kind = 'response_recorded'
                  AND source_turn_id = %s AND response_message_id = %s
                """,
                (row["id"], run_id, response_message_id),
            ).fetchone()
            if existing is not None:
                return self._record(row)
            prior = _optional(row.get("latest_disposition"))
            policy = branch_response_policy(
                classification=str(row["message_classification"]),
                control_kind=_optional(row.get("control_kind")),
                prior_disposition=prior,
            )
            if assistance is not BranchAssistanceKind.NONE:
                assert receipt_kind is not None and assistance_receipt_id is not None
                self._assert_assistance_receipt(
                    row=row,
                    run_id=run_id,
                    assistance_kind=assistance,
                    receipt_kind=receipt_kind,
                    receipt_id=assistance_receipt_id,
                )
            self._append_item(
                branch=row,
                run_id=run_id,
                branch_round=_integer(row["branch_round"]),
                item_kind="message",
                item_id=response_message_id,
                item_role="tutor",
                occurred_at=now,
            )
            next_version = _integer(row["version"]) + 1
            event_id = str(uuid4())
            request_hash = _hash(
                {
                    "branch_id": str(row["id"]),
                    "run_id": run_id,
                    "response_message_id": response_message_id,
                    "disposition": policy.disposition.value,
                    "assistance_kind": assistance.value,
                    "assistance_receipt_kind": (
                        receipt_kind.value if receipt_kind is not None else None
                    ),
                    "assistance_receipt_id": assistance_receipt_id,
                }
            )
            self._insert_event(
                branch=row,
                event_id=event_id,
                predecessor_event_id=str(row["current_event_id"]),
                branch_version=next_version,
                event_key=f"response:{run_id}:{response_message_id}",
                event_kind="response_recorded",
                classification=BranchMessageClassification(
                    str(row["message_classification"])
                ),
                control_kind=(
                    BranchControlKind(str(row["control_kind"]))
                    if row.get("control_kind") is not None
                    else None
                ),
                source_turn_id=run_id,
                source_message_id=str(row["source_message_id"]),
                source_input_revision=_integer(row["source_input_revision"]),
                request_hash=request_hash,
                occurred_at=now,
                disposition=policy.disposition,
                response_message_id=response_message_id,
                assistance_kind=assistance,
                assistance_receipt_kind=receipt_kind,
                assistance_receipt_id=assistance_receipt_id,
            )
            resolved_state = "resolved" if policy.resolves_branch else "active"
            updated = self._conn.execute(
                """
                UPDATE tutor_conversation_branches
                SET state = %s, current_event_id = %s, version = %s,
                    latest_disposition = %s,
                    resolved_turn_id = %s, resolved_at = %s, updated_at = %s
                WHERE id = %s AND user_id = %s AND conversation_id = %s
                  AND version = %s AND current_event_id = %s AND state = 'active'
                RETURNING *
                """,
                (
                    resolved_state,
                    event_id,
                    next_version,
                    policy.disposition.value,
                    run_id if policy.resolves_branch else None,
                    now if policy.resolves_branch else None,
                    now,
                    row["id"],
                    user_id,
                    conversation_id,
                    row["version"],
                    row["current_event_id"],
                ),
            ).fetchone()
            if updated is None:
                raise TutorBranchConflict("Tutor branch changed before response CAS")
            return self._record(updated)

    def supersede_authority(
        self, *, branch_id: str, user_id: str, conversation_id: str,
        learning_track_id: str, knowledge_key: str, teaching_session_id: str,
        successor_session_id: str, expected_version: int, expected_event_id: str,
        expected_session_version: int, expected_successor_version: int,
    ) -> TutorBranchRecord:
        """Retire only a proven direct replacement; never dispatch a continuation.

        The caller owns the outer transaction. A savepoint also prevents an
        event without its root CAS if the caller catches a domain conflict.
        """
        request_hash = _hash({
            "branch_id": branch_id, "user_id": user_id, "conversation_id": conversation_id,
            "learning_track_id": learning_track_id, "knowledge_key": knowledge_key,
            "teaching_session_id": teaching_session_id, "successor_session_id": successor_session_id,
            "expected_version": expected_version, "expected_event_id": expected_event_id,
            "expected_session_version": expected_session_version,
            "expected_successor_version": expected_successor_version,
        })
        event_key = f"authority-superseded:{successor_session_id}"
        with self._conn.transaction():
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            sessions = self._conn.execute(
                """SELECT * FROM tutor_teaching_sessions WHERE id IN (%s,%s)
                   AND user_id=%s AND conversation_id=%s AND track_id=%s AND knowledge_key=%s
                   ORDER BY id FOR UPDATE""",
                (teaching_session_id, successor_session_id, user_id, conversation_id,
                 learning_track_id, knowledge_key),
            ).fetchall()
            by_id = {str(row["id"]): row for row in sessions}
            if teaching_session_id not in by_id or successor_session_id not in by_id:
                raise TutorBranchConflict("Tutor branch replacement session scope is invalid")
            branch = self._conn.execute(
                """SELECT * FROM tutor_conversation_branches WHERE id=%s AND user_id=%s
                   AND conversation_id=%s AND learning_track_id=%s AND knowledge_key=%s
                   AND teaching_session_id=%s FOR UPDATE""",
                (branch_id, user_id, conversation_id, learning_track_id, knowledge_key, teaching_session_id),
            ).fetchone()
            if branch is None:
                raise TutorBranchNotFound("Tutor branch replacement scope was not found")
            event = self._conn.execute(
                "SELECT * FROM tutor_conversation_branch_events WHERE branch_id=%s AND event_key=%s",
                (branch_id, event_key),
            ).fetchone()
            if event is not None:
                if (event["request_hash"] != request_hash or branch["state"] != "superseded"
                        or branch["current_event_id"] != event["id"]):
                    raise TutorBranchConflict("Tutor branch replacement replay conflicts")
                return self._record(branch)
            if (branch["state"] != "active" or _integer(branch["version"]) != expected_version
                    or str(branch["current_event_id"]) != expected_event_id
                    or _integer(by_id[teaching_session_id]["version"]) != expected_session_version
                    or _integer(by_id[successor_session_id]["version"]) != expected_successor_version):
                raise TutorBranchConflict("Tutor branch replacement authority CAS changed")
            proof = self._conn.execute(
                "SELECT tutor_branch_authority_replacement_valid(%s,%s,%s,%s,%s,%s) AS valid",
                (user_id, conversation_id, learning_track_id, knowledge_key,
                 teaching_session_id, successor_session_id),
            ).fetchone()
            if proof is None or proof["valid"] is not True:
                raise TutorBranchConflict("Tutor branch requires an inactive replaced authority")
            event_id = str(uuid4())
            now = datetime.now(UTC)
            self._conn.execute(
                """INSERT INTO tutor_conversation_branch_events (
                   id,branch_id,user_id,conversation_id,artifact_id,predecessor_event_id,
                   branch_version,event_key,event_kind,message_classification,
                   source_turn_id,source_message_id,source_input_revision,
                   superseding_session_id,request_hash,created_at
                 ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'authority_superseded','normal',
                           NULL,NULL,NULL,%s,%s,%s)""",
                (event_id, branch_id, user_id, conversation_id, branch["artifact_id"],
                 expected_event_id, expected_version + 1, event_key,
                 successor_session_id, request_hash, now),
            )
            updated = self._conn.execute(
                """UPDATE tutor_conversation_branches SET state='superseded',
                   superseded_by_session_id=%s,superseded_at=%s,current_event_id=%s,
                   version=version+1,updated_at=%s
                   WHERE id=%s AND user_id=%s AND conversation_id=%s AND state='active'
                     AND version=%s AND current_event_id=%s RETURNING *""",
                (successor_session_id, now, event_id, now, branch_id, user_id,
                 conversation_id, expected_version, expected_event_id),
            ).fetchone()
            if updated is None:
                raise TutorBranchConflict("Tutor branch changed before replacement CAS")
            return self._record(updated)

    def read_for_artifact(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
    ) -> TutorBranchRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_conversation_branches
            WHERE user_id = %s AND conversation_id = %s AND artifact_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, conversation_id, artifact_id),
        ).fetchone()
        return self._record(row) if row is not None else None

    def list_snapshot_groups(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> tuple[TutorPublicBranchGroup, ...]:
        branches = self._conn.execute(
            """
            SELECT * FROM tutor_conversation_branches
            WHERE user_id = %s AND conversation_id = %s
            ORDER BY created_at, id
            LIMIT 50
            """,
            (user_id, conversation_id),
        ).fetchall()
        if not branches:
            return ()
        branch_ids = [row["id"] for row in branches]
        item_rows = self._conn.execute(
            """
            SELECT * FROM tutor_conversation_branch_items
            WHERE user_id = %s AND conversation_id = %s AND branch_id = ANY(%s)
            ORDER BY branch_id, item_sequence
            """,
            (user_id, conversation_id, branch_ids),
        ).fetchall()
        grouped: dict[str, list[TutorPublicBranchItemReferenceV1]] = {}
        for item in item_rows:
            grouped.setdefault(str(item["branch_id"]), []).append(
                TutorPublicBranchItemReferenceV1(
                    item_sequence=_integer(item["item_sequence"]),
                    branch_round=_integer(item["branch_round"]),
                    item_kind=cast(
                        Literal["message", "process"], str(item["item_kind"])
                    ),
                    item_id=str(item["item_id"]),
                    turn_id=str(item["run_id"]),
                    item_role=cast(
                        Literal["learner", "tutor", "process"],
                        str(item["item_role"]),
                    ),
                )
            )
        result: list[TutorPublicBranchGroup] = []
        for branch in branches:
            items = tuple(grouped.get(str(branch["id"]), ()))
            if not items:
                raise TutorBranchConflict(
                    "stored Tutor branch has no explicit item membership"
                )
            group_type = TutorPublicBranchGroupV2 if branch["state"] == "superseded" else TutorPublicBranchGroupV1
            extra = {"superseded_at": _iso(branch["superseded_at"])} if branch["state"] == "superseded" else {}
            result.append(
                group_type.model_validate(dict(
                    branch_id=str(branch["id"]),
                    anchor_artifact_id=str(branch["artifact_id"]),
                    teaching_session_id=str(branch["teaching_session_id"]),
                    checkpoint_id=str(branch["checkpoint_id"]),
                    state=str(branch["state"]),
                    disposition=(
                        BranchResponseDisposition(str(branch["latest_disposition"]))
                        if branch.get("latest_disposition") is not None
                        else None
                    ),
                    round_count=_integer(branch["round_count"]),
                    item_count=len(items),
                    collapsed=str(branch["state"]) != "active",
                    items=items,
                    created_at=_iso(branch["created_at"]),
                    resolved_at=(
                        _iso(branch["resolved_at"])
                        if branch.get("resolved_at") is not None
                        else None
                    ),
                    **extra,
                ))
            )
        return tuple(result)

    def _open_branch(
        self,
        *,
        scope: Mapping[str, object],
        user_id: str,
        conversation_id: str,
        run_id: str,
        message_id: str,
        input_revision: int,
        classification: BranchMessageClassification,
        control_kind: BranchControlKind | None,
        occurred_at: datetime,
    ) -> Mapping[str, object]:
        predecessor = self._conn.execute(
            """
            SELECT id FROM tutor_conversation_branches
            WHERE artifact_id = %s AND user_id = %s AND conversation_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (scope["artifact_id"], user_id, conversation_id),
        ).fetchone()
        branch_id = str(
            uuid5(
                _BRANCH_NAMESPACE,
                f"{user_id}:{conversation_id}:{scope['artifact_id']}:{run_id}",
            )
        )
        event_id = str(uuid4())
        request_hash = _hash(
            {
                "branch_id": branch_id,
                "artifact_id": str(scope["artifact_id"]),
                "run_id": run_id,
                "message_id": message_id,
                "input_revision": input_revision,
                "classification": classification.value,
                "control_kind": control_kind.value if control_kind is not None else None,
            }
        )
        try:
            row = self._conn.execute(
                """
                INSERT INTO tutor_conversation_branches (
                  id, user_id, conversation_id, learning_track_id, knowledge_key,
                  teaching_session_id, checkpoint_id, artifact_id,
                  predecessor_branch_id, current_event_id, version, round_count,
                  opened_turn_id, opened_message_id, opened_input_revision,
                  created_at, updated_at
                ) VALUES (
                  %s, %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, %s, 1, 1,
                  %s, %s, %s,
                  %s, %s
                ) RETURNING *
                """,
                (
                    branch_id,
                    user_id,
                    conversation_id,
                    scope["learning_track_id"],
                    scope["knowledge_key"],
                    scope["teaching_session_id"],
                    scope["checkpoint_id"],
                    scope["artifact_id"],
                    predecessor["id"] if predecessor is not None else None,
                    event_id,
                    run_id,
                    message_id,
                    input_revision,
                    occurred_at,
                    occurred_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Tutor branch insert failed")
            self._insert_event(
                branch=row,
                event_id=event_id,
                predecessor_event_id=None,
                branch_version=1,
                event_key=f"opened:{run_id}:{input_revision}",
                event_kind="opened",
                classification=classification,
                control_kind=control_kind,
                source_turn_id=run_id,
                source_message_id=message_id,
                source_input_revision=input_revision,
                request_hash=request_hash,
                occurred_at=occurred_at,
            )
            return row
        except (CheckViolation, ForeignKeyViolation) as exc:
            raise TutorBranchStale(
                "Tutor branch Artifact or TeachingSession scope is stale"
            ) from exc
        except UniqueViolation as exc:
            raise TutorBranchConflict(
                "Tutor branch active-anchor or lineage identity conflicts"
            ) from exc

    def _bind_additional_turn(
        self,
        *,
        row: Mapping[str, object],
        run_id: str,
        message_id: str,
        input_revision: int,
        classification: BranchMessageClassification,
        control_kind: BranchControlKind | None,
        occurred_at: datetime,
    ) -> Mapping[str, object]:
        if _integer(row["round_count"]) >= 100:
            raise TutorBranchConflict("Tutor branch round limit was reached")
        if control_kind is BranchControlKind.CONFIRM_TOPIC_SWITCH and str(
            row.get("latest_disposition") or ""
        ) != BranchResponseDisposition.OFFER_SWITCH.value:
            raise TutorBranchConflict(
                "topic switch confirmation requires a prior switch offer"
            )
        next_version = _integer(row["version"]) + 1
        event_id = str(uuid4())
        request_hash = _hash(
            {
                "branch_id": str(row["id"]),
                "run_id": run_id,
                "message_id": message_id,
                "input_revision": input_revision,
                "classification": classification.value,
                "control_kind": control_kind.value if control_kind is not None else None,
            }
        )
        self._insert_event(
            branch=row,
            event_id=event_id,
            predecessor_event_id=str(row["current_event_id"]),
            branch_version=next_version,
            event_key=f"turn:{run_id}:{input_revision}",
            event_kind="turn_bound",
            classification=classification,
            control_kind=control_kind,
            source_turn_id=run_id,
            source_message_id=message_id,
            source_input_revision=input_revision,
            request_hash=request_hash,
            occurred_at=occurred_at,
        )
        updated = self._conn.execute(
            """
            UPDATE tutor_conversation_branches
            SET current_event_id = %s, version = %s,
                round_count = round_count + 1, updated_at = %s
            WHERE id = %s AND version = %s AND current_event_id = %s
              AND state = 'active'
            RETURNING *
            """,
            (
                event_id,
                next_version,
                occurred_at,
                row["id"],
                row["version"],
                row["current_event_id"],
            ),
        ).fetchone()
        if updated is None:
            raise TutorBranchConflict("Tutor branch changed before Turn binding CAS")
        return updated

    def _insert_event(
        self,
        *,
        branch: Mapping[str, object],
        event_id: str,
        predecessor_event_id: str | None,
        branch_version: int,
        event_key: str,
        event_kind: str,
        classification: BranchMessageClassification,
        control_kind: BranchControlKind | None,
        source_turn_id: str,
        source_message_id: str,
        source_input_revision: int,
        request_hash: str,
        occurred_at: datetime,
        disposition: BranchResponseDisposition | None = None,
        response_message_id: str | None = None,
        assistance_kind: BranchAssistanceKind = BranchAssistanceKind.NONE,
        assistance_receipt_kind: BranchAssistanceReceiptKind | None = None,
        assistance_receipt_id: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO tutor_conversation_branch_events (
              id, branch_id, user_id, conversation_id, artifact_id,
              predecessor_event_id, branch_version, event_key, event_kind,
              message_classification, control_kind, disposition,
              source_turn_id, source_message_id, source_input_revision,
              response_message_id, assistance_kind, assistance_receipt_kind,
              assistance_receipt_id, request_hash, created_at
            ) VALUES (
              %s, %s, %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s
            )
            """,
            (
                event_id,
                branch["id"],
                branch["user_id"],
                branch["conversation_id"],
                branch["artifact_id"],
                predecessor_event_id,
                branch_version,
                _stable(event_key, "branch event key"),
                event_kind,
                classification.value,
                control_kind.value if control_kind is not None else None,
                disposition.value if disposition is not None else None,
                source_turn_id,
                source_message_id,
                source_input_revision,
                response_message_id,
                assistance_kind.value,
                (
                    assistance_receipt_kind.value
                    if assistance_receipt_kind is not None
                    else None
                ),
                assistance_receipt_id,
                request_hash,
                occurred_at,
            ),
        )

    def _append_item(
        self,
        *,
        branch: Mapping[str, object],
        run_id: str,
        branch_round: int,
        item_kind: str,
        item_id: str,
        item_role: str,
        occurred_at: datetime,
    ) -> None:
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_conversation_branch_items
            WHERE conversation_id = %s AND item_kind = %s AND item_id = %s
            """,
            (branch["conversation_id"], item_kind, item_id),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["branch_id"]) != str(branch["id"])
                or str(existing["run_id"]) != run_id
                or _integer(existing["branch_round"]) != branch_round
                or str(existing["item_role"]) != item_role
            ):
                raise TutorBranchConflict(
                    "Tutor public item already belongs to another branch"
                )
            return
        sequence = self._conn.execute(
            """
            SELECT COALESCE(max(item_sequence), 0) + 1 AS next_sequence
            FROM tutor_conversation_branch_items
            WHERE branch_id = %s
            """,
            (branch["id"],),
        ).fetchone()
        next_sequence = _integer(sequence["next_sequence"] if sequence else 1)
        self._conn.execute(
            """
            INSERT INTO tutor_conversation_branch_items (
              branch_id, user_id, conversation_id, artifact_id, run_id,
              branch_round, item_sequence, item_kind, item_id, item_role, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                branch["id"],
                branch["user_id"],
                branch["conversation_id"],
                branch["artifact_id"],
                run_id,
                branch_round,
                next_sequence,
                item_kind,
                item_id,
                item_role,
                occurred_at,
            ),
        )

    def _active_artifact_scope(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str,
        message_id: str,
        input_revision: int,
    ) -> Mapping[str, object] | None:
        return self._conn.execute(
            """
            SELECT artifacts.id AS artifact_id, artifacts.user_id,
                   artifacts.conversation_id, artifacts.learning_track_id,
                   artifacts.knowledge_key, artifacts.teaching_session_id,
                   artifacts.checkpoint_id, scopes.checkpoint_id AS run_checkpoint_id
            FROM tutor_run_teaching_scopes AS scopes
            JOIN tutor_run_input_events AS inputs
              ON inputs.run_id = scopes.run_id
             AND inputs.message_id = %s AND inputs.input_revision = %s
            JOIN tutor_learning_artifacts AS artifacts
              ON artifacts.user_id = scopes.user_id
             AND artifacts.conversation_id = scopes.conversation_id
             AND artifacts.teaching_session_id = scopes.teaching_session_id
             AND artifacts.learning_track_id = scopes.track_id
             AND artifacts.knowledge_key = scopes.knowledge_key
            WHERE scopes.run_id = %s AND scopes.user_id = %s
              AND scopes.conversation_id = %s
              AND tutor_teaching_checkpoint_descends_from(
                    scopes.checkpoint_id, artifacts.checkpoint_id,
                    artifacts.teaching_session_id, artifacts.user_id,
                    artifacts.conversation_id
                  )
              AND artifacts.blocking
              AND artifacts.state IN ('pending', 'ready', 'active', 'running')
            ORDER BY artifacts.created_at DESC, artifacts.id DESC
            LIMIT 1
            FOR UPDATE OF artifacts
            """,
            (message_id, input_revision, run_id, user_id, conversation_id),
        ).fetchone()

    def _assert_assistance_receipt(
        self,
        *,
        row: Mapping[str, object],
        run_id: str,
        assistance_kind: BranchAssistanceKind,
        receipt_kind: BranchAssistanceReceiptKind,
        receipt_id: str,
    ) -> None:
        params: tuple[object, ...]
        if assistance_kind is BranchAssistanceKind.HINT:
            if receipt_kind is BranchAssistanceReceiptKind.EXERCISE_HINT:
                query = """
                    SELECT 1
                    FROM tutor_exercise_hint_receipts AS receipts
                    JOIN tutor_learning_artifacts AS artifacts
                      ON artifacts.id = %s
                     AND artifacts.user_id = receipts.user_id
                     AND artifacts.learning_track_id = receipts.track_id
                     AND artifacts.knowledge_key = receipts.knowledge_key
                     AND artifacts.owner_kind = 'lesson_gate'
                    JOIN tutor_lesson_gate_states AS states
                      ON states.id = artifacts.owner_id
                     AND states.user_id = artifacts.user_id
                     AND states.track_id = artifacts.learning_track_id
                     AND states.knowledge_key = artifacts.knowledge_key
                     AND states.gate_binding_id = receipts.gate_binding_id
                     AND states.lesson_assignment_id = receipts.lesson_assignment_id
                    WHERE receipts.id = %s AND receipts.user_id = %s
                      AND receipts.track_id = %s AND receipts.knowledge_key = %s
                """
            elif receipt_kind is BranchAssistanceReceiptKind.REVIEW_HINT:
                query = """
                    SELECT 1
                    FROM tutor_review_hint_receipts AS receipts
                    JOIN tutor_learning_artifacts AS artifacts
                      ON artifacts.id = %s
                     AND artifacts.user_id = receipts.user_id
                     AND artifacts.learning_track_id = receipts.track_id
                     AND artifacts.knowledge_key = receipts.knowledge_key
                     AND artifacts.owner_kind = 'review_item'
                     AND artifacts.owner_id = receipts.item_id
                    WHERE receipts.id = %s AND receipts.user_id = %s
                      AND receipts.track_id = %s AND receipts.knowledge_key = %s
                """
            else:
                raise TutorBranchConflict(
                    "branch hint assistance requires a Hint policy receipt"
                )
            params = (
                row["artifact_id"],
                receipt_id,
                row["user_id"],
                row["learning_track_id"],
                row["knowledge_key"],
            )
        else:
            if receipt_kind is not BranchAssistanceReceiptKind.TEACHING_ACTION:
                raise TutorBranchConflict(
                    "branch direct answer requires a Teaching action receipt"
                )
            query = """
                SELECT 1 FROM tutor_teaching_action_receipts
                WHERE id = %s AND run_id = %s AND user_id = %s
                  AND teaching_session_id = %s AND action = 'answer_question'
            """
            params = (
                receipt_id,
                run_id,
                row["user_id"],
                row["teaching_session_id"],
            )
        if self._conn.execute(query, params).fetchone() is None:
            raise TutorBranchConflict(
                "branch assistance receipt is stale or outside the exact scope"
            )

    def _lock_conversation(self, *, user_id: str, conversation_id: str) -> None:
        row = self._conn.execute(
            """
            SELECT id FROM tutor_conversations
            WHERE id = %s AND user_id = %s AND visibility = 'learner'
              AND kind = 'interactive' AND status = 'active'
            FOR UPDATE
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorBranchNotFound("Tutor conversation was not found")

    @staticmethod
    def _record(row: Mapping[str, object]) -> TutorBranchRecord:
        return TutorBranchRecord(
            branch_id=str(row["id"]),
            user_id=str(row["user_id"]),
            conversation_id=str(row["conversation_id"]),
            learning_track_id=str(row["learning_track_id"]),
            knowledge_key=str(row["knowledge_key"]),
            teaching_session_id=str(row["teaching_session_id"]),
            checkpoint_id=str(row["checkpoint_id"]),
            artifact_id=str(row["artifact_id"]),
            predecessor_branch_id=(
                str(row["predecessor_branch_id"])
                if row.get("predecessor_branch_id") is not None
                else None
            ),
            state=str(row["state"]),
            version=_integer(row["version"]),
            round_count=_integer(row["round_count"]),
            latest_disposition=(
                BranchResponseDisposition(str(row["latest_disposition"]))
                if row.get("latest_disposition") is not None
                else None
            ),
            opened_turn_id=str(row["opened_turn_id"]),
            opened_message_id=str(row["opened_message_id"]),
            opened_input_revision=_integer(row["opened_input_revision"]),
            resolved_turn_id=(
                str(row["resolved_turn_id"])
                if row.get("resolved_turn_id") is not None
                else None
            ),
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
            resolved_at=(
                _datetime(row["resolved_at"])
                if row.get("resolved_at") is not None
                else None
            ),
            superseded_by_session_id=(str(row["superseded_by_session_id"])
                if row.get("superseded_by_session_id") is not None else None),
            superseded_at=(_datetime(row["superseded_at"])
                if row.get("superseded_at") is not None else None),
        )


class TutorClarificationBranchService:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._branches = PostgresTutorBranchRepository(conn)
        self._continuations = PostgresTutorContinuationIntentRepository(conn)

    def bind_learner_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str,
        message_id: str,
        input_revision: int,
        control_kind: BranchControlKind | str | None = None,
        occurred_at: datetime | None = None,
    ) -> TutorBranchTurnBinding | None:
        with self._conn.transaction():
            binding = self._branches.bind_turn(
                user_id=user_id,
                conversation_id=conversation_id,
                run_id=run_id,
                message_id=message_id,
                input_revision=input_revision,
                control_kind=control_kind,
                occurred_at=occurred_at,
            )
            if binding is None:
                return None
            continuation = self._continuations.record_learner_turn(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=binding.branch.artifact_id,
                branch_id=binding.branch.branch_id,
                message_id=message_id,
                input_revision=input_revision,
                run_id=run_id,
                occurred_at=occurred_at,
            )
            return TutorBranchTurnBinding(
                branch=binding.branch,
                run_id=binding.run_id,
                message_id=binding.message_id,
                input_revision=binding.input_revision,
                classification=binding.classification,
                control_kind=binding.control_kind,
                continuation=continuation,
                replayed=binding.replayed and continuation.replayed,
            )

    def complete_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str,
        response_message_id: str,
        assistance_kind: BranchAssistanceKind | str = BranchAssistanceKind.NONE,
        assistance_receipt_kind: BranchAssistanceReceiptKind | str | None = None,
        assistance_receipt_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> TutorBranchRecord | None:
        return self._branches.complete_turn(
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            response_message_id=response_message_id,
            assistance_kind=assistance_kind,
            assistance_receipt_kind=assistance_receipt_kind,
            assistance_receipt_id=assistance_receipt_id,
            occurred_at=occurred_at,
        )


def _hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable(value: object, label: str) -> str:
    normalized = str(value).strip()
    if not _STABLE.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable bounded identifier")
    return normalized


def _optional(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("expected integer")
    if isinstance(value, int):
        return value
    return int(str(value or 0))


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("expected datetime")
    return _utc(value)


def _iso(value: object) -> str:
    return _datetime(value).isoformat()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = (
    "PostgresTutorBranchRepository",
    "TutorBranchConflict",
    "TutorBranchError",
    "TutorBranchNotFound",
    "TutorBranchRecord",
    "TutorBranchStale",
    "TutorBranchTurnBinding",
    "TutorClarificationBranchService",
)
