"""Three focused protocol-only cases; fake seals/pins are NOT live acceptance."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aearn_shared.execution import SandboxResultV1
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.db.schema import SCHEMA_DIRECTORY, SCHEMA_FRAGMENT_NAMES
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
from app.services.grounding.autonomous.capture_provenance_composition import PinnedCaptureProvenanceComposition
from app.services.grounding.autonomous.finite_course_source_oracle import (
    public_course_execution_scope, public_course_source_request,
)
from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from app.services.grounding.autonomous.source_assessment_profiles import (
    DOMAIN, PreparedSourceAssessment, PreparedSQLiteSourceAssessment, SignedSourceAssessment,
    SourceAssessmentDenied, canonical_source_payload, run_source_assessment,
    sign_source_assessment, source_request, verify_source_assessment,
)
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
from app.services.grounding.autonomous.sqlite_predicate_source_profile import (
    SQLITE_ASSERTIONS, SQLITE_CAPTURE_URLS, analyze_sqlite_capture,
)
from app.services.grounding.public_course_contracts import public_course_demand
from app.services.learning.item_bank.contracts import canonical_hash
from tests.learning.test_item_supply_assessment_source import NOW, _capture, _signed

TARGET = "sqlite-predicate-order-v1"
PROFILE = "sqlite-predicate-source-v1"


def _captures():
    captures = {}
    for role, statements in SQLITE_ASSERTIONS.items():
        body = ("<html><body>" + "".join("<p>" + text[0] + "</p>" for text in statements.values())
                + "</body></html>").encode()
        digest = hashlib.sha256(body).hexdigest()
        url = SQLITE_CAPTURE_URLS[role]
        captures[role] = replace(_capture("sqlite-filter-order-source-v1"), body=body,
            digest=digest, revision=digest, scope=public_course_demand(TARGET).scope,
            source_handle="source." + role, final_url=url, request_chain=(url,))
    return captures


class _NativeProtocolOnlyRunner:
    def run(self, *, request, run_id, probe_name):
        _, expected, _ = public_course_source_request(TARGET)
        result = SandboxResultV1.model_validate(dict(status="success", stdout=json.dumps(expected),
                                                     diagnostic_code="item_supply_facts_v1"))
        r = SimpleNamespace(run_id=run_id, probe_name=probe_name,
            request_hash=canonical_hash(request.model_dump(mode="json")), lock_fingerprint="3" * 64,
            result=result, elapsed_seconds=0.2, mode="live", isolation="approved_os_boundary",
            seal="protocol-only-not-an-os-seal")
        r.to_payload = lambda: dict(schema_version="item_supply_runner_terminal_v1", run_id=str(run_id),
            probe_name=probe_name, request_hash=r.request_hash, lock_fingerprint=r.lock_fingerprint,
            result=result.model_dump(mode="json"), elapsed_seconds=r.elapsed_seconds, mode=r.mode,
            isolation=r.isolation, seal=r.seal)
        self.receipt = r
        return r

    def verify(self, receipt, *, request):
        return receipt is self.receipt and receipt.request_hash == canonical_hash(request.model_dump(mode="json"))


def _repository(monkeypatch, captures):
    roots, policies = {}, {}
    for role, capture in captures.items():
        expiry = NOW + timedelta(hours=1 if role == "select" else 2)
        policies[capture.capture_id] = dict(root_id="root." + role, policy_id="policy." + role,
            policy_generation=3 if role == "select" else 1, allowed_usages=["assessment_evidence"],
            immutable_history_allowed=True, expires_at=expiry, policy_retention=expiry,
            retention_until=expiry, storage_receipt_id="store." + role)
        roots["root." + role] = dict(root_id="root." + role, delegation_id="delegation." + role,
            delegation_generation=1, delegation_expires_at=expiry, period_end=expiry)
    conn = SimpleNamespace(execute=lambda sql, args: SimpleNamespace(fetchone=lambda: roots[args[0]]))
    pinned = {}
    for capture in captures.values():
        resolver = object.__new__(PostgresCurrentCaptureProvenanceResolver)
        resolver.conn = conn
        resolver.expected_capture = capture
        pinned[capture.capture_id] = resolver
    visited = []
    def resolve(self, capture):
        visited.append(capture.capture_id)
        return "2" * 64 if self.expected_capture == capture else None
    monkeypatch.setattr(PostgresCurrentCaptureProvenanceResolver, "resolve", resolve)
    by_id = {c.capture_id: c for c in captures.values()}
    monkeypatch.setattr(SourceReviewRepository, "_capture",
        lambda self, capture_id, lane, now: (by_id[capture_id], policies[capture_id]))
    composition = PinnedCaptureProvenanceComposition(conn, captures=pinned)
    repo = AssessmentReceiptRepository(conn, service_keys={"service.test": b"a" * 32},
                                        provenance=composition, enabled=True)
    monkeypatch.setattr(repo, "require_transaction", lambda: None)
    monkeypatch.setattr(repo, "_clock", lambda: NOW + timedelta(seconds=2))
    return repo, visited, pinned


def test_complete_exact_assertions_and_three_capture_contract_protocol_only(monkeypatch):
    captures = _captures()
    assert [len(analyze_sqlite_capture(c, role)) for role, c in captures.items()] == [5, 4, 1]
    assert source_request(PROFILE) == public_course_source_request(TARGET)
    repo, _, _ = _repository(monkeypatch, captures)
    ids = (captures["expression"].capture_id, captures["corefunc"].capture_id)
    q = repo.prepare(capture_id=captures["select"].capture_id, document_handle="document.sqlite-native",
                     demand=public_course_demand(TARGET), profile_id=PROFILE, companion_capture_ids=ids)
    assert type(q) is PreparedSQLiteSourceAssessment
    assert q.execution_scope == public_course_execution_scope(TARGET)
    assert q.consume_actor == "service.rag-public-course"
    assert q.authority_expires_at == NOW + timedelta(hours=1)
    assert "draft." not in q.model_dump_json()
    assert "consume_actor" not in q.model_dump()
    with pytest.raises(ValueError):
        PreparedSourceAssessment.model_validate(q.model_dump(exclude={"companions"}))
    with pytest.raises(SourceAssessmentDenied, match="SOURCE_COMPANIONS_REQUIRED"):
        repo.prepare(capture_id=q.capture_id, document_handle=q.document_handle,
                     demand=q.demand, profile_id=PROFILE)
    c = captures["corefunc"]
    body = c.body.replace(b"</p>", b" This is false.</p>")
    digest = hashlib.sha256(body).hexdigest()
    with pytest.raises(SourceAssessmentDenied, match="SOURCE_ASSERTIONS_UNSUPPORTED"):
        analyze_sqlite_capture(replace(c, body=body, digest=digest, revision=digest), "corefunc")


def test_signed_companions_are_rechecked_by_exact_current_pins_protocol_only(monkeypatch):
    captures = _captures()
    repo, visited, pinned = _repository(monkeypatch, captures)
    q = repo.prepare(capture_id=captures["select"].capture_id, document_handle="document.sqlite-native",
        demand=public_course_demand(TARGET), profile_id=PROFILE,
        companion_capture_ids=(captures["expression"].capture_id, captures["corefunc"].capture_id))
    runner = _NativeProtocolOnlyRunner()
    run = run_source_assessment(q, runner=runner, run_id=uuid4())
    key = Ed25519PrivateKey.generate()
    signed = sign_source_assessment(run, runner=runner, service_key_id="service.test", private_key=key,
        now=NOW + timedelta(seconds=3), expires_at=NOW + timedelta(minutes=30))
    repo.service_keys = {"service.test": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    monkeypatch.setattr(repo, "_clock", lambda: NOW + timedelta(seconds=4))
    roundtrip = SignedSourceAssessment.model_validate_json(signed.model_dump_json())
    assert roundtrip == signed
    assert type(roundtrip.payload.prepared) is PreparedSQLiteSourceAssessment
    visited.clear()
    assert repo._verify_current(roundtrip)[0].prepared.claim_hash == q.claim_hash
    assert visited == [c.capture_id for c in captures.values()]
    pinned[captures["corefunc"].capture_id].expected_capture = None
    with pytest.raises(SourceAssessmentDenied, match="SOURCE_AUTHORITY_DENIED"):
        repo._verify_current(roundtrip)
    # No fallback to SELECT's different verifier when the corefunc pin denies.
    assert visited[-1] == captures["corefunc"].capture_id
    assert repo.provenance.resolve(replace(captures["corefunc"], capture_id=uuid4())) is None


def test_historical_payload_bytes_and_closed_bootstrap_profile_contract():
    signed, pins = _signed()
    payload = verify_source_assessment(signed, service_keys=pins, now=NOW + timedelta(seconds=2))
    historical_shape = payload.model_dump(mode="json")
    assert "companions" not in historical_shape["prepared"]
    assert canonical_source_payload(payload) == DOMAIN + json.dumps(historical_shape, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    assert "488_rag_public_sqlite_course_source.sql" in SCHEMA_FRAGMENT_NAMES
    old = (SCHEMA_DIRECTORY / "486_rag_public_python_course_source.sql").read_text(encoding="utf-8")
    final = (SCHEMA_DIRECTORY / "488_rag_public_sqlite_course_source.sql").read_text(encoding="utf-8")
    assert ") NOT VALID;" in old
    assert "NOT VALID" not in final
    assert PROFILE in final
    assert public_course_demand(TARGET).demand_hash in final
    assert public_course_demand(TARGET).plan_ref in final
    assert "FOR companion_index IN 0..1" in final
