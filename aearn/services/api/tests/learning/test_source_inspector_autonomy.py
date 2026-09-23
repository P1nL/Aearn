from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import TutorContextInput, TutorContextSource, TutorTerminalOutcome
from app.agents.harness.provider_request import build_tutor_provider_messages
from app.services.learning.lesson_contracts import CodeExampleBlock, ConceptBlock, ExerciseGateBlock
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.learning.source_inspector import (
    PostgresSourceInspectorMaterializer, SourceInspectorCommitError,
    _rank_source_blocks, _scope_identity, validate_source_inspector_evidence,
)
from app.services.learning.teaching_contracts import TeachingControlStimulus
from app.services.learning.teaching_sessions import TeachingSessionService
from app.services.tutor.persistence import PostgresTutorRepository
from tests.learning.test_source_inspector import (
    TutorSourceScope, _TutorSourceProvider, _bootstrap_source_inspector, _dispatch, _settings, source_scope,
)
from tests.support.teaching_session_support import connection, database_available

# Imported fixture owns and cleans exact test-user rows in the isolated regression DB.
__all__ = ("source_scope", "_bootstrap_source_inspector")
pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")
_CITATIONS = ("cite_0123456789abcdef",)


def _blocks():  # type: ignore[no-untyped-def]
    return (
        ConceptBlock(block_id="assignment", order_index=0, citation_ids=_CITATIONS,
                     title="变量赋值", paragraphs=("赋值将右侧表达式绑定到变量名。",), coverage_keys=("python.variables",)),
        ConceptBlock(block_id="reference", order_index=1, citation_ids=_CITATIONS,
                     title="引用与列表浅拷贝", paragraphs=("简单赋值不会复制列表。两个变量引用同一个对象；切片创建新列表。",), coverage_keys=("python.variables",)),
        CodeExampleBlock(block_id="append-example", order_index=2, citation_ids=_CITATIONS,
                         title="列表追加", language_id="python", code="rgb = [1, 2]\nrgba = rgb\nrgba.append(4)",
                         explanation=("通过 rgba 追加也会改变 rgb。",)),
    )


def test_unprompted_question_ranks_relevant_second_concept_not_first_block() -> None:
    query = "我以为 b = a 会复制列表。为什么它们引用同一个对象？切片又有什么区别？"
    assert "来源" not in query
    blocks = _blocks()
    ranked = _rank_source_blocks(blocks, query=query)
    assert ranked[0].block_id == "reference"
    assert tuple(b.block_id for b in ranked) == tuple(b.block_id for b in _rank_source_blocks(tuple(reversed(blocks)), query=query))
    assert _rank_source_blocks(blocks, query="What does rgba.append do to rgb?")[0].block_id == "append-example"


def test_unrelated_query_has_no_fabricated_fallback_and_private_gate_is_not_indexed() -> None:
    gate = ExerciseGateBlock(block_id="gate", order_index=3, citation_ids=_CITATIONS,
                             gate_key="python.variables.test", gate_kind="knowledge_check",
                             assessment_contract_version="lesson_gate_v1", required_capabilities=("python",),
                             learner_prompt="火星轨道")
    assert _rank_source_blocks((*_blocks(), gate), query="火星轨道") == ()
    assert _rank_source_blocks(_blocks(), query="明白了，谢谢。") == ()
    assert _rank_source_blocks((replace(_blocks()[1], citation_ids=()),), query="引用与列表浅拷贝") == ()


def _run_scope(conn, scope):  # type: ignore[no-untyped-def]
    row = conn.execute("SELECT * FROM tutor_run_teaching_scopes WHERE run_id=%s AND user_id=%s", (scope.run_id, scope.user_id)).fetchone()
    assert row is not None
    return row


def _input(conn, scope, text):  # type: ignore[no-untyped-def]
    # Bounded fixture-only persisted input, never used in real acceptance.
    message = conn.execute("INSERT INTO tutor_messages(conversation_id,role,content) VALUES (%s,'learner',%s) RETURNING id", (scope.conversation_id, text)).fetchone()
    conn.execute("""INSERT INTO tutor_run_input_events(run_id,conversation_id,message_id,input_revision,idempotency_key,body_hash,source)
                    VALUES (%s,%s,%s,1,%s,%s,'test')""", (scope.run_id, scope.conversation_id, message["id"], str(uuid4()), "a"*64))
    conn.execute("UPDATE tutor_runs SET input_revision=1 WHERE id=%s", (scope.run_id,))


def test_persisted_normal_input_selects_exact_example_without_source_request(source_scope: TutorSourceScope) -> None:
    with connection() as conn:
        _input(conn, source_scope, "count = 3 后执行 print(count)，这里会发生什么？")
        materializer = PostgresSourceInspectorMaterializer(conn, settings=_settings())
        candidates = materializer.build_candidates(scope=_run_scope(conn, source_scope))
        assert candidates and candidates[0].block_id == "example"
        assert candidates[0].title == "建立并读取变量"
        assert candidates[0].document_content_hash == source_scope.document_content_hash
        assert candidates[0].recently_displayed is False


def test_explicit_selection_precedes_ranking_and_exact_block_is_not_duplicated(source_scope: TutorSourceScope) -> None:
    with connection() as conn:
        scope = _run_scope(conn, source_scope)
        document = PostgresLessonDocumentRepository(conn).load_document(document_id=source_scope.document_id)
    normalized = _scope_identity(scope)
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [{"reference_id": "selected-ref"}]
    materializer = PostgresSourceInspectorMaterializer(db, settings=_settings())
    materializer._retrieval_context = MagicMock(return_value=("变量绑定", frozenset(), True))
    materializer._lessons.load_document = MagicMock(return_value=document)
    # Same exact block reached through the explicit selection and block fallback.
    resolved = {
        "source_kind": "context_reference", "source_id": "selected-ref",
        "assignment": {"assignment_id": normalized["assignment_id"], "assignment_version": 2, "document_id": normalized["document_id"]},
        "document": {"title": document.title, "content_hash": document.content_hash, "blocks": [{"block_id": "concept", "title": "变量绑定"}]},
        "target": {"block_id": "concept", "citation_ids": [source_scope.citation_id], "safe_excerpt": "变量绑定"},
    }
    def resolve(**kwargs):  # type: ignore[no-untyped-def]
        source = kwargs["source"]
        return resolved if not hasattr(source, "block_id") else {**resolved, "source_kind": "lesson_block", "source_id": source.block_id}
    materializer._resolver.resolve = MagicMock(side_effect=resolve)
    candidates = materializer.build_candidates(scope=scope)
    assert len(candidates) == 1
    assert candidates[0].source_kind == "context_reference"


def test_recent_display_is_time_scoped_and_never_includes_current_or_future_turn(source_scope: TutorSourceScope) -> None:
    provider = _TutorSourceProvider(choose_source=True)
    result = _dispatch(settings=_settings(), scope=source_scope, provider=provider)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connection() as conn:
        service = TeachingSessionService(conn, settings=_settings())
        current = service.current(user_id=source_scope.user_id, track_id=source_scope.track_id, knowledge_key=source_scope.knowledge_key)
        key = str(uuid4())
        opened = service.action(
            user_id=source_scope.user_id, track_id=source_scope.track_id, session_id=source_scope.session_id,
            control=TeachingControlStimulus(control_key="continue", client_action_id=key,
                expected_session_version=current["session_version"], expected_track_version=current["track_version"],
                expected_progress_version=current["progress_version"], expected_assignment_version=current["assignment_version"]),
            target_mode=None, admit_run=True, idempotency_key=key,
        )
        following = replace(source_scope, run_id=str(opened["pending_run"]["run_id"]))
        materializer = PostgresSourceInspectorMaterializer(conn, settings=_settings())
        scope = _run_scope(conn, following)
        _query, recent, _has_input = materializer._retrieval_context(scope=_scope_identity(scope))
        identity = (source_scope.document_id, source_scope.document_content_hash, source_scope.block_id)
        assert identity in recent
        candidates = materializer.build_candidates(scope=scope)
        assert any(c.block_id == source_scope.block_id and c.recently_displayed for c in candidates)
        # Rebuilding the old run never treats its own newly committed card as history.
        old = materializer._retrieval_context(scope=_scope_identity(_run_scope(conn, source_scope)))
        assert not old[1]
        foreign_document = {**_scope_identity(scope), "document_content_hash": "f"*64}
        assert not materializer._retrieval_context(scope=foreign_document)[1]
        conn.execute("UPDATE tutor_runs SET terminal_at=(SELECT created_at+interval '1 second' FROM tutor_runs WHERE id=%s) WHERE id=%s", (following.run_id, source_scope.run_id))
        assert not materializer._retrieval_context(scope=_scope_identity(scope))[1]


def test_source_metadata_is_strict_and_provider_policy_is_autonomous_and_restrained(source_scope: TutorSourceScope) -> None:
    with connection() as conn:
        candidate = PostgresSourceInspectorMaterializer(conn, settings=_settings()).build_candidates(scope=_run_scope(conn, source_scope))[0]
        snapshot = PostgresTutorRepository(conn).load_snapshot(user_id=source_scope.user_id, run_id=source_scope.run_id)
    assert snapshot is not None
    evidence = candidate.provider_evidence()
    for bad in (1, "true", None):
        with pytest.raises(SourceInspectorCommitError):
            validate_source_inspector_evidence([{**evidence, "recently_displayed": bad}])
    assert candidate.model_copy(update={"recently_displayed": True}).handle == candidate.handle
    context = TutorContextBuilder().build(TutorContextInput(run_id=source_scope.run_id, conversation_id=source_scope.conversation_id, input_revision=0, current_input_required=False, required_facts=(TutorContextSource(
        source_id=f"teaching-source-candidate:{source_scope.run_id}:0", content=evidence,
        semantic_class="confirmed_fact_source"),)), token_budget=4000)
    system = build_tutor_provider_messages(run=snapshot, context=context)[0]["content"]
    assert "even without an explicit source request" in system
    assert "Do not attach sources for thanks" in system
    assert "do not repeat a recently displayed passage" in system
    assert "omit unrelated passages" in system
