from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.services.runtime_runner import run_exercise
from app.services.sql_query_runner import execute_sql_query_with_tests


def _sql_exercise() -> dict[str, object]:
    return {
        "runtime_profile": {
            "runtime_tier": "sql_query_test",
            "language": "sql",
            "runner": "sql",
            "sandbox_policy": {
                "dialect": "sqlite",
                "database": "per_run_ephemeral",
            },
        },
        "metadata_json": {
            "sql": {
                "dialect": "sqlite",
                "comparison": "ordered",
                "max_rows": 20,
                "setup_sql": [
                    "CREATE TABLE learners (id INTEGER PRIMARY KEY, name TEXT NOT NULL, track TEXT NOT NULL);",
                    "INSERT INTO learners (name, track) VALUES ('Ada', 'python'), ('Grace', 'sql'), ('Linus', 'systems');",
                ],
            },
        },
        "test_cases": [
            {
                "id": "visible_sql_track",
                "case_type": "visible",
                "expected_output_json": {
                    "columns": ["name"],
                    "rows": [{"name": "Grace"}],
                },
                "weight": 1,
                "is_critical": True,
            },
            {
                "id": "hidden_secret_expected_rows",
                "case_type": "hidden",
                "expected_output_json": {
                    "columns": ["name"],
                    "rows": [{"name": "Grace"}],
                },
                "weight": 2,
                "is_critical": False,
            },
        ],
    }


def test_sql_query_runner_executes_sqlite_select_with_visible_and_hidden_tests() -> None:
    result = execute_sql_query_with_tests(
        "SELECT name FROM learners WHERE track = 'sql' ORDER BY id",
        _sql_exercise()["test_cases"],  # type: ignore[arg-type]
        metadata=_sql_exercise()["metadata_json"],  # type: ignore[arg-type]
    )

    assert result.status == "success"
    assert result.stdout == "1 row"
    assert result.test_results[0].passed is True
    assert result.test_results[1].passed is True


def test_sql_query_runtime_adapter_redacts_hidden_results_in_public_output() -> None:
    exercise = _sql_exercise()
    result = run_exercise(
        exercise,
        "SELECT name FROM learners WHERE track = 'python'",
        {},
        "visible_tests",
    )
    serialized = repr(result.test_results)

    assert result.runtime_status == "success"
    assert result.test_pass_rate < 1.0
    assert result.test_results[1]["case_id"] == "hidden_case_2"
    assert result.test_results[1]["message"] == "A hidden test failed. Recheck edge cases and boundary behavior."
    assert "hidden_secret_expected_rows" not in serialized
    assert "Grace" not in serialized


def test_sql_query_runner_rejects_unsafe_sql_before_execution() -> None:
    for sql in [
        "UPDATE learners SET track = 'sql'",
        "SELECT name FROM learners; DROP TABLE learners;",
        "ATTACH DATABASE 'other.db' AS other",
        "PRAGMA database_list",
    ]:
        result = execute_sql_query_with_tests(
            sql,
            _sql_exercise()["test_cases"],  # type: ignore[arg-type]
            metadata=_sql_exercise()["metadata_json"],  # type: ignore[arg-type]
        )

        assert result.status == "runtime_error"
        assert result.error is not None
        assert "read-only SELECT" in result.error


def test_sql_query_runner_maps_syntax_error_to_runtime_error() -> None:
    result = execute_sql_query_with_tests(
        "SELECT FROM learners",
        _sql_exercise()["test_cases"],  # type: ignore[arg-type]
        metadata=_sql_exercise()["metadata_json"],  # type: ignore[arg-type]
    )

    assert result.status == "runtime_error"
    assert result.error is not None
    assert "SQL query failed" in result.error


def test_sql_query_runner_times_out_recursive_queries() -> None:
    result = execute_sql_query_with_tests(
        """
        WITH RECURSIVE counter(value) AS (
          SELECT 1
          UNION ALL
          SELECT value + 1 FROM counter
        )
        SELECT value FROM counter
        """,
        _sql_exercise()["test_cases"],  # type: ignore[arg-type]
        metadata=_sql_exercise()["metadata_json"],  # type: ignore[arg-type]
        timeout_s=0.001,
    )

    assert result.status == "timeout"
    assert result.error == "SQL query timed out."


def test_sql_query_runner_missing_sqlite_maps_to_unsupported(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.services import sql_query_runner

    monkeypatch.setattr(sql_query_runner, "sqlite3", None)

    result = run_exercise(_sql_exercise(), "SELECT name FROM learners", {}, "visible_tests")

    assert result.runtime_status == "unsupported"
    assert result.next_action == "retry_same"
    assert "SQLite" in (result.error_message or "")


def test_sql_query_runner_supports_unordered_result_comparison() -> None:
    exercise = _sql_exercise()
    metadata = dict(exercise["metadata_json"])  # type: ignore[arg-type]
    metadata["sql"] = {**metadata["sql"], "comparison": "unordered"}  # type: ignore[index]
    cases = [
        {
            "id": "visible_unordered",
            "case_type": "visible",
            "expected_output_json": {
                "columns": ["name"],
                "rows": [{"name": "Grace"}, {"name": "Ada"}],
            },
            "weight": 1,
            "is_critical": True,
        },
    ]

    result = execute_sql_query_with_tests(
        "SELECT name FROM learners WHERE track IN ('sql', 'python') ORDER BY name DESC",
        cases,
        metadata=metadata,  # type: ignore[arg-type]
    )

    assert result.status == "success"
    assert result.test_results[0].passed is True


def _fake_cases() -> Sequence[Mapping[str, object]]:
    return _sql_exercise()["test_cases"]  # type: ignore[return-value]
