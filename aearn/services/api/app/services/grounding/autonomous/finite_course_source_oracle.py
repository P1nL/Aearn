"""Closed PUBLIC curriculum source-oracle declarations, not execution receipts.

Examples are independently declared source-level binding/predicate controls, not
learner answers or the item bank's private fixture catalog. No code executes here.
"""
from __future__ import annotations

import json
from typing import Any

from aearn_shared.execution import ExecutionAction, SandboxInputV1

from app.services.grounding.autonomous.assessment_contracts import ExecutionScope
from app.services.grounding.material_contracts_v2 import digest
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_targets.contracts import TargetId

SOURCE_PROFILE_BY_TARGET = {
    "python-state-update-v1": "python-state-source-v1",
    "sqlite-predicate-order-v1": "sqlite-predicate-source-v1",
    "python-kc-binding-v1": "python-binding-source-v1",
}


def public_course_source_request(target_id: TargetId) -> tuple[SandboxInputV1, dict[str, Any], str]:
    target = get_finite_course_target(target_id)
    if target_id == "sqlite-predicate-order-v1":
        runtime = "sqlite-query-v1"
        code = (
            "SELECT name, active=1 AND score>=60 AS qualified, "
            "COALESCE(override_flag,default_flag)=1 AS effective, "
            "(COALESCE(flag_a,0)+COALESCE(flag_b,0))=1 AS exclusive, "
            "score<70 OR (score=70 AND id>2) AS after_cursor "
            "FROM entries ORDER BY score DESC NULLS LAST,id ASC"
        )
        columns = [("id", "INTEGER", False), ("name", "TEXT", False), ("active", "INTEGER", True),
                   ("score", "INTEGER", True), ("override_flag", "INTEGER", True), ("default_flag", "INTEGER", True),
                   ("flag_a", "INTEGER", True), ("flag_b", "INTEGER", True)]
        cases = [{"id": "public_course_source", "case_type": "visible", "max_rows": 20,
            "tables": [{"name": "entries", "columns": [{"name": n, "data_type": t, "nullable": nullable}
                                                       for n, t, nullable in columns]}],
            "dataset": {"tables": [{"table": "entries", "rows": [
                [1, "A", 1, 60, None, 1, 1, None], [2, "B", 0, 70, 0, 1, 1, 1],
                [3, "A", 1, 70, 1, 0, 0, 1], [4, "C", None, None, None, None, None, None],
                [5, "D", 1, 70, None, 0, 0, 0],
            ]}]}}]
        # Hand-derived NULL/boolean matrix, duplicate A projection and full tie
        # order. Never execute the reference query to manufacture expected truth.
        expected = {"cases": [{"id": "public_course_source", "status": "success", "code": "sqlite_terminal",
            "columns": ["name", "qualified", "effective", "exclusive", "after_cursor"],
            "rows": [["B", 0, 0, 0, 0], ["A", 1, 1, 1, 1], ["D", 1, 0, 0, 1],
                     ["A", 1, 1, 1, 1], ["C", None, None, 0, None]]}]}
        applicability = "Registered finite SQLite predicate/order curriculum: AND, NULL fallback, exclusive flags, strict cursor, multiset and full order; pinned runtime only."
    else:
        runtime = "python-stdout-v1"
        if target_id == "python-state-update-v1":
            code = (
                "amount=12\nup=7\ndown=2\namount+=up\namount-=down\nprint(amount)\n"
                "unit=3\ncount=4\nsubtotal=unit*count\ncount=6\nsubtotal=unit*count\nprint(subtotal)\n"
                "left=5\nright=13\nsaved=left\nleft=right\nright=saved\nprint(left,right)\n"
                "origin=15\ndestination=2\nstep=4\norigin-=step\ndestination+=step\nprint(origin,destination,origin+destination)"
            )
            stdout = "17\n18\n13 5\n11 6 17\n"
            applicability = "Registered finite Python integer state curriculum: current RHS, ordered update, derived refresh, saved swap and conserved transfer; pinned runtime only."
        else:
            code = (
                "origin=12\nsaved=origin\norigin=4\nprint(saved,origin)\n"
                "unit=7\ncount=2\nderived=unit*count\nunit=9\nprint(derived,unit*count)\n"
                "x=6\nold=x\nx=x+3\nnew=x*2\nprint(old,new)"
            )
            stdout = "12 4\n14 18\n6 18\n"
            applicability = "Registered Python integer binding curriculum: RHS time, saved versus rebound names and non-live derived values; source semantic oracle, not a KC execution score."
        cases = [{"id": "public_course_source", "case_type": "visible"}]
        expected = {"cases": [{"id": "public_course_source", "status": "success", "code": "python_terminal", "stdout": stdout}]}
    request = SandboxInputV1(runtime_id=runtime, action=ExecutionAction.TEST, submission=code,
        visible_test_bundle_json=json.dumps(cases, separators=(",", ":")), hidden_test_bundle_json="[]",
        source_reference_hash=digest({"profile": SOURCE_PROFILE_BY_TARGET[target_id], "target": target.definition_hash, "code": code}),
        test_reference_hash=digest(cases))
    return request, expected, applicability


def public_course_execution_scope(target_id: TargetId) -> ExecutionScope:
    request, expected, applicability = public_course_source_request(target_id)
    target = get_finite_course_target(target_id)
    return ExecutionScope(runtime_profile=request.runtime_id, input_hash=digest(request.model_dump(mode="json")),
        semantics_hash=digest({"target_definition_hash": target.definition_hash, "expected": expected, "applicability": applicability}))
