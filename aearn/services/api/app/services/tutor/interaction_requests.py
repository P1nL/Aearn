"""Closed interaction-request authority shared by Tutor persistence and public adapters."""
from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Mapping

from app.agents.harness.contracts import TutorTurnCompletionReason


TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION = "tutor_interaction_request_v1"
TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION = "tutor_authority_receipt_v1"


class TutorInteractionRequestKind(StrEnum):
    CLARIFICATION = "clarification"
    PLANNING_INPUT = "planning_input"
    APPROVAL = "approval"
    CAPABILITY_RESULT = "capability_result"
    EXTERNAL_RESULT = "external_result"


class TutorInteractionRequestActor(StrEnum):
    LEARNER = "learner"
    AUTHORITY = "authority"


class TutorInteractionRequestState(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    DENIED = "denied"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


def actor_for_request(kind: TutorInteractionRequestKind) -> TutorInteractionRequestActor:
    if kind in {TutorInteractionRequestKind.CAPABILITY_RESULT, TutorInteractionRequestKind.EXTERNAL_RESULT}:
        return TutorInteractionRequestActor.AUTHORITY
    return TutorInteractionRequestActor.LEARNER


def completion_reason_for_request(kind: TutorInteractionRequestKind) -> TutorTurnCompletionReason:
    if kind is TutorInteractionRequestKind.APPROVAL:
        return TutorTurnCompletionReason.AWAITING_APPROVAL
    if actor_for_request(kind) is TutorInteractionRequestActor.AUTHORITY:
        return TutorTurnCompletionReason.AWAITING_AUTHORITY
    return TutorTurnCompletionReason.AWAITING_USER


def public_item_kind(kind: TutorInteractionRequestKind) -> str:
    return "approval" if kind is TutorInteractionRequestKind.APPROVAL else "elicitation"


def canonical_payload_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
