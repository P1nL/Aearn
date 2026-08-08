from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    CONTEXT_SECTION_PRIORITY,
    TutorContextError,
    TutorContextSection,
)
from app.services.tutor.interactive import PostgresTutorContextLoader
from app.services.tutor.learner_state import TutorLearnerStateRepository
from conftest import TutorPersistenceFixture


class OneTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 1


def _loader(fixture: TutorPersistenceFixture) -> PostgresTutorContextLoader:
    return PostgresTutorContextLoader(
        conn=fixture.connection,
        learner_state=TutorLearnerStateRepository(fixture.connection),
    )


def test_postgres_context_loader_pins_exact_run_revision_and_keeps_newest_history(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    base_time = fixture.run.policy.deadline - timedelta(days=2)
    history_ids: list[str] = []
    for index, content in enumerate(
        (
            "我想做个网站",
            "我们先走图片和 HTML 路径。",
            "绘画作品，迪士尼风格，零基础",
            "请先准备图片资源。",
            "我已经有了",
            "你不是应该教我编程语言吗",
        )
    ):
        role = "learner" if index % 2 == 0 else "tutor"
        row = fixture.connection.execute(
            """
            INSERT INTO tutor_messages (conversation_id, role, content, created_at)
            VALUES (%s, %s, %s, %s)
            RETURNING id::text AS id
            """,
            (fixture.conversation_id, role, content, base_time + timedelta(minutes=index)),
        ).fetchone()
        assert row is not None
        history_ids.append(str(row["id"]))

    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="latest-input-context",
        content="我应该学哪些语言",
        received_at=base_time + timedelta(minutes=6),
    )
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert snapshot is not None

    context_input = _loader(fixture).load_context(snapshot, input_revision=accepted.input_revision)
    selection = TutorContextBuilder(
        estimator=OneTokenEstimator(),
        config=TutorContextBuilderConfig(
            section_item_limits=tuple(
                (section, 4 if section is TutorContextSection.RECENT_MESSAGES else 0)
                for section in CONTEXT_SECTION_PRIORITY
            ),
        ),
    ).build(context_input, token_budget=8)

    assert context_input.current_input is not None
    assert context_input.current_input.source_id == f"message:{accepted.message_id}"
    assert context_input.current_input.content == "我应该学哪些语言"
    assert all(source.source_id != f"message:{accepted.message_id}" for source in context_input.recent_messages)
    assert [item.source_id for item in selection.items] == [f"message:{message_id}" for message_id in history_ids[-4:]]


def test_postgres_context_loader_uses_input_event_when_timestamps_tie_or_a_later_row_interferes(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    accepted_at = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="timestamp-tie-current",
        content="权威当前输入",
        received_at=accepted_at,
    )
    interference = fixture.connection.execute(
        """
        INSERT INTO tutor_messages (conversation_id, role, content, created_at)
        VALUES (%s, 'learner', '时间戳更晚但不是当前输入', %s)
        RETURNING id::text AS id
        """,
        (fixture.conversation_id, accepted_at + timedelta(seconds=1)),
    ).fetchone()
    assert interference is not None
    tied = fixture.connection.execute(
        """
        INSERT INTO tutor_messages (conversation_id, role, content, created_at)
        VALUES (%s, 'tutor', '同时间戳干扰行', %s)
        RETURNING id::text AS id
        """,
        (fixture.conversation_id, accepted_at),
    ).fetchone()
    assert tied is not None
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert snapshot is not None

    context_input = _loader(fixture).load_context(snapshot, input_revision=accepted.input_revision)

    assert context_input.current_input is not None
    assert context_input.current_input.source_id == f"message:{accepted.message_id}"
    assert context_input.current_input.content == "权威当前输入"
    assert [source.source_id for source in context_input.recent_messages] == [
        f"message:{tied['id']}",
        f"message:{interference['id']}",
    ]


def test_postgres_context_loader_rejects_missing_or_wrong_role_current_input_evidence(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="invalid-evidence-current",
        content="当前输入",
    )
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert snapshot is not None
    loader = _loader(fixture)

    fixture.connection.execute(
        "UPDATE tutor_messages SET role = 'tutor' WHERE id = %s",
        (accepted.message_id,),
    )
    with pytest.raises(TutorContextError) as role_error:
        loader.load_context(snapshot, input_revision=accepted.input_revision)
    assert role_error.value.safe_code == "TUTOR_CURRENT_INPUT_ROLE_INVALID"

    fixture.connection.execute(
        "UPDATE tutor_messages SET role = 'learner' WHERE id = %s",
        (accepted.message_id,),
    )
    fixture.connection.execute(
        "DELETE FROM tutor_run_input_events WHERE run_id = %s AND input_revision = %s",
        (fixture.run.run_id, accepted.input_revision),
    )
    with pytest.raises(TutorContextError) as missing_error:
        loader.load_context(snapshot, input_revision=accepted.input_revision)
    assert missing_error.value.safe_code == "TUTOR_CURRENT_INPUT_EVIDENCE_INVALID"


def test_postgres_context_loader_resolves_explicit_continuation_revision(tutor_persistence) -> None:
    fixture = tutor_persistence
    first = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="continuation-first",
        content="第一条输入",
    )
    fixture.connection.execute(
        """
        UPDATE tutor_runs
        SET status = 'waiting_for_input', continuation_kind = 'approval'
        WHERE id = %s AND user_id = %s
        """,
        (fixture.run.run_id, fixture.user_id),
    )
    second = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="continuation-second",
        content="第二条 continuation 输入",
    )
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert snapshot is not None
    assert second.input_revision == first.input_revision + 1
    assert snapshot.continuation_kind is None

    context_input = _loader(fixture).load_context(snapshot, input_revision=second.input_revision)

    assert context_input.current_input is not None
    assert context_input.current_input.source_id == f"message:{second.message_id}"
    assert context_input.current_input.content == "第二条 continuation 输入"
    assert any(source.source_id == f"message:{first.message_id}" for source in context_input.recent_messages)


def test_postgres_context_loader_rejects_snapshot_scope_mismatch(tutor_persistence) -> None:
    fixture = tutor_persistence
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="scope-current",
        content="范围内输入",
    )
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert snapshot is not None
    other_conversation = fixture.repository.create_conversation(user_id=fixture.user_id)
    mismatched = replace(snapshot, conversation_id=other_conversation)

    with pytest.raises(TutorContextError) as exc_info:
        _loader(fixture).load_context(mismatched, input_revision=accepted.input_revision)

    assert exc_info.value.safe_code == "TUTOR_CURRENT_INPUT_EVIDENCE_INVALID"


def test_proactive_postgres_context_loader_does_not_invent_current_input(tutor_persistence) -> None:
    fixture = tutor_persistence
    loader = PostgresTutorContextLoader(
        conn=fixture.connection,
        learner_state=TutorLearnerStateRepository(fixture.connection),
        proactive_candidate_kind="review_due",
    )

    with pytest.raises(TutorContextError) as origin_error:
        loader.load_context(fixture.run, input_revision=0)
    assert origin_error.value.safe_code == "TUTOR_CONTEXT_ORIGIN_INVALID"

    proactive_snapshot = replace(fixture.run, origin="proactive")
    context_input = loader.load_context(proactive_snapshot, input_revision=0)

    assert context_input.current_input is None
    assert context_input.current_input_required is False
    assert context_input.recent_messages == ()
