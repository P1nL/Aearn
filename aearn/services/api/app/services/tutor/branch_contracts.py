"""Closed contracts for depth-one Tutor clarification branches."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BranchMessageClassification(StrEnum):
    NORMAL = "normal"
    CONTROL = "control"


class BranchControlKind(StrEnum):
    REQUEST_TOPIC_SWITCH = "request_topic_switch"
    CONFIRM_TOPIC_SWITCH = "confirm_topic_switch"
    CANCEL_TOPIC_SWITCH = "cancel_topic_switch"


class BranchResponseDisposition(StrEnum):
    ANSWER_AND_REFOCUS = "answer_and_refocus"
    OFFER_SWITCH = "offer_switch"
    CONFIRMED_SWITCH = "confirmed_switch"


class BranchAssistanceKind(StrEnum):
    NONE = "none"
    HINT = "hint"
    DIRECT_ANSWER = "direct_answer"


class BranchAssistanceReceiptKind(StrEnum):
    EXERCISE_HINT = "exercise_hint"
    REVIEW_HINT = "review_hint"
    TEACHING_ACTION = "teaching_action"


@dataclass(frozen=True, slots=True)
class BranchDispositionPolicy:
    disposition: BranchResponseDisposition
    resolves_branch: bool


def classify_branch_message(
    control_kind: BranchControlKind | str | None,
) -> tuple[BranchMessageClassification, BranchControlKind | None]:
    """Classify from an explicit typed control only; never infer from message text."""

    if control_kind is None:
        return BranchMessageClassification.NORMAL, None
    return BranchMessageClassification.CONTROL, BranchControlKind(str(control_kind))


def branch_response_policy(
    *,
    classification: BranchMessageClassification | str,
    control_kind: BranchControlKind | str | None,
    prior_disposition: BranchResponseDisposition | str | None,
) -> BranchDispositionPolicy:
    normalized_classification = BranchMessageClassification(str(classification))
    normalized_control = (
        BranchControlKind(str(control_kind)) if control_kind is not None else None
    )
    prior = (
        BranchResponseDisposition(str(prior_disposition))
        if prior_disposition is not None
        else None
    )
    if normalized_classification is BranchMessageClassification.NORMAL:
        if normalized_control is not None:
            raise ValueError("normal branch message cannot carry a control")
        return BranchDispositionPolicy(
            disposition=BranchResponseDisposition.ANSWER_AND_REFOCUS,
            resolves_branch=True,
        )
    if normalized_control is None:
        raise ValueError("control branch message requires an explicit control kind")
    if normalized_control is BranchControlKind.REQUEST_TOPIC_SWITCH:
        return BranchDispositionPolicy(
            disposition=BranchResponseDisposition.OFFER_SWITCH,
            resolves_branch=False,
        )
    if normalized_control is BranchControlKind.CONFIRM_TOPIC_SWITCH:
        if prior is not BranchResponseDisposition.OFFER_SWITCH:
            raise ValueError("topic switch confirmation requires a prior switch offer")
        return BranchDispositionPolicy(
            disposition=BranchResponseDisposition.CONFIRMED_SWITCH,
            resolves_branch=True,
        )
    return BranchDispositionPolicy(
        disposition=BranchResponseDisposition.ANSWER_AND_REFOCUS,
        resolves_branch=True,
    )


class _StrictBranchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TutorPublicBranchItemReferenceV1(_StrictBranchModel):
    item_sequence: int = Field(ge=1, le=400)
    branch_round: int = Field(ge=1, le=100)
    item_kind: Literal["message", "process"]
    item_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=160)
    item_role: Literal["learner", "tutor", "process"]

    @model_validator(mode="after")
    def validate_kind_role(self) -> "TutorPublicBranchItemReferenceV1":
        if self.item_kind == "process" and self.item_role != "process":
            raise ValueError("branch process reference role is invalid")
        if self.item_kind == "message" and self.item_role == "process":
            raise ValueError("branch message reference role is invalid")
        return self


class _TutorPublicBranchGroup(_StrictBranchModel):
    branch_id: str = Field(min_length=1, max_length=160)
    anchor_artifact_id: str = Field(min_length=1, max_length=160)
    teaching_session_id: str = Field(min_length=1, max_length=160)
    checkpoint_id: str = Field(min_length=1, max_length=160)
    disposition: BranchResponseDisposition | None = None
    round_count: int = Field(ge=1, le=100)
    item_count: int = Field(ge=1, le=400)
    collapsed: bool
    items: tuple[TutorPublicBranchItemReferenceV1, ...] = Field(
        min_length=1,
        max_length=400,
    )
    created_at: str = Field(min_length=1, max_length=80)
    resolved_at: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_membership(self) -> "_TutorPublicBranchGroup":
        if self.item_count != len(self.items):
            raise ValueError("branch item count is inconsistent")
        sequences = tuple(item.item_sequence for item in self.items)
        if sequences != tuple(range(1, len(self.items) + 1)):
            raise ValueError("branch item membership must be contiguous and ordered")
        if any(item.branch_round > self.round_count for item in self.items):
            raise ValueError("branch item round exceeds branch round count")
        return self


class TutorPublicBranchGroupV1(_TutorPublicBranchGroup):
    schema_version: Literal["tutor_conversation_branch_v1"] = "tutor_conversation_branch_v1"
    state: Literal["active", "resolved"]

    @model_validator(mode="after")
    def validate_group(self) -> "TutorPublicBranchGroupV1":
        if (self.state == "resolved") != (self.resolved_at is not None):
            raise ValueError("branch resolved timestamp is inconsistent")
        if self.collapsed != (self.state == "resolved"):
            raise ValueError("branch collapsed state is inconsistent")
        if self.state == "resolved" and self.disposition is None:
            raise ValueError("resolved branch requires a disposition")
        return self


class TutorPublicBranchGroupV2(_TutorPublicBranchGroup):
    """Authority retirement, never interpreted as an answered clarification."""

    schema_version: Literal["tutor_conversation_branch_v2"] = "tutor_conversation_branch_v2"
    state: Literal["superseded"] = "superseded"
    superseded_at: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_supersession(self) -> "TutorPublicBranchGroupV2":
        if self.resolved_at is not None or not self.collapsed:
            raise ValueError("superseded branch must be collapsed without resolution")
        return self


TutorPublicBranchGroup = TutorPublicBranchGroupV1 | TutorPublicBranchGroupV2


__all__ = (
    "BranchAssistanceKind",
    "BranchAssistanceReceiptKind",
    "BranchControlKind",
    "BranchDispositionPolicy",
    "BranchMessageClassification",
    "BranchResponseDisposition",
    "TutorPublicBranchGroupV1",
    "TutorPublicBranchGroupV2",
    "TutorPublicBranchGroup",
    "TutorPublicBranchItemReferenceV1",
    "branch_response_policy",
    "classify_branch_message",
)
