from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import psycopg
import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorCheckpoint,
    TutorCheckpointReason,
    TutorCompactionTrigger,
    TutorContextSection,
    TutorRunResult,
    TutorRunStatus,
    TutorTerminalOutcome,
    build_compaction_request,
)
from app.services.tutor.curation import (
    CurationContextSummaryProposalV2,
    CurationGatewayResult,
    PrimaryCurationGateway,
    TutorMemoryCurator,
)
from app.services.tutor.interactive import PostgresTutorContextLoader
from app.services.tutor.learner_state import (
    TutorCurationMessageEvidence,
    TutorCurationSource,
    TutorLearnerStateRepository,
)
from app.services.tutor.persistence import PostgresTutorRepository, TutorCurationEnvelope
from app.services.tutor.proactive import (
    TutorProactivePreference,
    TutorProactiveScheduler,
    TutorProactiveSchedulerConfig,
)
from app.services.tutor.proactive_repository import PostgresTutorProactiveRepository


_NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)


class OneTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 1


class _SummaryGateway:
    def __init__(self) -> None:
        self.calls: list[TutorCurationSource] = []

    def propose(self, *, source: TutorCurationSource) -> CurationGatewayResult:
        self.calls.append(source)
        return CurationGatewayResult(
            state="proposal",
            code="curation_proposal_ready",
            proposal=CurationContextSummaryProposalV2(
                kind="context_summary",
                schema_version="tutor_context_summary_v2",
                current_goal="学习 Python 函数并完成一个小练习",
                confirmed_facts=("学习者已经准备好所需资料",),
                completed_steps=("已完成环境准备",),
                rejected_paths=("不再沿用旧的网站搭建路径",),
                open_questions=("下一步先练参数还是返回值",),
                learner_preferences=("偏好短小且可验证的示例",),
                confidence="high",
            ),
        )


class _PrimaryClient:
    def __init__(self, content: dict[str, object]) -> None:
        self.content = content
        self.calls: list[object] = []

    def complete_json(self, messages, *, temperature=None, max_tokens=None, timeout_seconds=None):
        del temperature, max_tokens, timeout_seconds
        self.calls.append(messages)
        return SimpleNamespace(content=self.content)


class _NeverGateway:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, *, source: TutorCurationSource) -> CurationGatewayResult:
        del source
        self.calls += 1
        raise AssertionError("invalid source evidence must not reach the Curator")


def _scheduler_config(*, inferred_memory_enabled: bool = False) -> TutorProactiveSchedulerConfig:
    return TutorProactiveSchedulerConfig(
        enabled=True,
        hard_paused=False,
        cutover_eligible=True,
        inferred_memory_enabled=inferred_memory_enabled,
        proactive_daily_budget=1,
        curation_daily_budget=3,
        proactive_concurrency_limit=1,
        curation_concurrency_limit=1,
        proactive_cooldown_seconds=1,
        curation_cooldown_seconds=1,
        proactive_circuit_failure_threshold=2,
        curation_circuit_failure_threshold=2,
        circuit_window_seconds=60,
        candidate_lease_seconds=60,
        curation_lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=5,
    )


def _enable_background_preference(repository: PostgresTutorProactiveRepository, fixture) -> None:
    repository.upsert_preference(
        preference=TutorProactivePreference(user_id=fixture.user_id, enabled=True),
        now=_NOW,
    )


def _prepare_structured_outbox(fixture):
    base_time = _NOW - timedelta(days=1)
    history: list[dict[str, object]] = []
    for index, (role, content) in enumerate(
        (
            ("learner", "旧目标标记 RETIRED_RAW_MARKER：我想做个网站"),
            ("tutor", "旧路径建议先准备图片资源"),
            ("learner", "我已经有了"),
            ("tutor", "那就继续旧的 HTML 路径"),
            ("learner", "你应该教我编程语言"),
            ("tutor", "我们切换到 Python 学习"),
        )
    ):
        row = fixture.connection.execute(
            """
            INSERT INTO tutor_messages (conversation_id, role, content, created_at)
            VALUES (%s, %s, %s, %s)
            RETURNING id::text AS id, role, content, created_at
            """,
            (fixture.conversation_id, role, content, base_time + timedelta(minutes=index)),
        ).fetchone()
        assert row is not None
        history.append(row)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="context-summary-current",
        content="请从 Python 函数开始，并且不要重复网站步骤",
        received_at=base_time + timedelta(minutes=6),
    )
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert snapshot is not None
    learner_state = TutorLearnerStateRepository(fixture.connection)
    context_input = PostgresTutorContextLoader(
        conn=fixture.connection,
        learner_state=learner_state,
        now_provider=lambda: _NOW,
    ).load_context(snapshot, input_revision=accepted.input_revision)
    assert context_input.compaction_plan is not None
    assert [candidate.message_id for candidate in context_input.compaction_plan.candidates] == [
        str(item["id"]) for item in history
    ]
    assert [source.source_id for source in context_input.recent_messages[-4:]] == [
        f"message:{item['id']}" for item in history[2:]
    ]
    selection = TutorContextBuilder(estimator=OneTokenEstimator()).build(
        context_input,
        token_budget=64,
    )
    assert selection.checkpoint_metadata.compaction_input is not None
    assert selection.checkpoint_metadata.compaction_input.retired_message_ids == tuple(
        str(item["id"]) for item in history[:2]
    )
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=snapshot.run_id,
        owner_id="context-summary-lifecycle",
        now=_NOW,
        duration_seconds=60,
    )
    assert lease is not None
    high_water_request = build_compaction_request(
        run_id=snapshot.run_id,
        conversation_id=snapshot.conversation_id,
        input_revision=accepted.input_revision,
        trigger=TutorCompactionTrigger.CONTEXT_HIGH_WATER,
        metadata=selection.checkpoint_metadata,
    )
    fixture.repository.persist_context_high_water(
        user_id=fixture.user_id,
        lease=lease,
        request=high_water_request,
        envelope=TutorCurationEnvelope(
            request=high_water_request,
            retention_until=_NOW + timedelta(days=30),
            stale_after=_NOW + timedelta(days=7),
        ),
        created_at=_NOW,
    )
    terminal_request = build_compaction_request(
        run_id=snapshot.run_id,
        conversation_id=snapshot.conversation_id,
        input_revision=accepted.input_revision,
        trigger=TutorCompactionTrigger.TERMINAL,
        metadata=selection.checkpoint_metadata,
    )
    checkpoint = TutorCheckpoint(
        run_id=snapshot.run_id,
        input_revision=accepted.input_revision,
        reason=TutorCheckpointReason.TERMINAL,
        status=TutorRunStatus.COMPLETED,
        metadata=selection.checkpoint_metadata,
        created_at=_NOW,
    )
    result = TutorRunResult(
        run_id=snapshot.run_id,
        status=TutorRunStatus.COMPLETED,
        input_revision=accepted.input_revision,
        iteration_count=1,
        model_call_count=1,
        capability_call_count=0,
        effect_count=0,
        terminal_outcome=TutorTerminalOutcome.COMPLETED,
        diagnostic_code="completed",
    )
    fixture.repository.complete_run(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=checkpoint,
        result=result,
        envelope=TutorCurationEnvelope(
            request=terminal_request,
            retention_until=_NOW + timedelta(days=30),
            stale_after=_NOW + timedelta(days=7),
        ),
    )
    outbox = fixture.connection.execute(
        """
        SELECT id::text AS id, projection_kind, idempotency_key,
               source_ids_json, source_hashes_json, summary_source_hash
        FROM tutor_memory_curation_outbox
        WHERE run_id = %s
        """,
        (snapshot.run_id,),
    ).fetchall()
    assert len(outbox) == 1
    assert outbox[0]["projection_kind"] == "context_summary"
    assert outbox[0]["idempotency_key"] == high_water_request.curation_idempotency_key
    assert terminal_request.curation_idempotency_key == high_water_request.curation_idempotency_key
    assert terminal_request.idempotency_key != high_water_request.idempotency_key
    return context_input, str(outbox[0]["id"]), history


def test_structured_compaction_deduplicates_lifecycle_triggers_and_keeps_raw_content_out_of_envelopes(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    context_input, outbox_id, _history = _prepare_structured_outbox(fixture)
    assert context_input.compaction_plan is not None
    durable = fixture.connection.execute(
        """
        SELECT
          (SELECT string_agg(trace_json::text, ' ') FROM tutor_run_traces WHERE run_id = %s) AS traces,
          (SELECT envelope_json::text FROM tutor_memory_curation_outbox WHERE id = %s) AS outbox
        """,
        (fixture.run.run_id, outbox_id),
    ).fetchone()
    assert durable is not None
    serialized = f"{durable['traces']} {durable['outbox']}"
    assert "RETIRED_RAW_MARKER" not in serialized
    assert "旧路径建议" not in serialized
    assert "retired_message_ids" in serialized
    assert "summary_source_hash" in serialized


def test_structured_summary_runs_when_inferred_memory_is_disabled_and_round_trips_into_context(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    _context_input, outbox_id, history = _prepare_structured_outbox(fixture)
    scheduler_repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_background_preference(scheduler_repository, fixture)
    learner_state = TutorLearnerStateRepository(fixture.connection)
    gateway = _SummaryGateway()
    curator = TutorMemoryCurator(
        repository=PostgresTutorRepository(fixture.connection),
        learner_state=learner_state,
        gateway=gateway,
    )
    scheduler = TutorProactiveScheduler(
        store=scheduler_repository,
        config=_scheduler_config(inferred_memory_enabled=False),
        curation_processor=curator,
    )

    seeded = scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    drained = scheduler.drain_curation(
        worker_id="context-summary-worker",
        now=_NOW,
        user_id=fixture.user_id,
    )

    assert len(seeded) == 1
    assert seeded[0].projection_kind == "context_summary"
    assert drained.claimed == 1
    job_state = fixture.connection.execute(
        "SELECT state, no_action_code, last_error_code FROM tutor_curation_jobs WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone()
    assert drained.completed == 1, job_state
    assert len(gateway.calls) == 1
    assert gateway.calls[0].projection_kind == "context_summary"
    assert [item.content for item in gateway.calls[0].retired_messages] == [
        "旧目标标记 RETIRED_RAW_MARKER：我想做个网站",
        "旧路径建议先准备图片资源",
    ]
    summary = fixture.connection.execute(
        """
        SELECT id::text AS id, conversation_id::text AS conversation_id, summary,
               summary_schema_version, summary_policy_version, summary_json,
               covered_through_message_id::text AS covered_through_message_id,
               source_hash, prior_summary_id::text AS prior_summary_id
        FROM tutor_context_summaries
        WHERE outbox_id = %s
        """,
        (outbox_id,),
    ).fetchone()
    assert summary is not None
    assert summary["conversation_id"] == fixture.conversation_id
    assert summary["summary_schema_version"] == "tutor_context_summary_v2"
    assert summary["summary_policy_version"] == "tutor_context_summary_policy_v2"
    assert summary["summary_json"]["current_goal"] == "学习 Python 函数并完成一个小练习"
    assert summary["summary_json"]["completed_steps"] == ["已完成环境准备"]
    assert summary["summary_json"]["rejected_paths"] == ["不再沿用旧的网站搭建路径"]
    assert summary["prior_summary_id"] is None

    new_run = fixture.repository.create_run(
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        catalog_digest=fixture.catalog.digest,
        policy=fixture.run.policy,
        origin="interactive",
    )
    next_input = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=new_run.run_id,
        idempotency_key="context-summary-next-input",
        content="我已经有了，现在继续讲函数参数",
        received_at=_NOW + timedelta(hours=1),
    )
    next_snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=new_run.run_id)
    assert next_snapshot is not None
    loaded = PostgresTutorContextLoader(
        conn=fixture.connection,
        learner_state=learner_state,
        now_provider=lambda: _NOW + timedelta(hours=2),
    ).load_context(next_snapshot, input_revision=next_input.input_revision)
    assert loaded.current_input is not None
    assert loaded.current_input.content == "我已经有了，现在继续讲函数参数"
    assert len(loaded.working_summary) == 1
    assert loaded.working_summary[0].source_id == f"summary:{summary['id']}"
    assert loaded.working_summary[0].content["current_goal"] == "学习 Python 函数并完成一个小练习"
    assert loaded.compaction_plan is not None
    assert loaded.compaction_plan.prior_summary_id == summary["id"]
    candidate_ids = [candidate.message_id for candidate in loaded.compaction_plan.candidates]
    assert candidate_ids[0] == str(history[2]["id"])
    assert str(history[0]["id"]) not in candidate_ids
    assert str(history[1]["id"]) not in candidate_ids
    other_user = fixture.connection.execute(
        "INSERT INTO users (display_name) VALUES ('Summary Scope User') RETURNING id::text AS id"
    ).fetchone()
    assert other_user is not None
    assert learner_state.latest_context_summary_for_conversation(
        user_id=str(other_user["id"]),
        conversation_id=fixture.conversation_id,
        current_message_created_at=_NOW + timedelta(hours=1),
        current_message_id=next_input.message_id,
        now=_NOW + timedelta(hours=2),
    ) is None

    selection = TutorContextBuilder(estimator=OneTokenEstimator()).build(loaded, token_budget=32)
    assert selection.checkpoint_metadata.compaction_input is not None
    assert selection.checkpoint_metadata.compaction_input.retired_message_ids == (
        str(history[2]["id"]),
    )
    recent_indexes = [
        index for index, item in enumerate(selection.items) if item.section is TutorContextSection.RECENT_MESSAGES
    ]
    summary_index = next(
        index for index, item in enumerate(selection.items) if item.section is TutorContextSection.WORKING_SUMMARY
    )
    assert recent_indexes
    assert max(recent_indexes) < summary_index


def test_structured_summary_source_hash_mismatch_stops_before_curator(tutor_persistence) -> None:
    fixture = tutor_persistence
    _context_input, outbox_id, _history = _prepare_structured_outbox(fixture)
    stored = fixture.connection.execute(
        "SELECT source_hashes_json FROM tutor_memory_curation_outbox WHERE id = %s",
        (outbox_id,),
    ).fetchone()
    assert stored is not None
    mismatched = list(stored["source_hashes_json"])
    mismatched[0] = "b" * 64
    fixture.connection.execute(
        "UPDATE tutor_memory_curation_outbox SET source_hashes_json = %s::jsonb WHERE id = %s",
        (json.dumps(mismatched), outbox_id),
    )
    scheduler_repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_background_preference(scheduler_repository, fixture)
    gateway = _NeverGateway()
    curator = TutorMemoryCurator(
        repository=PostgresTutorRepository(fixture.connection),
        learner_state=TutorLearnerStateRepository(fixture.connection),
        gateway=gateway,
    )
    scheduler = TutorProactiveScheduler(
        store=scheduler_repository,
        config=_scheduler_config(inferred_memory_enabled=False),
        curation_processor=curator,
    )
    scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)

    drained = scheduler.drain_curation(
        worker_id="mismatch-worker",
        now=_NOW,
        user_id=fixture.user_id,
    )
    job = fixture.connection.execute(
        "SELECT state, no_action_code FROM tutor_curation_jobs WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone()

    assert drained.claimed == 1
    assert drained.no_action == 1
    assert gateway.calls == 0
    assert job == {"state": "no_action", "no_action_code": "context_summary_message_hash_mismatch"}
    assert fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_context_summaries WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone() == {"count": 0}


def test_stale_structured_summary_is_not_loaded(tutor_persistence) -> None:
    fixture = tutor_persistence
    _context_input, _outbox_id, _history = _prepare_structured_outbox(fixture)
    scheduler_repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_background_preference(scheduler_repository, fixture)
    learner_state = TutorLearnerStateRepository(fixture.connection)
    scheduler = TutorProactiveScheduler(
        store=scheduler_repository,
        config=_scheduler_config(inferred_memory_enabled=False),
        curation_processor=TutorMemoryCurator(
            repository=PostgresTutorRepository(fixture.connection),
            learner_state=learner_state,
            gateway=_SummaryGateway(),
        ),
    )
    scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    scheduler.drain_curation(worker_id="stale-summary-worker", now=_NOW, user_id=fixture.user_id)

    new_run = fixture.repository.create_run(
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        catalog_digest=fixture.catalog.digest,
        policy=fixture.run.policy,
        origin="interactive",
    )
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=new_run.run_id,
        idempotency_key="stale-summary-input",
        content="继续当前学习",
        received_at=_NOW + timedelta(hours=1),
    )
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=new_run.run_id)
    assert snapshot is not None

    loaded = PostgresTutorContextLoader(
        conn=fixture.connection,
        learner_state=learner_state,
        now_provider=lambda: _NOW + timedelta(days=8),
    ).load_context(snapshot, input_revision=accepted.input_revision)

    assert loaded.working_summary == ()
    assert loaded.compaction_plan is not None
    assert loaded.compaction_plan.prior_summary_id is None



def test_structured_summary_scope_constraints_and_append_only_contract(tutor_persistence) -> None:
    fixture = tutor_persistence
    _context_input, outbox_id, _history = _prepare_structured_outbox(fixture)
    scheduler_repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_background_preference(scheduler_repository, fixture)
    learner_state = TutorLearnerStateRepository(fixture.connection)
    scheduler = TutorProactiveScheduler(
        store=scheduler_repository,
        config=_scheduler_config(inferred_memory_enabled=False),
        curation_processor=TutorMemoryCurator(
            repository=PostgresTutorRepository(fixture.connection),
            learner_state=learner_state,
            gateway=_SummaryGateway(),
        ),
    )
    scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    result = scheduler.drain_curation(
        worker_id="summary-constraint-worker", now=_NOW, user_id=fixture.user_id
    )
    assert result.completed == 1

    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_context_summaries SET summary = %s WHERE outbox_id = %s",
                ("篡改摘要", outbox_id),
            )

    other_conversation = fixture.repository.create_conversation(user_id=fixture.user_id)
    other_message = fixture.connection.execute(
        """
        INSERT INTO tutor_messages (conversation_id, role, content, created_at)
        VALUES (%s, 'learner', 'other conversation', %s)
        RETURNING id::text AS id
        """,
        (other_conversation, _NOW - timedelta(days=2)),
    ).fetchone()
    assert other_message is not None
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_memory_curation_outbox SET covered_through_message_id = %s WHERE id = %s",
                (other_message["id"], outbox_id),
            )


def test_primary_context_summary_gateway_requires_v2_and_sends_only_transient_bounded_evidence() -> None:
    message = TutorCurationMessageEvidence(
        message_id="00000000-0000-0000-0000-000000000011",
        role="learner",
        content="TRANSIENT_ONLY_MARKER 我已经有了，请继续讲函数。",
        content_hash="a" * 64,
        created_at=_NOW - timedelta(minutes=1),
    )
    source = TutorCurationSource(
        job_id="job-summary-1",
        outbox_id="outbox-summary-1",
        run_id="run-summary-1",
        user_id="user-summary-1",
        lease_owner_id="worker-summary-1",
        lease_generation=1,
        policy_version="tutor_policy_v1",
        memory_setting_version="memory_settings_v1",
        envelope={"kind": "compaction_request", "projection_kind": "context_summary"},
        source_ids=(message.message_id,),
        source_hashes=(message.content_hash,),
        retention_until=_NOW + timedelta(days=30),
        stale_after=_NOW + timedelta(days=7),
        conversation_id="conversation-summary-1",
        projection_kind="context_summary",
        summary_schema_version="tutor_context_summary_v2",
        summary_policy_version="tutor_context_summary_policy_v2",
        summary_source_hash="b" * 64,
        covered_through_created_at=message.created_at,
        covered_through_message_id=message.message_id,
        prior_summary_json={
            "schema_version": "tutor_context_summary_v2",
            "current_goal": "学习函数",
            "confirmed_facts": [],
            "completed_steps": [],
            "rejected_paths": [],
            "open_questions": [],
            "learner_preferences": [],
            "covered_through_created_at": (_NOW - timedelta(minutes=2)).isoformat(),
            "covered_through_message_id": "00000000-0000-0000-0000-000000000010",
            "source_hash": "c" * 64,
        },
        retired_messages=(message,),
    )
    client = _PrimaryClient(
        {
            "kind": "context_summary",
            "schema_version": "tutor_context_summary_v2",
            "current_goal": "继续学习函数参数",
            "confirmed_facts": ["学习者已经准备好资料"],
            "completed_steps": ["环境准备已完成"],
            "rejected_paths": ["不再重复旧路径"],
            "open_questions": ["是否先练默认参数"],
            "learner_preferences": ["偏好短示例"],
            "confidence": "high",
        }
    )
    gateway = PrimaryCurationGateway(client=client, max_output_tokens=256)

    result = gateway.propose(source=source)

    assert result.state == "proposal"
    assert isinstance(result.proposal, CurationContextSummaryProposalV2)
    assert len(client.calls) == 1
    serialized = json.dumps(client.calls[0], ensure_ascii=False)
    assert "TRANSIENT_ONLY_MARKER" in serialized
    assert "tutor_context_summary_v2" in serialized
    assert "memory_entry" not in serialized

    legacy_client = _PrimaryClient(
        {
            "kind": "context_summary",
            "summary": "旧短摘要不符合新结构化 contract",
            "confidence": "low",
        }
    )
    legacy_result = PrimaryCurationGateway(client=legacy_client, max_output_tokens=256).propose(
        source=source
    )
    assert legacy_result.state == "retryable"
    assert legacy_result.code == "curation_model_invalid_response"
