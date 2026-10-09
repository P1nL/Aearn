"""P3 PG lease/CAS/recovery regressions, no provider or fabricated handler."""

from __future__ import annotations

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic
from time import sleep
from uuid import uuid4

import pytest
import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings
from app.services.learning.item_supply.jobs import CheckpointV1
from app.services.learning.item_supply.policies import (
    FailureClass,
    ResourceAmounts,
    SupplyRuntimeError,
)
from app.services.learning.item_supply.scheduler import OwnerPartition, claim_bounded
from tests.learning.test_item_supply_runtime import (
    NOW,
    conn as conn,
    profile,
    retry_policy,
    setup_private,
    setup_shared,
)
from tests.learning import test_item_supply_runtime as fx


def receipt(stage="generating", *, attempt=1, digest="a", status="completed"):
    return CheckpointV1(
        stage=stage,
        attempt=attempt,
        status=status,
        receipt_hash=digest * 64,
        safe_reason="synthetic.internal.receipt",
    )


def test_disabled_owner_budget_and_invalid_partition_never_query():
    class NoQuery:
        def __getattr__(self, name):
            raise AssertionError("disabled scheduler performed IO")

    kwargs = dict(
        repository=NoQuery(),
        owner=None,
        worker_id="worker.test",
        now=NOW,
        limit=1,
        lease_seconds=1,
        registered_handlers=frozenset(),
    )
    assert claim_bounded(settings=Settings(), **kwargs).state == "disabled"
    settings = Settings(
        learning_item_supply_enabled=True,
        learning_item_generation_enabled=True,
        learning_item_supply_scheduler_enabled=True,
    )
    assert claim_bounded(settings=settings, **kwargs).state == "owner_required"
    kwargs["owner"] = OwnerPartition("public", uuid4(), uuid4(), 1)
    assert claim_bounded(settings=settings, **kwargs).state == "invalid_owner"
    kwargs["owner"] = OwnerPartition("public", uuid4())
    assert claim_bounded(settings=settings, **kwargs).state == "budget_required"


@pytest.mark.parametrize("operation", ["heartbeat", "reserve"])
def test_db_waiting_for_control_lock_cannot_revive_expired_lease(conn, operation):
    repo, _, _, lease = setup_shared(conn)
    conn.execute(
        "UPDATE tutor_item_supply_shared_job_controls SET lease_expires_at=clock_timestamp()+interval '1 second' WHERE job_id=%s",
        (lease.job_id,),
    )
    conn.commit()
    conn.execute(
        "SELECT id FROM tutor_item_supply_shared_job_controls WHERE job_id=%s FOR UPDATE",
        (lease.job_id,),
    )
    blocker = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    ready = Queue()

    def callback():
        from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
        from app.services.learning.item_supply.repository import (
            ItemSupplyRuntimeRepository,
        )

        with psycopg.connect(fx.DSN, row_factory=dict_row) as other:
            assert (
                other.execute("SELECT current_database() AS db").fetchone()["db"]
                == "aearn_b1b_fixture_20260930"
            )
            other.execute("SET LOCAL statement_timeout='5s'")
            ready.put(other.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            try:
                if operation == "heartbeat":
                    ItemSupplyRuntimeRepository(other).heartbeat(
                        lease, now=NOW, lease_seconds=60
                    )
                else:
                    ItemSupplyBudgetRepository(other).reserve(
                        lease=lease,
                        reservation_key="wait.expired",
                        amounts=ResourceAmounts(
                            requests=1, input_tokens=1, output_tokens=1
                        ),
                        now=NOW,
                    )
                return "accepted"
            except SupplyRuntimeError as error:
                return str(error)
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
        sleep(1.1)
        conn.commit()
        assert future.result(timeout=5) == "LEASE_STALE"


def test_db_checkpoint_exact_replay_conflict_cas_and_stage_order(conn):
    repo, _, _, lease = setup_shared(conn)
    with pytest.raises(SupplyRuntimeError, match="STAGE_ORDER_MISMATCH"):
        repo.checkpoint(lease, receipt("reviewing"), now=NOW)
    first = receipt()
    assert repo.checkpoint(lease, first, now=NOW) == "validating"
    assert repo.checkpoint(lease, first, now=NOW) == "validating"
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_item_supply_shared_checkpoints WHERE job_id=%s",
            (lease.job_id,),
        ).fetchone()["n"]
        == 1
    )
    with pytest.raises(SupplyRuntimeError, match="CHECKPOINT_CONFLICT"):
        repo.checkpoint(lease, receipt(digest="b"), now=NOW)
    with pytest.raises(SupplyRuntimeError, match="STATE_VERSION_STALE"):
        repo.checkpoint(lease, receipt("validating"), now=NOW)
    lease = repo.refresh_lease(lease, now=NOW)
    assert repo.checkpoint(lease, receipt("validating"), now=NOW) == "reviewing"
    with pytest.raises(SupplyRuntimeError, match="STAGES_INCOMPLETE"):
        repo.complete(repo.refresh_lease(lease, now=NOW), now=NOW)


def test_db_crash_reclaim_new_generation_only_missing_stage(conn):
    repo, _, root, lease = setup_shared(conn)
    repo.checkpoint(lease, receipt(), now=NOW)
    lease = repo.refresh_lease(lease, now=NOW)
    # Expire a short REAL server-clock lease, not an injected future timestamp.
    repo.mark_preparing(lease, reason="isolated.crash.fixture", now=NOW)
    job = repo.enqueue(
        root_id=root,
        stage_key=f"crash.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    old = repo.claim(
        root_id=root,
        lease_owner="worker.crash",
        now=NOW,
        lease_seconds=1,
        visibility="public",
    )
    assert old and old.job_id == job
    repo.checkpoint(old, receipt(), now=NOW)
    old = repo.refresh_lease(old, now=NOW)
    sleep(1.05)
    resumed = repo.claim(
        root_id=root,
        lease_owner="worker.recovery",
        now=NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert (
        resumed and resumed.job_id == job and resumed.generation == old.generation + 1
    )
    assert repo.next_stage(resumed) == "validating"
    assert (
        resumed.profile == old.profile
        and resumed.parent_deadline == old.parent_deadline
    )
    with pytest.raises(SupplyRuntimeError, match="LEASE_STALE"):
        repo.checkpoint(old, receipt("validating"), now=NOW)
    repo.checkpoint(resumed, receipt("validating", attempt=2), now=NOW)
    assert repo.next_stage(resumed) == "reviewing"


def test_db_transient_retry_wait_is_bounded_and_preserves_snapshot(conn):
    repo, _, root, lease = setup_shared(conn)
    assert repo.fail(lease, failure=FailureClass.TRANSIENT, now=NOW) == "retry_wait"
    assert (
        repo.claim(
            root_id=root,
            lease_owner="worker.retry",
            now=NOW,
            lease_seconds=60,
            visibility="public",
        )
        is None
    )
    sleep(1.05)
    second = repo.claim(
        root_id=root,
        lease_owner="worker.retry",
        now=NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert second and second.generation == 2 and second.profile == lease.profile
    assert repo.fail(second, failure=FailureClass.TRANSIENT, now=NOW) == "retry_wait"
    sleep(2.05)
    third = repo.claim(
        root_id=root,
        lease_owner="worker.retry",
        now=NOW,
        lease_seconds=60,
        visibility="public",
    )
    assert third and third.generation == 3
    assert repo.fail(third, failure=FailureClass.TRANSIENT, now=NOW) == "blocked"
    assert (
        repo.claim(
            root_id=root,
            lease_owner="worker.retry",
            now=NOW,
            lease_seconds=60,
            visibility="public",
        )
        is None
    )


@pytest.mark.parametrize(
    "failure", [FailureClass.DETERMINISTIC, FailureClass.SAFETY, FailureClass.SCORING]
)
def test_db_deterministic_breaker_no_retry(conn, failure):
    repo, _, root, lease = setup_shared(conn)
    assert repo.fail(lease, failure=failure, now=NOW) == "blocked"
    row = conn.execute(
        "SELECT breaker_open,attempt_count FROM tutor_item_supply_shared_job_controls WHERE job_id=%s",
        (lease.job_id,),
    ).fetchone()
    assert row["breaker_open"] and row["attempt_count"] == 1
    assert (
        repo.claim(
            root_id=root,
            lease_owner="worker.other",
            now=NOW,
            lease_seconds=60,
            visibility="public",
        )
        is None
    )


def test_db_profile_reenqueue_and_heartbeat_cannot_move_deadline(conn):
    repo, _, root, lease = setup_shared(conn)
    heartbeat = repo.heartbeat(lease, now=NOW + timedelta(days=10), lease_seconds=3600)
    assert heartbeat.expires_at == lease.parent_deadline
    assert heartbeat.profile == lease.profile
    job = repo.enqueue(
        root_id=root,
        stage_key=f"snapshot.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=999,
        aging_seconds=1,
        visibility="public",
        parent_job_id=lease.job_id,
    )
    original = conn.execute(
        "SELECT parent_deadline,profile_snapshot_json FROM tutor_item_supply_shared_job_controls WHERE job_id=%s",
        (job,),
    ).fetchone()
    assert original["parent_deadline"] == lease.parent_deadline
    new_profile = profile(version=2)
    # A new job freezes a new profile, existing jobs retain their first binding.
    repo.enqueue(
        root_id=root,
        stage_key=f"next.{uuid4().hex}",
        profile=new_profile,
        retry_policy=retry_policy(),
        now=NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    assert (
        conn.execute(
            "SELECT parent_deadline,profile_snapshot_json FROM tutor_item_supply_shared_job_controls WHERE job_id=%s",
            (job,),
        ).fetchone()
        == original
    )


def test_db_missing_retry_profile_handler_and_budget_fail_closed(conn):
    repo, budget, root, lease = setup_shared(conn)
    repo.mark_preparing(lease, reason="fixture.release", now=NOW)
    missing = repo.enqueue(
        root_id=root,
        stage_key=f"missing.{uuid4().hex}",
        profile=profile(),
        now=NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    assert (
        conn.execute(
            "SELECT state FROM tutor_item_supply_shared_job_controls WHERE job_id=%s",
            (missing,),
        ).fetchone()["state"]
        == "preparing"
    )
    assert (
        repo.claim(
            root_id=root,
            lease_owner="worker.none",
            now=NOW,
            lease_seconds=60,
            visibility="public",
        )
        is None
    )
    with pytest.raises(SupplyRuntimeError, match="PROFILE_NOT_EXECUTABLE"):
        repo.enqueue(
            root_id=root,
            stage_key="blocked.profile",
            profile=profile(state="blocked"),
            now=NOW,
            priority=100,
            aging_seconds=1,
            visibility="public",
        )
    job = repo.enqueue(
        root_id=root,
        stage_key=f"handler.{uuid4().hex}",
        profile=profile(),
        retry_policy=retry_policy(),
        now=NOW,
        priority=100,
        aging_seconds=1,
        visibility="public",
    )
    from app.services.learning.item_supply.jobs import JOB_STAGES

    settings = Settings(
        learning_item_supply_enabled=True,
        learning_item_generation_enabled=True,
        learning_item_supply_scheduler_enabled=True,
    )
    batch = claim_bounded(
        settings=settings,
        repository=repo,
        owner=OwnerPartition("public", root),
        worker_id="worker.handler",
        now=NOW,
        limit=1,
        lease_seconds=60,
        registered_handlers=frozenset(),
        budget=budget,
        stage_budgets={
            stage: ResourceAmounts(requests=1, input_tokens=1) for stage in JOB_STAGES
        },
    )
    assert batch.state == "preparing" and not batch.leases
    assert (
        conn.execute(
            "SELECT state FROM tutor_item_supply_shared_job_controls WHERE job_id=%s",
            (job,),
        ).fetchone()["state"]
        == "preparing"
    )


def test_db_private_owner_cannot_adopt_lease_or_root(conn):
    o, _, _, repo, _, root, lease = setup_private(conn)
    with pytest.raises(SupplyRuntimeError, match="PRIVATE_EPOCH_STALE"):
        repo.claim(
            root_id=root,
            lease_owner="worker.other",
            now=NOW,
            lease_seconds=60,
            visibility="private",
            user_id=uuid4(),
            epoch=1,
        )
    with pytest.raises(SupplyRuntimeError, match="LEASE_STALE"):
        repo.checkpoint(
            lease.model_copy(update={"owner_id": uuid4()}), receipt(), now=NOW
        )
    assert (
        conn.execute(
            "SELECT user_id FROM tutor_item_supply_private_job_controls WHERE job_id=%s",
            (lease.job_id,),
        ).fetchone()["user_id"]
        == o["user"]
    )
