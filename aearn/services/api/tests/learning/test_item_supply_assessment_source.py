"""Focused pure source contracts. Stub terminals are NOT real OS acceptance."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aearn_shared.execution import SandboxResultV1
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.db.schema import SCHEMA_DIRECTORY, SCHEMA_FRAGMENT_NAMES
from app.services.grounding.assessment_material_factory import compose_assessment_authority
from app.services.grounding.autonomous.assessment_receipt_repository import (
    AssessmentReceiptRepository, PostgresAssessmentClaimResolver,
    PostgresAssessmentExecutionResolver,
)
from app.services.grounding.autonomous.contracts import (
    LearningMaterialDemand, RagBudgetDelegation, SubjectScope,
)
from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from app.services.grounding.autonomous.source_assessment_profiles import (
    PROFILE_IDS, PYTHON_CANONICAL_URL, PYTHON_PROFILE_IDS,
    PYTHON_PRINT_PARAGRAPH, PYTHON_SUM_PARAGRAPH, PYTHON_URL, SQLITE_ORDER,
    SQLITE_ORDER_PARAGRAPH, SQLITE_URL,
    PreparedSourceAssessment, SourceAssessmentDenied, analyze_source,
    run_source_assessment, sign_source_assessment, source_request, verify_source_assessment,
)
from app.services.grounding.autonomous.source_review_repository import (
    CompleteCapture, ReviewDenied, SourceReviewRepository,
)
from app.services.grounding.autonomous.sqlite_select_automated_review import WHERE_PARAGRAPH
from app.services.learning.item_bank.contracts import canonical_hash

NOW = datetime(2026,10,2,0,0,tzinfo=UTC)


def _capture(profile, *, quoted=False):
    python = profile in PYTHON_PROFILE_IDS
    sentences = (PYTHON_SUM_PARAGRAPH,PYTHON_PRINT_PARAGRAPH) if python else (WHERE_PARAGRAPH,SQLITE_ORDER_PARAGRAPH)
    content = "".join("<p>"+s+"</p>" for s in sentences)
    if quoted:
        content = "<blockquote>"+content+"</blockquote>"
    body = ("<html><body>"+content+"</body></html>").encode()
    url = (PYTHON_CANONICAL_URL if profile == "python-sum-print-source-v2" else PYTHON_URL) if python else SQLITE_URL
    digest = hashlib.sha256(body).hexdigest()
    scope = SubjectScope(subject_id="route.python" if python else "route.sql",subject_version="v1",
        facets=("fundamentals",) if python else ("queries",))
    return CompleteCapture(uuid4(),"registered",body,digest,digest,scope,"source.official",url,
        (url,),"official","beginner","PSF-2.0" if python else "Public-Domain")


def _prepared(profile):
    capture = _capture(profile)
    demand = LearningMaterialDemand(scope=capture.scope,demand_hash="1"*64,plan_ref="draft.source-test",
        node_ref="node.first",draft_revision=1,purpose="assessment_evidence",reading_level="beginner",language="en")
    return PreparedSourceAssessment(profile_id=profile,capture_id=capture.capture_id,
        source_handle=capture.source_handle,document_handle="document.source-test",document_hash=capture.digest,
        license_id=capture.license_id,reading_level="beginner",provenance_digest="2"*64,
        policy_id="policy.source-test",policy_generation=1,storage_receipt_id="store.source-test",
        budget=RagBudgetDelegation(root_id="root.source-test",delegation_id="delegation.source-test",
            generation=1,expires_at=NOW+timedelta(hours=1)),demand=demand,
        spans=analyze_source(capture,profile),prepared_at=NOW,authority_expires_at=NOW+timedelta(hours=1))


class _ProtocolStub:
    """Unit-only test double; never composed into actual source or corpus authority."""
    def __init__(self, *, mode="live", seal_valid=True, wrong=False):
        self.mode,self.seal_valid,self.wrong = mode,seal_valid,wrong
        self.receipt = None

    def run(self, *, request, run_id, probe_name):
        profile = PROFILE_IDS[0] if request.runtime_id == "python-stdout-v1" else PROFILE_IDS[1]
        _,expected,_ = source_request(profile)
        if self.wrong:
            expected = {"cases": []}
        result = SandboxResultV1.model_validate(dict(status="success",stdout=json.dumps(expected),
            diagnostic_code="item_supply_facts_v1"))
        receipt = SimpleNamespace(run_id=run_id,probe_name=probe_name,
            request_hash=canonical_hash(request.model_dump(mode="json")),lock_fingerprint="3"*64,
            result=result,elapsed_seconds=0.2,mode=self.mode,
            isolation="approved_os_boundary" if self.mode=="live" else "synthetic",seal="stub-seal")
        receipt.to_payload = lambda: dict(schema_version="item_supply_runner_terminal_v1",
            run_id=str(run_id),probe_name=probe_name,request_hash=receipt.request_hash,
            lock_fingerprint=receipt.lock_fingerprint,result=result.model_dump(mode="json"),
            elapsed_seconds=receipt.elapsed_seconds,mode=receipt.mode,isolation=receipt.isolation,seal=receipt.seal)
        self.receipt = receipt
        return receipt

    def verify(self, receipt, *, request):
        return (self.seal_valid and receipt is self.receipt
                and receipt.request_hash == canonical_hash(request.model_dump(mode="json")))


def _signed(profile=PROFILE_IDS[0]):
    runner = _ProtocolStub()
    run = run_source_assessment(_prepared(profile),runner=runner,run_id=uuid4())
    key = Ed25519PrivateKey.generate()
    signed = sign_source_assessment(run,runner=runner,service_key_id="service.source-test",private_key=key,
        now=NOW+timedelta(seconds=1),expires_at=NOW+timedelta(minutes=30))
    pins = {signed.service_key_id:key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)}
    return signed,pins


@pytest.mark.parametrize("profile",(PROFILE_IDS[0],PROFILE_IDS[1]))
def test_finite_source_contracts_and_signature(profile):
    signed,pins = _signed(profile)
    payload = verify_source_assessment(signed,service_keys=pins,now=NOW+timedelta(seconds=2))
    assert payload.prepared.claim_hash != payload.prepared.document_hash
    assert payload.prepared.execution_scope.runtime_profile in ("python-stdout-v1","sqlite-query-v1")
    assert len(payload.prepared.spans)==2
    assert payload.terminal["probe_name"]=="source_assessment_oracle"
    assert "candidate" not in payload.model_dump_json()


def test_pin_tamper_and_expiry_deny_without_renewal():
    signed,pins = _signed()
    for changed,keys,now in (
        (signed,{},NOW+timedelta(seconds=2)),
        (signed.model_copy(update={"signature_hex":"0"*128}),pins,NOW+timedelta(seconds=2)),
        (signed,pins,signed.payload.expires_at),
        (signed.model_copy(update={"payload":signed.payload.model_copy(update={
            "prepared":signed.payload.prepared.model_copy(update={"document_hash":"9"*64})})}),
         pins,NOW+timedelta(seconds=2)),
    ):
        with pytest.raises(SourceAssessmentDenied,match="SOURCE_PROOF_DENIED"):
            verify_source_assessment(changed,service_keys=keys,now=now)


def test_only_verified_seal_and_fixed_oracle_can_be_signed():
    for runner in (_ProtocolStub(mode="synthetic"),_ProtocolStub(seal_valid=False),_ProtocolStub(wrong=True)):
        with pytest.raises(SourceAssessmentDenied):
            run_source_assessment(_prepared(PROFILE_IDS[0]),runner=runner,run_id=uuid4())
    signed,_ = _signed()
    with pytest.raises(ValueError):
        signed.payload.model_copy(update={"expires_at":NOW+timedelta(days=2)}).__class__.model_validate(
            signed.payload.model_copy(update={"expires_at":NOW+timedelta(days=2)}).model_dump())


def test_url_and_quoted_snippets_do_not_become_body_authority():
    with pytest.raises(SourceAssessmentDenied):
        analyze_source(_capture(PROFILE_IDS[0],quoted=True),PROFILE_IDS[0])
    capture = _capture(PROFILE_IDS[0])
    from dataclasses import replace
    hostile = capture.body.replace(b"</p>", b" Warning: this is false.</p>", 1)
    with pytest.raises(SourceAssessmentDenied):
        analyze_source(replace(capture,body=hostile,digest=hashlib.sha256(hostile).hexdigest(),
            revision=hashlib.sha256(hostile).hexdigest()),PROFILE_IDS[0])
    for changed in (replace(capture,body=b"https://docs.python.org/3/library/functions.html"),
                    replace(capture,final_url=SQLITE_URL),replace(capture,revision="old")):
        with pytest.raises(SourceAssessmentDenied):
            analyze_source(changed,PROFILE_IDS[0])


def test_default_off_resolvers_and_factory_make_zero_queries():
    class Conn:
        autocommit = False
        info = SimpleNamespace(transaction_status=2)
        def execute(self,*args):
            pytest.fail("disabled authority queried database")
    conn = Conn()
    provenance = object.__new__(PostgresCurrentCaptureProvenanceResolver)
    provenance.conn = conn
    repo = AssessmentReceiptRepository(conn,service_keys={"service.test":b"a"*32},provenance=provenance)
    assert PostgresAssessmentClaimResolver(repo).resolve("source-claim."+"1"*32) is None
    assert PostgresAssessmentExecutionResolver(repo).resolve("source-execution."+"1"*32) is None
    with pytest.raises(SourceAssessmentDenied):
        compose_assessment_authority(conn,receipts=repo)


def test_capture_only_ambiguous_proofs_deny_and_source_uses_unique_capture_policy(monkeypatch):
    """Query-shape/chooser regression only; no DB, oracle, signing key or IO."""
    capture = _capture(PROFILE_IDS[0])
    proof_rows = [dict(id=uuid4(), document_handle="document.goal-a"),
                  dict(id=uuid4(), document_handle="document.goal-b")]
    queries = []

    class ProofCursor:
        def fetchall(self):
            return proof_rows

        def fetchone(self):
            pytest.fail("capture-only lookup picked an arbitrary demand proof")

    class PolicyCursor:
        def fetchone(self):
            return {"source_handle": "source.unique-capture-policy"}

    class Conn:
        def execute(self, sql, params):
            queries.append(sql)
            assert params == (capture.capture_id,)
            if "FROM rag_assessment_source_evidence" in sql:
                assert "WHERE capture_id=%s LIMIT 2 FOR SHARE" in sql
                assert "ORDER BY" not in sql
                return ProofCursor()
            assert "FROM rag_registered_source_captures c" in sql
            assert "JOIN rag_registered_source_policies p" in sql
            assert "p.policy_id=c.policy_id AND p.generation=c.generation" in sql
            assert "WHERE c.id=%s FOR SHARE OF c,p" in sql
            return PolicyCursor()

    repo = AssessmentReceiptRepository.__new__(AssessmentReceiptRepository)
    repo.conn = Conn()
    monkeypatch.setattr(repo, "require_transaction", lambda: None)
    monkeypatch.setattr(repo, "_load", lambda *_: pytest.fail("ambiguous proof reached signed-current owner"))
    finding = repo.verify(capture)
    assert finding.mode == "offline_protocol_only" and finding.evidence_hash == "0" * 64
    assert repo._document_for(capture.capture_id) == ""
    assert repo._capture_source(capture.capture_id) == "source.unique-capture-policy"
    assert len(queries) == 3


def test_legacy_excerpt_reviewer_cannot_upgrade_assessment():
    class Reviewer:
        def reviewed_usages(self,capture):
            return ("assessment_evidence",)
        def approved_excerpts(self,capture):
            return (WHERE_PARAGRAPH,SQLITE_ORDER)
    reviews = SourceReviewRepository(None,verifier=Reviewer())
    with pytest.raises(ReviewDenied,match="VERIFIER_SCOPE_DENIED"):
        reviews._verifier_scope(_capture(PROFILE_IDS[1]))


def test_additive_schema_keeps_legacy_denial_and_exact_database():
    fragment = "480_rag_assessment_execution_authority.sql"
    assert fragment in SCHEMA_FRAGMENT_NAMES
    sql = (SCHEMA_DIRECTORY/fragment).read_text(encoding="utf-8")
    old = (SCHEMA_DIRECTORY/"330_rag_source_admission.sql").read_text(encoding="utf-8")
    assert "isolated execution verifier unavailable" in old
    assert "current_database()<>'aearn_b1d_sandbox_20261001'" in sql
    assert "rag_assessment_source_evidence" in sql and "signed_proof" in sql
    assert "verified boolean" not in sql and "history_lease" not in sql
    assert "NEW.execution_receipt_handle IS DISTINCT FROM evidence.execution_handle" in sql


def test_assessment_capture_uniqueness_uses_frozen_demand_not_document_handle() -> None:
    fragment = "483_rag_assessment_demand_coordinates.sql"
    assert SCHEMA_FRAGMENT_NAMES[-1] == fragment
    sql = (SCHEMA_DIRECTORY / fragment).read_text(encoding="utf-8")
    assert sql.count("DROP CONSTRAINT") == 2
    assert "DROP CONSTRAINT IF EXISTS rag_assessment_source_evidence_capture_id_key;" in sql
    assert "IF NOT EXISTS (" in sql
    assert "conrelid = 'rag_assessment_source_evidence'::regclass" in sql
    assert "conname = 'rag_assessment_source_evidence_capture_demand_key'" in sql
    assert "ADD CONSTRAINT rag_assessment_source_evidence_capture_demand_key\n      UNIQUE (capture_id, demand_hash);" in sql
    assert "DROP CONSTRAINT IF EXISTS rag_source_reviews_registered_capture_id_key;" in sql
    assert ("CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_review_legacy_registered_capture\n"
            "  ON rag_source_reviews(registered_capture_id)\n"
            "  WHERE assessment_evidence_id IS NULL;") in sql
    assert ("CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_review_registered_capture_assessment\n"
            "  ON rag_source_reviews(registered_capture_id, assessment_evidence_id)\n"
            "  WHERE assessment_evidence_id IS NOT NULL;") in sql
    # Unconditional pair uniqueness includes expired proofs; a new document
    # handle cannot make the same capture/demand eligible for a second proof.
    for forbidden in ("CREATE TABLE", "CREATE OR REPLACE FUNCTION", "CREATE TRIGGER",
                      "DELETE FROM", "UPDATE rag_assessment_source_evidence", "expires_at", "revoked_at"):
        assert forbidden not in sql
    original = (SCHEMA_DIRECTORY / "480_rag_assessment_execution_authority.sql").read_text(encoding="utf-8")
    assert "capture_id uuid NOT NULL UNIQUE REFERENCES" in original
    assert "document_handle text NOT NULL UNIQUE" in original
    assert ("CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_review_assessment_evidence\n"
            "  ON rag_source_reviews(assessment_evidence_id) WHERE assessment_evidence_id IS NOT NULL;") in original
    legacy = (SCHEMA_DIRECTORY / "330_rag_source_admission.sql").read_text(encoding="utf-8")
    assert "registered_capture_id uuid UNIQUE REFERENCES" in legacy
    assert "document_handle text NOT NULL UNIQUE" in legacy


def test_python_v2_exact_canonical_capture_preserves_oracle_and_signed_binding():
    from dataclasses import replace

    v1,v2 = "python-sum-print-source-v1","python-sum-print-source-v2"
    capture = _capture(v2)
    assert capture.final_url == PYTHON_CANONICAL_URL
    assert len(analyze_source(capture,v2)) == 2
    first,oracle1,applicability1 = source_request(v1)
    second,oracle2,applicability2 = source_request(v2)
    assert (first.submission,first.runtime_id,first.visible_test_bundle_json,first.hidden_test_bundle_json) == (
        second.submission,second.runtime_id,second.visible_test_bundle_json,second.hidden_test_bundle_json)
    assert (oracle1,applicability1)==(oracle2,applicability2)
    assert first.source_reference_hash != second.source_reference_hash
    for changed,profile in (
        (replace(capture,final_url=PYTHON_URL,request_chain=(PYTHON_URL,)),v2),
        (capture,v1),
        (replace(capture,request_chain=(PYTHON_URL,PYTHON_CANONICAL_URL)),v2),
    ):
        with pytest.raises(SourceAssessmentDenied,match="SOURCE_PROFILE_DENIED"):
            analyze_source(changed,profile)
    signed,pins = _signed(v2)
    verified = verify_source_assessment(signed,service_keys=pins,now=NOW+timedelta(seconds=2))
    assert verified.prepared.profile_id == v2 and verified.prepared.demand.scope.subject_id=="route.python"
    changed = signed.model_copy(update={"payload":signed.payload.model_copy(update={
        "prepared":signed.payload.prepared.model_copy(update={"profile_id":v1})})})
    with pytest.raises(SourceAssessmentDenied,match="SOURCE_PROOF_DENIED"):
        verify_source_assessment(changed,service_keys=pins,now=NOW+timedelta(seconds=2))
    fragment = "482_rag_python_canonical_assessment_source.sql"
    assert fragment in SCHEMA_FRAGMENT_NAMES
    assert SCHEMA_FRAGMENT_NAMES.index("480_rag_assessment_execution_authority.sql") < SCHEMA_FRAGMENT_NAMES.index(fragment)
    migration = (SCHEMA_DIRECTORY/fragment).read_text(encoding="utf-8")
    assert "NEW.profile_id='python-sum-print-source-v2'" in migration
    assert PYTHON_CANONICAL_URL in migration and PYTHON_URL in migration
    assert "rag_assessment_source_evidence_profile_id_check" in migration


def test_sqlite_real_page_two_sentence_unit_and_exact_unclosed_footer():
    from dataclasses import replace
    from app.services.grounding.autonomous.source_assessment_profiles import (
        SQLITE_OFFICIAL_UNCLOSED_FOOTER, SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH, _Units,
    )

    profile = "sqlite-filter-order-source-v1"
    footer = SQLITE_OFFICIAL_UNCLOSED_FOOTER.replace("\r\n\r\n", "\n\n")
    text = ("<html><body><div><p>" + WHERE_PARAGRAPH + "</p><p>"
            + SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH + "</p>" + footer)
    body = text.encode("utf-8")
    capture = replace(_capture(profile),body=body,digest=hashlib.sha256(body).hexdigest(),
                      revision=hashlib.sha256(body).hexdigest())
    assert len(SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH)==311
    parser = _Units(text,{"claim.where":(WHERE_PARAGRAPH,),"claim.order":(SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH,)})
    parser.feed(text)
    parser.close()
    assert not parser.closed_html and parser.stack==["html","body","div"] and not parser.invalid
    assert parser.approved_units_explicitly_closed and parser.unit is None
    spans = analyze_source(capture,profile)
    assert tuple(capture.body[s.start_byte:s.end_byte].decode() for s in spans)==(
        WHERE_PARAGRAPH,SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH)
    assert capture.body==body and capture.digest==hashlib.sha256(body).hexdigest()
    crlf_body = text.removesuffix(footer).encode("utf-8") + SQLITE_OFFICIAL_UNCLOSED_FOOTER.encode("utf-8")
    crlf_capture = replace(capture,body=crlf_body,digest=hashlib.sha256(crlf_body).hexdigest(),
                           revision=hashlib.sha256(crlf_body).hexdigest())
    assert analyze_source(crlf_capture,profile) == spans
    assert crlf_capture.body == crlf_body and crlf_capture.digest != capture.digest
    # No fake appended closures or raw capture/hash edits to pass preflight.
    for bad in (
        text.removesuffix(footer),
        text.replace("2026-01-26 15:45:07Z","2026-01-27 15:45:07Z"),
        text.replace(SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH+"</p>",SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH),
    ):
        bad_body = bad.encode("utf-8")
        rejected = replace(capture,body=bad_body,digest=hashlib.sha256(bad_body).hexdigest(),
                           revision=hashlib.sha256(bad_body).hexdigest())
        with pytest.raises(SourceAssessmentDenied,match="SOURCE_ASSERTIONS_UNSUPPORTED"):
            analyze_source(rejected,profile)
