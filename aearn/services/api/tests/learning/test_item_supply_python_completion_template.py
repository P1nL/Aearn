"""Two focused pure presentation checks, not model/OS/source-current acceptance."""
from __future__ import annotations

import ast
import json

from app.services.learning.item_bank.contracts import LearningItemSourceV1
from app.services.learning.item_bank.validation import _filled_blanks
from app.services.learning.item_bank.practice_adapter import build_exercise_authority
from app.services.runners.runtime_runner import inspect_submission
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.python_goal_template import (
    PYTHON_GOAL_COMPLETION_PATTERNS, PYTHON_GOAL_COMPLETION_STARTER,
    PYTHON_GOAL_COMPLETION_VERSION, build_python_goal_completion_template,
)
from app.services.learning.item_supply.sandbox.probe_plans import build_candidate_probe_plan
from app.services.learning.item_supply.sandbox.python_goal_scorer import (
    PYTHON_GOAL_ID, PYTHON_GOAL_INSTRUCTION, PYTHON_GOAL_PROFILE, PYTHON_GOAL_SCORER_VERSION,
    compile_goal_tests, source_goal_contract, source_scorer_version,
)
from app.services.learning.item_supply.task_ambiguity_owner import build_task_ambiguity_plan, target_clauses
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request
from tests.learning.test_item_supply_python_goal_scorer import goal_source


def completion_source(refs=None):
    old = goal_source()
    template = build_python_goal_completion_template(item_key="python-completion-new-candidate",
        source_references=refs if refs is not None else old.blueprint.source_references)
    payload = old.model_dump(mode="json")
    payload["public"] = template.model_dump(mode="json")
    payload["blueprint"]["source_references"] = payload["public"]["source_references"]
    payload["private"].update(item_key=template.item_key, version=template.version)
    return LearningItemSourceV1.model_validate(payload)


def test_completion_metadata_covers_both_tails_without_changing_target_or_legacy_goal():
    old = goal_source()
    old_dump = old.model_dump(mode="json")
    new = completion_source()
    assert new.public.version == PYTHON_GOAL_COMPLETION_VERSION != old.public.version
    assert new.public.item_key != old.public.item_key and new.content_hash != old.content_hash
    assert old.model_dump(mode="json") == old_dump
    assert new.public.instruction_markdown == old.public.instruction_markdown == PYTHON_GOAL_INSTRUCTION
    assert new.public.content.starter_code == PYTHON_GOAL_COMPLETION_STARTER
    # Parse only, never exec a candidate on the host: the unfinished starter
    # contains exactly the unchanged assignment and comments, not a wrong print.
    body = ast.parse(new.public.content.starter_code).body
    assert len(body) == 1 and isinstance(body[0], ast.Assign)
    assert body[0].targets[0].id == "numbers"
    assert not any(isinstance(node, ast.Call) for node in ast.walk(body[0]))
    assert new.public.content.required_patterns == ()
    blank = new.public.content.code_blanks[0]
    assert blank.blank_key == "sum_output" and len(blank.acceptable_patterns) == 1
    assert blank.acceptable_patterns[0].type == "regex"
    assert blank.acceptable_patterns[0].value == r"\bsum\b"
    material = build_exercise_authority(new)
    assert material is not None
    tails = PYTHON_GOAL_COMPLETION_PATTERNS + (
        "total=sum(numbers)\nprint(total)",
        "print( sum( numbers ) )",
    )
    canonical_trees = {ast.dump(ast.parse("numbers = [3, -1, 0, 3]\n" + tail))
                       for tail in PYTHON_GOAL_COMPLETION_PATTERNS}
    for tail in tails:
        code = "numbers = [3, -1, 0, 3]\n" + tail
        assert ast.dump(ast.parse(code)) in canonical_trees
        filled = _filled_blanks(new.public.content, code)
        assert filled == {"sum_output": "sum"}
        # Inspect only: both old metadata paths must not reject AST-equivalent
        # formatting. No candidate execution or replacement scoring authority.
        assert inspect_submission(material.runner_payload, code, filled)["core_blank_gate"] is True
        assert inspect_submission(material.runner_payload, code, {})["core_blank_gate"] is True
    assert _filled_blanks(new.public.content, new.public.content.starter_code) == {}
    assert source_goal_contract(new) == source_goal_contract(old) == PYTHON_GOAL_ID
    assert source_scorer_version(new) == PYTHON_GOAL_SCORER_VERSION
    assert compile_goal_tests(new) == compile_goal_tests(old)
    assert target_clauses(new) == target_clauses(old)
    assert build_task_ambiguity_plan(new).target == build_task_ambiguity_plan(old).target
    plan = build_candidate_probe_plan(new)
    assert plan.profile_id == PYTHON_GOAL_PROFILE
    assert plan.server_fixture_hash == build_candidate_probe_plan(old).server_fixture_hash


def test_new_public_template_is_frozen_and_counted_by_existing_generation_contract():
    request, _ = make_request()
    source = completion_source(request.blueprint.source_references)
    payload = source.model_dump(mode="json")
    request = request.model_copy(update={"blueprint": source.blueprint, "public_template": source.public,
        "item_key": source.public.item_key, "version": source.public.version})
    provider = SyntheticProvider(payload)
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged" and result.source == source and provider.calls == 1
    prompt = json.loads(provider.messages[1]["content"])
    schema = json.loads(provider.messages[0]["content"].split("AUTHORITATIVE OUTPUT JSON SCHEMA:\n", 1)[1])
    assert prompt["public_template"] == source.public.model_dump(mode="json")
    assert schema["properties"]["public"]["const"] == prompt["public_template"]
    assert "private" not in prompt and "tests" not in prompt["public_template"]
    small = request.model_copy(update={"limits": request.limits.model_copy(update={"max_input_bytes": 1})})
    unused = SyntheticProvider(payload)
    blocked = generate_candidate(small, provider=unused, source_authority=SyntheticAuthority(), enabled=True)
    assert blocked.safe_reason == "input_limit" and unused.calls == 0
    changed = source.model_dump(mode="json")
    changed["public"]["content"]["starter_code"] = "numbers = [3, -1, 0, 3]\nprint(0)"
    rejected = generate_candidate(request, provider=SyntheticProvider(changed),
        source_authority=SyntheticAuthority(), enabled=True)
    assert rejected.safe_reason == "candidate_mismatch"
