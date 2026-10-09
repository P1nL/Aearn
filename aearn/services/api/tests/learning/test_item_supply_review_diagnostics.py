"""Small offline diagnostic regressions; no fresh source, provider, PG or OS claims."""
from __future__ import annotations

import copy
import json

import pytest

from app.services.learning.item_bank.contracts import canonical_hash, canonical_json
from app.services.learning.item_supply.review_contracts_v2 import (
    REVIEW_DIAGNOSTIC_PROMPT_VERSION, ReviewDiagnosticInputV1, ReviewDiagnosticOutputV1,
    ReviewInputV2, ReviewReportV2,
)
from app.services.learning.item_supply.review_provider import AutonomousReviewError, JsonReviewerV2, blind_input
from app.services.learning.item_supply.sandbox.python_goal_scorer import PYTHON_GOAL_SCORER_VERSION
from app.services.learning.item_supply.storage_contracts import checked_model
from tests.learning.test_item_supply_python_goal_scorer import goal_source
from tests.learning.test_item_supply_v2_execution_review import OfflineClient, binding_for, live_validation_fixture, ports


class RecordingClient(OfflineClient):
    def complete_json(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return super().complete_json(messages, **kwargs)


def diagnostic_fixture():
    source = goal_source()
    validation = live_validation_fixture(source)
    execution = validation.execution_evidence.model_copy(update={"scorer_version": PYTHON_GOAL_SCORER_VERSION})
    digest = canonical_hash(execution.model_dump(mode="json"))
    validation = validation.model_copy(update={"execution_evidence": execution,
        "checks": tuple(check.model_copy(update={"proof_hash": digest}) for check in validation.checks)})
    binding = binding_for(source)
    _, reviewers, _ = ports()
    request = ReviewDiagnosticInputV1(source_authority="expired_historical", review_input=ReviewInputV2(binding=binding, role=reviewers[2].role,
        source=source, validation_receipt=validation))
    reference = next(ref for ref in request.evidence_index if ref.pointer == "/source/public/content/starter_code")
    output = {"schema_version": "item_supply_review_diagnostic_output_v1", "findings": [{
        "severity": "major", "blocking": True, "safe_code": "ambiguity", "evidence_hash": binding.content_hash,
        # Deliberately fictional claim: matching a pointer does not prove this claim true.
        "problem": "UNIT_ONLY_PRIVATE_CLAIM about the supplied starter.",
        "expected_behavior": "UNIT_ONLY_EXPECTATION requiring human inspection.",
        "references": [reference.model_dump(mode="json")],
    }]}
    client = RecordingClient("unit-model", output)
    reviewer = JsonReviewerV2(client, role=request.review_input.role, identity=reviewers[2].provider_identity,
        profile_hash=binding.profile_hash, timeout_seconds=10, max_output_tokens=512)
    return request, reviewer, client


def test_private_retrospective_diagnostic_binds_full_input_output_and_separate_budget():
    request, reviewer, client = diagnostic_fixture()
    old_payload = request.review_input.input_payload
    plan = reviewer.diagnostic_resource_plan(request)
    assert client.inputs == [] and plan.requests == 1 and plan.output_tokens == 512
    receipt = reviewer.diagnose(request)
    receipt.verify_input(request)
    assert len(client.inputs) == 1 and client.kwargs["capture_provider_body"] is False
    assert receipt.admission_eligible is False and receipt.visibility == "private_only"
    assert receipt.run.prompt_version == REVIEW_DIAGNOSTIC_PROMPT_VERSION
    payload = json.loads(client.messages[1]["content"])
    assert payload["purpose"] == "retrospective_diagnosis" and payload["source_authority"] == "expired_historical"
    assert payload["review_input"] == old_payload == request.review_input.input_payload
    assert receipt.run.input_hash == request.input_hash == canonical_hash(payload)
    assert receipt.run.output_hash == canonical_hash(client.content) == canonical_hash(receipt.output.model_dump(mode="json"))
    expected_bytes = len(canonical_json({"messages": client.messages, "output_schema": client.kwargs["output_schema"],
        "schema_name": client.kwargs["schema_name"]}).encode("utf-8")) + 1024
    assert plan.input_tokens == expected_bytes
    assert "UNIT_ONLY_PRIVATE_CLAIM" not in repr(receipt) and "UNIT_ONLY_PRIVATE_CLAIM" not in str(receipt)
    assert "blind_solve" not in payload["review_input"] and "reports" not in payload["review_input"]
    blind = blind_input(request.review_input.source, request.binding).model_dump(mode="json")
    assert "private" not in blind and "evidence_index" not in blind and "scoring_descriptor" not in blind
    with pytest.raises(ValueError):
        checked_model(receipt, ReviewReportV2)
    changed = receipt.model_copy(update={"run": receipt.run.model_copy(update={"output_hash": "0" * 64})})
    with pytest.raises(ValueError, match="stale review diagnostic"):
        changed.verify_input(request)


def test_unbound_or_unexplained_diagnostics_fail_safely_without_retry():
    request, reviewer, client = diagnostic_fixture()
    original = copy.deepcopy(client.content)
    variants = []
    wrong_ref = copy.deepcopy(original)
    wrong_ref["findings"][0]["references"][0]["value_hash"] = "0" * 64
    variants.append(wrong_ref)
    missing_explanation = copy.deepcopy(original)
    del missing_explanation["findings"][0]["problem"]
    variants.append(missing_explanation)
    for value in variants:
        client.content = value
        before = len(client.inputs)
        with pytest.raises(AutonomousReviewError) as error:
            reviewer.diagnose(request)
        assert str(error.value) in {"review_diagnostic_failed", "review_provider_failed"}
        assert "UNIT_ONLY" not in str(error.value) and len(client.inputs) == before + 1
    with pytest.raises(ValueError):
        ReviewDiagnosticOutputV1.model_validate_json(canonical_json({**original, "verdict": "approved"}))


def test_legacy_review_vote_stays_exact_and_same_model_correlation_is_not_role_independence():
    from tests.learning.test_item_supply_v2_execution_review import (
        bundle_for, evaluate, evidence_for, source_fixture,
    )
    source = source_fixture()
    binding = binding_for(source)
    validation = live_validation_fixture(source)
    bundle = bundle_for(source, validation, binding)
    assert bundle.correlation_limited is True and len(bundle.correlation_groups) == 1
    for report in bundle.reports:
        assert report.run.output_hash == canonical_hash({"verdict": "approved", "findings": []})
        assert "diagnostic" not in report.model_dump_json()
    result = evaluate(source, validation, binding, bundle, evidence_for(validation, binding))
    assert result.correlation_limited is True
