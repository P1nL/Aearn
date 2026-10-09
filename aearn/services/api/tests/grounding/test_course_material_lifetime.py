"""Three offline protocol checks: stub seals are NOT live OS/source acceptance."""
from __future__ import annotations

import hashlib
from html import escape
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aearn_shared.execution import SandboxResultV1
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.grounding.autonomous import public_python_teaching_review as teaching
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, SubjectScope
from app.services.grounding.autonomous.material_lifetime import (
    COURSE_MATERIAL_POLICY, LEGACY_MATERIAL_POLICY, new_material_expiry,
)
from app.services.grounding.autonomous.public_python_teaching_profile import (
    AUTHORS, GROUPS, LICENSE_URL, URL, TeachingAttribution, analyze_teaching, teaching_request,
)
from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from app.services.grounding.autonomous.source_assessment_profiles import (
    COURSE_DOMAIN, DOMAIN, PYTHON_BINDING, PYTHON_RHS, PYTHON_STATEMENTS_URL,
    SourceAssessmentDenied, SourceAssessmentPayload,
    canonical_source_payload, run_source_assessment,
    sign_source_assessment, source_request, verify_source_assessment,
)
from app.services.grounding.autonomous.source_review_repository import CompleteCapture, SourceReviewRepository
from app.services.grounding.public_course_contracts import public_course_demand
from app.services.learning.item_bank.contracts import canonical_hash

NOW = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)


class ProtocolStub:
    """Tests only; no network, Docker, DB, key files or executed source."""
    def __init__(self, expected):
        self.expected = expected
        self.receipt = None

    def run(self, *, request, run_id, probe_name):
        result = SandboxResultV1.model_validate({"status": "success", "stdout": json.dumps(self.expected),
                                               "diagnostic_code": "item_supply_facts_v1"})
        payload = {"schema_version": "item_supply_runner_terminal_v1", "run_id": str(run_id),
                   "probe_name": probe_name, "request_hash": canonical_hash(request.model_dump(mode="json")),
                   "lock_fingerprint": "3" * 64, "result": result.model_dump(mode="json"),
                   "elapsed_seconds": 0.1, "mode": "live", "isolation": "approved_os_boundary", "seal": "offline-stub"}
        self.receipt = SimpleNamespace(**{**payload, "result": result, "run_id": run_id})
        self.receipt.to_payload = lambda: payload.copy()
        return self.receipt

    def verify(self, receipt, *, request):
        return receipt is self.receipt and receipt.request_hash == canonical_hash(request.model_dump(mode="json"))


def test_new_policy_caps_each_permission_and_never_renews_expired_bound():
    bounds = dict(policy_expires_at=NOW + timedelta(days=9), policy_retention_until=NOW + timedelta(days=9),
                  capture_retention_until=NOW + timedelta(days=9), delegation_expires_at=NOW + timedelta(days=9),
                  period_end=NOW + timedelta(days=9))
    assert new_material_expiry(now=NOW, policy=COURSE_MATERIAL_POLICY, **bounds) == NOW + timedelta(days=7)
    assert new_material_expiry(now=NOW, policy=LEGACY_MATERIAL_POLICY, **bounds) == NOW + timedelta(hours=24)
    for field in bounds:
        shorter = {**bounds, field: NOW + timedelta(hours=6)}
        assert new_material_expiry(now=NOW, policy=COURSE_MATERIAL_POLICY, **shorter) == shorter[field]
        for expired in (NOW, NOW - timedelta(days=2)):
            with pytest.raises(ValueError, match="permission expired"):
                new_material_expiry(now=NOW, policy=COURSE_MATERIAL_POLICY, **{**bounds, field: expired})
    with pytest.raises(ValueError, match="aware deadlines"):
        new_material_expiry(now=NOW, policy=COURSE_MATERIAL_POLICY,
                            **{**bounds, "period_end": NOW.replace(tzinfo=None)})


def test_lifetime_migration_requires_final_488_guard_and_accepts_only_exact_replay():
    # Offline source-contract regression only; main must still execute real DDL.
    from pathlib import Path
    import re

    schema = Path(__file__).resolve().parents[2] / "app" / "db" / "schema"
    migration = (schema / "497_rag_course_material_lifetime.sql").read_text(encoding="utf-8")
    expected = re.search(r"expected_guard_md5 constant text := '([0-9a-f]{32})'", migration).group(1)
    marker = "(proof->>'format') IS DISTINCT FROM 'aearn.rag.fresh-assessment-source.v1'"
    injected = ("rag_course_material_proof_lifetime_allowed(NEW.signed_proof,NEW.profile_id,"
                "NEW.issued_at,NEW.expires_at) IS DISTINCT FROM true")

    def body(filename):
        sql = (schema / filename).read_text(encoding="utf-8")
        return re.search(r"CREATE OR REPLACE FUNCTION rag_assessment_source_evidence_guard\(\) "
                         r"RETURNS trigger LANGUAGE plpgsql AS \$\$([\s\S]*?)\$\$;", sql).group(1)

    def accepted(value):
        normalized = value.replace(injected, marker).replace("\r", "")
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest() == expected

    current = body("488_rag_public_sqlite_course_source.sql")
    patched = current.replace(marker, injected)
    assert current.count(marker) == 1 and patched.count(injected) == 1
    assert accepted(current) and accepted(patched) and accepted(patched.replace("\n", "\r\n"))
    # The former marker-only gate accepted both incomplete historical bodies.
    for old in ("480_rag_assessment_execution_authority.sql", "486_rag_public_python_course_source.sql"):
        old_body = body(old)
        assert marker in old_body and not accepted(old_body)
    assert not accepted(patched.replace("companion_root.enabled IS NOT TRUE OR", ""))
    assert "md5(replace(replace(guard_body,injected,marker), E'\\r', '')) IS DISTINCT FROM expected_guard_md5" in migration
    assert migration.index("497 requires exact final 488 source guard") < migration.index(
        "CREATE OR REPLACE FUNCTION rag_course_material_proof_lifetime_allowed")


def test_course_assessment_new_domain_default_and_original_v1_signature_bytes(monkeypatch):
    demand = public_course_demand("python-kc-binding-v1")
    body = ("<html><body><p>" + escape(PYTHON_BINDING) + "</p><p>" + escape(PYTHON_RHS) + "</p></body></html>").encode()
    document_hash = hashlib.sha256(body).hexdigest()
    capture = CompleteCapture(uuid4(), "registered", body, document_hash, document_hash, demand.scope,
                              "source.test", PYTHON_STATEMENTS_URL, (PYTHON_STATEMENTS_URL,), "official", "beginner", "PSF-2.0")
    policy = dict(root_id="root.test", allowed_usages=["assessment_evidence"], immutable_history_allowed=True,
                  expires_at=NOW + timedelta(days=9), policy_retention=NOW + timedelta(days=9),
                  retention_until=NOW + timedelta(days=8), policy_id="policy.test", policy_generation=1,
                  storage_receipt_id="store.test")
    root = dict(root_id="root.test", delegation_id="delegation.test", delegation_generation=1,
                delegation_expires_at=NOW + timedelta(days=8), period_end=NOW + timedelta(days=8))
    conn = SimpleNamespace(execute=lambda *_a: SimpleNamespace(fetchone=lambda: root))
    provenance = object.__new__(PostgresCurrentCaptureProvenanceResolver)
    provenance.conn = conn
    monkeypatch.setattr(PostgresCurrentCaptureProvenanceResolver, "resolve", lambda *_a: "2" * 64)
    monkeypatch.setattr(SourceReviewRepository, "_capture", lambda *_a: (capture, policy))
    repo = AssessmentReceiptRepository(conn, service_keys={"service.test": b"x" * 32}, provenance=provenance, enabled=True)
    monkeypatch.setattr(repo, "require_transaction", lambda: None)
    monkeypatch.setattr(repo, "_clock", lambda: NOW)
    prepared = repo.prepare(capture_id=capture.capture_id, document_handle="document.test", demand=demand,
                            profile_id="python-binding-source-v1")
    assert prepared.authority_expires_at == NOW + timedelta(days=7)
    _, expected, _ = source_request(prepared.profile_id)
    runner = ProtocolStub(expected)
    run = run_source_assessment(prepared, runner=runner, run_id=uuid4())
    key = Ed25519PrivateKey.generate()
    signed = sign_source_assessment(run, runner=runner, service_key_id="service.test", private_key=key, now=NOW)
    pins = {"service.test": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    assert signed.payload.format == "aearn.rag.fresh-assessment-source.v2"
    assert signed.payload.expires_at == NOW + timedelta(days=7)
    assert canonical_source_payload(signed.payload).startswith(COURSE_DOMAIN)
    assert verify_source_assessment(signed, service_keys=pins, now=NOW + timedelta(days=6)) == signed.payload
    repo.service_keys = pins
    assert repo._verify_current(signed)[0] == signed.payload
    policy["retention_until"] = NOW + timedelta(hours=6)
    with pytest.raises(SourceAssessmentDenied, match="AUTHORITY_STALE"):
        repo._verify_current(signed)
    with pytest.raises(SourceAssessmentDenied, match="PROOF_DENIED"):
        verify_source_assessment(signed, service_keys=pins, now=signed.payload.expires_at)
    with pytest.raises(ValueError):
        SourceAssessmentPayload.model_validate(signed.payload.model_copy(update={"expires_at": NOW + timedelta(days=8)}).model_dump())
    # A legitimate legacy receipt retains exact historical canonical bytes/domain.
    legacy = sign_source_assessment(run, runner=runner, service_key_id="service.test", private_key=key, now=NOW,
                                    expires_at=NOW + timedelta(hours=6), lifetime_policy=LEGACY_MATERIAL_POLICY)
    old_bytes = DOMAIN + json.dumps(legacy.payload.model_dump(mode="json"), sort_keys=True,
                                   separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    assert canonical_source_payload(legacy.payload) == old_bytes
    assert verify_source_assessment(legacy, service_keys=pins, now=NOW + timedelta(hours=1)) == legacy.payload
    # Relabeling an old signature is not a new issuance.
    with pytest.raises(SourceAssessmentDenied, match="PROOF_DENIED"):
        verify_source_assessment(legacy.model_copy(update={"payload": legacy.payload.model_copy(
            update={"format": "aearn.rag.fresh-assessment-source.v2"})}), service_keys=pins, now=NOW)
    legacy_demand = LearningMaterialDemand(scope=demand.scope, demand_hash="1" * 64, plan_ref="draft.test",
        node_ref="node.test", draft_revision=1, purpose="assessment_evidence", reading_level="beginner", language="en")
    # New course policy never authorizes unrelated legacy sum/print source profiles.
    with pytest.raises(SourceAssessmentDenied, match="LIFETIME_SCOPE_DENIED"):
        repo.prepare(capture_id=capture.capture_id, document_handle="document.other", demand=legacy_demand,
                     profile_id="python-sum-print-source-v2", lifetime_policy=COURSE_MATERIAL_POLICY)


def test_teaching_new_issuance_and_legacy_domain_keep_shorter_current_permissions(monkeypatch):
    code = "\n\n".join(escape(group) for group in GROUPS.values())
    body = ('<html><body><pre lang="python">' + code + '</pre><footer><a rel="license" href="' + LICENSE_URL
            + '">CC BY-SA 3.0</a><p>' + ', '.join(AUTHORS) + '</p></footer></body></html>').encode()
    document_hash = hashlib.sha256(body).hexdigest()
    capture = CompleteCapture(uuid4(), "registered", body, document_hash, document_hash,
        SubjectScope(subject_id="route.python", subject_version="1.0", facets=("fundamentals",)),
        "source.test", URL, (URL,), "tutorial", "beginner", "cc-by-sa-3.0")
    policy = dict(root_id="root.test", allowed_usages=["main_teaching"], immutable_history_allowed=True,
                  expires_at=NOW + timedelta(days=9), policy_retention=NOW + timedelta(days=8),
                  retention_until=NOW + timedelta(days=8), policy_id="policy.test", policy_generation=1)
    root = dict(delegation_expires_at=NOW + timedelta(days=8), period_end=NOW + timedelta(days=8))
    conn = SimpleNamespace(execute=lambda *_a: SimpleNamespace(fetchone=lambda: root))
    provenance = object.__new__(PostgresCurrentCaptureProvenanceResolver)
    provenance.conn = conn
    monkeypatch.setattr(PostgresCurrentCaptureProvenanceResolver, "resolve", lambda *_a: "2" * 64)
    monkeypatch.setattr(SourceReviewRepository, "_capture", lambda *_a: (capture, policy))
    monkeypatch.setattr(teaching, "_clock", lambda *_a: NOW)
    prepared = teaching.prepare_teaching(conn, capture_id=capture.capture_id, provenance=provenance, enabled=True)
    assert prepared.authority_expires_at == NOW + timedelta(days=7)
    assert prepared.excerpts == analyze_teaching(capture) and prepared.attribution == TeachingAttribution()
    _, expected = teaching_request()
    runner = ProtocolStub(expected)
    terminal = teaching.run_teaching(prepared, runner=runner, run_id=uuid4())
    key = Ed25519PrivateKey.generate()
    signed = teaching.sign_teaching(prepared, terminal, runner=runner, private_key=key, service_key_id="service.test", now=NOW)
    assert signed.payload.format == "aearn.public-python-teaching.v2"
    key.public_key().verify(bytes.fromhex(signed.signature_hex), teaching._canonical(signed.payload))
    pins = {"service.test": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    verifier = teaching.PublicPythonTeachingVerifier(conn, review=signed, service_keys=pins, provenance=provenance, enabled=True)
    assert verifier.reviewed_usages(capture) == ("main_teaching",)
    policy["retention_until"] = NOW + timedelta(hours=6)
    assert verifier.reviewed_usages(capture) == ()
    short = teaching.prepare_teaching(conn, capture_id=capture.capture_id, provenance=provenance, enabled=True)
    assert short.authority_expires_at == NOW + timedelta(hours=6)
    old = teaching.prepare_teaching(conn, capture_id=capture.capture_id, provenance=provenance, enabled=True,
                                    lifetime_policy=LEGACY_MATERIAL_POLICY)
    legacy = teaching.sign_teaching(old, terminal, runner=runner, private_key=key, service_key_id="service.test", now=NOW)
    old_bytes = teaching.DOMAIN + json.dumps(legacy.payload.model_dump(mode="json"), sort_keys=True,
                                           separators=(",", ":"), ensure_ascii=False).encode()
    assert teaching._canonical(legacy.payload) == old_bytes
    key.public_key().verify(bytes.fromhex(legacy.signature_hex), old_bytes)
    legacy_verifier = teaching.PublicPythonTeachingVerifier(conn, review=legacy, service_keys=pins, provenance=provenance, enabled=True)
    assert legacy_verifier.reviewed_usages(capture) == ("main_teaching",)
    with pytest.raises(InvalidSignature):
        key.public_key().verify(bytes.fromhex(signed.signature_hex), old_bytes)
    policy["retention_until"] = NOW - timedelta(days=2)
    assert verifier.reviewed_usages(capture) == () and legacy_verifier.reviewed_usages(capture) == ()
