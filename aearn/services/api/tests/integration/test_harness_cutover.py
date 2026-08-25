from __future__ import annotations

import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.tutor.cutover import (
    CUTOVER_SHARED_TUTOR_TABLES,
    CUTOVER_TARGET_TUTOR_TABLES,
    CUTOVER_VERSION,
    CutoverError,
    HarnessCutoverService,
)


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for DB smoke tests.",
)


@pytest.fixture()
def client() -> TestClient:
    bootstrap_database()
    return TestClient(app)


@pytest.fixture()
def rollout_enabled() -> None:
    """The Tutor cutover is the always-on product entry boundary."""


@pytest.fixture()
def public_checkpoint_tables() -> None:
    """Create a disposable public checkpointer shape only when none exists."""

    table_names = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
    with connect() as conn:
        existing = conn.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'p')
              AND c.relname = ANY(%s)
            """,
            (list(table_names),),
        ).fetchall()
        if existing:
            pytest.skip("public checkpoint tables already exist; do not mutate a non-test checkpointer store")
        for table_name in table_names:
            conn.execute(f"CREATE TABLE public.{table_name} (thread_id text)")
        conn.commit()
    try:
        yield
    finally:
        with connect() as conn:
            for table_name in reversed(table_names):
                conn.execute(f"DROP TABLE IF EXISTS public.{table_name}")
            conn.commit()


def _create_user(client: TestClient, *, legacy: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {"display_name": f"Cutover {uuid.uuid4().hex[:10]}"}
    if legacy:
        payload.update(
            {
                "learning_style": "practice_first",
                "teaching_preference": "step_by_step",
                "encouragement_preference": "direct",
                "profession": "developer",
                "background_context": "legacy profile context",
                "preferred_time_slots": [{"weekday": "mon", "start": "20:00", "end": "21:00"}],
                "reminder_preference": {"enabled": True, "channels": ["desktop"]},
            }
        )
    response = client.post("/api/users", json=payload)
    assert response.status_code == 201
    user = response.json()["user"]
    assert isinstance(user, dict)
    return user


def _preview(client: TestClient, user_id: str) -> dict[str, object]:
    response = client.get(f"/api/harness/cutover?user_id={user_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "summary_ready"
    return payload


def _confirmation_body(user_id: str, preview: dict[str, object], *, action: str = "cutover-confirm") -> dict[str, object]:
    return {
        "user_id": user_id,
        "cutover_version": preview["cutover_version"],
        "summary_version": preview["summary_version"],
        "preview_nonce": preview["preview_nonce"],
        "summary_hash": preview["summary_hash"],
        "client_action_id": action,
        "confirm": True,
    }


def _insert_legacy_receipts(user_id: str, *, key_suffix: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO learner_profiles (user_id) VALUES (%s)", (user_id,))
        conn.execute(
            """
            INSERT INTO idempotency_records (key, operation, request_hash, response_json, user_id)
            VALUES (%s, 'cutover.test', %s, %s::jsonb, %s)
            """,
            (f"cutover-test:{key_suffix}:{uuid.uuid4().hex}", "0" * 64, json.dumps({"safe": True}), user_id),
        )
        conn.commit()


def _seed_full_legacy_hierarchy(user_id: str) -> dict[str, object]:
    """Seed every Child 07 legacy deletion category for one disposable user."""

    marker = uuid.uuid4().hex
    with connect() as conn:
        course = conn.execute(
            """
            SELECT id, runtime_profile_id, language
            FROM language_courses
            WHERE archived_at IS NULL
            ORDER BY language, level, id
            LIMIT 1
            """
        ).fetchone()
        assert course is not None
        plan = conn.execute(
            """
            INSERT INTO learning_plans (user_id, language_course_id, goal_text, language, target_level, mode)
            VALUES (%s, %s, %s, %s, 'beginner', 'goal_based')
            RETURNING id
            """,
            (user_id, course["id"], f"Cutover hierarchy {marker}", course["language"]),
        ).fetchone()
        assert plan is not None
        module = conn.execute(
            """
            INSERT INTO plan_modules (plan_id, title, order_index)
            VALUES (%s, %s, 0)
            RETURNING id
            """,
            (plan["id"], f"Cutover module {marker}"),
        ).fetchone()
        assert module is not None
        conn.execute("UPDATE learning_plans SET current_module_id = %s WHERE id = %s", (module["id"], plan["id"]))
        knowledge_point = conn.execute(
            """
            INSERT INTO knowledge_points (module_id, language_course_id, title, order_index)
            VALUES (%s, %s, %s, 0)
            RETURNING id
            """,
            (module["id"], course["id"], f"Cutover knowledge point {marker}"),
        ).fetchone()
        assert knowledge_point is not None
        exercise = conn.execute(
            """
            INSERT INTO exercises (knowledge_point_id, runtime_profile_id, title, exercise_type, prompt_markdown, starter_code)
            VALUES (%s, %s, %s, 'code_blank', 'Fixture prompt', 'const answer = __VALUE__;')
            RETURNING id
            """,
            (knowledge_point["id"], course["runtime_profile_id"], f"Cutover exercise {marker}"),
        ).fetchone()
        assert exercise is not None
        conn.execute(
            """
            INSERT INTO code_blanks (exercise_id, blank_key, placeholder, expected_concept, order_index)
            VALUES (%s, 'value', '__VALUE__', 'literal', 0)
            """,
            (exercise["id"],),
        )
        conn.execute(
            """
            INSERT INTO test_cases (exercise_id, case_type, order_index)
            VALUES (%s, 'visible', 0)
            """,
            (exercise["id"],),
        )
        conn.execute(
            """
            INSERT INTO teaching_chunks (knowledge_point_id, chunk_type, title, content)
            VALUES (%s, 'outline', %s, 'Fixture teaching content')
            """,
            (knowledge_point["id"], f"Cutover chunk {marker}"),
        )
        learning_session = conn.execute(
            """
            INSERT INTO learning_sessions (user_id, plan_id, session_type, entry_point, next_entry_point, learning_stage)
            VALUES (%s, %s, 'learn', %s, %s, 'practice_support')
            RETURNING id
            """,
            (user_id, plan["id"], str(knowledge_point["id"]), str(knowledge_point["id"])),
        ).fetchone()
        assert learning_session is not None
        review_session = conn.execute(
            """
            INSERT INTO learning_sessions (user_id, plan_id, session_type, entry_point, next_entry_point, review_stage)
            VALUES (%s, %s, 'review', %s, %s, 'warmup')
            RETURNING id
            """,
            (user_id, plan["id"], str(knowledge_point["id"]), str(knowledge_point["id"])),
        ).fetchone()
        assert review_session is not None
        conn.execute(
            "UPDATE knowledge_points SET last_session_id = %s WHERE id = %s",
            (learning_session["id"], knowledge_point["id"]),
        )
        attempt = conn.execute(
            """
            INSERT INTO attempts (session_id, exercise_id, user_id, attempt_type, submitted_code, code_hash, runtime_status)
            VALUES (%s, %s, %s, 'run', 'const answer = 1;', %s, 'success')
            RETURNING id
            """,
            (learning_session["id"], exercise["id"], user_id, f"cutover-{marker}"),
        ).fetchone()
        assert attempt is not None
        conn.execute(
            """
            INSERT INTO review_states (knowledge_point_id, user_id, plan_id, last_attempt_id)
            VALUES (%s, %s, %s, %s)
            """,
            (knowledge_point["id"], user_id, plan["id"], attempt["id"]),
        )
        conn.execute(
            """
            INSERT INTO review_logs (
              knowledge_point_id, user_id, plan_id, attempt_id, rating,
              previous_state_json, next_state_json, scheduled_due_at, source, request_id
            )
            VALUES (%s, %s, %s, %s, 'Good', '{}'::jsonb, '{}'::jsonb, now(), 'learn_submit', %s)
            """,
            (knowledge_point["id"], user_id, plan["id"], attempt["id"], f"cutover-log-{marker}"),
        )
        conn.execute(
            """
            INSERT INTO review_seed_banks (user_id, plan_id, knowledge_point_id, generator_version)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, plan["id"], knowledge_point["id"], f"cutover-seed-{marker}"),
        )
        conn.execute(
            """
            INSERT INTO exercise_variant_cache (
              user_id, knowledge_point_id, template_id, template_version,
              generator_version, runner_key, runtime_tier, variant_hash, status
            )
            VALUES (%s, %s, %s, 'v1', 'fixture', 'node', 'node_typescript_test', %s, 'validated')
            """,
            (user_id, knowledge_point["id"], f"cutover-template-{marker}", f"cutover-variant-{marker}"),
        )
        conn.execute(
            """
            INSERT INTO notes (user_id, knowledge_point_id, title, content_markdown)
            VALUES (%s, %s, %s, 'Fixture note')
            """,
            (user_id, knowledge_point["id"], f"Cutover note {marker}"),
        )
        conversation = conn.execute(
            """
            INSERT INTO onboarding_conversations (user_id)
            VALUES (%s)
            RETURNING id
            """,
            (user_id,),
        ).fetchone()
        assert conversation is not None
        conn.execute(
            "INSERT INTO onboarding_messages (conversation_id, role, content) VALUES (%s, 'user', 'Fixture onboarding')",
            (conversation["id"],),
        )
        conn.execute(
            """
            INSERT INTO learning_messages (session_id, knowledge_point_id, role, content)
            VALUES (%s, %s, 'user', 'Fixture learning message')
            """,
            (learning_session["id"], knowledge_point["id"]),
        )
        conn.execute(
            "INSERT INTO review_messages (review_session_id, role, content) VALUES (%s, 'user', 'Fixture review message')",
            (review_session["id"],),
        )
        conn.execute("INSERT INTO learner_profiles (user_id) VALUES (%s)", (user_id,))
        conn.execute(
            """
            INSERT INTO idempotency_records (key, operation, request_hash, response_json, user_id)
            VALUES (%s, 'cutover.fixture', %s, '{}'::jsonb, %s)
            """,
            (f"cutover-fixture:{marker}", "0" * 64, user_id),
        )
        conn.commit()
    return {
        "plan_id": str(plan["id"]),
        "knowledge_point_id": str(knowledge_point["id"]),
        "thread_ids": (
            f"aearn:learning:{learning_session['id']}",
            f"aearn:learning:{review_session['id']}",
        ),
    }


def test_confirm_is_explicit_exact_and_preserves_retained_settings(
    client: TestClient,
    rollout_enabled: None,
) -> None:
    del rollout_enabled
    owner = _create_user(client, legacy=True)
    other = _create_user(client, legacy=True)
    _insert_legacy_receipts(str(owner["id"]), key_suffix="owner")
    _insert_legacy_receipts(str(other["id"]), key_suffix="other")

    preview = _preview(client, str(owner["id"]))
    assert {item["id"] for item in preview["summary"]["legacy_profile_fields"]} == {
        "learning_style",
        "teaching_preference",
        "encouragement_preference",
        "profession",
        "background_context",
    }

    no_confirm = client.post(
        "/api/harness/cutover/confirm",
        json={**_confirmation_body(str(owner["id"]), preview), "confirm": False},
    )
    assert no_confirm.status_code == 400
    assert no_confirm.json()["error"]["code"] == "CUTOVER_CONFIRMATION_REQUIRED"

    completed = client.post("/api/harness/cutover/confirm", json=_confirmation_body(str(owner["id"]), preview))
    assert completed.status_code == 200
    assert completed.json()["state"] == "verified"

    replay = client.post("/api/harness/cutover/confirm", json=_confirmation_body(str(owner["id"]), preview))
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True

    conflict = client.post(
        "/api/harness/cutover/confirm",
        json={**_confirmation_body(str(owner["id"]), preview), "summary_hash": "1" * 64},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CUTOVER_CONFIRMATION_CONFLICT"

    with connect() as conn:
        owner_row = conn.execute(
            """
            SELECT display_name, learning_style, teaching_preference, encouragement_preference,
                   profession, background_context, preferred_time_slots, reminder_preference
            FROM users WHERE id = %s
            """,
            (owner["id"],),
        ).fetchone()
        assert owner_row is not None
        assert owner_row["display_name"] == owner["display_name"]
        assert owner_row["preferred_time_slots"] == owner["preferred_time_slots"]
        assert owner_row["reminder_preference"] == owner["reminder_preference"]
        assert all(owner_row[field] is None for field in (
            "learning_style", "teaching_preference", "encouragement_preference", "profession", "background_context"
        ))
        assert conn.execute("SELECT count(*)::int AS count FROM learner_profiles WHERE user_id = %s", (owner["id"],)).fetchone()["count"] == 0
        assert conn.execute("SELECT count(*)::int AS count FROM idempotency_records WHERE user_id = %s", (owner["id"],)).fetchone()["count"] == 0
        assert conn.execute("SELECT count(*)::int AS count FROM learner_profiles WHERE user_id = %s", (other["id"],)).fetchone()["count"] == 1
        assert conn.execute("SELECT count(*)::int AS count FROM idempotency_records WHERE user_id = %s", (other["id"],)).fetchone()["count"] == 1


def test_stale_and_cross_user_confirmation_do_not_delete(client: TestClient, rollout_enabled: None) -> None:
    del rollout_enabled
    owner = _create_user(client, legacy=True)
    other = _create_user(client, legacy=True)
    owner_preview = _preview(client, str(owner["id"]))
    _insert_legacy_receipts(str(owner["id"]), key_suffix="stale")

    stale = client.post("/api/harness/cutover/confirm", json=_confirmation_body(str(owner["id"]), owner_preview))
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CUTOVER_SUMMARY_STALE"

    cross_user = client.post(
        "/api/harness/cutover/confirm",
        json=_confirmation_body(str(other["id"]), owner_preview, action="cross-user"),
    )
    assert cross_user.status_code == 409
    assert cross_user.json()["error"]["code"] == "CUTOVER_SUMMARY_STALE"

    with connect() as conn:
        owner_row = conn.execute("SELECT learning_style FROM users WHERE id = %s", (owner["id"],)).fetchone()
        other_row = conn.execute("SELECT learning_style FROM users WHERE id = %s", (other["id"],)).fetchone()
        assert owner_row is not None and owner_row["learning_style"] == "practice_first"
        assert other_row is not None and other_row["learning_style"] == "practice_first"
        assert conn.execute("SELECT count(*)::int AS count FROM idempotency_records WHERE user_id = %s", (owner["id"],)).fetchone()["count"] == 1


def test_cutover_inventory_explicitly_classifies_every_tutor_table() -> None:
    bootstrap_database()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND left(table_name, 6) = 'tutor_'
            ORDER BY table_name
            """
        ).fetchall()
    schema_tables = {str(row["table_name"]) for row in rows}

    assert CUTOVER_TARGET_TUTOR_TABLES.isdisjoint(CUTOVER_SHARED_TUTOR_TABLES)
    assert schema_tables == CUTOVER_TARGET_TUTOR_TABLES | CUTOVER_SHARED_TUTOR_TABLES


def test_target_state_and_runtime_paths_fail_closed_without_deletion(
    client: TestClient,
    rollout_enabled: None,
) -> None:
    del rollout_enabled
    user = _create_user(client, legacy=True)
    with connect() as conn:
        conn.execute("INSERT INTO tutor_conversations (user_id) VALUES (%s)", (user["id"],))
        conn.commit()

    status_response = client.get(f"/api/harness/cutover?user_id={user['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "blocked_target_state"
    assert status_response.json()["code"] == "CUTOVER_TARGET_STATE_PRESENT"

    tutor_response = client.post(
        "/api/tutor/conversations",
        json={"user_id": user["id"], "client_action_id": "blocked-target"},
    )
    assert tutor_response.status_code == 409
    assert tutor_response.json()["error"]["code"] == "CUTOVER_TARGET_STATE_PRESENT"

    dashboard_response = client.get(f"/api/dashboard?user_id={user['id']}")
    assert dashboard_response.status_code == 404

    with connect() as conn:
        assert conn.execute("SELECT learning_style FROM users WHERE id = %s", (user["id"],)).fetchone()["learning_style"] == "practice_first"
        assert conn.execute("SELECT count(*)::int AS count FROM tutor_conversations WHERE user_id = %s", (user["id"],)).fetchone()["count"] == 1


def test_cutover_deletes_full_legacy_hierarchy_and_only_owned_checkpoints(
    client: TestClient,
    rollout_enabled: None,
    public_checkpoint_tables: None,
) -> None:
    del rollout_enabled, public_checkpoint_tables
    owner = _create_user(client, legacy=True)
    other = _create_user(client, legacy=True)
    owner_scope = _seed_full_legacy_hierarchy(str(owner["id"]))
    other_scope = _seed_full_legacy_hierarchy(str(other["id"]))

    with connect() as conn:
        for table_name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            for thread_id in (*owner_scope["thread_ids"], *other_scope["thread_ids"]):
                conn.execute(f"INSERT INTO public.{table_name} (thread_id) VALUES (%s)", (thread_id,))
        conn.commit()

    preview = _preview(client, str(owner["id"]))
    preview_categories = {item["id"] for item in preview["summary"]["legacy_categories"]}
    assert {
        "learning_plans",
        "plan_modules",
        "knowledge_points",
        "exercises",
        "code_blanks",
        "test_cases",
        "teaching_chunks",
        "learning_sessions",
        "attempts",
        "review_states",
        "review_logs",
        "review_seed_banks",
        "exercise_variant_cache",
        "notes",
        "onboarding_conversations",
        "onboarding_messages",
        "learning_messages",
        "review_messages",
        "learner_profiles",
        "idempotency_records",
    }.issubset(preview_categories)
    assert preview["summary"]["checkpoint"]["record_count"] == 3 * len(owner_scope["thread_ids"])

    completed = client.post(
        "/api/harness/cutover/confirm",
        json=_confirmation_body(str(owner["id"]), preview, action="full-hierarchy"),
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == "verified"

    with connect() as conn:
        owner_inventory = HarnessCutoverService(conn)._inventory(str(owner["id"]))
        other_inventory = HarnessCutoverService(conn)._inventory(str(other["id"]))
        assert not owner_inventory.has_legacy_data
        assert all(count == 0 for count in owner_inventory.legacy_counts.values())
        assert all(not present for present in owner_inventory.legacy_profile_fields.values())
        assert owner_inventory.checkpoints.state == "scoped"
        assert all(count == 0 for count in owner_inventory.checkpoints.table_counts.values())
        assert other_inventory.has_legacy_data
        for table_name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            owner_remaining = conn.execute(
                f"SELECT count(*)::int AS count FROM public.{table_name} WHERE thread_id = ANY(%s)",
                (list(owner_scope["thread_ids"]),),
            ).fetchone()
            other_remaining = conn.execute(
                f"SELECT count(*)::int AS count FROM public.{table_name} WHERE thread_id = ANY(%s)",
                (list(other_scope["thread_ids"]),),
            ).fetchone()
            assert owner_remaining is not None and owner_remaining["count"] == 0
            assert other_remaining is not None and other_remaining["count"] == len(other_scope["thread_ids"])


@pytest.mark.parametrize("unresolved_thread_id", ["aearn:learning:00000000-0000-0000-0000-000000000000", None])
def test_cutover_blocks_unresolved_checkpoint_scope_without_deletion(
    client: TestClient,
    rollout_enabled: None,
    public_checkpoint_tables: None,
    unresolved_thread_id: str | None,
) -> None:
    del rollout_enabled, public_checkpoint_tables
    user = _create_user(client, legacy=True)
    _seed_full_legacy_hierarchy(str(user["id"]))
    with connect() as conn:
        conn.execute("INSERT INTO public.checkpoints (thread_id) VALUES (%s)", (unresolved_thread_id,))
        conn.commit()

    status_response = client.get(f"/api/harness/cutover?user_id={user['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "blocked_checkpoint_scope"
    assert status_response.json()["code"] == "CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED"

    with connect() as conn:
        inventory = HarnessCutoverService(conn)._inventory(str(user["id"]))
        assert inventory.has_legacy_data
        assert inventory.checkpoints.state == "unresolved"
        user_row = conn.execute("SELECT learning_style FROM users WHERE id = %s", (user["id"],)).fetchone()
        assert user_row is not None and user_row["learning_style"] == "practice_first"


def test_cutover_blocks_ordinary_reset_and_legacy_routes_are_absent(
    client: TestClient,
    rollout_enabled: None,
) -> None:
    del rollout_enabled
    user = _create_user(client, legacy=True)

    reset = client.post(f"/api/users/{user['id']}/reset-data", json={"confirm": True})
    assert reset.status_code == 409
    assert reset.json()["error"]["code"] == "CUTOVER_REQUIRED"

    malformed_dashboard = client.get("/api/dashboard?user_id=not-a-uuid")
    assert malformed_dashboard.status_code == 404

    unscoped_onboarding = client.get("/api/onboarding/sessions/not-a-session/messages")
    assert unscoped_onboarding.status_code == 404

    with connect() as conn:
        row = conn.execute(
            "SELECT learning_style FROM users WHERE id = %s",
            (user["id"],),
        ).fetchone()
        assert row is not None
        assert row["learning_style"] == "practice_first"


def test_verified_user_can_only_enter_tutor_not_legacy_runtime(
    client: TestClient,
    rollout_enabled: None,
) -> None:
    del rollout_enabled
    user = _create_user(client, legacy=False)

    decision = client.get(f"/api/harness/cutover?user_id={user['id']}")
    assert decision.status_code == 200
    assert decision.json()["state"] == "verified"

    legacy_dashboard = client.get(f"/api/dashboard?user_id={user['id']}")
    assert legacy_dashboard.status_code == 404


def test_verification_failure_rolls_back_and_persists_safe_receipt(client: TestClient) -> None:
    user = _create_user(client, legacy=True)
    with connect() as conn:
        service = HarnessCutoverService(conn)
        preview = service.get_decision(user_id=str(user["id"]))

        def fail_before_verification(stage: str) -> None:
            if stage == "before_verification":
                raise RuntimeError("injected verification failure")

        failing = HarnessCutoverService(conn, failure_injector=fail_before_verification)
        with pytest.raises(CutoverError) as raised:
            failing.confirm(
                **_confirmation_body(str(user["id"]), preview),
            )
        assert raised.value.code == "CUTOVER_VERIFICATION_FAILED"
        row = conn.execute("SELECT learning_style FROM users WHERE id = %s", (user["id"],)).fetchone()
        receipt = conn.execute(
            "SELECT state, failure_code FROM harness_cutovers WHERE user_id = %s AND cutover_version = %s",
            (user["id"], CUTOVER_VERSION),
        ).fetchone()
        assert row is not None and row["learning_style"] == "practice_first"
        assert receipt is not None
        assert receipt["state"] == "verification_failed"
        assert receipt["failure_code"] == "CUTOVER_VERIFICATION_FAILED"
        conn.commit()
