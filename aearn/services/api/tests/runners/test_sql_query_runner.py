from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.services.runners.runtime_runner import run_exercise
from app.services.runners.sql_query_runner import (
    execute_sql_query_with_tests,
    execute_sql_workspace_query,
    sql_execution_result_to_safe_result,
)


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
    from app.services.runners import sql_query_runner

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


def _sql_v2_schema() -> list[dict[str, object]]:
    return [
        {
            "name": "mentors",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False, "primary_key": True},
                {"name": "name", "data_type": "TEXT", "nullable": False, "primary_key": False},
            ],
            "foreign_keys": [],
        },
        {
            "name": "learners",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False, "primary_key": True},
                {"name": "name", "data_type": "TEXT", "nullable": False, "primary_key": False},
                {"name": "track", "data_type": "TEXT", "nullable": False, "primary_key": False},
                {"name": "mentor_id", "data_type": "INTEGER", "nullable": True, "primary_key": False},
            ],
            "foreign_keys": [
                {"column": "mentor_id", "references_table": "mentors", "references_column": "id"}
            ],
        },
    ]


def _sql_v2_dataset(*, sql_name: str) -> dict[str, object]:
    return {
        "tables": [
            {"table": "mentors", "rows": [[1, "Grace Hopper"]]},
            {
                "table": "learners",
                "rows": [[1, "Ada", "python", 1], [2, sql_name, "sql", 1]],
            },
        ]
    }


def _sql_v2_cases() -> list[dict[str, object]]:
    return [
        {
            "id": "visible_sql",
            "case_type": "visible",
            "dataset": _sql_v2_dataset(sql_name="Grace"),
            "expected_output": {"kind": "table_result_v1", "columns": ["name"], "rows": [["Grace"]]},
            "weight": 1,
            "is_critical": True,
        },
        {
            "id": "private_hidden_identity",
            "case_type": "hidden",
            "dataset": _sql_v2_dataset(sql_name="Barbara"),
            "expected_output": {"kind": "table_result_v1", "columns": ["name"], "rows": [["Barbara"]]},
            "weight": 1,
            "is_critical": True,
        },
    ]


def test_sql_workspace_executes_public_and_hidden_datasets_independently() -> None:
    result = execute_sql_workspace_query(
        "SELECT name FROM learners WHERE track = 'sql' ORDER BY id",
        _sql_v2_cases(),
        schema=_sql_v2_schema(),
        public_dataset=_sql_v2_dataset(sql_name="Public Grace"),
        max_rows=20,
    )
    safe = sql_execution_result_to_safe_result(result)

    assert result.status == "success"
    assert result.columns == ["name"]
    assert result.rows == [["Public Grace"]]
    assert all(item.passed for item in result.test_results)
    assert safe.presentation.model_dump(mode="json") == {
        "kind": "table_result_v1",
        "columns": ["name"],
        "rows": [["Public Grace"]],
    }
    serialized = repr(safe.model_dump(mode="json"))
    assert "private_hidden_identity" not in serialized
    assert "Barbara" not in serialized
    assert safe.test_feedback[1].case_id == "non-visible-1"


def test_sql_workspace_keeps_public_grid_when_hidden_dataset_fails() -> None:
    result = execute_sql_workspace_query(
        "SELECT name FROM learners WHERE track = 'python' ORDER BY id",
        _sql_v2_cases(),
        schema=_sql_v2_schema(),
        public_dataset=_sql_v2_dataset(sql_name="Public Grace"),
        max_rows=20,
    )
    safe = sql_execution_result_to_safe_result(result)

    assert result.status == "success"
    assert result.rows == [["Ada"]]
    assert safe.status.value == "success"
    assert safe.passed_test_count == 0
    assert safe.presentation.kind == "table_result_v1"
    assert safe.test_feedback[1].message == "A non-visible scenario still failed."


def test_sql_workspace_rejects_unpublished_tables_and_excess_columns() -> None:
    unauthorized = execute_sql_workspace_query(
        "SELECT name FROM sqlite_master",
        _sql_v2_cases(),
        schema=_sql_v2_schema(),
        public_dataset=_sql_v2_dataset(sql_name="Public Grace"),
    )
    too_wide = execute_sql_workspace_query(
        "SELECT " + ",".join(f"{index} AS c{index}" for index in range(33)),
        _sql_v2_cases(),
        schema=_sql_v2_schema(),
        public_dataset=_sql_v2_dataset(sql_name="Public Grace"),
    )

    assert unauthorized.status == "runtime_error"
    assert too_wide.status == "runtime_error"
    assert sql_execution_result_to_safe_result(unauthorized).presentation.kind == "none"


def test_sql_workspace_schema_order_does_not_control_foreign_key_loading() -> None:
    schema = list(reversed(_sql_v2_schema()))
    dataset = _sql_v2_dataset(sql_name="Public Grace")
    dataset["tables"] = list(reversed(dataset["tables"]))  # type: ignore[index]

    result = execute_sql_workspace_query(
        "SELECT name FROM learners WHERE track = 'sql'",
        _sql_v2_cases(),
        schema=schema,
        public_dataset=dataset,
    )

    assert result.status == "success"
    assert result.rows == [["Public Grace"]]


def test_sql_workspace_rejects_non_primary_or_type_mismatched_foreign_keys() -> None:
    non_primary = _sql_v2_schema()
    non_primary[0]["columns"][0]["primary_key"] = False  # type: ignore[index]
    mismatched = _sql_v2_schema()
    mismatched[1]["columns"][3]["data_type"] = "TEXT"  # type: ignore[index]

    for schema in (non_primary, mismatched):
        result = execute_sql_workspace_query(
            "SELECT name FROM learners",
            _sql_v2_cases(),
            schema=schema,
            public_dataset=_sql_v2_dataset(sql_name="Public Grace"),
        )
        assert result.status == "runtime_error"
        assert sql_execution_result_to_safe_result(result).presentation.kind == "none"


def test_sql_workspace_applies_sqlite_output_resource_limits() -> None:
    result = execute_sql_workspace_query(
        "SELECT printf('%200000s', 'x') AS huge FROM learners LIMIT 1",
        _sql_v2_cases(),
        schema=_sql_v2_schema(),
        public_dataset=_sql_v2_dataset(sql_name="Public Grace"),
    )

    assert result.status == "success"
    assert result.rows == [[None]]
    safe = sql_execution_result_to_safe_result(result)
    assert safe.presentation.model_dump(mode="json") == {
        "kind": "table_result_v1",
        "columns": ["huge"],
        "rows": [[None]],
    }
