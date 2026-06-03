from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from psycopg import Connection

from app.services.exercises.exercise_templates import (
    ADAPTIVE_TEMPLATE_GENERATOR_VERSION,
    ADAPTIVE_TEMPLATE_PROMPT_VERSION,
    CanonicalExerciseTemplate,
    select_canonical_exercise_template,
)
from app.services.exercises.syntax_validators import SemanticValidationReport, validate_exercise_semantics
from app.services.llm.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError, OpenAICompatibleClient
from app.services.runners.runner_registry import get_runner_registry
from app.services.runners.runtime_runner import run_exercise


MAX_ADAPTIVE_GENERATION_ATTEMPTS = 3
SAFE_GENERATION_EXCEPTIONS = (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    TypeError,
    ValueError,
)
MODEL_CANDIDATE_ALLOWED_KEYS = {
    "title",
    "prompt_markdown",
    "starter_code",
    "solution_reference",
    "metadata_json",
    "code_blanks",
    "difficulty",
    "estimated_minutes",
    "requires_explanation",
    "exercise_intent",
    "target_skill_tags",
    "alignment_claims",
    "visible_examples",
    "requested_exercise_type",
}
FORBIDDEN_LEARNER_TEXT_MARKERS = (
    "api_key",
    "provider_payload",
    "raw prompt",
    "traceback",
    "sk-",
)


@dataclass(frozen=True, slots=True)
class GeneratedAdaptiveCandidate:
    content: Mapping[str, object]
    model: str | None = None


class CandidateValidationError(ValueError):
    def __init__(
        self,
        failure_code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ValidationReport:
    passed: bool
    failure_code: str | None
    runtime_status: str
    test_pass_rate: float
    runner_key: str
    runtime_tier: str

    def as_safe_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failure_code": self.failure_code,
            "runtime_status": self.runtime_status,
            "test_pass_rate": self.test_pass_rate,
            "runner_key": self.runner_key,
            "runtime_tier": self.runtime_tier,
        }


AdaptiveCandidateGenerator = Callable[[Mapping[str, object], CanonicalExerciseTemplate], GeneratedAdaptiveCandidate | None]


def build_adaptive_exercise_template(
    conn: Connection[dict[str, object]],
    *,
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
    fallback_template: Mapping[str, object],
    candidate_generator: AdaptiveCandidateGenerator | None = None,
) -> dict[str, object]:
    canonical = select_canonical_exercise_template(
        knowledge_point=knowledge_point,
        runtime_profile=runtime_profile,
        fallback_template=fallback_template,
    )
    runner_capability = get_runner_registry().select(runtime_profile)
    if not runner_capability.supports_execution or not runner_capability.supports_tests:
        raise LLMInvalidResponseError("Adaptive exercise generation requires an executable test runner")

    user_id = str(knowledge_point.get("user_id") or "")
    knowledge_point_id = str(knowledge_point.get("id") or "")
    if not user_id or not knowledge_point_id:
        raise LLMInvalidResponseError("Adaptive exercise generation requires user-scoped knowledge point context")

    cached = _load_cached_variant(
        conn,
        user_id=user_id,
        knowledge_point_id=knowledge_point_id,
        canonical=canonical,
        runtime_profile=runtime_profile,
    )
    if cached is not None:
        payload = _payload_from_cache(cached)
        _touch_cached_variant(conn, str(cached["id"]))
        return _with_adaptive_metadata(
            payload,
            canonical=canonical,
            runtime_profile=runtime_profile,
            source=str(_adaptive_meta(payload).get("source") or "model_candidate"),
            validation_status="validated",
            generator_model=_str_or_none(_adaptive_meta(payload).get("generator_model")),
            variant_hash=str(cached["variant_hash"]),
            cache_hit=True,
        )

    base_model_context = _model_context(knowledge_point, runtime_profile, canonical)
    generator = candidate_generator or build_model_candidate
    feedback_items: list[dict[str, object]] = []
    last_feedback: Mapping[str, object] | None = None

    for attempt_index in range(1, MAX_ADAPTIVE_GENERATION_ATTEMPTS + 1):
        model_context = _attempt_model_context(
            base_model_context,
            attempt_index=attempt_index,
            max_attempts=MAX_ADAPTIVE_GENERATION_ATTEMPTS,
            feedback_items=feedback_items,
        )

        try:
            generated = generator(model_context, canonical)
        except SAFE_GENERATION_EXCEPTIONS as exc:
            last_feedback = _generation_feedback(
                failure_stage="provider",
                failure_code="model_generation_failed",
                attempt_index=attempt_index,
                max_attempts=MAX_ADAPTIVE_GENERATION_ATTEMPTS,
            )
            feedback_items.append(dict(last_feedback))
            if attempt_index == MAX_ADAPTIVE_GENERATION_ATTEMPTS:
                raise LLMInvalidResponseError("Adaptive exercise model generation failed") from exc
            continue

        if generated is None:
            last_feedback = _generation_feedback(
                failure_stage="provider",
                failure_code="provider_unavailable",
                attempt_index=attempt_index,
                max_attempts=MAX_ADAPTIVE_GENERATION_ATTEMPTS,
            )
            feedback_items.append(dict(last_feedback))
            if attempt_index == MAX_ADAPTIVE_GENERATION_ATTEMPTS:
                raise LLMInvalidResponseError("Adaptive exercise model provider unavailable")
            continue

        try:
            candidate_payload = _candidate_payload_from_generated(generated.content, canonical)
        except CandidateValidationError as exc:
            last_feedback = _generation_feedback(
                failure_stage="schema",
                failure_code=exc.failure_code,
                attempt_index=attempt_index,
                max_attempts=MAX_ADAPTIVE_GENERATION_ATTEMPTS,
                extra=exc.details,
            )
            feedback_items.append(dict(last_feedback))
            if attempt_index == MAX_ADAPTIVE_GENERATION_ATTEMPTS:
                raise LLMInvalidResponseError("Adaptive exercise model candidate schema stayed invalid") from exc
            continue

        semantic_report = validate_exercise_semantics(
            candidate_payload=candidate_payload,
            knowledge_point=knowledge_point,
            runtime_profile=runtime_profile,
        )
        if not semantic_report.passed:
            last_feedback = _semantic_feedback(
                semantic_report,
                attempt_index=attempt_index,
                max_attempts=MAX_ADAPTIVE_GENERATION_ATTEMPTS,
            )
            feedback_items.append(dict(last_feedback))
            if attempt_index == MAX_ADAPTIVE_GENERATION_ATTEMPTS:
                raise LLMInvalidResponseError("Adaptive exercise model candidate missed required skills")
            continue

        validation = _validate_candidate(candidate_payload, runtime_profile)
        if not validation.passed:
            last_feedback = _runner_feedback(
                validation,
                attempt_index=attempt_index,
                max_attempts=MAX_ADAPTIVE_GENERATION_ATTEMPTS,
            )
            feedback_items.append(dict(last_feedback))
            if attempt_index == MAX_ADAPTIVE_GENERATION_ATTEMPTS:
                raise LLMInvalidResponseError("Adaptive exercise model candidate failed runner validation")
            continue

        variant_hash = _variant_hash(candidate_payload)
        payload = _with_adaptive_metadata(
            candidate_payload,
            canonical=canonical,
            runtime_profile=runtime_profile,
            source="model_candidate",
            validation_status="validated",
            generator_model=generated.model,
            variant_hash=variant_hash,
            validation_report=validation,
            semantic_report=semantic_report,
            generation_attempt_count=attempt_index,
            cache_hit=False,
        )
        _persist_validated_variant(
            conn,
            user_id=user_id,
            knowledge_point_id=knowledge_point_id,
            canonical=canonical,
            runtime_profile=runtime_profile,
            payload=payload,
            variant_hash=variant_hash,
            validation_report=validation,
        )
        return payload

    raise LLMInvalidResponseError(f"Adaptive exercise generation unavailable: {last_feedback or {}}")


def build_model_candidate(
    context: Mapping[str, object],
    template: CanonicalExerciseTemplate,
) -> GeneratedAdaptiveCandidate | None:
    try:
        client = OpenAICompatibleClient()
    except LLMConfigurationError:
        return None
    result = client.complete_json(_model_messages(context, template))
    return GeneratedAdaptiveCandidate(content=result.content, model=result.model)


def _model_messages(
    context: Mapping[str, object],
    template: CanonicalExerciseTemplate,
) -> list[dict[str, str]]:
    fallback = template.fallback_payload
    safe_envelope = {
        "template_id": template.template_id,
        "template_version": template.template_version,
        "language_id": template.language_id,
        "runtime_tier": template.runtime_tier,
        "exercise_type": template.exercise_type,
        "allowed_candidate_fields": sorted(MODEL_CANDIDATE_ALLOWED_KEYS),
        "internal_seed_starter_code": str(fallback.get("starter_code") or "")[:1200],
        "code_blanks": fallback.get("code_blanks") if isinstance(fallback.get("code_blanks"), list) else [],
        "metadata_json": _safe_model_metadata(fallback.get("metadata_json")),
    }
    return [
        {
            "role": "system",
            "content": (
                "You generate Aearn programming exercises with model-first bounded freeform design. "
                "The canonical template is only an internal seed, runner harness reference, and safety envelope; "
                "do not preserve its code skeleton unless that is the best way to teach the required skills. "
                "Return JSON only. Do not invent test cases, runtime tiers, hidden data, provider payloads, or unsupported fields."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "adaptive_exercise_candidate",
                    "generation_policy": (
                        "Create a learner-visible exercise that directly practices required_skill_tags. "
                        "Avoid generic language drills when a specific concept is present. "
                        "You may redesign title, prompt, starter_code, solution_reference, blanks, and safe metadata. "
                        "You must not change language_id, runtime_tier, runner_key, or final grading authority."
                    ),
                    "bounded_learner_context": context,
                    "canonical_template_envelope": safe_envelope,
                    "response_shape": {
                        "candidate": {
                            "title": "string",
                            "prompt_markdown": "string",
                            "starter_code": "string",
                            "solution_reference": "string",
                            "metadata_json": {},
                            "code_blanks": [],
                            "exercise_intent": "string",
                            "target_skill_tags": [],
                            "alignment_claims": [],
                        }
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]


def _candidate_payload_from_generated(
    generated: Mapping[str, object],
    canonical: CanonicalExerciseTemplate,
) -> dict[str, object]:
    candidate = generated.get("candidate", generated)
    if not isinstance(candidate, Mapping):
        raise CandidateValidationError("invalid_candidate_schema", "candidate must be an object")
    unsupported = set(candidate) - MODEL_CANDIDATE_ALLOWED_KEYS
    if unsupported:
        raise CandidateValidationError(
            "unsupported_candidate_field",
            "candidate contains unsupported fields",
            details={"unsupported_fields": sorted(str(field) for field in unsupported)[:8]},
        )
    missing_required_fields = [
        key
        for key in ("title", "prompt_markdown", "starter_code", "solution_reference")
        if not isinstance(candidate.get(key), str) or not str(candidate.get(key) or "").strip()
    ]
    if missing_required_fields:
        raise CandidateValidationError(
            "invalid_candidate_schema",
            "candidate is missing required learner-facing fields",
            details={"missing_required_fields": missing_required_fields},
        )

    payload = _clone_payload(canonical.fallback_payload)
    requested_exercise_type = candidate.get("requested_exercise_type")
    if isinstance(requested_exercise_type, str) and requested_exercise_type.strip():
        if requested_exercise_type != canonical.exercise_type:
            raise CandidateValidationError(
                "unsupported_exercise_type",
                "candidate requested an unsupported exercise type",
                details={"requested_exercise_type": _bounded_text(requested_exercise_type, 80)},
            )
    for key in ("title", "prompt_markdown", "starter_code", "solution_reference"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value

    for key in ("difficulty", "estimated_minutes"):
        value = candidate.get(key)
        if isinstance(value, int):
            payload[key] = value
    if isinstance(candidate.get("requires_explanation"), bool):
        payload["requires_explanation"] = candidate["requires_explanation"]

    if "metadata_json" in candidate:
        metadata = candidate["metadata_json"]
        if not isinstance(metadata, Mapping) or "adaptive_variant" in metadata:
            raise CandidateValidationError("invalid_candidate_schema", "candidate metadata is invalid")
        base_metadata = payload.get("metadata_json", {})
        payload["metadata_json"] = {
            **(dict(base_metadata) if isinstance(base_metadata, Mapping) else {}),
            **dict(metadata),
        }
    _attach_model_alignment_metadata(payload, candidate)

    if "code_blanks" in candidate:
        code_blanks = candidate["code_blanks"]
        if not isinstance(code_blanks, list) or not all(isinstance(blank, Mapping) for blank in code_blanks):
            raise CandidateValidationError("invalid_candidate_schema", "candidate code_blanks are invalid")
        payload["code_blanks"] = [dict(blank) for blank in code_blanks]

    _assert_candidate_safe(payload, canonical)
    return payload


def _deterministic_candidate(canonical: CanonicalExerciseTemplate) -> dict[str, object]:
    payload = _clone_payload(canonical.fallback_payload)
    payload["title"] = f"{payload.get('title', '练习')}：自适应复练"
    metadata = payload.get("metadata_json", {})
    payload["metadata_json"] = dict(metadata) if isinstance(metadata, Mapping) else {}
    return payload


def _validate_candidate(
    candidate_payload: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> ValidationReport:
    runner_capability = get_runner_registry().select(runtime_profile)
    solution = str(candidate_payload.get("solution_reference") or "").strip()
    if not solution:
        return _validation_report(False, "missing_solution_reference", "runtime_error", 0.0, runner_capability, runtime_profile)

    exercise = {
        "runtime_profile": dict(runtime_profile),
        "metadata_json": candidate_payload.get("metadata_json") if isinstance(candidate_payload.get("metadata_json"), Mapping) else {},
        "code_blanks": candidate_payload.get("code_blanks") if isinstance(candidate_payload.get("code_blanks"), Sequence) else [],
        "test_cases": candidate_payload.get("test_cases") if isinstance(candidate_payload.get("test_cases"), Sequence) else [],
    }
    result = run_exercise(exercise, solution, _filled_blanks(candidate_payload), "visible_tests")
    if result.runtime_status != "success":
        return _validation_report(False, str(result.runtime_status), result.runtime_status, result.test_pass_rate, runner_capability, runtime_profile)
    if result.test_pass_rate < 1.0:
        return _validation_report(False, "tests_failed", result.runtime_status, result.test_pass_rate, runner_capability, runtime_profile)
    if _hidden_output_leaked(result.test_results, candidate_payload):
        return _validation_report(False, "hidden_redaction_failed", result.runtime_status, result.test_pass_rate, runner_capability, runtime_profile)
    return _validation_report(True, None, result.runtime_status, result.test_pass_rate, runner_capability, runtime_profile)


def _validation_report(
    passed: bool,
    failure_code: str | None,
    runtime_status: str,
    test_pass_rate: float,
    runner_capability: object,
    runtime_profile: Mapping[str, object],
) -> ValidationReport:
    return ValidationReport(
        passed=passed,
        failure_code=failure_code,
        runtime_status=runtime_status,
        test_pass_rate=test_pass_rate,
        runner_key=str(getattr(runner_capability, "runner_key", "none")),
        runtime_tier=str(runtime_profile.get("runtime_tier") or ""),
    )


def _filled_blanks(candidate_payload: Mapping[str, object]) -> dict[str, str]:
    blanks = candidate_payload.get("code_blanks")
    if not isinstance(blanks, Sequence) or isinstance(blanks, str):
        return {}
    result: dict[str, str] = {}
    for blank in blanks:
        if not isinstance(blank, Mapping):
            continue
        key = str(blank.get("blank_key") or "")
        placeholder = str(blank.get("placeholder") or "")
        if key:
            result[key] = placeholder
    return result


def _hidden_output_leaked(test_results: Sequence[Mapping[str, object]], candidate_payload: Mapping[str, object]) -> bool:
    serialized = repr(test_results)
    for marker in _hidden_markers(candidate_payload):
        if marker and marker in serialized:
            return True
    return False


def _hidden_markers(candidate_payload: Mapping[str, object]) -> set[str]:
    markers: set[str] = set()
    test_cases = candidate_payload.get("test_cases")
    if not isinstance(test_cases, Sequence) or isinstance(test_cases, str):
        return markers
    visible_strings: set[str] = set()
    for test_case in test_cases:
        if not isinstance(test_case, Mapping) or str(test_case.get("case_type", "visible")) == "hidden":
            continue
        visible_strings.update(value for value in _string_values(test_case.get("expected_output_json")) if len(value) >= 3)
    for test_case in test_cases:
        if not isinstance(test_case, Mapping) or str(test_case.get("case_type", "visible")) != "hidden":
            continue
        case_id = test_case.get("id")
        if isinstance(case_id, str):
            markers.add(case_id)
        markers.update(
            value
            for value in _string_values(test_case.get("expected_output_json"))
            if len(value) >= 3 and value not in visible_strings
        )
    return markers


def _assert_candidate_safe(payload: Mapping[str, object], canonical: CanonicalExerciseTemplate) -> None:
    for key in ("title", "prompt_markdown", "starter_code"):
        text = str(payload.get(key) or "")
        lowered = text.lower()
        if any(marker in lowered for marker in FORBIDDEN_LEARNER_TEXT_MARKERS):
            raise CandidateValidationError("candidate_safety_failed", "candidate learner-facing text contains forbidden marker")
        solution = str(payload.get("solution_reference") or "")
        if key != "starter_code" and solution and solution in text:
            raise CandidateValidationError("candidate_safety_failed", "candidate learner-facing text exposed solution reference")
    hidden_markers = _hidden_markers(canonical.fallback_payload)
    learner_text = "\n".join(str(payload.get(key) or "") for key in ("title", "prompt_markdown", "starter_code"))
    if any(marker and marker in learner_text for marker in hidden_markers):
        raise CandidateValidationError("candidate_safety_failed", "candidate learner-facing text exposed hidden test data")


def _fallback_template(
    fallback_template: Mapping[str, object],
    *,
    canonical: CanonicalExerciseTemplate,
    runtime_profile: Mapping[str, object],
    fallback_reason: str,
    validation_report: ValidationReport | None = None,
) -> dict[str, object]:
    return _with_adaptive_metadata(
        _clone_payload(fallback_template),
        canonical=canonical,
        runtime_profile=runtime_profile,
        source="fallback_template",
        validation_status="fallback",
        fallback_reason=fallback_reason,
        validation_report=validation_report,
        cache_hit=False,
    )


def _with_adaptive_metadata(
    payload: Mapping[str, object],
    *,
    canonical: CanonicalExerciseTemplate,
    runtime_profile: Mapping[str, object],
    source: str,
    validation_status: str,
    generator_model: str | None = None,
    fallback_reason: str | None = None,
    variant_hash: str | None = None,
    validation_report: ValidationReport | None = None,
    semantic_report: SemanticValidationReport | None = None,
    generation_attempt_count: int | None = None,
    cache_hit: bool = False,
) -> dict[str, object]:
    cloned = _clone_payload(payload)
    metadata = cloned.get("metadata_json", {})
    metadata_dict = dict(metadata) if isinstance(metadata, Mapping) else {}
    adaptive: dict[str, object] = {
        "template_id": canonical.template_id,
        "template_version": canonical.template_version,
        "generator_version": ADAPTIVE_TEMPLATE_GENERATOR_VERSION,
        "prompt_version": ADAPTIVE_TEMPLATE_PROMPT_VERSION,
        "runner_key": str(runtime_profile.get("runner") or canonical.runner_key),
        "runtime_tier": str(runtime_profile.get("runtime_tier") or canonical.runtime_tier),
        "source": source,
        "validation_status": validation_status,
        "cache_hit": cache_hit,
    }
    if generator_model:
        adaptive["generator_model"] = generator_model
    if fallback_reason:
        adaptive["fallback_reason"] = fallback_reason
    if variant_hash:
        adaptive["variant_hash"] = variant_hash
    if validation_report is not None:
        adaptive["validation_report"] = validation_report.as_safe_payload()
    if semantic_report is not None:
        adaptive["semantic_validation_report"] = semantic_report.as_safe_payload()
    if generation_attempt_count is not None:
        adaptive["generation_attempt_count"] = generation_attempt_count
    metadata_dict["adaptive_variant"] = adaptive
    cloned["metadata_json"] = metadata_dict
    return cloned


def _model_context(
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
    canonical: CanonicalExerciseTemplate,
) -> dict[str, object]:
    required_skill_tags = _normalized_tag_list(knowledge_point.get("skill_tags_json"))[:12]
    lesson_outline = _bounded_lesson_outline(knowledge_point.get("lesson_outline_json"))
    source_attribution = _bounded_source_attribution(knowledge_point.get("lesson_sources_json"))
    return {
        "user_id": str(knowledge_point.get("user_id") or ""),
        "plan_id": str(knowledge_point.get("plan_id") or ""),
        "knowledge_point_id": str(knowledge_point.get("id") or ""),
        "knowledge_point_title": str(knowledge_point.get("title") or ""),
        "knowledge_point_description": _bounded_text(str(knowledge_point.get("description") or ""), 900),
        "required_skill_tags": required_skill_tags,
        "module_context": {
            "module_title": _bounded_text(str(knowledge_point.get("module_title") or ""), 160),
            "module_description": _bounded_text(str(knowledge_point.get("module_description") or ""), 240),
            "course_title": _bounded_text(str(knowledge_point.get("course_title") or ""), 160),
        },
        "lesson_outline": lesson_outline,
        "source_attribution": source_attribution,
        "taxonomy_hints": _taxonomy_hints(knowledge_point, canonical, source_attribution),
        "weak_points": _string_list(knowledge_point.get("weak_points_json"))[:6],
        "language_id": canonical.language_id,
        "runtime_tier": canonical.runtime_tier,
        "runner_key": canonical.runner_key,
        "exercise_type": canonical.exercise_type,
        "allowed_exercise_types": [canonical.exercise_type],
        "generation_policy": {
            "model_may_redesign_exercise_shape": True,
            "deterministic_template_role": "internal_seed_runner_harness_safety_envelope_only",
            "model_must_not_change": ["language_id", "runtime_tier", "runner_key", "test_cases", "grading_authority"],
            "retry_policy": {"max_attempts": MAX_ADAPTIVE_GENERATION_ATTEMPTS},
        },
    }


def _attempt_model_context(
    base_context: Mapping[str, object],
    *,
    attempt_index: int,
    max_attempts: int,
    feedback_items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        **dict(base_context),
        "generation_attempt": {
            "attempt_index": attempt_index,
            "max_attempts": max_attempts,
        },
        "previous_validation_feedback": [_json_safe(item) for item in feedback_items],
    }


def _generation_feedback(
    *,
    failure_stage: str,
    failure_code: str,
    attempt_index: int,
    max_attempts: int,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    feedback: dict[str, object] = {
        "failure_stage": failure_stage,
        "failure_code": failure_code,
        "attempt_index": attempt_index,
        "max_attempts": max_attempts,
    }
    if extra:
        feedback.update(_safe_feedback_extra(extra))
    return feedback


def _semantic_feedback(
    report: SemanticValidationReport,
    *,
    attempt_index: int,
    max_attempts: int,
) -> dict[str, object]:
    return _generation_feedback(
        failure_stage="semantic",
        failure_code=report.failure_code or "semantic_validation_failed",
        attempt_index=attempt_index,
        max_attempts=max_attempts,
        extra={
            "missing_skill_tags": report.missing_tags[:8],
            "matched_skill_tags": report.matched_tags[:8],
            "validator_key": report.validator_key,
            "validator_version": report.validator_version,
        },
    )


def _runner_feedback(
    report: ValidationReport,
    *,
    attempt_index: int,
    max_attempts: int,
) -> dict[str, object]:
    return _generation_feedback(
        failure_stage="runner",
        failure_code=report.failure_code or "runner_validation_failed",
        attempt_index=attempt_index,
        max_attempts=max_attempts,
        extra={
            "runner_status": report.runtime_status,
            "test_pass_rate": report.test_pass_rate,
            "runner_key": report.runner_key,
            "runtime_tier": report.runtime_tier,
        },
    )


def _safe_feedback_extra(extra: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "unsupported_fields",
        "missing_required_fields",
        "requested_exercise_type",
        "missing_skill_tags",
        "matched_skill_tags",
        "validator_key",
        "validator_version",
        "runner_status",
        "test_pass_rate",
        "runner_key",
        "runtime_tier",
    }
    return {
        key: _json_safe(value)
        for key, value in extra.items()
        if key in allowed
    }


def _attach_model_alignment_metadata(payload: dict[str, object], candidate: Mapping[str, object]) -> None:
    alignment: dict[str, object] = {}
    for key in ("exercise_intent", "requested_exercise_type"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            alignment[key] = _bounded_text(value, 500)
    target_skill_tags = _normalized_tag_list(candidate.get("target_skill_tags"))[:12]
    if target_skill_tags:
        alignment["target_skill_tags"] = target_skill_tags
    alignment_claims = _string_list(candidate.get("alignment_claims"))[:8]
    if alignment_claims:
        alignment["alignment_claims"] = alignment_claims
    visible_examples = _string_list(candidate.get("visible_examples"))[:4]
    if visible_examples:
        alignment["visible_examples"] = visible_examples
    if not alignment:
        return
    metadata = payload.get("metadata_json", {})
    metadata_dict = dict(metadata) if isinstance(metadata, Mapping) else {}
    metadata_dict["model_alignment"] = alignment
    payload["metadata_json"] = metadata_dict


def _bounded_lesson_outline(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    outline: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        outline.append(
            {
                "id": _bounded_text(str(item.get("id") or ""), 80),
                "title": _bounded_text(str(item.get("title") or ""), 160),
                "note": _bounded_text(str(item.get("note") or item.get("summary") or ""), 360),
            }
        )
        if len(outline) >= 6:
            break
    return outline


def _bounded_source_attribution(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    sources: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, Mapping):
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
        else:
            title = str(item)
            url = ""
        if not title.strip() and not url.strip():
            continue
        sources.append(
            {
                "title": _bounded_text(title, 160),
                "url": _bounded_text(url, 300),
            }
        )
        if len(sources) >= 4:
            break
    return sources


def _taxonomy_hints(
    knowledge_point: Mapping[str, object],
    canonical: CanonicalExerciseTemplate,
    source_attribution: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    return {
        "language_id": canonical.language_id,
        "course_title": _bounded_text(str(knowledge_point.get("course_title") or ""), 160),
        "source_titles": [
            _bounded_text(str(source.get("title") or ""), 120)
            for source in source_attribution
            if str(source.get("title") or "").strip()
        ],
    }


def _load_cached_variant(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
    canonical: CanonicalExerciseTemplate,
    runtime_profile: Mapping[str, object],
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT *
        FROM exercise_variant_cache
        WHERE user_id = %s
          AND knowledge_point_id = %s
          AND template_id = %s
          AND template_version = %s
          AND generator_version = %s
          AND runner_key = %s
          AND runtime_tier = %s
          AND status = 'validated'
          AND deleted_at IS NULL
        ORDER BY last_used_at DESC, created_at DESC
        LIMIT 1
        """,
        (
            user_id,
            knowledge_point_id,
            canonical.template_id,
            canonical.template_version,
            ADAPTIVE_TEMPLATE_GENERATOR_VERSION,
            str(runtime_profile.get("runner") or canonical.runner_key),
            str(runtime_profile.get("runtime_tier") or canonical.runtime_tier),
        ),
    ).fetchone()


def _payload_from_cache(row: Mapping[str, object]) -> dict[str, object]:
    payload = row.get("exercise_payload_json")
    if isinstance(payload, Mapping):
        return _clone_payload(payload)
    return {}


def _touch_cached_variant(conn: Connection[dict[str, object]], cache_id: str) -> None:
    conn.execute(
        "UPDATE exercise_variant_cache SET last_used_at = now() WHERE id = %s",
        (cache_id,),
    )


def _persist_validated_variant(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
    canonical: CanonicalExerciseTemplate,
    runtime_profile: Mapping[str, object],
    payload: Mapping[str, object],
    variant_hash: str,
    validation_report: ValidationReport,
) -> None:
    conn.execute(
        """
        INSERT INTO exercise_variant_cache (
          user_id, knowledge_point_id, template_id, template_version,
          generator_version, runner_key, runtime_tier, variant_hash,
          status, exercise_payload_json, validation_report_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'validated', %s::jsonb, %s::jsonb)
        """,
        (
            user_id,
            knowledge_point_id,
            canonical.template_id,
            canonical.template_version,
            ADAPTIVE_TEMPLATE_GENERATOR_VERSION,
            str(runtime_profile.get("runner") or canonical.runner_key),
            str(runtime_profile.get("runtime_tier") or canonical.runtime_tier),
            variant_hash,
            json.dumps(_json_safe(payload), ensure_ascii=False),
            json.dumps(validation_report.as_safe_payload(), ensure_ascii=False),
        ),
    )


def _adaptive_meta(payload: Mapping[str, object]) -> Mapping[str, object]:
    metadata = payload.get("metadata_json")
    if not isinstance(metadata, Mapping):
        return {}
    adaptive = metadata.get("adaptive_variant")
    return adaptive if isinstance(adaptive, Mapping) else {}


def _variant_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clone_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(_json_safe(payload), ensure_ascii=False))


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _safe_model_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: _json_safe(item)
        for key, item in value.items()
        if key not in {"adaptive_variant", "solution_reference"}
    }


def _string_values(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        result: set[str] = set()
        for item in value.values():
            result.update(_string_values(item))
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        values: set[str] = set()
        for item in value:
            values.update(_string_values(item))
        return values
    if value is None:
        return set()
    return {str(value)}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [_bounded_text(str(item), 120) for item in value if str(item).strip()]


def _normalized_tag_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    tags: list[str] = []
    for item in value:
        tag = str(item).strip().lower().replace("-", "_")
        if tag and tag not in tags:
            tags.append(_bounded_text(tag, 120))
    return tags


def _bounded_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _str_or_none(value: object) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)
