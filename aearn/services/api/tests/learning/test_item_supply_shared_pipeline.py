"""Four offline seam checks only: no PG, Docker, provider network or live authority.

The concrete source/provider adapters have explicitly synthetic ports in this
file. Their DTO labels do not attest real C authorization or database guards.
"""
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash, learning_item_uuid
from app.services.learning.item_supply.budget import ReservationResult
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.finite_candidate_factory import build_finite_generation_request
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.generation_contracts import GenerationDemandBindingV1, SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
from app.services.learning.item_supply.shared_pipeline_contracts import match_shared_request, native_request
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request
from tests.learning.test_item_supply_shared_validation import _candidate


def inputs(target_id="python-kc-binding-v1"):
    # Native source coordinates alone do not attest a generic KC task. Reuse
    # registered finite public semantics and explicitly OFFLINE private truth.
    spec, materials, source = _candidate(target_id)
    base, _ = make_request()
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile,
        limits=base.limits, materials=materials)
    lease = JobLeaseV1(job_id=uuid4(), visibility="public", lease_owner="worker.shared.offline", generation=1,
        state_version=1, expires_at=request.profile.parent_deadline_at,
        parent_deadline=request.profile.parent_deadline_at, profile=request.profile)
    return request, source.model_dump(mode="json"), spec.coverage_blueprint, lease


class OfflineConnection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.row = None
        self.policy_binding = None
        self.statements = []

    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == TransactionStatus.IDLE
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql, params=()):
        assert self.info.transaction_status == TransactionStatus.INTRANS
        self.statements.append(sql)
        if "to_regclass" in sql:
            row = {"table_id": "tutor_item_supply_shared_generation_policy_bindings"}
        elif sql.startswith("INSERT INTO tutor_item_supply_shared_generation_policy_bindings"):
            payload = params[-1].obj
            self.policy_binding = dict(payload_json=payload, payload_hash=canonical_hash(payload),
                candidate_id=params[0],root_id=params[1],job_id=params[2],lease_generation=params[3],
                request_hash=params[4],profile_hash=params[5],policy_hash=params[6])
            row = None
        elif "FROM tutor_item_supply_shared_generation_policy_bindings" in sql:
            row = self.policy_binding
        elif "FROM tutor_item_supply_shared_reservations" in sql:
            row = None  # No old author allowance may be upgraded.
        elif "current_database()" in sql:
            row = {"db": "aearn_b1d_sandbox_20261001"}
        elif sql.startswith("INSERT INTO tutor_item_supply_shared_generation_artifacts"):
            if self.row is None:
                names = ("root_id", "blueprint_id", "job_id", "lease_owner", "lease_generation", "lease_state_version",
                    "reservation_id", "candidate_id", "item_id", "version_id", "target_id", "target_definition_hash",
                    "artifact_key", "source_hash", "content_hash", "source_json", "receipt_json", "request_json")
                self.row = dict(zip(names, params, strict=True))
                for key in ("source_json", "receipt_json", "request_json"):
                    self.row[key] = self.row[key].obj
                self.row.update(id=uuid4(), artifact_hash=canonical_hash({
                    "source": self.row["source_json"], "receipt": self.row["receipt_json"], "request": self.row["request_json"]}))
                row = self.row
            else:
                row = None
        elif "SELECT * FROM tutor_item_supply_shared_generation_artifacts" in sql:
            row = self.row
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row)


def setup(monkeypatch, *, model="fixture", usage=True):
    request, payload, coverage, lease = inputs()
    conn = OfflineConnection()
    calls, settlements, checkpoints = [], [], []
    settings = Settings(llm_type="deepseek", deepseek_api_key="offline-not-a-secret",
        deepseek_base_url="https://invalid.example", deepseek_model="fixture", llm_timeout_seconds=1,
        learning_item_supply_enabled=True, learning_item_generation_enabled=True, learning_item_network_enabled=True)

    def transport(url, headers, body, timeout):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        calls.append(body)
        result = {"model": model, "choices": [{"message": {"content": json.dumps(payload)}}]}
        if usage:
            result["usage"] = {"prompt_tokens": 17, "completion_tokens": 11}
        return result

    provider = OpenAICompatibleGenerationProvider(settings, transport=transport)
    pipeline = SharedGenerationPipeline(conn, settings, enabled=True,
        trusted_model_bindings={(provider.provider_key, "fixture-version"): "fixture"})
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    receipts = tuple(SourceReceiptV2(material_digest=material_digest(m), binding_digest=m.binding.binding_digest,
        corpus_version_id=UUID(m.binding.evidence[0].corpus_version_id), active_generation=m.binding.evidence[0].active_generation,
        checked_at_iso=datetime.now(UTC).isoformat(), claim_receipt_hashes=(m.binding.evidence[0].claim_receipt_hash,),
        mode="current_authority") for m in request.materials)
    monkeypatch.setattr(authority, "authorize", lambda m: receipts[0])
    monkeypatch.setattr(authority, "assert_current", lambda m, r: r)
    meta = dict(root_id=uuid4(), blueprint_id=uuid4(), provider_key=provider.provider_key, coverage=coverage,
                key=SimpleNamespace(provider=provider.provider_key, model_version="fixture-version"))

    def context(value, *, now):
        pipeline.artifacts.require_owner()
        assert value == lease
        return meta

    monkeypatch.setattr(pipeline.artifacts, "context", context)
    rid = uuid4()
    monkeypatch.setattr(pipeline.budget, "reserve", lambda **kw: ReservationResult(True, "RESERVED", rid))
    monkeypatch.setattr(pipeline.artifacts, "reservation", lambda *a, **kw: rid)
    monkeypatch.setattr(pipeline.budget, "settle", lambda **kw: settlements.append(kw))
    monkeypatch.setattr(pipeline.runtime, "next_stage", lambda value: "generating")
    monkeypatch.setattr(pipeline.runtime, "_control", lambda *a, **kw: {"attempt_count": 1})
    monkeypatch.setattr(pipeline.artifacts.runtime, "_control", lambda *a, **kw: {"attempt_count": 1})
    monkeypatch.setattr(pipeline.runtime, "checkpoint", lambda *a, **kw: checkpoints.append(a[1]))
    return pipeline, conn, request, lease, provider, authority, calls, settlements, checkpoints


def test_native_request_and_exact_target_runtime_scope():
    request, _, coverage, lease = inputs("python-state-update-v1")
    assert match_shared_request(request, coverage, lease).target_id == "python-state-update-v1"
    other_scope = coverage.scope.model_copy(update={"runtime_profile_id": "sqlite-query-v1"})
    other = coverage.model_copy(update={"scope": other_scope})
    with pytest.raises(PipelineRepositoryError, match="SCOPE_MISMATCH"):
        match_shared_request(request.model_copy(update={"scope_hash": other_scope.scope_hash}), other, lease)
    kc, _, static, kc_lease = inputs()
    assert match_shared_request(kc, static, kc_lease).assessment.runtime_profile_id is None
    assert kc.blueprint.runtime_profile_id is None and static.scope.runtime_profile_id == "static-exact-v1"
    private, _ = make_request()
    with pytest.raises(PipelineRepositoryError, match="NATIVE_SOURCE"):
        native_request(private)
    with pytest.raises(PipelineRepositoryError, match="PRIVATE_DEMAND"):
        native_request(kc.model_copy(update={"demand_binding": GenerationDemandBindingV1(demand_id=uuid4(), demand_hash="a"*64)}))


def test_native_source_does_not_authorize_generic_legacy_task():
    native, _, _, _ = inputs()
    generic, payload = make_request()
    invalid = generic.model_copy(update={"materials": native.materials})
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    result = generate_candidate(invalid, provider=provider, source_authority=authority, enabled=True)
    assert result.state == "blocked" and result.safe_reason == "invalid_request"
    assert provider.calls == authority.calls == 0
    # A genuinely legacy (non-native) request still uses its old generic path.
    result = generate_candidate(generic, provider=provider, source_authority=authority, enabled=True)
    assert result.state == "staged" and provider.calls == authority.calls == 1


def test_default_off_and_concrete_same_connection_gate():
    request, _, _, lease = inputs()
    conn = OfflineConnection()
    assert SharedGenerationPipeline(conn, Settings()).prepare_generation(
        lease=lease, request=request, provider=None, source_authority=None) is None
    assert not conn.statements
    repository = SharedPipelineArtifactRepository(conn)
    with pytest.raises(PipelineRepositoryError, match="DISABLED"):
        repository.context(lease, now=datetime.now(UTC))
    repository.enabled = True
    with pytest.raises(PipelineRepositoryError, match="SOURCE_AUTHORITY"):
        repository.require_source(SimpleNamespace(connection=conn, verified=True))
    with pytest.raises(PipelineRepositoryError, match="SOURCE_AUTHORITY"):
        repository.require_source(RagSourceAuthority(SimpleNamespace(conn=OfflineConnection()), None))
    conn.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(PipelineRepositoryError, match="TRANSACTION_REQUIRED"):
        repository.require_owner()


@pytest.mark.parametrize("diagnostic", [False, True])
def test_two_phase_staging_idle_io_replay_and_native_future_ids(monkeypatch, diagnostic):
    pipeline, conn, request, lease, provider, authority, calls, settlements, checkpoints = setup(monkeypatch)
    policy = AutonomousEvidencePolicyV3() if diagnostic else AutonomousEvidencePolicyV2()
    prepared = pipeline.prepare_generation(lease=lease, request=request, provider=provider, source_authority=authority, evidence_policy=policy)
    assert prepared.evidence_policy_hash == policy.policy_hash
    with pytest.raises(PipelineRepositoryError, match="IDLE_TRANSACTION"):
        pipeline.run_generation(prepared, provider)
    conn.info.transaction_status = TransactionStatus.IDLE
    result = pipeline.run_generation(prepared, provider)
    assert result.state == "staged" and len(calls) == 1
    with pytest.raises(PipelineRepositoryError, match="ALREADY_DISPATCHED"):
        pipeline.run_generation(prepared, provider)
    with conn.transaction():
        pipeline.settle_generation(prepared, result)
    assert settlements[0]["usage_state"] == "known" and settlements[0]["cost_amount"] is None
    with conn.transaction():
        stage = pipeline.commit_generation(prepared, result, source_authority=authority)
        replay = pipeline.artifacts.store_generation(lease=lease, request=request, result=result,
            artifact_key=f"generation.{request.candidate_id.hex}", now=datetime.now(UTC), source_authority=authority)
        assert pipeline.artifacts.published_generation_policy(replay) == policy
    assert stage.state == "staged" and stage.artifact_id == replay["id"]
    assert replay["item_id"] == learning_item_uuid("item", request.item_key)
    assert replay["version_id"] == learning_item_uuid("version", f"{request.item_key}@{request.version}")
    assert replay["candidate_id"] == request.candidate_id
    assert [c.stage for c in checkpoints] == ["generating"]
    assert not any("private_" in sql or "INSERT INTO tutor_learning_item" in sql for sql in conn.statements)


def test_unknown_usage_retained_when_final_current_source_fails(monkeypatch):
    pipeline, conn, request, lease, provider, authority, calls, settlements, checkpoints = setup(monkeypatch, usage=False)
    prepared = pipeline.prepare_generation(lease=lease, request=request, provider=provider, source_authority=authority)
    conn.info.transaction_status = TransactionStatus.IDLE
    result = pipeline.run_generation(prepared, provider)
    with conn.transaction():
        pipeline.settle_generation(prepared, result)
    assert settlements[0]["usage_state"] == "unknown"
    assert settlements[0]["actual"] is None and settlements[0]["cost_amount"] is None

    def stale(*args):
        raise ValueError("source_unavailable")

    monkeypatch.setattr(authority, "assert_current", stale)
    with conn.transaction(), pytest.raises(ValueError, match="source_unavailable"):
        pipeline.commit_generation(prepared, result, source_authority=authority)
    assert len(calls) == 1 and conn.row is None and not checkpoints
