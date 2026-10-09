"""P3 pure controller and dedicated PostgreSQL runtime acceptance tests."""

from __future__ import annotations
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
import psycopg
import pytest
from psycopg.rows import dict_row
from app.core.config import Settings
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.calibration import (
    CalibrationObservationV1,
    CalibrationPolicyV1,
    calibrate,
    CalibrationWindowV1,
)
from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1
from app.services.learning.item_supply.jobs import CheckpointV1
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.parameter_profiles import (
    ExecutionParameterProfileV1,
    ParameterValuesV1,
    ProfileKeyV1,
)
from app.services.learning.item_supply.policies import (
    RESOURCE_KINDS,
    CoverageObligationV1,
    FailureClass,
    ResourceAmounts,
    RetryPolicyV1,
    SupplyRuntimeError,
    derive_runtime_contract_hash,
)
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.scheduler import OwnerPartition, claim_bounded
from tests.learning.test_item_supply_storage import H, P, owner, scope, shared

DSN = "postgresql://postgres:postgres@127.0.0.1:5432/aearn_b1b_fixture_20260930"
NOW = datetime.now(UTC)
WINDOW_END = NOW + timedelta(seconds=12)
RUN_ID = uuid4().hex


def values(
    request: int = 100_000, stage: int = 300_000, parent: int = 600_000, rounds: int = 8
) -> ParameterValuesV1:
    return ParameterValuesV1(
        connection_timeout_ms=20_000,
        first_token_timeout_ms=30_000,
        stream_idle_timeout_ms=40_000,
        request_timeout_ms=request,
        stage_deadline_ms=stage,
        parent_deadline_ms=parent,
        discussion_rounds=rounds,
        revision_rounds=rounds,
        investigation_rounds=rounds,
    )


def profile(
    *,
    version: int = 1,
    state: str = "stable",
    current: ParameterValuesV1 | None = None,
    last: ParameterValuesV1 | None = None,
) -> ExecutionParameterProfileV1:
    initial = values()
    floor = values(60_000, 180_000, 360_000, 2)
    ceiling = values(300_000, 900_000, 1_800_000, 16)
    current = current or initial
    return ExecutionParameterProfileV1(
        profile_key=ProfileKeyV1(
            provider="provider.synthetic",
            model_version=f"model.{RUN_ID}",
            agent_role="generator",
            item_kind="code",
            risk_tier="medium",
            difficulty="intermediate",
            input_size_bucket="medium",
            runtime="python.v1",
            provider_version="provider.v1",
            prompt_version="prompt.v1",
            validator_version="validator.v1",
            output_size_bucket="medium",
            load_bucket="normal",
            complexity_version="complexity.v1",
        ),
        version=version,
        state=state,
        initial=initial,
        current=current,
        last_stable=last or (initial if state == "canary" else current),
        floor=floor,
        ceiling=ceiling,
        measurement_window_started_at=NOW - timedelta(days=1),
        change_reason="synthetic.config",
        trusted_initial_evidence=("trusted.config",),
    )


def retry_policy() -> RetryPolicyV1:
    return RetryPolicyV1(
        max_transient_attempts=3, initial_backoff_ms=1000, maximum_backoff_ms=4000
    )


def policy() -> CalibrationPolicyV1:
    return CalibrationPolicyV1(
        minimum_samples=3,
        minimum_complete_samples=3,
        maximum_right_censored_ratio=0.0,
        minimum_quality_score=0.8,
        minimum_coverage_score=0.8,
        timeout_step_ratio=0.1,
        timeout_safety_margin_ratio=0.2,
        maximum_quality_regression=0.03,
        maximum_coverage_regression=0.03,
        minimum_canary_samples=3,
        round_step=1,
        cooldown_seconds=60,
        freeze_after_rollbacks=2,
        minimum_window_seconds=1,
        latency_quantile=0.9,
        minimum_quantile_samples=12,
        minimum_idle_tail_rounds=1,
        maximum_tail_contribution=0.05,
        minimum_qualified_yield_score=0.8,
        maximum_token_growth_ratio=1.1,
        maximum_retry_increase=0,
    )


OBS_INDEX = 0


def observation(
    p: ExecutionParameterProfileV1,
    *,
    mode: str = "live",
    completed: bool = True,
    censored: bool = False,
    quality: float = 0.95,
    coverage: float = 0.95,
    baseline: float = 0.96,
    request_ms: int = 50_000,
) -> CalibrationObservationV1:
    global OBS_INDEX
    OBS_INDEX += 1
    return CalibrationObservationV1(
        observation_key=f"observation.{OBS_INDEX}",
        prompt_version="prompt.v1",
        validator_version="validator.v1",
        output_size_bucket="medium",
        complexity_version="complexity.v1",
        termination="completed" if completed else ("timeout" if censored else "failed"),
        qualified_yield_score=0.95,
        first_review_passed=True,
        final_review_passed=completed,
        unresolved_issues=0,
        scorer_blocked=False,
        safety_blocked=False,
        retry_count=0,
        usage_tokens=100,
        profile_key_hash=p.profile_key.key_hash,
        profile_version=p.version,
        provider_version="provider.v1",
        model_version=p.profile_key.model_version,
        runtime_version="python.v1",
        load_bucket="normal",
        mode=mode,
        completed=completed,
        right_censored=censored,
        quality_score=quality,
        coverage_score=coverage,
        baseline_quality_score=baseline,
        baseline_coverage_score=baseline,
        values_used=p.last_stable
        if mode == "control" or (mode == "shadow" and p.state == "canary")
        else p.current,
        actual_request_ms=request_ms,
        actual_stage_ms=request_ms * 2,
        actual_discussion_rounds=3,
        actual_revision_rounds=3,
        actual_investigation_rounds=3,
        observed_at=NOW - timedelta(seconds=OBS_INDEX),
    )


def test_canonical_root_excludes_client_and_profile_keys() -> None:
    base = dict(
        scope_hash=H,
        objective_hash=H,
        purpose="assessment",
        runtime_contract_hash=H,
        visibility="private",
        policy_version="autonomous_evidence_policy_v2",
        owner_id=uuid4(),
    )
    obligation = CoverageObligationV1(**base)
    assert obligation.canonical_key == CoverageObligationV1(**base).canonical_key
    assert profile(version=1).profile_hash != profile(version=2).profile_hash


def test_retry_is_bounded_and_deterministic_breaker_never_retries() -> None:
    retry = RetryPolicyV1(
        max_transient_attempts=3, initial_backoff_ms=1000, maximum_backoff_ms=4000
    )
    assert (
        retry.next_retry_at(
            failure=FailureClass.DETERMINISTIC,
            attempt=1,
            now=NOW,
            parent_deadline=NOW + timedelta(seconds=10),
        )
        is None
    )
    assert (
        retry.next_retry_at(
            failure=FailureClass.TRANSIENT,
            attempt=3,
            now=NOW,
            parent_deadline=NOW + timedelta(seconds=10),
        )
        is None
    )


def run_calibration(p, obs, pol, *, now, rollback_count=None):
    window = (
        None
        if not obs
        else CalibrationWindowV1(
            window_key=f"window.{uuid4().hex}",
            profile_hash=p.profile_hash,
            policy_hash=pol.policy_hash,
            expected_observation_keys=tuple(o.observation_key for o in obs),
            started_at=min(o.observed_at for o in obs),
            ended_at=now,
        )
    )
    return calibrate(p, obs, pol, now=now, rollback_count=rollback_count, window=window)


def test_calibration_no_samples_timeout_failure_and_regression_hold_or_rollback() -> (
    None
):
    p = profile()
    assert run_calibration(p, (), policy(), now=NOW).reason == "insufficient_samples"
    timed = (
        observation(p, completed=False, censored=True),
        observation(p),
        observation(p),
    )
    assert (
        run_calibration(p, timed, policy(), now=NOW).reason
        == "censored_failure_or_success_bias"
    )
    reg = tuple(
        observation(p, quality=0.90, coverage=0.90, baseline=0.96) for _ in range(12)
    )
    assert run_calibration(p, reg, policy(), now=NOW).action == "rollback"


def test_calibration_single_dimension_margin_shadow_and_canary_rules() -> None:
    p = profile()
    obs = tuple(observation(p, request_ms=70_000) for _ in range(12))
    decision = run_calibration(p, obs, policy(), now=NOW)
    assert decision.action == "propose" and decision.parameter == "request_timeout_ms"
    assert (
        decision.proposed is not None and decision.proposed.request_timeout_ms >= 84_000
    )
    canary = profile(state="canary", current=decision.proposed, last=p.current)
    mixed = (
        observation(canary, mode="canary"),
        observation(canary, mode="shadow"),
        observation(canary, mode="shadow"),
    )
    assert run_calibration(canary, mixed, policy(), now=NOW).reason in {
        "shadow_not_quality_proof",
        "insufficient_samples",
    }
    real = tuple(observation(canary, mode="canary") for _ in range(12))
    real = tuple(
        o.model_copy(update={"comparison_key": f"pair.{i}"}) for i, o in enumerate(real)
    )
    controls = tuple(
        observation(canary, mode="control").model_copy(
            update={"comparison_key": f"pair.{i}"}
        )
        for i in range(12)
    )
    assert (
        run_calibration(canary, real + controls, policy(), now=NOW).action == "commit"
    )


def test_calibration_last_stable_rollback_cooldown_and_freeze() -> None:
    p = profile(
        state="canary",
        current=values().replace("request_timeout_ms", 90_000),
        last=values(),
    )
    bad = tuple(observation(p, quality=0.5, coverage=0.5) for _ in range(12))
    rollback = run_calibration(p, bad, policy(), now=NOW, rollback_count=0)
    assert (
        rollback.action == "rollback"
        and rollback.proposed == p.last_stable
        and rollback.cooldown_until > NOW
    )
    assert (
        run_calibration(p, bad, policy(), now=NOW, rollback_count=1).action == "freeze"
    )


@pytest.fixture(autouse=True)
def schema(request) -> None:
    if "conn" not in request.fixturenames:
        return
    assert os.environ.get("DATABASE_URL") == DSN
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert os.environ.get("LLM_TYPE") == "disabled"
    assert os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1"
    # Schema/bootstrap belongs exclusively to the coordinating main session.


@pytest.fixture
def conn():
    global NOW, WINDOW_END, RUN_ID
    assert os.environ.get("DATABASE_URL") == DSN
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert os.environ.get("LLM_TYPE") == "disabled"
    assert os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1"
    c = psycopg.connect(DSN, row_factory=dict_row)
    assert (
        c.execute("SELECT current_database() AS db").fetchone()["db"]
        == "aearn_b1b_fixture_20260930"
    )
    c.execute("SET statement_timeout=5000")
    NOW = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    WINDOW_END = NOW + timedelta(seconds=12)
    RUN_ID = uuid4().hex
    owned_start, owned_end = NOW - timedelta(seconds=1), WINDOW_END
    try:
        yield c
    finally:
        c.rollback()
        c.close()
        # Commit races leave immutable facts intact. Only this test's exact
        # server-clock window is checked; wait for expiry before the next test
        # or suite repeat. No destructive cleanup, guards or caps are changed.
        from time import monotonic, sleep

        with psycopg.connect(DSN, row_factory=dict_row) as check:
            committed = check.execute(
                "SELECT count(*) AS n FROM tutor_item_supply_runtime_global_limits WHERE window_start=%s AND window_end=%s",
                (owned_start, owned_end),
            ).fetchone()["n"]
            if committed:
                stop = monotonic() + 15
                while (
                    check.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
                    < owned_end
                ):
                    assert monotonic() < stop, (
                        "fixture window expiry exceeded bounded wait"
                    )
                    sleep(0.05)


def setup_shared(
    conn,
    *,
    cap: int = 10,
    pool_class: str = "base",
    provider_key: str = "provider.synthetic",
    root_request_cap: int = 1000,
):
    data = shared(conn)
    # Distinct server obligations isolate jobs, not cumulative limit accounting.
    from app.services.learning.item_bank.contracts import canonical_hash

    blueprint = data["blueprint"].model_copy(
        update={"objective_hash": canonical_hash(uuid4().hex)}
    )
    data = {
        **data,
        "blueprint": blueprint,
        "blueprint_id": data["repo"].register_blueprint(blueprint),
    }
    repo = ItemSupplyRuntimeRepository(conn)
    p = profile()
    p = p.model_copy(
        update={
            "profile_key": p.profile_key.model_copy(update={"provider": provider_key})
        }
    )
    scope = data["blueprint"].scope
    obligation = CoverageObligationV1(
        blueprint_hash=data["blueprint"].blueprint_hash,
        scope_hash=scope.scope_hash,
        objective_hash=data["blueprint"].objective_hash,
        purpose=scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(scope),
        visibility="public",
        policy_version="autonomous_evidence_policy_v2",
    )
    root = repo.ensure_shared_root(
        blueprint_id=data["blueprint_id"],
        obligation=obligation,
        pool=pool_class,
        provider_key=provider_key,
    )
    conn.execute(
        "INSERT INTO tutor_item_supply_shared_budget_windows(root_id,pool_key,provider_key,window_start,window_end,request_cap,token_cap,resource_cap) VALUES(%s,%s,%s,%s,%s,%s,1000000,1000000) ON CONFLICT DO NOTHING",
        (
            root,
            pool_class,
            provider_key,
            NOW - timedelta(seconds=1),
            WINDOW_END,
            root_request_cap,
        ),
    )
    budget = ItemSupplyBudgetRepository(conn)
    for kind in RESOURCE_KINDS:
        amount = cap if kind == "requests" else cap * 100
        for dimension, key in (
            ("system", "item-supply"),
            ("provider", provider_key),
            ("window", "item-supply"),
            ("pool", pool_class),
        ):
            budget.register_global_limit(
                dimension_kind=dimension,
                dimension_key=key,
                resource_kind=kind,
                window_start=NOW - timedelta(seconds=1),
                window_end=WINDOW_END,
                cap_amount=amount,
            )
    job = repo.enqueue(
        root_id=root,
        stage_key=f"stage.{uuid4().hex}",
        profile=p,
        retry_policy=retry_policy(),
        now=NOW,
        priority=100,
        aging_seconds=60,
        visibility="public",
    )
    lease = repo.claim(
        root_id=root,
        lease_owner="worker.001",
        now=NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert lease and lease.job_id == job
    return repo, budget, root, lease


def setup_private(conn, *, root_request_cap: int = 10):
    o = owner(conn)
    contract = scope(o["user"])
    demand = AssessmentSupplyDemandV1(
        demand_id=f"demand.{uuid4().hex}",
        learner_ref=f"user:{o['user']}",
        scope=contract,
        objective_hash=o["scope"].objective_hash,
        blueprint_hash=H,
        matrix_hash=build_support_matrix().matrix_hash,
        policy_version=P,
        input_revision=1,
    )
    demand_id = o["repo"].store_demand(
        scope_id=o["scope"].id, request_key=f"request.{uuid4().hex}", demand=demand
    )
    obligation = CoverageObligationV1(
        blueprint_hash=H,
        scope_hash=o["scope"].scope_hash,
        objective_hash=o["scope"].objective_hash,
        purpose=contract.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(contract),
        visibility="private",
        policy_version=P,
        owner_id=o["user"],
    )
    repo = ItemSupplyRuntimeRepository(conn)
    root = repo.ensure_private_root(
        user_id=o["user"],
        epoch=1,
        scope_id=o["scope"].id,
        demand_id=demand_id,
        obligation=obligation,
        pool="enhancement",
        provider_key="provider.synthetic",
    )
    conn.execute(
        "INSERT INTO tutor_item_supply_private_budget_windows(user_id,epoch,scope_id,root_id,pool_key,provider_key,window_start,window_end,request_cap,token_cap,resource_cap) VALUES(%s,1,%s,%s,'enhancement','provider.synthetic',%s,%s,%s,1000,1000)",
        (
            o["user"],
            o["scope"].id,
            root,
            NOW - timedelta(seconds=1),
            WINDOW_END,
            root_request_cap,
        ),
    )
    budget = ItemSupplyBudgetRepository(conn)
    for kind in RESOURCE_KINDS:
        cap = 10 if kind == "requests" else 1000
        for dimension, key in (
            ("system", "item-supply"),
            ("provider", "provider.synthetic"),
            ("window", "item-supply"),
            ("pool", "enhancement"),
        ):
            budget.register_global_limit(
                dimension_kind=dimension,
                dimension_key=key,
                resource_kind=kind,
                window_start=NOW - timedelta(seconds=1),
                window_end=WINDOW_END,
                cap_amount=cap,
            )
        budget.register_user_limit(
            user_id=o["user"],
            epoch=1,
            resource_kind=kind,
            window_start=NOW - timedelta(seconds=1),
            window_end=WINDOW_END,
            cap_amount=cap,
        )
    job = repo.enqueue(
        root_id=root,
        stage_key=f"private.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=100,
        aging_seconds=60,
        visibility="private",
        user_id=o["user"],
        epoch=1,
        scope_id=o["scope"].id,
    )
    lease = repo.claim(
        root_id=root,
        lease_owner="worker.private",
        now=NOW,
        lease_seconds=60,
        visibility="private",
        user_id=o["user"],
        epoch=1,
    )
    assert lease and lease.job_id == job
    return o, demand_id, obligation, repo, budget, root, lease


def test_db_profile_switch_does_not_reset_root_and_default_off_entrypoint(conn) -> None:
    repo, budget, root, lease = setup_shared(conn)
    settings = Settings(
        learning_item_supply_enabled=False,
        learning_item_generation_enabled=True,
        learning_item_supply_scheduler_enabled=True,
    )
    assert (
        claim_bounded(
            settings=settings,
            repository=repo,
            owner=OwnerPartition("public", root),
            worker_id="worker.002",
            now=NOW,
            limit=1,
            lease_seconds=60,
            registered_handlers=frozenset(),
        ).state
        == "disabled"
    )
    assert (
        claim_bounded(
            settings=Settings(
                learning_item_supply_enabled=True,
                learning_item_generation_enabled=True,
                learning_item_supply_scheduler_enabled=True,
            ),
            repository=repo,
            owner=None,
            worker_id="worker.002",
            now=NOW,
            limit=1,
            lease_seconds=60,
            registered_handlers=frozenset(),
        ).state
        == "owner_required"
    )


def test_db_unknown_replay_actual_overage_and_separate_units(conn) -> None:
    repo, budget, root, lease = setup_shared(conn, cap=10)
    requested = ResourceAmounts(requests=1, input_tokens=50, output_tokens=20)
    reservation = budget.reserve(
        lease=lease, reservation_key="reserve.one", amounts=requested, now=NOW
    )
    assert reservation.allowed and reservation.reservation_id
    assert (
        budget.settle(
            lease=lease,
            reservation_id=reservation.reservation_id,
            settlement_key="unknown.one",
            usage_state="unknown",
            actual=None,
            cost_amount=None,
            receipt_hash=None,
        ).state
        == "unknown"
    )
    assert (
        budget.settle(
            lease=lease,
            reservation_id=reservation.reservation_id,
            settlement_key="unknown.one",
            usage_state="unknown",
            actual=None,
            cost_amount=None,
            receipt_hash=None,
        ).sequence
        == 1
    )
    actual = ResourceAmounts(requests=10, input_tokens=900, output_tokens=100)
    budget.settle(
        lease=lease,
        reservation_id=reservation.reservation_id,
        settlement_key="known.one",
        usage_state="known",
        actual=actual,
        cost_amount=None,
        receipt_hash="b" * 64,
    )
    other = repo.enqueue(
        root_id=root,
        stage_key=f"other.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=1,
        aging_seconds=1,
        visibility="public",
    )
    other_lease = repo.claim(
        root_id=root,
        lease_owner="worker.002",
        now=NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert other_lease and other_lease.job_id == other
    denied = budget.reserve(
        lease=other_lease,
        reservation_key="reserve.two",
        amounts=ResourceAmounts(requests=1, input_tokens=1, output_tokens=1),
        now=NOW,
    )
    assert not denied.allowed and denied.reason.endswith("CAP_EXHAUSTED")
    with pytest.raises(SupplyRuntimeError, match="SETTLEMENT_CONFLICT"):
        budget.settle(
            lease=lease,
            reservation_id=reservation.reservation_id,
            settlement_key="known.one",
            usage_state="known",
            actual=requested,
            cost_amount=Decimal("0"),
            receipt_hash="b" * 64,
        )


def test_db_stale_lease_cannot_checkpoint_but_can_settle_usage(conn) -> None:
    repo, budget, root, lease = setup_shared(conn)
    reservation = budget.reserve(
        lease=lease,
        reservation_key="reserve.stale",
        amounts=ResourceAmounts(requests=1, input_tokens=10, output_tokens=5),
        now=NOW,
    )
    assert reservation.reservation_id
    repo.mark_preparing(lease, reason="lost.worker", now=NOW)
    with pytest.raises(SupplyRuntimeError, match="LEASE_STALE"):
        repo.checkpoint(
            lease,
            CheckpointV1(
                stage="generating",
                attempt=1,
                status="completed",
                receipt_hash="c" * 64,
                safe_reason="synthetic",
            ),
            now=NOW + timedelta(seconds=61),
        )
    assert (
        budget.settle(
            lease=lease,
            reservation_id=reservation.reservation_id,
            settlement_key="lost.usage",
            usage_state="unknown",
            actual=None,
            cost_amount=None,
            receipt_hash=None,
        ).state
        == "unknown"
    )


def test_db_double_claim_only_one_generation(conn) -> None:
    repo, budget, root, lease = setup_shared(conn)
    repo.mark_preparing(lease, reason="handler_not_registered", now=NOW)
    # A fresh queued job is visible to both committed connections.
    job = repo.enqueue(
        root_id=root,
        stage_key=f"race.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=500,
        aging_seconds=1,
        visibility="public",
    )
    conn.commit()

    def claim(worker):
        with psycopg.connect(DSN, row_factory=dict_row) as c:
            r = ItemSupplyRuntimeRepository(c).claim(
                root_id=root,
                lease_owner=worker,
                now=NOW,
                lease_seconds=60,
                visibility="public",
            )
            c.commit()
            return r

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("worker.a", "worker.b")))
    winners = [x for x in results if x is not None and x.job_id == job]
    assert len(winners) == 1 and winners[0].generation == 1


def test_db_server_rebuilds_shared_authority_and_rejects_forged_fields(conn) -> None:
    data = shared(conn)
    repo = ItemSupplyRuntimeRepository(conn)
    s = data["blueprint"].scope
    correct = CoverageObligationV1(
        blueprint_hash=data["blueprint"].blueprint_hash,
        scope_hash=s.scope_hash,
        objective_hash=data["blueprint"].objective_hash,
        purpose=s.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(s),
        visibility="public",
        policy_version=P,
    )
    for field, value in (
        ("scope_hash", "f" * 64),
        ("objective_hash", "e" * 64),
        ("runtime_contract_hash", "d" * 64),
        ("purpose", "review"),
        ("policy_version", "other.policy"),
    ):
        with pytest.raises(SupplyRuntimeError, match="OBLIGATION_AUTHORITY_MISMATCH"):
            repo.ensure_shared_root(
                blueprint_id=data["blueprint_id"],
                obligation=correct.model_copy(update={field: value}),
                pool="base",
                provider_key="provider.synthetic",
            )


def test_db_private_authority_owner_metadata_and_root_cap(conn) -> None:
    o, demand_id, obligation, repo, budget, root, lease = setup_private(
        conn, root_request_cap=1
    )
    with pytest.raises(SupplyRuntimeError, match="OBLIGATION_AUTHORITY_MISMATCH"):
        repo.ensure_private_root(
            user_id=o["user"],
            epoch=1,
            scope_id=o["scope"].id,
            demand_id=demand_id,
            obligation=obligation.model_copy(update={"objective_hash": "e" * 64}),
            pool="enhancement",
            provider_key="provider.synthetic",
        )
    with pytest.raises(SupplyRuntimeError, match="ROOT_CONFLICT"):
        repo.ensure_private_root(
            user_id=o["user"],
            epoch=1,
            scope_id=o["scope"].id,
            demand_id=demand_id,
            obligation=obligation,
            pool="base",
            provider_key="provider.synthetic",
        )
    first = budget.reserve(
        lease=lease,
        reservation_key="private.one",
        amounts=ResourceAmounts(requests=1, input_tokens=10, output_tokens=5),
        now=NOW,
    )
    assert first.allowed
    repo.mark_preparing(lease, reason="handler_not_registered", now=NOW)
    repo.enqueue(
        root_id=root,
        stage_key=f"private.second.{uuid4().hex}",
        profile=profile(version=2),
        retry_policy=retry_policy(),
        now=NOW,
        priority=100,
        aging_seconds=60,
        visibility="private",
        user_id=o["user"],
        epoch=1,
        scope_id=o["scope"].id,
    )
    second_lease = repo.claim(
        root_id=root,
        lease_owner="worker.private.2",
        now=NOW,
        lease_seconds=60,
        visibility="private",
        user_id=o["user"],
        epoch=1,
    )
    assert second_lease
    denied = budget.reserve(
        lease=second_lease,
        reservation_key="private.two",
        amounts=ResourceAmounts(requests=1, input_tokens=1, output_tokens=1),
        now=NOW,
    )
    assert not denied.allowed and denied.reason == "ROOT_CAP_EXHAUSTED"


def test_db_shared_subscription_cancel_preserves_other_consumer(conn) -> None:
    repo, budget, root, lease = setup_shared(conn)
    users = []
    for _ in range(2):
        o = owner(conn)
        contract = scope(o["user"])
        demand = AssessmentSupplyDemandV1(
            demand_id=f"demand.{uuid4().hex}",
            learner_ref=f"user:{o['user']}",
            scope=contract,
            objective_hash=o["scope"].objective_hash,
            blueprint_hash=H,
            matrix_hash=build_support_matrix().matrix_hash,
            policy_version=P,
            input_revision=1,
        )
        demand_id = o["repo"].store_demand(
            scope_id=o["scope"].id, request_key=f"request.{uuid4().hex}", demand=demand
        )
        subscription = conn.execute(
            "INSERT INTO tutor_item_supply_private_subscriptions(user_id,epoch,scope_id,demand_id,shared_job_id,subscription_key) VALUES(%s,1,%s,%s,%s,%s) RETURNING id",
            (
                o["user"],
                o["scope"].id,
                demand_id,
                lease.job_id,
                f"subscription.{uuid4().hex}",
            ),
        ).fetchone()["id"]
        users.append((o, subscription))
    assert repo.cancel_shared_subscription(
        subscription_id=users[0][1], user_id=users[0][0]["user"], epoch=1, now=NOW
    )
    assert (
        conn.execute(
            "SELECT state FROM tutor_item_supply_shared_job_controls WHERE job_id=%s",
            (lease.job_id,),
        ).fetchone()["state"]
        == "leased"
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_item_supply_private_subscriptions WHERE shared_job_id=%s AND state='active'",
            (lease.job_id,),
        ).fetchone()["n"]
        == 1
    )


def test_db_priority_aging_prevents_starvation(conn) -> None:
    repo, budget, root, lease = setup_shared(conn)
    repo.mark_preparing(lease, reason="handler_not_registered", now=NOW)
    conn.execute(
        "UPDATE tutor_item_supply_shared_job_controls c SET state='preparing',state_version=c.state_version+1 FROM tutor_item_supply_shared_jobs j WHERE j.id=c.job_id AND j.root_id=%s AND c.state IN ('queued','retry_wait')",
        (root,),
    )
    old = repo.enqueue(
        root_id=root,
        stage_key=f"old.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=1,
        aging_seconds=1,
        visibility="public",
    )
    conn.execute(
        "UPDATE tutor_item_supply_shared_job_controls SET available_at=%s WHERE job_id=%s",
        (NOW - timedelta(hours=2), old),
    )
    repo.enqueue(
        root_id=root,
        stage_key=f"new.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=100,
        aging_seconds=3600,
        visibility="public",
    )
    claimed = repo.claim(
        root_id=root,
        lease_owner="worker.aging",
        now=NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert claimed and claimed.job_id == old
