"""CPU-only B lesson contracts. No connection, bootstrap, provider or runner I/O."""
from __future__ import annotations

import copy
import hashlib
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.grounding import grounding_index_repository as grounding
from app.services.grounding.grounding_fixtures import fixture_documents_for_language
from app.services.grounding.grounding_processing import clean_and_chunk_document, is_admissible_lesson_source
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery
from app.services.learning import lesson_authoring as authoring
from app.services.learning import lesson_completion_stages as completion
from app.services.learning.lesson_authoring_feedback import LessonAuthorFeedback, LessonFeedbackIssue, attempt_diagnostic, validate_attempt_diagnostic
from app.services.learning.lesson_contracts import (
    LESSON_COMPLETION_VERSION, LESSON_EVIDENCE_VERSION, LessonEvidenceUnit,
    canonical_lesson_document_payload, canonical_source_set_hash, lesson_evidence_identity,
)
from app.services.learning.lesson_projection import project_lesson_source
from app.services.learning.lesson_repository import LessonAuthoringRunRecord, LessonScopeRecord, LessonVersionConflict, PostgresLessonDocumentRepository
from tests.support.lesson_document_support import author_candidate_payload, sample_lesson_document, sample_source_snapshot


NOW = datetime(2026, 10, 26, tzinfo=UTC)


def snapshot():
    text = "变量 variables bind names to values. " * 60 + "Exception: assignment alone does not copy an object."
    digest = hashlib.sha256(text.encode()).hexdigest()
    return replace(sample_source_snapshot(), chunk_content_hash=digest,
        evidence_excerpt=" ".join(text.split())[:1200], evidence_schema_version=LESSON_EVIDENCE_VERSION,
        evidence_units=(LessonEvidenceUnit(text, digest, 0, len(text.encode())),))


def run_record(**changes):
    base = LessonAuthoringRunRecord(
        run_id="run-1", user_id="user-1", track_id="track-1", knowledge_key="python.variables",
        run_kind="prepare", state="running", idempotency_key="key-1", request_hash="a" * 64,
        expected_track_version=1, expected_progress_version=1, active_plan_revision_id="revision-1",
        profile_hash="b" * 64, source_set_hash=canonical_source_set_hash((snapshot(),)), attempt_count=0,
        lease_generation=1, lease_owner="owner-1", lease_expires_at=NOW + timedelta(seconds=120),
        failure_code=None, failure_message=None, standard_document_id=None, personalized_document_id=None,
        assignment_id=None, created_at=NOW, updated_at=NOW, terminal_at=None,
        completion_contract_version=LESSON_COMPLETION_VERSION,
    )
    return replace(base, **changes)


def scope_record():
    return LessonScopeRecord("user-1", "track-1", "python", "Learn variables", "beginner", 1, "revision-1",
        "core", False, "python.variables", "Variables", "Names and values", ("python.variables",),
        "available", 1, "unseen", 0.0)


def request(kind="standard", standard=None):
    evidence, handles = authoring._authoring_evidence((snapshot(),))
    return authoring.LessonAuthoringRequest(kind, "python", "python.variables", "Variables", "Learn variables",
        "beginner", ("python.variables",), "unseen", 0.0, evidence, standard,
        citation_handles=tuple(handles.items()), completion_contract_version=LESSON_COMPLETION_VERSION)


def test_evidence_full_utf8_bytes_feed_generation_but_not_display_or_legacy_hash():
    source = snapshot()
    legacy = replace(source, evidence_schema_version=None, evidence_units=())
    assert canonical_source_set_hash((source,)) == canonical_source_set_hash((legacy,))
    assert len(project_lesson_source(source)["evidence_excerpt"]) == 1200
    assert "evidence_units" not in project_lesson_source(source)
    payload = authoring._safe_request_payload(request())
    unit = payload["evidence"][0]["evidence_units"][0]
    assert unit["text"].endswith("assignment alone does not copy an object.")
    assert unit["end_byte"] == len(unit["text"].encode("utf-8")) > len(unit["text"])
    assert unit["content_hash"] == hashlib.sha256(unit["text"].encode()).hexdigest()
    with pytest.raises(ValueError):
        replace(source.evidence_units[0], text="truncated")
    with pytest.raises(ValueError):
        replace(source, chunk_content_hash="f" * 64)
    with pytest.raises(ValueError):
        lesson_evidence_identity((legacy,))


def test_coverage_follows_missing_topics_instead_of_global_four(monkeypatch):
    original = clean_and_chunk_document(fixture_documents_for_language("python")[0])[0]
    chunks = []
    topics = tuple(f"python.topic{i}" for i in range(6))
    for i, topic in enumerate(topics):
        text = f"Definition and exception for topic{i}."
        chunks.append(replace(original, chunk_id=str(i), title=topic, text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(), topic_tags=(topic,)))
    # A top-ranked invalid-provenance candidate must not consume coverage.
    chunks.insert(0, replace(chunks[0], chunk_id="invalid", content_hash="0" * 64))
    monkeypatch.setattr(grounding, "_load_grounding_chunks_for_languages", lambda *_: tuple(chunks))
    selected, missing = grounding.search_lesson_coverage_chunks(Mock(), GroundingRetrievalQuery("python", "topic"),
        required_topics=topics, admission_filter=lambda chunk: is_admissible_lesson_source(chunk, allow_fixtures_for_tests=True))
    assert len(selected) == 6 and not missing
    assert {item.chunk.chunk_id for item in selected} == {str(i) for i in range(6)}
    selected, missing = grounding.search_lesson_coverage_chunks(Mock(), GroundingRetrievalQuery("python", "topic"),
        required_topics=(*topics, "python.missing"), admission_filter=lambda _: True)
    assert missing == ("python.missing",)


def test_standard_dependency_is_complete_private_and_independent_of_personal_conditions():
    def dependency(run=None, scope=None, **kw):
        return completion.stage_dependency(run=run or run_record(), scope=scope or scope_record(),
            snapshots=(snapshot(),), stage_kind="standard", policy={"timeout_seconds": 600}, **kw)
    base = dependency()
    assert dependency(scope=replace(scope_record(), mastery_level="learning", mastery_confidence=0.3)) == base
    for scope in (replace(scope_record(), goal_text="A different goal"), replace(scope_record(), node_description="Different curriculum"),
                  replace(scope_record(), active_plan_revision_id="revision-2")):
        assert dependency(scope=scope) != base
    assert dependency(run=run_record(user_id="other")) != base
    assert dependency(run=run_record(track_id="other")) != base
    assert base["evidence"]["selected_units"][0]["units"][0]["text"] == snapshot().evidence_units[0].text


def test_feedback_and_diagnostic_cumulative_versions_preserve_legacy_contracts():
    issue = LessonFeedbackIssue("LESSON_CITATION_REQUIRED", "blocks[2]")
    feedback = LessonAuthorFeedback("standard", "quality_gate", 7, (issue,), "lesson_author_feedback_v2")
    value = attempt_diagnostic("standard", 7, feedback, completion_driven=True)
    assert value["schema_version"] == "lesson_author_attempt_diagnostic_v3"
    assert validate_attempt_diagnostic(value) == value
    assert validate_attempt_diagnostic({}) == {}
    assert attempt_diagnostic("standard", 1)["schema_version"] == "lesson_author_attempt_diagnostic_v1"
    with pytest.raises(ValueError):
        LessonAuthorFeedback("standard", "quality_gate", 7, (issue,))
    with pytest.raises(ValueError):
        validate_attempt_diagnostic({**value, "schema_version": "lesson_author_attempt_diagnostic_v2"})


class MemoryStages:
    def __init__(self):
        self.rows, self.events = [], []
        self.current = True
        self.lost = False
        self.stop_before_decision = False
        self.lose_after_result = False

    @contextmanager
    def connection(self):
        yield self

    @contextmanager
    def transaction(self):
        yield self
        self.events.append("commit")

    def assert_authoring_current(self, **_kwargs):
        if not self.current:
            raise LessonVersionConflict("stale")

    def evidence_is_current(self, _snapshots):
        return self.current

    def read_completion_attempts(self, *, run, stage_kind, dependency):
        return tuple(copy.deepcopy(row) for row in self.rows
            if row["user_id"] == run.user_id and row["track_id"] == run.track_id
            and row["stage_kind"] == stage_kind and row["dependency_json"] == dependency)

    def begin_completion_attempt(self, *, run, stage_kind, dependency, now, **_kwargs):
        self.events.append("intent")
        row = {"id": str(len(self.rows) + 1), "run_id": run.run_id, "user_id": run.user_id, "track_id": run.track_id,
            "stage_kind": stage_kind, "dependency_json": dict(dependency), "stage_attempt_index": len(self.rows) + 1,
            "state": "intent", "lease_generation": run.lease_generation,
            "request_deadline_at": now + timedelta(seconds=600), "result_deadline_at": now + timedelta(seconds=660)}
        self.rows.append(row)
        return copy.deepcopy(row)

    def save_completion_result(self, *, attempt, result, feedback, execution_outcome, usage_status, now):
        row = next(row for row in self.rows if row["id"] == attempt["id"])
        row.update(result_json=copy.deepcopy(result), feedback_json=copy.deepcopy(feedback),
            execution_outcome=execution_outcome, usage_status=usage_status, result_saved_at=now,
            state="outcome_unknown" if execution_outcome == "unknown" else "result_saved")
        self.events.append("result")
        if self.lose_after_result:
            self.lost = True
        return copy.deepcopy(row)

    def decide_completion_result(self, *, attempt, document, quality, **_kwargs):
        if self.stop_before_decision:
            raise LessonVersionConflict("simulated process stop after result COMMIT")
        assert self.events[-1] == "commit"
        row = next(row for row in self.rows if row["id"] == attempt["id"])
        row.update(state="accepted" if document else "rejected", quality_json=quality,
            document_json=canonical_lesson_document_payload(document) if document else None,
            document_hash=document.content_hash if document else None)
        self.events.append(row["state"])
        return copy.deepcopy(row)

    def ensure(self):
        if self.lost:
            raise LessonVersionConflict("heartbeat lost")


class Author:
    def __init__(self, store, candidates=None, error=None):
        self.store, self.candidates, self.error = store, list(candidates or []), error
        self.requests = []

    def author(self, request):
        assert self.store.events[-1] == "commit"
        assert self.store.rows[-1]["state"] == "intent"
        self.requests.append(request)
        self.store.events.append("provider")
        if self.error:
            raise self.error
        return authoring.LessonAuthoringResponse(self.candidates.pop(0) if self.candidates else author_candidate_payload(
            personalized=request.document_kind == "personalized"), "fake", "fixture", "fixture", usage=None)


@pytest.fixture
def store(monkeypatch):
    store = MemoryStages()
    monkeypatch.setattr(completion, "connect", store.connection)
    monkeypatch.setattr(completion, "PostgresLessonDocumentRepository", lambda _conn: store)
    return store


def stage(store, author, *, run=None, req=None, dependency=None):
    return completion.complete_stage(run=run or run_record(), request=req or request(), dependency=dependency or {"kind": "standard"},
        snapshots=(snapshot(),), handles={"S1": snapshot().citation_id}, port=author, clock=lambda: NOW, heartbeat=store)


def test_intent_result_and_acceptance_are_separate_commits_and_usage_unknown_is_not_zero(store):
    port = Author(store)
    document, quality, accepted = stage(store, port)
    assert quality.passed and accepted["state"] == "accepted"
    assert store.events.index("intent") < store.events.index("provider") < store.events.index("result") < store.events.index("accepted")
    assert store.events[store.events.index("result") + 1] == "commit"
    assert accepted["result_json"]["candidate"] == author_candidate_payload()
    assert accepted["result_json"]["usage"] is None and accepted["usage_status"] == "unknown"
    assert accepted["execution_outcome"] == "known"
    assert document.content_hash == accepted["document_hash"]
    stage(store, port, run=run_record(run_id="new-explicit-run"))
    assert len(port.requests) == 1  # same-user/course dependency reuse before provider


def test_result_saved_recovery_never_repeats_provider(store):
    store.stop_before_decision = True
    port = Author(store)
    with pytest.raises(LessonVersionConflict):
        stage(store, port)
    assert store.rows[0]["state"] == "result_saved"
    store.stop_before_decision = False
    stage(store, port, run=run_record(lease_generation=2, lease_owner="reclaimer"))
    assert len(port.requests) == 1


def test_personalized_failure_keeps_standard_committed_and_resume_uses_it(store):
    port = Author(store)
    standard, _quality, _row = stage(store, port)
    store.stop_before_decision = True
    with pytest.raises(LessonVersionConflict):
        stage(store, port, req=request("personalized", standard), dependency={"kind": "personalized"})
    store.stop_before_decision = False
    standard2, _, _ = stage(store, port, run=run_record(lease_generation=2))
    personal, _, _ = stage(store, port, run=run_record(lease_generation=2), req=request("personalized", standard2), dependency={"kind": "personalized"})
    assert standard2 == standard and personal is not None
    assert [req.document_kind for req in port.requests] == ["standard", "personalized"]


def test_directed_repairs_accept_more_than_two_cumulative_attempts(store):
    first, second = author_candidate_payload(), author_candidate_payload()
    first["extra"] = "invalid"
    second["blocks"][2]["citation_ids"] = []
    port = Author(store, [first, second, author_candidate_payload()])
    _, _, row = stage(store, port)
    assert row["stage_attempt_index"] == 3
    assert [request.previous_attempt_feedback.previous_attempt_index for request in port.requests[1:]] == [1, 2]
    assert [row["state"] for row in store.rows] == ["rejected", "rejected", "accepted"]


def test_repeated_failure_without_progress_stops_and_persists_actual_candidate(store):
    bad = author_candidate_payload()
    bad["blocks"][2]["citation_ids"] = []
    port = Author(store, [bad, copy.deepcopy(bad)])
    with pytest.raises(authoring.LessonAuthoringFailure):
        stage(store, port)
    assert len(port.requests) == 2
    assert all(row["result_json"]["candidate"] == bad for row in store.rows)


def test_unknown_execution_never_replays_even_under_new_run_or_expired_lease(store):
    port = Author(store, error=TimeoutError("not a provider closure"))
    with pytest.raises(authoring.LessonAuthoringFailure, match="未知"):
        stage(store, port)
    assert store.rows[0]["state"] == "outcome_unknown"
    with pytest.raises(authoring.LessonAuthoringFailure, match="未知"):
        stage(store, port, run=run_record(run_id="different", lease_generation=8))
    assert len(port.requests) == 1 and store.rows[0]["usage_status"] == "unknown"


def test_lease_loss_keeps_actual_result_but_does_not_accept(store):
    store.lose_after_result = True
    with pytest.raises(LessonVersionConflict):
        stage(store, Author(store))
    assert store.rows[0]["state"] == "result_saved"
    assert store.rows[0]["result_json"]["candidate"] == author_candidate_payload()


def test_stale_evidence_blocks_cached_standard_without_provider_call(store):
    port = Author(store)
    stage(store, port)
    store.current = False
    with pytest.raises(LessonVersionConflict):
        stage(store, port)
    assert len(port.requests) == 1


def test_targeted_personal_changes_cannot_rewrite_unaffected_blocks():
    previous = sample_lesson_document(personalized=True)
    req = replace(request("personalized", sample_lesson_document()), previous_personalized_document=previous,
        editable_block_ids=("concept", "summary"))
    blocks = list(previous.blocks)
    blocks[0] = replace(blocks[0], title="Unrelated change")
    with pytest.raises(authoring.LessonAuthoringFailure):
        authoring._assert_candidate_identity(replace(previous, blocks=tuple(blocks)), req)
    blocks = list(previous.blocks)
    blocks[2] = replace(blocks[2], paragraphs=("Updated explanation",))
    authoring._assert_candidate_identity(replace(previous, blocks=tuple(blocks)), req)
    payload = authoring._safe_request_payload(req)
    assert payload["editable_block_ids"] == ["concept", "summary"]


@pytest.mark.parametrize("change", ["title", "coverage", "block_coverage", "citations", "block_type"])
def test_targeted_personal_changes_preserve_document_and_editable_block_structure(change):
    from app.services.learning.lesson_contracts import HintBlock
    previous = sample_lesson_document(personalized=True)
    req = replace(request("personalized", sample_lesson_document()), previous_personalized_document=previous,
        editable_block_ids=("concept", "summary"))
    candidate = previous
    if change == "title":
        candidate = replace(previous, title="Unrelated title change")
    elif change == "coverage":
        candidate = replace(previous, coverage_keys=(*previous.coverage_keys, "python.unrelated"))
    else:
        blocks = list(previous.blocks)
        concept = blocks[2]
        if change == "block_coverage":
            blocks[2] = replace(concept, coverage_keys=("python.unrelated",))
        elif change == "citations":
            blocks[2] = replace(concept, citation_ids=())
        else:
            blocks[2] = HintBlock(block_id=concept.block_id, order_index=concept.order_index,
                citation_ids=concept.citation_ids, title="Changed block type", steps=("Keep structure",))
        candidate = replace(previous, blocks=tuple(blocks))
    with pytest.raises(authoring.LessonAuthoringFailure) as failure:
        authoring._assert_candidate_identity(candidate, req)
    assert failure.value.issues[0].code == "LESSON_PERSONALIZED_UNAFFECTED_CHANGED"


@pytest.mark.parametrize("unclosed", [False, True])
def test_new_running_reclaim_uses_generation_cas_only_with_closed_stage(unclosed):
    run = run_record(lease_expires_at=NOW - timedelta(seconds=1))
    row = {**asdict(run), "id": run.run_id}
    claimed = {**row, "lease_generation": 2, "lease_owner": "new", "lease_expires_at": NOW + timedelta(seconds=120)}
    conn = Mock()
    conn.execute.side_effect = [Mock(fetchone=lambda: row), Mock(fetchone=lambda: {"id": "open"} if unclosed else None), Mock(fetchone=lambda: claimed)]
    result = PostgresLessonDocumentRepository(conn).claim_authoring_run(run_id=run.run_id, owner="new", now=NOW)
    if unclosed:
        assert result is None and conn.execute.call_count == 2
    else:
        assert result.state == "running" and result.lease_generation == 2
        sql, args = conn.execute.call_args.args
        assert "AND lease_generation = %s AND state = %s" in sql
        assert args[0] == "running" and args[-2:] == (1, "running")


def test_schema_is_forward_single_private_table_with_committed_result_and_purge_guards():
    path = Path(__file__).resolve().parents[2] / "app/db/schema/597_lesson_completion_stages.sql"
    sql = path.read_text(encoding="utf-8")
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 1
    assert "CREATE TABLE IF NOT EXISTS tutor_lesson_authoring_stage_attempts" in sql
    assert "tutor_learning_track_purge_allowed(OLD.user_id)" in sql
    assert "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED" in sql
    assert "OLD.result_transaction_id = pg_current_xact_id()" in sql
    assert "NEW.decision_lease_generation IS DISTINCT FROM owner_row.lease_generation" in sql
    assert "OLD.state = 'running' AND NEW.state = 'running'" in sql
    assert "Legacy Lesson rows cannot be converted or reopened" in sql
    assert "state IN ('intent','outcome_unknown')" in sql
    assert "digest(raw_bytes, 'sha256')" in sql
    assert "evidence_schema_version IS NOT DISTINCT FROM 'lesson_evidence_units_v1'" in sql
    assert "Committed Lesson results require reconciliation before failure" in sql
    assert "DELETE FROM" not in sql and "UPDATE tutor_lesson_authoring_runs" not in sql


def test_explicit_opt_in_remains_default_off_without_database(monkeypatch):
    from app.services.learning import lesson_service
    monkeypatch.setattr(lesson_service, "get_settings", lambda: SimpleNamespace(tutor_completion_driven_enabled=False))
    conn = Mock()
    with pytest.raises(lesson_service.LessonDocumentServiceError, match="尚未启用"):
        lesson_service.LessonDocumentService(conn).prepare(user_id="not-reached", track_id="not-reached", knowledge_key="python.variables",
            expected_track_version=1, expected_progress_version=1, idempotency_key="key", completion_driven=True)
    conn.execute.assert_not_called()


def test_primary_policy_is_only_on_new_requests_and_inside_real_stage_scope(store):
    from app.agents.harness.contracts import TutorExecutionProfile
    from app.core.config import Settings
    from app.services.llm.http_execution import current_http_execution
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-flash",
        deepseek_api_key="offline-fixture", deepseek_base_url="https://provider.invalid",
        tutor_completion_driven_enabled=True)
    calls = []

    class Client:
        def complete_json(self, _messages, **kwargs):
            execution = current_http_execution()
            if kwargs.get("completion_stage") is not None:
                assert execution is not None
                assert execution.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1
                assert execution.max_attempts == 1
                assert execution.before_send() == 600
            else:
                assert execution is None
            calls.append(kwargs)
            return SimpleNamespace(content=author_candidate_payload(), model="fixture", usage=None, response_diagnostics=None)

    primary = authoring.PrimaryLessonDocumentAuthor(settings, client=Client())
    primary.author(replace(request(), completion_contract_version=None))
    stage(store, primary)
    assert "completion_stage" not in calls[0]
    assert calls[1]["completion_stage"] == "lesson_authoring"
    assert calls[0]["max_tokens"] == calls[1]["max_tokens"] == 12000


def test_expired_open_intent_is_not_a_retry_permit(store):
    port = Author(store)
    intent = store.begin_completion_attempt(run=run_record(), stage_kind="standard", dependency={"kind": "standard"}, now=NOW)
    store.rows[0]["result_deadline_at"] = NOW - timedelta(seconds=1)
    assert intent["state"] == "intent"
    with pytest.raises(authoring.LessonAuthoringFailure, match="尚未闭合"):
        stage(store, port, run=run_record(lease_generation=2))
    assert port.requests == []


def test_proven_not_started_failure_allows_only_fresh_explicit_run(store):
    failure = authoring.LessonAuthoringFailure("LESSON_DOCUMENT_GENERATION_UNAVAILABLE", "fixture disabled", outcome="unavailable")
    failure.execution_outcome = "not_started"
    port = Author(store, error=failure)
    with pytest.raises(authoring.LessonAuthoringFailure):
        stage(store, port)
    assert store.rows[0]["execution_outcome"] == "not_started"
    assert store.rows[0]["usage_status"] == "not_started"
    port.error = None
    with pytest.raises(authoring.LessonAuthoringFailure):
        stage(store, port)  # no blind same-run reset
    stage(store, port, run=run_record(run_id="explicit-successor"))
    assert len(port.requests) == 2


def test_legacy_run_cannot_enter_completion_stage(store):
    port = Author(store)
    with pytest.raises(ValueError, match="explicitly opted-in"):
        stage(store, port, run=run_record(completion_contract_version=None))
    assert not store.rows and not port.requests


def test_expired_worker_cannot_terminalize_known_result_for_reclaimer():
    run = run_record(lease_expires_at=NOW - timedelta(seconds=1))
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {**asdict(run), "id": run.run_id}
    with pytest.raises(LessonVersionConflict, match="Expired"):
        PostgresLessonDocumentRepository(conn).fail_authoring_run(run_id=run.run_id, lease_generation=1,
            failure_code="FIXTURE", failure_message="fixture", now=NOW)
    assert conn.execute.call_count == 1  # SELECT only; no stale terminal write


def test_live_worker_failure_after_result_commit_preserves_recovery():
    run = run_record()
    conn = Mock()
    conn.execute.side_effect = [Mock(fetchone=lambda: {**asdict(run), "id": run.run_id}),
        Mock(fetchone=lambda: {"id": "saved-result"})]
    with pytest.raises(LessonVersionConflict, match="reconciliation"):
        PostgresLessonDocumentRepository(conn).fail_authoring_run(run_id=run.run_id, lease_generation=1,
            failure_code="FIXTURE", failure_message="heartbeat lost after result COMMIT", now=NOW)
    assert conn.execute.call_count == 2
    assert all(call.args[0].startswith("SELECT") for call in conn.execute.call_args_list)


def test_dispatch_reuses_standard_and_targets_personal_changes_with_atomic_publish(monkeypatch, store):
    from app.core.config import Settings
    from app.services.llm.completion_policy import CompletionStagePolicy
    settings = SimpleNamespace(tutor_completion_driven_enabled=True, llm_provider_type="fixture", llm_model="fixture")
    monkeypatch.setattr(completion, "get_settings", lambda: settings)
    resolved = completion.resolve_completion_stage_policy(Settings(tutor_default_context_window_tokens=64_000, tutor_default_output_reserve_tokens=16_384), "lesson_authoring")
    assert resolved.context_capability is not None
    policy = CompletionStagePolicy("lesson_authoring", 12000, 600, resolved.context_capability)
    monkeypatch.setattr(completion, "resolve_completion_stage_policy", lambda *_: policy)
    monkeypatch.setattr(completion, "LessonLeaseHeartbeat", lambda *_: nullcontext(store))
    monkeypatch.setattr(completion, "resolve_catalog_knowledge_key", lambda *_args, **_kw: "python.variables")
    monkeypatch.setattr(authoring, "_load_evidence_snapshots", lambda *_args, **_kw: (snapshot(),))
    scope = [scope_record()]
    store.read_scope = lambda **_kw: scope[0]
    store.read_personalization_context = lambda _scope: {"mastery_level": scope[0].mastery_level, "learning_style": "examples"}
    store.read_lesson_state = lambda **_kw: {"document": None, "sources": ()}
    store.set_authoring_source_set = lambda **_kw: None
    store.read_prior_personalized_stage = lambda **kw: next((row for row in reversed(store.rows)
        if row["stage_kind"] == "personalized" and row["state"] == "accepted"
        and row["dependency_json"]["standard_dependency_hash"] == kw["standard_dependency_hash"]), None)
    publications = []

    def publish(**kwargs):
        assert kwargs["standard_quality"]["passed"] and kwargs["personalized_quality"]["passed"]
        assert store.rows[-1]["state"] == "accepted"
        assert kwargs["generator_version"].endswith(".completion1")
        publications.append(kwargs)

    store.publish_authoring_result = publish
    port = Author(store)
    completion.dispatch_completion_lesson(run=run_record(), author=port, clock=lambda: NOW)
    scope[0] = replace(scope[0], mastery_level="learning", mastery_confidence=0.4)
    completion.dispatch_completion_lesson(run=run_record(run_id="personal-refresh", profile_hash="c" * 64), author=port, clock=lambda: NOW)
    assert [req.document_kind for req in port.requests] == ["standard", "personalized", "personalized"]
    assert port.requests[-1].previous_personalized_document is not None
    assert "concept" in port.requests[-1].editable_block_ids and "gate" not in port.requests[-1].editable_block_ids
    assert dict(port.requests[-1].personal_preferences)["mastery_level"] == "learning"
    assert store.rows[0]["dependency_json"]["stage_policy"] == {
        **asdict(policy), "provider": "fixture", "model": "fixture",
    }
    assert len(publications) == 2


def test_heartbeat_uses_short_separate_connection_and_never_changes_sources(monkeypatch):
    from app.services.learning.lesson_completion_stages import LessonLeaseHeartbeat
    events = []
    conn = Mock()
    conn.transaction.return_value = nullcontext()
    repository = Mock()
    repository.heartbeat_authoring_run.return_value = True

    @contextmanager
    def connection():
        events.append("open")
        yield conn
        events.append("close")

    monkeypatch.setattr(completion, "connect", connection)
    monkeypatch.setattr(completion, "PostgresLessonDocumentRepository", lambda _: repository)
    heartbeat = LessonLeaseHeartbeat(run_record(), lambda: NOW)
    heartbeat.renew()
    assert events == ["open", "close"]
    assert repository.heartbeat_authoring_run.call_count == 1
    repository.evidence_is_current.assert_not_called()
    assert [call.args[0] for call in conn.execute.call_args_list] == ["SET LOCAL statement_timeout = '5s'", "SET LOCAL lock_timeout = '2s'"]
