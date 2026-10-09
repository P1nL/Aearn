"""Synthetic exposure policy tests; no learner database or publication evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.learning.item_supply.exposure import (
    MAX_EXPOSURE_RECORDS,
    ExposureDecision,
    ExposureRecordV1,
    ExposureSnapshotV1,
    check_exposure,
)


NOW = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
HASH = "a" * 64
ITEM = "li:" + "b" * 64
OTHER_ITEM = "li:" + "c" * 64


def record(**updates: Any) -> ExposureRecordV1:
    values: dict[str, Any] = {
        "event_id": "event-1", "learner_ref": "learner-1", "scope_hash": HASH,
        "item_handle": ITEM, "candidate_family_id": "family-1",
        "kind": "hint", "occurred_at": NOW,
    }
    return ExposureRecordV1(**(values | updates))


def snapshot(*records: ExposureRecordV1) -> ExposureSnapshotV1:
    return ExposureSnapshotV1(learner_ref="learner-1", scope_hash=HASH, records=records)


def check(value: Any, **updates: Any) -> ExposureDecision:
    values: dict[str, Any] = {
        "learner_ref": "learner-1", "scope_hash": HASH, "item_handle": ITEM,
        "candidate_family_id": "family-1", "independent": True,
    }
    return check_exposure(value, **(values | updates))


def test_synthetic_empty_snapshot_permits_independence() -> None:
    decision = check(snapshot())
    assert decision.allowed
    assert decision.reason == "allowed"


@pytest.mark.parametrize("kind", ["attempted", "hint", "direct_answer"])
@pytest.mark.parametrize("same_identity", ["item", "family", "both"])
def test_any_exposure_blocks_same_item_or_family_independence(
    kind: str, same_identity: str,
) -> None:
    previous = record(
        kind=kind,
        item_handle=ITEM if same_identity in {"item", "both"} else OTHER_ITEM,
        candidate_family_id="family-1" if same_identity in {"family", "both"} else "other-family",
    )
    decision = check(snapshot(previous))
    assert not decision.allowed
    assert decision.reason == "already_exposed"


@pytest.mark.parametrize("kind", ["attempted", "hint", "direct_answer"])
def test_ordinary_practice_remediation_can_reuse_exposed_items(kind: str) -> None:
    assert check(snapshot(record(kind=kind)), independent=False).allowed


def test_unrelated_item_and_family_do_not_block() -> None:
    assert check(snapshot(record(item_handle=OTHER_ITEM, candidate_family_id="other-family"))).allowed


@pytest.mark.parametrize("independent", [True, False])
def test_snapshot_identity_mismatch_always_denies(independent: bool) -> None:
    assert check(snapshot(), learner_ref="learner-2", independent=independent).reason == "learner_mismatch"
    assert check(snapshot(), scope_hash="d" * 64, independent=independent).reason == "scope_mismatch"


@pytest.mark.parametrize("updates", [
    {"learner_ref": "learner-2"}, {"scope_hash": "d" * 64},
])
def test_nested_exposure_cannot_belong_to_different_snapshot(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        snapshot(record(**updates))


def test_exact_event_replay_is_deduplicated() -> None:
    event = record()
    replay = ExposureRecordV1.model_validate(event.model_dump(mode="python"))
    result = snapshot(event, replay)
    assert result.records == (event,)
    assert result.snapshot_hash == snapshot(event).snapshot_hash


@pytest.mark.parametrize("updates", [
    {"item_handle": OTHER_ITEM}, {"candidate_family_id": "other-family"},
    {"kind": "direct_answer"}, {"occurred_at": NOW + timedelta(seconds=1)},
    # The instant is equal, but the exact wire representation is not a replay.
    {"occurred_at": NOW.astimezone(timezone(timedelta(hours=8)))},
])
def test_duplicate_event_identity_with_changed_fact_is_conflict(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        snapshot(record(), record(**updates))


@pytest.mark.parametrize("updates", [
    {"event_id": ""}, {"event_id": "x" * 161}, {"event_id": "event\n"},
    {"learner_ref": " user"}, {"scope_hash": "A" * 64},
    {"item_handle": "li:not-a-hash"}, {"candidate_family_id": []},
    {"kind": "unknown"}, {"occurred_at": NOW.replace(tzinfo=None)},
    {"occurred_at": NOW.isoformat()}, {"occurred_at": 1},
    {"occurred_at": datetime(1969, 12, 31, tzinfo=timezone.utc)},
    {"private_answer": "not allowed"},
])
def test_strict_bounded_record_contract(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        record(**updates)


def test_frozen_tuple_snapshot_and_input_detachment() -> None:
    payload = record().model_dump(mode="python")
    result = ExposureSnapshotV1.model_validate({
        "learner_ref": "learner-1", "scope_hash": HASH, "records": (payload,),
    })
    payload["kind"] = "direct_answer"
    assert result.records[0].kind == "hint"
    with pytest.raises(ValidationError):
        result.learner_ref = "learner-2"
    with pytest.raises(ValidationError):
        result.records[0].kind = "direct_answer"
    with pytest.raises(ValidationError):
        ExposureSnapshotV1(learner_ref="learner-1", scope_hash=HASH, records=[record()])  # type: ignore[arg-type]


def test_record_count_bounded_before_replay_deduplication() -> None:
    event = record()
    assert len(snapshot(*((event,) * MAX_EXPOSURE_RECORDS)).records) == 1
    with pytest.raises(ValidationError):
        snapshot(*((event,) * (MAX_EXPOSURE_RECORDS + 1)))


@pytest.mark.parametrize("field,bad", [
    ("learner_ref", "learner-2"), ("scope_hash", "d" * 64),
    ("item_handle", "bad"), ("kind", "bad"),
    ("occurred_at", NOW.replace(tzinfo=None)), ("candidate_family_id", []),
    ("event_id", "x" * 161),
])
@pytest.mark.parametrize("bypass", ["copy", "construct"])
def test_function_revalidates_forged_nested_record(
    field: str, bad: Any, bypass: str,
) -> None:
    event = record()
    forged = (
        event.model_copy(update={field: bad}) if bypass == "copy"
        else ExposureRecordV1.model_construct(**(event.model_dump(mode="python") | {field: bad}))
    )
    value = snapshot().model_copy(update={"records": (forged,)})
    decision = check(value, independent=False)
    assert not decision.allowed
    assert decision.reason == "invalid_exposure"


@pytest.mark.parametrize("values", [
    {"records": []}, {"records": ("secret-provider-error",)},
    {"scope_hash": "invalid"}, {"records": (record(), record(kind="attempted"))},
    {"records": (record(),) * (MAX_EXPOSURE_RECORDS + 1)},
    {"raw_provider_error": "secret-provider-error"},
])
def test_function_revalidates_forged_root(values: dict[str, Any]) -> None:
    decision = check(snapshot().model_copy(update=values))
    assert decision == ExposureDecision(allowed=False, reason="invalid_exposure")
    assert "secret-provider-error" not in decision.model_dump_json()


@pytest.mark.parametrize("query", [
    {"independent": 1}, {"independent": "false"}, {"learner_ref": []},
    {"scope_hash": "bad"}, {"item_handle": "bad"}, {"candidate_family_id": ""},
])
def test_function_query_is_strict_and_fail_closed(query: dict[str, Any]) -> None:
    assert check(snapshot(), **query).reason == "invalid_exposure"


@pytest.mark.parametrize("value", [None, {}, "secret", 1])
def test_wrong_snapshot_type_denies_without_raw_errors(value: Any) -> None:
    assert check(value).reason == "invalid_exposure"


def test_missing_construct_fields_fail_closed() -> None:
    assert check(ExposureSnapshotV1.model_construct()).reason == "invalid_exposure"


def test_hidden_nested_extra_state_cannot_be_dropped_to_allow_or_hash() -> None:
    forged = record().model_copy(update={"private_answer": "secret-provider-error"})
    result = snapshot().model_copy(update={"records": (forged,)})
    assert check(result, independent=False).reason == "invalid_exposure"
    with pytest.raises(ValueError, match="^invalid exposure snapshot$"):
        _ = result.snapshot_hash


def test_construct_nested_extra_storage_fails_closed() -> None:
    forged = record()
    object.__setattr__(forged, "__pydantic_extra__", {"secret": "not allowed"})
    assert check(snapshot().model_copy(update={"records": (forged,)})).reason == "invalid_exposure"


def test_hash_revalidates_nested_copy_bypass_with_safe_error() -> None:
    forged = record().model_copy(update={"kind": "secret-provider-error"})
    result = snapshot().model_copy(update={"records": (forged,)})
    with pytest.raises(ValueError, match="^invalid exposure snapshot$"):
        _ = result.snapshot_hash


def test_snapshot_subclass_is_not_an_authority_substitute() -> None:
    class ForgedSnapshot(ExposureSnapshotV1):
        pass

    assert check(ForgedSnapshot(learner_ref="learner-1", scope_hash=HASH)).reason == "invalid_exposure"


@pytest.mark.parametrize("values", [
    {"allowed": 1, "reason": "allowed"}, {"allowed": True, "reason": "scope_mismatch"},
    {"allowed": False, "reason": "allowed"}, {"allowed": False, "reason": "secret"},
])
def test_decision_is_strict_safe_and_consistent(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ExposureDecision(**values)
