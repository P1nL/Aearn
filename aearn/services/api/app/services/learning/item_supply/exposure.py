"""Pure, caller-supplied exposure facts; never publication or owner authority."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.services.grounding.autonomous.contracts import FrozenContract
from app.services.learning.item_bank.contracts import canonical_hash


_Identifier = Annotated[
    str, Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
]
_Hash = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
_ItemHandle = Annotated[
    str, Field(min_length=67, max_length=67, pattern=r"^li:[0-9a-f]{64}$")
]
ExposureKind = Literal["attempted", "hint", "direct_answer"]
ExposureReason = Literal[
    "allowed", "invalid_exposure", "learner_mismatch", "scope_mismatch", "already_exposed"
]
MAX_EXPOSURE_RECORDS = 4096


class _ExposureContract(FrozenContract):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class ExposureRecordV1(_ExposureContract):
    event_id: _Identifier
    learner_ref: _Identifier
    scope_hash: _Hash
    item_handle: _ItemHandle
    candidate_family_id: _Identifier
    kind: ExposureKind
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def bounded_timestamp(self) -> ExposureRecordV1:
        if self.occurred_at.year < 1970:
            raise ValueError("invalid exposure timestamp")
        return self


class ExposureSnapshotV1(_ExposureContract):
    learner_ref: _Identifier
    scope_hash: _Hash
    records: tuple[ExposureRecordV1, ...] = Field(
        default=(), max_length=MAX_EXPOSURE_RECORDS
    )

    @model_validator(mode="after")
    def exact_identity_and_replay(self) -> ExposureSnapshotV1:
        by_event: dict[str, ExposureRecordV1] = {}
        for record in self.records:
            if record.learner_ref != self.learner_ref or record.scope_hash != self.scope_hash:
                raise ValueError("invalid exposure record scope")
            previous = by_event.get(record.event_id)
            if previous is not None:
                if previous.model_dump(mode="json") != record.model_dump(mode="json"):
                    raise ValueError("conflicting exposure event")
            else:
                by_event[record.event_id] = record
        # Exact duplicate event replays are facts once, not extra exposure counts.
        object.__setattr__(self, "records", tuple(by_event.values()))
        return self

    @property
    def snapshot_hash(self) -> str:
        try:
            return canonical_hash(_checked_snapshot(self).model_dump(mode="json"))
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise ValueError("invalid exposure snapshot") from None


class ExposureDecision(_ExposureContract):
    allowed: bool
    reason: ExposureReason

    @model_validator(mode="after")
    def consistent_decision(self) -> ExposureDecision:
        if self.allowed != (self.reason == "allowed"):
            raise ValueError("invalid exposure decision")
        return self


class _ExposureQuery(_ExposureContract):
    learner_ref: _Identifier
    scope_hash: _Hash
    item_handle: _ItemHandle
    candidate_family_id: _Identifier
    independent: bool


def _checked_snapshot(snapshot: ExposureSnapshotV1) -> ExposureSnapshotV1:
    # Pydantic can discard construct/copy extra state during revalidation; inspect
    # it first so hidden fields cannot disappear into an apparently valid hash.
    if type(snapshot) is not ExposureSnapshotV1:
        raise ValueError("invalid exposure snapshot")
    if (
        set(snapshot.__dict__) != set(ExposureSnapshotV1.model_fields)
        or snapshot.__pydantic_extra__
        or type(snapshot.records) is not tuple
        or len(snapshot.records) > MAX_EXPOSURE_RECORDS
    ):
        raise ValueError("invalid exposure snapshot")
    for record in snapshot.records:
        if (
            type(record) is not ExposureRecordV1
            or set(record.__dict__) != set(ExposureRecordV1.model_fields)
            or record.__pydantic_extra__
        ):
            raise ValueError("invalid exposure record")
    return ExposureSnapshotV1.model_validate(snapshot)


def check_exposure(
    snapshot: ExposureSnapshotV1,
    *,
    learner_ref: str,
    scope_hash: str,
    item_handle: str,
    candidate_family_id: str,
    independent: bool,
) -> ExposureDecision:
    """Fail closed on forged snapshots; ordinary practice may reuse exposure.

    Independence forbids any prior attempted/hint/direct-answer exposure to
    either the same immutable item or its candidate family. Scope and learner
    validation applies even when independence is not required. No clock, storage
    lookup, private-owner delegation or publication authorization happens here.
    """
    try:
        if type(snapshot) is not ExposureSnapshotV1:
            return ExposureDecision(allowed=False, reason="invalid_exposure")
        # Revalidation recursively checks copy/construct payloads, not just the root.
        checked = _checked_snapshot(snapshot)
        query = _ExposureQuery(
            learner_ref=learner_ref,
            scope_hash=scope_hash,
            item_handle=item_handle,
            candidate_family_id=candidate_family_id,
            independent=independent,
        )
    except (ValueError, TypeError, AttributeError, OverflowError):
        return ExposureDecision(allowed=False, reason="invalid_exposure")
    if checked.learner_ref != query.learner_ref:
        return ExposureDecision(allowed=False, reason="learner_mismatch")
    if checked.scope_hash != query.scope_hash:
        return ExposureDecision(allowed=False, reason="scope_mismatch")
    if query.independent and any(
        record.item_handle == query.item_handle
        or record.candidate_family_id == query.candidate_family_id
        for record in checked.records
    ):
        return ExposureDecision(allowed=False, reason="already_exposed")
    return ExposureDecision(allowed=True, reason="allowed")
