"""Finite Python goal evidence for the protected adapter; never execute code."""
from __future__ import annotations

import ast

GOAL_CONTRACT_ID = "python-assignment-sum-print-v1"
_ALLOWED_PROGRAMS = frozenset(
    ast.dump(ast.parse(source), include_attributes=False)
    for source in (
        "numbers = [3, -1, 0, 3]\nprint(sum(numbers))",
        "numbers = [3, -1, 0, 3]\ntotal = sum(numbers)\nprint(total)",
    )
)


def normalize_goal_contract(value: object = None) -> str | None:
    """Missing/null/empty is legacy; any other unknown declaration fails closed."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value != GOAL_CONTRACT_ID:
        raise ValueError("python_goal_contract_invalid")
    return value


def python_goal_satisfied(code: str) -> bool:
    """Match the whole program, not reachable-looking snippets or output alone.

    Only assignment to the fixed literal list followed by sum/print, optionally
    through a single ``total`` assignment, is supported. AST comparison ignores
    whitespace/comments but rejects other statements, names, calls and literals.
    This static fact is not a score or a substitute for terminal stdout evidence.
    """
    try:
        tree = ast.parse(code)
        return ast.dump(tree, include_attributes=False) in _ALLOWED_PROGRAMS
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False
