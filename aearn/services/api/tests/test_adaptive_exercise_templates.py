from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

import psycopg
import pytest

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.exercises import adaptive_exercise_service
from app.services.exercises.adaptive_exercise_service import GeneratedAdaptiveCandidate, build_adaptive_exercise_template
from app.services.exercises.exercise_repository import _exercise_template, get_or_create_exercise_for_knowledge_point
from app.services.repositories.local_user_data_repository import export_user_data, get_user_data_summary, reset_user_data


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


@pytest.mark.parametrize("language", ["python", "javascript"])
def test_model_candidate_is_runner_validated_and_cached(language: str) -> None:
    bootstrap_database()
    with connect() as conn:
        context = _learning_context(conn, language=language)
        fallback = _exercise_template(context["knowledge_point"], context["runtime_profile"])
        calls = 0

        def fake_model_candidate(
            model_context: Mapping[str, object],
            template: object,
        ) -> GeneratedAdaptiveCandidate:
            nonlocal calls
            calls += 1
            assert model_context["user_id"] == context["user_id"]
            return GeneratedAdaptiveCandidate(
                content={
                    "candidate": {
                        "title": f"Model-assisted {language} practice",
                        "prompt_markdown": f"Practice {language} with validated model wording.",
                        "starter_code": fallback["starter_code"],
                        "solution_reference": fallback["solution_reference"],
                        "metadata_json": fallback["metadata_json"],
                    }
                },
                model="fake-model-v1",
            )

        first = build_adaptive_exercise_template(
            conn,
            knowledge_point=context["knowledge_point"],
            runtime_profile=context["runtime_profile"],
            fallback_template=fallback,
            candidate_generator=fake_model_candidate,
        )
        second = build_adaptive_exercise_template(
            conn,
            knowledge_point=context["knowledge_point"],
            runtime_profile=context["runtime_profile"],
            fallback_template=fallback,
            candidate_generator=lambda _context, _template: pytest.fail("cache hit should not call the model"),
        )
        conn.commit()

    first_meta = first["metadata_json"]["adaptive_variant"]
    second_meta = second["metadata_json"]["adaptive_variant"]
    assert first_meta["source"] == "model_candidate"
    assert first_meta["validation_status"] == "validated"
    assert first_meta["generator_model"] == "fake-model-v1"
    assert second_meta["cache_hit"] is True
    assert second["title"] == first["title"]
    assert calls == 1


def test_sql_template_uses_query_exercise_not_browser_fallback() -> None:
    bootstrap_database()
    with connect() as conn:
        context = _learning_context(conn, language="sql")
        fallback = _exercise_template(context["knowledge_point"], context["runtime_profile"])
        exercise = build_adaptive_exercise_template(
            conn,
            knowledge_point=context["knowledge_point"],
            runtime_profile=context["runtime_profile"],
            fallback_template=fallback,
            candidate_generator=lambda _context, _template: None,
        )
        conn.commit()

    starter_code = str(exercise["starter_code"])
    metadata = exercise["metadata_json"]
    adaptive_meta = metadata["adaptive_variant"]

    assert starter_code.lstrip().upper().startswith("SELECT")
    assert "document.querySelector" not in starter_code
    assert "addEventListener" not in starter_code
    assert "count += 1" not in starter_code
    assert metadata["sql"]["dialect"] == "sqlite"
    assert adaptive_meta["validation_status"] == "validated"
    assert adaptive_meta["runtime_tier"] == "sql_query_test"


def test_exercise_repository_materializes_validated_model_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap_database()
    with connect() as conn:
        context = _learning_context(conn, language="python")
        fallback = _exercise_template(context["knowledge_point"], context["runtime_profile"])

        def fake_model_candidate(_context: Mapping[str, object], _template: object) -> GeneratedAdaptiveCandidate:
            return GeneratedAdaptiveCandidate(
                content={
                    "candidate": {
                        "title": "Materialized model candidate",
                        "prompt_markdown": "Use return value evidence in this model-assisted variant.",
                        "starter_code": fallback["starter_code"],
                        "solution_reference": fallback["solution_reference"],
                        "metadata_json": fallback["metadata_json"],
                    }
                },
                model="materializer-model",
            )

        monkeypatch.setattr(adaptive_exercise_service, "build_model_candidate", fake_model_candidate)

        exercise = get_or_create_exercise_for_knowledge_point(
            conn,
            knowledge_point=context["knowledge_point"],
            runtime_profile=context["runtime_profile"],
        )
        cache_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM exercise_variant_cache
            WHERE user_id = %s AND knowledge_point_id = %s AND status = 'validated'
            """,
            (context["user_id"], context["knowledge_point"]["id"]),
        ).fetchone()
        conn.commit()

    adaptive_meta = exercise["metadata_json"]["adaptive_variant"]
    assert exercise["title"] == "Materialized model candidate"
    assert adaptive_meta["source"] == "model_candidate"
    assert adaptive_meta["validation_status"] == "validated"
    assert adaptive_meta["generator_model"] == "materializer-model"
    assert cache_count is not None
    assert cache_count["count"] == 1


def test_invalid_model_output_validation_failure_and_unsupported_runner_fall_back() -> None:
    bootstrap_database()
    with connect() as conn:
        python_context = _learning_context(conn, language="python")
        fallback = _exercise_template(python_context["knowledge_point"], python_context["runtime_profile"])

        invalid = build_adaptive_exercise_template(
            conn,
            knowledge_point=python_context["knowledge_point"],
            runtime_profile=python_context["runtime_profile"],
            fallback_template=fallback,
            candidate_generator=lambda _context, _template: GeneratedAdaptiveCandidate(
                content={"candidate": {"test_cases": [{"id": "model_must_not_own_tests"}]}},
                model="bad-model",
            ),
        )

        invalid_meta = invalid["metadata_json"]["adaptive_variant"]
        assert invalid_meta["source"] == "deterministic_fallback"
        assert invalid_meta["validation_status"] == "validated"
        assert invalid_meta["fallback_reason"] == "invalid_model_candidate"

        validation_context = _learning_context(conn, language="python")
        validation_fallback = _exercise_template(validation_context["knowledge_point"], validation_context["runtime_profile"])
        failing_validation = build_adaptive_exercise_template(
            conn,
            knowledge_point=validation_context["knowledge_point"],
            runtime_profile=validation_context["runtime_profile"],
            fallback_template=validation_fallback,
            candidate_generator=lambda _context, _template: GeneratedAdaptiveCandidate(
                content={
                    "candidate": {
                        "title": "Invalid validated code",
                        "prompt_markdown": "This candidate should fail runner validation.",
                        "starter_code": validation_fallback["starter_code"],
                        "solution_reference": "def summarize_scores(scores):\n    return -1\n",
                        "metadata_json": validation_fallback["metadata_json"],
                    }
                },
                model="bad-validation-model",
            ),
        )

        validation_meta = failing_validation["metadata_json"]["adaptive_variant"]
        assert validation_meta["source"] == "fallback_template"
        assert validation_meta["validation_status"] == "fallback"
        assert validation_meta["fallback_reason"] == "validation_failed"

        cpp_runtime = conn.execute(
            "SELECT * FROM runtime_profiles WHERE language = 'cpp' LIMIT 1",
        ).fetchone()
        assert cpp_runtime is not None
        unsupported_fallback = _exercise_template(
            validation_context["knowledge_point"],
            cpp_runtime,
        )
        unsupported = build_adaptive_exercise_template(
            conn,
            knowledge_point=validation_context["knowledge_point"],
            runtime_profile=cpp_runtime,
            fallback_template=unsupported_fallback,
            candidate_generator=lambda _context, _template: pytest.fail("unsupported runner should not call model"),
        )
        conn.commit()

    unsupported_meta = unsupported["metadata_json"]["adaptive_variant"]
    assert unsupported_meta["source"] == "fallback_template"
    assert unsupported_meta["fallback_reason"] == "runner_unsupported"


def test_variant_cache_is_user_scoped_and_safe_for_export_and_reset() -> None:
    bootstrap_database()
    with connect() as conn:
        context = _learning_context(conn, language="python")
        fallback = _exercise_template(context["knowledge_point"], context["runtime_profile"])

        candidate = build_adaptive_exercise_template(
            conn,
            knowledge_point=context["knowledge_point"],
            runtime_profile=context["runtime_profile"],
            fallback_template=fallback,
            candidate_generator=lambda _context, _template: GeneratedAdaptiveCandidate(
                content={
                    "candidate": {
                        "title": "Export-safe model candidate",
                        "prompt_markdown": "Practice return values without exposing hidden details.",
                        "starter_code": fallback["starter_code"],
                        "solution_reference": fallback["solution_reference"],
                        "metadata_json": fallback["metadata_json"],
                    }
                },
                model="export-model",
            ),
        )
        assert candidate["metadata_json"]["adaptive_variant"]["source"] == "model_candidate"

        summary = get_user_data_summary(conn, str(context["user_id"]))
        exported = export_user_data(conn, str(context["user_id"]))
        export_text = json.dumps(exported, ensure_ascii=False)

        assert summary["counts"]["exercise_variant_cache"] == 1
        assert "adaptive_variant_summaries" in exported
        assert "def summarize_scores" not in export_text
        assert "raw provider payload" not in export_text
        assert "expected_output_json" not in export_text

        reset = reset_user_data(conn, str(context["user_id"]))
        after_count = conn.execute(
            "SELECT count(*) AS count FROM exercise_variant_cache WHERE user_id = %s",
            (context["user_id"],),
        ).fetchone()
        conn.commit()

    assert reset["summary"]["counts"]["exercise_variant_cache"] == 0
    assert after_count is not None
    assert after_count["count"] == 0


def _learning_context(conn, *, language: str) -> dict[str, object]:
    suffix = uuid.uuid4().hex[:8]
    user = conn.execute(
        "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
        (f"Adaptive User {suffix}",),
    ).fetchone()
    assert user is not None
    course = conn.execute(
        """
        SELECT
          language_courses.id AS course_id,
          language_courses.language,
          runtime_profiles.*
        FROM language_courses
        JOIN runtime_profiles ON runtime_profiles.id = language_courses.runtime_profile_id
        WHERE language_courses.language = %s
        LIMIT 1
        """,
        (language,),
    ).fetchone()
    assert course is not None
    plan = conn.execute(
        """
        INSERT INTO learning_plans (
          user_id, language_course_id, goal_text, language, target_level, mode
        )
        VALUES (%s, %s, %s, %s, 'beginner', 'goal_based')
        RETURNING id
        """,
        (user["id"], course["course_id"], f"Practice adaptive {language}", course["language"]),
    ).fetchone()
    assert plan is not None
    module = conn.execute(
        """
        INSERT INTO plan_modules (plan_id, title, order_index, is_skippable)
        VALUES (%s, %s, 0, false)
        RETURNING id
        """,
        (plan["id"], f"Adaptive {language} module"),
    ).fetchone()
    assert module is not None
    knowledge_point = conn.execute(
        """
        INSERT INTO knowledge_points (
          module_id, language_course_id, title, description, order_index,
          skill_tags_json, weak_points_json
        )
        VALUES (%s, %s, %s, %s, 0, %s::jsonb, %s::jsonb)
        RETURNING *
        """,
        (
            module["id"],
            course["course_id"],
            f"Adaptive {language} concept",
            "Practice with model-assisted variants.",
            json.dumps([language, "adaptive"]),
            json.dumps(["return_vs_output", "edge_case_error"]),
        ),
    ).fetchone()
    assert knowledge_point is not None
    runtime_profile = conn.execute(
        "SELECT * FROM runtime_profiles WHERE id = %s",
        (course["id"],),
    ).fetchone()
    assert runtime_profile is not None
    return {
        "user_id": str(user["id"]),
        "plan_id": str(plan["id"]),
        "knowledge_point": dict(knowledge_point) | {
            "user_id": str(user["id"]),
            "plan_id": str(plan["id"]),
        },
        "runtime_profile": runtime_profile,
    }
