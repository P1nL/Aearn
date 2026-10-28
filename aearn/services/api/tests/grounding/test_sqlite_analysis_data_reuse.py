"""Finite parser reuse over real CPU analyzers/signatures; never live authority."""
from copy import copy
from dataclasses import replace
from datetime import timedelta
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.grounding.autonomous import sqlite_predicate_source_profile as profile
from app.services.grounding.autonomous.source_assessment_profiles import (
    SourceAssessmentDenied, run_source_assessment, sign_source_assessment, source_request,
)
from app.services.grounding.public_course_contracts import public_course_demand
from tests.learning.test_item_supply_public_sqlite_source import (
    NOW, PROFILE, TARGET, _captures, _NativeProtocolOnlyRunner, _repository,
)


def counted_analyzer(monkeypatch):
    calls = []
    cold = profile.analyze_sqlite_capture

    def analyze(capture, role):
        calls.append((capture.capture_id, role))
        return cold(capture, role)

    monkeypatch.setattr(profile, "analyze_sqlite_capture", analyze)
    return calls


def signed_sqlite(monkeypatch):
    captures = _captures()
    repo, visits, pins = _repository(monkeypatch, captures)
    prepared = repo.prepare(capture_id=captures["select"].capture_id, document_handle="document.sqlite-native",
        demand=public_course_demand(TARGET), profile_id=PROFILE,
        companion_capture_ids=(captures["expression"].capture_id, captures["corefunc"].capture_id))
    # Existing CPU terminal double, not an executor/provider/source request.
    runner = _NativeProtocolOnlyRunner()
    run = run_source_assessment(prepared, runner=runner, run_id=uuid4())
    key = Ed25519PrivateKey.generate()
    signed = sign_source_assessment(run, runner=runner, service_key_id="service.test", private_key=key,
        now=NOW + timedelta(seconds=3), expires_at=NOW + timedelta(minutes=30))
    repo.service_keys = {"service.test": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    monkeypatch.setattr(repo, "_clock", lambda: NOW + timedelta(seconds=4))
    return repo, captures, signed, visits, pins


def test_primitive_spans_are_rebuilt_and_full_utf8_bytes_are_retained(monkeypatch):
    capture = _captures()["select"]
    body = capture.body.replace(b"<body>", "<body><p>教学</p>".encode())
    digest = hashlib.sha256(body).hexdigest()
    capture = replace(capture, body=body, digest=digest, revision=digest)
    expected = profile.analyze_sqlite_capture(capture, "select")
    calls = counted_analyzer(monkeypatch)
    data = profile._SQLiteAnalysisData()
    first = data.analyze(capture, "select")
    assert first == expected
    first[0].__dict__["start_byte"] += 1  # Deliberately evade frozen DTO setters.
    second = data.analyze(capture, "select")
    assert second == expected and second[0] is not first[0]
    assert len(calls) == 1
    for span in second:
        assert hashlib.sha256(body[span.start_byte:span.end_byte]).hexdigest() == span.sha256
    assert all(type(v) in (str, int) for _, spans in data._entries.values() for s in spans for v in s)
    data.close()
    assert not data._entries
    assert data.analyze(capture, "select") == expected
    assert data.analyze(capture, "select") == expected
    assert len(calls) == 3 and not data._entries


@pytest.mark.parametrize("change", ["body", "revision", "role", "url", "chain", "subject", "facets"])
def test_same_id_or_claimed_digest_never_reuses_changed_input(monkeypatch, change):
    capture = _captures()["select"]
    calls = counted_analyzer(monkeypatch)
    data = profile._SQLiteAnalysisData()
    data.analyze(capture, "select")
    altered, role = capture, "select"
    if change == "body":
        altered = replace(capture, body=capture.body.replace(b"WHERE", b"WHERX", 1))
    elif change == "revision":
        altered = replace(capture, revision="a" * 64)
    elif change == "role":
        role = "expression"
    elif change == "url":
        altered = replace(capture, final_url=profile.SQLITE_EXPRESSION_URL)
    elif change == "chain":
        altered = replace(capture, request_chain=(capture.final_url, capture.final_url))
    elif change == "subject":
        altered = replace(capture, scope=capture.scope.model_copy(update={"subject_version": "2.0"}))
    else:
        altered = replace(capture, scope=capture.scope.model_copy(update={"facets": ("schema",)}))
    with pytest.raises(SourceAssessmentDenied):
        data.analyze(altered, role)
    assert len(calls) == 2 and not data._entries
    # Catch + restore cannot revive the earlier parse inside this operation.
    data.analyze(capture, "select")
    data.analyze(capture, "select")
    assert len(calls) == 4 and not data._entries


def test_all_non_authority_metadata_and_rules_are_part_of_parse_identity(monkeypatch):
    capture = _captures()["select"]
    calls = counted_analyzer(monkeypatch)
    data = profile._SQLiteAnalysisData()
    data.analyze(capture, "select")
    for field, value in (("source_handle", "source.changed"), ("reading_level", "advanced"), ("license_id", "other-license")):
        capture = replace(capture, **{field: value})
        assert data.analyze(capture, "select") == profile.analyze_sqlite_capture(capture, "select")
    assert len(calls) == 7  # Each input was cold, plus independent comparisons.
    rules = dict(profile.SQLITE_ASSERTIONS["select"])
    rules["claim.where"] = ("A different complete assertion.",)
    monkeypatch.setitem(profile.SQLITE_ASSERTIONS, "select", rules)
    with pytest.raises(SourceAssessmentDenied, match="ASSERTIONS_UNSUPPORTED"):
        data.analyze(capture, "select")
    assert len(calls) == 8


def test_parser_implementation_identity_change_requires_cold_analysis(monkeypatch):
    capture = _captures()["select"]
    calls = counted_analyzer(monkeypatch)
    data = profile._SQLiteAnalysisData()
    expected = data.analyze(capture, "select")
    finish = profile._SQLiteUnits._finish_unit

    def finish_unit(parser):
        return finish(parser)

    monkeypatch.setattr(profile._SQLiteUnits, "_finish_unit", finish_unit)
    assert data.analyze(capture, "select") == expected
    assert len(calls) == 2


def test_only_three_slots_and_no_arbitrary_capture_table(monkeypatch):
    captures = _captures()
    calls = counted_analyzer(monkeypatch)
    data = profile._SQLiteAnalysisData()
    for role, capture in captures.items():
        data.analyze(capture, role)
    extra = replace(captures["select"], capture_id=uuid4())
    data.analyze(extra, "select")
    data.analyze(extra, "select")
    assert len(data._entries) == 3 and len(calls) == 5


def test_signed_repository_repeats_current_provenance_and_closes_each_operation(monkeypatch):
    repo, captures, signed, visits, pins = signed_sqlite(monkeypatch)
    calls = counted_analyzer(monkeypatch)
    expected = repo._verify_current(signed)
    assert len(calls) == 3
    calls.clear()
    visits.clear()
    for _ in range(2):
        with repo._sqlite_analysis_scope():
            for _ in range(4):
                assert repo._verify_current(signed) == expected
        assert repo._sqlite_analysis is None
    assert len(calls) == 6 and len(visits) == 24
    with pytest.raises(SourceAssessmentDenied, match="AUTHORITY_DENIED"):
        with repo._sqlite_analysis_scope():
            assert repo._verify_current(signed) == expected
            pins[captures["corefunc"].capture_id].expected_capture = None
            repo._verify_current(signed)
    assert repo._sqlite_analysis is None
    pins[captures["corefunc"].capture_id].expected_capture = captures["corefunc"]
    with repo._sqlite_analysis_scope():
        assert repo._verify_current(signed) == expected
    assert len(calls) == 12  # Failed scope did not seed the next operation.


def test_repository_connection_and_instance_cannot_share_data(monkeypatch):
    repo, captures, _, _, _ = signed_sqlite(monkeypatch)
    other, _, _ = _repository(monkeypatch, captures)
    calls = counted_analyzer(monkeypatch)
    capture = captures["select"]
    with repo._sqlite_analysis_scope():
        a = repo._sqlite_analysis_data()
        a.analyze(capture, "select")
        with other._sqlite_analysis_scope():
            b = other._sqlite_analysis_data()
            b.analyze(capture, "select")
            assert b is not a
        conn = repo.conn
        repo.conn = other.conn
        with pytest.raises(SourceAssessmentDenied, match="ANALYSIS_SCOPE_DENIED"):
            with repo._sqlite_analysis_scope():
                pytest.fail("A nested scope must reject a different connection")
        repo.conn = conn
        a.analyze(capture, "select")
        a.analyze(capture, "select")
        assert len(calls) == 4
    assert repo._sqlite_analysis is None and other._sqlite_analysis is None
    with repo._sqlite_analysis_scope():
        with pytest.raises(SourceAssessmentDenied, match="ANALYSIS_SCOPE_DENIED"):
            with copy(repo)._sqlite_analysis_scope():
                pytest.fail("A copied repository must not inherit the parent DATA")


@pytest.mark.parametrize("nested", [False, True])
def test_confirmed_authorize_reuses_parser_not_claims_prepared_or_final_current(monkeypatch, nested):
    from contextlib import nullcontext
    from app.services.grounding.assessment_course_adapter import ConfirmedAssessmentCourseReader
    from app.services.grounding.autonomous.assessment_contracts import ClaimEvidenceReceipt
    from app.services.grounding.autonomous.contracts import RagEvidenceBinding
    from app.services.grounding.current_authorization import AuthorizationReceipt, EvidenceDenied
    from app.services.learning.item_bank.contracts import canonical_hash

    repo, _, signed, visits, _ = signed_sqlite(monkeypatch)
    p, q = signed.payload, signed.payload.prepared
    claim = ClaimEvidenceReceipt(receipt_id=p.claim_handle, demand_hash=q.demand.demand_hash,
        purpose="assessment_evidence", admission_receipt_id=p.admission_handle, claim_hash=q.claim_hash,
        scope=q.demand.scope, source_handle=q.source_handle, document_handle=q.document_handle,
        document_revision=q.document_hash, document_hash=q.document_hash, applicability=source_request(q.profile_id)[2],
        method="isolated_execution", execution_receipt_id=p.execution_handle,
        execution_scope=q.execution_scope, verified=True, revoked=False)
    evidence = RagEvidenceBinding(scope=q.demand.scope, demand_hash=q.demand.demand_hash,
        purpose="assessment_evidence", source_handle=q.source_handle, document_handle=q.document_handle,
        document_revision=q.document_hash, document_hash=q.document_hash,
        admission_receipt_id=p.admission_handle, claim_receipt_id=p.claim_handle)
    coord = SimpleNamespace(binding=evidence, claim_id=p.claim_handle,
        claim_receipt_hash=canonical_hash(claim.model_dump(mode="json")),
        execution_receipt_id=p.execution_handle, corroboration_id=None)
    binding = SimpleNamespace(node_id="course.sqlite", goal_hash="a" * 64, evidence=(coord, coord))
    requirement = SimpleNamespace(node_id=binding.node_id, goal_hash=binding.goal_hash,
        demand=q.demand, prerequisites=())
    course = SimpleNamespace(binding=binding, selection=SimpleNamespace(requirements=(requirement,)),
        node=SimpleNamespace(prerequisite_keys=()))
    state = dict(final=True, trace=[])

    def find(handle):
        state["trace"].append("prepared")
        assert handle == p.claim_handle
        payload, capture = repo._verify_current(signed)
        return payload, capture, {"applicability": source_request(q.profile_id)[2]}

    def resolve(handle):
        state["trace"].append("claim")
        find(handle)
        return claim

    expected = AuthorizationReceipt("a" * 64, "assessment_evidence", str(uuid4()), 5,
        ((q.policy_id, q.policy_generation),), (p.admission_handle,), (), "b" * 64, ("queries",), repo._clock())

    def current(actual, purpose, *, request, exact_item_claims):
        state["trace"].append("final")
        assert actual is binding and purpose == "assessment_evidence"
        assert request.actor_id == q.consume_actor and request.budget == q.budget
        assert len(exact_item_claims) == 1 and exact_item_claims[0].claim_hash == q.claim_hash
        assert repo._verify_current(signed)[0] == p
        if not state["final"]:
            raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE")
        return expected

    # Only outer course/SQL boundaries are doubles. Every repeated prepared
    # source read executes the original public signature/current verifier.
    monkeypatch.setattr(repo, "_find", find)
    reader = object.__new__(ConfirmedAssessmentCourseReader)
    reader.conn, reader.receipts = repo.conn, repo
    reader.authority = SimpleNamespace(_claims=SimpleNamespace(resolve=resolve),
        _current=SimpleNamespace(check_current_authorization=current))

    def authorize():
        with repo._sqlite_analysis_scope() if nested else nullcontext():
            return reader.authorize(course, target_id=TARGET)

    calls = counted_analyzer(monkeypatch)
    visits.clear()
    with monkeypatch.context() as cold:
        cold.setattr(repo, "_sqlite_analysis_scope", lambda: nullcontext())
        assert authorize() == expected
    trace = tuple(state["trace"])
    assert len(calls) == len(visits) == 15
    state["trace"].clear()
    calls.clear()
    visits.clear()
    for _ in range(2):
        assert authorize() == expected
        assert repo._sqlite_analysis is None
    assert len(calls) == 6 and len(visits) == 30 and tuple(state["trace"]) == trace * 2
    state["final"] = False
    with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
        authorize()
    assert len(calls) == 9 and repo._sqlite_analysis is None
    state["final"] = True
    assert authorize() == expected
    assert len(calls) == 12


def test_nested_repository_scope_taints_parent_after_caught_failure(monkeypatch):
    repo, captures, _, _, _ = signed_sqlite(monkeypatch)
    calls = counted_analyzer(monkeypatch)
    capture = captures["select"]
    with repo._sqlite_analysis_scope(include_history=True):
        outer = repo._sqlite_analysis
        current = repo._sqlite_analysis_data()
        historical = repo._sqlite_analysis_data(historical=True)
        current.analyze(capture, "select")
        historical.analyze(capture, "select")
        with repo._sqlite_analysis_scope():
            assert repo._sqlite_analysis_data() is current
            assert repo._sqlite_analysis_data(historical=True) is historical
            current.analyze(capture, "select")
        assert repo._sqlite_analysis is outer and len(calls) == 2
        with pytest.raises(SourceAssessmentDenied, match="SOURCE_AUTHORITY_DENIED"):
            with repo._sqlite_analysis_scope():
                raise SourceAssessmentDenied("SOURCE_AUTHORITY_DENIED")
        assert repo._sqlite_analysis is outer
        for _ in range(2):
            current.analyze(capture, "select")
            historical.analyze(capture, "select")
        assert len(calls) == 6 and not current._entries and not historical._entries
    assert repo._sqlite_analysis is None
