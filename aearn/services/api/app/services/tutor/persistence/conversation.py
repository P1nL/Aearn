"""Tutor persistence 的 conversation 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._namespace import *
from ._mixin import PersistenceMixin


class ConversationPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

    def create_conversation(self, *, user_id: str, conversation_id: str | None = None) -> str:
        conversation_id = conversation_id or str(uuid4())
        row = self._conn.execute(
            """
            INSERT INTO tutor_conversations (id, user_id, status)
            SELECT %s, users.id, 'active'
            FROM users
            WHERE users.id = %s
            RETURNING id
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor user not found")
        return str(row["id"])

    def resolve_learner_conversation(self, *, user_id: str, conversation_id: str) -> str:
        row = self._conn.execute(
            """
            SELECT id
            FROM tutor_conversations
            WHERE id = %s
              AND user_id = %s
              AND visibility = 'learner'
              AND kind = 'interactive'
              AND status = 'active'
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor conversation not found")
        return str(row["id"])

    def create_or_resume_learner_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str | None = None,
    ) -> tuple[str, bool]:
        if conversation_id is not None:
            return self.resolve_learner_conversation(user_id=user_id, conversation_id=conversation_id), False
        return self.create_conversation(user_id=user_id), True

    def _lock_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str,
        learner_only: bool = False,
    ) -> Mapping[str, object]:
        clauses = ["id = %s", "user_id = %s", "status = 'active'"]
        if learner_only:
            clauses.extend(("visibility = 'learner'", "kind = 'interactive'"))
        row = self._conn.execute(
            f"SELECT * FROM tutor_conversations WHERE {' AND '.join(clauses)} FOR UPDATE",
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor conversation not found")
        return row

    def _lock_learner_conversation(self, *, user_id: str, conversation_id: str) -> Mapping[str, object]:
        return self._lock_conversation(user_id=user_id, conversation_id=conversation_id, learner_only=True)

    def _lock_run_with_conversation(
        self,
        *,
        user_id: str,
        run_id: str,
        learner_only: bool = False,
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        """Lock a run's conversation before its run row to serialize latest-input-wins.

        Normal turns lock the conversation then the foreground run. Every later
        unsafe write follows the same ordering, so a newly accepted turn either
        replaces the old run first or waits behind a write that is already
        authoritative; it cannot race a stale post-provider write around it.
        """

        reference = self._conn.execute(
            "SELECT conversation_id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if reference is None:
            raise TutorRunNotFound("tutor run not found")
        conversation = self._lock_conversation(
            user_id=user_id,
            conversation_id=str(reference["conversation_id"]),
            learner_only=learner_only,
        )
        run = self._lock_run(user_id=user_id, run_id=run_id)
        if str(run["conversation_id"]) != str(conversation["id"]):
            raise TutorPersistenceError("Tutor run conversation scope is inconsistent")
        return conversation, run

    def _touch_conversation_public_activity_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        occurred_at: datetime,
    ) -> None:
        updated = self._conn.execute(
            """
            UPDATE tutor_conversations
            SET last_public_activity_at = GREATEST(last_public_activity_at, %s)
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (occurred_at, conversation_id, user_id),
        ).fetchone()
        if updated is None:
            raise TutorRunNotFound("tutor conversation not found")

    def _increment_control_version_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        event_key: str,
        occurred_at: datetime,
        turn_id: str | None,
    ) -> int:
        row = self._conn.execute(
            """
            UPDATE tutor_conversations
            SET control_version = control_version + 1
            WHERE id = %s AND user_id = %s
            RETURNING control_version
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor conversation not found")
        version = max(1, _as_int(row.get("control_version"), 1))
        self._append_conversation_event_locked(
            user_id=user_id,
            conversation_id=conversation_id,
            event_key=event_key,
            kind=TutorConversationEventKind.CONTROL_UPDATED,
            payload={"control_version": version},
            occurred_at=occurred_at,
        )
        return version

    def _write_conversation_title_once_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        candidate: str | None,
    ) -> None:
        if candidate is None:
            return
        try:
            title = normalize_tutor_conversation_title(candidate)
        except ValueError:
            return
        self._conn.execute(
            """
            UPDATE tutor_conversations
            SET title = %s
            WHERE id = %s AND user_id = %s AND title IS NULL
            """,
            (title, conversation_id, user_id),
        )

    def list_public_conversations(
        self,
        *,
        user_id: str,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[tuple[TutorConversationSummary, ...], str | None, bool]:
        if limit < 1 or limit > 40:
            raise ValueError("conversation page limit is invalid")
        after = self._decode_public_cursor(
            cursor=cursor,
            kind="conversation-list",
            user_id=user_id,
            conversation_id=None,
        ) if cursor else None
        query = """
            SELECT conversations.id AS conversation_id,
                   conversations.title,
                   conversations.last_public_activity_at,
                   foreground.id AS active_run_id,
                   foreground.status AS active_run_status,
                   foreground.continuation_kind AS active_run_continuation_kind
            FROM tutor_conversations AS conversations
            LEFT JOIN LATERAL (
              SELECT runs.id, runs.status, runs.continuation_kind
              FROM tutor_runs AS runs
              WHERE runs.user_id = conversations.user_id
                AND runs.conversation_id = conversations.id
                AND runs.origin = 'interactive'
                AND runs.terminal_outcome IS NULL
                AND runs.cancelled_at IS NULL
                AND runs.superseded_by_run_id IS NULL
              ORDER BY runs.created_at DESC, runs.id DESC
              LIMIT 1
            ) AS foreground ON TRUE
            WHERE conversations.user_id = %s
              AND conversations.visibility = 'learner'
              AND conversations.kind = 'interactive'
              AND conversations.status = 'active'
              AND (
                EXISTS (SELECT 1 FROM tutor_messages AS messages WHERE messages.conversation_id = conversations.id)
                OR EXISTS (SELECT 1 FROM tutor_run_public_processes AS processes WHERE processes.conversation_id = conversations.id)
                OR EXISTS (
                  SELECT 1
                  FROM tutor_learning_artifacts AS artifacts
                  WHERE artifacts.conversation_id = conversations.id
                    AND artifacts.user_id = conversations.user_id
                )
              )
        """
        params: list[object] = [user_id]
        if after is not None:
            query += """
              AND (
                conversations.last_public_activity_at < %s
                OR (
                  conversations.last_public_activity_at = %s
                  AND conversations.id < %s::uuid
                )
              )
            """
            params.extend((after["created_at"], after["created_at"], after["item_id"]))
        query += """
            ORDER BY conversations.last_public_activity_at DESC, conversations.id DESC
            LIMIT %s
        """
        params.append(limit + 1)
        rows = self._conn.execute(query, tuple(params)).fetchall()
        page_rows = rows[:limit]
        items: list[TutorConversationSummary] = []
        for row in page_rows:
            continuation_value = row.get("active_run_continuation_kind")
            try:
                continuation_kind = TutorContinuationKind(str(continuation_value)) if continuation_value is not None else None
            except ValueError:
                continuation_kind = None
            items.append(
                TutorConversationSummary(
                    conversation_id=str(row["conversation_id"]),
                    title=str(row["title"]) if row.get("title") is not None else None,
                    last_public_activity_at=_as_datetime(row.get("last_public_activity_at")) or datetime.now(UTC),
                    active_run_id=str(row["active_run_id"]) if row.get("active_run_id") is not None else None,
                    active_run_status=str(row["active_run_status"]) if row.get("active_run_status") is not None else None,
                    active_run_continuation_kind=continuation_kind,
                )
            )
        has_more = len(rows) > limit
        next_cursor = (
            self._encode_public_cursor(
                kind="conversation-list",
                user_id=user_id,
                conversation_id=None,
                created_at=items[-1].last_public_activity_at,
                sort_rank=0,
                item_id=items[-1].conversation_id,
            )
            if has_more and items
            else None
        )
        return tuple(items), next_cursor, has_more

    def read_public_foreground_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> TutorPublicForegroundRun | None:
        self.resolve_learner_conversation(user_id=user_id, conversation_id=conversation_id)
        row = self._conn.execute(
            """
            SELECT id, status, continuation_kind
            FROM tutor_runs
            WHERE user_id = %s
              AND conversation_id = %s
              AND origin = 'interactive'
              AND terminal_outcome IS NULL
              AND cancelled_at IS NULL
              AND superseded_by_run_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, conversation_id),
        ).fetchone()
        if row is None:
            return None
        raw_kind = row.get("continuation_kind")
        try:
            continuation_kind = TutorContinuationKind(str(raw_kind)) if raw_kind is not None else None
        except ValueError:
            continuation_kind = None
        return TutorPublicForegroundRun(
            run_id=str(row["id"]),
            status=str(row["status"]),
            continuation_kind=continuation_kind,
        )

    def _runtime_output_for_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str,
    ) -> dict[str, object] | None:
        rows = self._conn.execute(
            """
            SELECT items.id, items.channel, items.state, items.text, items.last_event_sequence,
                   items.connection_generation, runs.input_revision AS run_input_revision
            FROM tutor_runtime_text_items AS items
            JOIN tutor_runs AS runs ON runs.id = items.run_id
            JOIN tutor_messages AS messages ON messages.id = items.public_message_id
            JOIN tutor_conversations AS conversations ON conversations.id = messages.conversation_id
            WHERE items.user_id = %s AND items.conversation_id = %s
              AND items.public_message_id = %s
              AND conversations.user_id = %s AND conversations.id = %s
              AND items.state = 'completed' AND items.text <> ''
            ORDER BY items.created_at, items.id
            """,
            (user_id, conversation_id, message_id, user_id, conversation_id),
        ).fetchall()
        return self._runtime_output_payload(rows) if rows else None

    def _runtime_output_for_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str,
    ) -> dict[str, object] | None:
        rows = self._conn.execute(
            """
            SELECT items.id, items.channel, items.state, items.text, items.last_event_sequence,
                   items.connection_generation, runs.input_revision AS run_input_revision
            FROM tutor_runtime_text_items AS items
            JOIN tutor_runs AS runs ON runs.id = items.run_id
            WHERE items.user_id = %s AND items.conversation_id = %s AND items.run_id = %s
              AND runs.user_id = %s AND runs.conversation_id = %s
              AND items.state IN ('streaming', 'completed')
              AND items.text <> ''
            ORDER BY items.created_at, items.id
            """,
            (user_id, conversation_id, run_id, user_id, conversation_id),
        ).fetchall()
        return self._runtime_output_payload(rows) if rows else None

    @staticmethod
    def _runtime_output_payload(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
        reasoning_items: list[dict[str, object]] = []
        final_answer_item: dict[str, object] | None = None
        for row in rows:
            item = {
                "item_id": str(row["id"]),
                "text": str(row.get("text") or ""),
                "state": str(row.get("state") or "streaming"),
                "last_sequence": _as_int(row.get("last_event_sequence"), 0),
            }
            if str(row.get("channel") or "") == "reasoning":
                reasoning_items.append(item)
            elif str(row.get("channel") or "") == "final_answer":
                final_answer_item = item
        first = rows[0]
        return {
            "output_version": TUTOR_RUNTIME_OUTPUT_VERSION,
            "input_revision": _as_int(first.get("run_input_revision"), 0),
            "generation": _as_int(first.get("connection_generation"), 1),
            "reasoning_items": reasoning_items,
            "final_answer_item": final_answer_item,
        }

    def read_public_history(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int,
        cursor: str | None = None,
        now: datetime | None = None,
        include_errors: bool = False,
    ) -> tuple[tuple[TutorConversationTimelineRecord, ...], str | None, bool]:
        if limit < 1 or limit > 40:
            raise ValueError("history page limit is invalid")
        self.resolve_learner_conversation(user_id=user_id, conversation_id=conversation_id)
        after = self._decode_public_cursor(
            cursor=cursor,
            kind="conversation-history",
            user_id=user_id,
            conversation_id=conversation_id,
        ) if cursor else None
        timeline = """
            WITH timeline AS (
              SELECT
                'message'::text AS kind,
                messages.id AS item_id,
                messages.created_at AS created_at,
                CASE WHEN messages.role = 'learner' THEN 10 ELSE 30 END AS sort_rank,
                messages.role AS role,
                messages.content AS content,
                messages.public_thinking_text AS public_thinking_text,
                messages.public_thinking_steps_json AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                COALESCE(input_events.run_id, tutor_process.run_id) AS turn_id,
                NULL::text AS error_code,
                NULL::boolean AS error_recoverable,
                replied_requests.item_id AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_messages AS messages
              JOIN tutor_conversations AS conversations ON conversations.id = messages.conversation_id
              LEFT JOIN tutor_run_input_events AS input_events ON input_events.message_id = messages.id
              LEFT JOIN tutor_runs AS response_runs ON response_runs.id = input_events.run_id
              LEFT JOIN tutor_interaction_requests AS replied_requests
                ON replied_requests.id = response_runs.response_to_request_id
              LEFT JOIN tutor_run_public_processes AS tutor_process ON tutor_process.tutor_message_id = messages.id
              WHERE conversations.id = %s
                AND conversations.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
              UNION ALL
              SELECT
                'process'::text AS kind,
                processes.run_id AS item_id,
                processes.started_at AS created_at,
                20 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                processes.run_id AS process_run_id,
                processes.run_id AS turn_id,
                NULL::text AS error_code,
                NULL::boolean AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_run_public_processes AS processes
              JOIN tutor_conversations AS conversations ON conversations.id = processes.conversation_id
              WHERE processes.conversation_id = %s
                AND processes.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
              UNION ALL
              SELECT
                CASE WHEN requests.kind = 'approval' THEN 'approval' ELSE 'elicitation' END AS kind,
                requests.item_id AS item_id,
                requests.created_at AS created_at,
                35 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                requests.source_turn_id AS turn_id,
                NULL::text AS error_code,
                NULL::boolean AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                requests.id AS interaction_request_id
              FROM tutor_interaction_requests AS requests
              JOIN tutor_conversations AS conversations ON conversations.id = requests.conversation_id
              WHERE requests.conversation_id = %s
                AND requests.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
              UNION ALL
              SELECT
                'artifact'::text AS kind,
                artifacts.id AS item_id,
                artifacts.created_at AS created_at,
                34 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                artifacts.turn_id AS turn_id,
                NULL::text AS error_code,
                NULL::boolean AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_learning_artifacts AS artifacts
              JOIN tutor_conversations AS conversations ON conversations.id = artifacts.conversation_id
              WHERE artifacts.conversation_id = %s
                AND artifacts.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
        """
        params: list[object] = [
            conversation_id, user_id,
            conversation_id, user_id,
            conversation_id, user_id,
            conversation_id, user_id,
        ]
        if include_errors:
            timeline += """
              UNION ALL
              SELECT
                'error'::text AS kind,
                jobs.id AS item_id,
                jobs.dead_at AS created_at,
                40 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                jobs.run_id AS turn_id,
                'TUTOR_DISPATCH_FAILED'::text AS error_code,
                true AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_interactive_dispatch_jobs AS jobs
              JOIN tutor_conversations AS conversations ON conversations.id = jobs.conversation_id
              WHERE jobs.conversation_id = %s
                AND jobs.user_id = %s
                AND jobs.state = 'dead'
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
              UNION ALL
              SELECT
                'error'::text AS kind,
                errors.id AS item_id,
                errors.created_at AS created_at,
                40 AS sort_rank,
                NULL::text AS role,
                NULL::text AS content,
                ''::text AS public_thinking_text,
                '[]'::jsonb AS public_thinking_steps_json,
                NULL::uuid AS process_run_id,
                errors.run_id AS turn_id,
                errors.code AS error_code,
                errors.recoverable AS error_recoverable,
                NULL::uuid AS in_reply_to_item_id,
                NULL::uuid AS interaction_request_id
              FROM tutor_runtime_public_errors AS errors
              JOIN tutor_conversations AS conversations ON conversations.id = errors.conversation_id
              WHERE errors.conversation_id = %s
                AND errors.user_id = %s
                AND conversations.visibility = 'learner'
                AND conversations.kind = 'interactive'
                AND conversations.status = 'active'
            """
            params.extend((conversation_id, user_id, conversation_id, user_id))
        timeline += """
            )
            SELECT * FROM timeline
        """
        if after is not None:
            timeline += """
            WHERE (
              created_at < %s
              OR (
                created_at = %s
                AND (
                  sort_rank < %s
                  OR (sort_rank = %s AND item_id < %s::uuid)
                )
              )
            )
            """
            params.extend(
                (
                    after["created_at"],
                    after["created_at"],
                    after["sort_rank"],
                    after["sort_rank"],
                    after["item_id"],
                )
            )
        timeline += " ORDER BY created_at DESC, sort_rank DESC, item_id DESC LIMIT %s"
        params.append(limit + 1)
        rows = self._conn.execute(timeline, tuple(params)).fetchall()
        page_rows = rows[:limit]
        from app.services.learning.context_references import PostgresTutorContextReferenceRepository

        learner_message_ids = [
            str(row["item_id"])
            for row in page_rows
            if str(row.get("kind") or "") == "message" and str(row.get("role") or "") == "learner"
        ]
        references_by_message = PostgresTutorContextReferenceRepository(self._conn).read_for_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            message_ids=learner_message_ids,
        )
        artifact_repository = None
        if any(str(row.get("kind") or "") == "artifact" for row in page_rows):
            from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository

            artifact_repository = PostgresLearningArtifactRepository(self._conn)
        records: list[TutorConversationTimelineRecord] = []
        for row in page_rows:
            kind = str(row["kind"])
            created_at = _as_datetime(row.get("created_at")) or datetime.now(UTC)
            if kind == "message":
                role = str(row.get("role") or "")
                if role not in {"learner", "tutor"}:
                    continue
                records.append(
                    TutorConversationTimelineRecord(
                        kind="message",
                        item_id=str(row["item_id"]),
                        created_at=created_at,
                        sort_rank=_as_int(row.get("sort_rank"), 0),
                        role=role,
                        content=str(row.get("content") or ""),
                        public_thinking_text=(
                            _public_thinking_text_from_values(
                                row.get("public_thinking_text"),
                                row.get("public_thinking_steps_json"),
                            )
                            if role == "tutor"
                            else ""
                        ),
                        public_thinking_steps=(
                            _public_thinking_steps_from_value(
                                row.get("public_thinking_steps_json")
                            )
                            if role == "tutor"
                            else ()
                        ),
                        runtime_output=(
                            self._runtime_output_for_message(
                                user_id=user_id,
                                conversation_id=conversation_id,
                                message_id=str(row["item_id"]),
                            )
                            if role == "tutor"
                            else None
                        ),
                        context_references=references_by_message.get(str(row["item_id"]), ()),
                        turn_id=str(row["turn_id"]) if row.get("turn_id") is not None else None,
                        in_reply_to_item_id=_optional_string(row.get("in_reply_to_item_id")),
                    )
                )
                continue
            if kind == "artifact":
                if artifact_repository is None:
                    raise RuntimeError("artifact repository was not initialized for artifact timeline row")
                artifact = artifact_repository.read_artifact(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    artifact_id=str(row["item_id"]),
                )
                records.append(
                    TutorConversationTimelineRecord(
                        kind="artifact",
                        item_id=artifact.id,
                        created_at=created_at,
                        sort_rank=_as_int(row.get("sort_rank"), 0),
                        turn_id=artifact.turn_id,
                        artifact=artifact,
                    )
                )
                continue
            if kind in {"elicitation", "approval"}:
                request_id = _optional_string(row.get("interaction_request_id"))
                if request_id is None:
                    continue
                request_row = self._conn.execute(
                    "SELECT * FROM tutor_interaction_requests WHERE id = %s AND user_id = %s",
                    (request_id, user_id),
                ).fetchone()
                if request_row is not None:
                    request = _interaction_request_from_row(request_row)
                    records.append(
                        TutorConversationTimelineRecord(
                            kind=kind,
                            item_id=request.item_id,
                            created_at=created_at,
                            sort_rank=_as_int(row.get("sort_rank"), 0),
                            turn_id=request.source_turn_id,
                            request=request,
                        )
                    )
                continue
            if kind == "error":
                records.append(
                    TutorConversationTimelineRecord(
                        kind="error",
                        item_id=str(row["item_id"]),
                        created_at=created_at,
                        sort_rank=_as_int(row.get("sort_rank"), 0),
                        turn_id=_optional_string(row.get("turn_id")),
                        error_code=str(row.get("error_code") or "TUTOR_DISPATCH_FAILED"),
                        error_recoverable=row.get("error_recoverable") is True,
                    )
                )
                continue
            if kind == "process":
                process_run_id = str(row.get("process_run_id") or "")
                process = self.read_public_process(user_id=user_id, run_id=process_run_id, now=now)
                if process is not None:
                    records.append(
                        TutorConversationTimelineRecord(
                            kind="process",
                            item_id=process.run_id,
                            created_at=created_at,
                            sort_rank=_as_int(row.get("sort_rank"), 0),
                            process=process,
                            turn_id=process.run_id,
                        )
                    )
        has_more = len(rows) > limit
        next_cursor = (
            self._encode_public_cursor(
                kind="conversation-history",
                user_id=user_id,
                conversation_id=conversation_id,
                created_at=records[-1].created_at,
                sort_rank=records[-1].sort_rank,
                item_id=records[-1].item_id,
            )
            if has_more and records
            else None
        )
        return tuple(records), next_cursor, has_more

    def _encode_public_cursor(
        self,
        *,
        kind: str,
        user_id: str,
        conversation_id: str | None,
        created_at: datetime,
        sort_rank: int,
        item_id: str,
    ) -> str:
        payload = {
            "v": _CURSOR_VERSION,
            "k": kind,
            "u": user_id,
            "c": conversation_id,
            "t": created_at.astimezone(UTC).isoformat(),
            "r": sort_rank,
            "i": item_id,
        }
        encoded = _base64url_encode(_json(payload).encode("utf-8"))
        signature = hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_base64url_encode(signature)}"

    def _decode_public_cursor(
        self,
        *,
        cursor: str,
        kind: str,
        user_id: str,
        conversation_id: str | None,
    ) -> dict[str, object]:
        parts = cursor.split(".")
        if len(parts) != 2 or not all(parts):
            raise TutorCursorInvalid("cursor is invalid")
        encoded, supplied_signature = parts
        expected_signature = _base64url_encode(
            hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise TutorCursorInvalid("cursor is invalid")
        try:
            payload = _as_mapping(json.loads(_base64url_decode(encoded).decode("utf-8")))
            parsed_created_at = _as_datetime(payload.get("t"))
            parsed_rank = _as_int(payload.get("r"), -1)
            item_id = str(payload.get("i") or "")
            valid = (
                _as_int(payload.get("v"), -1) == _CURSOR_VERSION
                and str(payload.get("k") or "") == kind
                and str(payload.get("u") or "") == user_id
                and payload.get("c") == conversation_id
                and parsed_created_at is not None
                and parsed_rank >= 0
                and bool(item_id)
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            valid = False
            parsed_created_at = None
            parsed_rank = -1
            item_id = ""
        if not valid or parsed_created_at is None:
            raise TutorCursorInvalid("cursor is invalid")
        return {"created_at": parsed_created_at, "sort_rank": parsed_rank, "item_id": item_id}

    def read_conversation_snapshot(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int = 40,
        cursor: str | None = None,
        now: datetime | None = None,
    ) -> TutorConversationSnapshot:
        conversation = self._conn.execute(
            """
            SELECT *
            FROM tutor_conversations
            WHERE id = %s AND user_id = %s
              AND visibility = 'learner' AND kind = 'interactive' AND status = 'active'
            FOR SHARE
            """,
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise TutorRunNotFound("tutor conversation not found")
        timeline, next_cursor, has_more = self.read_public_history(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=limit,
            cursor=cursor,
            now=now,
            include_errors=True,
        )
        active = self._conn.execute(
            """
            SELECT *
            FROM tutor_runs
            WHERE user_id = %s AND conversation_id = %s AND origin = 'interactive'
              AND terminal_outcome IS NULL AND cancelled_at IS NULL AND superseded_by_run_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, conversation_id),
        ).fetchone()
        artifact_state = self._conn.execute(
            """
            SELECT
              EXISTS (
                SELECT 1
                FROM tutor_learning_artifacts
                WHERE user_id = %s AND conversation_id = %s
              ) AS has_artifacts,
              (
                SELECT id
                FROM tutor_learning_artifacts
                WHERE user_id = %s AND conversation_id = %s
                  AND blocking
                  AND state IN ('pending', 'ready', 'active', 'running')
                ORDER BY created_at DESC, id DESC
                LIMIT 1
              ) AS active_artifact_id
            """,
            (user_id, conversation_id, user_id, conversation_id),
        ).fetchone()
        active_artifact = None
        active_artifact_id = (
            _optional_string(artifact_state.get("active_artifact_id"))
            if artifact_state is not None
            else None
        )
        if active_artifact_id is not None:
            from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository

            active_artifact = PostgresLearningArtifactRepository(self._conn).read_artifact(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=active_artifact_id,
            )
        has_artifacts = bool(
            artifact_state is not None and artifact_state.get("has_artifacts") is True
        )
        pending_requests = self.read_pending_interaction_requests(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        queue_rows = self._conn.execute(
            "SELECT * FROM tutor_queued_inputs WHERE user_id = %s AND conversation_id = %s AND state = 'pending' ORDER BY position, created_at, id",
            (user_id, conversation_id),
        ).fetchall()
        queued_inputs = tuple(_queued_input_from_row(row) for row in queue_rows)
        queue_paused = bool(conversation.get("queue_paused"))
        control_state = (
            "waiting" if pending_requests else
            "running" if active is not None else
            "queue_paused" if queue_paused else
            "idle"
        )
        current_sequence = max(0, _as_int(conversation.get("next_public_event_sequence"), 1) - 1)
        return TutorConversationSnapshot(
            conversation_id=conversation_id,
            title=str(conversation["title"]) if conversation.get("title") is not None else None,
            control_version=max(1, _as_int(conversation.get("control_version"), 1)),
            control_state=control_state,
            queue_paused=queue_paused,
            queue_pause_reason=_optional_string(conversation.get("queue_pause_reason")),
            pending_count=len(queued_inputs),
            max_pending=_QUEUE_MAX_PENDING,
            active_turn=self._public_turn_from_row(active) if active is not None else None,
            active_thinking=(
                self._public_active_thinking_from_row(active)
                if active is not None
                else None
            ),
            active_runtime_output=(
                self._runtime_output_for_run(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    run_id=str(active["id"]),
                )
                if active is not None
                and str(active.get("runtime_kind") or "") == "codex_sidecar_v1"
                else None
            ),
            active_artifact=active_artifact,
            pending_requests=tuple(item.public_item for item in pending_requests),
            queue=tuple(item.as_public_dict() for item in queued_inputs),
            timeline=timeline,
            next_cursor=next_cursor,
            has_more=has_more,
            stream_cursor=self._encode_conversation_event_cursor(
                user_id=user_id,
                conversation_id=conversation_id,
                sequence=current_sequence,
            ),
            snapshot_version=(
                TUTOR_CONVERSATION_SNAPSHOT_V4_VERSION
                if has_artifacts
                else TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION
            ),
        )

    def append_conversation_event(
        self,
        *,
        user_id: str,
        conversation_id: str,
        event_key: str,
        kind: TutorConversationEventKind | str,
        payload: Mapping[str, object],
        occurred_at: datetime,
        turn_id: str | None = None,
        item_id: str | None = None,
        item_kind: str | None = None,
    ) -> TutorConversationEvent:
        with self._conn.transaction():
            return self._append_conversation_event_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=event_key,
                kind=kind,
                payload=payload,
                occurred_at=occurred_at,
                turn_id=turn_id,
                item_id=item_id,
                item_kind=item_kind,
            )

    def append_artifact_item_reference(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        artifact_version: int,
        turn_id: str | None,
        kind: Literal["item_added", "item_updated"],
        occurred_at: datetime,
    ) -> TutorConversationEvent:
        if artifact_version < 1:
            raise ValueError("artifact item reference version must be positive")
        normalized_kind = TutorConversationEventKind(kind)
        event_key = (
            f"item:artifact:{artifact_id}:{normalized_kind.value}:{artifact_version}"
        )
        with self._conn.transaction():
            event = self._append_conversation_event_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=event_key,
                kind=normalized_kind,
                turn_id=turn_id,
                item_id=artifact_id,
                item_kind="artifact",
                payload={
                    "item": {
                        "item_id": artifact_id,
                        "item_kind": "artifact",
                        "turn_id": turn_id,
                    }
                },
                occurred_at=occurred_at,
            )
            self._touch_conversation_public_activity_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                occurred_at=event.occurred_at,
            )
            return event

    def conversation_events_after(
        self,
        *,
        user_id: str,
        conversation_id: str,
        cursor: str | None,
        limit: int = 100,
    ) -> tuple[TutorConversationEvent, ...]:
        if limit < 1 or limit > 200:
            raise ValueError("conversation event replay limit is invalid")
        conversation = self._conn.execute(
            """
            SELECT next_public_event_sequence
            FROM tutor_conversations
            WHERE id = %s AND user_id = %s
              AND visibility = 'learner' AND kind = 'interactive' AND status = 'active'
            """,
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise TutorRunNotFound("tutor conversation not found")
        after_sequence = (
            self._decode_conversation_event_cursor(
                cursor=cursor,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if cursor
            else 0
        )
        current_sequence = max(0, _as_int(conversation.get("next_public_event_sequence"), 1) - 1)
        if after_sequence > current_sequence:
            raise TutorCursorInvalid("conversation event cursor is ahead of the authoritative sequence")
        minimum = self._conn.execute(
            "SELECT MIN(event_sequence) AS minimum FROM tutor_conversation_events WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        minimum_sequence = _as_int(minimum.get("minimum") if minimum is not None else None, 0)
        if minimum_sequence > 0 and after_sequence < minimum_sequence - 1:
            raise TutorCursorInvalid("conversation event cursor is older than the retained event window")
        rows = self._conn.execute(
            """
            SELECT *
            FROM tutor_conversation_events
            WHERE user_id = %s AND conversation_id = %s AND event_sequence > %s
            ORDER BY event_sequence ASC
            LIMIT %s
            """,
            (user_id, conversation_id, after_sequence, limit),
        ).fetchall()
        return tuple(
            _conversation_event_from_row(
                row,
                cursor=self._encode_conversation_event_cursor(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sequence=_as_int(row.get("event_sequence"), 0),
                ),
            )
            for row in rows
        )

    def _append_turn_event_locked(
        self,
        *,
        run: Mapping[str, object],
        kind: TutorConversationEventKind,
        event_key: str,
        occurred_at: datetime,
    ) -> TutorConversationEvent | None:
        if (
            str(run.get("origin") or "") != "interactive"
            or _protocol_version_from_row(run) is not TutorInteractionProtocolVersion.THREAD_TURN_V2
        ):
            return None
        return self._append_conversation_event_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            event_key=event_key,
            kind=kind,
            turn_id=str(run["id"]),
            payload={"turn": self._public_turn_from_row(run)},
            occurred_at=occurred_at,
        )

    def _append_item_reference_event_locked(
        self,
        *,
        run: Mapping[str, object],
        event_key: str,
        kind: TutorConversationEventKind,
        item_id: str,
        item_kind: str,
        occurred_at: datetime,
    ) -> TutorConversationEvent | None:
        if (
            str(run.get("origin") or "") != "interactive"
            or _protocol_version_from_row(run) is not TutorInteractionProtocolVersion.THREAD_TURN_V2
        ):
            return None
        return self._append_conversation_event_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            event_key=event_key,
            kind=kind,
            turn_id=str(run["id"]),
            item_id=item_id,
            item_kind=item_kind,
            payload={
                "item": {
                    "item_id": item_id,
                    "item_kind": item_kind,
                    "turn_id": str(run["id"]),
                }
            },
            occurred_at=occurred_at,
        )

    def _append_conversation_event_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        event_key: str,
        kind: TutorConversationEventKind | str,
        payload: Mapping[str, object],
        occurred_at: datetime,
        turn_id: str | None = None,
        item_id: str | None = None,
        item_kind: str | None = None,
    ) -> TutorConversationEvent:
        _safe_key(event_key, label="conversation event key")
        normalized_kind = TutorConversationEventKind(str(kind))
        safe_payload = validate_conversation_event_payload(normalized_kind, payload)
        _validate_conversation_event_identity(
            kind=normalized_kind,
            payload=safe_payload,
            turn_id=turn_id,
            item_id=item_id,
            item_kind=item_kind,
        )
        payload_hash = _sha256_json(safe_payload)
        conversation = self._lock_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            learner_only=False,
        )
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_conversation_events
            WHERE conversation_id = %s AND event_key = %s
            """,
            (conversation_id, event_key),
        ).fetchone()
        if existing is not None:
            if (
                str(existing.get("payload_hash") or "") != payload_hash
                or str(existing.get("kind") or "") != normalized_kind.value
                or _optional_string(existing.get("turn_id")) != turn_id
                or _optional_string(existing.get("item_id")) != item_id
                or _optional_string(existing.get("item_kind")) != item_kind
            ):
                raise TutorIdempotencyConflict("conversation event key conflicts with different public facts")
            return _conversation_event_from_row(
                existing,
                cursor=self._encode_conversation_event_cursor(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sequence=_as_int(existing.get("event_sequence"), 0),
                ),
            )
        sequence = max(1, _as_int(conversation.get("next_public_event_sequence"), 1))
        advanced = self._conn.execute(
            """
            UPDATE tutor_conversations
            SET next_public_event_sequence = next_public_event_sequence + 1
            WHERE id = %s AND user_id = %s AND next_public_event_sequence = %s
            RETURNING id
            """,
            (conversation_id, user_id, sequence),
        ).fetchone()
        if advanced is None:
            raise TutorIdempotencyConflict("conversation public event sequence changed before append")
        row = self._conn.execute(
            """
            INSERT INTO tutor_conversation_events (
              user_id, conversation_id, event_sequence, event_key, kind,
              turn_id, item_id, item_kind, projection_version,
              payload_json, payload_hash, occurred_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                user_id,
                conversation_id,
                sequence,
                event_key,
                normalized_kind.value,
                turn_id,
                item_id,
                item_kind,
                TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION,
                _json(safe_payload),
                payload_hash,
                occurred_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("conversation event insert failed")
        return _conversation_event_from_row(
            row,
            cursor=self._encode_conversation_event_cursor(
                user_id=user_id,
                conversation_id=conversation_id,
                sequence=sequence,
            ),
        )

    def _public_turn_from_row(self, row: Mapping[str, object]) -> dict[str, object]:
        turn = TutorPublicTurn(
            turn_id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            interaction_protocol_version=_protocol_version_from_row(row),
            status=public_turn_status(
                terminal_outcome=_optional_string(row.get("terminal_outcome")),
                cancelled=row.get("cancelled_at") is not None,
                superseded=row.get("superseded_by_run_id") is not None,
            ),
            input_revision=_as_int(row.get("input_revision"), 0),
            retry_of_turn_id=_optional_string(row.get("retry_of_turn_id")),
            retry_root_turn_id=_optional_string(row.get("retry_root_turn_id")),
            completion_reason=cast(
                Literal["awaiting_user", "awaiting_approval", "awaiting_authority"] | None,
                _optional_string(row.get("completion_reason")),
            ),
            created_at=(_as_datetime(row.get("created_at")) or datetime.now(UTC)).astimezone(UTC).isoformat(),
            updated_at=(_as_datetime(row.get("updated_at")) or datetime.now(UTC)).astimezone(UTC).isoformat(),
        )
        return dict(turn.model_dump(mode="json", exclude_none=True))

    def _encode_conversation_event_cursor(
        self,
        *,
        user_id: str,
        conversation_id: str,
        sequence: int,
    ) -> str:
        if sequence < 0:
            raise ValueError("conversation event cursor sequence must be non-negative")
        payload = {
            "v": TUTOR_CONVERSATION_STREAM_CURSOR_VERSION,
            "k": _CONVERSATION_EVENT_CURSOR_KIND,
            "u": user_id,
            "c": conversation_id,
            "s": sequence,
        }
        encoded = _base64url_encode(_json(payload).encode("utf-8"))
        signature = hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_base64url_encode(signature)}"

    def _decode_conversation_event_cursor(
        self,
        *,
        cursor: str,
        user_id: str,
        conversation_id: str,
    ) -> int:
        parts = cursor.split(".")
        if len(parts) != 2 or not all(parts):
            raise TutorCursorInvalid("conversation event cursor is invalid")
        encoded, supplied_signature = parts
        expected_signature = _base64url_encode(
            hmac.new(self._cursor_signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise TutorCursorInvalid("conversation event cursor is invalid")
        try:
            payload = _as_mapping(json.loads(_base64url_decode(encoded).decode("utf-8")))
            sequence = _as_int(payload.get("s"), -1)
            valid = (
                _as_int(payload.get("v"), -1) == TUTOR_CONVERSATION_STREAM_CURSOR_VERSION
                and str(payload.get("k") or "") == _CONVERSATION_EVENT_CURSOR_KIND
                and str(payload.get("u") or "") == user_id
                and str(payload.get("c") or "") == conversation_id
                and sequence >= 0
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            valid = False
            sequence = -1
        if not valid:
            raise TutorCursorInvalid("conversation event cursor is invalid")
        return sequence
