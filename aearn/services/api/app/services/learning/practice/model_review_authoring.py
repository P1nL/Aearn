"""Recoverable primary-only authoring and controlled validation workflow."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.agents.harness.actions import (
    ActionDescriptor,
    ActionLifecycleStatus,
    ActionResourceRequest,
    build_action_invocation,
    default_action_descriptors,
)
from app.core.config import Settings, get_settings
from app.db.connection import connect
from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
)
from app.services.learning.practice.model_review_actions import (
    ModelReviewPublicationVerifier,
    ModelReviewValidationActionAdapter,
)
from app.services.learning.practice.model_review_contracts import (
    ModelReviewArtifactV1,
    ModelReviewPromptV1,
    ModelReviewRubricV1,
)
from app.services.learning.practice.model_review_repository import (
    MODEL_REVIEW_GENERATOR_VERSION,
    ModelReviewAuthoringRunRecord,
    ModelReviewRepositoryError,
    PostgresModelReviewRepository,
)
from app.services.llm.contracts import LLMUsage
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    OpenAICompatibleClient,
    select_llm_protocol,
)
from app.services.tutor.action_persistence import PostgresActionFence, PostgresActionReceiptStore
from app.services.tutor.action_runtime import ControlledActionRuntime


@dataclass(frozen=True, slots=True)
class ModelReviewAuthoringRequest:
    language_id: str
    knowledge_key: str
    required_capabilities: tuple[str, ...]
    mastery_level: str
    mastery_confidence: float
    validation_profile_version: str


@dataclass(frozen=True, slots=True)
class ModelReviewAuthoringResponse:
    candidate: Mapping[str, object]
    provider: str
    model: str
    protocol: str
    usage: LLMUsage | None = None


class ModelCodeReviewAuthorPort(Protocol):
    def author(self, request: ModelReviewAuthoringRequest) -> ModelReviewAuthoringResponse: ...


class ModelReviewAuthoringFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, outcome: str = "invalid") -> None:
        self.code = code
        self.message = message
        self.outcome = outcome
        super().__init__(message)


class PrimaryModelCodeReviewAuthor:
    """Primary-only adapter. It never falls back to a template or second provider."""

    def __init__(self, settings: Settings | None = None, *, client: OpenAICompatibleClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    def author(self, request: ModelReviewAuthoringRequest) -> ModelReviewAuthoringResponse:
        try:
            client = self._client or OpenAICompatibleClient(self._settings)
            response = client.complete_json(
                _author_messages(request), temperature=0.1, max_tokens=10_000, timeout_seconds=90
            )
        except LLMConfigurationError as exc:
            raise ModelReviewAuthoringFailure(
                "MODEL_REVIEW_GENERATION_UNAVAILABLE", "代码审核题生成服务当前不可用。", outcome="unavailable"
            ) from exc
        except LLMInvalidResponseError as exc:
            raise ModelReviewAuthoringFailure(
                "MODEL_REVIEW_CANDIDATE_INVALID", "代码审核题候选未通过结构校验。"
            ) from exc
        except LLMCallError as exc:
            raise ModelReviewAuthoringFailure(
                "MODEL_REVIEW_GENERATION_UNAVAILABLE", "代码审核题生成服务当前不可用。", outcome="unavailable"
            ) from exc
        return ModelReviewAuthoringResponse(
            candidate=response.content,
            provider=self._settings.llm_provider_type or "configured-primary",
            model=response.model,
            protocol=select_llm_protocol(self._settings).value,
            usage=response.usage,
        )


AuthorFactory = Callable[[], ModelCodeReviewAuthorPort]
MODEL_REVIEW_AUTHOR_FACTORY: AuthorFactory = PrimaryModelCodeReviewAuthor


def dispatch_model_review_authoring_run(
    run_id: str,
    *,
    author: ModelCodeReviewAuthorPort | None = None,
    now: Callable[[], datetime] | None = None,
) -> None:
    clock = now or (lambda: datetime.now(UTC))
    claimed: ModelReviewAuthoringRunRecord | None = None
    try:
        with connect() as conn:
            with conn.transaction():
                claimed = PostgresModelReviewRepository(conn).claim(
                    run_id=run_id, owner=f"model-review-author-{uuid4()}", now=clock()
                )
        if claimed is None:
            return
        with connect() as conn:
            with conn.transaction():
                repository = PostgresModelReviewRepository(conn)
                running = repository.mark_running(repository.read_authoring_run(run_id=run_id, for_update=True))
                candidate = (
                    repository.read_candidate(candidate_id=running.candidate_id, user_id=running.user_id)
                    if running.candidate_id
                    else None
                )
        if candidate is None:
            request = ModelReviewAuthoringRequest(
                language_id=running.language_id,
                knowledge_key=running.knowledge_key,
                required_capabilities=running.required_capabilities,
                mastery_level=running.mastery_level,
                mastery_confidence=running.mastery_confidence,
                validation_profile_version=running.validation_profile_version,
            )
            port = author or MODEL_REVIEW_AUTHOR_FACTORY()
            response = _call_author_and_record(port=port, request=request, run=running)
            exercise, rubric = _parse_candidate(response.candidate, request)
            with connect() as conn:
                with conn.transaction():
                    repository = PostgresModelReviewRepository(conn)
                    candidate = repository.create_candidate(run=running, exercise=exercise, rubric=rubric)
                    running = repository.read_authoring_run(run_id=run_id, for_update=True)
        with connect() as conn:
            with conn.transaction():
                repository = PostgresModelReviewRepository(conn)
                running = repository.read_authoring_run(run_id=run_id, for_update=True)
                snapshot, _lease = repository.ensure_internal_run(run=running, now=clock())
                running = repository.read_authoring_run(run_id=run_id, for_update=True)
                candidate = repository.read_candidate(candidate_id=candidate.candidate_id, user_id=running.user_id)
                descriptor = _descriptor()
                retry_index = max(0, running.attempt_count - 1)
                invocation_id = f"model-review-{candidate.candidate_hash[:24]}-{running.attempt_count}"
                validation = repository.create_or_replay_validation(
                    run=running, candidate=candidate, action_invocation_id=invocation_id
                )
                run_authority = conn.execute(
                    "SELECT catalog_digest, policy_fingerprint FROM tutor_runs WHERE id = %s AND user_id = %s",
                    (snapshot.run_id, running.user_id),
                ).fetchone()
                if run_authority is None:
                    raise ModelReviewRepositoryError("MODEL_REVIEW_VALIDATION_STALE")
                invocation = build_action_invocation(
                    descriptor=descriptor,
                    run=snapshot,
                    invocation_id=invocation_id,
                    idempotency_key=invocation_id,
                    arguments={
                        "candidate_id": candidate.candidate_id,
                        "candidate_hash": candidate.candidate_hash,
                        "validation_profile_version": candidate.validation_profile_version,
                    },
                    resource_request=ActionResourceRequest(
                        artifact_ids=(candidate.candidate_id,),
                        artifact_kinds=(
                            "model_review_candidate", "model_review_private_rubric", "model_review_validation"
                        ),
                        execution_profile_id=_execution_profile(candidate.public_payload),
                        network_class=descriptor.resource_profile.network_class,
                        temporary_workspace=True,
                        input_bytes=512,
                        expected_output_bytes=1024,
                        cost_units=1,
                    ),
                    task_kind="model_code_review",
                    catalog_digest=str(run_authority["catalog_digest"]),
                    policy_fingerprint=str(run_authority["policy_fingerprint"]),
                    selected_skill_reference=None,
                    action_generation=running.attempt_count,
                    requested_at=clock(),
                    retry_index=retry_index,
                )
                outcome = ControlledActionRuntime(
                    descriptors=(descriptor,),
                    adapters={descriptor.owner_adapter_id: ModelReviewValidationActionAdapter(conn, clock=clock)},
                    verifiers={descriptor.verifier_id: ModelReviewPublicationVerifier(conn)},
                    fence=PostgresActionFence(conn),
                    store=PostgresActionReceiptStore(conn),
                    clock=clock,
                    approved_artifact_ids=(candidate.candidate_id,),
                ).execute(invocation)
                if outcome.receipt.status is ActionLifecycleStatus.VERIFIED:
                    repository.attach_action_receipt(
                        validation_id=validation.validation_id,
                        user_id=running.user_id,
                        action_receipt_hash=outcome.receipt.receipt_hash,
                    )
                    verified = repository.read_validation(
                        validation_id=validation.validation_id, user_id=running.user_id
                    )
                    repository.publish(
                        run=running, candidate=candidate, validation=verified, now=clock()
                    )
                    return
                if outcome.receipt.status is ActionLifecycleStatus.RETRYABLE_FAILED:
                    repository.release(run_id=running.run_id, lease_generation=running.lease_generation)
                    return
                raise ModelReviewAuthoringFailure(
                    outcome.receipt.diagnostic_code or "MODEL_REVIEW_VALIDATION_FAILED",
                    "代码审核题未通过预发布验证。",
                )
    except ModelReviewAuthoringFailure as exc:
        _safe_fail(run_id, exc.code, exc.message, clock())
    except ModelReviewRepositoryError as exc:
        _safe_fail(run_id, str(exc), "代码审核题未通过预发布验证。", clock())
    except Exception:
        _safe_fail(run_id, "MODEL_REVIEW_VALIDATION_UNAVAILABLE", "代码审核题验证服务当前不可用。", clock())


def _call_author_and_record(
    *, port: ModelCodeReviewAuthorPort, request: ModelReviewAuthoringRequest, run: ModelReviewAuthoringRunRecord
) -> ModelReviewAuthoringResponse:
    request_payload = _request_payload(request)
    request_hash = _hash_json(request_payload)
    try:
        response = port.author(request)
    except ModelReviewAuthoringFailure as exc:
        with connect() as conn:
            with conn.transaction():
                PostgresModelReviewRepository(conn).record_author_attempt(
                    run=run, provider="configured-primary", model="configured-primary", protocol="unknown",
                    outcome="unavailable" if exc.outcome == "unavailable" else "invalid",
                    diagnostic_code=exc.code, input_tokens=None, output_tokens=None,
                    request_hash=request_hash, response_hash=None,
                )
        raise
    usage = response.usage
    with connect() as conn:
        with conn.transaction():
            PostgresModelReviewRepository(conn).record_author_attempt(
                run=run, provider=response.provider, model=response.model, protocol=response.protocol,
                outcome="success", diagnostic_code=None,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                request_hash=request_hash, response_hash=_hash_json(response.candidate),
            )
    return response


def _parse_candidate(
    payload: Mapping[str, object], request: ModelReviewAuthoringRequest
) -> tuple[ExerciseVersion, ExercisePrivateRubric]:
    if set(payload) != {"title", "learner_prompt", "starter_artifact", "private_rubric", "private_test_bundle", "score_policy"}:
        raise ModelReviewAuthoringFailure("MODEL_REVIEW_CANDIDATE_INVALID", "代码审核题候选字段不完整。")
    prompt = ModelReviewPromptV1.model_validate(_mapping(payload.get("learner_prompt")))
    artifact = ModelReviewArtifactV1.model_validate(_mapping(payload.get("starter_artifact")))
    rubric = ModelReviewRubricV1.model_validate(_mapping(payload.get("private_rubric")))
    if artifact.language_id != request.language_id:
        raise ModelReviewAuthoringFailure("MODEL_REVIEW_CANDIDATE_INVALID", "代码审核题候选语言不匹配。")
    seed = _hash_json(payload)
    exercise = ExerciseVersion(
        language_id=request.language_id,
        exercise_key=f"{request.language_id}.review.{request.knowledge_key}.{seed[:12]}",
        exercise_type=ExerciseType.MODEL_CODE_REVIEW,
        version=f"v1-{seed[:12]}",
        source_kind=ExerciseSourceKind.REGISTERED_AUTHOR,
        title=str(payload["title"]),
        learner_prompt=prompt.model_dump(mode="json"),
        starter_artifact=artifact.model_dump(mode="json"),
        required_capabilities=request.required_capabilities,
        runtime_profile_id=None,
        execution_required=False,
        public_feedback_policy_version="model_code_review_feedback_v1",
    )
    private = ExercisePrivateRubric(
        rubric_version="v1",
        private_test_bundle=tuple(_mapping(item) for item in _sequence(payload.get("private_test_bundle"))),
        reference_answer=rubric.model_dump(mode="json"),
        score_policy=_mapping(payload.get("score_policy")),
    )
    if str(private.score_policy.get("kind")) != "model_code_review":
        raise ModelReviewAuthoringFailure("MODEL_REVIEW_CANDIDATE_INVALID", "代码审核题评分策略无效。")
    return exercise, private


def _descriptor() -> ActionDescriptor:
    return next(item for item in default_action_descriptors() if item.action_id == "model-code-review.validate")


def _execution_profile(public_payload: Mapping[str, object]) -> str:
    language = str(_mapping(public_payload.get("starter_artifact")).get("language_id") or "").lower()
    profile = {
        "python": "python-stdout-v1",
        "javascript": "node-typescript-v1",
        "typescript": "node-typescript-v1",
        "sql": "sqlite-query-v1",
    }.get(language)
    if profile is None:
        raise ModelReviewAuthoringFailure("MODEL_REVIEW_CANDIDATE_INVALID", "代码审核题运行时不受支持。")
    return profile


def _author_messages(request: ModelReviewAuthoringRequest) -> tuple[dict[str, str], ...]:
    instruction = (
        "Author one strict model code review exercise JSON object. The learner reviews only generated code, never a user repository. "
        "Return exact keys: title, learner_prompt, starter_artifact, private_rubric, private_test_bundle, score_policy. "
        "Use learner_prompt schema model_code_review_prompt_v1 and starter_artifact schema model_code_review_artifact_v1. "
        "Use private_rubric schema model_code_review_rubric_v1. Include deterministic visible and hidden tests. "
        "Do not include user identity, conversation history, secrets, paths, commands, images, containers, or provider metadata. "
        "The public prompt must not reveal scenario_kind, expected findings, matcher tokens, reachability proofs, or hidden tests. "
        "score_policy is exactly {kind:model_code_review, policy_version:model_code_review_score_v1, threshold:0.8}. Return JSON only."
    )
    return (
        {"role": "system", "content": instruction},
        {"role": "user", "content": json.dumps(_request_payload(request), ensure_ascii=False, sort_keys=True)},
    )


def _request_payload(request: ModelReviewAuthoringRequest) -> dict[str, object]:
    return {
        "language_id": request.language_id,
        "knowledge_key": request.knowledge_key,
        "required_capabilities": list(request.required_capabilities),
        "target_difficulty": request.mastery_level,
        "mastery_confidence_band": round(request.mastery_confidence, 2),
        "validation_profile_version": request.validation_profile_version,
        "generator_version": MODEL_REVIEW_GENERATOR_VERSION,
    }


def _safe_fail(run_id: str, code: str, message: str, now: datetime) -> None:
    normalized = str(code or "MODEL_REVIEW_VALIDATION_UNAVAILABLE").upper().replace("-", "_")
    if not normalized.startswith("MODEL_REVIEW_"):
        normalized = "MODEL_REVIEW_VALIDATION_UNAVAILABLE"
    try:
        with connect() as conn:
            with conn.transaction():
                PostgresModelReviewRepository(conn).fail(
                    run_id=run_id, code=normalized[:80], message=message, now=now
                )
    except Exception:
        return


def _hash_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mapping(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(value)
