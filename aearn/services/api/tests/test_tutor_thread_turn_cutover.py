from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.harness.contracts import TutorPolicySnapshot
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.tutor.cutover import CUTOVER_VERSION, CutoverError
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.thread_turn_cutover import (
    THREAD_TURN_CUTOVER_VERSION,
    TutorThreadTurnCutoverService,
)


@pytest.fixture(autouse=True)
def reset_global_cutover() -> None:
    bootstrap_database()
    _reset_cutover(state="idle", generation=0)
    yield
    _reset_cutover(state="enabled", generation=1)


def _reset_cutover(*, state: str, generation: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE tutor_runs
            SET status = 'cancelled', cancelled_at = COALESCE(cancelled_at, now()),
                terminal_outcome = 'cancelled',
                terminal_diagnostic_code = COALESCE(terminal_diagnostic_code, 'test_fixture_cleanup'),
                terminal_at = COALESCE(terminal_at, now()),
                active_lease_owner_id = NULL, active_lease_expires_at = NULL
            WHERE interaction_protocol_version = 'legacy_v1' AND terminal_outcome IS NULL
            """
        )
        conn.execute(
            """
            UPDATE tutor_interactive_dispatch_jobs
            SET state = 'dead', lease_owner_id = NULL, lease_expires_at = NULL,
                last_error_code = COALESCE(last_error_code, 'test_fixture_cleanup'),
                dead_at = COALESCE(dead_at, now()), completed_at = NULL
            WHERE state IN ('pending','leased','retry_wait')
              AND run_id IN (SELECT id FROM tutor_runs WHERE interaction_protocol_version = 'legacy_v1')
            """
        )
        conn.execute("TRUNCATE tutor_thread_turn_cutover_events, tutor_thread_turn_cutovers CASCADE")
        conn.execute(
            """
            INSERT INTO tutor_thread_turn_cutovers (
              cutover_version, state, generation, summary_hash, counts_json, ready_at, enabled_at
            ) VALUES (%s, %s, %s, %s, '{}'::jsonb,
                      CASE WHEN %s IN ('ready','enabled') THEN now() ELSE NULL END,
                      CASE WHEN %s = 'enabled' THEN now() ELSE NULL END)
            """,
            (
                THREAD_TURN_CUTOVER_VERSION,
                state,
                generation,
                "0" * 64 if state in {"ready", "enabled"} else None,
                state,
                state,
            ),
        )
        conn.commit()


def _legacy_run(conn, *, status: str = "queued") -> tuple[str, str]:  # type: ignore[no-untyped-def]
    user = conn.execute("INSERT INTO users (display_name) VALUES (%s) RETURNING id", (f"Cutover {uuid4().hex[:8]}",)).fetchone()
    assert user is not None
    user_id = str(user["id"])
    conn.execute(
        "INSERT INTO harness_cutovers (user_id, cutover_version, state, verified_at) VALUES (%s, %s, 'verified', now())",
        (user_id, CUTOVER_VERSION),
    )
    repository = PostgresTutorRepository(conn)
    catalog = compile_published_skill_catalog()
    repository.record_catalog_snapshot(catalog)
    conversation_id = repository.create_conversation(user_id=user_id)
    run = repository.create_run(
        user_id=user_id,
        conversation_id=conversation_id,
        catalog_digest=catalog.digest,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
        origin="interactive",
    )
    repository.accept_input(user_id=user_id, run_id=run.run_id, idempotency_key=f"input-{uuid4().hex}", content="legacy input")
    conn.execute(
        "UPDATE tutor_runs SET status = %s, continuation_kind = CASE WHEN %s = 'waiting_for_input' THEN 'clarification' ELSE NULL END WHERE id = %s",
        (status, status, run.run_id),
    )
    return user_id, run.run_id


def test_prepare_terminalizes_safe_legacy_and_enable_rollback_never_reopens() -> None:
    settings = Settings(tutor_thread_turn_v2_enabled=True)
    with connect() as conn:
        _user_a, active_id = _legacy_run(conn, status="running")
        _user_b, waiting_id = _legacy_run(conn, status="waiting_for_input")
        conn.execute(
            "UPDATE tutor_runs SET active_lease_owner_id = 'legacy-owner', active_lease_generation = 1, active_lease_expires_at = now() + interval '1 minute' WHERE id = %s",
            (active_id,),
        )
        conn.commit()
        service = TutorThreadTurnCutoverService(conn)
        prepared = service.prepare(expected_generation=0, idempotency_key="prepare-safe")
        assert prepared["state"] == "ready"
        assert prepared["generation"] == 1
        assert prepared["counts"]["migrated_active_cancelled"] == 1
        assert prepared["counts"]["migrated_waiting_failed"] == 1
        rows = conn.execute(
            "SELECT id::text, terminal_outcome, terminal_diagnostic_code, active_lease_owner_id FROM tutor_runs WHERE id IN (%s, %s) ORDER BY id",
            (active_id, waiting_id),
        ).fetchall()
        by_id = {str(row["id"]): row for row in rows}
        assert by_id[active_id]["terminal_outcome"] == "cancelled"
        assert by_id[active_id]["terminal_diagnostic_code"] == "legacy_protocol_cutover"
        assert by_id[active_id]["active_lease_owner_id"] is None
        assert by_id[waiting_id]["terminal_outcome"] == "failed"
        assert by_id[waiting_id]["terminal_diagnostic_code"] == "legacy_continuation_requires_new_turn"
        summary_hash = str(prepared["summary_hash"])
        enabled = service.enable(expected_generation=1, summary_hash=summary_hash, idempotency_key="enable-safe")
        assert enabled["state"] == "enabled"
        assert service.status(settings=settings)["effective_enabled"] is True
        service.assert_mutation_allowed(settings=settings)
        rolled_back = service.rollback(expected_generation=1, idempotency_key="rollback-safe")
        assert rolled_back["state"] == "ready"
        with pytest.raises(CutoverError) as blocked:
            service.assert_mutation_allowed(settings=settings)
        assert blocked.value.code == "TUTOR_THREAD_TURN_V2_UNAVAILABLE"
        assert conn.execute("SELECT count(*) AS count FROM tutor_runs WHERE id IN (%s,%s) AND terminal_outcome IS NULL", (active_id, waiting_id)).fetchone() == {"count": 0}


def test_ambiguous_effect_blocks_without_guessing() -> None:
    with connect() as conn:
        _user_id, run_id = _legacy_run(conn, status="awaiting_effect_commit")
        conn.execute(
            """
            INSERT INTO tutor_effects (
              run_id, effect_id, idempotency_key, effect_type, expected_input_revision,
              payload_hash, lease_owner_id, lease_generation, status,
              safe_outcome_json, safe_outcome_hash
            ) VALUES (%s, 'effect-1', 'effect-key-1', 'fixture.effect', 1,
                      %s, 'legacy-owner', 1, 'proposed', '{}'::jsonb, %s)
            """,
            (run_id, "1" * 64, "2" * 64),
        )
        conn.commit()
        result = TutorThreadTurnCutoverService(conn).prepare(expected_generation=0, idempotency_key="prepare-blocked")
        assert result["state"] == "blocked"
        assert result["block_code"] == "TUTOR_CUTOVER_AMBIGUOUS_EFFECT"
        assert result["counts"]["ambiguous_effects"] == 1
        assert conn.execute("SELECT terminal_outcome FROM tutor_runs WHERE id = %s", (run_id,)).fetchone() == {"terminal_outcome": None}


def test_concurrent_prepare_advances_one_generation_and_replay_is_idempotent() -> None:
    barrier = Barrier(2)

    def invoke(key: str) -> tuple[str, int]:
        with connect() as conn:
            barrier.wait()
            try:
                result = TutorThreadTurnCutoverService(conn).prepare(expected_generation=0, idempotency_key=key)
                return str(result["state"]), int(result["generation"])
            except CutoverError as exc:
                return exc.code, -1

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, ("prepare-a", "prepare-b")))
    assert sum(1 for state, generation in results if state == "ready" and generation == 1) == 1
    assert sum(1 for state, _generation in results if state == "TUTOR_CUTOVER_GENERATION_CONFLICT") == 1
    with connect() as conn:
        record = conn.execute("SELECT generation FROM tutor_thread_turn_cutovers WHERE cutover_version = %s", (THREAD_TURN_CUTOVER_VERSION,)).fetchone()
        assert record == {"generation": 1}


def test_legacy_continuation_route_is_side_effect_free_410() -> None:
    client = TestClient(app)
    with connect() as conn:
        before = conn.execute("SELECT count(*) AS count FROM tutor_api_idempotency_records").fetchone()
    response = client.post(
        f"/api/tutor/runs/{uuid4()}/inputs",
        json={"user_id": str(uuid4()), "client_action_id": "legacy-tombstone", "content": "continue"},
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "TUTOR_LEGACY_CONTINUATION_DISABLED"
    with connect() as conn:
        after = conn.execute("SELECT count(*) AS count FROM tutor_api_idempotency_records").fetchone()
    assert after == before

