"""Two focused offline cases. No SQL runtime, provider, Docker or DB connection."""
from __future__ import annotations

import json

import pytest

from app.services.learning.item_bank.contracts import LearningItemSqlDatasetTableV2, LearningItemSqlDatasetV2
from app.services.learning.item_supply.finite_family_transfer_sql_v2 import (
    SqliteFamilyTransferPlanV2,
    build_sqlite_family_transfer_plan_v2,
    sqlite_family_transfer_plan_hash_v2,
)
from app.services.learning.item_supply.finite_targets.sqlite_predicates import ConjunctionTargetV1
from app.services.learning.item_supply.finite_targets.sqlite_predicates_v2 import (
    SQLITE_TASK_KINDS_V2,
    SqlitePrivateFixtureV2,
    SqliteTaskKindV2,
    parse_sqlite_target_v2,
    sqlite_counterexample_output_v2,
    sqlite_fixture_hash_v2,
    sqlite_oracle_v2,
    sqlite_private_fixture_v2,
    sqlite_public_task_hash_v2,
    sqlite_public_task_v2,
    sqlite_target_v2,
)

# Independent hand-derived ordered multisets from the approved fifteen rows.
_NAMES: dict[SqliteTaskKindV2, tuple[str, ...]] = {
    "conjunction": ("Both", "Cursor", "After", "NullB", "Twin", "Twin"),
    "override_fallback": ("NullB", "Fallback", "Cursor", "After", "Twin", "Twin", "Both", "Below", "NullScore"),
    "exclusive": ("NullB", "Fallback", "Cursor", "After", "OnlyB", "Twin", "Twin", "Veto", "Below", "NullScore"),
    "keyset_after": ("After", "OnlyB", "Twin", "Twin", "NullNone", "ZeroNull", "Veto", "Both", "Below"),
}
_LOCK = "a" * 64  # Only a plan input; not an execution lock attestation.


def test_four_oracles_private_tasks_and_twelve_complete_identity_predictions() -> None:
    tasks = tuple(sqlite_public_task_v2(sqlite_target_v2(kind)) for kind in SQLITE_TASK_KINDS_V2)
    assert len({task.content.model_dump_json() for task in tasks}) == 1
    for public in tasks:
        kind = public.target.task_kind
        assert tuple(column.name for column in public.content.tables[0].columns) == ("id", "name", "flag_a", "flag_b", "score")
        assert len(public.content.public_dataset.tables[0].rows) == 15
        truth = sqlite_oracle_v2(public.target, public.content.public_dataset)
        assert truth.columns == ("name",)
        assert truth.rows == tuple((name,) for name in _NAMES[kind])
        fixture = sqlite_private_fixture_v2(public.target)
        assert fixture.public_task == public
        visible, hidden, no_match, empty = fixture.private_cases
        assert visible.case_type == "visible" and visible.expected_output == truth
        assert hidden.expected_output.rows == tuple(("Private " + name,) for name in _NAMES[kind])
        assert no_match.expected_output.rows == empty.expected_output.rows == ()
        assert len(set(fixture.equivalent_queries)) == 2
        assert all(query.startswith("SELECT name FROM entries WHERE (") for query in fixture.equivalent_queries)
        assert all(counter.failing_case_ids and counter.execution_status == "pending" for counter in fixture.counterexamples)
        assert all(sqlite_counterexample_output_v2(public.target, visible.dataset, counter.fault) != truth
                   for counter in fixture.counterexamples)
        public_wire = public.model_dump_json()
        assert all(private_key not in public_wire for private_key in (
            "expected_output", "private_cases", "equivalent_queries", "counterexamples", "Private "))
        assert all(query not in public_wire for query in fixture.equivalent_queries)
        assert fixture.execution_status == fixture.family_independence_status == "pending"
        roundtrip = SqlitePrivateFixtureV2.model_validate_json(fixture.model_dump_json())
        assert sqlite_fixture_hash_v2(roundtrip) == sqlite_fixture_hash_v2(fixture)
        # One boundary seed only, not a sweep: id/score/parameter translation
        # preserves NULL/multiplicity/order while using new target identities.
        shifted = sqlite_public_task_v2(sqlite_target_v2(kind, seed=255))
        assert sqlite_oracle_v2(shifted.target, shifted.content.public_dataset) == truth

    plan = build_sqlite_family_transfer_plan_v2(tasks, runtime_lock_hash=_LOCK)
    assert len(plan.pairs) == 6 and plan.construction == "planned" and not plan.publication_enabled
    directions = tuple(direction for pair in plan.pairs for direction in (pair.forward, pair.backward))
    assert len(directions) == 12
    assert len({(d.source_reference.family_id, d.target_reference.family_id) for d in directions}) == 12
    for direction in directions:
        source, target, transfer = direction.source_reference, direction.target_reference, direction.transfer_check
        assert source.required_scorer_result == target.required_scorer_result == "pass"
        assert transfer.required_scorer_result == "reject"
        assert transfer.submission == source.submission == transfer.request.submission
        assert transfer.predicted_output.rows == tuple((name,) for name in _NAMES[source.public_task.target.task_kind])
        assert transfer.target_expected.rows == tuple((name,) for name in _NAMES[target.public_task.target.task_kind])
        assert transfer.predicted_output != transfer.target_expected
        assert not transfer.target_expected_truncated and not transfer.predicted_output_truncated
        assert direction.identity_symbol_pairs == tuple((name, name) for name in ("entries", "id", "name", "flag_a", "flag_b", "score"))
        assert direction.identity_parameter_pairs == (("min_score", "min_score", 60, 60),
            ("cut_score", "cut_score", 70, 70), ("cut_id", "cut_id", 4, 4))
        cases = json.loads(transfer.request.hidden_test_bundle_json)
        assert cases[0]["dataset"] == target.public_task.content.public_dataset.model_dump(mode="json")
        assert len(cases[0]["tables"][0]["columns"]) == 5
        assert transfer.required_terminal == "successful_read_only_select"
        assert direction.execution_status == transfer.execution_status == "not_performed"
        assert direction.review_status == "four_role_reviews_pending"
        assert direction.authority == "not_family_pair_evidence"
    roundtrip_plan = SqliteFamilyTransferPlanV2.model_validate_json(plan.model_dump_json())
    digest = sqlite_family_transfer_plan_hash_v2(plan)
    assert sqlite_family_transfer_plan_hash_v2(roundtrip_plan) == digest
    assert sqlite_family_transfer_plan_hash_v2(build_sqlite_family_transfer_plan_v2(
        tuple(reversed(tasks)), runtime_lock_hash=_LOCK)) == digest


def test_fail_closed_domains_exact_rebuild_shared_seed_and_guidance_scope() -> None:
    target = sqlite_target_v2("conjunction")
    with pytest.raises(ValueError):
        parse_sqlite_target_v2(ConjunctionTargetV1())
    with pytest.raises(ValueError):
        sqlite_target_v2("conjunction", seed=True)
    with pytest.raises(ValueError):
        parse_sqlite_target_v2(target.model_copy(update={"extra_authority": True}))
    # Validate unused public columns too; neither malformed rows nor missing
    # columns are legitimate family-transfer counterexamples.
    for rows in (((1, "Bad", 1, 2, 60),), ((1, "Bool", 1, True, 60),),
                 ((1, "A", 1, 0, 60), (1, "B", 1, 0, 61)), ((1, "Short", 1, 60),)):
        with pytest.raises(ValueError):
            sqlite_oracle_v2(target, LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(table="entries", rows=rows),)))
    tasks = tuple(sqlite_public_task_v2(sqlite_target_v2(kind)) for kind in SQLITE_TASK_KINDS_V2)
    changed_seed = sqlite_public_task_v2(sqlite_target_v2("keyset_after", seed=1))
    with pytest.raises(ValueError, match="same_seed"):
        build_sqlite_family_transfer_plan_v2(tasks[:3] + (changed_seed,), runtime_lock_hash=_LOCK)
    guided = sqlite_public_task_v2(target, guided=True)
    assert guided.purpose == "remediation" and guided.guided and "引导" in guided.instruction
    assert sqlite_public_task_hash_v2(guided) != sqlite_public_task_hash_v2(tasks[0])
    with pytest.raises(ValueError, match="unguided"):
        build_sqlite_family_transfer_plan_v2((guided,) + tasks[1:], runtime_lock_hash=_LOCK)
    with pytest.raises(ValueError, match="not_exact"):
        sqlite_public_task_hash_v2(tasks[0].model_copy(update={"instruction": "Altered task"}))
    plan = build_sqlite_family_transfer_plan_v2(tasks, runtime_lock_hash=_LOCK)
    with pytest.raises(ValueError):
        sqlite_family_transfer_plan_hash_v2(plan.model_copy(update={"publication_enabled": True}))
    with pytest.raises(ValueError):
        build_sqlite_family_transfer_plan_v2(tasks, runtime_lock_hash="0" * 64)
