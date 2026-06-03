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
from app.services.llm.llm_client import LLMInvalidResponseError
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
            assert model_context["required_skill_tags"] == [language, "adaptive"]
            assert model_context["module_context"]["module_title"] == f"Adaptive {language} module"
            assert model_context["lesson_outline"][0]["title"] == f"{language} target behavior"
            assert model_context["source_attribution"][0]["title"] == "Local test lesson"
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
            candidate_generator=lambda _context, _template: GeneratedAdaptiveCandidate(
                content={
                    "candidate": {
                        "title": "Model-assisted SQL practice",
                        "prompt_markdown": "Practice SQL filtering with validated model wording.",
                        "starter_code": fallback["starter_code"],
                        "solution_reference": fallback["solution_reference"],
                        "metadata_json": fallback["metadata_json"],
                    }
                },
                model="sql-model",
            ),
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


@pytest.mark.parametrize(
    ("language", "expected_runtime_tier", "expected_runner", "expected_entry_function"),
    [
        ("typescript", "node_typescript_test", "node", "increment"),
        ("go", "managed_compiled_test", "compiled", "Increment"),
        ("csharp", "managed_compiled_test", "compiled", "Increment"),
    ],
)
def test_public_non_browser_languages_have_runner_matching_internal_seeds(
    language: str,
    expected_runtime_tier: str,
    expected_runner: str,
    expected_entry_function: str,
) -> None:
    bootstrap_database()
    with connect() as conn:
        context = _learning_context(conn, language=language)
        fallback = _exercise_template(context["knowledge_point"], context["runtime_profile"])
        conn.rollback()

    starter_code = str(fallback["starter_code"])
    solution_reference = str(fallback["solution_reference"])
    metadata = fallback["metadata_json"]
    assert context["runtime_profile"]["runtime_tier"] == expected_runtime_tier
    assert context["runtime_profile"]["runner"] == expected_runner
    assert metadata["entry_function"] == expected_entry_function
    assert "document.querySelector" not in starter_code
    assert "addEventListener" not in solution_reference
    assert fallback["test_cases"][0]["input_json"] == {"args": [1]}
    assert fallback["test_cases"][0]["expected_output_json"] == {"return": 2}


def test_semantic_miss_retries_with_safe_feedback_before_cache() -> None:
    bootstrap_database()
    with connect() as conn:
        context = _learning_context(
            conn,
            language="python",
            skill_tags=["python", "list_comprehension"],
        )
        fallback = _exercise_template(context["knowledge_point"], context["runtime_profile"])
        contexts: list[Mapping[str, object]] = []

        def fake_model_candidate(
            model_context: Mapping[str, object],
            _template: object,
        ) -> GeneratedAdaptiveCandidate:
            contexts.append(model_context)
            if len(contexts) == 1:
                return GeneratedAdaptiveCandidate(
                    content={
                        "candidate": {
                            "title": "Generic Python return practice",
                            "prompt_markdown": "Practice returning a computed value.",
                            "starter_code": fallback["starter_code"],
                            "solution_reference": fallback["solution_reference"],
                            "metadata_json": {
                                **fallback["metadata_json"],
                                "target_skill_tags": ["python"],
                            },
                        }
                    },
                    model="retry-model",
                )
            return GeneratedAdaptiveCandidate(
                content={
                    "candidate": {
                        "title": "List comprehension score summary",
                        "prompt_markdown": "Use a list comprehension before summing the normalized scores.",
                        "starter_code": (
                            "def summarize_scores(scores):\n"
                            "    normalized = [__BLANK_1__ for score in scores]\n"
                            "    total = sum(normalized)\n"
                            "    print(f\"total={total}\")\n"
                            "    return total\n"
                        ),
                        "solution_reference": _python_list_comprehension_solution(),
                        "metadata_json": {
                            **fallback["metadata_json"],
                            "target_skill_tags": ["python", "list_comprehension"],
                        },
                        "code_blanks": fallback["code_blanks"],
                    }
                },
                model="retry-model",
            )

        exercise = build_adaptive_exercise_template(
            conn,
            knowledge_point=context["knowledge_point"],
            runtime_profile=context["runtime_profile"],
            fallback_template=fallback,
            candidate_generator=fake_model_candidate,
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
    assert adaptive_meta["source"] == "model_candidate"
    assert adaptive_meta["validation_status"] == "validated"
    assert adaptive_meta["generator_model"] == "retry-model"
    assert len(contexts) == 2
    retry_feedback = contexts[1]["previous_validation_feedback"]
    assert retry_feedback[-1]["failure_stage"] == "semantic"
    assert retry_feedback[-1]["failure_code"] == "missing_required_skill"
    assert retry_feedback[-1]["missing_skill_tags"] == ["list_comprehension"]
    assert "solution_reference" not in json.dumps(retry_feedback, ensure_ascii=False)
    assert cache_count is not None
    assert cache_count["count"] == 1


def test_retry_cap_exhaustion_returns_honest_unavailable_without_fallback() -> None:
    bootstrap_database()
    with connect() as conn:
        context = _learning_context(
            conn,
            language="python",
            skill_tags=["python", "list_comprehension"],
        )
        fallback = _exercise_template(context["knowledge_point"], context["runtime_profile"])
        calls = 0

        def generic_candidate(
            _context: Mapping[str, object],
            _template: object,
        ) -> GeneratedAdaptiveCandidate:
            nonlocal calls
            calls += 1
            return GeneratedAdaptiveCandidate(
                content={
                    "candidate": {
                        "title": "Still generic Python practice",
                        "prompt_markdown": "Practice returning a computed value.",
                        "starter_code": fallback["starter_code"],
                        "solution_reference": fallback["solution_reference"],
                        "metadata_json": {
                            **fallback["metadata_json"],
                            "target_skill_tags": ["python"],
                        },
                    }
                },
                model="stuck-model",
            )

        with pytest.raises(LLMInvalidResponseError):
            build_adaptive_exercise_template(
                conn,
                knowledge_point=context["knowledge_point"],
                runtime_profile=context["runtime_profile"],
                fallback_template=fallback,
                candidate_generator=generic_candidate,
            )
        cache_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM exercise_variant_cache
            WHERE user_id = %s AND knowledge_point_id = %s
            """,
            (context["user_id"], context["knowledge_point"]["id"]),
        ).fetchone()
        conn.rollback()

    assert calls == 3
    assert cache_count is not None
    assert cache_count["count"] == 0


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


def test_invalid_model_output_and_runner_failure_retry_instead_of_fallback() -> None:
    bootstrap_database()
    with connect() as conn:
        python_context = _learning_context(conn, language="python")
        fallback = _exercise_template(python_context["knowledge_point"], python_context["runtime_profile"])
        invalid_contexts: list[Mapping[str, object]] = []

        invalid = build_adaptive_exercise_template(
            conn,
            knowledge_point=python_context["knowledge_point"],
            runtime_profile=python_context["runtime_profile"],
            fallback_template=fallback,
            candidate_generator=lambda model_context, _template: _invalid_then_valid_candidate(
                invalid_contexts,
                model_context,
                fallback,
            ),
        )

        invalid_meta = invalid["metadata_json"]["adaptive_variant"]
        assert invalid_meta["source"] == "model_candidate"
        assert invalid_meta["validation_status"] == "validated"
        assert invalid_meta["generator_model"] == "recovered-model"
        assert invalid_contexts[1]["previous_validation_feedback"][-1]["failure_stage"] == "schema"
        assert invalid_contexts[1]["previous_validation_feedback"][-1]["failure_code"] == "unsupported_candidate_field"

        validation_context = _learning_context(conn, language="python")
        validation_fallback = _exercise_template(validation_context["knowledge_point"], validation_context["runtime_profile"])
        validation_contexts: list[Mapping[str, object]] = []
        failing_validation = build_adaptive_exercise_template(
            conn,
            knowledge_point=validation_context["knowledge_point"],
            runtime_profile=validation_context["runtime_profile"],
            fallback_template=validation_fallback,
            candidate_generator=lambda model_context, _template: _runner_failure_then_valid_candidate(
                validation_contexts,
                model_context,
                validation_fallback,
            ),
        )

        validation_meta = failing_validation["metadata_json"]["adaptive_variant"]
        assert validation_meta["source"] == "model_candidate"
        assert validation_meta["validation_status"] == "validated"
        assert validation_meta["generator_model"] == "runner-recovery-model"
        assert validation_contexts[1]["previous_validation_feedback"][-1]["failure_stage"] == "runner"
        assert validation_contexts[1]["previous_validation_feedback"][-1]["failure_code"] in {"tests_failed", "runtime_error"}

        cpp_runtime = conn.execute(
            "SELECT * FROM runtime_profiles WHERE language = 'cpp' LIMIT 1",
        ).fetchone()
        assert cpp_runtime is not None
        unsupported_fallback = _exercise_template(
            validation_context["knowledge_point"],
            cpp_runtime,
        )
        with pytest.raises(LLMInvalidResponseError):
            build_adaptive_exercise_template(
                conn,
                knowledge_point=validation_context["knowledge_point"],
                runtime_profile=cpp_runtime,
                fallback_template=unsupported_fallback,
                candidate_generator=lambda _context, _template: pytest.fail("unsupported runner should not call model"),
            )
        conn.commit()


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


def _learning_context(
    conn,
    *,
    language: str,
    skill_tags: list[str] | None = None,
    lesson_outline: list[dict[str, str]] | None = None,
    lesson_sources: list[dict[str, str]] | None = None,
) -> dict[str, object]:
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
        RETURNING id, title
        """,
        (plan["id"], f"Adaptive {language} module"),
    ).fetchone()
    assert module is not None
    knowledge_point = conn.execute(
        """
        INSERT INTO knowledge_points (
          module_id, language_course_id, title, description, order_index,
          skill_tags_json, weak_points_json, lesson_outline_json, lesson_sources_json
        )
        VALUES (%s, %s, %s, %s, 0, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
        RETURNING *
        """,
        (
            module["id"],
            course["course_id"],
            f"Adaptive {language} concept",
            "Practice with model-assisted variants.",
            json.dumps(skill_tags or [language, "adaptive"]),
            json.dumps(["return_vs_output", "edge_case_error"]),
            json.dumps(lesson_outline or _default_lesson_outline(language)),
            json.dumps(lesson_sources or [{"title": "Local test lesson", "url": "https://docs.example.test/aearn"}]),
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
            "module_title": str(module["title"]),
            "course_title": str(course["language"]),
        },
        "runtime_profile": runtime_profile,
    }


def _default_lesson_outline(language: str) -> list[dict[str, str]]:
    return [
        {
            "id": "target_behavior",
            "title": f"{language} target behavior",
            "note": "Practice the exact route concept instead of a generic language drill.",
        }
    ]


def _python_list_comprehension_solution() -> str:
    return (
        "def summarize_scores(scores):\n"
        "    normalized = [score for score in scores]\n"
        "    total = sum(normalized)\n"
        "    print(f\"total={total}\")\n"
        "    return total\n\n"
        "result = summarize_scores([2, 3, 4])\n"
    )


def _invalid_then_valid_candidate(
    contexts: list[Mapping[str, object]],
    model_context: Mapping[str, object],
    fallback: Mapping[str, object],
) -> GeneratedAdaptiveCandidate:
    contexts.append(model_context)
    if len(contexts) == 1:
        return GeneratedAdaptiveCandidate(
            content={"candidate": {"test_cases": [{"id": "model_must_not_own_tests"}]}},
            model="bad-model",
        )
    return GeneratedAdaptiveCandidate(
        content={
            "candidate": {
                "title": "Recovered model candidate",
                "prompt_markdown": "Recover from schema feedback with an allowed candidate shape.",
                "starter_code": fallback["starter_code"],
                "solution_reference": fallback["solution_reference"],
                "metadata_json": fallback["metadata_json"],
            }
        },
        model="recovered-model",
    )


def _runner_failure_then_valid_candidate(
    contexts: list[Mapping[str, object]],
    model_context: Mapping[str, object],
    fallback: Mapping[str, object],
) -> GeneratedAdaptiveCandidate:
    contexts.append(model_context)
    if len(contexts) == 1:
        return GeneratedAdaptiveCandidate(
            content={
                "candidate": {
                    "title": "Invalid validated code",
                    "prompt_markdown": "This candidate should fail runner validation.",
                    "starter_code": fallback["starter_code"],
                    "solution_reference": "def summarize_scores(scores):\n    return -1\n",
                    "metadata_json": fallback["metadata_json"],
                }
            },
            model="bad-validation-model",
        )
    return GeneratedAdaptiveCandidate(
        content={
            "candidate": {
                "title": "Runner-recovered model candidate",
                "prompt_markdown": "Recover from runner feedback with a passing candidate.",
                "starter_code": fallback["starter_code"],
                "solution_reference": fallback["solution_reference"],
                "metadata_json": fallback["metadata_json"],
            }
        },
        model="runner-recovery-model",
    )
