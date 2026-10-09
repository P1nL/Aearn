"""Three OFFLINE protocol cases; local stub seals/rows are not live authority."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from html import escape
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from psycopg.pq import TransactionStatus
from psycopg.errors import CheckViolation, LockNotAvailable

from app.services.grounding.autonomous.actual_d_finite_source import read_actual_d_finite_scope
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
from app.services.grounding.autonomous.capture_provenance_composition import PinnedCaptureProvenanceComposition
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, SubjectScope
from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from app.services.grounding.autonomous.source_assessment_profiles import (
    ACTUAL_D_DOMAIN, PYTHON_AUGMENTED, PYTHON_BINDING, PYTHON_RHS, PYTHON_STATEMENTS_URL,
    PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment, SignedSourceAssessment,
    SourceAssessmentDenied, SourceAssessmentRun, canonical_source_payload, run_source_assessment,
    sign_source_assessment, storage_profile_id, verify_source_assessment,
)
from app.services.grounding.autonomous.source_review_repository import CompleteCapture, SourceReviewRepository
from app.services.grounding.autonomous.sqlite_predicate_source_profile import SQLITE_ASSERTIONS, SQLITE_CAPTURE_URLS
from app.services.grounding.material_binding_repository import goal_hash_for_node
from app.services.grounding.material_contracts_v2 import DraftScope, MaterialSelectionResult, digest
from app.services.grounding.public_course_contracts import public_course_demand
from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.item_supply.finite_course_mapping import finite_node_description
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.plan_drafting import CompactPlanModule, CompactPlanProfile, build_plan_draft
from tests.grounding.test_course_material_lifetime import ProtocolStub

NOW = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)


class OfflineD:
    autocommit = False

    def __init__(self, target_id):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.target_id = target_id
        target = get_finite_course_target(target_id)
        self.target = target
        profile = CompactPlanProfile(language_id=target.language_id, goal_text="Finite offline protocol",
            target_level="beginner", weekly_minutes=60, experience_level="beginner", pace_summary="bounded", title="Course")
        modules = tuple(CompactPlanModule.model_validate(dict(module_key="module."+key, title=key, nodes=[dict(
            knowledge_key="course."+key, title=key, description=description,
            required_capabilities=list(target.required_capabilities))])) for key, description in (
                ("base", "Source protocol prerequisite"), ("target", finite_node_description(target_id))))
        artifact = build_plan_draft(profile=profile, modules=modules, sources=(), change_reason="offline source test")
        self.scope = DraftScope(user_id=str(uuid4()), session_id=str(uuid4()), conversation_id=str(uuid4()),
            draft_id=str(uuid4()), draft_version=2, content_hash=artifact.content_hash,
            source_run_id=str(uuid4()), source_input_revision=3)
        s = self.scope
        self.parent = dict(id=s.draft_id, user_id=s.user_id, session_id=s.session_id,
            draft_version=s.draft_version, content_hash=s.content_hash, source_run_id=s.source_run_id,
            source_input_revision=s.source_input_revision, run_conversation_id=s.conversation_id,
            profile_json=profile.model_dump(mode="json"), plan_json=canonical_plan_payload(artifact.plan),
            source_summary_json=[], generator_version=artifact.plan.generator_version,
            policy_version=artifact.plan.policy_version, change_reason=artifact.plan.change_reason)
        self.session = dict(id=s.session_id, user_id=s.user_id, conversation_id=s.conversation_id,
            current_draft_id=s.draft_id, status="draft_ready", confirmed_track_id=str(uuid4()))
        self.run = dict(user_id=s.user_id, conversation_id=s.conversation_id, input_revision=s.source_input_revision)
        self.active = dict(plan_json=self.parent["plan_json"], content_hash=artifact.plan.content_hash, language_id=target.language_id)
        requirements, entries = [], []
        for module in self.parent["plan_json"]["modules"]:
            for node in module["nodes"]:
                demand = LearningMaterialDemand(scope=SubjectScope(subject_id=target.subject_id, subject_version="1.0",
                    facets=target.required_facets), demand_hash=digest(node["knowledge_key"]), plan_ref="draft."+s.draft_id,
                    node_ref="node."+node["knowledge_key"], draft_revision=s.draft_version,
                    purpose="main_teaching", reading_level="beginner", language="zh")
                requirements.append(dict(node_id=node["knowledge_key"], goal_hash=goal_hash_for_node(node),
                    prerequisites=node["prerequisite_keys"], demand=demand.model_dump(mode="json")))
                entries.append(dict(node_id=node["knowledge_key"], goal_hash=goal_hash_for_node(node), purpose="main_teaching",
                    status="gap", covered_facets=[], gaps=["missing_material"], evidence=[], preparation_job_id=None))
        payload = dict(contract_version="rag_d_selection_v2", handle="selection."+"a"*32,
            draft=s.model_dump(mode="json"), requirements=requirements, entries=entries)
        self.selection = MaterialSelectionResult.model_validate_json(json.dumps({**payload, "selection_digest":digest(payload)}))
        self.roots, self.policies, self.captures = {}, {}, {}
        self.writes = []
        self.d_writer_locked = False
        self.owner_deleted = False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        if q.startswith(("INSERT", "UPDATE", "DELETE")):
            self.writes.append(q)
            raise AssertionError("source write not expected in offline stale check")
        if q == "SHOW transaction_isolation":
            row = {"transaction_isolation":"read committed"}
        elif q == "SHOW transaction_read_only":
            row = {"transaction_read_only":"off"}
        elif "current_database()" in q:
            row = {"name":"aearn_b1d_sandbox_20261001"}
        elif "clock_timestamp()" in q:
            row = {"now":NOW}
        elif "to_regprocedure" in q:
            row = {"installed":getattr(self,"installed",True)}
        elif "to_regclass('public.rag_actual_d_private_provenance')" in q:
            row = {"installed":getattr(self,"provenance_installed",True)}
        elif "rag_actual_d_private_epoch" in q:
            owner, expected_epoch, _ = params
            epoch = getattr(self,"epoch",1)
            if (str(owner) != self.scope.user_id or self.owner_deleted or not getattr(self,"epoch_enabled",True)
                    or getattr(self,"reset_pending",False) or expected_epoch is not None and expected_epoch != epoch):
                raise CheckViolation("offline owner/epoch context denied")
            row = {"epoch":epoch}
        elif "FROM users" in q:
            row = None if self.owner_deleted else {"id":self.scope.user_id}
        elif "FROM tutor_learning_plan_sessions" in q:
            if self.d_writer_locked and "NOWAIT" in q:
                raise LockNotAvailable("offline concurrent D writer")
            row = self.session
        elif "FROM tutor_learning_plan_drafts" in q:
            row = self.parent
        elif "FROM tutor_runs" in q:
            row = self.run
        elif "FROM tutor_track_active_plans" in q:
            row = self.active
        elif "FROM rag_material_selections" in q:
            row = dict(snapshot_json=self.selection.model_dump(mode="json"), selection_digest=self.selection.selection_digest)
        elif "FROM rag_budget_authority_roots" in q:
            row = self.roots[params[0]]
        else:
            raise AssertionError("unexpected offline query: "+q)
        return SimpleNamespace(fetchone=lambda:row)

    def args(self):
        return dict(draft=self.scope, base_selection_handle=self.selection.handle,
                    node_id="course.target", target_id=self.target_id)


def repository(monkeypatch, conn):
    if conn.target.language_id == "sql":
        bodies = {role: ("<html><body>"+"".join("<p>"+texts[0]+"</p>" for texts in statements.values())+"</body></html>").encode()
                  for role, statements in SQLITE_ASSERTIONS.items()}
        urls = SQLITE_CAPTURE_URLS
    else:
        statements = [PYTHON_BINDING, PYTHON_RHS]
        if conn.target_id == "python-state-update-v1":
            statements.append(PYTHON_AUGMENTED)
        bodies = {"select":("<html><body>"+"".join("<p>"+escape(text)+"</p>" for text in statements)+"</body></html>").encode()}
        urls = {"select":PYTHON_STATEMENTS_URL}
    for role, body in bodies.items():
        content_hash = hashlib.sha256(body).hexdigest()
        c = CompleteCapture(uuid4(), "registered", body, content_hash, content_hash,
            SubjectScope(subject_id=conn.target.subject_id, subject_version="1.0", facets=conn.target.required_facets),
            "source."+role, urls[role], (urls[role],), "official", "beginner", "public-license-test")
        conn.captures[role] = c
        until = NOW + timedelta(days=3 if role == "expression" else 9)
        conn.policies[c.capture_id] = dict(root_id="root."+role, policy_id="policy."+role, policy_generation=1,
            allowed_usages=["assessment_evidence"], immutable_history_allowed=True, expires_at=until,
            policy_retention=until, retention_until=until, storage_receipt_id="store."+role)
        conn.roots["root."+role] = dict(root_id="root."+role, delegation_id="delegation."+role,
            delegation_generation=1, delegation_expires_at=until, period_end=until)
    by_id = {c.capture_id:c for c in conn.captures.values()}
    monkeypatch.setattr(SourceReviewRepository, "_capture", lambda _self, cid, *_a: (by_id[cid], conn.policies[cid]))
    monkeypatch.setattr(PostgresCurrentCaptureProvenanceResolver, "resolve", lambda *_a: "2"*64)
    resolvers = {}
    for c in conn.captures.values():
        resolver = object.__new__(PostgresCurrentCaptureProvenanceResolver)
        resolver.conn = conn
        resolvers[c.capture_id] = resolver
    provenance = PinnedCaptureProvenanceComposition(conn, captures=resolvers) if len(resolvers)>1 else next(iter(resolvers.values()))
    return AssessmentReceiptRepository(conn, service_keys={"service.test":b"x"*32}, provenance=provenance, enabled=True,
                                       actual_d_private_provenance_enabled=True)


def prepare(repo, conn):
    companions = ((conn.captures["expression"].capture_id, conn.captures["corefunc"].capture_id)
                  if "expression" in conn.captures else None)
    return repo.prepare_actual_d(capture_id=conn.captures["select"].capture_id, document_handle="document.actual-d-test",
                                 companion_capture_ids=companions, **conn.args())


def sign(repo, q):
    runner = ProtocolStub(public_course_source_request(q.actual_d.target_id)[1])
    run = run_source_assessment(q, runner=runner, run_id=q.actual_d.oracle_run_id)
    key = Ed25519PrivateKey.generate()
    receipt = sign_source_assessment(run, runner=runner, service_key_id="service.test", private_key=key, now=NOW)
    repo.service_keys = {"service.test":key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    return receipt, runner, key


def test_actual_d_python_new_identity_nonce_and_no_public_proof_relabel(monkeypatch):
    for target_id in ("python-state-update-v1", "python-kc-binding-v1"):
        conn = OfflineD(target_id)
        repo = repository(monkeypatch, conn)
        q = prepare(repo, conn)
        assert type(q) is PreparedActualDSourceAssessment and q.consume_actor == "service.rag-assessment"
        assert q.actual_d.draft == conn.scope and q.demand.plan_ref == "draft."+conn.scope.draft_id
        assert q.execution_scope == public_course_execution_scope(target_id)
        assert q.demand != public_course_demand(target_id) and q.authority_expires_at == NOW+timedelta(days=7)
        signed, runner, key = sign(repo, q)
        assert signed.payload.format == "aearn.rag.actual-d-finite-source.v3"
        assert canonical_source_payload(signed.payload).startswith(ACTUAL_D_DOMAIN)
        assert SignedSourceAssessment.model_validate_json(signed.model_dump_json()) == signed
        assert verify_source_assessment(signed, service_keys=repo.service_keys, now=NOW) == signed.payload
        assert repo._verify_current(signed, for_issuance=True)[0] == signed.payload
        repeated = prepare(repo, conn)
        assert repeated.demand == q.demand and repeated.actual_d.oracle_run_id != q.actual_d.oracle_run_id
        with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_RUN_DENIED"):
            run_source_assessment(repeated, runner=runner, run_id=q.actual_d.oracle_run_id)
        with pytest.raises(SourceAssessmentDenied, match="REPOSITORY_REQUIRED"):
            repo.prepare(capture_id=q.capture_id, document_handle="document.bypass", demand=q.demand, profile_id=q.profile_id)
        public = repo.prepare(capture_id=q.capture_id, document_handle="document.public-test",
            demand=public_course_demand(target_id), profile_id=storage_profile_id(q))
        old_runner = ProtocolStub(public_course_source_request(target_id)[1])
        old_run = run_source_assessment(public, runner=old_runner, run_id=uuid4())
        with pytest.raises(SourceAssessmentDenied, match="TERMINAL_DENIED"):
            sign_source_assessment(SourceAssessmentRun(q, old_run.terminal), runner=old_runner,
                service_key_id="service.test", private_key=key, now=NOW)
        conn.run["input_revision"] += 1
        with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
            repo.persist(signed)
        assert conn.writes == []


def test_actual_d_current_goal_selection_and_confirmed_frozen_plan_fences(monkeypatch):
    conn = OfflineD("python-state-update-v1")
    repo = repository(monkeypatch, conn)
    q = prepare(repo, conn)
    signed, _, _ = sign(repo, q)
    # Primary capture/root lasts nine days, but this signed proof lasts seven.
    # A clock advancing during lock waits must not leave the earlier signature
    # currentness check authoritative at the final capture read.
    late = NOW + timedelta(days=8)
    ticks = iter((NOW, NOW, late))
    with monkeypatch.context() as waiting:
        waiting.setattr(repo, "_clock", lambda: next(ticks, late))
        with pytest.raises(SourceAssessmentDenied, match="AUTHORITY_STALE"):
            repo._verify_current(signed)
    conn.owner_deleted = True
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        repo._verify_current(signed)
    conn.owner_deleted = False
    conn.d_writer_locked = True
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        repo._verify_current(signed)
    conn.d_writer_locked = False
    wrong = conn.args() | {"target_id":"python-kc-binding-v1"}
    with pytest.raises(ValueError, match="semantics mismatch"):
        read_actual_d_finite_scope(conn, **wrong, oracle_run_id=uuid4())
    conn.session["status"] = "confirmed"
    assert repo._verify_current(signed)[0] == signed.payload
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        repo.persist(signed)
    conn.active["content_hash"] = "0"*64
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        repo._verify_current(signed)
    conn.session["status"] = "draft_ready"
    conn.parent["plan_json"]["modules"][1]["nodes"][0]["title"] = "changed node goal"
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        prepare(repo, conn)
    assert conn.writes == []


def test_actual_d_sqlite_three_capture_minimum_and_additive_bootstrap_contract(monkeypatch):
    conn = OfflineD("sqlite-predicate-order-v1")
    repo = repository(monkeypatch, conn)
    q = prepare(repo, conn)
    assert type(q) is PreparedActualDSQLiteSourceAssessment and len(q.companions) == 2
    assert q.execution_scope == public_course_execution_scope(conn.target_id)
    assert q.authority_expires_at == NOW+timedelta(days=3)
    signed, _, _ = sign(repo, q)
    assert repo._verify_current(signed, for_issuance=True)[0] == signed.payload
    conn.roots["root.expression"]["delegation_expires_at"] = NOW+timedelta(days=2)
    with pytest.raises(SourceAssessmentDenied, match="AUTHORITY_STALE"):
        repo.persist(signed)
    with pytest.raises(ValueError):
        PreparedActualDSourceAssessment.model_validate(q.model_dump(exclude={"companions"}))
    schema = Path(__file__).parents[2]/"app"/"db"/"schema"
    migration = (schema/"499_rag_actual_d_finite_source.sql").read_text(encoding="utf8")
    assert "499 requires exact497 or499 source guard" in migration
    assert "DROP CONSTRAINT" not in migration and "ALTER TABLE" not in migration
    assert "rag_actual_d_finite_storage_profile" in migration and "FOR SHARE" in migration
    assert "actual D source proof expired after locks" in migration
    assert "actual D active source owner missing" in migration and "deleted_at IS NULL" in migration
    assert "a547c4cf6f0710e894f294380f40f351" in migration  # Parenthesized final488 ->497 ->499 guard.
    # PL/pgSQL IF's THEN must not terminate a bare scalar CASE expression.
    assert "(CASE WHEN expected_language='sql' THEN '[\"queries\"]'::jsonb ELSE '[\"fundamentals\"]'::jsonb END) THEN" in migration
    assert "'(CASE WHEN proof->>''format''" in migration
    assert "ELSE prepared->>''profile_id'' END) IS DISTINCT FROM NEW.profile_id'" in migration
    assert "IS DISTINCT FROM (CASE WHEN proof->>''format''" in migration
    assert "ELSE ''source_assessment_oracle'' END)'" in migration
    assert "SELECT CASE profile" in migration and "  CASE q->>'profile_id'" in migration
    assert hashlib.sha256((schema/"497_rag_course_material_lifetime.sql").read_text(encoding="utf8").encode()).hexdigest() == "8f21834c37d24a8963ed41c3ae73d4011f5a6e5c2caec9d23fa0f29282b21efb"
    for target_id in ("python-state-update-v1", "python-kc-binding-v1", "sqlite-predicate-order-v1"):
        assert get_finite_course_target(target_id).definition_hash in migration
        assert hashlib.sha256(finite_node_description(target_id).encode()).hexdigest() in migration
    assert conn.writes == []
