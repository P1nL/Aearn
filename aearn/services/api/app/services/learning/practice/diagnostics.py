"""Module-level independent diagnostic sessions and explicit skip confirmation."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from psycopg import Connection

from app.services.learning.contracts import (
    MasteryEvidence,
    MasteryEvidenceEffect,
    MasteryEvidenceKind,
    MasteryIndependence,
)
from app.services.learning.practice.contracts import (
    ExerciseAttemptResult,
    ExerciseAttemptType,
    ModuleDiagnosticItem,
    ModuleDiagnosticVersion,
    canonical_hash,
    canonical_submission_hash,
)
from app.services.learning.practice.fixtures import fixture_for_language
from app.services.learning.practice.policies import (
    DEFAULT_DIAGNOSTIC_COOLDOWN_SECONDS,
    DEFAULT_DIAGNOSTIC_THRESHOLD,
    DIAGNOSTIC_POLICY_VERSION,
    diagnostic_decision,
)
from app.services.learning.practice.repository import (
    PostgresExerciseGateRepository,
    PracticeIdempotencyConflict,
    PracticeNotFound,
    PracticeNotReady,
    PracticeRepositoryError,
    PracticeVersionConflict,
    _datetime_or_none,
    _float,
    _int,
    _json,
    _string_list,
)
from app.services.learning.track_repository import PostgresLearningTrackRepository


class PostgresModuleDiagnosticRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._practice = PostgresExerciseGateRepository(conn)
        self._tracks = PostgresLearningTrackRepository(conn)

    def create_session(
        self,
        *,
        user_id: str,
        track_id: str,
        module_key: str,
        expected_track_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        track = self._conn.execute(
            """
            SELECT tracks.language_id, tracks.version, tracks.current_knowledge_key, active.revision_id
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            WHERE tracks.id = %s AND tracks.user_id = %s FOR UPDATE OF tracks
            """,
            (track_id, user_id),
        ).fetchone()
        if track is None:
            raise PracticeNotFound("LearningTrack was not found")
        if _int(track["version"]) != expected_track_version:
            raise PracticeVersionConflict("LearningTrack version changed")
        module = self._conn.execute(
            """
            SELECT * FROM tutor_track_plan_modules
            WHERE revision_id = %s AND track_id = %s AND user_id = %s AND module_key = %s
            """,
            (track["revision_id"], track_id, user_id, module_key),
        ).fetchone()
        if module is None:
            raise PracticeNotFound("module was not found")
        if not bool(module["is_skippable"]):
            raise PracticeNotReady("module is not eligible for diagnostic skip")
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_module_diagnostic_sessions
            WHERE user_id = %s AND track_id = %s AND module_key = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (user_id, track_id, module_key, idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise PracticeIdempotencyConflict("diagnostic idempotency key conflicts with stored request")
            result = self.read_session(user_id=user_id, track_id=track_id, session_id=str(existing["id"]))
            result["idempotent_replayed"] = True
            return result
        cooldown = self._conn.execute(
            """
            SELECT cooldown_until FROM tutor_module_diagnostic_sessions
            WHERE user_id = %s AND track_id = %s AND module_key = %s
              AND cooldown_until IS NOT NULL
            ORDER BY cooldown_until DESC LIMIT 1
            """,
            (user_id, track_id, module_key),
        ).fetchone()
        if cooldown is not None:
            until = _datetime_or_none(cooldown.get("cooldown_until"))
            if until is not None and until > now:
                raise PracticeNotReady("module diagnostic cooldown is active")
        nodes = self._conn.execute(
            """
            SELECT nodes.knowledge_key, nodes.required_capabilities_json, nodes.order_index,
                   nodes.is_core, progress.status AS progress_status
            FROM tutor_track_plan_nodes AS nodes
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id, progress.knowledge_key) =
                 (nodes.track_id, nodes.user_id, nodes.knowledge_key)
            WHERE nodes.module_id = %s AND nodes.revision_id = %s
              AND nodes.track_id = %s AND nodes.user_id = %s
            ORDER BY nodes.order_index
            """,
            (module["id"], track["revision_id"], track_id, user_id),
        ).fetchall()
        if (
            not nodes
            or str(track.get("current_knowledge_key") or "") != str(nodes[0]["knowledge_key"])
            or any(
                str(node["progress_status"]) in {"completed", "review_due", "diagnostic_skipped"}
                for node in nodes
            )
        ):
            raise PracticeNotReady("module diagnostic is only available at the module boundary")
        core: list[tuple[str, str]] = []
        seen: set[str] = set()
        for node in nodes:
            if not bool(node["is_core"]):
                continue
            capabilities = _string_list(node.get("required_capabilities_json")) or [str(node["knowledge_key"])]
            for capability in capabilities:
                if capability not in seen:
                    seen.add(capability)
                    core.append((capability, str(node["knowledge_key"])))
        if not core:
            raise PracticeNotReady("module has no core capabilities")
        fixture = fixture_for_language(str(track["language_id"]))
        if fixture is None:
            raise PracticeNotReady("module language has no diagnostic fixture")
        exercise_version_id = self._practice.ensure_curated_fixture(fixture, now=now)
        version_label = f"v1-{str(track['revision_id']).replace('-', '')[:8]}"
        items = tuple(
            ModuleDiagnosticItem(
                item_key=f"{module_key}.item.{index + 1}",
                capability_key=capability,
                knowledge_key=knowledge_key,
                exercise_key=fixture.exercise.exercise_key,
                exercise_version=fixture.exercise.version,
                threshold=DEFAULT_DIAGNOSTIC_THRESHOLD,
            )
            for index, (capability, knowledge_key) in enumerate(core)
        )
        diagnostic = ModuleDiagnosticVersion(
            language_id=str(track["language_id"]),
            module_key=module_key,
            version=version_label,
            policy_version=DIAGNOSTIC_POLICY_VERSION,
            core_capabilities=tuple(capability for capability, _ in core),
            pass_threshold=DEFAULT_DIAGNOSTIC_THRESHOLD,
            require_all_core=True,
            independent_only=True,
            cooldown_seconds=DEFAULT_DIAGNOSTIC_COOLDOWN_SECONDS,
            items=items,
        )
        version_row = self._conn.execute(
            """
            INSERT INTO tutor_module_diagnostic_versions (
              language_id, module_key, version, policy_version, core_capabilities_json,
              pass_threshold, require_all_core, independent_only, cooldown_seconds,
              content_hash, published_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (language_id, module_key, version) DO NOTHING RETURNING id
            """,
            (
                diagnostic.language_id,
                diagnostic.module_key,
                diagnostic.version,
                diagnostic.policy_version,
                _json(list(diagnostic.core_capabilities)),
                diagnostic.pass_threshold,
                diagnostic.require_all_core,
                diagnostic.independent_only,
                diagnostic.cooldown_seconds,
                diagnostic.content_hash,
                now,
            ),
        ).fetchone()
        if version_row is None:
            version_row = self._conn.execute(
                """
                SELECT id, content_hash FROM tutor_module_diagnostic_versions
                WHERE language_id = %s AND module_key = %s AND version = %s
                """,
                (diagnostic.language_id, diagnostic.module_key, diagnostic.version),
            ).fetchone()
            if version_row is None or str(version_row["content_hash"]) != diagnostic.content_hash:
                raise PracticeIdempotencyConflict("diagnostic version conflicts with stored content")
        session_id = str(uuid4())
        self._conn.execute(
            """
            INSERT INTO tutor_module_diagnostic_sessions (
              id, user_id, track_id, module_key, diagnostic_version_id,
              source_plan_revision_id, expected_track_version, state,
              idempotency_key, request_hash, started_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, %s)
            """,
            (
                session_id,
                user_id,
                track_id,
                module_key,
                version_row["id"],
                track["revision_id"],
                expected_track_version,
                idempotency_key,
                request_hash,
                now,
            ),
        )
        for index, item in enumerate(items):
            item_hash = canonical_hash(
                {
                    "session_id": session_id,
                    "item_key": item.item_key,
                    "capability_key": item.capability_key,
                    "knowledge_key": item.knowledge_key,
                    "exercise_version_id": exercise_version_id,
                    "threshold": item.threshold,
                }
            )
            self._conn.execute(
                """
                INSERT INTO tutor_module_diagnostic_items (
                  session_id, user_id, track_id, source_plan_revision_id,
                  item_key, order_index, capability_key, knowledge_key,
                  exercise_version_id, threshold, item_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    user_id,
                    track_id,
                    track["revision_id"],
                    item.item_key,
                    index,
                    item.capability_key,
                    item.knowledge_key,
                    exercise_version_id,
                    item.threshold,
                    item_hash,
                ),
            )
        result = self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)
        result["idempotent_replayed"] = False
        return result

    def read_session(self, *, user_id: str, track_id: str, session_id: str) -> dict[str, object]:
        session = self._conn.execute(
            """
            SELECT sessions.*, versions.language_id, versions.version AS diagnostic_version,
                   versions.policy_version, versions.core_capabilities_json,
                   versions.pass_threshold, versions.require_all_core,
                   versions.independent_only, versions.cooldown_seconds
            FROM tutor_module_diagnostic_sessions AS sessions
            JOIN tutor_module_diagnostic_versions AS versions ON versions.id = sessions.diagnostic_version_id
            WHERE sessions.id = %s AND sessions.user_id = %s AND sessions.track_id = %s
            """,
            (session_id, user_id, track_id),
        ).fetchone()
        if session is None:
            raise PracticeNotFound("module diagnostic session was not found")
        items = self._conn.execute(
            """
            SELECT items.*, versions.exercise_key, versions.exercise_type,
                   versions.version AS exercise_version, versions.title AS exercise_title,
                   versions.learner_prompt_json, versions.starter_artifact_json,
                   attempts.id AS attempt_id, attempts.submission_hash, attempts.independence,
                   results.outcome, results.score, results.safe_feedback_json, results.terminal_at,
                   links.execution_job_id, jobs.state AS execution_job_state
            FROM tutor_module_diagnostic_items AS items
            JOIN tutor_exercise_versions AS versions ON versions.id = items.exercise_version_id
            LEFT JOIN LATERAL (
              SELECT attempt.* FROM tutor_exercise_attempts AS attempt
              WHERE attempt.diagnostic_session_id = items.session_id
                AND attempt.diagnostic_item_id = items.id
              ORDER BY attempt.accepted_at DESC, attempt.id DESC LIMIT 1
            ) AS attempts ON true
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            LEFT JOIN tutor_exercise_execution_links AS links ON links.attempt_id = attempts.id
            LEFT JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE items.session_id = %s AND items.user_id = %s AND items.track_id = %s
            ORDER BY items.order_index
            """,
            (session_id, user_id, track_id),
        ).fetchall()
        result = dict(session)
        result["items"] = [dict(item) for item in items]
        return result

    def create_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        module_key: str,
        session_id: str,
        item_id: str,
        submission: str,
        expected_track_version: int,
        expected_session_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        session = self._conn.execute(
            """
            SELECT sessions.*, tracks.version AS track_version
            FROM tutor_module_diagnostic_sessions AS sessions
            JOIN tutor_learning_tracks AS tracks
              ON (tracks.id, tracks.user_id) = (sessions.track_id, sessions.user_id)
            WHERE sessions.id = %s AND sessions.user_id = %s AND sessions.track_id = %s
              AND sessions.module_key = %s
            FOR UPDATE OF sessions, tracks
            """,
            (session_id, user_id, track_id, module_key),
        ).fetchone()
        if session is None:
            raise PracticeNotFound("module diagnostic session was not found")
        if str(session["state"]) != "active":
            raise PracticeNotReady("module diagnostic session is not active")
        if _int(session["version"]) != expected_session_version or _int(session["track_version"]) != expected_track_version:
            raise PracticeVersionConflict("module diagnostic version changed")
        item = self._conn.execute(
            """
            SELECT items.*, versions.exercise_type
            FROM tutor_module_diagnostic_items AS items
            JOIN tutor_exercise_versions AS versions ON versions.id = items.exercise_version_id
            WHERE items.id = %s AND items.session_id = %s AND items.user_id = %s AND items.track_id = %s
            """,
            (item_id, session_id, user_id, track_id),
        ).fetchone()
        if item is None:
            raise PracticeNotFound("module diagnostic item was not found")
        normalized = str(submission).replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip() or len(normalized) > 48_000:
            raise PracticeRepositoryError("submission must contain 1..48000 characters")
        existing = self._conn.execute(
            """
            SELECT attempts.*, submissions.id AS submission_id
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_submissions AS submissions ON submissions.attempt_id = attempts.id
            WHERE attempts.user_id = %s AND attempts.attempt_type = 'diagnostic_submit'
              AND attempts.idempotency_key = %s FOR UPDATE OF attempts
            """,
            (user_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise PracticeIdempotencyConflict("diagnostic Attempt idempotency conflict")
            replay = dict(existing)
            replay["idempotent_replayed"] = True
            return replay
        attempt_id = str(uuid4())
        submission_id = str(uuid4())
        submission_hash = canonical_submission_hash(normalized)
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempts (
              id, attempt_type, user_id, track_id, plan_revision_id,
              expected_track_version, expected_progress_version, knowledge_key,
              diagnostic_session_id, diagnostic_item_id, exercise_version_id,
              submission_hash, hint_state_hash, independence,
              idempotency_key, request_hash, accepted_at
            ) VALUES (%s, 'diagnostic_submit', %s, %s, %s, %s, NULL, %s,
                      %s, %s, %s, %s, %s, 'independent', %s, %s, %s)
            """,
            (
                attempt_id,
                user_id,
                track_id,
                session["source_plan_revision_id"],
                expected_track_version,
                item["knowledge_key"],
                session_id,
                item_id,
                item["exercise_version_id"],
                submission_hash,
                canonical_hash({"hint_count": 0, "diagnostic": True}),
                idempotency_key,
                request_hash,
                now,
            ),
        )
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempt_submissions (
              id, attempt_id, user_id, exercise_version_id,
              submission_kind, content_text, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                submission_id,
                attempt_id,
                user_id,
                item["exercise_version_id"],
                "sql" if str(item["exercise_type"]) == "sql_query" else "code",
                normalized,
                submission_hash,
            ),
        )
        return {
            "id": attempt_id,
            "attempt_type": ExerciseAttemptType.DIAGNOSTIC_SUBMIT.value,
            "user_id": user_id,
            "track_id": track_id,
            "knowledge_key": str(item["knowledge_key"]),
            "exercise_version_id": str(item["exercise_version_id"]),
            "submission_id": submission_id,
            "submission_hash": submission_hash,
            "independence": "independent",
            "accepted_at": now,
            "diagnostic_session_id": session_id,
            "diagnostic_item_id": item_id,
            "idempotent_replayed": False,
        }

    def finalize_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        attempt_id: str,
        result: ExerciseAttemptResult,
        now: datetime,
    ) -> dict[str, object]:
        attempt = self._practice.read_attempt(user_id=user_id, attempt_id=attempt_id, for_update=True)
        if str(attempt["attempt_type"]) != ExerciseAttemptType.DIAGNOSTIC_SUBMIT.value:
            raise PracticeRepositoryError("Attempt is not a module diagnostic submission")
        if str(attempt["track_id"]) != track_id:
            raise PracticeNotFound("module diagnostic Attempt was not found")
        if attempt.get("result_hash") is not None:
            if str(attempt["result_hash"]) != result.result_hash:
                raise PracticeIdempotencyConflict("diagnostic result conflicts with stored result")
            replay = self.read_session(
                user_id=user_id,
                track_id=track_id,
                session_id=str(attempt["diagnostic_session_id"]),
            )
            replay["idempotent_replayed"] = True
            return replay
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempt_results (
              attempt_id, user_id, outcome, score, safe_feedback_json,
              capability_scores_json, execution_receipt_hash, policy_version,
              result_hash, terminal_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                attempt_id,
                user_id,
                result.outcome.value,
                result.score,
                _json(result.safe_feedback),
                _json(result.capability_scores),
                result.execution_receipt_hash,
                result.policy_version,
                result.result_hash,
                result.terminal_at,
            ),
        )
        session_id = str(attempt["diagnostic_session_id"])
        return self._aggregate_session(user_id=user_id, track_id=track_id, session_id=session_id, now=now)

    def _aggregate_session(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        now: datetime,
    ) -> dict[str, object]:
        session = self._conn.execute(
            """
            SELECT sessions.*, versions.language_id, versions.version AS diagnostic_version,
                   versions.policy_version, versions.core_capabilities_json,
                   versions.pass_threshold, versions.require_all_core,
                   versions.independent_only, versions.cooldown_seconds
            FROM tutor_module_diagnostic_sessions AS sessions
            JOIN tutor_module_diagnostic_versions AS versions ON versions.id = sessions.diagnostic_version_id
            WHERE sessions.id = %s AND sessions.user_id = %s AND sessions.track_id = %s
            FOR UPDATE OF sessions
            """,
            (session_id, user_id, track_id),
        ).fetchone()
        if session is None:
            raise PracticeNotFound("module diagnostic session was not found")
        if str(session["state"]) != "active":
            return self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)
        rows = self._conn.execute(
            """
            SELECT items.*, attempts.id AS attempt_id, attempts.independence,
                   results.outcome, results.score, results.safe_feedback_json,
                   results.capability_scores_json, results.policy_version,
                   results.result_hash, results.terminal_at
            FROM tutor_module_diagnostic_items AS items
            LEFT JOIN LATERAL (
              SELECT attempt.* FROM tutor_exercise_attempts AS attempt
              JOIN tutor_exercise_attempt_results AS result ON result.attempt_id = attempt.id
              WHERE attempt.diagnostic_session_id = items.session_id
                AND attempt.diagnostic_item_id = items.id
              ORDER BY attempt.accepted_at DESC, attempt.id DESC LIMIT 1
            ) AS attempts ON true
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            WHERE items.session_id = %s AND items.user_id = %s AND items.track_id = %s
            ORDER BY items.order_index
            """,
            (session_id, user_id, track_id),
        ).fetchall()
        if not rows or any(row.get("attempt_id") is None or row.get("outcome") is None for row in rows):
            return self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)
        items = tuple(
            ModuleDiagnosticItem(
                item_key=str(row["item_key"]),
                capability_key=str(row["capability_key"]),
                knowledge_key=str(row["knowledge_key"]),
                exercise_key="diagnostic.bound",
                exercise_version="v1",
                threshold=_float(row["threshold"]),
            )
            for row in rows
        )
        version = ModuleDiagnosticVersion(
            language_id=str(session["language_id"]),
            module_key=str(session["module_key"]),
            version=str(session["diagnostic_version"]),
            policy_version=str(session["policy_version"]),
            core_capabilities=tuple(_string_list(session.get("core_capabilities_json"))),
            pass_threshold=_float(session["pass_threshold"]),
            require_all_core=bool(session["require_all_core"]),
            independent_only=bool(session["independent_only"]),
            cooldown_seconds=_int(session["cooldown_seconds"]),
            items=items,
        )
        results = tuple(
            _result_from_row(row, capability_key=str(row["capability_key"]))
            for row in rows
        )
        independence = tuple(MasteryIndependence(str(row["independence"])) for row in rows)
        decision = diagnostic_decision(version=version, results=results, independence=independence)
        effect = (
            MasteryEvidenceEffect.REINFORCING
            if decision.passed
            else MasteryEvidenceEffect.OBSERVATIONAL_NON_DEGRADING
        )
        for row, item, item_result in zip(rows, items, results, strict=True):
            evidence = MasteryEvidence(
                evidence_id=str(uuid4()),
                knowledge_key=item.knowledge_key,
                evidence_kind=MasteryEvidenceKind.MODULE_DIAGNOSTIC,
                source_receipt_id=str(row["attempt_id"]),
                source_receipt_hash=str(row["result_hash"]),
                independence=MasteryIndependence(str(row["independence"])),
                score=item_result.score,
                hint_count=0,
                attempt_count=1,
                summary={
                    "strengths": [item.capability_key] if item_result.score >= item.threshold else [],
                    "weaknesses": [item.capability_key] if item_result.score < item.threshold else [],
                },
                created_at=now,
                evidence_effect=effect,
            )
            self._tracks.append_mastery_evidence(
                user_id=user_id,
                track_id=track_id,
                evidence=evidence,
            )
        if decision.passed:
            active_revision_id, plan = self._tracks.read_active_plan(user_id=user_id, track_id=track_id)
            if active_revision_id != str(session["source_plan_revision_id"]):
                raise PracticeVersionConflict("active plan changed during module diagnostic")
            track = self._conn.execute(
                "SELECT version FROM tutor_learning_tracks WHERE id = %s AND user_id = %s FOR UPDATE",
                (track_id, user_id),
            ).fetchone()
            if track is None:
                raise PracticeNotFound("LearningTrack was not found")
            current_version = _int(track["version"])
            proposed_plan = replace(
                plan,
                change_reason=f"模块 {session['module_key']} 独立诊断全部通过，等待确认跳过。",
            )
            proposal_hash = canonical_hash(
                {
                    "session_id": session_id,
                    "module_key": str(session["module_key"]),
                    "source_revision_id": active_revision_id,
                    "capability_scores": dict(decision.capability_scores),
                }
            )
            proposed_revision_id, _impact, new_track_version = self._tracks.propose_revision(
                user_id=user_id,
                track_id=track_id,
                expected_track_version=current_version,
                plan=proposed_plan,
                idempotency_key=f"diagnostic-proposal:{session_id}",
                request_hash=proposal_hash,
            )
            module_nodes = self._conn.execute(
                """
                SELECT knowledge_key FROM tutor_track_plan_nodes
                WHERE revision_id = %s AND track_id = %s AND user_id = %s
                  AND module_id = (
                    SELECT id FROM tutor_track_plan_modules
                    WHERE revision_id = %s AND track_id = %s AND user_id = %s AND module_key = %s
                  ) ORDER BY order_index
                """,
                (
                    active_revision_id,
                    track_id,
                    user_id,
                    active_revision_id,
                    track_id,
                    user_id,
                    session["module_key"],
                ),
            ).fetchall()
            impact = {
                "kind": "diagnostic_skipped_module",
                "module_key": str(session["module_key"]),
                "diagnostic_session_id": session_id,
                "policy_version": str(session["policy_version"]),
                "affected_knowledge_keys": [str(row["knowledge_key"]) for row in module_nodes],
                "capability_scores": dict(decision.capability_scores),
                "source_plan_revision_id": active_revision_id,
                "proposed_plan_revision_id": proposed_revision_id,
                "expected_track_version": new_track_version,
            }
            self._conn.execute(
                """
                UPDATE tutor_module_diagnostic_sessions
                SET state = 'passed_pending_confirmation', proposed_plan_revision_id = %s,
                    impact_json = %s::jsonb, weak_capabilities_json = '[]'::jsonb,
                    terminal_at = %s, version = version + 1
                WHERE id = %s
                """,
                (proposed_revision_id, _json(impact), now, session_id),
            )
        else:
            self._conn.execute(
                """
                UPDATE tutor_module_diagnostic_sessions
                SET state = 'failed', weak_capabilities_json = %s::jsonb,
                    terminal_at = %s, cooldown_until = %s, version = version + 1
                WHERE id = %s
                """,
                (
                    _json(list(decision.weak_capabilities)),
                    now,
                    now + timedelta(seconds=_int(session["cooldown_seconds"])),
                    session_id,
                ),
            )
        result_state = self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)
        result_state["idempotent_replayed"] = False
        return result_state

    def confirm_skip(
        self,
        *,
        user_id: str,
        track_id: str,
        module_key: str,
        session_id: str,
        expected_session_version: int,
        expected_track_version: int,
        now: datetime,
    ) -> dict[str, object]:
        session = self._conn.execute(
            """
            SELECT * FROM tutor_module_diagnostic_sessions
            WHERE id = %s AND user_id = %s AND track_id = %s AND module_key = %s FOR UPDATE
            """,
            (session_id, user_id, track_id, module_key),
        ).fetchone()
        if session is None:
            raise PracticeNotFound("module diagnostic session was not found")
        if str(session["state"]) == "confirmed":
            result = self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)
            result["idempotent_replayed"] = True
            return result
        if str(session["state"]) != "passed_pending_confirmation" or session.get("proposed_plan_revision_id") is None:
            raise PracticeNotReady("module skip confirmation is not available")
        if _int(session["version"]) != expected_session_version:
            raise PracticeVersionConflict("module diagnostic session changed")
        self._tracks.activate_revision(
            user_id=user_id,
            track_id=track_id,
            revision_id=str(session["proposed_plan_revision_id"]),
            expected_track_version=expected_track_version,
        )
        nodes = self._conn.execute(
            """
            SELECT nodes.knowledge_key
            FROM tutor_track_plan_modules AS modules
            JOIN tutor_track_plan_nodes AS nodes ON nodes.module_id = modules.id
            WHERE modules.revision_id = %s AND modules.track_id = %s
              AND modules.user_id = %s AND modules.module_key = %s
            ORDER BY nodes.order_index
            """,
            (session["proposed_plan_revision_id"], track_id, user_id, session["module_key"]),
        ).fetchall()
        if not nodes:
            raise PracticeVersionConflict("module nodes changed before skip confirmation")
        keys = [str(row["knowledge_key"]) for row in nodes]
        self._conn.execute(
            """
            UPDATE tutor_track_node_progress
            SET status = 'diagnostic_skipped', started_at = COALESCE(started_at, %s),
                completed_at = COALESCE(completed_at, %s), version = version + 1
            WHERE track_id = %s AND user_id = %s AND knowledge_key = ANY(%s)
            """,
            (now, now, track_id, user_id, keys),
        )
        self._practice._unlock_available_nodes(
            user_id=user_id,
            track_id=track_id,
            plan_revision_id=str(session["proposed_plan_revision_id"]),
        )
        self._practice._advance_track(
            user_id=user_id,
            track_id=track_id,
            completed_key=keys[-1],
            now=now,
        )
        self._conn.execute(
            """
            UPDATE tutor_module_diagnostic_sessions
            SET state = 'confirmed', confirmed_at = %s, version = version + 1
            WHERE id = %s
            """,
            (now, session_id),
        )
        result = self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)
        result["idempotent_replayed"] = False
        return result


def _result_from_row(row, *, capability_key: str) -> ExerciseAttemptResult:
    from app.services.learning.practice.contracts import ExerciseAttemptOutcome

    terminal_at = _datetime_or_none(row.get("terminal_at"))
    if terminal_at is None:
        raise PracticeRepositoryError("diagnostic result terminal time is missing")
    score = _float(row["score"])
    return ExerciseAttemptResult(
        outcome=ExerciseAttemptOutcome(str(row["outcome"])),
        score=score,
        safe_feedback=dict(row["safe_feedback_json"])
        if isinstance(row.get("safe_feedback_json"), dict)
        else {},
        capability_scores={capability_key: score},
        policy_version=str(row["policy_version"]),
        terminal_at=terminal_at,
    )
