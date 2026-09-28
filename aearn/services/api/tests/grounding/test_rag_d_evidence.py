"""D exact selection over synthetic C fixtures in an explicitly disposable database.

The verifier here is a test double. These tests do not establish live-source quality,
public release, or a current real-world SQLite excerpt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema
from app.services.grounding.autonomous.access_policy import (
    AccessRequest, AuthoritySnapshot, AutonomousGates,
)
from app.services.grounding.autonomous.contracts import (
    LearningMaterialDemand, RagBudgetDelegation, SubjectScope,
)
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_contracts_v2 import (
    DraftScope, NodeMaterialRequirement, digest,
)
from tests.grounding.test_rag_c_corpus_governance import SyntheticQualityVerifier


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture()
def db():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_D_TEST_DATABASE_URL")
    if dsn is None:
        pytest.skip("explicit AEARN_RAG_D_TEST_DATABASE_URL required")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_d_"):
        pytest.fail("refusing non-disposable D database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute("SELECT current_database() AS name").fetchone()
        if row is None or row["name"] != name:
            pytest.fail("current_database() mismatch")
        apply_schema(conn)
        apply_schema(conn)
        yield conn
        conn.rollback()


def _seed_sql_d(conn, *, purpose="main_teaching",
                source_facets=("queries",), chunk_facets=("queries",)):  # type: ignore[no-untyped-def]
    """Unique synthetic URL on each run; avoids immutable C URL/dispatch replay.

    The path is intentionally not a live SQLite document and never fetched.
    """
    from app.services.grounding.autonomous.corpus_governance import (
        CorpusGovernance, PostgresCorpusAuthority,
    )
    from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
    from app.services.grounding.corpus_contracts import (
        CorpusCandidate, CorpusChunk, CorpusDocument, CorpusSource,
    )

    suffix = uuid4().hex[:12]
    root, policy, source, doc = (f"{prefix}.{suffix}" for prefix in
                                 ("root", "policy", "source", "document"))
    path = f"/lang_select_synthetic_{suffix}.html"
    url = f"https://www.sqlite.org{path}"
    body = "SELECT title FROM books WHERE id = 1;"  # synthetic bytes only
    now = datetime.now(UTC)
    end = now + timedelta(days=2)
    conn.execute("""INSERT INTO rag_budget_authority_roots
        (root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,
         policy_generation,period_key,period_start,period_end,cap_units,enabled)
        VALUES (%s,%s,1,%s,%s,1,%s,%s,%s,100,true)""",
        (root, f"delegate.{suffix}", end, policy, suffix, now-timedelta(hours=1), end))
    conn.execute("""INSERT INTO rag_registered_source_policies
        (policy_id,generation,source_handle,subject_id,subject_version,facets,origin,
         reading_level,canonical_url,canonical_url_sha256,host,path,license_id,
         allowed_usages,immutable_history_allowed,max_captured_bytes,retention_until,
         expires_at,root_id,enabled)
        VALUES (%s,1,%s,'route.sql','v1',%s,'official','beginner',
                %s,%s,'www.sqlite.org',%s,'PublicDomain',%s,true,1048576,%s,%s,%s,true)""",
        (policy, source, list(source_facets), url, sha(url), path, [purpose], end, end, root))
    attempt, capture, review, admission = (uuid4() for _ in range(4))
    conn.execute("""INSERT INTO rag_registered_fetch_attempts
        (id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,
         state,response_sha256,response_bytes,settled_at)
        VALUES (%s,%s,1,%s,%s,%s,%s,'settled',%s,%s,now())""",
        (attempt, policy, sha(url), root, f"attempt.{suffix}", sha(suffix), sha(body), len(body)))
    conn.execute("""INSERT INTO rag_registered_source_captures
        (id,fetch_attempt_id,policy_id,generation,request_chain,final_url,content_type,
         fetched_sha256,captured_bytes,captured_body,license_id,retention_until)
        VALUES (%s,%s,%s,1,%s::jsonb,%s,'text/plain',%s,%s,%s,'PublicDomain',%s)""",
        (capture, attempt, policy, json.dumps([url]), url, sha(body), len(body), body.encode(), end))
    class ScopedSyntheticQualityVerifier(SyntheticQualityVerifier):
        def verify(self, capture):  # type: ignore[no-untyped-def]
            return replace(super().verify(capture), covered_facets=tuple(source_facets))

    reviewer = SourceReviewRepository(conn, verifier=ScopedSyntheticQualityVerifier(f"family.{suffix}"))
    _, capture_authority = reviewer._capture(capture, "registered", now)
    conn.execute("""INSERT INTO rag_source_reviews
        (id,registered_capture_id,source_handle,document_handle,subject_id,subject_version,
         facets,document_revision,document_hash,lineage_family,origin,reading_level,status,
         quality_code,reading_fit,version_fit,technical_status,conflict_status,known_error,
         covered_facets,quality_evidence_hash,storage_receipt_id,license_id,allowed_usages,
         immutable_history_allowed,policy_id,policy_generation,root_id,review_receipt_hash)
        VALUES (%s,%s,%s,%s,'route.sql','v1',%s,%s,%s,%s,'official',
                'beginner','reviewed','QUALIFIED','suitable','current','correct',
                'resolved','absent',%s,%s,%s,'PublicDomain',%s,
                true,%s,1,%s,%s)""",
        (review, capture, source, doc, list(source_facets), sha(body), sha(body), f"family.{suffix}",
         list(source_facets), sha("synthetic-quality"), capture_authority["storage_receipt_id"],
         [purpose], policy, root, sha("review")))
    conn.execute("""INSERT INTO rag_source_admissions
        (id,review_id,receipt_handle,allowed_usages,policy_generation,receipt_hash)
        VALUES (%s,%s,%s,%s,1,%s)""",
        (admission, review, f"receipt.{suffix}", [purpose], sha("admission")))
    candidate = CorpusCandidate(corpus_id=uuid4(), subject_id="route.sql", subject_version="v1",
        registry_digest=sha("sql-registry-v1"), retrieval_policy_version="fts-v1",
        coverage_policy_version="dynamic-c-v1")
    common = dict(corpus_id=candidate.corpus_id, subject_id="route.sql", subject_version="v1")
    source_row = CorpusSource(**common, source_id=source, source_hash=sha(source),
        trust_tier="official", source_kind="documentation", source_version=sha(body),
        allowed_domains=("www.sqlite.org",), seed_urls=(url,), facets=tuple(source_facets))
    doc_row = CorpusDocument(**common, document_id=doc, source_id=source,
        source_hash=source_row.source_hash, trust_tier="official", canonical_url=url,
        final_url=url, content_type="text/plain", document_version=sha(body), fetched_at=now,
        document_hash=sha(body), parse_status="parsed")
    chunk = CorpusChunk(**common, chunk_id=f"chunk.{suffix}", document_id=doc,
        source_id=source, source_hash=source_row.source_hash, trust_tier="official",
        document_hash=sha(body), ordinal=0, title="SQL queries", section_path="SELECT",
        content=body, facets=tuple(chunk_facets), topic_tags=(), chunk_hash=sha(body))
    service = CorpusGovernance(conn, authority=PostgresCorpusAuthority(),
                               source_reviews=reviewer, isolated_operator_enabled=True)
    prior_active = service.repo.active(candidate.subject_id)
    pointer_generation = prior_active.generation if prior_active else 0
    service.create_candidate(candidate, sources=[source_row], documents=[doc_row],
        chunks=[chunk], admissions={doc: admission}, purpose=purpose,
        idempotency_key=f"d-create-{suffix}")
    candidate_generation = service.repo.version(candidate.corpus_id).generation
    return service, candidate, policy, suffix, candidate_generation, pointer_generation


def setup_ready(conn, *, purpose="main_teaching",
                source_facets=("queries",), chunk_facets=("queries",)):  # type: ignore[no-untyped-def]
    service, candidate, policy, suffix, candidate_generation, pointer_generation = _seed_sql_d(
        conn, purpose=purpose, source_facets=source_facets, chunk_facets=chunk_facets,
    )
    # Validation fences this candidate version; activation separately fences the
    # subject's prior active pointer. They are different generation authorities.
    service.validate(candidate.corpus_id, expected_generation=candidate_generation,
                     purpose=purpose, idempotency_key=f"d-validate-{suffix}")
    version = service.repo.version(candidate.corpus_id)
    service.activate(candidate.corpus_id, expected_generation=pointer_generation,
                     summary_hash=version.summary_hash or "", purpose=purpose,
                     idempotency_key=f"d-activate-{suffix}")
    draft_id = str(uuid4())
    scope = DraftScope(user_id=str(uuid4()), conversation_id=str(uuid4()),
                       session_id=str(uuid4()), draft_id=draft_id, draft_version=1,
                       content_hash=sha("synthetic draft"), source_run_id=str(uuid4()),
                       source_input_revision=1)
    demand = LearningMaterialDemand(
        scope=SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",)),
        demand_hash=sha("synthetic demand"), plan_ref=f"draft.{draft_id}",
        node_ref="node.sql.queries", draft_revision=1,
        purpose=purpose, reading_level="beginner", language="en",
    )
    req = NodeMaterialRequirement(node_id="sql.queries", goal_hash=sha("sql goal"),
                                  demand=demand)
    budget = RagBudgetDelegation(root_id=f"root.{suffix}",
        delegation_id=f"delegate.{suffix}", generation=1,
        expires_at=datetime.now(UTC) + timedelta(days=1))

    issued: dict[str, LearningMaterialDemand] = {demand.demand_hash: demand}

    class TrustedSyntheticActor:
        def resolve(self, request: AccessRequest) -> AuthoritySnapshot:
            issued_demand = issued[request.demand_hash]
            return AuthoritySnapshot(
                demand=issued_demand, demand_hash=issued_demand.demand_hash,
                scope=issued_demand.scope, purpose=issued_demand.purpose,
                actor_id="actor.synthetic", allowed_actions=("consume",),
                policy_id=policy, policy_generation=1, budget=budget,
                budget_active=True, authorized=True,
            )

    def request_for(item: NodeMaterialRequirement) -> AccessRequest:
        issued[item.demand.demand_hash] = item.demand
        return AccessRequest(demand_hash=item.demand.demand_hash, scope=item.demand.scope,
            purpose=item.demand.purpose, actor_id="actor.synthetic", action="consume",
            policy_id=policy, policy_generation=1, budget=budget)

    adapter = EvidenceSelection(conn, governance=service, request_for=request_for,
        gates=AutonomousGates(evidence_consumer=True),
        authority_resolver=TrustedSyntheticActor(), enabled=True)
    return adapter, scope, req, policy, candidate


def test_exact_selection_and_current_revocation(db) -> None:  # type: ignore[no-untyped-def]
    adapter, draft, req, policy, _candidate = setup_ready(db)
    entry = adapter.resolve(db, req, draft)
    assert entry.status == "ready"
    assert entry.covered_facets == ("queries",)
    assert len(entry.evidence) == 1
    coord = entry.evidence[0]
    assert coord.binding.document_hash and coord.chunk_hash == coord.approved_excerpt_hash
    result = adapter.resolve_evidence(draft, (req,))
    receipt = adapter.authorize_selection(db, result)
    assert receipt.kind == "selection" and receipt.object_digest == result.selection_digest
    assert receipt.authorization_digest != "0" * 64
    db.execute("UPDATE rag_registered_source_policies SET enabled=false,revoked_at=clock_timestamp() "
               "WHERE policy_id=%s", (policy,))
    with pytest.raises(Exception):
        adapter.authorize_selection(db, result)


def test_broader_current_c_review_reuses_only_exact_requested_chunk_facets(db) -> None:  # type: ignore[no-untyped-def]
    """Real PG/C ports with a synthetic verifier, never a live source acceptance."""
    adapter, draft, req, _policy, _candidate = setup_ready(
        db, source_facets=("queries", "schema"), chunk_facets=("queries", "schema"),
    )
    entry = adapter.resolve(db, req, draft)
    assert entry.status == "ready" and entry.covered_facets == ("queries",)
    coord = entry.evidence[0]
    original = adapter.governance.source_reviews.resolve(
        coord.binding.source_handle, coord.binding.document_handle,
    )
    assert original is not None
    assert original.facts.coordinate.scope.facets == ("queries", "schema")
    assert coord.binding.scope.facets == ("queries",)
    selection = adapter.resolve_evidence(draft, (req,))
    assert adapter.authorize_selection(db, selection).kind == "selection"
    binding, receipt = adapter.freeze_binding(selection, node_id=req.node_id,
        goal_hash=req.goal_hash, purpose=req.demand.purpose, request=adapter.request_for(req))
    assert receipt.covered_facets == ("queries",)
    original_authorization = adapter.governance.source_reviews.resolve_authorization(
        coord.binding.source_handle, coord.binding.document_handle,
    )
    assert original_authorization is not None
    assert receipt.original_source_digests == ((coord.binding.source_handle,
        coord.binding.document_handle, original.facts.review_receipt_hash,
        digest(original_authorization.model_dump(mode="json"))),)
    assert adapter.check_current_authorization(binding, binding.purpose,
        request=adapter.request_for(req)).original_source_digests == receipt.original_source_digests


def test_broader_review_cannot_fill_missing_exact_chunk_facet(db) -> None:  # type: ignore[no-untyped-def]
    adapter, draft, req, _policy, _candidate = setup_ready(
        db, source_facets=("queries", "schema"), chunk_facets=("queries",),
    )
    missing = req.model_copy(update={"demand": req.demand.model_copy(update={
        "scope": SubjectScope(subject_id="route.sql", subject_version="v1", facets=("schema",)),
        "demand_hash": sha("schema demand missing exact chunk"),
    })})
    denied = adapter.resolve(db, missing, draft)
    assert denied.status != "ready" and not denied.evidence


def test_ready_selection_requires_facets_proven_by_exact_chunks(db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A current source grant alone cannot make an unrepresented facet ready."""
    from app.services.grounding.current_authorization import EvidenceDenied

    adapter, draft, req, _policy, _candidate = setup_ready(db)
    result = adapter.resolve_evidence(draft, (req,))
    original = adapter.check_current_authorization

    def current_without_requested_facet(*args, **kwargs):  # type: ignore[no-untyped-def]
        return replace(original(*args, **kwargs), covered_facets=())

    monkeypatch.setattr(adapter, "check_current_authorization", current_without_requested_facet)
    with pytest.raises(EvidenceDenied, match="EVIDENCE_INSUFFICIENT"):
        adapter.authorize_selection(db, result)


def test_partial_wrong_purpose_and_assessment_fail_closed(db) -> None:  # type: ignore[no-untyped-def]
    adapter, draft, req, _policy, _candidate = setup_ready(db)
    partial = req.model_copy(update={"demand": req.demand.model_copy(update={
        "scope": SubjectScope(subject_id="route.sql", subject_version="v1",
                              facets=("queries", "schema")),
        "demand_hash": sha("partial demand"),
    })})
    assert adapter.resolve(db, partial, draft).status != "ready"
    wrong = req.model_copy(update={"demand": req.demand.model_copy(update={
        "purpose": "supplementary_explanation",
        "demand_hash": sha("wrong purpose demand"),
    })})
    assert adapter.resolve(db, wrong, draft).status != "ready"
    assessment = req.model_copy(update={"demand": req.demand.model_copy(update={
        "purpose": "assessment_evidence",
    })})
    assert adapter.resolve(db, assessment, draft).gaps == ("claim_unverified",)


def test_exact_binding_rejects_changed_coordinates(db) -> None:  # type: ignore[no-untyped-def]
    from app.services.grounding.current_authorization import EvidenceDenied
    from app.services.grounding.material_contracts_v2 import EvidenceBindingV2, digest

    adapter, draft, req, _policy, _candidate = setup_ready(db)
    selection = adapter.resolve_evidence(draft, (req,))
    binding, receipt = adapter.freeze_binding(selection, node_id=req.node_id,
        goal_hash=req.goal_hash, purpose=req.demand.purpose, request=adapter.request_for(req))
    assert receipt.active_generation == binding.evidence[0].active_generation
    original = binding.payload()
    for field in ("summary_hash", "validation_hash", "registry_digest", "chunk_hash",
                  "approved_excerpt_hash", "retrieval_hash", "coverage_hash"):
        payload = copy.deepcopy(original)
        payload["evidence"][0][field] = sha(f"tampered {field}")
        changed = EvidenceBindingV2.model_validate_json(json.dumps({**payload,
            "binding_digest": digest(payload)}))
        with pytest.raises(EvidenceDenied, match="BINDING_MISMATCH"):
            adapter.check_current_authorization(changed, changed.purpose,
                                                request=adapter.request_for(req))
    payload = copy.deepcopy(original)
    payload["evidence"][0]["chunk_id"] = "chunk.nonexistent"
    changed = EvidenceBindingV2.model_validate_json(json.dumps({**payload, "binding_digest": digest(payload)}))
    with pytest.raises(EvidenceDenied, match="BINDING_MISMATCH"):
        adapter.check_current_authorization(changed, changed.purpose,
                                            request=adapter.request_for(req))
    payload = copy.deepcopy(original)
    payload["evidence"][0]["binding"]["document_revision"] = "wrong-revision"
    changed = EvidenceBindingV2.model_validate_json(json.dumps({**payload, "binding_digest": digest(payload)}))
    with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
        adapter.check_current_authorization(changed, changed.purpose,
                                            request=adapter.request_for(req))
    payload = copy.deepcopy(original)
    payload["evidence"][0]["active_generation"] += 1
    changed = EvidenceBindingV2.model_validate_json(json.dumps({**payload, "binding_digest": digest(payload)}))
    with pytest.raises(EvidenceDenied, match="CORPUS_GENERATION_STALE"):
        adapter.check_current_authorization(changed, changed.purpose,
                                            request=adapter.request_for(req))


def test_root_generation_and_capture_retention_stale(db) -> None:  # type: ignore[no-untyped-def]
    from app.services.grounding.current_authorization import EvidenceDenied

    adapter, draft, req, policy, _candidate = setup_ready(db)
    selection = adapter.resolve_evidence(draft, (req,))
    binding, _ = adapter.freeze_binding(selection, node_id=req.node_id,
        goal_hash=req.goal_hash, purpose=req.demand.purpose, request=adapter.request_for(req))
    root = db.execute("SELECT root_id FROM rag_registered_source_policies WHERE policy_id=%s",
                      (policy,)).fetchone()["root_id"]
    with db.transaction():
        db.execute("UPDATE rag_budget_authority_roots SET policy_generation=2 WHERE root_id=%s", (root,))
        with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
            adapter.check_current_authorization(binding, binding.purpose,
                                                request=adapter.request_for(req))
        db.execute("UPDATE rag_budget_authority_roots SET policy_generation=1 WHERE root_id=%s", (root,))
    capture = db.execute("SELECT registered_capture_id FROM rag_source_reviews "
                         "WHERE document_handle=%s", (binding.evidence[0].binding.document_handle,)).fetchone()
    assert capture is not None
    db.execute("UPDATE rag_registered_source_captures SET captured_body=NULL,cleared_at=clock_timestamp() "
               "WHERE id=%s", (capture["registered_capture_id"],))
    with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
        adapter.check_current_authorization(binding, binding.purpose,
                                            request=adapter.request_for(req))


def test_candidate_grant_and_rule_revocation_block_current_read(db) -> None:  # type: ignore[no-untyped-def]
    """Synthetic B/C only; source grant cannot survive revocation or rule change."""
    from app.services.grounding.autonomous.candidate_use_grants import PostgresCandidateGrantResolver
    from app.services.grounding.autonomous.corpus_governance import (
        CorpusGovernance, PostgresCandidateCorpusAuthority,
    )
    from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
    from app.services.grounding.corpus_contracts import (
        CorpusCandidate, CorpusChunk, CorpusDocument, CorpusSource,
    )
    from app.services.grounding.current_authorization import EvidenceDenied
    from tests.grounding.test_rag_c_candidate_use_grants import _seed as seed_candidate
    from tests.grounding.test_rag_c_corpus_governance import SyntheticQualityVerifier

    adapter, draft, req, _, _ = setup_ready(db)
    suffix, root, policy, source, doc, url, body, capture, end = seed_candidate(db)
    db.execute("""INSERT INTO rag_candidate_use_grants
        (capture_id,capture_sha256,policy_id,policy_generation,root_id,license_id,
         source_handle,subject_id,subject_version,facets,origin,reading_level,
         allowed_usages,immutable_history_allowed,retained_until,storage_receipt_id,
         approval_ref,active)
        VALUES (%s,%s,%s,1,%s,'PublicDomain',%s,'route.sql','v1',ARRAY['queries'],
                'tutorial','beginner',ARRAY['main_teaching'],true,%s,%s,%s,true)""",
        (capture, sha(body), policy, root, source, end,
         f"store.{suffix}", f"operator-approved-fixture.{suffix}"))
    grants = PostgresCandidateGrantResolver(db)
    reviewer = SourceReviewRepository(db, verifier=SyntheticQualityVerifier(f"family.{suffix}"),
                                      candidate_grants=grants)
    review = reviewer.review_and_admit(capture_id=capture, lane="candidate",
        document_handle=doc, requested_usages=("main_teaching",), now=datetime.now(UTC))
    admission = db.execute("SELECT id FROM rag_source_admissions WHERE review_id=%s",
                           (review,)).fetchone()["id"]
    candidate = CorpusCandidate(corpus_id=uuid4(), subject_id="route.sql", subject_version="v1",
        registry_digest=sha("sql-registry-v1"), retrieval_policy_version="fts-v1",
        coverage_policy_version="dynamic-c-v1")
    common = dict(corpus_id=candidate.corpus_id, subject_id="route.sql", subject_version="v1")
    source_row = CorpusSource(**common, source_id=source, source_hash=sha(source),
        trust_tier="trusted_de_facto", source_kind="documentation", source_version=sha(body),
        allowed_domains=("example.org",), seed_urls=(url,), facets=("queries",))
    doc_row = CorpusDocument(**common, document_id=doc, source_id=source,
        source_hash=source_row.source_hash, trust_tier="trusted_de_facto",
        canonical_url=url, final_url=url, content_type="text/plain",
        document_version=sha(body), fetched_at=datetime.now(UTC), document_hash=sha(body),
        parse_status="parsed")
    chunk = CorpusChunk(**common, chunk_id=f"chunk.{suffix}", document_id=doc,
        source_id=source, source_hash=source_row.source_hash, trust_tier="trusted_de_facto",
        document_hash=sha(body), ordinal=0, title="SQL queries", section_path="SELECT",
        content=body, facets=("queries",), topic_tags=(), chunk_hash=sha(body))
    service = CorpusGovernance(db, authority=PostgresCandidateCorpusAuthority(),
                               source_reviews=reviewer, isolated_operator_enabled=True)
    service.create_candidate(candidate, sources=[source_row], documents=[doc_row],
        chunks=[chunk], admissions={doc: admission}, purpose="main_teaching",
        idempotency_key=f"d-candidate-create-{suffix}")
    service.validate(candidate.corpus_id, expected_generation=0,
        purpose="main_teaching", idempotency_key=f"d-candidate-validate-{suffix}")
    version = service.repo.version(candidate.corpus_id)
    previous = service.repo.active("route.sql")
    service.activate(candidate.corpus_id, expected_generation=previous.generation if previous else 0,
        summary_hash=version.summary_hash or "", purpose="main_teaching",
        idempotency_key=f"d-candidate-activate-{suffix}")
    adapter.governance = service
    selection = adapter.resolve_evidence(draft, (req,))
    assert selection.entries[0].status == "ready"
    binding, _ = adapter.freeze_binding(selection, node_id=req.node_id,
        goal_hash=req.goal_hash, purpose=req.demand.purpose, request=adapter.request_for(req))
    with pytest.raises(RuntimeError, match="rollback synthetic rule revoke"):
        with db.transaction():
            db.execute("UPDATE rag_candidate_access_rules SET revoked_at=clock_timestamp() "
                       "WHERE policy_id=%s AND generation=1", (policy,))
            with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
                adapter.check_current_authorization(binding, binding.purpose,
                                                    request=adapter.request_for(req))
            raise RuntimeError("rollback synthetic rule revoke")
    db.execute("UPDATE rag_candidate_use_grants SET active=false,revoked_at=clock_timestamp() "
               "WHERE capture_id=%s", (capture,))
    with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
        adapter.check_current_authorization(binding, binding.purpose,
                                            request=adapter.request_for(req))
    # A revoked grant cannot be revived. Separately, a previously selected
    # candidate rule can be narrowed without changing the immutable binding.
    with pytest.raises(psycopg.Error):
        with db.transaction():
            db.execute("UPDATE rag_candidate_use_grants SET active=true WHERE capture_id=%s",
                       (capture,))


def test_active_pointer_generation_change_invalidates_old_binding(db) -> None:  # type: ignore[no-untyped-def]
    from app.services.grounding.current_authorization import EvidenceDenied

    adapter, draft, req, _policy, old = setup_ready(db)
    selection = adapter.resolve_evidence(draft, (req,))
    binding, _ = adapter.freeze_binding(selection, node_id=req.node_id,
        goal_hash=req.goal_hash, purpose=req.demand.purpose, request=adapter.request_for(req))
    assert adapter.governance.repo.active("route.sql").corpus_id == old.corpus_id
    _second_adapter, _draft, _req, _policy2, successor = setup_ready(db)
    assert adapter.governance.repo.active("route.sql").corpus_id == successor.corpus_id
    with pytest.raises(EvidenceDenied, match="CORPUS_GENERATION_STALE"):
        adapter.check_current_authorization(binding, binding.purpose,
                                            request=adapter.request_for(req))
