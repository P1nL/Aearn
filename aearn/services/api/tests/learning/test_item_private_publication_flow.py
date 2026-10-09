"""Focused offline P7 seam checks. Doubles here are NOT real PG/OS admission.

No environment/provider/Docker/bootstrap is used. Main owns live acceptance.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aearn_shared.execution import RuntimeImageLockV1, RuntimeLimitProfileV1
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.private_publication_contracts import PrivatePracticeMaterializationV1
from app.services.learning.item_bank.private_publication_repository import PostgresPrivatePublicationRepository
from app.services.learning.item_bank.publication import LearningItemPublicationService, PrivatePublicationError, source_bindings
from app.services.learning.item_bank.practice_adapter import LEARNING_ITEM_PRACTICE_ADAPTER_VERSION
from app.services.learning.item_supply.admission_facts import AdmissionFactsOwner
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.pipeline import CompletedReview, ItemSupplyPipeline, PreparedReview
from app.services.learning.item_supply.private_supply import PrivateSupplyExposureOwner, PrivateSupplyRuntimeOwner, SupplyQuery
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvaluationV2
from app.services.learning.item_supply.sandbox.python_goal_scorer import PYTHON_GOAL_ID, compile_goal_tests, source_scorer_version
from app.services.learning.practice.contracts import ExerciseSourceKind
from app.services.learning.practice.quality import require_exercise_quality
from tests.learning.test_item_supply_admission_facts import source_fixture
from tests.learning.test_item_supply_autonomous_review import evidence, make_bundle, subject
from tests.learning.test_item_supply_contracts import make_blueprint, make_demand, make_scope
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request
from tests.learning.test_item_supply_python_completion_template import completion_source


class ConnectionDouble:
    def __init__(self, status=TransactionStatus.INTRANS):
        self.info = SimpleNamespace(transaction_status=status)
        self.calls = []

    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == TransactionStatus.IDLE
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql, args=()):
        self.calls.append((sql, args))
        return SimpleNamespace(fetchone=lambda: {"now": datetime.now(UTC)}, fetchall=lambda: [])


def repo_double(conn, user=None):
    # No fake repository is passed as genuine storage in a real operation. These
    # exact-class shells exercise only explicit monkeypatched orchestration seams.
    repo = object.__new__(PostgresPrivatePublicationRepository)
    repo.conn, repo.user_id, repo.expected_epoch = conn, user or uuid4(), 1
    return repo


def test_publication_default_off_and_nonconcrete_owner_fail_before_database():
    conn = ConnectionDouble()
    publisher = LearningItemPublicationService(conn, object())
    kwargs = dict(lease=None, facts_owner=None, facts_receipt=None, evaluation=None, evaluation_receipt_id=uuid4())
    with pytest.raises(PrivatePublicationError, match="DISABLED"):
        publisher.publish_internal_private(None, None, **kwargs)
    publisher.enabled = True
    with pytest.raises(PrivatePublicationError, match="OWNER_REQUIRED"):
        publisher.publish_internal_private(None, None, **kwargs)
    assert conn.calls == []


def test_materialization_preserves_python_goal_and_sql_private_contracts():
    for source in (completion_source(), source_fixture()):
        dto = PrivatePracticeMaterializationV1(user_id=uuid4(), epoch=1, scope_id=uuid4(), version_id=uuid4(),
            materialization_id=uuid4(), source=source, source_hash=source.source_hash,
            content_hash=source.content_hash, version_payload_hash="b" * 64,
            adapter_version=LEARNING_ITEM_PRACTICE_ADAPTER_VERSION, scorer_version=source_scorer_version(source),
            runtime_profile_id=source.blueprint.runtime_profile_id, runtime_profile_hash="c" * 64,
            created_at=datetime.now(UTC))
        material = dto.authority_material()
        require_exercise_quality(material.exercise, material.rubric)
        assert material.exercise.source_kind is ExerciseSourceKind.REGISTERED_AUTHOR
        assert dto.receipt_hash != dto.version_payload_hash
        if source.blueprint.language_id == "python":
            assert material.rubric.private_test_bundle == compile_goal_tests(source)
            assert all(case["input_json"]["goal_contract"] == PYTHON_GOAL_ID for case in material.rubric.private_test_bundle)
            assert tuple(material.runner_payload["test_cases"]) == material.rubric.private_test_bundle
        else:
            assert material.rubric.private_test_bundle == tuple(t.model_dump(mode="json") for t in source.private.content.tests)
        public = str(material.exercise.public_payload())
        assert "private_test_bundle" not in public and "reference_answer" not in public


def test_full_source_set_rejects_synthetic_or_changed_persisted_generation():
    request, payload = make_request()
    result = generate_candidate(request, provider=SyntheticProvider(payload), source_authority=SyntheticAuthority(), enabled=True)
    artifact = dict(request_json=request.model_dump(mode="json"), receipt_json=result.receipt.model_dump(mode="json"),
        source_json=result.source.model_dump(mode="json"), source_hash=result.source.source_hash,
        content_hash=result.source.content_hash, mode="synthetic")
    with pytest.raises(PrivatePublicationError, match="GENERATION_MISMATCH"):
        source_bindings(artifact, result.source)
    # This changes only a declared fixture shape; it never calls a RAG authority
    # or grants publication. The separate real-issuer gate must still be present.
    artifact["mode"] = "live"
    artifact["receipt_json"]["provider"]["mode"] = "provider"
    artifact["receipt_json"]["sources"][0]["mode"] = "current_authority"
    bindings = source_bindings(artifact, result.source)
    assert len(bindings) == 1 and bindings[0].material == request.materials[0]
    artifact["request_json"]["materials"][0]["excerpt"] += "changed"
    with pytest.raises(ValueError):
        source_bindings(artifact, result.source)


def test_pipeline_default_shape_and_precheckpoint_publisher_order(monkeypatch):
    import app.services.learning.item_supply.pipeline as module

    source, validation, binding = subject()
    bundle = make_bundle(source, validation, binding)
    conn, calls = ConnectionDouble(), []
    pipeline = ItemSupplyPipeline(conn, Settings())
    lease = SimpleNamespace(visibility="private")
    pipeline.runtime = SimpleNamespace(refresh_lease=lambda *a, **k: lease,
        checkpoint=lambda *a, **k: calls.append("checkpoint"))
    def store(**kwargs):
        calls.append(kwargs["kind"])
        return {"id": uuid4()}
    pipeline.artifacts = SimpleNamespace(get_generation=lambda **kwargs: {}, store_receipt=store)
    monkeypatch.setattr(pipeline, "_fence_source", lambda *a: None)
    owner = object.__new__(AdmissionFactsOwner)
    owner.conn = conn
    monkeypatch.setattr(AdmissionFactsOwner, "verify", lambda *a, **k: evidence(binding, validation))
    evaluation = AdmissionEvaluationV2(binding=binding, disposition="eligible_internal", safe_reasons=("publication_port_pending",))
    monkeypatch.setattr(module, "evaluate_admission_v2", lambda *a, **k: evaluation)
    prepared = PreparedReview(lease=lease, scope_id=uuid4(), artifact_id=uuid4(), source=source,
        validation=validation, binding=binding, author_identity="author", reservation_id=uuid4(), mode="live",
        attempt_bounds=(1,) * 7, provider_bindings=tuple((run.provider_identity.provider, run.provider_identity.model)
            for run in (bundle.blind_solve.run, *(r.run for r in bundle.reports))))
    completed = CompletedReview(bundle)
    receipt = object()
    assert pipeline.commit_review(prepared, completed, facts_owner=owner, facts_receipt=receipt) is evaluation
    assert calls == ["blind_solve", "review_bundle", "admission_evaluation", "checkpoint"]
    publisher = LearningItemPublicationService(conn, repo_double(conn), enabled=True)
    def publish(*a, **kw):
        assert kw["lease"] is lease and kw["facts_receipt"] is receipt
        assert kw["evaluation_receipt_id"] is not None and not kw["evaluation"].publication_enabled
        calls.append("publication")
    monkeypatch.setattr(LearningItemPublicationService, "publish_internal_private", publish)
    calls.clear()
    assert pipeline.commit_review(prepared, completed, facts_owner=owner, facts_receipt=receipt,
                                  private_publisher=publisher) is evaluation
    assert calls == ["blind_solve", "review_bundle", "admission_evaluation", "publication", "checkpoint"]
    def fail(*a, **kw):
        raise PrivatePublicationError("FINAL_FENCE_FAILED")
    monkeypatch.setattr(LearningItemPublicationService, "publish_internal_private", fail)
    calls.clear()
    with pytest.raises(PrivatePublicationError, match="FINAL_FENCE_FAILED"):
        pipeline.commit_review(prepared, completed, facts_owner=owner, facts_receipt=receipt, private_publisher=publisher)
    assert "checkpoint" not in calls  # Real transaction rollback is main's PG check.


def runtime_double(monkeypatch, conn):
    lock = RuntimeImageLockV1(runtime_id="python-stdout-v1", protocol_version="sandbox-input-v1",
        image_reference="example.test/aearn@sha256:" + "0123456789abcdef" * 4,
        fixed_entrypoint=("/opt/aearn/entrypoint.py",), non_root_user="10001:10001",
        limits=RuntimeLimitProfileV1(cpu_millis=1000, memory_mb=128, pids_limit=32, nofile_limit=128,
            wall_clock_seconds=10, max_output_bytes=8192, work_tmpfs_mb=16, temp_tmpfs_mb=8))
    calls = []
    runner = SimpleNamespace(_locks={lock.runtime_id: lock})
    def inspect(value):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        calls.append(value.fingerprint)
        return True
    runner._verify_image = inspect
    owner = PrivateSupplyRuntimeOwner(conn, runner=runner)
    # Only the trust boundary is stubbed; actual network/container tests forbidden.
    monkeypatch.setattr(owner, "_concrete_runner", lambda: runner)
    return owner, lock, calls


def test_runtime_observation_is_idle_single_use_and_lock_bound(monkeypatch):
    conn = ConnectionDouble(TransactionStatus.IDLE)
    owner, lock, calls = runtime_double(monkeypatch, conn)
    owner.observe(runtime_id=lock.runtime_id)
    conn.info.transaction_status = TransactionStatus.INTRANS
    owner.begin_query()
    owner.assert_matches(runtime_id=lock.runtime_id, fingerprints={lock.fingerprint}, now=datetime.now(UTC))
    with pytest.raises(PrivatePublicationError, match="STALE"):
        owner.assert_matches(runtime_id=lock.runtime_id, fingerprints={"0" * 64}, now=datetime.now(UTC))
    owner.finish_query()
    with pytest.raises(PrivatePublicationError, match="OBSERVATION_REQUIRED"):
        owner.begin_query()
    with pytest.raises(PrivatePublicationError, match="REQUIRES_IDLE"):
        owner.observe(runtime_id=lock.runtime_id)
    assert calls == [lock.fingerprint]
    naked = PrivateSupplyRuntimeOwner(ConnectionDouble(TransactionStatus.IDLE), runner=SimpleNamespace(_live=True))
    with pytest.raises(PrivatePublicationError, match="ACTUAL_RUNTIME_REQUIRED"):
        naked.observe(runtime_id=lock.runtime_id)


def test_exact_discovery_cannot_invent_exposure_or_whole_pack_readiness(monkeypatch):
    import app.services.learning.item_supply.private_supply as module

    conn = ConnectionDouble(TransactionStatus.IDLE)
    repo = repo_double(conn)
    runtime, lock, _ = runtime_double(monkeypatch, conn)
    runtime.observe(runtime_id=lock.runtime_id)
    conn.info.transaction_status = TransactionStatus.INTRANS
    blueprint = make_blueprint(make_scope(visibility="private", owner_ref="user:" + str(repo.user_id),
                                         runtime_profile_hash=lock.fingerprint))
    demand = make_demand(blueprint).model_copy(update={"learner_ref": "user:" + str(repo.user_id)})
    source = RagSourceAuthority(SimpleNamespace(conn=conn), object())
    exposure = PrivateSupplyExposureOwner(conn, user_id=repo.user_id, expected_epoch=1)
    query = SupplyQuery(conn, repo)
    now = datetime.now(UTC)
    proof = SimpleNamespace(user_id=repo.user_id, epoch=1, version_id=uuid4(), candidate_family_id="family:finite",
                            sources=(), checked_at=now - timedelta(seconds=1), valid_until=now + timedelta(seconds=10))
    record = SimpleNamespace(proof=proof)
    terminal = SimpleNamespace(lock_fingerprint=lock.fingerprint)
    facts = SimpleNamespace(coverage=SimpleNamespace(execution_terminals=(terminal,), blind_terminals=(terminal,)),
                            ambiguity=SimpleNamespace(terminals=(terminal,)))
    monkeypatch.setattr(query, "_demand", lambda *a: (demand, blueprint))
    monkeypatch.setattr(query, "_record", lambda *a, **k: facts)
    monkeypatch.setattr(repo, "load_exact", lambda **k: (record,))
    fences = []
    monkeypatch.setattr(module, "current_sources", lambda *a: fences.append("source"))
    result = query.query_exact(demand_id=uuid4(), scope_id=uuid4(), source_authority=source,
                              runtime_facts=runtime, exposure=exposure)
    assert result.status == "pending" and result.selected_handles == ()
    assert fences == ["source", "source"]
    assert [(g.slot, g.required, g.available) for g in result.gaps] == [
        ("practice", 2, 0), ("assessment", 2, 0), ("remediation", 1, 0)]
    assert "exposure_denied" in result.reasons
    assert not {"source", "private", "rubric", "tests", "provider"} & result.model_dump().keys()
    # Caller-supplied shape/boolean cannot replace the concrete exposure owner.
    with pytest.raises(PrivatePublicationError, match="CURRENT_OWNERS_REQUIRED"):
        query.query_exact(demand_id=uuid4(), scope_id=uuid4(), source_authority=source,
                          runtime_facts=runtime, exposure=SimpleNamespace(allowed=True))
