#!/usr/bin/env python3
"""Fixed P6 in-image facts adapter, stdlib only. Never invoke this on a host.

It evaluates no learning score. Expected answers are kept in the API scorer,
not sent to candidate children. Every case gets a fresh subprocess/SQLite DB.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any

from python_goal import normalize_goal_contract, python_goal_satisfied
from python_state_goal import inspect_python_state_goal, normalize_python_state_contract

MAX_INPUT = 98_304
MAX_CASES = 48
MAX_OUTPUT = 16_384
MEMORY = 96 * 1024 * 1024
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _protect_parent() -> bool:
    """Reinstall protection after adapter exec; never trust inherited state."""
    if sys.platform != "linux" or os.getuid() != 10001:
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.restype = ctypes.c_int
        return libc.prctl(4, ctypes.c_long(0), ctypes.c_long(0), ctypes.c_long(0), ctypes.c_long(0)) == 0
    except (OSError, AttributeError):
        return False


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _goal_contract(value: object) -> str | dict[str, Any] | None:
    if isinstance(value, dict):
        return normalize_python_state_contract(value)
    return normalize_goal_contract(value)


def _python(code: str, case: dict[str, Any]) -> dict[str, Any]:
    # Compute only in the protected parent, from the actual submitted program.
    contract = _goal_contract(case.get("goal_contract"))
    if isinstance(contract, dict):
        goal_facts = inspect_python_state_goal(code, contract)
        fact = _python_terminal(code, case)
        fact.update(goal_facts)
        return fact
    static_goal = python_goal_satisfied(code) if contract is not None else False
    fact = _python_terminal(code, case)
    if contract is not None:
        fact["goal_contract_id"] = contract
        fact["goal_satisfied"] = static_goal and fact["status"] == "success"
    return fact


def _python_terminal(code: str, case: dict[str, Any]) -> dict[str, Any]:
    # The fixed child reads only code, never expected output or other cases.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", "import sys; exec(compile(sys.stdin.read(), '<submission>', 'exec'))"],
                input=code.encode(), stdout=out, stderr=err, cwd="/work",
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
                timeout=2, check=False, preexec_fn=_limits,
            )
        except subprocess.TimeoutExpired:
            return {"id": case["id"], "status": "timeout", "code": "time_limit"}
        out.seek(0)
        err.seek(0)
        stdout = out.read(MAX_OUTPUT + 1)
        stderr = err.read(MAX_OUTPUT + 1)
        if len(stdout) >= MAX_OUTPUT or len(stderr) >= MAX_OUTPUT:
            return {"id": case["id"], "status": "failed", "code": "output_limit"}
        if b"MemoryError" in stderr:
            return {"id": case["id"], "status": "failed", "code": "memory_limit"}
        return {
            "id": case["id"], "status": "success" if proc.returncode == 0 else "runtime_error",
            "code": "python_terminal", "stdout": stdout.decode("utf-8", errors="replace"),
        }


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError("sql_identifier_invalid")
    return '"' + value + '"'


def _sql(query: str, case: dict[str, Any]) -> dict[str, Any]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.enable_load_extension(False)
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 128 * 1024 * 1024)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 48_000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 64)
        tables = case["tables"]
        dataset = case["dataset"]["tables"]
        if not isinstance(tables, list) or not 1 <= len(tables) <= 8 or not isinstance(dataset, list) or len(dataset) > 8:
            raise ValueError("sql_setup_bound")
        schema: dict[str, list[dict[str, Any]]] = {}
        for table in tables:
            columns = table["columns"]
            if not isinstance(columns, list) or not 1 <= len(columns) <= 32:
                raise ValueError("sql_setup_bound")
            definitions = []
            for column in columns:
                dtype = column["data_type"]
                if dtype not in {"INTEGER", "REAL", "TEXT"}:
                    raise ValueError("sql_type_invalid")
                definition = _identifier(column["name"]) + " " + dtype
                if not column.get("nullable", True):
                    definition += " NOT NULL"
                if column.get("primary_key", False):
                    definition += " PRIMARY KEY"
                definitions.append(definition)
            foreign_keys = table.get("foreign_keys", [])
            if len(foreign_keys) > 16:
                raise ValueError("sql_setup_bound")
            for foreign in foreign_keys:
                definitions.append(
                    "FOREIGN KEY(" + _identifier(foreign["column"]) + ") REFERENCES "
                    + _identifier(foreign["references_table"]) + "(" + _identifier(foreign["references_column"]) + ")"
                )
            conn.execute("CREATE TABLE " + _identifier(table["name"]) + "(" + ",".join(definitions) + ")")
            schema[table["name"]] = columns
        conn.execute("PRAGMA foreign_keys=ON")
        total_rows = 0
        for table in dataset:
            columns = schema[table["table"]]
            rows = table["rows"]
            total_rows += len(rows)
            if total_rows > 256:
                raise ValueError("sql_setup_bound")
            for row in rows:
                if len(row) != len(columns) or any(not (cell is None or type(cell) in (int, float, str)) for cell in row):
                    raise ValueError("sql_row_invalid")
                if any(isinstance(cell, str) and len(cell) > 512 for cell in row):
                    raise ValueError("sql_cell_bound")
            conn.executemany("INSERT INTO " + _identifier(table["table"]) + " VALUES (" + ",".join("?" for _ in columns) + ")", rows)
        conn.commit()
        conn.execute("PRAGMA query_only=ON")
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        def authorize(action: int, arg1: str | None, arg2: str | None, db: str | None, source: str | None) -> int:
            if action not in allowed or (action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() in {"load_extension", "readfile", "writefile"}):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
        deadline = time.monotonic() + 2
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        cursor = conn.execute(query)
        columns_out = [column[0] for column in cursor.description or ()]
        max_rows = case.get("max_rows", 50)
        if type(max_rows) is not int or not 1 <= max_rows <= 200:
            raise ValueError("sql_row_bound")
        rows_out = cursor.fetchmany(max_rows + 1)
        if len(rows_out) > max_rows:
            return {"id": case["id"], "status": "failed", "code": "output_limit"}
        return {"id": case["id"], "status": "success", "code": "sqlite_terminal", "columns": columns_out, "rows": rows_out}
    except MemoryError:
        return {"id": case["id"], "status": "failed", "code": "memory_limit"}
    except sqlite3.Error as exc:
        code = "time_limit" if "interrupted" in str(exc) else "memory_limit" if "memory" in str(exc) else "sql_rejected"
        return {"id": case["id"], "status": "timeout" if code == "time_limit" else "runtime_error", "code": code}
    except (ValueError, KeyError, TypeError):
        return {"id": case.get("id", "invalid"), "status": "failed", "code": "sql_setup_invalid"}
    finally:
        conn.close()


def main() -> int:
    if not _protect_parent():
        return _emit("failed", "runtime_parent_protection_unavailable")
    # Explicit in-image guard: no supported host runner fallback.
    if os.getuid() != 10001 or os.environ.get("AEARN_RUNTIME_ID") not in {"python-stdout-v1", "sqlite-query-v1"}:
        return _emit("unavailable", "runtime_boundary_missing")
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("input_bound")
        request = json.loads(raw)
        if set(request) - {"schema_version", "runtime_id", "action", "submission", "visible_test_bundle_json", "hidden_test_bundle_json", "source_reference_hash", "test_reference_hash"}:
            raise ValueError("input_extra")
        if request["schema_version"] != "sandbox-input-v1" or request["runtime_id"] != os.environ["AEARN_RUNTIME_ID"] or request["action"] != "test":
            raise ValueError("input_protocol")
        code = request["submission"]
        if not isinstance(code, str) or not 0 < len(code) <= 48_000:
            raise ValueError("submission_bound")
        visible = json.loads(request["visible_test_bundle_json"])
        hidden = json.loads(request["hidden_test_bundle_json"])
        cases = visible + hidden
        if not isinstance(visible, list) or not isinstance(hidden, list) or not 1 <= len(cases) <= MAX_CASES:
            raise ValueError("cases_bound")
        if len({case["id"] for case in cases}) != len(cases):
            raise ValueError("case_duplicate")
        # Validate every declaration before any child execution, including SQL.
        for case in cases:
            contract = _goal_contract(case.get("goal_contract"))
            if contract is not None and request["runtime_id"] != "python-stdout-v1":
                raise ValueError("goal_runtime_invalid")
        started = time.monotonic()
        if request["runtime_id"] == "sqlite-query-v1":
            _limits()
        facts = [_python(code, case) if request["runtime_id"] == "python-stdout-v1" else _sql(code, case) for case in cases]
        body = json.dumps({"cases": facts}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        result = {"schema_version": "sandbox-result-v1", "status": "success", "stdout": body, "stderr": "", "test_feedback": [], "passed_test_count": 0, "total_test_count": 0, "duration_ms": min(120000, int((time.monotonic() - started) * 1000)), "diagnostic_code": "item_supply_facts_v1"}
        wire = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(wire.encode()) > MAX_OUTPUT:
            return _emit("failed", "output_limit")
        sys.stdout.write(wire)
        return 0
    except (ValueError, TypeError, KeyError, UnicodeError, OSError):
        return _emit("failed", "sandbox_protocol_invalid")


def _emit(status: str, code: str) -> int:
    sys.stdout.write(json.dumps({"schema_version": "sandbox-result-v1", "status": status, "stdout": "", "stderr": "", "test_feedback": [], "passed_test_count": 0, "total_test_count": 0, "duration_ms": 0, "diagnostic_code": code}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
