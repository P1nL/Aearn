"""Primary-only, redacted-outbox Curator for Child 05 target projections."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agents.harness.capabilities import contains_forbidden_execution_target
from app.agents.harness.contracts import TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION
from app.core.teaching_safety import sanitize_message_content
from app.core.config import Settings, get_settings
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    OpenAICompatibleClient,
)
from app.services.tutor.learner_state import (
    TutorCurationSource,
    TutorLearnerStateConflict,
    TutorLearnerStateRepository,
)
from app.services.tutor.persistence import (
    PostgresTutorRepository,
    TutorCurationProposalReceipt,
    TutorIdempotencyConflict,
    TutorRunNotFound,
)
from app.services.tutor.proactive import CurationProcessOutcome, TutorCurationJob


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _FrozenCurationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CurationContextSummaryProposalV1(_FrozenCurationModel):
    kind: Literal["context_summary"]
    summary: str = Field(min_length=1, max_length=280)
    confidence: Literal["low", "medium", "high"]

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _learner_text(value, label="context summary", maximum=280)


class CurationContextSummaryProposalV2(_FrozenCurationModel):
    kind: Literal["context_summary"]
    schema_version: Literal["tutor_context_summary_v2"]
    current_goal: str | None = Field(default=None, max_length=240)
    confirmed_facts: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    completed_steps: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    rejected_paths: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    open_questions: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    learner_preferences: tuple[str, ...] = Field(default_factory=tuple, max_length=6)
    confidence: Literal["low", "medium", "high"]

    @field_validator("current_goal")
    @classmethod
    def _validate_goal(cls, value: str | None) -> str | None:
        return _learner_text(value, label="context summary current goal", maximum=240) if value is not None else None

    @field_validator(
        "confirmed_facts",
        "completed_steps",
        "rejected_paths",
        "open_questions",
        "learner_preferences",
    )
    @classmethod
    def _validate_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_learner_text(item, label="context summary item", maximum=240) for item in value)

    @model_validator(mode="after")
    def _require_semantic_content(self) -> Self:
        if self.current_goal is None and not any(
            (
                self.confirmed_facts,
                self.completed_steps,
                self.rejected_paths,
                self.open_questions,
                self.learner_preferences,
            )
        ):
            raise ValueError("structured context summary cannot be empty")
        return self


class CurationMemoryEntryProposalV1(_FrozenCurationModel):
    kind: Literal["memory_entry"]
    category: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=180)
    confidence: Literal["low", "medium", "high"]

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        return _identifier(value, label="memory category")

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, value: str) -> str:
        return _learner_text(value, label="memory statement", maximum=180)


class CurationNoActionProposalV1(_FrozenCurationModel):
    kind: Literal["no_action"]
    code: str = Field(min_length=1, max_length=120)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        return _identifier(value, label="curation no-action code")


CurationProjectionProposal: TypeAlias = (
    CurationContextSummaryProposalV1 | CurationContextSummaryProposalV2 | CurationMemoryEntryProposalV1
)
CurationOutput: TypeAlias = CurationProjectionProposal | CurationNoActionProposalV1


@dataclass(frozen=True)
class CurationGatewayResult:
    state: Literal["proposal", "no_action", "retryable"]
    code: str
    proposal: CurationProjectionProposal | None = None

    def __post_init__(self) -> None:
        _identifier(self.code, label="curation gateway code")
        if self.state == "proposal" and self.proposal is None:
            raise ValueError("a curation proposal result requires a proposal")
        if self.state != "proposal" and self.proposal is not None:
            raise ValueError("non-proposal curation result cannot carry a proposal")


class CurationJsonClient(Protocol):
    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = 0.2,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
    ) -> object: ...


class CurationGateway(Protocol):
    def propose(self, *, source: TutorCurationSource) -> CurationGatewayResult: ...


class PrimaryCurationGateway:
    """Call only the configured primary provider/model, with no fallback path."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: CurationJsonClient | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        configured_limit = self._settings.tutor_curation_max_output_tokens
        self._max_output_tokens = configured_limit if max_output_tokens is None else max_output_tokens
        if self._max_output_tokens < 0:
            raise ValueError("curation max output tokens must be non-negative")
        self._client = client
        self._timeout_seconds = timeout_seconds

    def propose(self, *, source: TutorCurationSource) -> CurationGatewayResult:
        if self._max_output_tokens == 0:
            return CurationGatewayResult(state="no_action", code="curation_output_disabled")
        try:
            client = self._client if self._client is not None else OpenAICompatibleClient(self._settings)
            response = client.complete_json(
                _build_messages(source=source),
                temperature=None,
                max_tokens=self._max_output_tokens,
                timeout_seconds=self._timeout_seconds,
                output_schema=curation_output_schema(source.projection_kind),
                schema_name=curation_output_schema_name(source.projection_kind),
            )
            content = getattr(response, "content", None)
            if not isinstance(content, Mapping):
                return CurationGatewayResult(state="retryable", code="curation_model_invalid_response")
            parsed = parse_curation_output(content)
            if source.projection_kind == "context_summary" and not isinstance(
                parsed, (CurationContextSummaryProposalV2, CurationNoActionProposalV1)
            ):
                return CurationGatewayResult(state="retryable", code="curation_model_invalid_response")
            if source.projection_kind == "memory_or_summary" and isinstance(
                parsed, CurationContextSummaryProposalV2
            ):
                return CurationGatewayResult(state="retryable", code="curation_model_invalid_response")
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError, ValidationError, TypeError, ValueError):
            return CurationGatewayResult(state="retryable", code="curation_model_unavailable")
        except Exception:
            # Never turn an adapter failure into a provider/model fallback.
            return CurationGatewayResult(state="retryable", code="curation_model_unavailable")
        if isinstance(parsed, CurationNoActionProposalV1):
            return CurationGatewayResult(state="no_action", code=parsed.code)
        return CurationGatewayResult(state="proposal", code="curation_proposal_ready", proposal=parsed)


class TutorMemoryCurator:
    """Validate one redacted outbox source and commit one typed target projection."""

    def __init__(
        self,
        *,
        repository: PostgresTutorRepository,
        learner_state: TutorLearnerStateRepository,
        gateway: CurationGateway,
    ) -> None:
        self._repository = repository
        self._learner_state = learner_state
        self._gateway = gateway

    def process(self, *, job: TutorCurationJob, lease_owner_id: str, now: datetime) -> CurationProcessOutcome:
        source, code = self._learner_state.curation_source_for_job(
            job_id=job.job_id,
            user_id=job.user_id,
            lease_owner_id=lease_owner_id,
            lease_generation=job.lease_generation,
            now=_utc(now),
        )
        if source is None:
            return CurationProcessOutcome(state="no_action", code=code)
        result = self._gateway.propose(source=source)
        if result.state == "retryable":
            return CurationProcessOutcome(state="retryable", code=result.code)
        try:
            if result.state == "no_action":
                self._record_non_projection(
                    source=source,
                    kind="context_summary",
                    state="no_action",
                    confidence="low",
                    code=result.code,
                    payload_hash=_hash({"kind": "no_action", "code": result.code}),
                    now=_utc(now),
                )
                return CurationProcessOutcome(state="no_action", code=result.code)
            proposal = result.proposal
            if proposal is None:
                return CurationProcessOutcome(state="retryable", code="curation_proposal_missing")
            return self._commit_projection(source=source, proposal=proposal, now=_utc(now))
        except (TutorIdempotencyConflict, TutorLearnerStateConflict, TutorRunNotFound, ValueError):
            return CurationProcessOutcome(state="retryable", code="curation_persistence_retryable")

    def _commit_projection(
        self,
        *,
        source: TutorCurationSource,
        proposal: CurationProjectionProposal,
        now: datetime,
    ) -> CurationProcessOutcome:
        if source.projection_kind == "context_summary" and not isinstance(
            proposal, CurationContextSummaryProposalV2
        ):
            return CurationProcessOutcome(state="retryable", code="curation_summary_schema_invalid")
        if source.projection_kind == "memory_or_summary" and isinstance(
            proposal, CurationContextSummaryProposalV2
        ):
            return CurationProcessOutcome(state="retryable", code="curation_projection_kind_invalid")
        with self._repository._conn.transaction():  # noqa: SLF001 - exact shared transaction is the target boundary.
            refreshed, code = self._learner_state.curation_source_for_job(
                job_id=source.job_id,
                user_id=source.user_id,
                lease_owner_id=source.lease_owner_id,
                lease_generation=source.lease_generation,
                now=now,
            )
            if refreshed is None:
                return CurationProcessOutcome(state="no_action", code=code)
            proposal_receipt = self._record_generic_proposal(source=refreshed, proposal=proposal, now=now)
            if proposal_receipt.state != "pending":
                self._learner_state.record_curation_projection_receipt(
                    source=refreshed,
                    proposal_id=proposal_receipt.proposal_id,
                    state=_receipt_state(proposal_receipt.state),
                    target_kind="none",
                    target_id=None,
                    code="curation_projection_not_pending",
                    now=now,
                )
                return CurationProcessOutcome(state="no_action", code="curation_projection_not_pending")
            if isinstance(proposal, CurationContextSummaryProposalV2):
                self._learner_state.commit_structured_context_summary_projection(
                    source=refreshed,
                    proposal_id=proposal_receipt.proposal_id,
                    summary=_summary_overview(proposal),
                    summary_json={
                        "schema_version": proposal.schema_version,
                        "current_goal": proposal.current_goal,
                        "confirmed_facts": list(proposal.confirmed_facts),
                        "completed_steps": list(proposal.completed_steps),
                        "rejected_paths": list(proposal.rejected_paths),
                        "open_questions": list(proposal.open_questions),
                        "learner_preferences": list(proposal.learner_preferences),
                    },
                    code="curation_context_summary_committed",
                    now=now,
                )
            elif isinstance(proposal, CurationContextSummaryProposalV1):
                self._learner_state.commit_context_summary_projection(
                    source=refreshed,
                    proposal_id=proposal_receipt.proposal_id,
                    summary=proposal.summary,
                    code="curation_context_summary_committed",
                    now=now,
                )
            else:
                self._learner_state.commit_inference_memory_projection(
                    source=refreshed,
                    proposal_id=proposal_receipt.proposal_id,
                    category=proposal.category,
                    statement=proposal.statement,
                    confidence=proposal.confidence,
                    code="curation_memory_entry_committed",
                    now=now,
                )
        return CurationProcessOutcome(state="completed", code="curation_projection_committed")

    def _record_non_projection(
        self,
        *,
        source: TutorCurationSource,
        kind: Literal["context_summary", "memory_entry"],
        state: Literal["no_action", "stale", "failed"],
        confidence: Literal["low", "medium", "high"],
        code: str,
        payload_hash: str,
        now: datetime,
    ) -> None:
        with self._repository._conn.transaction():  # noqa: SLF001 - pair generic evidence and domain receipt atomically.
            receipt = self._repository.record_curation_proposal(
                user_id=source.user_id,
                outbox_id=source.outbox_id,
                kind=kind,
                state=state,
                payload={"safe_hash": payload_hash},
                confidence=confidence,
                policy_version=source.policy_version,
                memory_setting_version=source.memory_setting_version,
                created_at=now,
            )
            self._learner_state.record_curation_projection_receipt(
                source=source,
                proposal_id=receipt.proposal_id,
                state=_receipt_state(receipt.state),
                target_kind="none",
                target_id=None,
                code=code,
                now=now,
            )

    def _record_generic_proposal(
        self,
        *,
        source: TutorCurationSource,
        proposal: CurationProjectionProposal,
        now: datetime,
    ) -> TutorCurationProposalReceipt:
        if isinstance(proposal, CurationContextSummaryProposalV2):
            kind: Literal["context_summary", "memory_entry"] = "context_summary"
            confidence = proposal.confidence
            payload_hash = _hash({"summary": proposal.model_dump(mode="json"), "kind": kind})
        elif isinstance(proposal, CurationContextSummaryProposalV1):
            kind = "context_summary"
            confidence = proposal.confidence
            payload_hash = _hash({"summary": proposal.summary, "kind": kind})
        else:
            kind = "memory_entry"
            confidence = proposal.confidence
            payload_hash = _hash(
                {"category": proposal.category, "statement": proposal.statement, "kind": kind}
            )
        return self._repository.record_curation_proposal(
            user_id=source.user_id,
            outbox_id=source.outbox_id,
            kind=kind,
            state="pending",
            payload={"safe_hash": payload_hash},
            confidence=confidence,
            policy_version=source.policy_version,
            memory_setting_version=source.memory_setting_version,
            created_at=now,
        )


def build_curation_proposal_processor(
    *,
    conn,
    settings: Settings | None = None,
) -> TutorMemoryCurator:
    """Create the feature-gated processor; a zero output budget remains a no-call path."""

    resolved_settings = settings or get_settings()
    return TutorMemoryCurator(
        repository=PostgresTutorRepository(conn),
        learner_state=TutorLearnerStateRepository(conn),
        gateway=PrimaryCurationGateway(settings=resolved_settings),
    )


def curation_output_schema(projection_kind: str) -> dict[str, object]:
    if projection_kind == "context_summary":
        return {
            "oneOf": [
                CurationContextSummaryProposalV2.model_json_schema(),
                CurationNoActionProposalV1.model_json_schema(),
            ]
        }
    return {
        "oneOf": [
            CurationContextSummaryProposalV1.model_json_schema(),
            CurationMemoryEntryProposalV1.model_json_schema(),
            CurationNoActionProposalV1.model_json_schema(),
        ]
    }


def curation_output_schema_name(projection_kind: str) -> str:
    return "tutor_context_summary_v2" if projection_kind == "context_summary" else "tutor_curation_output_v1"


def canonical_curation_examples(projection_kind: str) -> str:
    examples: tuple[Mapping[str, object], ...]
    if projection_kind == "context_summary":
        examples = (
            {
                "kind": "context_summary",
                "schema_version": TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION,
                "current_goal": "继续学习函数参数",
                "confirmed_facts": ["学习者已经准备好练习环境"],
                "completed_steps": ["已完成变量基础"],
                "rejected_paths": ["不再重复旧的网站搭建路径"],
                "open_questions": ["下一步先练默认参数还是返回值"],
                "learner_preferences": ["偏好短小且可验证的示例"],
                "confidence": "high",
            },
            {"kind": "no_action", "code": "no_safe_continuity_fact"},
        )
    else:
        examples = (
            {"kind": "context_summary", "summary": "学习者正在练习函数边界。", "confidence": "medium"},
            {
                "kind": "memory_entry",
                "category": "learning_preference",
                "statement": "学习者偏好短小且可验证的示例。",
                "confidence": "high",
            },
            {"kind": "no_action", "code": "no_safe_projection"},
        )
    return " ".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in examples)


def parse_curation_output(payload: Mapping[str, object]) -> CurationOutput:
    kind = str(payload.get("kind") or "")
    if kind == "context_summary" and str(payload.get("schema_version") or "") == TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION:
        return CurationContextSummaryProposalV2.model_validate(payload)
    if kind == "context_summary":
        return CurationContextSummaryProposalV1.model_validate(payload)
    if kind == "memory_entry":
        return CurationMemoryEntryProposalV1.model_validate(payload)
    if kind == "no_action":
        return CurationNoActionProposalV1.model_validate(payload)
    raise LLMInvalidResponseError("Curator output has an unsupported kind")


def _build_messages(*, source: TutorCurationSource) -> list[dict[str, str]]:
    bounded_source: dict[str, object]
    if source.projection_kind == "context_summary":
        system = (
            "You are the Aearn Tutor Context Summary Curator. Return one JSON object only. "
            "Use exactly these keys: kind, schema_version, current_goal, confirmed_facts, completed_steps, "
            "rejected_paths, open_questions, learner_preferences, confidence. "
            "kind must be context_summary and schema_version must be tutor_context_summary_v2. "
            "Merge only the supplied prior summary and retired messages. Newer learner corrections override older "
            "facts; completed work and rejected paths must remain separate; open questions are not confirmed facts. "
            "Do not quote messages or include code, URL, path, command, SQL, provider detail, credential, reasoning, "
            "or unknown fields. Use bounded arrays and return no_action only when no continuity fact is safe to retain. "
            f"Valid output examples: {canonical_curation_examples(source.projection_kind)}"
        )
        bounded_source = {
            "summary_schema_version": source.summary_schema_version,
            "summary_policy_version": source.summary_policy_version,
            "prior_summary_id": source.prior_summary_id,
            "prior_summary_hash": source.prior_summary_hash,
            "prior_summary": source.prior_summary_json,
            "retired_messages": [
                {
                    "message_id": item.message_id,
                    "role": item.role,
                    "created_at": item.created_at.astimezone(UTC).isoformat(),
                    "content": sanitize_message_content(
                        role="assistant" if item.role == "tutor" else "user",
                        content=item.content,
                        max_length=1200,
                    ),
                }
                for item in source.retired_messages[:24]
            ],
            "covered_through_created_at": (
                source.covered_through_created_at.astimezone(UTC).isoformat()
                if source.covered_through_created_at is not None
                else None
            ),
            "covered_through_message_id": source.covered_through_message_id,
            "source_hash": source.summary_source_hash,
        }
    else:
        system = (
            "You are the Aearn Memory Curator. Return one JSON object only. "
            "Allowed kind values are context_summary, memory_entry, or no_action. "
            "Use only the supplied redacted evidence. Never include raw conversation, prompt, "
            "provider reasoning, code, URL, path, command, SQL, secret, chat, activity, plan, "
            "review, FSRS, attempt, executor, provider choice, or unknown fields. "
            f"Valid output examples: {canonical_curation_examples(source.projection_kind)}"
        )
        bounded_source = {
            "outbox_id": source.outbox_id,
            "run_id": source.run_id,
            "policy_version": source.policy_version,
            "memory_setting_version": source.memory_setting_version,
            "source_ids": list(source.source_ids[:16]),
            "source_hashes": list(source.source_hashes[:16]),
            "retention_until": source.retention_until.astimezone(UTC).isoformat(),
            "stale_after": source.stale_after.astimezone(UTC).isoformat(),
            "envelope": source.envelope,
        }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(bounded_source, ensure_ascii=False, sort_keys=True)},
    ]


def _summary_overview(proposal: CurationContextSummaryProposalV2) -> str:
    parts: list[str] = []
    if proposal.current_goal is not None:
        parts.append(f"目标：{proposal.current_goal}")
    if proposal.confirmed_facts:
        parts.append(f"事实：{proposal.confirmed_facts[0]}")
    if proposal.completed_steps:
        parts.append(f"完成：{proposal.completed_steps[0]}")
    if proposal.rejected_paths:
        parts.append(f"拒绝路径：{proposal.rejected_paths[0]}")
    if proposal.open_questions:
        parts.append(f"待解决：{proposal.open_questions[0]}")
    if proposal.learner_preferences:
        parts.append(f"偏好：{proposal.learner_preferences[0]}")
    return _learner_text("；".join(parts)[:280], label="context summary", maximum=280)


def _receipt_state(value: str) -> Literal["no_action", "stale", "failed"]:
    if value == "no_action":
        return "no_action"
    if value == "stale":
        return "stale"
    if value == "failed":
        return "failed"
    raise TutorLearnerStateConflict("curation_receipt_state_invalid")


def _identifier(value: object, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable bounded identifier")
    return normalized


def _learner_text(value: object, *, label: str, maximum: int) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized or len(normalized) > maximum or contains_forbidden_execution_target(normalized):
        raise ValueError(f"{label} must be bounded learner-safe text")
    return normalized


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)