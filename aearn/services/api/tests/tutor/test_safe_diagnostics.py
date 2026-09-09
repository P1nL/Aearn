"""Stage3 logging-only regressions; all dependencies are offline fakes."""
import io
import json
import logging
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.safe_diagnostics import log_safe_event, safe_diagnostic_identifier
from app.agents.harness.contracts import TutorCapabilityRequest, TutorDecision, TutorEffectProposal
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.services.learning import lesson_authoring as lesson
from app.services.tutor import interactive_worker as worker
from app.services.tutor.run_loop import _log_gate_denial
from tests.tutor.test_tutor_run_loop import _snapshot, _context


def events(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.getMessage().startswith('{')]


def test_message_formatter_keeps_fields_and_never_formats_secrets():
    stream = io.StringIO()
    logger = logging.Logger('isolated-stage3')
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    class Secret:
        def __str__(self):
            raise AssertionError('must not stringify payload')
    error = ValueError('SECRET provider body')
    error.__cause__ = RuntimeError('SECRET reasoning')
    log_safe_event(logger, 'runtime_metrics', exception=error, run_id='run-1',
                   visible_chars=32, reasoning_chars=90, effective_max_output_tokens=100,
                   effective_max_visible_chars=500, termination_reason='completed',
                   duration_ms=float('nan'), attempt=10**50, payload=Secret(),
                   code='https://SECRET/url', job_id=Secret(), extra={'secret': 'SECRET'})
    data = json.loads(stream.getvalue())
    assert data['run_id'] == 'run-1' and data['visible_chars'] == 32
    assert data['reasoning_chars'] == 90 and data['termination_reason'] == 'completed'
    assert data['exception_class'] == 'ValueError' and data['cause_class'] == 'RuntimeError'
    assert data['attempt'] == 1_000_000_000
    assert 'duration_ms' not in data and 'job_id' not in data
    assert 'SECRET' not in stream.getvalue() and len(stream.getvalue()) < 1500
    assert safe_diagnostic_identifier('x'*1000).startswith('sha256:')


@pytest.mark.parametrize('category,decision', [
    ('capability', TutorDecision(capability_requests=(TutorCapabilityRequest('req', 'SECRET_UNKNOWN'),))),
    ('effect', TutorDecision(effect_proposals=(TutorEffectProposal('effect', 'SECRET_UNKNOWN', 0),))),
])
def test_gate_denial_records_action_hash_catalog_revision_without_payload(caplog, category, decision):
    catalog = compile_published_skill_catalog()
    _log_gate_denial(_snapshot(), decision, 'skill_selection_required', _context(0),
                     SimpleNamespace(_catalog=catalog))
    data = events(caplog)[0]
    assert data['action_category'] == category and data['input_revision'] == 0
    assert data['catalog_digest'] == catalog.digest
    assert data['action_identifier'] == safe_diagnostic_identifier('SECRET_UNKNOWN', trusted=False)
    assert 'SECRET_UNKNOWN' not in caplog.text and data['field_path']


def lesson_fakes(monkeypatch, *, receipt_error=False):
    repository = Mock(unsafe=True)
    repository.evidence_is_current.return_value = True
    if receipt_error:
        repository.record_authoring_attempt.side_effect = OSError('SECRET receipt body')
    connection = SimpleNamespace(transaction=lambda: nullcontext())
    monkeypatch.setattr(lesson, 'connect', lambda: nullcontext(connection))
    monkeypatch.setattr(lesson, 'PostgresLessonDocumentRepository', lambda conn: repository)
    return repository


@pytest.mark.parametrize('receipt_error', [False, True])
def test_provider_reason_survives_receipt_failure_in_logs(monkeypatch, caplog, receipt_error):
    repo = lesson_fakes(monkeypatch, receipt_error=receipt_error)
    port = Mock()
    port.author.side_effect = TimeoutError('SECRET provider body reasoning')
    diagnostics = lesson._LessonDiagnostics()
    request = lesson.LessonAuthoringRequest('standard', 'python', 'variables', 'Title', 'Goal',
                                           'beginner', (), 'unseen', 0, ())
    with pytest.raises(OSError if receipt_error else lesson.LessonAuthoringFailure):
        lesson._author_and_validate(port=port, request=request, run=SimpleNamespace(run_id='lesson-1'),
                                    budget=lesson._RepairBudget(1), handles={}, snapshots=(), diagnostics=diagnostics)
    data = events(caplog)
    assert data[0]['stage'] == 'provider' and data[0]['exception_class'] == 'TimeoutError'
    if receipt_error:
        assert data[1]['stage'] == 'receipt' and data[1]['primary_stage'] == 'provider'
        assert data[1]['primary_code'] == 'LESSON_DOCUMENT_GENERATION_UNAVAILABLE'
    assert port.author.call_count == 1 and repo.record_authoring_attempt.call_count == 1
    assert 'SECRET' not in caplog.text


def test_validation_logs_original_class_and_preserves_mapping(monkeypatch, caplog):
    lesson_fakes(monkeypatch)
    monkeypatch.setattr(lesson, '_parse_author_candidate', Mock(side_effect=TypeError('SECRET value')))
    port = Mock()
    port.author.return_value = lesson.LessonAuthoringResponse({}, 'fake', 'fake', 'fake')
    request = lesson.LessonAuthoringRequest('standard', 'python', 'variables', 'Title', 'Goal',
                                           'beginner', (), 'unseen', 0, ())
    with pytest.raises(lesson.LessonAuthoringFailure) as caught:
        lesson._author_and_validate(port=port, request=request, run=SimpleNamespace(run_id='lesson-1'),
                                    budget=lesson._RepairBudget(1), handles={}, snapshots=())
    assert caught.value.code == 'LESSON_DOCUMENT_GENERATION_UNAVAILABLE'
    assert events(caplog)[0]['stage'] == 'validation'
    assert events(caplog)[0]['exception_class'] == 'TypeError'
    assert 'SECRET' not in caplog.text


def test_failure_receipt_is_not_silent(monkeypatch, caplog):
    repo = lesson_fakes(monkeypatch)
    repo.read_authoring_run.side_effect = OSError('SECRET database')
    lesson._safe_fail('lesson-1', None, 'LESSON_SOURCE_EVIDENCE_INSUFFICIENT', 'safe', None,
                     diagnostics=lesson._LessonDiagnostics(stage='source'), exception=ValueError('SECRET'))
    data = events(caplog)
    assert data[0]['stage'] == 'source'
    assert data[1]['stage'] == 'receipt'
    assert data[1]['primary_code'] == 'LESSON_SOURCE_EVIDENCE_INSUFFICIENT'
    assert 'SECRET' not in caplog.text


def test_dispatch_logs_exception_before_retry_write_can_fail(monkeypatch, caplog):
    connection = object()
    monkeypatch.setattr(worker, 'connect', lambda: nullcontext(connection))
    monkeypatch.setattr(worker, 'TutorThreadTurnCutoverService', lambda conn: Mock(unsafe=True))
    repo = Mock()
    repo.claim_interactive_dispatch_jobs.return_value = [SimpleNamespace(
        user_id='user-1', run_id='run-1', job_id='job-1', lease_generation=1, attempt_count=1)]
    repo.retry_interactive_dispatch_job.side_effect = OSError('SECRET receipt')
    monkeypatch.setattr(worker, 'PostgresTutorRepository', lambda conn: repo)
    dispatcher = Mock()
    dispatcher.dispatch.side_effect = LookupError('SECRET provider')
    instance = worker.TutorInteractiveWorker(dispatcher=dispatcher)
    with pytest.raises(OSError):
        instance.dispatch_job(job_id='job-1')
    data = events(caplog)[0]
    assert data['stage'] == 'dispatch' and data['exception_class'] == 'LookupError'
    assert data['job_id'] == 'job-1' and data['code'] == 'dispatch_failed'
    assert 'SECRET' not in caplog.text


@pytest.mark.parametrize('stage', ['source', 'publish'])
def test_outer_failure_retains_actual_stage_and_public_mapping(monkeypatch, caplog, stage):
    repo = lesson_fakes(monkeypatch)
    run = SimpleNamespace(run_id='lesson-1', user_id='user-1', track_id='track-1',
                          knowledge_key='python.variables', lease_generation=1, attempt_count=1)
    repo.claim_authoring_run.return_value = run
    repo.mark_authoring_running.return_value = run
    repo.read_authoring_run.return_value = SimpleNamespace(state='running', lease_generation=1)
    if stage == 'source':
        repo.read_scope.side_effect = ValueError('SECRET source')
    else:
        repo.read_scope.return_value = SimpleNamespace(language_id='python', knowledge_key='python.variables',
            node_title='Title', goal_text='Goal', target_level='beginner', required_capabilities=(),
            mastery_level='unseen', mastery_confidence=0)
        repo.read_lesson_state.return_value = {}
        monkeypatch.setattr(lesson, '_load_evidence_snapshots', lambda *args: (SimpleNamespace(source_id='source'),))
        monkeypatch.setattr(lesson, 'canonical_source_set_hash', lambda snapshots: 'hash')
        monkeypatch.setattr(lesson, '_authoring_evidence', lambda snapshots: ((), {}))
        monkeypatch.setattr(lesson, '_author_and_validate', lambda **kwargs: (Mock(), Mock()))
        monkeypatch.setattr(lesson, 'calculate_lesson_impact', lambda *args, **kwargs: Mock())
        repo.publish_authoring_result.side_effect = ValueError('SECRET publish')
    lesson.dispatch_lesson_authoring_run('lesson-1', author=Mock())
    data = events(caplog)[0]
    assert data['stage'] == stage and data['exception_class'] == 'ValueError'
    assert repo.fail_authoring_run.call_args.kwargs['failure_code'] == 'LESSON_DOCUMENT_INVALID'
    assert 'SECRET' not in caplog.text


def test_plain_file_handler_persists_structured_event(tmp_path):
    path = tmp_path / 'stage3.log'
    logger = logging.Logger('stage3-file')
    handler = logging.FileHandler(path, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    try:
        log_safe_event(logger, 'lesson_receipt_failed', stage='receipt', run_id='run-1',
                       exception=OSError('SECRET'), primary_code='LESSON_DOCUMENT_INVALID')
    finally:
        handler.close()
    text = path.read_text(encoding='utf-8')
    assert json.loads(text)['primary_code'] == 'LESSON_DOCUMENT_INVALID'
    assert 'SECRET' not in text



def test_decorated_gate_retains_frozen_catalog_and_selected_skill(caplog):
    from dataclasses import replace
    from app.agents.harness.contracts import TutorContextSource
    catalog = compile_published_skill_catalog()
    context = replace(_context(0), system_descriptors=(TutorContextSource(
        'catalog:selected:tutor.registry-grounding@1.0.0', {'instruction': 'SECRET instruction'}),))
    decision = TutorDecision(capability_requests=(TutorCapabilityRequest('req', 'grounding.retrieve'),))
    gate = SimpleNamespace(_base=SimpleNamespace(_catalog=catalog))
    _log_gate_denial(_snapshot(), decision, 'capability_arguments_invalid', context, gate)
    data = events(caplog)[0]
    assert data['catalog_digest'] == catalog.digest
    assert data['skill_reference'] == 'tutor.registry-grounding@1.0.0'
    assert data['action_identifier'] == 'grounding.retrieve'
    assert 'SECRET' not in caplog.text
