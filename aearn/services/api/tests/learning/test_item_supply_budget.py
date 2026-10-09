"""P3 actual PostgreSQL accounting races; all IO stays on the dedicated fixture."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from time import sleep, monotonic
from queue import Queue
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.policies import (
    RESOURCE_KINDS,
    ResourceAmounts,
    SupplyRuntimeError,
)
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from tests.learning import test_item_supply_runtime as fx
from tests.learning.test_item_supply_runtime import conn as conn


def spend(requests=1, **extra):
    return ResourceAmounts(requests=requests, input_tokens=10, output_tokens=5, **extra)


@pytest.mark.parametrize("kind", RESOURCE_KINDS)
def test_db_each_resource_unit_is_independently_capped(conn, kind):
    _, budget, _, lease = fx.setup_shared(conn)
    amounts = spend().as_dict()
    amounts[kind] = 11 if kind == "requests" else 1001
    result = budget.reserve(
        lease=lease,
        reservation_key=f"over.{kind}",
        amounts=ResourceAmounts(**amounts),
        now=fx.NOW,
    )
    assert not result.allowed and result.reason.endswith("CAP_EXHAUSTED")
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_item_supply_shared_reservations WHERE job_id=%s",
            (lease.job_id,),
        ).fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize(
    "pool,provider",
    [
        ("base", "provider.synthetic"),
        ("enhancement", "provider.synthetic"),
        ("enhancement", "provider.other"),
    ],
)
def test_db_new_root_pool_provider_profile_and_future_time_cannot_clear_system_cap(
    conn, pool, provider
):
    _, budget, root, lease = fx.setup_shared(conn)
    first = budget.reserve(
        lease=lease, reservation_key="consume.system", amounts=spend(10), now=fx.NOW
    )
    assert first.allowed
    repo, budget, other, new = fx.setup_shared(
        conn, pool_class=pool, provider_key=provider
    )
    assert other != root
    denied = budget.reserve(
        lease=new,
        reservation_key=f"new.{uuid4().hex}",
        amounts=spend(),
        now=fx.NOW + timedelta(days=30),
    )
    assert not denied.allowed and denied.reason.endswith("CAP_EXHAUSTED")
    # Metadata cannot be changed on the existing root to escape its pool/provider.
    obligation = conn.execute(
        "SELECT obligation_json FROM tutor_item_supply_shared_obligations WHERE root_id=%s",
        (root,),
    ).fetchone()["obligation_json"]
    from app.services.learning.item_supply.policies import CoverageObligationV1
    from tests.learning.test_item_supply_storage import shared

    with pytest.raises(
        SupplyRuntimeError, match="BLUEPRINT_MISMATCH|OBLIGATION_AUTHORITY_MISMATCH"
    ):
        repo.ensure_shared_root(
            blueprint_id=shared(conn)["blueprint_id"],
            obligation=CoverageObligationV1.model_validate_json(
                __import__("json").dumps(obligation)
            ),
            pool=pool,
            provider_key=provider,
        )


def test_db_reservation_replay_at_full_cap_unknown_zero_cost_and_explicit_reconciliation(
    conn,
):
    _, budget, _, lease = fx.setup_shared(conn)
    reserved = budget.reserve(
        lease=lease, reservation_key="full.cap", amounts=spend(10), now=fx.NOW
    )
    assert reserved.reservation_id
    assert (
        budget.reserve(
            lease=lease, reservation_key="full.cap", amounts=spend(10), now=fx.NOW
        ).reason
        == "REPLAY"
    )
    with pytest.raises(SupplyRuntimeError, match="RESERVATION_CONFLICT"):
        budget.reserve(
            lease=lease, reservation_key="full.cap", amounts=spend(9), now=fx.NOW
        )
    rid = reserved.reservation_id
    args = dict(
        lease=lease,
        reservation_id=rid,
        settlement_key="unknown.one",
        usage_state="unknown",
        actual=None,
        cost_amount=None,
        receipt_hash=None,
    )
    assert budget.settle(**args).sequence == 1
    assert budget.settle(**args).sequence == 1
    assert not budget.reserve(
        lease=lease, reservation_key="unknown.not.free", amounts=spend(), now=fx.NOW
    ).allowed
    # Real zero usage is allowed only with a KNOWN receipt, never inferred.
    known = dict(
        lease=lease,
        reservation_id=rid,
        settlement_key="known.zero",
        usage_state="known",
        actual=ResourceAmounts(),
        cost_amount=None,
        receipt_hash="a" * 64,
    )
    assert budget.settle(**known).sequence == 2
    assert budget.settle(**known).sequence == 2
    row = conn.execute(
        "SELECT cost_amount FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=%s AND settlement_key='known.zero'",
        (rid,),
    ).fetchone()
    assert row["cost_amount"] is None
    assert budget.reserve(
        lease=lease, reservation_key="after.reconciled", amounts=spend(), now=fx.NOW
    ).allowed
    assert (
        budget.settle(**{**args, "settlement_key": "later.unknown"}).state == "unknown"
    )
    assert not budget.reserve(
        lease=lease, reservation_key="unknown.again", amounts=spend(), now=fx.NOW
    ).allowed
    with pytest.raises(SupplyRuntimeError, match="SETTLEMENT_CONFLICT"):
        budget.settle(**{**known, "actual": spend()})


def test_db_actual_unreserved_dimension_overage_is_retained_and_blocks_followup(conn):
    _, budget, _, lease = fx.setup_shared(conn)
    reservation = budget.reserve(
        lease=lease, reservation_key="small", amounts=spend(), now=fx.NOW
    )
    assert reservation.reservation_id
    actual = spend(candidates=1001)
    budget.settle(
        lease=lease,
        reservation_id=reservation.reservation_id,
        settlement_key="actual.overage",
        usage_state="known",
        actual=actual,
        cost_amount=Decimal("0.01"),
        receipt_hash="b" * 64,
    )
    row = conn.execute(
        "SELECT actual_amount FROM tutor_item_supply_shared_runtime_settlement_amounts a JOIN tutor_item_supply_shared_runtime_settlements s ON s.id=a.settlement_id WHERE s.reservation_id=%s AND a.resource_kind='candidates'",
        (reservation.reservation_id,),
    ).fetchone()
    assert row["actual_amount"] == 1001
    denied = budget.reserve(
        lease=lease, reservation_key="after.overage", amounts=spend(), now=fx.NOW
    )
    assert not denied.allowed and denied.reason.endswith("CAP_EXHAUSTED")


def test_db_late_settlement_only_original_generation_and_expired_reserve_denied(conn):
    repo, budget, root, initial = fx.setup_shared(conn)
    repo.mark_preparing(initial, reason="fixture.release", now=fx.NOW)
    job = repo.enqueue(
        root_id=root,
        stage_key=f"late.{uuid4().hex}",
        profile=fx.profile(),
        retry_policy=fx.retry_policy(),
        now=fx.NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    old = repo.claim(
        root_id=root,
        lease_owner="worker.old",
        now=fx.NOW,
        lease_seconds=1,
        visibility="public",
    )
    assert old and old.job_id == job
    reservation = budget.reserve(
        lease=old, reservation_key="original", amounts=spend(), now=fx.NOW
    )
    sleep(1.05)
    with pytest.raises(SupplyRuntimeError, match="LEASE_STALE"):
        budget.reserve(lease=old, reservation_key="stale", amounts=spend(), now=fx.NOW)
    new = repo.claim(
        root_id=root,
        lease_owner="worker.new",
        now=fx.NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert new and new.generation == 2
    args = dict(
        reservation_id=reservation.reservation_id,
        settlement_key="late.cost",
        usage_state="known",
        actual=spend(),
        cost_amount=None,
        receipt_hash="c" * 64,
    )
    assert budget.settle(lease=old, **args).state == "known"
    with pytest.raises(SupplyRuntimeError, match="RESERVATION_UNAVAILABLE"):
        budget.settle(lease=new, **args)


def test_db_missing_limit_and_future_window_fail_closed(conn):
    repo, budget, root, lease = fx.setup_shared(
        conn, provider_key="provider.unconfigured"
    )
    # Future configuration cannot authorize now, even with a future caller time.
    conn.execute(
        "INSERT INTO tutor_item_supply_runtime_global_limits(dimension_kind,dimension_key,resource_kind,window_start,window_end,cap_amount) VALUES('provider','provider.future','requests',%s,%s,10)",
        (fx.NOW + timedelta(days=1), fx.NOW + timedelta(days=2)),
    )
    repo2, b2, r2, l2 = fx.setup_shared(conn, provider_key="provider.other")
    # Missing ALL other seven resources on a provider must fail closed.
    # Use a nested rollback to create a root without registering budgets.
    from tests.learning.test_item_supply_storage import shared
    from app.services.learning.item_supply.policies import (
        CoverageObligationV1,
        derive_runtime_contract_hash,
    )

    data = shared(conn)
    from app.services.learning.item_bank.contracts import canonical_hash

    # This is a genuinely different obligation, not a provider rebinding of a
    # canonical fixture root left by an earlier immutable commit.
    bp = data["blueprint"].model_copy(
        update={"objective_hash": canonical_hash(uuid4().hex)}
    )
    data = {
        **data,
        "blueprint": bp,
        "blueprint_id": data["repo"].register_blueprint(bp),
    }
    obligation = CoverageObligationV1(
        blueprint_hash=bp.blueprint_hash,
        scope_hash=bp.scope.scope_hash,
        objective_hash=bp.objective_hash,
        purpose=bp.scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(bp.scope),
        visibility="public",
        policy_version=bp.policy_version,
    )
    r = repo.ensure_shared_root(
        blueprint_id=data["blueprint_id"],
        obligation=obligation,
        pool="base",
        provider_key="provider.future",
    )
    p = fx.profile().model_copy(
        update={
            "profile_key": fx.profile().profile_key.model_copy(
                update={"provider": "provider.future"}
            )
        }
    )
    repo.enqueue(
        root_id=r,
        stage_key=f"future.{uuid4().hex}",
        profile=p,
        retry_policy=fx.retry_policy(),
        now=fx.NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    future = repo.claim(
        root_id=r,
        lease_owner="worker.future",
        now=fx.NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert future
    assert (
        budget.reserve(
            lease=future,
            reservation_key="future.cannot.choose",
            amounts=spend(),
            now=fx.NOW + timedelta(days=1),
        ).reason
        == "BUDGET_CONFIGURATION_MISSING"
    )


def test_db_two_connections_atomic_last_root_capacity_and_multidimension_locks(conn):
    repo, budget, root, one = fx.setup_shared(conn, root_request_cap=1)
    job = repo.enqueue(
        root_id=root,
        stage_key=f"race.{uuid4().hex}",
        profile=fx.profile(),
        retry_policy=fx.retry_policy(),
        now=fx.NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    two = repo.claim(
        root_id=root,
        lease_owner="worker.two",
        now=fx.NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert two and two.job_id == job
    conn.commit()
    barrier = Barrier(2)

    def reserve(lease):
        with psycopg.connect(fx.DSN, row_factory=dict_row) as c:
            c.execute("SET statement_timeout=5000")
            barrier.wait(timeout=5)
            result = ItemSupplyBudgetRepository(c).reserve(
                lease=lease,
                reservation_key="race.last",
                amounts=spend(candidates=1, fetches=1),
                now=fx.NOW,
            )
            c.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, (one, two)))
    assert sum(result.allowed for result in results) == 1
    rows = conn.execute(
        "SELECT id FROM tutor_item_supply_shared_reservations WHERE root_id=%s", (root,)
    ).fetchall()
    assert len(rows) == 1
    for kind in RESOURCE_KINDS:
        expected = spend(candidates=1, fetches=1).as_dict()[kind]
        assert (
            budget._root_used(
                "shared",
                root,
                conn.execute(
                    "SELECT window_id FROM tutor_item_supply_shared_reservations WHERE root_id=%s",
                    (root,),
                ).fetchone()["window_id"],
            )[kind]
            == expected
        )


def test_db_concurrent_equal_settlement_is_one_charge_sequence(conn):
    _, budget, _, lease = fx.setup_shared(conn)
    reservation = budget.reserve(
        lease=lease, reservation_key="settlement.race", amounts=spend(), now=fx.NOW
    )
    conn.commit()
    barrier = Barrier(2)

    def settle(_):
        with psycopg.connect(fx.DSN, row_factory=dict_row) as c:
            c.execute("SET statement_timeout=5000")
            barrier.wait(timeout=5)
            result = ItemSupplyBudgetRepository(c).settle(
                lease=lease,
                reservation_id=reservation.reservation_id,
                settlement_key="same.callback",
                usage_state="known",
                actual=spend(),
                cost_amount=None,
                receipt_hash="d" * 64,
            )
            c.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(settle, (1, 2)))
    assert [r.sequence for r in results] == [1, 1]
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=%s",
            (reservation.reservation_id,),
        ).fetchone()["n"]
        == 1
    )


def test_db_cancel_rebuild_new_client_keys_and_new_profile_keep_root_usage(conn):
    repo, budget, root, lease = fx.setup_shared(conn)
    reservation = budget.reserve(
        lease=lease, reservation_key="before.cancel", amounts=spend(10), now=fx.NOW
    )
    assert reservation.allowed
    row = conn.execute(
        "SELECT r.blueprint_id,o.obligation_json FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id WHERE r.id=%s",
        (root,),
    ).fetchone()
    from app.services.learning.item_supply.policies import CoverageObligationV1
    import json

    obligation = CoverageObligationV1.model_validate_json(
        json.dumps(row["obligation_json"])
    )
    repo.cancel(lease, now=fx.NOW)
    restarted = ItemSupplyRuntimeRepository(conn)
    assert (
        restarted.ensure_shared_root(
            blueprint_id=row["blueprint_id"],
            obligation=obligation,
            pool="base",
            provider_key="provider.synthetic",
        )
        == root
    )
    for pool, provider in (
        ("enhancement", "provider.synthetic"),
        ("base", "provider.other"),
    ):
        with pytest.raises(SupplyRuntimeError, match="ROOT_CONFLICT"):
            restarted.ensure_shared_root(
                blueprint_id=row["blueprint_id"],
                obligation=obligation,
                pool=pool,
                provider_key=provider,
            )
    restarted.enqueue(
        root_id=root,
        stage_key=f"new.client.candidate.{uuid4().hex}",
        profile=fx.profile(version=2),
        retry_policy=fx.retry_policy(),
        now=fx.NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    rebuilt = restarted.claim(
        root_id=root,
        lease_owner="worker.rebuilt",
        now=fx.NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert rebuilt and rebuilt.profile.profile_version == 2
    result = ItemSupplyBudgetRepository(conn).reserve(
        lease=rebuilt,
        reservation_key="new.client.reservation",
        amounts=spend(),
        now=fx.NOW,
    )
    assert not result.allowed and result.reason.endswith("CAP_EXHAUSTED")


def test_db_latest_unknown_retains_actual_overage_and_missing_facts_cannot_release(
    conn,
):
    _, budget, _, lease = fx.setup_shared(conn)
    reservation = budget.reserve(
        lease=lease, reservation_key="unknown.after.actual", amounts=spend(), now=fx.NOW
    )
    rid = reservation.reservation_id
    actual = spend(candidates=1001)
    budget.settle(
        lease=lease,
        reservation_id=rid,
        settlement_key="first.known",
        usage_state="known",
        actual=actual,
        cost_amount=None,
        receipt_hash="e" * 64,
    )
    assert budget._effective("shared", rid, "candidates", 0) == 1001
    budget.settle(
        lease=lease,
        reservation_id=rid,
        settlement_key="later.unknown",
        usage_state="unknown",
        actual=None,
        cost_amount=None,
        receipt_hash=None,
    )
    assert budget._effective("shared", rid, "candidates", 0) == 1001
    # Raw partial known facts cannot silently manufacture a full reconciliation.
    sid = conn.execute(
        "INSERT INTO tutor_item_supply_shared_runtime_settlements(reservation_id,sequence,settlement_key,usage_state,receipt_hash) VALUES(%s,3,'partial.known','known',%s) RETURNING id",
        (rid, "f" * 64),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO tutor_item_supply_shared_runtime_settlement_amounts(settlement_id,resource_kind,actual_amount) VALUES(%s,'requests',0)",
        (sid,),
    )
    conn.execute(
        "INSERT INTO tutor_item_supply_runtime_global_usage_facts(reservation_namespace,reservation_id,settlement_id,sequence,resource_kind,usage_state,actual_amount) VALUES('shared',%s,%s,3,'requests','known',0)",
        (rid, sid),
    )
    assert budget._effective("shared", rid, "candidates", 0) == 1001
    assert budget._effective("shared", rid, "requests", 1) == 1


def test_db_unknown_cannot_hide_known_downward_reconciliation_requirement(conn):
    _, budget, _, lease = fx.setup_shared(conn)
    rid = budget.reserve(
        lease=lease, reservation_key="known.unknown.lower", amounts=spend(), now=fx.NOW
    ).reservation_id
    budget.settle(
        lease=lease,
        reservation_id=rid,
        settlement_key="known.peak",
        usage_state="known",
        actual=spend(20),
        cost_amount=Decimal("2"),
        receipt_hash="a" * 64,
    )
    budget.settle(
        lease=lease,
        reservation_id=rid,
        settlement_key="later.unknown",
        usage_state="unknown",
        actual=None,
        cost_amount=None,
        receipt_hash=None,
    )
    lower = dict(
        lease=lease,
        reservation_id=rid,
        settlement_key="lower.known",
        usage_state="known",
        actual=ResourceAmounts(),
        cost_amount=Decimal("0"),
        receipt_hash="b" * 64,
    )
    with pytest.raises(SupplyRuntimeError, match="RECONCILIATION_REQUIRED"):
        budget.settle(**lower)
    assert budget._effective("shared", rid, "requests", 1) == 20
    assert budget.settle(**lower, reconcile=True).state == "known"
    assert budget._effective("shared", rid, "requests", 1) == 0


@pytest.mark.parametrize("boundary", ["cancel", "revision", "reset"])
def test_db_private_late_cost_boundary_keeps_global_facts_without_reviving_payload(
    conn, boundary
):
    from tests.learning.test_item_supply_storage import switch_revision
    from app.services.repositories.local_user_data_repository import reset_user_data

    o, _, _, repo, budget, _, lease = fx.setup_private(conn)
    rid = budget.reserve(
        lease=lease, reservation_key="boundary.cost", amounts=spend(), now=fx.NOW
    ).reservation_id
    budget.settle(
        lease=lease,
        reservation_id=rid,
        settlement_key="prior.overage",
        usage_state="known",
        actual=spend(20),
        cost_amount=None,
        receipt_hash="a" * 64,
    )
    budget.settle(
        lease=lease,
        reservation_id=rid,
        settlement_key="pending.unknown",
        usage_state="unknown",
        actual=None,
        cost_amount=None,
        receipt_hash=None,
    )
    if boundary == "cancel":
        repo.cancel(lease, now=fx.NOW)
    elif boundary == "revision":
        switch_revision(conn, o)
    else:
        reset_user_data(conn, str(o["user"]))
    with pytest.raises(SupplyRuntimeError, match="LEASE_STALE|PRIVATE_SCOPE_STALE"):
        repo.heartbeat(lease, now=fx.NOW, lease_seconds=60)
    late = dict(
        lease=lease,
        reservation_id=rid,
        settlement_key="late.original",
        usage_state="known",
        actual=spend(25),
        cost_amount=None,
        receipt_hash="b" * 64,
    )
    if boundary == "cancel":
        assert budget.settle(**late).state == "known"
        assert budget._effective("private", rid, "requests", 1) == 25
    else:
        # P3 deliberately does not authenticate post-revision/post-purge live
        # provider callbacks. It refuses them and preserves previous cost truth.
        with pytest.raises(
            SupplyRuntimeError, match="PRIVATE_SCOPE_STALE|JOB_UNAVAILABLE"
        ):
            budget.settle(**late)
        assert budget._effective("private", rid, "requests", 1) == 20


@pytest.mark.parametrize(
    "dimension,key",
    [("pool", "base"), ("provider", "provider.synthetic"), ("window", "item-supply")],
)
def test_db_each_cumulative_dimension_and_overlapping_window_enforced(
    conn, dimension, key
):
    _, budget, _, lease = fx.setup_shared(conn)
    # The stricter overlapping cumulative row remains authoritative, even when
    # a newer permissive window exists. Client time cannot choose between them.
    budget.register_global_limit(
        dimension_kind=dimension,
        dimension_key=key,
        resource_kind="requests",
        window_start=fx.NOW - timedelta(seconds=2),
        window_end=fx.WINDOW_END,
        cap_amount=1,
    )
    assert budget.reserve(
        lease=lease, reservation_key="first.cumulative", amounts=spend(), now=fx.NOW
    ).allowed
    denied = budget.reserve(
        lease=lease,
        reservation_key="second.cumulative",
        amounts=spend(),
        now=fx.NOW + timedelta(days=1),
    )
    assert not denied.allowed and denied.reason == f"{dimension.upper()}_CAP_EXHAUSTED"


def test_db_private_user_cumulative_cap_applies_across_new_job(conn):
    o, _, _, repo, budget, root, lease = fx.setup_private(conn)
    budget.register_user_limit(
        user_id=o["user"],
        epoch=1,
        resource_kind="requests",
        window_start=fx.NOW - timedelta(seconds=2),
        window_end=fx.WINDOW_END,
        cap_amount=1,
    )
    assert budget.reserve(
        lease=lease, reservation_key="user.first", amounts=spend(), now=fx.NOW
    ).allowed
    repo.enqueue(
        root_id=root,
        stage_key=f"user.new.{uuid4().hex}",
        profile=fx.profile(version=2),
        retry_policy=fx.retry_policy(),
        now=fx.NOW,
        priority=100,
        aging_seconds=1,
        visibility="private",
        user_id=o["user"],
        epoch=1,
        scope_id=o["scope"].id,
    )
    other = repo.claim(
        root_id=root,
        lease_owner="worker.user.two",
        now=fx.NOW,
        lease_seconds=60,
        visibility="private",
        user_id=o["user"],
        epoch=1,
    )
    assert other
    denied = budget.reserve(
        lease=other, reservation_key="user.second", amounts=spend(), now=fx.NOW
    )
    assert not denied.allowed and denied.reason == "USER_CAP_EXHAUSTED"


def test_db_waiting_for_global_limit_lock_cannot_spend_expired_window(conn):
    _, _, _, lease = fx.setup_shared(conn)
    conn.commit()
    conn.execute(
        "SELECT id FROM tutor_item_supply_runtime_global_limits WHERE window_start=%s AND window_end=%s ORDER BY dimension_kind,dimension_key,resource_kind,id LIMIT 1 FOR UPDATE",
        (fx.NOW - timedelta(seconds=1), fx.WINDOW_END),
    )
    blocker = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    ready = Queue()

    def callback():
        with psycopg.connect(fx.DSN, row_factory=dict_row) as other:
            assert (
                other.execute("SELECT current_database() AS db").fetchone()["db"]
                == "aearn_b1b_fixture_20260930"
            )
            other.execute("SET LOCAL statement_timeout='15s'")
            ready.put(other.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            try:
                return ItemSupplyBudgetRepository(other).reserve(
                    lease=lease,
                    reservation_key="wait.window",
                    amounts=spend(),
                    now=fx.NOW,
                )
            finally:
                other.rollback()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(callback)
        pid = ready.get(timeout=2)
        stop = monotonic() + 2
        while (
            blocker
            not in conn.execute(
                "SELECT pg_blocking_pids(%s) AS blockers", (pid,)
            ).fetchone()["blockers"]
        ):
            assert not future.done() and monotonic() < stop
            sleep(0.01)
        stop = monotonic() + 14
        while (
            conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            <= fx.WINDOW_END
        ):
            assert monotonic() < stop
            sleep(0.05)
        conn.commit()
        result = future.result(timeout=5)
        assert not result.allowed and result.reason in {
            "ROOT_WINDOW_MISSING",
            "BUDGET_CONFIGURATION_MISSING",
        }
