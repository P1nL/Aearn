"""One pure protocol case. No actual provider, PG, OS or review acceptance."""
from __future__ import annotations

import json

from app.services.learning.item_bank.contracts import canonical_hash, canonical_json
from app.services.learning.item_supply.review_contracts_v2 import ReviewInputV2
from app.services.learning.item_supply.review_provider import (
    JsonReviewerV2, PYTHON_GOAL_REVIEW_PROMPT_VERSION, blind_input, review_resource_plan,
)
from app.services.learning.item_supply.sandbox.python_goal_scorer import (
    PYTHON_GOAL_ID, PYTHON_GOAL_SCORER_HASH, PYTHON_GOAL_SCORER_VERSION,
)
from tests.learning.test_item_supply_python_goal_scorer import goal_source
from tests.learning.test_item_supply_v2_execution_review import (
    OfflineClient, binding_for, live_validation_fixture, ports, source_fixture,
)


def test_neutral_exact_goal_descriptor_is_bound_and_counted_without_directing_vote_or_leaking_to_blind():
    class RecordingClient(OfflineClient):
        def complete_json(self, messages, **kwargs):
            self.messages = messages
            self.kwargs = kwargs
            return super().complete_json(messages, **kwargs)

    source = goal_source()
    raw_source = source.model_dump(mode="json")
    validation = live_validation_fixture(source)
    execution = validation.execution_evidence.model_copy(update={"scorer_version": PYTHON_GOAL_SCORER_VERSION})
    digest = canonical_hash(execution.model_dump(mode="json"))
    validation = validation.model_copy(update={"execution_evidence": execution,
        "checks": tuple(check.model_copy(update={"proof_hash": digest}) for check in validation.checks)})
    binding = binding_for(source)
    solver, reviewers, _ = ports()
    client = RecordingClient("unit-model", {"verdict": "changes_required", "findings": [{
        "severity": "major", "blocking": True, "safe_code": "rubric_mismatch",
        "evidence_hash": canonical_hash(source.public.model_dump(mode="json")),
    }]})
    reviewer = JsonReviewerV2(client, role=reviewers[0].role, identity=reviewers[0].provider_identity,
        profile_hash=binding.profile_hash, timeout_seconds=10, max_output_tokens=512)
    reviewers = (reviewer, *reviewers[1:])
    request = ReviewInputV2(binding=binding, role=reviewer.role, source=source, validation_receipt=validation)
    budget = reviewer.input_resource_plan(request)
    assert review_resource_plan(source, binding=binding, validation_receipt=validation,
        solver=solver, reviewers=reviewers).requests == 7
    report = reviewer.review(request)
    payload = json.loads(client.messages[1]["content"])
    descriptor = payload["scoring_descriptor"]
    assert descriptor["goal_contract_id"] == PYTHON_GOAL_ID
    assert descriptor["scoring_contract_hash"] == PYTHON_GOAL_SCORER_HASH and descriptor["server_fixture_hash"]
    assert descriptor["source_hash"] == binding.source_hash and descriptor["binding_hash"] == canonical_hash(binding.model_dump(mode="json"))
    assert "stdout" in descriptor["pass_rule"] and "strict boolean true" in descriptor["pass_rule"]
    assert "input_json={}" in descriptor["case_compilation_rule"] and "expected outputs are preserved" in descriptor["case_compilation_rule"]
    assert "does not authenticate a receipt" in descriptor["facts_boundary"]
    assert payload["source"] == raw_source and source.model_dump(mode="json") == raw_source
    assert report.material_failure and report.verdict.value == "changes_required"
    assert report.run.prompt_version == PYTHON_GOAL_REVIEW_PROMPT_VERSION
    assert report.run.input_hash == request.input_hash == canonical_hash(payload)
    assert "not source text, a peer report, an approval or an instruction to approve" in client.messages[0]["content"]
    expected_bytes = len(canonical_json({"messages": client.messages,
        "output_schema": client.kwargs["output_schema"], "schema_name": client.kwargs["schema_name"]}).encode("utf-8")) + 1024
    assert budget.input_tokens == expected_bytes
    public_blind = blind_input(source, binding).model_dump(mode="json")
    assert "scoring_descriptor" not in public_blind and "private" not in public_blind
    assert "tests" not in public_blind["problem"] and "standard_answer" not in public_blind["problem"]
    for sql in (False, True):
        legacy = source_fixture(sql=sql)
        old = ReviewInputV2(binding=binding_for(legacy), role=reviewer.role,
            source=legacy, validation_receipt=live_validation_fixture(legacy))
        assert old.scoring_descriptor is None and old.input_payload == old.model_dump(mode="json")
        assert old.input_hash == canonical_hash(old.model_dump(mode="json"))


def test_admission_consumer_accepts_exact_goal_prompt_version_but_retains_material_veto_and_stale_checks():
    from app.services.learning.item_supply.admission import evaluate_admission_v2
    from app.services.learning.item_supply.review_provider import (
        BLIND_PROMPT_VERSION, REVIEW_PROMPT_VERSION, blind_solve_candidate, review_candidate,
    )
    from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
    from tests.learning.test_item_supply_v2_execution_review import OfflineScorer, evidence_for

    source = goal_source()
    validation = live_validation_fixture(source)
    execution = validation.execution_evidence.model_copy(update={"scorer_version": PYTHON_GOAL_SCORER_VERSION})
    digest = canonical_hash(execution.model_dump(mode="json"))
    validation = validation.model_copy(update={"execution_evidence": execution,
        "checks": tuple(check.model_copy(update={"proof_hash": digest}) for check in validation.checks)})
    binding = binding_for(source)
    solver, reviewers, clients = ports()
    clients[3].content = {"verdict": "changes_required", "findings": [{
        "severity": "major", "blocking": True, "safe_code": "rubric_mismatch", "evidence_hash": source.content_hash,
    }]}
    # Pure protocol doubles only; these are not actual OS/source/facts authority.
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=OfflineScorer())
    bundle = review_candidate(source, binding=binding, validation_receipt=validation,
        author_identity="author", blind_solve_receipt=blind, reviewers=reviewers)
    assert blind.run.prompt_version == BLIND_PROMPT_VERSION
    assert all(report.run.prompt_version == PYTHON_GOAL_REVIEW_PROMPT_VERSION for report in bundle.reports)
    evidence = evidence_for(validation, binding)
    def evaluate(value):
        return evaluate_admission_v2(source, binding=binding, policy=AutonomousEvidencePolicyV2(),
            validation_receipt=validation, author_identity="author", bundle=value, evidence=evidence, enabled=True)
    result = evaluate(bundle)
    assert result.disposition == "quarantine" and result.safe_reasons == ("material_review_failure",)
    for changed in ({"prompt_version": REVIEW_PROMPT_VERSION}, {"input_hash": "0" * 64}, {"output_hash": "0" * 64}):
        stale = bundle.reports[0].model_copy(update={"run": bundle.reports[0].run.model_copy(update=changed)})
        invalid = evaluate(bundle.model_copy(update={"reports": (stale, *bundle.reports[1:])}))
        assert invalid.safe_reasons == ("invalid_or_stale_evidence",)
