"""Shared structured judgement module.

Provides page-agnostic types and normalization logic for AI-produced
structured judgements. Feature services define their own policies and
fallback text; this module owns only the generic schema and the
normalization algorithm.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError


JudgementStatus = Literal["confirmed", "ambiguous", "missing", "unsupported"]


class StructuredJudgement(BaseModel):
    """A single field-level judgement produced by the LLM."""

    status: JudgementStatus
    ambiguity_type: str | None = None
    evidence: str | None = None
    ambiguity_reason: str | None = None
    clarification_question: str | None = None


@dataclass(frozen=True)
class FieldPolicy:
    """Policy for one field in a judgement set."""

    name: str
    required: bool = True
    fallback_question: str = ""
    blocks_on: tuple[JudgementStatus, ...] = ("ambiguous", "missing", "unsupported")


@dataclass(frozen=True)
class JudgementPolicy:
    """Page-specific policy that drives normalization behavior.

    Fields are listed in clarification priority order (highest first).
    """

    fields: Sequence[FieldPolicy]
    default_fallback_question: str = ""

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def get_field(self, name: str) -> FieldPolicy | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass(frozen=True)
class NormalizedJudgementResult:
    """Output of the normalization pass."""

    ready: bool
    cleared_fields: tuple[str, ...]
    blocking_fields: tuple[str, ...]
    clarification_question: str | None


def coerce_structured_judgements(
    value: object,
    policy: JudgementPolicy,
) -> dict[str, StructuredJudgement]:
    """Parse arbitrary model judgement payloads into policy-shaped judgements."""

    payload = value if isinstance(value, Mapping) else {}
    judgements: dict[str, StructuredJudgement] = {}
    for field_policy in policy.fields:
        raw = payload.get(field_policy.name)
        if isinstance(raw, StructuredJudgement):
            judgement = raw
        elif isinstance(raw, Mapping):
            try:
                judgement = StructuredJudgement.model_validate(raw)
            except ValidationError:
                judgement = _unsupported_judgement(field_policy, policy)
        else:
            judgement = _missing_judgement(field_policy, policy)
        judgements[field_policy.name] = judgement
    return judgements


def normalize_judgements(
    field_values: Mapping[str, object],
    judgements: Mapping[str, StructuredJudgement],
    policy: JudgementPolicy,
    *,
    value_present_fn: ValuePresentFn | None = None,
) -> NormalizedJudgementResult:
    """Apply policy-based normalization to a set of field judgements.

    For each field in the policy:
      - If the judgement status is not 'confirmed', the field value is cleared.
      - If the field blocks readiness per policy, it becomes a blocker.

    Returns a result with readiness, cleared fields, blockers, and the
    highest-priority clarification question.
    """

    is_present = value_present_fn or _default_value_present
    cleared: list[str] = []
    blockers: list[str] = []

    for field_policy in policy.fields:
        name = field_policy.name
        judgement = judgements.get(name)

        if judgement is not None and judgement.status != "confirmed":
            cleared.append(name)

        if _field_blocks_ready(
            field_policy, judgement, field_values.get(name), is_present
        ):
            blockers.append(name)

    ready = not blockers
    question = (
        None
        if ready
        else _select_clarification_question(blockers, judgements, policy)
    )

    return NormalizedJudgementResult(
        ready=ready,
        cleared_fields=tuple(cleared),
        blocking_fields=tuple(blockers),
        clarification_question=question,
    )


ValuePresentFn = Callable[[str, object], bool]


def _missing_judgement(
    field_policy: FieldPolicy,
    policy: JudgementPolicy,
) -> StructuredJudgement:
    return StructuredJudgement(
        status="missing",
        ambiguity_reason="judgement payload missing",
        clarification_question=field_policy.fallback_question or policy.default_fallback_question,
    )


def _unsupported_judgement(
    field_policy: FieldPolicy,
    policy: JudgementPolicy,
) -> StructuredJudgement:
    return StructuredJudgement(
        status="unsupported",
        ambiguity_reason="judgement payload invalid",
        clarification_question=field_policy.fallback_question or policy.default_fallback_question,
    )


def _default_value_present(field_name: str, value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _field_blocks_ready(
    field_policy: FieldPolicy,
    judgement: StructuredJudgement | None,
    value: object,
    is_present: ValuePresentFn,
) -> bool:
    if field_policy.required:
        if not is_present(field_policy.name, value):
            return True
        if judgement is not None and judgement.status in field_policy.blocks_on:
            return True
    else:
        if judgement is None:
            return False
        if judgement.status in field_policy.blocks_on:
            return True
    return False


def _select_clarification_question(
    blockers: Sequence[str],
    judgements: Mapping[str, StructuredJudgement],
    policy: JudgementPolicy,
) -> str:
    for name in blockers:
        judgement = judgements.get(name)
        if judgement is not None:
            question = (judgement.clarification_question or "").strip()
            if question:
                return question
        fp = policy.get_field(name)
        if fp is not None and fp.fallback_question:
            return fp.fallback_question
    return policy.default_fallback_question
