from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_sqlite3: Any
try:
    import sqlite3 as _sqlite3
except ImportError:  # pragma: no cover - sqlite3 is normally bundled with Python.
    _sqlite3 = None


sqlite3: Any = _sqlite3

MAX_SQL_ERROR_CHARS = 500
MAX_SQL_CELL_CHARS = 500
DEFAULT_SQL_MAX_ROWS = 50
HARD_SQL_MAX_ROWS = 200
UNSAFE_SQL_TOKENS = {
    "alter",
    "attach",
    "begin",
    "commit",
    "create",
    "delete",
    "detach",
    "drop",
    "insert",
    "load_extension",
    "pragma",
    "reindex",
    "release",
    "replace",
    "rollback",
    "savepoint",
    "transaction",
    "update",
    "vacuum",
}


@dataclass(slots=True)
class SqlTestCaseResult:
    case_id: str
    case_type: str
    passed: bool
    weight: float
    is_critical: bool
    message: str
    duration_ms: int


@dataclass(slots=True)
class SqlExecutionResult:
    status: str
    stdout: str
    stderr: str
    error: str | None
    test_results: list[SqlTestCaseResult]
    total_duration_ms: int


@dataclass(frozen=True, slots=True)
class SqlRunnerOptions:
    dialect: str
    setup_sql: tuple[str, ...]
    comparison: str
    max_rows: int


def execute_sql_query_with_tests(
    query: str,
    test_cases: Sequence[Mapping[str, object]],
    *,
    metadata: Mapping[str, object] | None = None,
    timeout_s: float = 5.0,
) -> SqlExecutionResult:
    start = time.perf_counter()
    if sqlite3 is None:
        return SqlExecutionResult(
            status="missing_toolchain",
            stdout="",
            stderr="",
            error="SQLite support is required for sql_query_test.",
            test_results=[],
            total_duration_ms=_elapsed_ms(start),
        )

    options = _runner_options(metadata or {})
    if options.dialect != "sqlite":
        return SqlExecutionResult(
            status="unsupported",
            stdout="",
            stderr="",
            error="Only the SQLite teaching dialect is supported for SQL exercises.",
            test_results=_failed_test_results(test_cases, "Only the SQLite teaching dialect is supported."),
            total_duration_ms=_elapsed_ms(start),
        )

    validation_error = _validate_learner_query(query)
    if validation_error is not None:
        return SqlExecutionResult(
            status="runtime_error",
            stdout="",
            stderr="",
            error=validation_error,
            test_results=_failed_test_results(test_cases, validation_error),
            total_duration_ms=_elapsed_ms(start),
        )

    timed_out = False
    deadline = time.perf_counter() + max(timeout_s, 0.001)

    def progress_handler() -> int:
        nonlocal timed_out
        if time.perf_counter() >= deadline:
            timed_out = True
            return 1
        return 0

    try:
        conn = sqlite3.connect(":memory:")
    except sqlite3.Error:
        return SqlExecutionResult(
            status="unsupported",
            stdout="",
            stderr="",
            error="SQLite teaching database could not be created.",
            test_results=_failed_test_results(test_cases, "SQLite teaching database could not be created."),
            total_duration_ms=_elapsed_ms(start),
        )

    try:
        conn.row_factory = sqlite3.Row
        _disable_extension_loading(conn)
        for setup_statement in options.setup_sql:
            if setup_statement.strip():
                conn.executescript(setup_statement)
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_sqlite_authorizer)
        conn.set_progress_handler(progress_handler, 1 if timeout_s <= 0.01 else 1000)
        columns, rows = _execute_bounded_query(conn, query, options.max_rows, _uses_recursive_cte(query))
    except sqlite3.OperationalError as exc:
        if timed_out or "interrupted" in str(exc).lower():
            return SqlExecutionResult(
                status="timeout",
                stdout="",
                stderr="",
                error="SQL query timed out.",
                test_results=_failed_test_results(test_cases, "SQL query timed out."),
                total_duration_ms=_elapsed_ms(start),
            )
        return SqlExecutionResult(
            status="runtime_error",
            stdout="",
            stderr="",
            error=_bound_text(f"SQL query failed: {exc}", MAX_SQL_ERROR_CHARS),
            test_results=_failed_test_results(test_cases, "SQL query failed."),
            total_duration_ms=_elapsed_ms(start),
        )
    except sqlite3.DatabaseError:
        return SqlExecutionResult(
            status="runtime_error",
            stdout="",
            stderr="",
            error="SQL fixture setup or query execution failed.",
            test_results=_failed_test_results(test_cases, "SQL query failed."),
            total_duration_ms=_elapsed_ms(start),
        )
    finally:
        conn.close()

    test_results = _evaluate_test_cases(test_cases, columns, rows, options.comparison)
    return SqlExecutionResult(
        status="success",
        stdout=_row_count_stdout(len(rows)),
        stderr="",
        error=None,
        test_results=test_results,
        total_duration_ms=_elapsed_ms(start),
    )


def _runner_options(metadata: Mapping[str, object]) -> SqlRunnerOptions:
    sql_metadata = metadata.get("sql", {})
    if not isinstance(sql_metadata, Mapping):
        sql_metadata = {}

    setup_sql_raw = sql_metadata.get("setup_sql", ())
    setup_sql: tuple[str, ...]
    if isinstance(setup_sql_raw, Sequence) and not isinstance(setup_sql_raw, str):
        setup_sql = tuple(str(statement) for statement in setup_sql_raw)
    else:
        setup_sql = ()

    comparison = str(sql_metadata.get("comparison", "ordered")).lower()
    if comparison not in {"ordered", "unordered"}:
        comparison = "ordered"

    max_rows = _int_in_range(sql_metadata.get("max_rows"), DEFAULT_SQL_MAX_ROWS, 1, HARD_SQL_MAX_ROWS)
    return SqlRunnerOptions(
        dialect=str(sql_metadata.get("dialect", "sqlite")).lower(),
        setup_sql=setup_sql,
        comparison=comparison,
        max_rows=max_rows,
    )


def _validate_learner_query(query: str) -> str | None:
    if not query.strip():
        return "SQL query must be a single read-only SELECT statement."

    if _has_multiple_statements(query):
        return "SQL query must be a single read-only SELECT statement."

    tokens = _sql_tokens(query)
    if not tokens or tokens[0] not in {"select", "with"}:
        return "SQL query must be a single read-only SELECT statement."

    if any(token in UNSAFE_SQL_TOKENS for token in tokens):
        return "SQL query must be a single read-only SELECT statement."

    return None


def _has_multiple_statements(query: str) -> bool:
    semicolons = _semicolon_positions_outside_literals(query)
    if not semicolons:
        return False
    first = semicolons[0]
    if query[first + 1 :].strip():
        return True
    return len(semicolons) > 1


def _semicolon_positions_outside_literals(query: str) -> list[int]:
    positions: list[int] = []
    state = "normal"
    index = 0
    while index < len(query):
        char = query[index]
        next_char = query[index + 1] if index + 1 < len(query) else ""
        if state == "normal":
            if char == "'":
                state = "single"
            elif char == '"':
                state = "double"
            elif char == "-" and next_char == "-":
                state = "line_comment"
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                index += 1
            elif char == ";":
                positions.append(index)
        elif state == "single":
            if char == "'" and next_char == "'":
                index += 1
            elif char == "'":
                state = "normal"
        elif state == "double":
            if char == '"' and next_char == '"':
                index += 1
            elif char == '"':
                state = "normal"
        elif state == "line_comment":
            if char in {"\n", "\r"}:
                state = "normal"
        elif state == "block_comment" and char == "*" and next_char == "/":
            state = "normal"
            index += 1
        index += 1
    return positions


def _sql_tokens(query: str) -> list[str]:
    cleaned = _remove_sql_comments_and_literals(query)
    return [match.group(0).lower() for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", cleaned)]


def _remove_sql_comments_and_literals(query: str) -> str:
    chars: list[str] = []
    state = "normal"
    index = 0
    while index < len(query):
        char = query[index]
        next_char = query[index + 1] if index + 1 < len(query) else ""
        if state == "normal":
            if char == "'":
                state = "single"
                chars.append(" ")
            elif char == '"':
                state = "double"
                chars.append(" ")
            elif char == "-" and next_char == "-":
                state = "line_comment"
                chars.append(" ")
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                chars.append(" ")
                index += 1
            else:
                chars.append(char)
        elif state == "single":
            chars.append(" ")
            if char == "'" and next_char == "'":
                index += 1
                chars.append(" ")
            elif char == "'":
                state = "normal"
        elif state == "double":
            chars.append(" ")
            if char == '"' and next_char == '"':
                index += 1
                chars.append(" ")
            elif char == '"':
                state = "normal"
        elif state == "line_comment":
            chars.append(" ")
            if char in {"\n", "\r"}:
                state = "normal"
        elif state == "block_comment":
            chars.append(" ")
            if char == "*" and next_char == "/":
                state = "normal"
                index += 1
                chars.append(" ")
        index += 1
    return "".join(chars)


def _sqlite_authorizer(action_code: int, arg1: str | None, arg2: str | None, db_name: str | None, source: str | None) -> int:
    del arg1, db_name, source
    ok = int(getattr(sqlite3, "SQLITE_OK", 0))
    deny = int(getattr(sqlite3, "SQLITE_DENY", 1))
    allowed = {
        getattr(sqlite3, "SQLITE_READ", None),
        getattr(sqlite3, "SQLITE_SELECT", None),
        getattr(sqlite3, "SQLITE_RECURSIVE", None),
    }
    if action_code in allowed:
        return ok
    if action_code == getattr(sqlite3, "SQLITE_FUNCTION", None):
        return deny if str(arg2 or "").lower() == "load_extension" else ok
    return deny


def _disable_extension_loading(conn: Any) -> None:
    enable = getattr(conn, "enable_load_extension", None)
    if callable(enable):
        try:
            enable(False)
        except sqlite3.Error:
            return


def _execute_bounded_query(conn: Any, query: str, max_rows: int, fetch_until_complete: bool) -> tuple[list[str], list[dict[str, object]]]:
    cursor = conn.execute(query)
    columns = [str(item[0]) for item in (cursor.description or [])]
    raw_rows = cursor.fetchall() if fetch_until_complete else cursor.fetchmany(max_rows + 1)
    if len(raw_rows) > max_rows:
        raise sqlite3.OperationalError(f"SQL query returned more than {max_rows} rows.")
    return columns, [_row_to_dict(row, columns) for row in raw_rows]


def _uses_recursive_cte(query: str) -> bool:
    tokens = _sql_tokens(query)
    return len(tokens) >= 2 and tokens[0] == "with" and tokens[1] == "recursive"


def _row_to_dict(row: Any, columns: Sequence[str]) -> dict[str, object]:
    return {column: _serialize_cell(row[column]) for column in columns}


def _evaluate_test_cases(
    test_cases: Sequence[Mapping[str, object]],
    actual_columns: Sequence[str],
    actual_rows: Sequence[Mapping[str, object]],
    comparison: str,
) -> list[SqlTestCaseResult]:
    results: list[SqlTestCaseResult] = []
    for index, case in enumerate(test_cases):
        started = time.perf_counter()
        expected = _expected_result(case)
        passed, message = _compare_expected(actual_columns, actual_rows, expected, comparison)
        results.append(
            SqlTestCaseResult(
                case_id=str(case.get("id") or f"case_{index + 1}"),
                case_type=str(case.get("case_type", "visible")),
                passed=passed,
                weight=_float_or_default(case.get("weight"), 1.0),
                is_critical=bool(case.get("is_critical", False)),
                message=message,
                duration_ms=_elapsed_ms(started),
            ),
        )
    return results


def _expected_result(case: Mapping[str, object]) -> tuple[list[str], list[dict[str, object]]]:
    expected_output = case.get("expected_output_json", {})
    if not isinstance(expected_output, Mapping):
        expected_output = {}

    raw_columns = expected_output.get("columns", [])
    columns = [str(column) for column in raw_columns] if isinstance(raw_columns, Sequence) and not isinstance(raw_columns, str) else []

    rows: list[dict[str, object]] = []
    raw_rows = expected_output.get("rows", [])
    if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, str):
        for row in raw_rows:
            if isinstance(row, Mapping):
                rows.append({str(key): _serialize_cell(value) for key, value in row.items()})
    return columns, rows


def _compare_expected(
    actual_columns: Sequence[str],
    actual_rows: Sequence[Mapping[str, object]],
    expected: tuple[Sequence[str], Sequence[Mapping[str, object]]],
    comparison: str,
) -> tuple[bool, str]:
    expected_columns, expected_rows = expected
    if list(expected_columns) != list(actual_columns):
        return False, f"Expected columns {list(expected_columns)}, got {list(actual_columns)}."

    if comparison == "unordered":
        passed = _unordered_rows(actual_rows) == _unordered_rows(expected_rows)
    else:
        passed = [dict(row) for row in actual_rows] == [dict(row) for row in expected_rows]

    if passed:
        return True, "SQL result matched expected rows."
    return False, "Expected rows did not match query result."


def _unordered_rows(rows: Sequence[Mapping[str, object]]) -> list[str]:
    return sorted(str(sorted(row.items())) for row in rows)


def _failed_test_results(test_cases: Sequence[Mapping[str, object]], message: str) -> list[SqlTestCaseResult]:
    results: list[SqlTestCaseResult] = []
    for index, case in enumerate(test_cases):
        results.append(
            SqlTestCaseResult(
                case_id=str(case.get("id") or f"case_{index + 1}"),
                case_type=str(case.get("case_type", "visible")),
                passed=False,
                weight=_float_or_default(case.get("weight"), 1.0),
                is_critical=bool(case.get("is_critical", False)),
                message=message,
                duration_ms=0,
            ),
        )
    return results


def _serialize_cell(value: object) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, bytes):
        return "<bytes>"
    return _bound_text(str(value), MAX_SQL_CELL_CHARS)


def _row_count_stdout(row_count: int) -> str:
    return "1 row" if row_count == 1 else f"{row_count} rows"


def _int_in_range(value: object, default: int, lower: int, upper: int) -> int:
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(parsed, upper))


def _float_or_default(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _bound_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
