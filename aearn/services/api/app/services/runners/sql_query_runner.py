from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from aearn_shared.execution import (
    SafeExecutionPresentationNoneV1,
    SafeExecutionPresentationV1,
    SafeExecutionResultV2,
    SafeExecutionStatus,
    SafeTableResultCellV1,
    SafeTableResultPresentationV1,
    SafeTestFeedbackV2,
    contains_protected_execution_text,
)

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
HARD_SQL_MAX_COLUMNS = 32
_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_UNSAFE_SQL_FUNCTIONS = frozenset({"edit", "load_extension", "readfile", "writefile"})
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
_SQLITE_LIMITS = (
    ("SQLITE_LIMIT_ATTACHED", 0),
    ("SQLITE_LIMIT_COLUMN", 64),
    ("SQLITE_LIMIT_COMPOUND_SELECT", 16),
    ("SQLITE_LIMIT_EXPR_DEPTH", 100),
    ("SQLITE_LIMIT_FUNCTION_ARG", 32),
    ("SQLITE_LIMIT_LENGTH", 131_072),
    ("SQLITE_LIMIT_LIKE_PATTERN_LENGTH", 1_024),
    ("SQLITE_LIMIT_SQL_LENGTH", 48_000),
    ("SQLITE_LIMIT_VARIABLE_NUMBER", 256),
    ("SQLITE_LIMIT_VDBE_OP", 100_000),
)


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
    columns: list[str] = field(default_factory=list)
    rows: list[list[SafeTableResultCellV1]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SqlRunnerOptions:
    dialect: str
    setup_sql: tuple[str, ...]
    comparison: str
    max_rows: int


@dataclass(frozen=True, slots=True)
class SqlColumnSpec:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True, slots=True)
class SqlForeignKeySpec:
    column: str
    references_table: str
    references_column: str


@dataclass(frozen=True, slots=True)
class SqlTableSpec:
    name: str
    columns: tuple[SqlColumnSpec, ...]
    foreign_keys: tuple[SqlForeignKeySpec, ...]


SqlDatasetRows = dict[str, tuple[tuple[SafeTableResultCellV1, ...], ...]]


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
        _apply_sqlite_limits(conn)
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
        columns=list(columns),
        rows=[[row.get(column) for column in columns] for row in rows],
    )


def execute_sql_workspace_query(
    query: str,
    test_cases: Sequence[Mapping[str, object]],
    *,
    schema: Sequence[Mapping[str, object]],
    public_dataset: Mapping[str, object],
    comparison: str = "ordered",
    max_rows: int = DEFAULT_SQL_MAX_ROWS,
    timeout_s: float = 5.0,
) -> SqlExecutionResult:
    """Execute one public dataset and independently score bounded private datasets."""

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
    normalized_comparison = comparison.casefold()
    if normalized_comparison not in {"ordered", "unordered"}:
        normalized_comparison = "ordered"
    bounded_rows = max(1, min(int(max_rows), HARD_SQL_MAX_ROWS))
    deadline = time.perf_counter() + max(timeout_s, 0.001)
    try:
        columns, public_rows = _execute_structured_dataset(
            query,
            schema=schema,
            dataset=public_dataset,
            max_rows=bounded_rows,
            deadline=deadline,
        )
    except TimeoutError:
        return SqlExecutionResult(
            status="timeout",
            stdout="",
            stderr="",
            error="SQL query timed out.",
            test_results=_failed_test_results(test_cases, "SQL query timed out."),
            total_duration_ms=_elapsed_ms(start),
        )
    except (TypeError, ValueError, sqlite3.DatabaseError) as exc:
        return SqlExecutionResult(
            status="runtime_error",
            stdout="",
            stderr="",
            error=_bound_text(f"SQL query failed: {exc}", MAX_SQL_ERROR_CHARS),
            test_results=_failed_test_results(test_cases, "SQL query failed."),
            total_duration_ms=_elapsed_ms(start),
        )

    results: list[SqlTestCaseResult] = []
    for index, case in enumerate(test_cases):
        started = time.perf_counter()
        dataset = case.get("dataset")
        if not isinstance(dataset, Mapping):
            results.append(
                SqlTestCaseResult(
                    case_id=str(case.get("id") or f"case_{index + 1}"),
                    case_type=str(case.get("case_type", "visible")),
                    passed=False,
                    weight=_float_or_default(case.get("weight"), 1.0),
                    is_critical=bool(case.get("is_critical", False)),
                    message="SQL test dataset is unavailable.",
                    duration_ms=_elapsed_ms(started),
                )
            )
            continue
        try:
            actual_columns, actual_rows = _execute_structured_dataset(
                query,
                schema=schema,
                dataset=dataset,
                max_rows=HARD_SQL_MAX_ROWS,
                deadline=deadline,
            )
            passed, message = _compare_expected(
                actual_columns,
                actual_rows,
                _expected_result(case),
                normalized_comparison,
            )
        except TimeoutError:
            return SqlExecutionResult(
                status="timeout",
                stdout="",
                stderr="",
                error="SQL query timed out.",
                test_results=_failed_test_results(test_cases, "SQL query timed out."),
                total_duration_ms=_elapsed_ms(start),
            )
        except (TypeError, ValueError, sqlite3.DatabaseError):
            passed = False
            message = "SQL query did not satisfy this dataset."
        results.append(
            SqlTestCaseResult(
                case_id=str(case.get("id") or f"case_{index + 1}"),
                case_type=str(case.get("case_type", "visible")),
                passed=passed,
                weight=_float_or_default(case.get("weight"), 1.0),
                is_critical=bool(case.get("is_critical", False)),
                message=message,
                duration_ms=_elapsed_ms(started),
            )
        )
    return SqlExecutionResult(
        status="success",
        stdout=_row_count_stdout(len(public_rows)),
        stderr="",
        error=None,
        test_results=results,
        total_duration_ms=_elapsed_ms(start),
        columns=list(columns),
        rows=[[row.get(column) for column in columns] for row in public_rows],
    )


def sql_execution_result_to_safe_result(
    result: SqlExecutionResult,
) -> SafeExecutionResultV2:
    """Convert a SQL runner result into the strict learner-visible v2 authority."""

    status = {
        "success": SafeExecutionStatus.SUCCESS,
        "timeout": SafeExecutionStatus.TIMEOUT,
        "missing_toolchain": SafeExecutionStatus.UNAVAILABLE,
        "unsupported": SafeExecutionStatus.UNSUPPORTED,
    }.get(result.status, SafeExecutionStatus.RUNTIME_ERROR)
    hidden_ordinal = 0
    feedback: list[SafeTestFeedbackV2] = []
    for index, item in enumerate(result.test_results, start=1):
        visible = item.case_type != "hidden"
        if visible:
            candidate_id = item.case_id or f"visible-{index}"
            case_id = (
                f"visible-{index}"
                if contains_protected_execution_text(candidate_id)
                else candidate_id
            )
            message = (
                "SQL result matched the visible expectation."
                if item.passed
                else "SQL result did not match the visible expectation."
            )
        else:
            hidden_ordinal += 1
            case_id = f"non-visible-{hidden_ordinal}"
            message = (
                "A non-visible scenario passed."
                if item.passed
                else "A non-visible scenario still failed."
            )
        feedback.append(
            SafeTestFeedbackV2(
                case_id=case_id,
                passed=item.passed,
                visible=visible,
                message=message,
                duration_ms=max(0, item.duration_ms),
            )
        )
    passed_count = sum(1 for item in result.test_results if item.passed)
    presentation: SafeExecutionPresentationV1 = SafeExecutionPresentationNoneV1()
    if status is SafeExecutionStatus.SUCCESS and result.columns:
        presentation = SafeTableResultPresentationV1(
            columns=tuple(result.columns),
            rows=tuple(tuple(row) for row in result.rows),
        )
    diagnostic = {
        SafeExecutionStatus.SUCCESS: (
            "sql_query_passed"
            if passed_count == len(result.test_results)
            else "sql_test_failure"
        ),
        SafeExecutionStatus.TIMEOUT: "sql_query_timeout",
        SafeExecutionStatus.UNAVAILABLE: "sql_runtime_unavailable",
        SafeExecutionStatus.UNSUPPORTED: "sql_runtime_unsupported",
        SafeExecutionStatus.RUNTIME_ERROR: "sql_query_runtime_error",
    }[status]
    return SafeExecutionResultV2(
        schema_version="safe-execution-result-v2",
        status=status,
        stdout=result.stdout if status is SafeExecutionStatus.SUCCESS else "",
        stderr=(
            "SQL query could not be executed."
            if status is SafeExecutionStatus.RUNTIME_ERROR
            else ""
        ),
        test_feedback=tuple(feedback),
        passed_test_count=passed_count,
        total_test_count=len(result.test_results),
        duration_ms=max(0, result.total_duration_ms),
        diagnostic_code=diagnostic,
        presentation=presentation,
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


def _apply_sqlite_limits(conn: Any) -> None:
    setlimit = getattr(conn, "setlimit", None)
    if not callable(setlimit):
        return
    for constant_name, limit in _SQLITE_LIMITS:
        category = getattr(sqlite3, constant_name, None)
        if not isinstance(category, int):
            continue
        try:
            setlimit(category, limit)
        except sqlite3.Error:
            continue


def _disable_extension_loading(conn: Any) -> None:
    enable = getattr(conn, "enable_load_extension", None)
    if callable(enable):
        try:
            enable(False)
        except sqlite3.Error:
            return


def _execute_structured_dataset(
    query: str,
    *,
    schema: Sequence[Mapping[str, object]],
    dataset: Mapping[str, object],
    max_rows: int,
    deadline: float,
) -> tuple[list[str], list[dict[str, SafeTableResultCellV1]]]:
    schema_rows = _parse_structured_schema(schema)
    data_rows = _parse_structured_dataset(dataset, schema_rows)
    conn = sqlite3.connect(":memory:")
    timed_out = False

    def progress_handler() -> int:
        nonlocal timed_out
        if time.perf_counter() >= deadline:
            timed_out = True
            return 1
        return 0

    try:
        conn.row_factory = sqlite3.Row
        _apply_sqlite_limits(conn)
        _disable_extension_loading(conn)
        for table in schema_rows:
            conn.execute(_create_table_sql(table))
        for table in schema_rows:
            rows = data_rows[table.name]
            if not rows:
                continue
            columns = tuple(column.name for column in table.columns)
            placeholders = ",".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO {_quote_identifier(table.name)} "
                f"({','.join(_quote_identifier(column) for column in columns)}) "
                f"VALUES ({placeholders})",
                rows,
            )
        conn.commit()
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("SQL dataset violates its published foreign keys")
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(
            _sqlite_authorizer_for(frozenset(table.name for table in schema_rows))
        )
        conn.set_progress_handler(progress_handler, 1000)
        return _execute_bounded_query(conn, query, max_rows, False)
    except sqlite3.OperationalError as exc:
        if timed_out or "interrupted" in str(exc).casefold():
            raise TimeoutError("SQL query timed out") from exc
        raise
    finally:
        conn.close()


def _parse_structured_schema(
    schema: Sequence[Mapping[str, object]],
) -> tuple[SqlTableSpec, ...]:
    if not isinstance(schema, Sequence) or isinstance(schema, (str, bytes, bytearray)):
        raise ValueError("SQL schema must be a sequence")
    if not 1 <= len(schema) <= 8:
        raise ValueError("SQL schema table count is invalid")
    parsed: list[SqlTableSpec] = []
    names: set[str] = set()
    for raw_table in schema:
        if not isinstance(raw_table, Mapping) or set(raw_table) != {"name", "columns", "foreign_keys"}:
            raise ValueError("SQL schema table shape is invalid")
        name = _sql_identifier(raw_table.get("name"), "table")
        if name in names:
            raise ValueError("SQL schema table names must be unique")
        names.add(name)
        raw_columns = raw_table.get("columns")
        if not isinstance(raw_columns, Sequence) or isinstance(raw_columns, (str, bytes, bytearray)) or not 1 <= len(raw_columns) <= HARD_SQL_MAX_COLUMNS:
            raise ValueError("SQL schema columns are invalid")
        columns: list[SqlColumnSpec] = []
        column_names: set[str] = set()
        for raw_column in raw_columns:
            if not isinstance(raw_column, Mapping) or set(raw_column) != {"name", "data_type", "nullable", "primary_key"}:
                raise ValueError("SQL schema column shape is invalid")
            column_name = _sql_identifier(raw_column.get("name"), "column")
            data_type = str(raw_column.get("data_type") or "")
            nullable = raw_column.get("nullable")
            primary_key = raw_column.get("primary_key")
            if column_name in column_names or data_type not in {"INTEGER", "REAL", "TEXT"} or not isinstance(nullable, bool) or not isinstance(primary_key, bool) or (primary_key and nullable):
                raise ValueError("SQL schema column contract is invalid")
            column_names.add(column_name)
            columns.append(
                SqlColumnSpec(
                    name=column_name,
                    data_type=data_type,
                    nullable=nullable,
                    primary_key=primary_key,
                )
            )
        raw_foreign_keys = raw_table.get("foreign_keys")
        if not isinstance(raw_foreign_keys, Sequence) or isinstance(raw_foreign_keys, (str, bytes, bytearray)) or len(raw_foreign_keys) > 16:
            raise ValueError("SQL schema foreign keys are invalid")
        foreign_keys: list[SqlForeignKeySpec] = []
        for raw_foreign_key in raw_foreign_keys:
            if not isinstance(raw_foreign_key, Mapping) or set(raw_foreign_key) != {"column", "references_table", "references_column"}:
                raise ValueError("SQL schema foreign-key shape is invalid")
            foreign_key = SqlForeignKeySpec(
                column=_sql_identifier(raw_foreign_key.get("column"), "foreign-key column"),
                references_table=_sql_identifier(raw_foreign_key.get("references_table"), "referenced table"),
                references_column=_sql_identifier(raw_foreign_key.get("references_column"), "referenced column"),
            )
            if foreign_key.column not in column_names:
                raise ValueError("SQL foreign key references an unknown local column")
            foreign_keys.append(foreign_key)
        parsed.append(
            SqlTableSpec(
                name=name,
                columns=tuple(columns),
                foreign_keys=tuple(foreign_keys),
            )
        )
    by_name = {table.name: table for table in parsed}
    for table in parsed:
        columns_by_name = {column.name: column for column in table.columns}
        for foreign_key in table.foreign_keys:
            target = by_name.get(foreign_key.references_table)
            target_columns = (
                {column.name: column for column in target.columns}
                if target is not None
                else {}
            )
            target_column = target_columns.get(foreign_key.references_column)
            target_primary = (
                tuple(column.name for column in target.columns if column.primary_key)
                if target is not None
                else ()
            )
            source_column = columns_by_name[foreign_key.column]
            if (
                target_column is None
                or target_primary != (foreign_key.references_column,)
                or source_column.data_type != target_column.data_type
            ):
                raise ValueError(
                    "SQL foreign key must reference one matching published primary key"
                )
    return tuple(parsed)


def _parse_structured_dataset(
    dataset: Mapping[str, object],
    schema: Sequence[SqlTableSpec],
) -> SqlDatasetRows:
    if set(dataset) != {"tables"}:
        raise ValueError("SQL dataset shape is invalid")
    raw_tables = dataset.get("tables")
    if not isinstance(raw_tables, Sequence) or isinstance(raw_tables, (str, bytes, bytearray)):
        raise ValueError("SQL dataset tables are invalid")
    schema_by_name = {table.name: table for table in schema}
    parsed: SqlDatasetRows = {}
    for raw_table in raw_tables:
        if not isinstance(raw_table, Mapping) or set(raw_table) != {"table", "rows"}:
            raise ValueError("SQL dataset table shape is invalid")
        name = _sql_identifier(raw_table.get("table"), "dataset table")
        table = schema_by_name.get(name)
        if table is None or name in parsed:
            raise ValueError("SQL dataset table identity is invalid")
        raw_rows = raw_table.get("rows")
        if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes, bytearray)) or len(raw_rows) > HARD_SQL_MAX_ROWS:
            raise ValueError("SQL dataset rows are invalid")
        rows: list[tuple[SafeTableResultCellV1, ...]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes, bytearray)) or len(raw_row) != len(table.columns):
                raise ValueError("SQL dataset row width is invalid")
            row = tuple(
                _structured_cell(value, table.columns[index])
                for index, value in enumerate(raw_row)
            )
            rows.append(row)
        SafeTableResultPresentationV1(
            columns=tuple(column.name for column in table.columns),
            rows=tuple(rows),
        )
        parsed[name] = tuple(rows)
    if set(parsed) != set(schema_by_name):
        raise ValueError("SQL dataset must include every published table")
    return parsed


def _structured_cell(
    value: object,
    column: SqlColumnSpec,
) -> SafeTableResultCellV1:
    if value is None:
        if column.nullable and not column.primary_key:
            return None
        raise ValueError("SQL dataset nullability is invalid")
    if column.data_type == "TEXT" and isinstance(value, str):
        return _serialize_cell(value)
    if column.data_type == "INTEGER" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if column.data_type == "REAL" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ValueError("SQL dataset cell type is invalid")


def _create_table_sql(table: SqlTableSpec) -> str:
    definitions = [
        " ".join(
            part
            for part in (
                _quote_identifier(column.name),
                column.data_type,
                "NOT NULL" if not column.nullable else "",
            )
            if part
        )
        for column in table.columns
    ]
    primary = [column.name for column in table.columns if column.primary_key]
    if primary:
        definitions.append(
            f"PRIMARY KEY ({','.join(_quote_identifier(name) for name in primary)})"
        )
    definitions.extend(
        f"FOREIGN KEY ({_quote_identifier(foreign_key.column)}) REFERENCES "
        f"{_quote_identifier(foreign_key.references_table)}"
        f"({_quote_identifier(foreign_key.references_column)})"
        for foreign_key in table.foreign_keys
    )
    return f"CREATE TABLE {_quote_identifier(table.name)} ({','.join(definitions)})"


def _sqlite_authorizer_for(allowed_tables: frozenset[str]):
    def authorize(action_code: int, arg1: str | None, arg2: str | None, db_name: str | None, source: str | None) -> int:
        del db_name, source
        ok = int(getattr(sqlite3, "SQLITE_OK", 0))
        deny = int(getattr(sqlite3, "SQLITE_DENY", 1))
        if action_code == getattr(sqlite3, "SQLITE_READ", None):
            return ok if str(arg1 or "") in allowed_tables else deny
        if action_code in {
            getattr(sqlite3, "SQLITE_SELECT", None),
            getattr(sqlite3, "SQLITE_RECURSIVE", None),
        }:
            return ok
        if action_code == getattr(sqlite3, "SQLITE_FUNCTION", None):
            return deny if str(arg2 or "").casefold() in _UNSAFE_SQL_FUNCTIONS else ok
        return deny

    return authorize


def _sql_identifier(value: object, label: str) -> str:
    normalized = str(value or "")
    if not _SQL_IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"SQL {label} identifier is invalid")
    return normalized


def _quote_identifier(value: str) -> str:
    return f'"{value}"'


def _execute_bounded_query(conn: Any, query: str, max_rows: int, fetch_until_complete: bool) -> tuple[list[str], list[dict[str, SafeTableResultCellV1]]]:
    cursor = conn.execute(query)
    columns = [str(item[0]) for item in (cursor.description or [])]
    if not columns or len(columns) > HARD_SQL_MAX_COLUMNS or len(columns) != len(set(columns)):
        raise sqlite3.OperationalError("SQL query columns exceed the learner-safe bounds.")
    raw_rows = cursor.fetchall() if fetch_until_complete else cursor.fetchmany(max_rows + 1)
    if len(raw_rows) > max_rows:
        raise sqlite3.OperationalError(f"SQL query returned more than {max_rows} rows.")
    rows = [_row_to_dict(row, columns) for row in raw_rows]
    try:
        SafeTableResultPresentationV1(
            columns=tuple(columns),
            rows=tuple(tuple(row.get(column) for column in columns) for row in rows),
        )
    except (TypeError, ValueError) as exc:
        raise sqlite3.OperationalError(
            "SQL query result exceeds the learner-safe bounds."
        ) from exc
    return columns, rows


def _uses_recursive_cte(query: str) -> bool:
    tokens = _sql_tokens(query)
    return len(tokens) >= 2 and tokens[0] == "with" and tokens[1] == "recursive"


def _row_to_dict(row: Any, columns: Sequence[str]) -> dict[str, SafeTableResultCellV1]:
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
    expected_output = case.get("expected_output", case.get("expected_output_json", {}))
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
            elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)) and len(row) == len(columns):
                rows.append({column: _serialize_cell(value) for column, value in zip(columns, row, strict=True)})
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


def _serialize_cell(value: object) -> SafeTableResultCellV1:
    if value is None or isinstance(value, (bool, int, float)):
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
