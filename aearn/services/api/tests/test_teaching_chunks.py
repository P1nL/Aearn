"""Tests for teaching chunks indexing and retrieval."""
from __future__ import annotations

import uuid

import pytest

from app.agents.tooling.tools import LearningToolContext, do_search_teaching_materials
from app.db.bootstrap import bootstrap_database
from app.models.onboarding import (
    DraftKnowledgePoint,
    DraftModule,
    PlanDraft,
    RuntimeBoundary,
    UserCreateRequest,
)
from app.services.exercises.exercise_repository import get_or_create_exercise_for_knowledge_point
from app.services.repositories.plan_repository import confirm_plan, request_hash
from app.services.curriculum.teaching_chunks import (
    index_current_knowledge_point_chunks,
    index_knowledge_point_chunks,
    search_chunks,
)
from app.services.repositories.user_repository import create_user


@pytest.fixture()
def conn():
    from app.core.config import get_settings
    import psycopg
    from psycopg.rows import dict_row

    bootstrap_database()
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        connection.execute("DELETE FROM teaching_chunks")
        connection.commit()
        yield connection
        connection.rollback()


@pytest.fixture()
def knowledge_point_id(conn):
    row = conn.execute(
        "SELECT id FROM knowledge_points LIMIT 1",
    ).fetchone()
    if row is None:
        pytest.skip("No knowledge points in database")
    return str(row["id"])


class TestIndexing:
    def test_index_from_lesson_outline(self, conn, knowledge_point_id):
        kp = {
            "title": "Python Functions",
            "description": "Learn how to define and call functions in Python.",
            "lesson_outline_json": [
                {"title": "Defining Functions", "summary": "Use def keyword to define functions", "subpoints": ["Parameters", "Return values"]},
                {"title": "Calling Functions", "summary": "Call functions with arguments"},
            ],
            "lesson_sources_json": [],
        }
        count = index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()
        assert count >= 3  # 2 outline + 1 explanation

    def test_index_with_exercises(self, conn, knowledge_point_id):
        kp = {
            "title": "Loops",
            "description": "For and while loops.",
            "lesson_outline_json": [],
            "lesson_sources_json": [],
        }
        exercises = [
            {"title": "Sum a list", "prompt_markdown": "Write a function to sum a list", "solution_reference": "def sum_list(lst):\n    return sum(lst)"},
        ]
        count = index_knowledge_point_chunks(conn, knowledge_point_id, kp, exercises)
        conn.commit()
        assert count >= 2  # 1 example + 1 explanation

    def test_index_idempotent(self, conn, knowledge_point_id):
        kp = {
            "title": "Test",
            "description": "Old marker",
            "lesson_outline_json": [{"title": "S1", "summary": "old indexed content"}],
            "lesson_sources_json": [],
        }
        count1 = index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()
        kp["description"] = "New marker"
        kp["lesson_outline_json"] = [{"title": "S1", "summary": "new indexed content"}]
        count2 = index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()
        rows = conn.execute(
            "SELECT content FROM teaching_chunks WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchall()
        assert count1 > 0
        assert count2 > 0
        assert len(rows) == count2
        assert any("New marker" in row["content"] or "new indexed content" in row["content"] for row in rows)
        assert all("Old marker" not in row["content"] and "old indexed content" not in row["content"] for row in rows)

    def test_index_with_source_urls(self, conn, knowledge_point_id):
        kp = {
            "title": "Closures",
            "description": "Understanding closures.",
            "lesson_outline_json": [],
            "lesson_sources_json": [
                {"url": "https://docs.python.org/3/faq/programming.html", "title": "Python FAQ"},
            ],
        }
        count = index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()
        assert count >= 2  # 1 source_note + 1 explanation


class TestSearch:
    def test_search_finds_relevant_chunk(self, conn, knowledge_point_id):
        kp = {
            "title": "Recursion",
            "description": "A function that calls itself to solve smaller subproblems.",
            "lesson_outline_json": [
                {"title": "Base Case", "summary": "Every recursive function needs a base case to stop recursion"},
                {"title": "Recursive Step", "summary": "The function calls itself with a smaller input"},
            ],
            "lesson_sources_json": [],
        }
        index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()

        results = search_chunks(conn, knowledge_point_id, "base case stop")
        assert len(results) > 0
        assert any("Base Case" in r["title"] for r in results)

    def test_search_returns_empty_gracefully(self, conn, knowledge_point_id):
        results = search_chunks(conn, knowledge_point_id, "nonexistent topic xyz")
        # Falls back to recent chunks or empty
        assert isinstance(results, list)

    def test_search_respects_top_k(self, conn, knowledge_point_id):
        kp = {
            "title": "Variables",
            "description": "Variable assignment and types.",
            "lesson_outline_json": [
                {"title": f"Section {i}", "summary": f"Content about variables part {i}"}
                for i in range(10)
            ],
            "lesson_sources_json": [],
        }
        index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()

        results = search_chunks(conn, knowledge_point_id, "variables", top_k=2)
        assert len(results) <= 2

    def test_search_is_scoped_to_current_knowledge_point(self, conn):
        plan = _confirmed_plan(conn)
        first = plan["knowledge_points"][0]
        second = plan["knowledge_points"][1]

        first_results = search_chunks(conn, str(first["id"]), "alpha marker")
        second_results = search_chunks(conn, str(second["id"]), "alpha marker")

        assert first_results
        assert any("Alpha Marker" in item["content"] or "Alpha Marker" in item["title"] for item in first_results)
        assert all("Alpha Marker" not in item["content"] and "Alpha Marker" not in item["title"] for item in second_results)

    def test_confirm_plan_indexes_teaching_chunks(self, conn):
        plan = _confirmed_plan(conn)
        knowledge_point_id = str(plan["knowledge_points"][0]["id"])

        results = search_chunks(conn, knowledge_point_id, "alpha marker")

        assert results
        assert any("Alpha Marker" in item["content"] or "Alpha Marker" in item["title"] for item in results)

    def test_exercise_creation_reindexes_teaching_chunks(self, conn):
        plan = _confirmed_plan(conn, language="python")
        knowledge_point_id = str(plan["knowledge_points"][0]["id"])
        knowledge_point = conn.execute(
            "SELECT * FROM knowledge_points WHERE id = %s",
            (knowledge_point_id,),
        ).fetchone()
        runtime_profile = conn.execute(
            "SELECT * FROM runtime_profiles WHERE language = 'python' LIMIT 1",
        ).fetchone()
        assert knowledge_point is not None
        assert runtime_profile is not None
        before_count = _chunk_count(conn, knowledge_point_id)

        exercise = get_or_create_exercise_for_knowledge_point(
            conn,
            knowledge_point=knowledge_point,
            runtime_profile=runtime_profile,
        )
        conn.commit()
        results = search_chunks(conn, knowledge_point_id, "Python print")

        assert _chunk_count(conn, knowledge_point_id) > before_count
        assert any(item["chunk_type"] == "example" for item in results)
        assert all(str(exercise["solution_reference"]) not in item["content"] for item in results)

    def test_index_current_knowledge_point_chunks_rebuilds_without_duplicates(self, conn):
        plan = _confirmed_plan(conn, language="python")
        knowledge_point_id = str(plan["knowledge_points"][0]["id"])

        count1 = index_current_knowledge_point_chunks(conn, knowledge_point_id)
        conn.commit()
        count2 = index_current_knowledge_point_chunks(conn, knowledge_point_id)
        conn.commit()

        assert count1 == count2
        assert _chunk_count(conn, knowledge_point_id) == count2


class TestSearchTool:
    def test_do_search_without_kp_id(self):
        ctx = LearningToolContext(session_id="s1", exercise_id=None, current_stage="concept_intro", knowledge_point_id=None)
        result = do_search_teaching_materials(ctx, "test query")
        assert result["success"] is False

    def test_do_search_with_invalid_kp_id(self):
        ctx = LearningToolContext(
            session_id="s1", exercise_id=None, current_stage="concept_intro",
            knowledge_point_id="00000000-0000-0000-0000-000000000000",
        )
        result = do_search_teaching_materials(ctx, "test query")
        assert result["success"] is True
        assert result["count"] == 0


def _confirmed_plan(conn, *, language: str = "javascript") -> dict[str, object]:
    user = create_user(
        conn,
        UserCreateRequest(
            display_name=f"Teaching Chunks User {uuid.uuid4().hex[:8]}",
            learning_style="practice_first",
            teaching_preference="step_by_step",
        ),
    )
    course = conn.execute(
        "SELECT id FROM language_courses WHERE language = %s LIMIT 1",
        (language,),
    ).fetchone()
    assert course is not None
    draft = PlanDraft(
        draft_id=f"draft_teaching_chunks_{uuid.uuid4().hex}",
        user_id=str(user["id"]),
        language_course_id=str(course["id"]),
        language=language,
        target_level="beginner",
        mode="goal_based",
        goal_text="Index teaching chunks during runtime persistence.",
        runtime_boundary=RuntimeBoundary(
            runtime_tier=_runtime_tier(language),
            unsupported_languages=[],
            notice="Test runtime boundary.",
        ),
        source_attribution=["test"],
        modules=[
            DraftModule(
                temp_id="module_alpha",
                title="Alpha Module",
                description="Module used for teaching chunk indexing tests.",
                order_index=0,
                is_skippable=False,
                is_adjustable=True,
                estimated_sessions=2,
                source="template",
                knowledge_points=[
                    DraftKnowledgePoint(
                        temp_id="kp_alpha",
                        title="Alpha Marker Runtime Indexing",
                        description="Alpha Marker durable lesson material.",
                        skill_tags=["alpha", "indexing"],
                    ),
                    DraftKnowledgePoint(
                        temp_id="kp_beta",
                        title="Beta Runtime Search Boundary",
                        description="Beta scoped durable lesson material.",
                        skill_tags=["beta", "scope"],
                    ),
                ],
            )
        ],
    )
    response, replayed = confirm_plan(
        conn,
        user_id=str(user["id"]),
        plan_draft=draft,
        idempotency_key=f"confirm-plan-test:{uuid.uuid4().hex}",
        request_hash=request_hash(draft.model_dump(mode="json")),
    )
    assert replayed is False
    conn.commit()
    return response


def _chunk_count(conn, knowledge_point_id: str) -> int:
    row = conn.execute(
        "SELECT count(*)::int AS cnt FROM teaching_chunks WHERE knowledge_point_id = %s",
        (knowledge_point_id,),
    ).fetchone()
    assert row is not None
    return int(row["cnt"])


def _runtime_tier(language: str) -> str:
    if language == "python":
        return "python_stdout_test"
    if language == "java":
        return "managed_compiled_test"
    if language == "cpp":
        return "compiled_sandbox_later"
    return "browser_preview"
