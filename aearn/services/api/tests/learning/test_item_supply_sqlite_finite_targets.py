"""Offline finite truth only: no sqlite3, DB, provider or runner execution."""
from __future__ import annotations

from typing import cast

import pytest

from app.services.learning.item_bank.contracts import (
    LearningItemSqlDatasetTableV2,
    LearningItemSqlDatasetV2,
)
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_targets.sqlite_predicates import (
    SQLITE_PROGRAM_TARGET_ID,
    ConjunctionTargetV1,
    ExclusiveTargetV1,
    KeysetAfterTargetV1,
    OverrideFallbackTargetV1,
    SqlitePredicateTargetV1,
    SqlitePrivateFixtureV1,
    parse_sqlite_target,
    sqlite_counterexample_output,
    sqlite_fixture_hash,
    sqlite_oracle,
    sqlite_private_fixture,
    sqlite_target_hash,
)


@pytest.mark.parametrize(("target", "names"), (
    (ConjunctionTargetV1(), ("Early", "Twin", "Twin", "Later")),
    (OverrideFallbackTargetV1(), ("High", "First", "Second", "Twin", "Twin", "LowRank", "NullLast", "NullLastTwo")),
    (ExclusiveTargetV1(), ("High", "First", "Second", "Twin", "Twin", "LowRank", "NullLast", "NullLastTwo")),
    (KeysetAfterTargetV1(), ("First", "Second", "Twin", "Twin")),
))
def test_declared_truth_and_private_wire(target: SqlitePredicateTargetV1, names: tuple[str, ...]) -> None:
    fixture = sqlite_private_fixture(target)
    boundary, empty_result, empty_table = fixture.private_cases[:3]
    # Hand-written expectations independently check predicates, NULL handling,
    # duplicate projection and tie order, not oracle-derived self-comparison.
    assert boundary.expected_output.columns == ("name",)
    assert boundary.expected_output.rows == tuple((name,) for name in names)
    assert empty_result.expected_output.rows == empty_table.expected_output.rows == ()
    if isinstance(target, KeysetAfterTargetV1):
        assert fixture.private_cases[3].expected_output == boundary.expected_output
    assert fixture.family_id == f"{SQLITE_PROGRAM_TARGET_ID}:{target.task_kind}"
    assessment = get_finite_course_target(SQLITE_PROGRAM_TARGET_ID).assessment
    assert assessment.scorer_domain == assessment.assessment_contract_version == SQLITE_PROGRAM_TARGET_ID
    assert assessment.runtime_profile_id == "sqlite-query-v1"
    assert len(set(fixture.equivalent_queries)) == 2
    assert all(query.startswith("SELECT name FROM entries WHERE") for query in fixture.equivalent_queries)
    public_wire = fixture.public_task.model_dump_json()
    assert "expected_output" not in public_wire and "private_cases" not in public_wire
    assert all(query not in public_wire for query in fixture.equivalent_queries)
    assert all(case.execution_status == "pending" and case.failing_case_ids for case in fixture.counterexamples)
    roundtrip = SqlitePrivateFixtureV1.model_validate_json(fixture.model_dump_json())
    assert roundtrip == fixture
    assert sqlite_fixture_hash(roundtrip) == sqlite_fixture_hash(fixture)
    assert len(sqlite_target_hash(target)) == 64


def test_key_semantic_negatives_are_predictions_not_execution() -> None:
    and_fixture = sqlite_private_fixture(ConjunctionTargetV1())
    dataset = and_fixture.private_cases[0].dataset
    wrong_and = sqlite_counterexample_output(and_fixture.target, dataset, "or_instead_of_and")
    assert ("Inactive",) in wrong_and.rows and ("NullScore",) in wrong_and.rows
    fallback = sqlite_private_fixture(OverrideFallbackTargetV1())
    wrong_fallback = sqlite_counterexample_output(fallback.target, fallback.private_cases[0].dataset, "ignores_override")
    assert ("OverrideZero",) in wrong_fallback.rows
    assert ("OverrideZero",) not in fallback.private_cases[0].expected_output.rows
    cursor = sqlite_private_fixture(KeysetAfterTargetV1())
    wrong_cursor = sqlite_counterexample_output(cursor.target, cursor.private_cases[0].dataset, "score_only")
    assert wrong_cursor.rows == (("Twin",), ("Twin",))
    assert all(fixture.execution_status == "pending" for fixture in (and_fixture, fallback, cursor))


def test_domain_errors_are_not_semantic_negatives() -> None:
    target = ConjunctionTargetV1()
    with pytest.raises(ValueError):
        parse_sqlite_target({"task_kind": "conjunction", "min_score": True})
    with pytest.raises(ValueError):
        parse_sqlite_target(target.model_copy(update={"extra_authority": True}))
    with pytest.raises(ValueError):
        sqlite_oracle(target, LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(
            table="entries", rows=((1, "Bool", True, 60),),
        ),)))
    with pytest.raises(ValueError):
        sqlite_oracle(target, LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(
            table="entries", rows=((1, "UnsupportedFlag", 2, 60),),
        ),)))
    with pytest.raises(ValueError):
        sqlite_oracle(target, LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(
            table="entries", rows=((1, "Duplicate", 1, 60), (1, "Duplicate", 1, 61)),
        ),)))
    fixture = sqlite_private_fixture(target)
    with pytest.raises(ValueError):
        sqlite_fixture_hash(cast(SqlitePrivateFixtureV1, fixture.model_copy(update={"equivalent_queries": ("bad", "bad")})))
