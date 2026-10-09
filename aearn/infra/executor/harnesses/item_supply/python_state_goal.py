"""Closed public-task AST facts for the protected parent; never execute a program.

This module contains role/dependency rules, NOT private answers or fixture values.
A fact is not a grade. The API must verify the actual terminal seal and stdout.
"""
from __future__ import annotations

import ast
import hashlib
import json
import keyword
import re
from typing import Any, Literal, TypedDict

GOAL_CONTRACT_ID = "python-state-update-v1"
GRAMMAR_VERSION = "python-state-ast-v1"
MAX_SOURCE_BYTES = 8192
MAX_AST_NODES = 256
MAX_STATEMENTS = 12
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
# Only role names, never private current/future item fixtures.
_ROLES = {
    "accumulate": ({"total", "increase", "decrease"}, {"initial", "increase", "decrease"}),
    "refresh": ({"price", "qty", "subtotal", "saved"}, {"price", "initial_qty", "updated_qty"}),
    "swap": ({"left", "right", "saved"}, {"left", "right"}),
    "transfer": ({"source", "target", "amount", "total"}, {"source", "target", "amount"}),
}


class GoalFacts(TypedDict):
    goal_contract_id: str
    goal_contract_hash: str
    goal_status: Literal["satisfied", "unsatisfied", "unsupported"]
    goal_satisfied: bool | None


class _Unsupported(ValueError):
    pass


def normalize_python_state_contract(value: object) -> dict[str, Any]:
    """Strict public-only wire; unknown/extra declarations are protocol errors."""
    if not isinstance(value, dict) or set(value) != {"goal_contract_id", "task_kind", "variables", "values"}:
        raise ValueError("python_state_contract_invalid")
    kind = value["task_kind"]
    if value["goal_contract_id"] != GOAL_CONTRACT_ID or not isinstance(kind, str) or kind not in _ROLES:
        raise ValueError("python_state_contract_invalid")
    names, values = value["variables"], value["values"]
    role_keys, value_keys = _ROLES[kind]
    if not isinstance(names, dict) or set(names) != role_keys or not isinstance(values, dict) or set(values) != value_keys:
        raise ValueError("python_state_contract_invalid")
    if any(not isinstance(name, str) or not _IDENTIFIER.fullmatch(name)
           or keyword.iskeyword(name) or name == "print" for name in names.values()):
        raise ValueError("python_state_variable_invalid")
    if len(set(names.values())) != len(names):
        raise ValueError("python_state_variable_alias")
    if any(type(number) is not int or abs(number) > 1000 for number in values.values()):
        raise ValueError("python_state_value_invalid")
    if kind == "transfer" and not (0 <= values["amount"] <= values["source"] and values["target"] >= 0):
        raise ValueError("python_state_transfer_invalid")
    return {"goal_contract_id": GOAL_CONTRACT_ID, "task_kind": kind,
            "variables": dict(names), "values": dict(values)}


def _name(role: str) -> tuple[str, str]:
    return ("role", role)


def _literal(value: int) -> tuple[str, int]:
    return ("integer", value)


def _binary(op: str, left: tuple[Any, ...], right: tuple[Any, ...]) -> tuple[Any, ...]:
    # Only exact commutativity of one Add/Mult node; no algebraic simplifier.
    if op in {"add", "multiply"}:
        left, right = sorted((left, right), key=repr)
    return (op, left, right)


def _set(role: str, expression: tuple[Any, ...]) -> tuple[Any, ...]:
    return ("set", role, expression)


def _output(*expressions: tuple[Any, ...]) -> tuple[Any, ...]:
    return ("print", *expressions)


def _role(node: ast.AST, inverse: dict[str, str]) -> str:
    if not isinstance(node, ast.Name) or node.id not in inverse:
        raise _Unsupported("unknown_variable")
    return inverse[node.id]


def _atom(node: ast.AST, inverse: dict[str, str]) -> tuple[Any, ...]:
    if isinstance(node, ast.Name):
        return _name(_role(node, inverse))
    if isinstance(node, ast.Constant) and type(node.value) is int and abs(node.value) <= 1000:
        return _literal(node.value)
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
            and abs(node.operand.value) <= 1000):
        return _literal(-node.operand.value if isinstance(node.op, ast.USub) else node.operand.value)
    raise _Unsupported("expression_outside_finite_grammar")


def _expression(node: ast.AST, inverse: dict[str, str]) -> tuple[Any, ...]:
    if isinstance(node, ast.BinOp):
        operations = {ast.Add: "add", ast.Sub: "subtract", ast.Mult: "multiply"}
        if type(node.op) not in operations:
            raise _Unsupported("operator_outside_finite_grammar")
        return _binary(operations[type(node.op)], _atom(node.left, inverse), _atom(node.right, inverse))
    return _atom(node, inverse)


def _event(statement: ast.stmt, inverse: dict[str, str]) -> tuple[Any, ...]:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        if isinstance(target, ast.Name):
            return _set(_role(target, inverse), _expression(statement.value, inverse))
        if (isinstance(target, ast.Tuple) and isinstance(statement.value, ast.Tuple)
                and len(target.elts) == len(statement.value.elts) == 2):
            roles = tuple(_role(node, inverse) for node in target.elts)
            if roles[0] == roles[1]:
                raise _Unsupported("duplicate_parallel_target")
            return ("parallel", tuple(zip(roles, (_expression(node, inverse) for node in statement.value.elts))))
    if isinstance(statement, ast.AugAssign) and isinstance(statement.op, (ast.Add, ast.Sub)):
        role = _role(statement.target, inverse)
        return _set(role, _binary("add" if isinstance(statement.op, ast.Add) else "subtract",
                                 _name(role), _atom(statement.value, inverse)))
    if (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name) and statement.value.func.id == "print"
            and not statement.value.keywords and 1 <= len(statement.value.args) <= 3):
        return _output(*(_expression(node, inverse) for node in statement.value.args))
    raise _Unsupported("statement_outside_finite_grammar")


def _matches(events: list[tuple[Any, ...]], contract: dict[str, Any]) -> bool:
    """Four closed dependency shapes, not a symbolic/numeric interpreter."""
    kind, values = contract["task_kind"], contract["values"]
    initial = {
        "accumulate": (("total", "initial"), ("increase", "increase"), ("decrease", "decrease")),
        "refresh": (("price", "price"), ("qty", "initial_qty")),
        "swap": (("left", "left"), ("right", "right")),
        "transfer": (("source", "source"), ("target", "target"), ("amount", "amount")),
    }[kind]
    prefix = [_set(role, _literal(values[key])) for role, key in initial]
    # Independent initialization may be reordered, but never duplicated/omitted.
    if sorted(events[:len(prefix)], key=repr) != sorted(prefix, key=repr):
        return False
    rest = events[len(prefix):]
    n, b, s, out = _name, _binary, _set, _output
    if kind == "accumulate":
        return rest == [s("total", b("add", n("total"), n("increase"))),
                        s("total", b("subtract", n("total"), n("decrease"))), out(n("total"))]
    if kind == "refresh":
        derived = b("multiply", n("price"), n("qty"))
        before = [s("subtotal", derived), s("qty", _literal(values["updated_qty"]))]
        return rest in [before + [s("subtotal", derived), out(n("subtotal"))],
                        before + [s("saved", derived), s("subtotal", n("saved")), out(n("subtotal"))]]
    if kind == "swap":
        return rest in [
            [s("saved", n("left")), s("left", n("right")), s("right", n("saved")), out(n("left"), n("right"))],
            [s("saved", n("right")), s("right", n("left")), s("left", n("saved")), out(n("left"), n("right"))],
            [("parallel", (("left", n("right")), ("right", n("left")))), out(n("left"), n("right"))],
            [("parallel", (("right", n("left")), ("left", n("right")))), out(n("left"), n("right"))],
        ]
    debit, credit = b("subtract", n("source"), n("amount")), b("add", n("target"), n("amount"))
    total = b("add", n("source"), n("target"))
    updates = [
        [s("source", debit), s("target", credit)],
        [s("target", credit), s("source", debit)],
        [("parallel", (("source", debit), ("target", credit)))],
        [("parallel", (("target", credit), ("source", debit)))],
    ]
    outputs = [[out(n("source"), n("target"), total)],
               [s("total", total), out(n("source"), n("target"), n("total"))]]
    return any(rest == update + output for update in updates for output in outputs)


def inspect_python_state_goal(code: str, goal_contract: object) -> GoalFacts:
    """Static facts only; unsupported cannot establish a semantic negative."""
    contract = normalize_python_state_contract(goal_contract)
    digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False).encode("utf-8")).hexdigest()
    facts: GoalFacts = {"goal_contract_id": GOAL_CONTRACT_ID, "goal_contract_hash": digest,
                        "goal_status": "unsupported", "goal_satisfied": None}
    if not isinstance(code, str):
        return facts
    try:
        if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
            return facts
        tree = ast.parse(code)
        if not 1 <= len(tree.body) <= MAX_STATEMENTS or sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
            return facts
        inverse = {name: role for role, name in contract["variables"].items()}
        events = [_event(statement, inverse) for statement in tree.body]
        if events[-1][0] != "print" or any(event[0] == "print" for event in events[:-1]):
            return facts
        satisfied = _matches(events, contract)
        facts["goal_status"] = "satisfied" if satisfied else "unsatisfied"
        facts["goal_satisfied"] = satisfied
        return facts
    except (_Unsupported, SyntaxError, ValueError, UnicodeError, MemoryError, RecursionError):
        return facts
