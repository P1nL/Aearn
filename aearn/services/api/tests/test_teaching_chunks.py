"""Tests for teaching chunks indexing and retrieval."""
from __future__ import annotations

import pytest

from app.services.teaching_chunks import index_knowledge_point_chunks, search_chunks
from app.agents.tools import LearningToolContext, do_search_teaching_materials


@pytest.fixture()
def conn():
    from app.core.config import get_settings
    import psycopg
    from psycopg.rows import dict_row

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
        kp = {"title": "Test", "description": "Desc", "lesson_outline_json": [{"title": "S1", "summary": "content"}], "lesson_sources_json": []}
        count1 = index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()
        count2 = index_knowledge_point_chunks(conn, knowledge_point_id, kp)
        conn.commit()
        assert count1 > 0
        assert count2 == 0  # already indexed

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
