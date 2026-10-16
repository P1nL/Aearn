"""Offline C review contracts; fake ports are not production authority."""
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.services.grounding.autonomous.source_assessment import (
    CurrentReview, DocumentCoordinate, DocumentReviewFacts, StorageUseGrant, assess_document,
)
from app.services.grounding.autonomous.source_policy import check_source
from tests.grounding.rag_material_helpers import H, H2, NOW, SCOPE


REVIEW_ID = UUID("00000000-0000-0000-0000-000000000001")
CAPTURE_ID = UUID("00000000-0000-0000-0000-000000000002")


class Reviews:
    def __init__(self, review):
        self.review = review
        self.calls = 0

    def resolve(self, source_handle, document_handle):
        self.calls += 1
        return self.review


def coordinate():
    return DocumentCoordinate(scope=SCOPE, source_handle="source.blog", document_handle="document.001",
                              document_revision="v1", document_hash=H2)


def facts(**changes):
    values = dict(coordinate=coordinate(), review_id=REVIEW_ID, registered_capture_id=CAPTURE_ID,
                  review_receipt_hash=H, quality_code="QUALIFIED", license_id="CC0",
                  policy_id="policy.001", policy_generation=2, root_id="root.001",
                  immutable_history_allowed=True,
                  allowed_usages=("main_teaching", "assessment_evidence"),
                  lineage_family="family.blog", origin="blog", reading_level="beginner",
                  reading_fit="suitable", version_fit="current", technical_status="correct",
                  conflict_status="resolved", known_error="absent", covered_facets=("syntax",),
                  status="reviewed")
    return DocumentReviewFacts(**(values | changes))


def grant(**changes):
    values = dict(coordinate=coordinate(), review_id=REVIEW_ID, active=True, revoked=False,
                  storage_receipt_id="store.001",
                  admission_receipt_id="admission.001", policy_generation=2,
                  license_status="granted", retained_until=NOW + timedelta(days=1),
                  allowed_usages=("main_teaching", "assessment_evidence"))
    return StorageUseGrant(**(values | changes))


def decide(item=None, permission=None, *, revoked=False):
    item = item or facts()
    permission = grant() if permission is None else permission
    return assess_document(item, resolver=Reviews(CurrentReview(facts=item, grant=permission,
                                                                  revoked=revoked)), now=NOW)


def test_exact_review_projects_existing_a_contracts_without_claim_success():
    result = decide()
    assert result.allowed and result.assessment is not None and result.authorization is not None
    assert result.authorization.lineage_family == "family.blog"
    assert check_source(result.assessment, purpose="main_teaching",
                        resolver=type("Port", (), {"resolve": lambda self, *_: result.authorization})()).allowed
    assert result.assessment.allowed_usages == ("main_teaching", "assessment_evidence")
    # Admission at the source level is not itself a scoring/claim receipt.
    assert result.assessment.status == "reviewed"


@pytest.mark.parametrize("change", [
    {"version_fit": "stale"}, {"reading_fit": "unsuitable"},
    {"technical_status": "incorrect"}, {"technical_status": "unknown"},
    {"conflict_status": "unresolved"}, {"known_error": "present"},
    {"covered_facets": ()}, {"quality_code": "KNOWN_ERROR"},
])
def test_bad_or_unknown_quality_never_admits(change):
    result = decide(facts(**change))
    assert not result.allowed and result.reason == "QUALITY_UNVERIFIED"
    assert result.assessment is None and result.authorization is None


def test_official_label_or_hash_does_not_override_unverified_quality():
    assert decide(facts(origin="official", technical_status="unknown")).reason == "QUALITY_UNVERIFIED"
    assert decide(facts(origin="official", quality_code="UNREVIEWED")).reason == "QUALITY_UNVERIFIED"


def test_quarantine_revocation_and_stale_snapshot_fail_closed():
    assert decide(facts(status="quarantined", allowed_usages=(), immutable_history_allowed=False)).reason == "REVIEW_QUARANTINED"
    with pytest.raises(ValidationError):
        facts(status="revoked")
    assert decide(revoked=True).reason == "SOURCE_REVOKED"
    supplied = facts()
    current = CurrentReview(facts=facts(coordinate=coordinate().model_copy(update={"document_revision": "v2"})),
                            grant=grant(), revoked=False)
    assert assess_document(supplied, resolver=Reviews(current), now=NOW).reason == "SOURCE_STALE"
    assert assess_document(supplied, resolver=None, now=NOW).reason == "AUTHORITY_MISSING"


def test_storage_use_retention_and_exact_coordinate_are_separate():
    assert decide(permission=grant(retained_until=NOW)).reason == "RETENTION_EXPIRED"
    assert decide(permission=grant(active=False)).reason == "STORAGE_DENIED"
    assert decide(permission=grant(revoked=True, active=False)).reason == "STORAGE_DENIED"
    assert decide(permission=grant(policy_generation=3)).reason == "STORAGE_DENIED"
    assert decide(permission=grant(review_id=UUID("00000000-0000-0000-0000-000000000003"))).reason == "STORAGE_DENIED"
    assert decide(permission=grant(allowed_usages=())).reason == "USAGE_DENIED"
    assert decide(permission=grant(allowed_usages=("supplementary_explanation",))).reason == "USAGE_DENIED"
    assert decide(permission=grant(coordinate=coordinate().model_copy(update={"document_hash": "c" * 64}))).reason == "STORAGE_DENIED"
    assert decide(permission=grant(license_status="unclear", allowed_usages=())).reason == "STORAGE_DENIED"
    assert decide(facts(allowed_usages=("supplementary_explanation",)),
                  permission=grant(allowed_usages=("supplementary_explanation",))).assessment.allowed_usages == (
        "supplementary_explanation",)


def _p7_same_top_source(monkeypatch):
    """OFFLINE only: real source signatures/prepare, stub SQL549 and original rows."""
    import hashlib
    from types import SimpleNamespace
    from uuid import uuid4

    from app.services.grounding.autonomous import assessment_receipt_repository as receipts
    from app.services.grounding.autonomous.source_assessment_profiles import (
        run_source_assessment, sign_source_assessment, source_proof_hash, source_request, storage_profile_id,
    )
    from app.services.grounding.public_course_contracts import public_course_demand
    from app.services.learning.item_bank.contracts import canonical_hash
    from app.services.learning.item_supply import persistent_pack_current_source as source
    from tests.grounding.test_actual_d_finite_source import NOW, OfflineD, prepare, repository, sign
    from tests.grounding.test_course_material_lifetime import ProtocolStub

    conn = OfflineD("python-kc-binding-v1")
    repo = repository(monkeypatch, conn)
    private, _, key = sign(repo, prepare(repo, conn))
    public_prepared = repo.prepare(capture_id=private.payload.prepared.capture_id,
        document_handle="document.public-test", demand=public_course_demand(conn.target_id),
        profile_id="python-binding-source-v1")
    runner = ProtocolStub(source_request(public_prepared.profile_id)[1])
    public = sign_source_assessment(run_source_assessment(public_prepared, runner=runner, run_id=uuid4()),
        runner=runner, service_key_id="service.test", private_key=key, now=NOW)

    def record(signed):
        p, q = signed.payload, signed.payload.prepared
        proof_hash = source_proof_hash(signed)
        applicability = source_request(q.profile_id)[2]
        row = dict(id=p.evidence_id, capture_id=q.capture_id, source_handle=q.source_handle,
            document_handle=q.document_handle, document_hash=q.document_hash, policy_id=q.policy_id,
            policy_generation=q.policy_generation, root_id=q.budget.root_id, profile_id=storage_profile_id(q),
            demand_hash=q.demand.demand_hash, claim_hash=q.claim_hash, execution_handle=p.execution_handle,
            claim_handle=p.claim_handle, service_key_id=signed.service_key_id,
            signed_proof=signed.model_dump(mode="json"), proof_hash=proof_hash,
            terminal_hash=canonical_hash(p.terminal), issued_at=p.issued_at, expires_at=p.expires_at,
            revoked_at=None, review_id=p.review_id, admission_id=p.admission_id, claim_id=p.claim_id,
            review_receipt_hash=proof_hash, quality_evidence_hash=proof_hash,
            storage_receipt_id=q.storage_receipt_id, license_id=q.license_id, origin="official",
            reading_level=q.reading_level, subject_id=q.demand.scope.subject_id,
            subject_version=q.demand.scope.subject_version, document_revision=q.document_hash,
            status="reviewed", quality_code="QUALIFIED", reading_fit="suitable", version_fit="current",
            technical_status="correct", conflict_status="resolved", known_error="absent",
            immutable_history_allowed=True, receipt_handle=p.admission_handle, admission_generation=q.policy_generation,
            active=True, admission_revoked=None, claim_revoked=None, stored_claim_handle=p.claim_handle,
            stored_claim_hash=q.claim_hash, stored_demand_hash=q.demand.demand_hash,
            applicability=applicability, applicability_hash=hashlib.sha256(applicability.encode()).hexdigest(),
            source_document_hash=q.document_hash, execution_receipt_handle=p.execution_handle,
            verification_receipt_hash=proof_hash, method="isolated_execution",
            execution_scope_json=q.execution_scope.model_dump(mode="json"), facets=list(q.demand.scope.facets),
            covered_facets=list(q.demand.scope.facets), scope_facets=list(q.demand.scope.facets),
            review_usages=list(receipts.USAGES), admission_usages=list(receipts.USAGES))
        if signed is private:
            row.update(private_user_id=UUID(q.actual_d.draft.user_id), private_epoch=q.actual_d.user_epoch)
        return row

    rows = {s.payload.evidence_id: record(s) for s in (public, private)}
    flags = dict(txid=7, ok=True, sql549=0, front=0, verified=0)
    execute = conn.execute

    def scoped_execute(sql, params=()):
        if "current_pack_source_origin_current" in sql:
            flags["sql549"] += 1
            row = {"ok": flags["ok"]}
        elif "txid_current()" in sql:
            row = {"now": NOW, "txid": flags["txid"]}
        elif "FROM rag_assessment_source_evidence e" in sql:
            row = rows.get(params[0])
        else:
            return execute(sql, params)
        return SimpleNamespace(fetchone=lambda: row)

    monkeypatch.setattr(conn, "execute", scoped_execute)
    verify = repo._verify_current

    def counted_verify(signed, **kwargs):
        flags["verified"] += 1
        return verify(signed, **kwargs)

    monkeypatch.setattr(repo, "_verify_current", counted_verify)
    task_data = dict(pack_task_id=str(source.TASK), user_id=conn.scope.user_id, epoch=1)
    task = SimpleNamespace(user_id=UUID(conn.scope.user_id), epoch=1, mapping_receipt_id=uuid4(),
        model_dump=lambda **_: dict(task_data))
    mapping = SimpleNamespace(mapping_hash=H, model_dump=lambda **_: {"mapping_hash": H})
    type_owner = SimpleNamespace(conn=conn, user_id=task.user_id, epoch=1, query=object(),
        mapping_owner=SimpleNamespace(current_authority=SimpleNamespace(receipts=repo)))
    authority = SimpleNamespace(connection=conn, authorize=lambda _: None)
    type_owner.source_authority = authority
    core = SimpleNamespace(conn=conn, user_id=task.user_id, epoch=1, type_owner=type_owner,
        _guard=lambda: NOW, _current_source_bindings={}, _current_source_origins={})
    selected = [dict(version_id=str(v), proof_id=str(uuid4()), proof_hash=H,
        published_at=NOW.isoformat()) for v in source.VERSIONS.values()]
    cap = source.IssuedCurrentPackSourceBinding(core, uuid4(), task, H, H2,
        source._authorization(mapping, (), (), ()), private.payload.expires_at, (), (), mapping)
    core._current_source_bindings[cap.binding_id] = (cap, source._seal(cap))
    payload = dict(issued_at=NOW.isoformat(), capture_txid=7, task_ref=task_data,
        selection_hash=cap.selection_hash, source_authorization_hash=cap.source_authorization_hash,
        selected=selected, public_receipts=[])
    rid = uuid4()
    core._current_source_origins[(cap.binding_id, 7)] = (rid, payload, canonical_hash(payload))
    type_owner.current_source_binding = cap
    monkeypatch.setattr(source, "_data", lambda *_: dict(public_materials=[], course_materials=[]))
    # Exact source data hash still runs on the strict front.
    object.__setattr__(cap, "source_data_hash", canonical_hash(dict(public_materials=[], course_materials=[])))
    core._current_source_bindings[cap.binding_id] = (cap, source._seal(cap))

    def full_front(*_):
        flags["front"] += 1
        for _ in range(2):
            for signed in (public, private):
                repo._load(signed.payload.evidence_id)
        return {}, (), cap.source_deadline, mapping

    monkeypatch.setattr(source, "_current_with_mapping", full_front)
    monkeypatch.setattr(source, "_selection", lambda *_: (selected, cap.selection_hash))
    return SimpleNamespace(repo=repo, cap=cap, rows=rows, private=private, public=public,
        flags=flags, source=source, receipts=receipts, now=NOW, payload=payload)


def test_p7_same_top_full_front_once_per_exact_evidence_and_strict_exit(monkeypatch):
    ctx = _p7_same_top_source(monkeypatch)
    with ctx.cap.current_scope() as permission:
        assert permission is None
        assert ctx.flags["verified"] == 2 and ctx.flags["front"] == 1
        before = ctx.flags["sql549"]
        assert ctx.cap.require() is ctx.cap.mapping
        assert ctx.cap.resolve_mapping(ctx.cap.task.mapping_receipt_id) is ctx.cap.mapping
        assert ctx.source.source_origin_payload(ctx.cap.owner.type_owner)["current_source_origin_id"] == str(ctx.cap.origin_id())
        assert ctx.flags["sql549"] > before
        assert ctx.flags["verified"] == 2 and ctx.flags["front"] == 1
    assert ctx.source._CURRENT_SOURCE_SCOPE.get() is None
    assert ctx.receipts._CURRENT_RECEIPT_DATA.get() is None
    ctx.repo._load(ctx.private.payload.evidence_id)
    ctx.repo._load(ctx.private.payload.evidence_id)
    assert ctx.flags["verified"] == 4


@pytest.mark.parametrize("signed_name,change", [
    ("private", {"active": False}), ("private", {"admission_revoked": NOW}),
    ("private", {"technical_status": "incorrect"}), ("private", {"private_epoch": 2}),
    ("public", {"claim_revoked": NOW}), ("public", {"scope_facets": []}),
    ("private", {"admission_usages": []}), ("private", {"execution_scope_json": {}}),
    ("repository", {"actual_d_private_provenance_enabled": False}),
    ("repository", {"provenance": None}),
])
def test_p7_same_top_own_current_row_changes_deny(monkeypatch, signed_name, change):
    from app.services.grounding.autonomous.source_assessment_profiles import SourceAssessmentDenied
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

    ctx = _p7_same_top_source(monkeypatch)
    with ctx.cap.current_scope():
        data = ctx.receipts._CURRENT_RECEIPT_DATA.get()
        state = ctx.source._CURRENT_SOURCE_SCOPE.get()
        if signed_name == "repository":
            key = next(iter(change))
            original = getattr(ctx.repo, key)
            if key == "provenance":
                other_owner = object.__new__(type(original))
                other_owner.conn = ctx.repo.conn  # Same concrete class/conn is not the same front owner.
                setattr(ctx.repo, key, other_owner)
            else:
                setattr(ctx.repo, key, change[key])
        else:
            row = ctx.rows[getattr(ctx, signed_name).payload.evidence_id]
            original = dict(row)
            row.update(change)
        with pytest.raises((SourceAssessmentDenied, PipelineRepositoryError)):
            ctx.cap.require()
        if signed_name == "repository":
            setattr(ctx.repo, key, original)
        else:
            row.clear()
            row.update(original)
        assert state.closed and state.front is None and state.public_receipts is None
        assert not data.loads and data.sealed
        with pytest.raises(PipelineRepositoryError, match="SCOPE_REQUIRED"):
            ctx.cap.require()  # Catch + restore cannot resurrect this lexical scope.
        with pytest.raises(PipelineRepositoryError, match="SCOPE_REQUIRED"):
            with ctx.cap.current_scope():
                pytest.fail("closed tombstone cannot be reopened inside the old scope")
        with pytest.raises(PipelineRepositoryError, match="SCOPE_REQUIRED"):
            ctx.repo._load(ctx.private.payload.evidence_id)
    assert ctx.receipts._CURRENT_RECEIPT_DATA.get() is None


def test_p7_same_top_expiry_receiver_txid_and_foreign_cap_deny(monkeypatch):
    from dataclasses import replace

    from app.services.grounding.autonomous.source_assessment_profiles import SourceAssessmentDenied
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

    # Each existing rejection needs a distinct scope now: the first failure
    # poisons its entire lexical scope even when the caller catches it.
    for failure in ("foreign_cap", "receiver", "txid", "foreign_conn", "expiry"):
        ctx = _p7_same_top_source(monkeypatch)
        with ctx.cap.current_scope():
            if failure == "foreign_cap":
                action = replace(ctx.cap).require
            elif failure == "receiver":
                ctx.flags["ok"] = False
                action = ctx.cap.require
            elif failure == "txid":
                ctx.flags["txid"] += 1
                action = ctx.cap.require
            elif failure == "foreign_conn":
                ctx.cap.owner.conn = object()
                action = ctx.cap.require
            else:
                monkeypatch.setattr(ctx.repo, "_clock", lambda: ctx.private.payload.expires_at)
                action = ctx.cap.require
            with pytest.raises((PipelineRepositoryError, SourceAssessmentDenied)):
                action()
            assert ctx.source._CURRENT_SOURCE_SCOPE.get().closed
            assert not ctx.receipts._CURRENT_RECEIPT_DATA.get().loads
    ctx.flags["txid"] += 1
    with pytest.raises(PipelineRepositoryError, match="ORIGINAL_ORIGIN_REQUIRED"):
        with ctx.cap.current_scope():
            pytest.fail("old origin cannot enter a new TOP")


def test_p7_same_top_exception_cleans_lexical_data_and_origin_digest_denies(monkeypatch):
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

    ctx = _p7_same_top_source(monkeypatch)
    with pytest.raises(RuntimeError, match="abort"):
        with ctx.cap.current_scope():
            raise RuntimeError("abort")
    assert ctx.source._CURRENT_SOURCE_SCOPE.get() is None
    assert ctx.receipts._CURRENT_RECEIPT_DATA.get() is None
    with ctx.cap.current_scope():
        stored = ctx.rows[ctx.private.payload.evidence_id]["signed_proof"]
        stored["signature_hex"] = "0" * len(stored["signature_hex"])
        from app.services.grounding.autonomous.source_assessment_profiles import SourceAssessmentDenied
        with pytest.raises(SourceAssessmentDenied, match="BINDING_DENIED"):
            ctx.cap.require()
        stored["signature_hex"] = ctx.private.signature_hex
        with pytest.raises(PipelineRepositoryError, match="SCOPE_REQUIRED"):
            ctx.cap.require()
    with ctx.cap.current_scope():
        ctx.payload["selected"][0]["proof_hash"] = H2
        with pytest.raises(PipelineRepositoryError, match="ORIGIN_CHANGED"):
            ctx.cap.origin_id()


def test_p7_same_top_implicit_publication_time_only_exact_scoped_front(monkeypatch):
    from types import SimpleNamespace

    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

    ctx = _p7_same_top_source(monkeypatch)
    entry = ctx.payload["selected"][0]
    proof = SimpleNamespace(version_id=UUID(entry["version_id"]), proof_id=UUID(entry["proof_id"]), proof_hash=entry["proof_hash"])
    kwargs = dict(query=ctx.cap.owner.type_owner.query, proof=proof, source_authority=ctx.cap.owner.type_owner.source_authority)
    with pytest.raises(PipelineRepositoryError, match="PUBLICATION_TIME_REQUIRED"):
        ctx.cap.current_receipts(**kwargs)
    with ctx.cap.current_scope():
        assert ctx.cap.current_receipts(**kwargs) == ()
        with pytest.raises(PipelineRepositoryError, match="EXACT_PUBLICATION_REQUIRED"):
            ctx.cap.current_receipts(**kwargs, published_at=ctx.now + timedelta(seconds=1))
        with pytest.raises(PipelineRepositoryError, match="SCOPE_REQUIRED"):
            ctx.cap.current_receipts(**kwargs)
    with ctx.cap.current_scope():
        proof.proof_hash = H2
        with pytest.raises(PipelineRepositoryError, match="EXACT_PUBLICATION_REQUIRED"):
            ctx.cap.current_receipts(**kwargs)


def test_strict_immutable_bounded_review_and_no_model_reviewer():
    with pytest.raises(ValidationError):
        facts(reviewer="model")
    with pytest.raises(ValidationError):
        facts(covered_facets=("schema",))
    with pytest.raises(ValidationError):
        facts(covered_facets=("syntax", "syntax"))
    with pytest.raises(ValidationError):
        facts(origin="official", arbitrary_model_score=0.9)
    with pytest.raises(ValidationError):
        grant(allowed_usages=("main_teaching", "main_teaching"))
    with pytest.raises(ValidationError):
        grant(retained_until=datetime(2026, 9, 26))
    invalid = facts().model_copy(update={"candidate_capture_id": CAPTURE_ID})
    current = CurrentReview(facts=facts(), grant=grant(), revoked=False).model_copy(update={"facts": invalid})
    assert assess_document(invalid, resolver=Reviews(current), now=NOW).reason == "INVALID_CONTRACT"
    assert facts().model_config["frozen"]
