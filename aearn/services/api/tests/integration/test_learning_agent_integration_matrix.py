from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from aearn_shared.execution import (
    SafeExecutionResultV1,
    SafeExecutionStatus,
    runtime_id_for_profile,
)
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.grounding.grounding_sources import get_grounding_source
from app.services.learning.contracts import (
    ExecutionComposition,
    ExecutionTier,
    LearningPlan,
    LearningPlanModule,
    LearningPlanNode,
)
from app.services.learning.execution_tiers import (
    ExecutionTierInputs,
    ExecutionTierResolver,
    StaticExecutorAvailability,
)
from app.services.learning.lesson_contracts import (
    AuthorityNoteBlock,
    CodeExampleBlock,
    ConceptBlock,
    ExerciseGateBlock,
    HeadingBlock,
    HintBlock,
    LearningObjectivesBlock,
    LessonDocumentDraft,
    LessonSourceSnapshot,
    NextStepsBlock,
    SummaryBlock,
    calculate_lesson_impact,
    canonical_source_set_hash,
)
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
)
from app.services.learning.practice.fixtures import CuratedExerciseFixture, fixture_for_language
from app.services.learning.practice.quality import require_exercise_quality
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.learning.practice.service import ExerciseGateService
from app.services.learning.reviews.service import ReviewService
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.runners.language_capabilities import (
    capabilities_for_public_course_language,
    get_language_capability,
    public_course_language_ids,
)
from app.services.tutor.execution import default_runtime_registry


CORE_CASES = (
    ("python", "python.variables", "python-tutorial", "value"),
    (
        "javascript",
        "javascript.dom.text_content",
        "mdn-javascript-guide",
        'document.querySelector("#answer").textContent = "3";',
    ),
    ("typescript", "typescript.functions", "typescript-handbook", "return a + b;"),
    (
        "sql",
        "sql.select.where",
        "postgresql-sql-docs",
        "SELECT name FROM users WHERE active = 1;",
    ),
)
PROTECTED_PUBLIC_KEYS = {
    "private_test_bundle",
    "private_test_bundle_json",
    "reference_answer",
    "reference_answer_json",
    "expected_output_json",
    "content_text",
    "provider_body",
    "provider_reasoning",
    "raw_reasoning",
    "command",
    "container_name",
    "host_path",
    "secret",
}


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is required for the learning-agent integration matrix.",
)


def _successful_local_runner(
    _exercise: object, _submission: str
) -> SafeExecutionResultV1:
    return SafeExecutionResultV1(
        status=SafeExecutionStatus.SUCCESS,
        stdout="fixture passed",
        passed_test_count=2,
        total_test_count=2,
        diagnostic_code="integration_fixture_success",
    )


def _plan(language_id: str, knowledge_key: str) -> LearningPlan:
    return LearningPlan(
        title=f"{language_id} integration track",
        target_level="beginner",
        generator_version="learning-agent-integration-v1",
        policy_version="learning-agent-integration-v1",
        change_reason="验证核心语言学习闭环。",
        modules=(
            LearningPlanModule(
                module_key="foundations",
                title="基础模块",
                description="单节点确定性集成矩阵。",
                order_index=0,
                is_core=True,
                is_skippable=False,
                nodes=(
                    LearningPlanNode(
                        knowledge_key=knowledge_key,
                        title=f"{language_id} 基础能力",
                        description="验证计划、课程、练习与复习证据。",
                        order_index=0,
                        is_core=True,
                        prerequisite_keys=(),
                        required_capabilities=(knowledge_key,),
                    ),
                ),
            ),
        ),
    )


def _snapshot(
    *, language_id: str, knowledge_key: str, source_id: str
) -> tuple[LessonSourceSnapshot, GroundingChunk]:
    source = get_grounding_source(source_id)
    assert source is not None
    suffix = uuid4().hex[:16]
    citation_id = f"cite_{suffix}"
    chunk_id = f"integration-{language_id}-{suffix}"
    fetched_at = datetime(2026, 8, 12, tzinfo=UTC)
    snapshot = LessonSourceSnapshot(
        citation_id=citation_id,
        source_id=source.source_id,
        display_name=source.display_name,
        provider=source.provider,
        trust_tier=source.trust_tier,
        source_type=source.content_type,
        source_version_label=source.source_version_label,
        source_version_kind=source.source_version_kind,
        canonical_url=source.seed_urls[0],
        section_path=(source.display_name, knowledge_key),
        grounding_chunk_id=chunk_id,
        document_content_hash="a" * 64,
        chunk_content_hash="b" * 64,
        fetched_at=fetched_at,
        snapshotted_at=fetched_at,
        evidence_excerpt=f"{source.display_name} 为 {knowledge_key} 提供可信教学依据。",
    )
    chunk = GroundingChunk(
        chunk_id=chunk_id,
        source_id=source.source_id,
        language_id=language_id,
        title=knowledge_key,
        section_path=snapshot.section_path,
        canonical_url=snapshot.canonical_url,
        source_type=snapshot.source_type,
        source_trust_tier=snapshot.trust_tier,
        fetched_at=fetched_at,
        content_hash=snapshot.chunk_content_hash,
        text=snapshot.evidence_excerpt,
        topic_tags=("integration",),
        source_version_label=snapshot.source_version_label,
        source_version_kind=snapshot.source_version_kind,
        document_content_hash=snapshot.document_content_hash,
    )
    return snapshot, chunk


def _insert_grounding_chunk(
    conn: psycopg.Connection[dict[str, object]], chunk: GroundingChunk
) -> None:
    conn.execute(
        """
        INSERT INTO grounding_chunks (
          chunk_id, source_id, language_id, title, section_path_json,
          canonical_url, source_type, source_trust_tier, fetched_at,
          source_version_label, source_version_kind, document_content_hash,
          content_hash, content, topic_tags_json, metadata_json
        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, '{}'::jsonb)
        """,
        (
            chunk.chunk_id,
            chunk.source_id,
            chunk.language_id,
            chunk.title,
            json.dumps(list(chunk.section_path), ensure_ascii=False),
            chunk.canonical_url,
            chunk.source_type,
            chunk.source_trust_tier,
            chunk.fetched_at,
            chunk.source_version_label,
            chunk.source_version_kind,
            chunk.document_content_hash,
            chunk.content_hash,
            chunk.text,
            json.dumps(list(chunk.topic_tags), ensure_ascii=False),
        ),
    )


def _document(
    *,
    language_id: str,
    knowledge_key: str,
    citation_id: str,
    personalized: bool,
) -> LessonDocumentDraft:
    title = f"{language_id} 集成课程" + ("（个性化）" if personalized else "")
    gate_key = f"{knowledge_key}.basic"
    return LessonDocumentDraft(
        title=title,
        language_id=language_id,
        knowledge_key=knowledge_key,
        content_standard_version="programming_language_lesson_v1",
        coverage_keys=(knowledge_key,),
        blocks=(
            HeadingBlock(
                block_id="heading",
                order_index=0,
                citation_ids=(),
                title=title,
                subtitle="确定性集成矩阵课程。",
            ),
            LearningObjectivesBlock(
                block_id="objectives",
                order_index=1,
                citation_ids=(),
                items=("完成课程 Gate 并生成可复习证据。",),
                coverage_keys=(knowledge_key,),
            ),
            ConceptBlock(
                block_id="concept",
                order_index=2,
                citation_ids=(citation_id,),
                title="核心概念",
                paragraphs=("课程正文只引用冻结的可信来源快照。",),
                coverage_keys=(knowledge_key,),
            ),
            AuthorityNoteBlock(
                block_id="authority",
                order_index=3,
                citation_ids=(citation_id,),
                title="权威依据",
                statement="该说明来自当前课程绑定的来源快照。",
            ),
            CodeExampleBlock(
                block_id="example",
                order_index=4,
                citation_ids=(citation_id,),
                title="静态示例",
                language_id=language_id,
                code="example",
                explanation=("示例本身不声称已运行。",),
            ),
            HintBlock(
                block_id="hint",
                order_index=5,
                citation_ids=(),
                title="提示",
                steps=("先完成最小正确答案。",),
            ),
            ExerciseGateBlock(
                block_id="gate",
                order_index=6,
                citation_ids=(),
                gate_key=gate_key,
                gate_kind="knowledge_check",
                assessment_contract_version="lesson_gate_v1",
                required_capabilities=(knowledge_key,),
                learner_prompt="提交一个满足当前能力点的答案。",
            ),
            SummaryBlock(
                block_id="summary",
                order_index=7,
                citation_ids=(citation_id,),
                points=("完成 Gate 后生成掌握度与复习日程。",),
                coverage_keys=(knowledge_key,),
            ),
            NextStepsBlock(
                block_id="next",
                order_index=8,
                citation_ids=(),
                items=("进入复习队列验证证据闭环。",),
            ),
        ),
    )


def _publish_lesson(
    conn: psycopg.Connection[dict[str, object]],
    *,
    user_id: str,
    track_id: str,
    language_id: str,
    knowledge_key: str,
    snapshot: LessonSourceSnapshot,
) -> tuple[PostgresLessonDocumentRepository, str]:
    repository = PostgresLessonDocumentRepository(conn)
    scope = repository.read_scope(
        user_id=user_id, track_id=track_id, knowledge_key=knowledge_key
    )
    run, replayed = repository.create_or_replay_authoring_run(
        scope=scope,
        run_kind="prepare",
        idempotency_key=f"integration-lesson-{uuid4()}",
        request_hash="c" * 64,
        profile_hash="d" * 64,
    )
    assert replayed is False
    claimed = repository.claim_authoring_run(
        run_id=run.run_id,
        owner="integration-test",
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )
    assert claimed is not None
    running = repository.mark_authoring_running(
        run_id=claimed.run_id,
        lease_generation=claimed.lease_generation,
    )
    source_hash = canonical_source_set_hash((snapshot,))
    repository.set_authoring_source_set(
        run_id=running.run_id,
        lease_generation=running.lease_generation,
        source_set_hash=source_hash,
    )
    standard = _document(
        language_id=language_id,
        knowledge_key=knowledge_key,
        citation_id=snapshot.citation_id,
        personalized=False,
    )
    personalized = _document(
        language_id=language_id,
        knowledge_key=knowledge_key,
        citation_id=snapshot.citation_id,
        personalized=True,
    )
    published = repository.publish_authoring_result(
        run=running,
        standard_document=standard,
        personalized_document=personalized,
        snapshots=(snapshot,),
        standard_quality={"passed": True, "fixture": "integration_matrix"},
        personalized_quality={"passed": True, "fixture": "integration_matrix"},
        standard_change_summary={},
        personalized_change_summary={"personalized": True},
        generator_version="learning-agent-integration-v1",
        policy_version="learning-agent-integration-v1",
        source_set_hash=source_hash,
        impact=calculate_lesson_impact(standard, personalized),
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )
    return repository, published.assignment_id


def _seed_inaccessible_registered_author_candidates(
    conn: psycopg.Connection[dict[str, object]],
    *,
    language_id: str,
    knowledge_key: str,
) -> None:
    repository = PostgresExerciseGateRepository(conn)
    for index in range(12):
        exercise = ExerciseVersion(
            language_id=language_id,
            exercise_key=f"{language_id}.integration.private.{uuid4().hex[:12]}",
            exercise_type=ExerciseType.STATIC_CODE_REASONING,
            version="v1",
            source_kind=ExerciseSourceKind.REGISTERED_AUTHOR,
            title=f"不可访问的注册作者候选 {index}",
            learner_prompt={"text": "该候选属于其他作用域，不得进入当前 ReviewSession。"},
            starter_artifact={"content": ""},
            required_capabilities=(knowledge_key,),
            runtime_profile_id=None,
            execution_required=False,
            public_feedback_policy_version="lesson_gate_feedback_v1",
        )
        rubric = ExercisePrivateRubric(
            rubric_version="v1",
            private_test_bundle=(
                {"case_type": "hidden", "input": {}, "expected": {"value": "private"}},
            ),
            reference_answer={"accepted_answers": ["private"]},
            score_policy={"kind": "exact_static", "threshold": 0.8},
        )
        require_exercise_quality(exercise, rubric)
        repository.ensure_curated_fixture(
            CuratedExerciseFixture(exercise=exercise, rubric=rubric),
            now=datetime.now(UTC) + timedelta(seconds=index),
        )


def _assert_safe_projection(*payloads: object) -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            normalized_keys = {str(key).casefold() for key in value}
            assert normalized_keys.isdisjoint(PROTECTED_PUBLIC_KEYS)
            for item in value.values():
                walk(item)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    walk(payloads)
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True).casefold()
    assert "hidden_secret" not in serialized
    assert "reference answer" not in serialized


@pytest.mark.parametrize(
    ("language_id", "knowledge_key", "source_id", "submission"), CORE_CASES
)
def test_core_language_plan_lesson_gate_persistence_and_review_evidence_matrix(
    language_id: str,
    knowledge_key: str,
    source_id: str,
    submission: str,
) -> None:
    bootstrap_database()
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        user = conn.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
            (f"Integration {language_id} {uuid4().hex[:8]}",),
        ).fetchone()
        assert user is not None
        user_id = str(user["id"])
        track_repository = PostgresLearningTrackRepository(conn)
        track_id = track_repository.create_track(
            user_id=user_id,
            language_id=language_id,
            goal_text=f"验证 {language_id} 学习闭环",
            target_level="beginner",
            plan=_plan(language_id, knowledge_key),
        )
        track = track_repository.read_track(user_id=user_id, track_id=track_id)
        roadmap = track_repository.read_roadmap(user_id=user_id, track_id=track_id)
        assert track["language_id"] == language_id
        assert roadmap["modules"][0]["nodes"][0]["knowledge_key"] == knowledge_key

        snapshot, chunk = _snapshot(
            language_id=language_id,
            knowledge_key=knowledge_key,
            source_id=source_id,
        )
        _insert_grounding_chunk(conn, chunk)
        lesson_repository, assignment_id = _publish_lesson(
            conn,
            user_id=user_id,
            track_id=track_id,
            language_id=language_id,
            knowledge_key=knowledge_key,
            snapshot=snapshot,
        )
        started = lesson_repository.start_assignment(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            assignment_id=assignment_id,
            expected_assignment_version=1,
            expected_progress_version=1,
            now=datetime(2026, 8, 12, 1, tzinfo=UTC),
        )
        assert started["progress_status"] == "in_progress"

        public_gate_service = ExerciseGateService(
            conn, composition=ExecutionComposition.PUBLIC
        )
        public_prepared = public_gate_service.prepare_gate(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=f"{knowledge_key}.basic",
            expected_track_version=1,
            expected_progress_version=int(started["progress_version"]),
            idempotency_key=f"public-prepare-{uuid4()}",
        )
        assert public_prepared["gate"]["execution_tier"] == "unavailable"
        assert public_prepared["gate"]["allowed_actions"] == []

        development_gate_service = ExerciseGateService(
            conn,
            composition=ExecutionComposition.DEVELOPMENT,
            local_runner_available=True,
            local_runner=_successful_local_runner,
        )
        development_gate = development_gate_service.read_gates(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
        )["items"][0]
        assert development_gate["execution_tier"] == "teaching_local"
        attempt = development_gate_service.attempt_gate(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=f"{knowledge_key}.basic",
            attempt_type="submit",
            submission=submission,
            expected_track_version=1,
            expected_progress_version=int(started["progress_version"]),
            expected_assignment_version=1,
            expected_gate_version=int(development_gate["gate_version"]),
            idempotency_key=f"gate-submit-{uuid4()}",
        )
        assert attempt["status"] == "terminal"
        assert attempt["result"]["outcome"] == "passed"
        assert attempt["route_changed"] is True
        assert attempt["execution_tier"] == "teaching_local"

        persistence = conn.execute(
            """
            SELECT progress.status,
                   submissions.content_text,
                   (SELECT count(*)::int FROM tutor_mastery_evidence
                    WHERE user_id = %s AND track_id = %s AND knowledge_key = %s
                      AND evidence_kind = 'gate') AS gate_evidence_count,
                   schedules.version AS schedule_version
            FROM tutor_track_node_progress AS progress
            JOIN tutor_exercise_attempt_submissions AS submissions ON submissions.attempt_id = %s
            JOIN tutor_review_schedule_states AS schedules
              ON (schedules.user_id, schedules.track_id, schedules.knowledge_key) =
                 (progress.user_id, progress.track_id, progress.knowledge_key)
            WHERE progress.user_id = %s AND progress.track_id = %s AND progress.knowledge_key = %s
            """,
            (
                user_id,
                track_id,
                knowledge_key,
                attempt["attempt_id"],
                user_id,
                track_id,
                knowledge_key,
            ),
        ).fetchone()
        assert persistence == {
            "status": "completed",
            "content_text": submission,
            "gate_evidence_count": 1,
            "schedule_version": 1,
        }
        schedule = conn.execute(
            """
            UPDATE tutor_review_schedule_states
            SET due_at = %s, version = version + 1
            WHERE user_id = %s AND track_id = %s AND knowledge_key = %s
            RETURNING version
            """,
            (
                datetime.now(UTC) - timedelta(minutes=1),
                user_id,
                track_id,
                knowledge_key,
            ),
        ).fetchone()
        assert schedule is not None
        current_track = track_repository.read_track(user_id=user_id, track_id=track_id)
        _seed_inaccessible_registered_author_candidates(
            conn,
            language_id=language_id,
            knowledge_key=knowledge_key,
        )

        review_service = ReviewService(
            conn,
            composition=ExecutionComposition.DEVELOPMENT,
            local_runner_available=True,
            local_runner=_successful_local_runner,
        )
        review = review_service.create_session(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            expected_track_version=int(current_track["version"]),
            expected_schedule_version=int(schedule["version"]),
            max_items=1,
            idempotency_key=f"review-create-{uuid4()}",
        )
        assert review["state"] == "active"
        selected_exercise_id = review["items"][0]["exercise"]["exercise_version_id"]
        selected_source = conn.execute(
            "SELECT source_kind FROM tutor_exercise_versions WHERE id = %s",
            (selected_exercise_id,),
        ).fetchone()
        assert selected_source == {"source_kind": "curated_fixture"}
        assert review["items"][0]["exercise"]["execution_tier"] == "teaching_local"
        warmed = review_service.warmup(
            user_id=user_id,
            track_id=track_id,
            session_id=str(review["session_id"]),
            response_kind="skipped",
            confidence=None,
            expected_session_version=int(review["version"]),
            idempotency_key=f"review-warmup-{uuid4()}",
        )
        review_attempt = review_service.attempt_item(
            user_id=user_id,
            track_id=track_id,
            session_id=str(review["session_id"]),
            item_id=str(review["items"][0]["item_id"]),
            submission=submission,
            review_submission=None,
            expected_session_version=int(warmed["version"]),
            expected_item_version=1,
            idempotency_key=f"review-attempt-{uuid4()}",
        )
        assert review_attempt["status"] == "terminal"
        assert review_attempt["result"]["outcome"] == "passed"
        finalized = review_service.finalize_session(
            user_id=user_id,
            track_id=track_id,
            session_id=str(review["session_id"]),
            expected_session_version=int(review_attempt["session_version"]),
            idempotency_key=f"review-finalize-{uuid4()}",
        )
        assert finalized["state"] == "finalized"
        assert finalized["finalization"] is not None
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*)::int FROM tutor_mastery_evidence
               WHERE user_id = %s AND track_id = %s AND knowledge_key = %s
                 AND evidence_kind = 'review') AS review_evidence_count,
              (SELECT count(*)::int FROM tutor_review_schedule_events
               WHERE user_id = %s AND track_id = %s AND knowledge_key = %s
                 AND source_kind = 'session_finalization') AS review_schedule_event_count
            """,
            (user_id, track_id, knowledge_key, user_id, track_id, knowledge_key),
        ).fetchone()
        assert counts == {"review_evidence_count": 1, "review_schedule_event_count": 1}
        _assert_safe_projection(
            public_prepared, attempt, review, warmed, review_attempt, finalized
        )
        conn.rollback()


def test_language_tiers_and_empty_image_locks_remain_truthful() -> None:
    registry = default_runtime_registry()
    resolver = ExecutionTierResolver()
    public_inputs = ExecutionTierInputs(
        composition=ExecutionComposition.PUBLIC,
        local_runner_available=True,
        runtime_registry=registry,
        executor_availability=StaticExecutorAvailability(
            frozenset(runtime.runtime_id for runtime in registry.runtimes)
        ),
    )

    assert public_course_language_ids() == (
        "javascript",
        "python",
        "typescript",
        "sql",
        "java",
        "go",
        "csharp",
        "html_css",
    )
    assert [
        item.language_id for item in capabilities_for_public_course_language("html_css")
    ] == ["html", "css"]

    expected = {
        "python": ("full", ExecutionTier.STATIC_ONLY, "python-stdout-v1"),
        "javascript": ("full", ExecutionTier.STATIC_ONLY, "browser-preview-v1"),
        "typescript": ("partial", ExecutionTier.STATIC_ONLY, "node-typescript-v1"),
        "sql": ("partial", ExecutionTier.STATIC_ONLY, "sqlite-query-v1"),
        "java": ("partial", ExecutionTier.STATIC_ONLY, "java-managed-v1"),
        "html": ("full", ExecutionTier.STATIC_ONLY, "browser-preview-v1"),
        "css": ("full", ExecutionTier.STATIC_ONLY, "browser-preview-v1"),
        "go": ("partial", ExecutionTier.STATIC_ONLY, "go-managed-v1"),
        "csharp": ("partial", ExecutionTier.STATIC_ONLY, "dotnet-managed-v1"),
        "rust": ("planned", ExecutionTier.UNAVAILABLE, None),
        "cpp": ("planned", ExecutionTier.STATIC_ONLY, None),
    }
    for language_id, (capability_state, expected_tier, runtime_id) in expected.items():
        capability = get_language_capability(language_id)
        assert capability is not None
        assert capability.capability_state == capability_state
        resolved_runtime_id = runtime_id_for_profile(
            runtime_tier=capability.execution,
            language=capability.language_id,
        )
        assert resolved_runtime_id == runtime_id
        if resolved_runtime_id is not None:
            assert registry.lock_for(resolved_runtime_id) is None
        projection = resolver.resolve(language=capability, inputs=public_inputs)
        assert projection.tier is expected_tier
        assert projection.tier is not ExecutionTier.CONTAINER_VERIFIED

    assert fixture_for_language("java") is None
    assert fixture_for_language("html") is None
    assert fixture_for_language("css") is None
    assert get_language_capability("rust").enabled_for_public_selection is False  # type: ignore[union-attr]
    assert get_language_capability("cpp").enabled_for_public_selection is False  # type: ignore[union-attr]
