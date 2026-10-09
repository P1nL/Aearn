"""Eight offline/fixture checks, with caller-owned PG rollback and no bootstrap.

PG prepare/settle/store/checkpoints are real. Provider phases use an explicit
pure idle-connection/refresh seam, not a disguised active PG transaction; this
does not attest a committed cross-connection provider lifecycle.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.generation_contracts import ProviderUsageV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.pipeline import ItemSupplyPipeline, PreparedGeneration, PreparedReview
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import (
    RESOURCE_KINDS, CoverageObligationV1, ResourceAmounts, SupplyRuntimeError, derive_runtime_contract_hash,
)
from app.services.learning.item_supply.review_contracts_v2 import BlindScoreV2, CandidateBindingV2
from app.services.learning.item_supply.review_provider import JsonBlindSolverV2, JsonReviewerV2
from app.services.learning.item_supply.storage import (
    PostgresPrivateSupplyStorage, export_private_supply, purge_private_supply,
)
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.learning.item_supply.validation_adapter import validate_candidate
from tests.learning.test_item_supply_autonomous_review import FakeJsonClient, identity
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request
from tests.learning.test_item_supply_runtime import DSN, profile, retry_policy
from tests.learning.test_item_supply_storage import H, P, insert, scope


def enabled_settings():
    return Settings(learning_item_supply_enabled=True, learning_item_generation_enabled=True,
                    learning_item_network_enabled=True, learning_item_v2_admission_enabled=True)


class IdleConnection:
    """Pure lifecycle seam, never a wrapper around an active PG transaction."""

    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.refreshes = 0

    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == TransactionStatus.IDLE
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def refresh_lease(self, lease, *, now):
        assert self.info.transaction_status == TransactionStatus.INTRANS
        self.refreshes += 1
        return lease


def offline_runner():
    conn = IdleConnection()
    pipeline = ItemSupplyPipeline(conn, enabled_settings())
    pipeline.runtime = conn
    return pipeline, conn


class Provider(SyntheticProvider):
    def __init__(self, payload, *, idle=None, known=False):
        super().__init__(payload)
        self.idle, self.known = idle, known

    def generate(self, *, messages, limits, timeout_seconds):
        if self.idle is not None:
            assert self.idle.info.transaction_status == TransactionStatus.IDLE
            assert self.idle.refreshes > 0
        assert timeout_seconds > 0
        # Existing helper requires its pure profile's 1s timeout. This trusted
        # synthetic port also accepts the longer real P3 frozen profile timeout.
        response = super().generate(messages=messages, limits=limits, timeout_seconds=1.0)
        if self.known:
            usage = ProviderUsageV2(state="known", input_tokens=17, output_tokens=11, total_tokens=28)
            response = response.model_copy(update={"receipt": response.receipt.model_copy(update={"usage": usage})})
        return response


class Scorer:
    def score(self, source, *, answer):
        return BlindScoreV2(passed=answer in source.private.content.accepted_answers,
                            scorer_identity="fixture-scorer", scorer_version="fixture.v2",
                            receipt_hash=canonical_hash((source.content_hash, answer)))


class IdleJsonClient(FakeJsonClient):
    def complete_json(self, messages, **kwargs):
        assert self.idle.info.transaction_status == TransactionStatus.IDLE
        assert self.idle.refreshes > 0
        return super().complete_json(messages, **kwargs)


def review_ports(source, profile_hash, idle):
    roles = source.blueprint.publication_policy.required_review_roles
    clients = [IdleJsonClient(content={"answer": "prints_2"})] + [IdleJsonClient() for _ in roles]
    for client in clients:
        client.idle = idle
    kwargs = dict(profile_hash=profile_hash, timeout_seconds=1.0, max_output_tokens=1024)
    solver = JsonBlindSolverV2(clients[0], identity=identity("fixture-solver"), **kwargs)
    reviewers = tuple(JsonReviewerV2(client, role=role, identity=identity("fixture-" + role.value), **kwargs)
                      for role, client in zip(roles, clients[1:], strict=True))
    return solver, reviewers, clients


def pure_generation():
    request, payload = make_request()
    lease = JobLeaseV1(job_id=uuid4(), visibility="private", owner_id=uuid4(), owner_epoch=1,
                       lease_owner="worker.pipeline", generation=1, state_version=1,
                       expires_at=request.profile.parent_deadline_at,
                       parent_deadline=request.profile.parent_deadline_at, profile=request.profile)
    authority = SyntheticAuthority()
    prepared = PreparedGeneration(lease, uuid4(), request, uuid4(),
                                  tuple(authority.authorize(m) for m in request.materials), 1, "synthetic")
    return prepared, payload


def pure_review():
    generation, payload = pure_generation()
    source = LearningItemSourceV1.model_validate(payload)
    binding = CandidateBindingV2(candidate_key="fixture.candidate", version_key="fixture.version",
        source_hash=source.source_hash, content_hash=source.content_hash,
        policy_hash=AutonomousEvidencePolicyV2().policy_hash,
        profile_hash=generation.lease.profile.profile_hash, runtime_key="python-v1",
        risk_tier=source.blueprint.publication_policy.risk_tier)
    return PreparedReview(generation.lease, generation.scope_id, uuid4(), source,
                          validate_candidate(source), binding, "synthetic.item_author",
                          uuid4(), "synthetic", (1,) * 7)


@pytest.fixture
def conn():
    assert os.environ.get("DATABASE_URL") == DSN
    for key, value in (("PYTHON_DOTENV_DISABLED", "1"), ("LLM_TYPE", "disabled"),
                       ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")):
        assert os.environ.get(key) == value
    connection = psycopg.connect(DSN, row_factory=dict_row)
    try:
        assert connection.execute("SELECT current_database() AS db").fetchone()["db"] == "aearn_b1b_fixture_20260930"
        connection.execute("SET LOCAL statement_timeout=5000")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def private_pipeline(conn, *, request_cap=20):
    request, payload = make_request()
    user = insert(conn, "users", display_name="B1c pipeline synthetic")["id"]
    track = insert(conn, "tutor_learning_tracks", user_id=user, language_id="python",
                   goal_text="synthetic", target_level="basic")["id"]
    revision = insert(conn, "tutor_track_plan_revisions", track_id=track, user_id=user,
        status="active", title="synthetic", target_level="basic", plan_json={},
        generator_version="synthetic", policy_version="synthetic", change_reason="fixture",
        content_hash=H, activated_at=datetime.now(UTC))["id"]
    insert(conn, "tutor_track_active_plans", track_id=track, user_id=user, revision_id=revision)
    module = insert(conn, "tutor_track_plan_modules", revision_id=revision, track_id=track,
                    user_id=user, module_key="variables", title="synthetic", order_index=0)["id"]
    insert(conn, "tutor_track_plan_nodes", module_id=module, revision_id=revision, track_id=track,
           user_id=user, knowledge_key="python.variables", title="synthetic", description="rebindings", order_index=0)
    storage = PostgresPrivateSupplyStorage(conn, user_id=user, expected_epoch=1)
    contract = scope(user).model_copy(update={
        "knowledge_key": request.blueprint.knowledge_key, "item_kind": request.blueprint.item_kind,
        "purpose": request.blueprint.purpose, "interaction": request.blueprint.allowed_interactions[0],
        "required_facets": ("fundamentals",), "required_capabilities": tuple(request.blueprint.required_capabilities),
    })
    bound = storage.bind_scope(track_id=track, revision_id=revision, scope=contract)
    demand = AssessmentSupplyDemandV1(demand_id=f"demand.{uuid4().hex}", learner_ref=f"user:{user}",
        scope=contract, objective_hash=bound.objective_hash, blueprint_hash=H,
        matrix_hash=build_support_matrix().matrix_hash, policy_version=P, input_revision=1)
    demand_id = storage.store_demand(scope_id=bound.id, request_key=f"request.{uuid4().hex}", demand=demand)
    pipeline = ItemSupplyPipeline(conn, enabled_settings())
    obligation = CoverageObligationV1(blueprint_hash=H, scope_hash=bound.scope_hash,
        objective_hash=bound.objective_hash, purpose=contract.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(contract), visibility="private",
        policy_version=P, owner_id=user)
    root = pipeline.runtime.ensure_private_root(user_id=user, epoch=1, scope_id=bound.id,
        demand_id=demand_id, obligation=obligation, pool="enhancement", provider_key="provider.synthetic")
    now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    start, end = now - timedelta(seconds=1), now + timedelta(minutes=5)
    insert(conn, "tutor_item_supply_private_budget_windows", user_id=user, epoch=1, scope_id=bound.id,
        root_id=root, pool_key="enhancement", provider_key="provider.synthetic", window_start=start,
        window_end=end, request_cap=request_cap, token_cap=1_000_000, resource_cap=1_000_000)
    for kind in RESOURCE_KINDS:
        cap = 100 if kind == "requests" else 1_000_000
        for dimension, key in (("system", "item-supply"), ("provider", "provider.synthetic"),
                               ("window", "item-supply"), ("pool", "enhancement")):
            pipeline.budget.register_global_limit(dimension_kind=dimension, dimension_key=key,
                resource_kind=kind, window_start=start, window_end=end, cap_amount=cap)
        pipeline.budget.register_user_limit(user_id=user, epoch=1, resource_kind=kind,
            window_start=start, window_end=end, cap_amount=cap)
    execution_profile = profile()
    execution_profile = execution_profile.model_copy(update={"profile_key":
        execution_profile.profile_key.model_copy(update={"model_version": f"pipeline.{uuid4().hex}"})})
    job = pipeline.runtime.enqueue(root_id=root, stage_key=f"pipeline.{uuid4().hex}",
        profile=execution_profile, retry_policy=retry_policy(), now=now, priority=100, aging_seconds=60,
        visibility="private", user_id=user, epoch=1, scope_id=bound.id)
    lease = pipeline.runtime.claim(root_id=root, lease_owner="worker.pipeline", now=now,
        lease_seconds=60, visibility="private", user_id=user, epoch=1)
    assert lease is not None and lease.job_id == job
    request = request.model_copy(update={"scope_hash": bound.scope_hash, "profile": lease.profile})
    return SimpleNamespace(pipeline=pipeline, user=user, storage=storage, scope=bound,
                           lease=lease, request=request, payload=payload)


def stage_generation(fx, *, known=False):
    runner, idle = offline_runner()
    provider = Provider(fx.payload, idle=idle, known=known)
    prepared = fx.pipeline.prepare_generation(lease=fx.lease, scope_id=fx.scope.id,
        request=fx.request, provider=provider, source_authority=SyntheticAuthority(), mode="synthetic")
    assert prepared is not None
    with pytest.raises(PipelineRepositoryError, match="PROVIDER_IO_REQUIRES_IDLE_TRANSACTION"):
        fx.pipeline.run_generation(prepared, provider)
    result = runner.run_generation(prepared, provider)
    assert result.state == "staged"
    fx.pipeline.settle_generation(prepared, result)
    staged = fx.pipeline.commit_generation(prepared, result)
    assert staged.artifact_id is not None
    return prepared, result, staged.artifact_id


def prepare_review(fx, artifact_id, *, resources=None):
    runner, idle = offline_runner()
    source = LearningItemSourceV1.model_validate(fx.payload)
    solver, reviewers, clients = review_ports(source, fx.lease.profile.profile_hash, idle)
    prepared = fx.pipeline.prepare_review(lease=fx.lease, scope_id=fx.scope.id, artifact_id=artifact_id,
        mode="synthetic", resources=resources or ResourceAmounts(requests=7, input_tokens=100_000, output_tokens=7168),
        solver=solver, reviewers=reviewers)
    return prepared, runner, solver, reviewers, clients


def test_default_off_prepare_never_queries_or_invokes_ports():
    class NoIO:
        def __getattr__(self, name):
            raise AssertionError(f"disabled pipeline attempted IO: {name}")

    pipeline = ItemSupplyPipeline(NoIO(), Settings())
    assert pipeline.prepare_generation(lease=None, scope_id=None, request=None,
        provider=NoIO(), source_authority=NoIO()) is None
    assert pipeline.prepare_review(lease=None, scope_id=None, artifact_id=None,
        mode="synthetic", resources=None, solver=NoIO(), reviewers=()) is None
    # A profile model-version label alone is not a trusted model mapping.
    configured = profile()
    row = {"provider_key": configured.profile_key.provider, "profile_hash": configured.profile_hash,
           "profile_key": configured.profile_key.model_dump(mode="json")}
    fake = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: row))
    pending = ItemSupplyPipeline(fake, enabled_settings())
    lease = SimpleNamespace(job_id=uuid4(), owner_id=uuid4(), owner_epoch=1,
                            profile=SimpleNamespace(profile_hash=configured.profile_hash))
    with pytest.raises(PipelineRepositoryError, match="^PROVIDER_PROFILE_PLAN_PENDING$"):
        pending._provider_binding(lease, configured.profile_key.provider, "fixture-model")


def test_generation_run_requires_idle_and_frozen_bound_then_closes_read_tx():
    prepared, payload = pure_generation()
    pipeline, conn = offline_runner()
    provider = Provider(payload, idle=conn)
    conn.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(PipelineRepositoryError, match="PROVIDER_IO_REQUIRES_IDLE_TRANSACTION"):
        pipeline.run_generation(prepared, provider)
    conn.info.transaction_status = TransactionStatus.IDLE
    provider.request_attempt_bound = 2
    with pytest.raises(PipelineRepositoryError, match="PROVIDER_ATTEMPT_BOUND_CHANGED"):
        pipeline.run_generation(prepared, provider)
    assert provider.calls == conn.refreshes == 0
    provider.request_attempt_bound = 1
    assert pipeline.run_generation(prepared, provider).state == "staged"
    assert provider.calls == conn.refreshes == 1

    request, payload = make_request()
    result = generate_candidate(request, provider=SyntheticProvider(payload),
                                source_authority=SyntheticAuthority(), enabled=True)
    assert result.receipt is not None
    pipeline = ItemSupplyPipeline.__new__(ItemSupplyPipeline)
    pipeline.conn = object()
    # Rejection must happen before accessing budget/lease/any DB connection.
    prepared = SimpleNamespace(request=request, sources=result.receipt.sources, attempt_bound=1)
    foreign = result.model_copy(update={"receipt": result.receipt.model_copy(update={"candidate_id": uuid4()})})
    with pytest.raises(PipelineRepositoryError, match="^GENERATION_SETTLEMENT_IDENTITY_MISMATCH$"):
        pipeline.settle_generation(prepared, foreign)

    fake_authority = SimpleNamespace(connection=pipeline.conn, assert_current=lambda *args: None)
    with pytest.raises(PipelineRepositoryError, match="^SOURCE_AUTHORITY_REQUIRED$"):
        pipeline._fence_source({}, "live", fake_authority)


def test_review_run_requires_idle_and_exact_seven_port_bounds():
    prepared = pure_review()
    pipeline, conn = offline_runner()
    solver, reviewers, clients = review_ports(prepared.source, prepared.binding.profile_hash, conn)
    conn.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(PipelineRepositoryError, match="PROVIDER_IO_REQUIRES_IDLE_TRANSACTION"):
        pipeline.run_review(prepared, solver=solver, scorer=Scorer(), reviewers=reviewers)
    conn.info.transaction_status = TransactionStatus.IDLE
    clients[3].request_attempt_bound = 2
    with pytest.raises(PipelineRepositoryError, match="REVIEW_ATTEMPT_BOUND_CHANGED"):
        pipeline.run_review(prepared, solver=solver, scorer=Scorer(), reviewers=reviewers)
    assert conn.refreshes == 0 and not any(c.seen for c in clients)
    clients[3].request_attempt_bound = 1
    completed = pipeline.run_review(prepared, solver=solver, scorer=Scorer(), reviewers=reviewers)
    assert len(completed.bundle.reports) == 6 and completed.bundle.blind_solve.score.passed
    assert conn.refreshes == 1 and all(len(c.seen) == 1 for c in clients)
    for forbidden in ("accepted_answers", "answer_explanation_markdown", "hidden_incorrect", "reports"):
        assert forbidden not in clients[0].seen[0][1]["content"]


def test_pg_generation_validation_review_pending_receipts_and_unknown_usage(conn):
    fx = private_pipeline(conn)
    prepared, _, artifact_id = stage_generation(fx, known=True)
    validation = fx.pipeline.validate_generation(lease=fx.lease, scope_id=fx.scope.id,
                                                artifact_id=artifact_id, mode="synthetic")
    assert validation.state == "machine_verified"
    reviewed, runner, solver, reviewers, clients = prepare_review(fx, artifact_id)
    assert reviewed is not None and reviewed.attempt_bounds == (1,) * 7
    amounts = conn.execute("SELECT resource_kind,reserved_amount FROM tutor_item_supply_private_runtime_reservation_amounts WHERE reservation_id=%s",
                           (reviewed.reservation_id,)).fetchall()
    assert dict((r["resource_kind"], r["reserved_amount"]) for r in amounts)["requests"] == 7
    completed = runner.run_review(reviewed, solver=solver, scorer=Scorer(), reviewers=reviewers)
    fx.pipeline.settle_review(reviewed, completed)
    evaluation = fx.pipeline.commit_review(reviewed, completed)
    assert not evaluation.publication_enabled and evaluation.disposition != "eligible_internal"
    assert "source" in " ".join(evaluation.safe_reasons)
    rows = conn.execute("SELECT artifact_kind,payload_json,publication_enabled FROM tutor_item_supply_private_pipeline_receipts WHERE generation_artifact_id=%s", (artifact_id,)).fetchall()
    assert {r["artifact_kind"] for r in rows} == {"validation", "blind_solve", "review_bundle", "admission_evaluation"}
    assert all(not r["publication_enabled"] for r in rows)
    assert "answer" not in next(r["payload_json"] for r in rows if r["artifact_kind"] == "blind_solve")
    settlements = conn.execute("SELECT reservation_id,usage_state,cost_amount FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id IN (%s,%s)",
                               (prepared.reservation_id, reviewed.reservation_id)).fetchall()
    assert {str(r["reservation_id"]): r["usage_state"] for r in settlements} == {
        str(prepared.reservation_id): "known", str(reviewed.reservation_id): "unknown"}
    assert all(r["cost_amount"] is None for r in settlements)
    current = fx.pipeline.runtime.refresh_lease(fx.lease, now=datetime.now(UTC))
    assert fx.pipeline.runtime.next_stage(current) == "investigating"
    assert all(len(c.seen) == 1 for c in clients)


def test_pg_bounded_reservation_and_underfunded_review_do_not_call_ports(conn):
    fx = private_pipeline(conn, request_cap=1)
    with pytest.raises(PipelineRepositoryError, match="PROVIDER_PROFILE_PLAN_PENDING"):
        fx.pipeline._provider_binding(fx.lease, "provider.synthetic", "fixture-model")
    key = conn.execute(
        "SELECT p.profile_json->'profile_key' AS key FROM tutor_item_supply_private_job_controls c "
        "JOIN tutor_item_supply_parameter_profiles p ON p.id=c.profile_id WHERE c.job_id=%s",
        (fx.lease.job_id,),
    ).fetchone()["key"]
    bound = ItemSupplyPipeline(conn, enabled_settings(), trusted_model_bindings={
        (key["provider"], key["model_version"]): "fixture-model"})
    assert bound._provider_binding(fx.lease, "provider.synthetic", "fixture-model") == (
        "provider.synthetic", "fixture-model")
    with pytest.raises(PipelineRepositoryError, match="PROVIDER_BUDGET_BINDING_MISMATCH"):
        bound._provider_binding(fx.lease, "different-provider", "fixture-model")
    provider = Provider(fx.payload)
    provider.request_attempt_bound = 3
    assert fx.pipeline.prepare_generation(lease=fx.lease, scope_id=fx.scope.id, request=fx.request,
        provider=provider, source_authority=SyntheticAuthority(), mode="synthetic") is None
    assert provider.calls == 0
    provider.request_attempt_bound = 1
    _, _, artifact_id = stage_generation(fx)
    fx.pipeline.validate_generation(lease=fx.lease, scope_id=fx.scope.id, artifact_id=artifact_id, mode="synthetic")
    with pytest.raises(PipelineRepositoryError, match="REVIEW_RESOURCE_PLAN_INCOMPLETE"):
        prepare_review(fx, artifact_id, resources=ResourceAmounts(requests=6, input_tokens=100, output_tokens=100))
    prepared, _, _, _, clients = prepare_review(fx, artifact_id)
    assert prepared is None and not any(c.seen for c in clients)
    assert conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_reservations WHERE job_id=%s", (fx.lease.job_id,)).fetchone()["n"] == 1


def test_pg_generation_and_typed_receipt_immutable_replay_conflict(conn):
    fx = private_pipeline(conn)
    prepared, result, artifact_id = stage_generation(fx)
    assert fx.pipeline.commit_generation(prepared, result).artifact_id == artifact_id
    changed = result.model_copy(update={"receipt": result.receipt.model_copy(update={
        "provider": result.receipt.provider.model_copy(update={"run_id": uuid4()})})})
    with pytest.raises(PipelineRepositoryError, match="PIPELINE_GENERATION_CONFLICT"):
        fx.pipeline.commit_generation(prepared, changed)
    validation = fx.pipeline.validate_generation(lease=fx.lease, scope_id=fx.scope.id,
                                                artifact_id=artifact_id, mode="synthetic")
    lease = fx.pipeline.runtime.refresh_lease(fx.lease, now=datetime.now(UTC))
    kwargs = dict(lease=lease, scope_id=fx.scope.id, artifact_id=artifact_id, kind="validation",
                  artifact_key=f"validation.{artifact_id.hex}", now=datetime.now(UTC), mode="synthetic")
    first = fx.pipeline.artifacts.store_receipt(payload=validation, **kwargs)
    assert fx.pipeline.artifacts.store_receipt(payload=validation, **kwargs)["id"] == first["id"]
    conflicting = validation.model_copy(update={"checks": (validation.checks[0].model_copy(
        update={"proof_hash": canonical_hash("changed-proof")}),) + validation.checks[1:]})
    with pytest.raises(PipelineRepositoryError, match="PIPELINE_RECEIPT_CONFLICT"):
        fx.pipeline.artifacts.store_receipt(payload=conflicting, **kwargs)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE tutor_item_supply_private_generation_artifacts SET artifact_key='changed' WHERE id=%s", (artifact_id,))
    assert conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_generation_artifacts WHERE job_id=%s", (fx.lease.job_id,)).fetchone()["n"] == 1
    # Direct SQL must reject stale source identity too, not merely Python callers.
    with pytest.raises(psycopg.errors.CheckViolation, match="pipeline receipt identity mismatch"):
        with conn.transaction():
            conn.execute(
                "INSERT INTO tutor_item_supply_private_pipeline_receipts "
                "(user_id,epoch,scope_id,job_id,lease_generation,lease_state_version,generation_artifact_id,"
                "version_id,content_hash,artifact_key,artifact_kind,schema_version,mode,payload_json) "
                "SELECT user_id,epoch,scope_id,job_id,lease_generation,%s,generation_artifact_id,"
                "version_id,content_hash,'validation.stale-source',artifact_kind,schema_version,mode,"
                "jsonb_set(payload_json,'{source_hash}',to_jsonb(%s::text)) "
                "FROM tutor_item_supply_private_pipeline_receipts WHERE id=%s",
                (lease.state_version, canonical_hash("stale-source"), first["id"]),
            )


def test_pg_lost_lease_can_settle_original_cost_but_cannot_store_candidate(conn):
    fx = private_pipeline(conn)
    runner, idle = offline_runner()
    provider = Provider(fx.payload, idle=idle)
    prepared = fx.pipeline.prepare_generation(lease=fx.lease, scope_id=fx.scope.id, request=fx.request,
        provider=provider, source_authority=SyntheticAuthority(), mode="synthetic")
    assert prepared is not None
    result = runner.run_generation(prepared, provider)
    conn.execute("UPDATE tutor_item_supply_private_job_controls SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (fx.lease.job_id,))
    fx.pipeline.settle_generation(prepared, result)
    fx.pipeline.settle_generation(prepared, result)
    with pytest.raises(SupplyRuntimeError, match="LEASE_STALE"):
        fx.pipeline.commit_generation(prepared, result)
    assert conn.execute("SELECT usage_state FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=%s", (prepared.reservation_id,)).fetchone()["usage_state"] == "unknown"
    assert conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_generation_artifacts WHERE job_id=%s", (fx.lease.job_id,)).fetchone()["n"] == 0


def test_pg_private_export_and_reset_remove_artifacts_and_fence_old_epoch(conn):
    fx = private_pipeline(conn)
    prepared, result, artifact_id = stage_generation(fx)
    fx.pipeline.validate_generation(lease=fx.lease, scope_id=fx.scope.id, artifact_id=artifact_id, mode="synthetic")
    exported = export_private_supply(conn, fx.user)
    assert len(exported["tutor_item_supply_private_generation_artifacts"]["records"]) == 1
    assert len(exported["tutor_item_supply_private_pipeline_receipts"]["records"]) == 1
    projection = json.dumps(exported, default=str)
    for secret in ("accepted_answers", "receipt_json", "request_json", "source_json", result.source.content_hash):
        assert secret not in projection
    assert purge_private_supply(conn, fx.user) == 2
    assert conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_generation_artifacts WHERE user_id=%s", (fx.user,)).fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_pipeline_receipts WHERE user_id=%s", (fx.user,)).fetchone()["n"] == 0
    with pytest.raises(SupplyRuntimeError, match="LEASE_STALE"):
        fx.pipeline.commit_generation(prepared, result)
    assert export_private_supply(conn, fx.user)["epoch"]["epoch"] == 2
