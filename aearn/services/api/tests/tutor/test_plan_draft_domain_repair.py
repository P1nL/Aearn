"""Pure domain failures enter repair before semantic-review IO or plan execution."""
from __future__ import annotations

import json

import pytest

from app.agents.harness.contracts import TutorProviderAttemptOutcome, payload_mapping_from_fields
from app.core.config import Settings
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from tests.tutor.test_plan_draft_semantic_repair import _Client
from tests.tutor.test_plan_draft_versioned_capacity import _setup
from tests.tutor.test_tutor_plan_wire_contract import _arguments, _candidate, _valid_parts


@pytest.mark.parametrize(("part", "path", "limit"), [
    (0, ("pace_summary",), 240),
    (1, ("nodes", 0, "description"), 300),
])
def test_domain_shape_repairs_before_semantic_review_without_rejected_values(part, path, limit):
    run, context, *_ = _setup("1.1.0")
    valid = _valid_parts()
    invalid = list(valid)
    body = json.loads(invalid[part])
    target = body
    for component in path[:-1]:
        target = target[component]
    secret_marker = "private-rejected-domain-value-"
    rejected = secret_marker + "x" * (limit + 1 - len(secret_marker))
    target[path[-1]] = rejected
    invalid[part] = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    assert len(invalid[part]) <= 1024
    client = _Client([
        _candidate("learning.plan.draft", _arguments(tuple(invalid))),
        _candidate("learning.plan.draft", _arguments(valid)),
    ])
    reviewed = []

    def semantic_review(_run, _context, decision, attempt):
        reviewed.append(attempt)
        assert payload_mapping_from_fields(decision.capability_requests[0].arguments) == dict(
            zip(("profile_json", "module_1", "module_2"), valid))
        return None

    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client, decision_validator=semantic_review,
    ).decide(run=run, context=context)
    assert result.decision is not None
    assert reviewed == [2]
    assert [attempt.outcome for attempt in result.attempts] == [
        TutorProviderAttemptOutcome.REPAIRABLE_REJECTED, TutorProviderAttemptOutcome.ACCEPTED,
    ]
    guidance = client.messages[1][-1]["content"]
    assert "plan_domain_invalid" in guidance
    assert path[-1] in guidance and f"maxLength={limit}" in guidance
    assert secret_marker not in guidance and rejected not in guidance
