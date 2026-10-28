"""Opt-in SQL596-598 contracts; Main preinstalls schema. Use --noconftest.

No bootstrap, provider, runner, source GET or cleanup. Retain synthetic audit rows.
"""
from __future__ import annotations

# Main disables dotenv/models before collection; do not mutate process-wide
# environment at import time and affect unrelated tests in a combined run.
import hashlib
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import cast
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from app.agents.harness.contracts import (
    TutorDecision, TutorLease,
    TutorPolicySnapshot, TutorProviderResult, TutorRunSnapshot,
)
from app.agents.harness.skill_catalog import (
    PublishedSkill, SkillCatalogSnapshot, SkillContentHash, SkillManifest, _snapshot_digest,
)
from app.agents.runtime.contracts import (
    RuntimePlanningStepResult, RuntimeTerminalStatus, RuntimeThreadHandle, RuntimeTurnResult,
)
from app.core.config import Settings
from app.services.tutor.completion_execution import (
    CompletionExecutionError, CompletionExecutionOwner, ExecutionBatch, StepAttempt,
    completion_admission_policy,
)
from app.services.tutor.conversation_contracts import TutorInteractionProtocolVersion
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.runtime_projection import (
    PostgresTutorRuntimeProjectionRepository, TutorRuntimeBinding, TutorRuntimeProjectionFence,
)

_URL_ENV = "AEARN_COMPLETION_TEST_DATABASE_URL"
_OFFLINE_URL = "postgresql://offline:offline@127.0.0.1:1/offline"


def _checked_url() -> str:
    value = os.environ.get(_URL_ENV)
    if value is None:
        pytest.skip(f"{_URL_ENV} absent; Main owns PostgreSQL acceptance")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.query or parsed.fragment
        or re.fullmatch(r"/aearn_completion_b_test_[A-Za-z0-9_]+", unquote(parsed.path)) is None
    ):
        raise ValueError(f"{_URL_ENV} requires local aearn_completion_b_test_ DB, no URL query")
    return value


def _connect(url: str) -> Connection[dict[str, object]]:
    if url != _checked_url():
        raise ValueError("completion test URL changed")
    # Pin loopback even if libpq inherits PGHOSTADDR/service settings. No pgpass.
    return psycopg.connect(
        url, hostaddr="127.0.0.1", passfile=os.devnull, autocommit=True,
        row_factory=dict_row, connect_timeout=3,
        application_name="aearn_completion_b_contract_tests",
        options="-c statement_timeout=5000 -c lock_timeout=2000",
    )


def _clock(conn: Connection[dict[str, object]]) -> datetime:
    row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
    assert row is not None and isinstance(row["now"], datetime)
    return row["now"]


def _repository(conn: Connection[dict[str, object]]) -> PostgresTutorRepository:
    return PostgresTutorRepository(conn, settings=Settings(
        database_url=_OFFLINE_URL, llm_type="disabled", codex_runtime_enabled=False,
        openai_api_key=None, deepseek_api_key=None,
    ))


def _catalog(identity: str) -> SkillCatalogSnapshot:
    """In-memory inert evidence; no published bundles/schema manifest loaded."""
    instruction = f"Synthetic completion persistence evidence {identity}."
    instruction_hash = hashlib.sha256(instruction.encode()).hexdigest()
    evaluation_hash = hashlib.sha256(b'{"cases":[]}').hexdigest()
    manifest = SkillManifest(
        id=f"tutor.completion-test-{identity}", version="1.0.0", owner="test",
        kind="test", summary="Synthetic persistence evidence only",
        instruction_file="instructions.md", evaluation_suite_file="evals.json",
        content_hashes=(
            SkillContentHash(file="instructions.md", sha256=instruction_hash),
            SkillContentHash(file="evals.json", sha256=evaluation_hash),
        ),
        input_contract="tutor.completion-test-input.v1",
        output_contract="tutor.completion-test-output.v1",
    )
    skill = PublishedSkill(
        manifest=manifest, instruction=instruction, instruction_hash=instruction_hash,
        evaluation_hash=evaluation_hash,
        manifest_hash=hashlib.sha256(manifest.model_dump_json().encode()).hexdigest(),
    )
    return SkillCatalogSnapshot(
        skills=(skill,), capability_descriptors=(), effect_descriptors=(),
        digest=_snapshot_digest(skills=(skill,), capability_descriptors=(), effect_descriptors=()),
    )


@dataclass(frozen=True)
class CompletionPG:
    url: str = field(repr=False)
    conn: Connection[dict[str, object]]
    repository: PostgresTutorRepository
    run: TutorRunSnapshot
    lease: TutorLease


@pytest.fixture
def completion_pg(request: pytest.FixtureRequest) -> Iterator[CompletionPG]:
    url = _checked_url()
    with _connect(url) as conn:
        for table in (
            "tutor_run_execution_batches", "tutor_run_step_attempts",
            "tutor_lesson_authoring_stage_attempts",
        ):
            row = conn.execute("SELECT to_regclass(%s) AS relation", (f"public.{table}",)).fetchone()
            assert row is not None and row["relation"] is not None, f"Main must preinstall {table}"
        column = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='tutor_run_runtime_bindings' AND column_name='step_attempt_id'",
        ).fetchone()
        assert column is not None, "Main must preinstall SQL598"
        mode = getattr(request, "param", "provider")
        assert mode in {"provider", "sidecar", "legacy"}
        identity, user_id = uuid4().hex, str(uuid4())
        repository = _repository(conn)
        with conn.transaction():
            conn.execute("INSERT INTO users (id,display_name) VALUES (%s,%s)",
                         (user_id, f"Completion B synthetic {identity}"))
            conn.execute(
                "INSERT INTO harness_cutovers (user_id,cutover_version,state,verified_at) "
                "VALUES (%s,'harness_clean_slate_v1','verified',clock_timestamp())", (user_id,),
            )
            catalog = _catalog(identity)
            repository.record_catalog_snapshot(catalog)
            conversation = repository.create_conversation(user_id=user_id)
            now = _clock(conn)
            policy = TutorPolicySnapshot(
                deadline=now, max_capability_calls=2, max_effects=2,
                context_token_budget=64, lease_duration_seconds=600,
            )
            if mode != "legacy":
                policy = completion_admission_policy(policy, now=now)
            run = repository.create_run(
                user_id=user_id, conversation_id=conversation, catalog_digest=catalog.digest,
                policy=policy, origin="interactive",
                interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
                runtime_kind="harness_v1" if mode == "provider" else "codex_sidecar_v1",
            )
            repository.accept_input(
                user_id=user_id, run_id=run.run_id, idempotency_key=f"input-{identity}",
                content="Synthetic persistence input; do not dispatch.", ensure_dispatch=False,
            )
            lease = repository.acquire_lease(
                user_id=user_id, run_id=run.run_id, owner_id=f"test-{identity}",
                now=now, duration_seconds=600,
            )
            assert lease is not None
            current = repository.load_snapshot(user_id=user_id, run_id=run.run_id)
            assert current is not None and current.input_revision == 1
        assert conn.info.transaction_status == TransactionStatus.IDLE
        yield CompletionPG(url, conn, repository, current, lease)
        # Close only. Committed synthetic audit rows remain even on test failure.


def _result(run: TutorRunSnapshot) -> TutorProviderResult | RuntimePlanningStepResult:
    if run.runtime_kind == "harness_v1":
        return TutorProviderResult(decision=TutorDecision(public_message="Synthetic durable answer."))
    return RuntimePlanningStepResult(
        runtime=RuntimeTurnResult(
            thread=RuntimeThreadHandle(thread_id=f"thread-{run.run_id}", generation=1),
            turn_id=f"turn-{uuid4()}", terminal_status=RuntimeTerminalStatus.COMPLETED, events=(),
        ),
        planning_state={"status": "synthetic_data_only"}, tool_results=(),
        tool_call_count=0, tool_repair_count=0,
    )


def _prepare(case: CompletionPG, *, key: str = "step-1") -> tuple[CompletionExecutionOwner, ExecutionBatch, StepAttempt]:
    owner = CompletionExecutionOwner(case.conn)
    batch = owner.ensure_batch(run=case.run, lease=case.lease)
    step = owner.prepare_step(
        run=case.run, lease=case.lease, batch=batch, step_key=key,
        kind="provider_decision" if case.run.runtime_kind == "harness_v1" else "sidecar_turn",
        request={"synthetic": True, "step": key},
        dependencies={"catalog_scope": case.run.conversation_id, "revision": case.run.input_revision},
    )
    return owner, batch, step


def _renew(case: CompletionPG, conn: Connection[dict[str, object]]) -> tuple[TutorRunSnapshot, TutorLease]:
    repository = _repository(conn)
    # Same-owner reacquisition increments generation; no expiry rewrite/fake clock.
    lease = repository.acquire_lease(
        user_id=case.run.user_id, run_id=case.run.run_id, owner_id=case.lease.owner_id,
        now=_clock(conn), duration_seconds=600,
    )
    run = repository.load_snapshot(user_id=case.run.user_id, run_id=case.run.run_id)
    assert lease is not None and run is not None and lease.generation > case.lease.generation
    return run, lease


def _insert_successor(conn: Connection[dict[str, object]], batch: ExecutionBatch, lease: TutorLease) -> None:
    # Bypass Python deliberately to exercise SQL596's data-dependent guard.
    conn.execute(
        """INSERT INTO tutor_run_execution_batches
        (run_id,user_id,conversation_id,input_revision,predecessor_batch_id,batch_index,
         owner_id,owner_generation,policy_fingerprint,issued_at,expires_at)
        SELECT run_id,user_id,conversation_id,input_revision,id,batch_index+1,%s,%s,
         policy_fingerprint,clock_timestamp(),clock_timestamp()+interval '2300 seconds'
        FROM tutor_run_execution_batches WHERE id=%s""",
        (lease.owner_id, lease.generation, batch.id),
    )


@pytest.mark.parametrize("completion_pg", ["provider", "sidecar"], indirect=True)
def test_committed_result_cold_recovery_fresh_acceptance_once(completion_pg: CompletionPG) -> None:
    case = completion_pg
    owner, batch, step = _prepare(case)
    expected = _result(case.run)
    with _connect(case.url) as cold:
        recovered = CompletionExecutionOwner(cold)
        pending = recovered.pending_step(run=case.run, lease=case.lease)
        assert pending is not None and pending.id == step.id and pending.state == "prepared"
        step = owner.mark_dispatched(run=case.run, lease=case.lease, step=step)
        pending = recovered.pending_step(run=case.run, lease=case.lease)
        assert pending is not None and pending.state == "dispatched"
        if case.run.runtime_kind == "harness_v1":
            # Observable intent accounting only. No transport/provider is invoked.
            owner.record_http_attempt(run=case.run, lease=case.lease, step=step, batch=batch)
        owner.record_result(run=case.run, lease=case.lease, step=step, result=expected)
        case.conn.close()  # Cold recovery cannot reuse the original connection.
        run, lease = _renew(case, cold)
        restored = recovered.pending_step(run=run, lease=lease)
        assert restored is not None and restored.state == "result_recorded"
        assert restored.result == expected and type(restored.result) is type(expected)
        if isinstance(restored.result, RuntimePlanningStepResult):
            assert restored.result.model_http_request_count is None
            assert restored.result.model_usage_available is False
        fresh = recovered.ensure_batch(run=run, lease=lease)
        assert fresh.predecessor_batch_id == batch.id

        def validate() -> None:
            row = cold.execute(
                "SELECT input_revision,active_lease_generation FROM tutor_runs WHERE id=%s", (run.run_id,),
            ).fetchone()
            assert row == {"input_revision": run.input_revision, "active_lease_generation": lease.generation}

        def consume() -> int:
            row = cold.execute(
                "UPDATE tutor_runs SET effect_count=effect_count+1 WHERE id=%s RETURNING effect_count",
                (run.run_id,),
            ).fetchone()
            assert row is not None
            return cast(int, row["effect_count"])

        with pytest.raises(CompletionExecutionError, match="completion_current_owner_required"):
            recovered.accept_result(
                run=run, lease=case.lease, step=restored, batch=fresh,
                dependencies=restored.dependencies, validate=validate, consume=consume,
            )
        with pytest.raises(CompletionExecutionError, match="completion_result_not_consumable"):
            recovered.accept_result(
                run=run, lease=lease, step=restored, batch=fresh,
                dependencies={"wrong_revision": True}, validate=validate, consume=consume,
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="completion fresh acceptance batch required"):
            recovered.accept_result(
                run=run, lease=lease, step=restored, batch=batch,
                dependencies=restored.dependencies, validate=validate, consume=consume,
            )

        def failed_consume() -> int:
            consume()
            raise RuntimeError("synthetic_consumer_rollback")

        with pytest.raises(RuntimeError, match="synthetic_consumer_rollback"):
            recovered.accept_result(
                run=run, lease=lease, step=restored, batch=fresh,
                dependencies=restored.dependencies, validate=validate, consume=failed_consume,
            )
        row = cold.execute(
            "SELECT s.state,r.effect_count FROM tutor_run_step_attempts s "
            "JOIN tutor_runs r ON r.id=s.run_id WHERE s.id=%s", (restored.id,),
        ).fetchone()
        assert row == {"state": "result_recorded", "effect_count": 0}
        assert recovered.accept_result(
            run=run, lease=lease, step=restored, batch=fresh,
            dependencies=restored.dependencies, validate=validate, consume=consume,
        ) == 1
        with pytest.raises(CompletionExecutionError, match="completion_result_not_consumable"):
            recovered.accept_result(
                run=run, lease=lease, step=restored, batch=fresh,
                dependencies=restored.dependencies, validate=validate, consume=consume,
            )
        row = cold.execute(
            "SELECT s.state,s.accepted_owner_generation,s.acceptance_batch_id,r.effect_count "
            "FROM tutor_run_step_attempts s JOIN tutor_runs r ON r.id=s.run_id WHERE s.id=%s", (restored.id,),
        ).fetchone()
        assert row is not None and row["state"] == "accepted" and row["effect_count"] == 1
        assert row["accepted_owner_generation"] == lease.generation
        assert str(row["acceptance_batch_id"]) == fresh.id
        assert recovered.pending_step(run=run, lease=lease) is None


@pytest.mark.parametrize("with_result", [False, True])
def test_unknown_blocks_rekey_successor_and_consumption(completion_pg: CompletionPG, with_result: bool) -> None:
    case = completion_pg
    owner, batch, step = _prepare(case)
    step = owner.mark_dispatched(run=case.run, lease=case.lease, step=step)
    if with_result:
        owner.record_result(
            run=case.run, lease=case.lease, step=step, result=_result(case.run), outcome_unknown=True,
        )
    else:
        owner.mark_unknown(run=case.run, lease=case.lease, step=step)
    # Original owner/batch still match: specifically exercise the active-step index.
    with pytest.raises(psycopg.errors.UniqueViolation) as conflict:
        owner.prepare_step(
            run=case.run, lease=case.lease, batch=batch, step_key="rekeyed-unknown", kind=step.kind,
            request={"new_key": True}, dependencies=step.dependencies,
        )
    assert conflict.value.diag.constraint_name == "uq_tutor_completion_active_step"
    with _connect(case.url) as cold:
        run, lease = _renew(case, cold)
        recovered = CompletionExecutionOwner(cold)
        unknown = recovered.pending_step(run=run, lease=lease)
        assert unknown is not None and unknown.state == "outcome_unknown"
        assert (unknown.result is not None) is with_result
        with pytest.raises(CompletionExecutionError, match="completion_unresolved_attempt"):
            recovered.ensure_batch(run=run, lease=lease)
        with pytest.raises(psycopg.errors.CheckViolation, match="completion unresolved attempt blocks successor"):
            _insert_successor(cold, batch, lease)
        with pytest.raises(CompletionExecutionError, match="completion_unresolved_attempt"):
            recovered.prepare_step(
                run=run, lease=lease, batch=batch, step_key=unknown.step_key, kind=unknown.kind,
                request=unknown.request, dependencies=unknown.dependencies,
            )
        with pytest.raises(CompletionExecutionError, match="completion_result_not_consumable"):
            recovered.accept_result(
                run=run, lease=lease, step=unknown, batch=batch, dependencies=unknown.dependencies,
                validate=lambda: None, consume=lambda: cold.execute("SELECT 1").fetchone(),
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="completion final result immutable"):
            cold.execute(
                "UPDATE tutor_run_step_attempts SET diagnostic_code='retry_forbidden' WHERE id=%s", (unknown.id,),
            )


def test_successor_is_unique_and_cumulative_accounting_cannot_regress(completion_pg: CompletionPG) -> None:
    case = completion_pg
    owner, root, step = _prepare(case)
    step = owner.mark_dispatched(run=case.run, lease=case.lease, step=step)
    owner.record_http_attempt(run=case.run, lease=case.lease, step=step, batch=root)
    step = owner.record_result(run=case.run, lease=case.lease, step=step, result=_result(case.run))
    progress = owner.action_progress(
        run=case.run, lease=case.lease, step=step, capability_count=1, effect_count=1,
    )
    owner.accept_result(
        run=progress, lease=case.lease, step=step, batch=root, dependencies=step.dependencies,
        validate=lambda: None, consume=lambda: case.conn.execute("SELECT 1").fetchone(),
    )
    with _connect(case.url) as cold:
        run, lease = _renew(case, cold)
        current = CompletionExecutionOwner(cold)
        successor = current.ensure_batch(run=run, lease=lease)
        assert successor.batch_index == root.batch_index + 1 and successor.predecessor_batch_id == root.id
        assert current.ensure_batch(run=run, lease=lease).id == successor.id
        with pytest.raises(psycopg.errors.UniqueViolation):
            _insert_successor(cold, root, lease)
        second = current.prepare_step(
            run=run, lease=lease, batch=successor, step_key="step-2", kind=step.kind,
            request={"synthetic": True, "step": "step-2"}, dependencies=step.dependencies,
        )
        second = current.mark_dispatched(run=run, lease=lease, step=second)
        assert second.decision_iteration == 2
        current.record_http_attempt(run=run, lease=lease, step=second, batch=successor)
        second = current.record_result(run=run, lease=lease, step=second, result=_result(run))
        current.accept_result(
            run=run, lease=lease, step=second, batch=successor, dependencies=second.dependencies,
            validate=lambda: None, consume=lambda: cold.execute("SELECT 1").fetchone(),
        )
        rows = cold.execute(
            "SELECT decision_count,http_attempt_count FROM tutor_run_execution_batches "
            "WHERE run_id=%s ORDER BY batch_index", (run.run_id,),
        ).fetchall()
        assert rows == [
            {"decision_count": 1, "http_attempt_count": 1},
            {"decision_count": 1, "http_attempt_count": 1},
        ]
        for field in ("iteration_count", "model_call_count", "capability_call_count", "effect_count"):
            with pytest.raises(psycopg.errors.CheckViolation, match="completion cumulative counters cannot decrease"):
                cold.execute(
                    sql.SQL("UPDATE tutor_runs SET {}=0 WHERE id=%s").format(sql.Identifier(field)), (run.run_id,),
                )
        with pytest.raises(psycopg.errors.CheckViolation, match="completion batch identity and accounting immutable"):
            cold.execute("UPDATE tutor_run_execution_batches SET http_attempt_count=0 WHERE id=%s", (successor.id,))
        snapshot = _repository(cold).load_snapshot(user_id=run.user_id, run_id=run.run_id)
        assert snapshot is not None
        assert (snapshot.iteration_count, snapshot.model_call_count, snapshot.capability_call_count, snapshot.effect_count) == (2, 2, 1, 1)


def _bind(case: CompletionPG, step: StepAttempt | None) -> TutorRuntimeBinding:
    return PostgresTutorRuntimeProjectionRepository(case.conn).bind_run(
        user_id=case.run.user_id, run_id=case.run.run_id,
        fence=TutorRuntimeProjectionFence(
            input_revision=case.run.input_revision, lease_owner_id=case.lease.owner_id,
            lease_generation=case.lease.generation, connection_generation=1,
        ),
        runtime_version="synthetic-test-v1", protocol_version="synthetic-protocol-v1",
        external_thread_id=f"thread-{case.run.conversation_id}", occurred_at=_clock(case.conn),
        step_attempt_id=step.id if step is not None else None,
    )


def _copy_binding(case: CompletionPG, binding: TutorRuntimeBinding, *, step_id: str | None) -> None:
    case.conn.execute(
        """INSERT INTO tutor_run_runtime_bindings
        (run_id,user_id,conversation_id,conversation_runtime_thread_id,step_attempt_id,
         runtime_kind,runtime_version,protocol_version,external_thread_id,connection_generation,state,terminal_at)
        SELECT run_id,user_id,conversation_id,conversation_runtime_thread_id,%s,
         runtime_kind,runtime_version,protocol_version,external_thread_id,connection_generation,'completed',clock_timestamp()
        FROM tutor_run_runtime_bindings WHERE id=%s""", (step_id, binding.binding_id),
    )


@pytest.mark.parametrize("completion_pg", ["sidecar"], indirect=True)
def test_sidecar_two_internal_bindings_one_active_and_no_legacy_mix(completion_pg: CompletionPG) -> None:
    case = completion_pg
    owner, batch, first = _prepare(case)
    binding = _bind(case, first)
    first = owner.mark_dispatched(run=case.run, lease=case.lease, step=first)
    first = owner.record_result(run=case.run, lease=case.lease, step=first, result=_result(case.run))
    owner.accept_result(
        run=case.run, lease=case.lease, step=first, batch=batch, dependencies=first.dependencies,
        validate=lambda: None, consume=lambda: case.conn.execute("SELECT 1").fetchone(),
    )
    current = case.repository.load_snapshot(user_id=case.run.user_id, run_id=case.run.run_id)
    assert current is not None
    case = replace(case, run=current)
    _, _, second = _prepare(case, key="step-2")
    with pytest.raises(psycopg.errors.UniqueViolation) as active:
        _bind(case, second)
    assert active.value.diag.constraint_name == "uq_tutor_runtime_binding_active_run"
    with pytest.raises(psycopg.errors.UniqueViolation) as duplicate:
        _copy_binding(case, binding, step_id=first.id)
    assert duplicate.value.diag.constraint_name == "uq_tutor_runtime_binding_step"
    with pytest.raises(psycopg.errors.CheckViolation, match="frozen completion profile"):
        _copy_binding(case, binding, step_id=None)
    # Terminalize this internal binding only, not the business run.
    case.conn.execute(
        "UPDATE tutor_run_runtime_bindings SET state='completed',terminal_at=clock_timestamp() WHERE id=%s",
        (binding.binding_id,),
    )
    second_binding = _bind(case, second)
    assert second_binding.binding_id != binding.binding_id and second_binding.step_attempt_id == second.id
    rows = case.conn.execute(
        "SELECT step_attempt_id,state FROM tutor_run_runtime_bindings WHERE run_id=%s ORDER BY created_at",
        (case.run.run_id,),
    ).fetchall()
    assert [(str(row["step_attempt_id"]), row["state"]) for row in rows] == [
        (first.id, "completed"), (second.id, "thread_bound"),
    ]
    with pytest.raises(psycopg.errors.CheckViolation, match="identity is immutable"):
        case.conn.execute(
            "UPDATE tutor_run_runtime_bindings SET step_attempt_id=%s WHERE id=%s",
            (first.id, second_binding.binding_id),
        )
    row = case.conn.execute("SELECT terminal_outcome FROM tutor_runs WHERE id=%s", (case.run.run_id,)).fetchone()
    assert row == {"terminal_outcome": None}


@pytest.mark.parametrize("completion_pg", ["legacy"], indirect=True)
def test_legacy_binding_stays_once_and_cannot_opt_into_completion(completion_pg: CompletionPG) -> None:
    case = completion_pg
    binding = _bind(case, None)
    case.conn.execute(
        "UPDATE tutor_run_runtime_bindings SET state='completed',terminal_at=clock_timestamp() WHERE id=%s",
        (binding.binding_id,),
    )
    with pytest.raises(psycopg.errors.UniqueViolation) as duplicate:
        _copy_binding(case, binding, step_id=None)
    assert duplicate.value.diag.constraint_name == "uq_tutor_runtime_binding_legacy_run"
    with pytest.raises(psycopg.errors.CheckViolation, match="frozen completion profile"):
        _copy_binding(case, binding, step_id=str(uuid4()))
    with pytest.raises(CompletionExecutionError, match="completion_profile_required"):
        CompletionExecutionOwner(case.conn).ensure_batch(run=case.run, lease=case.lease)
    with pytest.raises(psycopg.errors.CheckViolation, match="completion run policy and scope are immutable"):
        case.conn.execute(
            "UPDATE tutor_runs SET policy_json=jsonb_set(policy_json,'{execution_profile}',"
            "'\"completion_driven_v1\"'::jsonb) WHERE id=%s", (case.run.run_id,),
        )
