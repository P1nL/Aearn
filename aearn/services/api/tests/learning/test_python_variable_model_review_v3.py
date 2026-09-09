from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.services.learning.item_bank.compiler import LearningItemCompiler, curated_learning_item_source_root
from app.services.learning.practice.model_review_contracts import ModelCodeReviewSubmissionV1, ModelReviewAssistanceKind
from app.services.learning.practice.model_review_scoring import evaluate_model_code_review

# Exact public-task counterexamples from the independent v2 ambiguity review.
_COUNTEREXAMPLES = {'stale-derived-remediation': {'verdict': 'correctness_issue',
                               'findings': [{'client_finding_id': 'alternate-1',
                                             'finding_kind': 'correctness',
                                             'start_line': 4,
                                             'end_line': 4,
                                             'category': 'assignment_order',
                                             'severity': 'high',
                                             'trigger_condition': 'doubled was calculated before '
                                                                  'the input changed from 3 to 4.',
                                             'principle': 'Integer arithmetic produces a value, '
                                                          'not a formula that automatically '
                                                          'updates.',
                                             'impact': 'The final result is 6; the requirement '
                                                       'demands 8.',
                                             'validation_method': 'Execute the four statements and '
                                                                  'compare result with 4 * 2; the '
                                                                  'equality is false.',
                                             'suggested_fix': 'Recompute twice the updated input '
                                                              'in the final assignment instead of '
                                                              'copying the cached value.',
                                             'supplemental_note': None}],
                               'supplemental_note': None},
 'stale-subtotal-review': {'verdict': 'correctness_issue',
                           'findings': [{'client_finding_id': 'alternate-1',
                                         'finding_kind': 'correctness',
                                         'start_line': 5,
                                         'end_line': 5,
                                         'category': 'assignment_order',
                                         'severity': 'high',
                                         'trigger_condition': 'subtotal was calculated before the '
                                                              'price changed from 10 to 12.',
                                         'principle': 'An integer product is a snapshot, not a '
                                                      'formula that updates when an input changes.',
                                         'impact': 'The final total is 20; the requirement demands '
                                                   '24.',
                                         'validation_method': 'Execute the five statements and '
                                                              'compare total with 12 * 2; the '
                                                              'equality is false.',
                                         'suggested_fix': 'Recompute the product of the updated '
                                                          'price and the unchanged count in the '
                                                          'final assignment instead of copying the '
                                                          'cached value.',
                                         'supplemental_note': None}],
                           'supplemental_note': None}}

_V3_HASHES = {
    "stale-derived-remediation": "b2a79f0f1c65760044c1c218eb54597c34bf3e9bdf7989deb5c43c495bc2c19e",
    "stale-subtotal-review": "5e62fb38532f38bc6f81a07f16fb5ea22d7cf494c72c31704b640e1eee938923",
}
_V2_BYTES = {
    "stale-derived-remediation": "3c7836f49d5c50a74ca470aa09e967c80fbf99b338ec9dc1165023b051e3cd68",
    "stale-subtotal-review": "46bcd976041c4537b88ff0e1d35b7bcdc976529da18b91e7d1e66a1f378e9a65",
}


def _compiled(name, version):  # type: ignore[no-untyped-def]
    return LearningItemCompiler().compile_file(
        curated_learning_item_source_root(), f"python-variables-{name}-{version}.json", require_valid=True,
    )


def _score(name, version, payload):  # type: ignore[no-untyped-def]
    source = _compiled(name, version).loaded.source
    private = source.private.content
    return evaluate_model_code_review(
        submission=ModelCodeReviewSubmissionV1.model_validate(payload),
        rubric=private.rubric,
        line_count=source.public.content.artifact.line_count,
        required_capabilities=source.blueprint.required_capabilities,
        assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
        threshold=private.score_policy.threshold,
        now=datetime(2026, 9, 8, tzinfo=UTC),
    )


@pytest.mark.parametrize("name", _COUNTEREXAMPLES)
def test_v3_accepts_exact_independent_review_counterexample(name: str) -> None:
    payload = _COUNTEREXAMPLES[name]
    assert _score(name, "v2", payload).outcome.value == "failed"
    assert _score(name, "v3", payload).outcome.value == "passed"


@pytest.mark.parametrize("name", _COUNTEREXAMPLES)
def test_v3_accepts_valid_paraphrase_with_visible_identifiers(name: str) -> None:
    payload = deepcopy(_COUNTEREXAMPLES[name])
    finding = payload["findings"][0]
    finding["principle"] = "A computed number is stored; later rebinding does not reevaluate its expression."
    finding["validation_method"] = (
        "Test the assignments and assert the final result equals the product required by the task."
    )
    finding["suggested_fix"] = "Change the final assignment to evaluate the required expression again."
    assert _score(name, "v3", payload).outcome.value == "passed"


@pytest.mark.parametrize("name", _COUNTEREXAMPLES)
@pytest.mark.parametrize("defect", ["wrong_verdict", "wrong_range", "wrong_category", "missing_identifier"])
def test_v3_rejects_invalid_structured_reviews(name: str, defect: str) -> None:
    payload = deepcopy(_COUNTEREXAMPLES[name])
    finding = payload["findings"][0]
    if defect == "wrong_verdict":
        payload["verdict"] = "uncertain"
    elif defect == "wrong_range":
        finding["start_line"] = finding["end_line"] = 1
    elif defect == "wrong_category":
        finding["category"] = "style"
    else:
        missing = "doubled" if name == "stale-derived-remediation" else "subtotal"
        for key, value in finding.items():
            if isinstance(value, str):
                finding[key] = value.replace(missing, "cached value")
    assert _score(name, "v3", payload).outcome.value == "failed"


@pytest.mark.parametrize("name", _COUNTEREXAMPLES)
def test_v3_is_immutable_and_keeps_threshold_and_publication_policy(name: str) -> None:
    previous = _compiled(name, "v2")
    current = _compiled(name, "v3")
    assert previous.loaded.source_bytes_hash == _V2_BYTES[name]
    source = current.loaded.source
    old = previous.loaded.source
    assert source.content_hash == _V3_HASHES[name]
    assert source.public.item_key == old.public.item_key
    assert source.blueprint.version == source.public.version == source.private.version == "v3"
    assert source.blueprint.publication_policy == old.blueprint.publication_policy
    assert source.private.content.score_policy == old.private.content.score_policy
    finding = source.private.content.rubric.expected_findings[0]
    old_finding = old.private.content.rubric.expected_findings[0]
    assert finding.minimum_token_matches == old_finding.minimum_token_matches == 2
    assert finding.accepted_line_ranges == old_finding.accepted_line_ranges
    assert finding.category == old_finding.category
    identifiers = ("result", "doubled") if name == "stale-derived-remediation" else ("total", "subtotal")
    assert set(finding.matcher_tokens) == set(identifiers)
    for identifier in identifiers:
        assert f"`{identifier}`" in source.public.content.prompt.learner_instruction
    assert "both visible variable identifiers" in source.public.content.prompt.learner_instruction
    assert "as separate words" in source.public.content.prompt.learner_instruction
