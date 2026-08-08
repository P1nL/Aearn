from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.services.tutor.evals import (
    TutorEvalFixtureError,
    load_tutor_eval_cases,
    run_tutor_eval_case,
    run_tutor_eval_fixture,
)


FIXTURE = Path(__file__).parent / "fixtures" / "tutor_evals" / "tutor_harness_foundation_v1.json"


def test_fake_only_tutor_eval_fixture_covers_pinned_catalog_and_required_scenarios() -> None:
    results = run_tutor_eval_fixture(FIXTURE)

    assert results
    assert all(result.passed for result in results)
    assert {result.case_id for result in results} == {
        "catalog-identity-pinned",
        "policy-denial-no-capability",
        "strict-provider-envelope-rejected",
        "bounded-loop-exits-before-provider",
        "revision-race-stale-effect",
        "primary-only-model-unavailable",
        "protected-values-never-exported",
        "replay-outbox-proposal-terminal-unique",
        "current-input-pinned",
        "newest-history-selected",
        "teaching-correction-policy-present",
        "current-input-unrepresentable-provider-not-called",
    }


def test_eval_runner_rejects_unknown_fixture_version_and_mutable_catalog_alias(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schema_version":"unknown","cases":[]}', encoding="utf-8")

    with pytest.raises(TutorEvalFixtureError, match="schema version"):
        load_tutor_eval_cases(invalid)

    case = load_tutor_eval_cases(FIXTURE)[0]
    mutable_catalog = dict(case.catalog) | {"skill_version": "current"}
    with pytest.raises(TutorEvalFixtureError, match="catalog identity"):
        run_tutor_eval_case(replace(case, catalog=mutable_catalog))
