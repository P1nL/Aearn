import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.plans as plans_route
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.models.onboarding import PlanDraft


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


def test_user_create_get_and_preferences(client: TestClient) -> None:
    created = _create_user(client)

    fetched = client.get(f"/api/users/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["user"]["id"] == created["id"]

    patched = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"teaching_preference": "example_then_practice", "profession": "frontend_developer"},
    )
    assert patched.status_code == 200
    assert patched.json()["user"]["teaching_preference"] == "example_then_practice"


def test_preference_update_rejects_fixed_backend_rules(client: TestClient) -> None:
    created = _create_user(client)

    response = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"fsrs_parameters": {"retention": 0.95}, "attempt_policy": "off"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert sorted(response.json()["error"]["details"]["forbidden_fields"]) == [
        "attempt_policy",
        "fsrs_parameters",
    ]


def test_language_courses_include_compiled_later_placeholders(client: TestClient) -> None:
    response = client.get("/api/language-courses")

    assert response.status_code == 200
    items = response.json()["items"]
    runtime_tiers = {item["language"]: item["runtime_profile"]["runtime_tier"] for item in items}
    assert runtime_tiers["java"] == "compiled_sandbox_later"
    assert runtime_tiers["cpp"] == "compiled_sandbox_later"


def test_generate_plan_goal_and_material_modes(client: TestClient) -> None:
    user = _create_user(client)
    js_course = _course_by_language(client, "javascript")
    goal_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Learn DOM events by validating generated code.",
            "course_id": js_course["id"],
            "target_level": "beginner_to_intermediate",
        },
    )
    assert goal_response.status_code == 200
    goal_draft = goal_response.json()["plan_draft"]
    assert goal_draft["runtime_boundary"]["runtime_tier"] == "browser_preview"
    assert goal_draft["modules"][0]["is_skippable"] is False

    python_course = _course_by_language(client, "python")
    material_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "material_based",
            "materials": [{"type": "text", "title": "函数笔记", "content": "return 和 print"}],
            "course_id": python_course["id"],
        },
    )
    assert material_response.status_code == 200
    assert "User materials" in material_response.json()["plan_draft"]["source_attribution"][1]


def test_generate_plan_uses_valid_sdk_candidate(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")

    def fake_sdk_response(context, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        candidate = PlanDraft.model_validate(context.deterministic_plan_draft).model_copy(
            update={"goal_text": "SDK refined DOM validation goal."}
        )
        return {"plan_draft": candidate, "agent_notes": ["SDK note: keep deterministic DOM templates."]}

    monkeypatch.setattr(plans_route, "build_sdk_onboarding_plan_response", fake_sdk_response)

    response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Learn DOM.",
            "course_id": course["id"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan_draft"]["goal_text"] == "SDK refined DOM validation goal."
    assert "SDK note: keep deterministic DOM templates." in body["agent_notes"]
    assert body["plan_draft"]["runtime_boundary"]["runtime_tier"] == "browser_preview"


def test_generate_plan_failure_paths_and_java_notice(client: TestClient) -> None:
    user = _create_user(client)
    java_course = _course_by_language(client, "java")

    insufficient = client.post(
        "/api/plans/generate",
        json={"user_id": user["id"], "mode": "goal_based", "course_id": java_course["id"]},
    )
    assert insufficient.status_code == 400
    assert insufficient.json()["error"]["code"] == "VALIDATION_ERROR"

    unknown_user = client.post(
        "/api/plans/generate",
        json={"user_id": str(uuid.uuid4()), "mode": "goal_based", "goal_text": "Learn", "course_id": java_course["id"]},
    )
    assert unknown_user.status_code == 404
    assert unknown_user.json()["error"]["code"] == "USER_NOT_FOUND"

    unknown_course = client.post(
        "/api/plans/generate",
        json={"user_id": user["id"], "mode": "goal_based", "goal_text": "Learn", "course_id": str(uuid.uuid4())},
    )
    assert unknown_course.status_code == 404
    assert unknown_course.json()["error"]["code"] == "COURSE_NOT_FOUND"

    java_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Read Java method signatures.",
            "course_id": java_course["id"],
        },
    )
    assert java_response.status_code == 200
    draft = java_response.json()["plan_draft"]
    assert draft["runtime_boundary"]["runtime_tier"] == "compiled_sandbox_later"
    assert "planned later" in draft["runtime_boundary"]["notice"]


def test_confirm_plan_persists_review_states_and_is_idempotent(client: TestClient) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Build a deterministic DOM learning route.",
            "course_id": course["id"],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["plan_draft"]

    confirm = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert confirm.status_code == 201
    body = confirm.json()
    assert body["LearningPlan"]["current_module_id"] == body["modules"][0]["id"]
    assert len(body["knowledge_points"]) >= 1

    replay = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert replay.status_code == 201
    assert replay.json()["LearningPlan"]["id"] == body["LearningPlan"]["id"]
    assert replay.json()["idempotency_replayed"] is True

    with connect() as conn:
        review_count = conn.execute(
            "SELECT count(*) AS count FROM review_states WHERE plan_id = %s",
            (body["LearningPlan"]["id"],),
        ).fetchone()
    assert review_count is not None
    assert review_count["count"] == len(body["knowledge_points"])


def test_confirm_plan_invalid_draft_and_idempotency_conflict(client: TestClient) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Learn DOM.",
            "course_id": course["id"],
        },
    )
    draft = draft_response.json()["plan_draft"]
    invalid_draft = draft | {"modules": []}

    invalid = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": invalid_draft})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "PLAN_DRAFT_INVALID"

    idempotency_key = f"m2-conflict-key-{uuid.uuid4().hex}"
    first = client.post(
        "/api/plans",
        headers={"Idempotency-Key": idempotency_key},
        json={"user_id": user["id"], "plan_draft": draft},
    )
    assert first.status_code == 201
    changed_draft = draft | {"goal_text": "Changed goal with same idempotency key."}
    conflict = client.post(
        "/api/plans",
        headers={"Idempotency-Key": idempotency_key},
        json={"user_id": user["id"], "plan_draft": changed_draft},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def _create_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"M2 User {uuid.uuid4().hex[:8]}",
            "learning_style": "practice_first",
            "teaching_preference": "step_by_step",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert isinstance(user, dict)
    return user


def _course_by_language(client: TestClient, language: str) -> dict[str, object]:
    response = client.get(f"/api/language-courses?language={language}")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    course = items[0]
    assert isinstance(course, dict)
    return course
