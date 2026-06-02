from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from psycopg import Connection

from app.services.exercise_templates import (
    ADAPTIVE_TEMPLATE_GENERATOR_VERSION,
    ADAPTIVE_TEMPLATE_PROMPT_VERSION,
    CanonicalExerciseTemplate,
    select_canonical_exercise_template,
)
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError, OpenAICompatibleClient
from app.services.runner_registry import get_runner_registry
from app.services.runtime_runner import run_exercise


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
        return _fallback_template(
            fallback_template,
            canonical=canonical,
            runtime_profile=runtime_profile,
            fallback_reason="runner_unsupported",
        )

    user_id = str(knowledge_point.get("user_id") or "")
    knowledge_point_id = str(knowledge_point.get("id") or "")
    if not user_id or not knowledge_point_id:
        return _fallback_template(
            fallback_template,
            canonical=canonical,
            runtime_profile=runtime_profile,
            fallback_reason="missing_user_scope",
        )

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

    model_context = _model_context(knowledge_point, runtime_profile, canonical)
    generator = candidate_generator or build_model_candidate
    candidate_payload: dict[str, object] | None = None
    source = "model_candidate"
    model_name: str | None = None
    fallback_reason: str | None = None

    try:
        generated = generator(model_context, canonical)
    except SAFE_GENERATION_EXCEPTIONS:
        generated = None
        fallback_reason = "model_generation_failed"

    if generated is None:
        candidate_payload = _deterministic_candidate(canonical)
        source = "deterministic_fallback"
        fallback_reason = fallback_reason or "provider_unavailable"
    else:
        try:
            candidate_payload = _candidate_payload_from_generated(generated.content, canonical)
            model_name = generated.model
        except ValueError:
            candidate_payload = _deterministic_candidate(canonical)
            source = "deterministic_fallback"
            fallback_reason = "invalid_model_candidate"

    validation = _validate_candidate(candidate_payload, runtime_profile)
    if not validation.passed:
        return _fallback_template(
            fallback_template,
            canonical=canonical,
            runtime_profile=runtime_profile,
            fallback_reason="validation_failed",
            validation_report=validation,
        )

    variant_hash = _variant_hash(candidate_payload)
    payload = _with_adaptive_metadata(
        candidate_payload,
        canonical=canonical,
        runtime_profile=runtime_profile,
        source=source,
        validation_status="validated",
        generator_model=model_name,
        fallback_reason=fallback_reason,
        variant_hash=variant_hash,
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
        "starter_code": str(fallback.get("starter_code") or "")[:1200],
        "code_blanks": fallback.get("code_blanks") if isinstance(fallback.get("code_blanks"), list) else [],
        "metadata_json": _safe_model_metadata(fallback.get("metadata_json")),
    }
    return [
        {
            "role": "system",
            "content": (
                "You generate Aearn programming exercise variants inside a canonical template envelope. "
                "Return JSON only. Do not invent test cases, runtime tiers, hidden data, provider payloads, or unsupported fields."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "adaptive_exercise_candidate",
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
        raise ValueError("candidate must be an object")
    unsupported = set(candidate) - MODEL_CANDIDATE_ALLOWED_KEYS
    if unsupported:
        raise ValueError(f"unsupported candidate fields: {sorted(unsupported)}")

    payload = _clone_payload(canonical.fallback_payload)
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
            raise ValueError("candidate metadata is invalid")
        base_metadata = payload.get("metadata_json", {})
        payload["metadata_json"] = {
            **(dict(base_metadata) if isinstance(base_metadata, Mapping) else {}),
            **dict(metadata),
        }

    if "code_blanks" in candidate:
        code_blanks = candidate["code_blanks"]
        if not isinstance(code_blanks, list) or not all(isinstance(blank, Mapping) for blank in code_blanks):
            raise ValueError("candidate code_blanks are invalid")
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
    for test_case in test_cases:
        if not isinstance(test_case, Mapping) or str(test_case.get("case_type", "visible")) != "hidden":
            continue
        case_id = test_case.get("id")
        if isinstance(case_id, str):
            markers.add(case_id)
        markers.update(value for value in _string_values(test_case.get("expected_output_json")) if len(value) >= 3)
    return markers


def _assert_candidate_safe(payload: Mapping[str, object], canonical: CanonicalExerciseTemplate) -> None:
    for key in ("title", "prompt_markdown", "starter_code"):
        text = str(payload.get(key) or "")
        lowered = text.lower()
        if any(marker in lowered for marker in FORBIDDEN_LEARNER_TEXT_MARKERS):
            raise ValueError("candidate learner-facing text contains forbidden marker")
        solution = str(payload.get("solution_reference") or "")
        if key != "starter_code" and solution and solution in text:
            raise ValueError("candidate learner-facing text exposed solution reference")
    hidden_markers = _hidden_markers(canonical.fallback_payload)
    learner_text = "\n".join(str(payload.get(key) or "") for key in ("title", "prompt_markdown", "starter_code"))
    if any(marker and marker in learner_text for marker in hidden_markers):
        raise ValueError("candidate learner-facing text exposed hidden test data")


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
    metadata_dict["adaptive_variant"] = adaptive
    cloned["metadata_json"] = metadata_dict
    return cloned


def _model_context(
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
    canonical: CanonicalExerciseTemplate,
) -> dict[str, object]:
    return {
        "user_id": str(knowledge_point.get("user_id") or ""),
        "plan_id": str(knowledge_point.get("plan_id") or ""),
        "knowledge_point_id": str(knowledge_point.get("id") or ""),
        "knowledge_point_title": str(knowledge_point.get("title") or ""),
        "knowledge_point_description": _bounded_text(str(knowledge_point.get("description") or ""), 500),
        "weak_points": _string_list(knowledge_point.get("weak_points_json"))[:6],
        "language_id": canonical.language_id,
        "runtime_tier": canonical.runtime_tier,
        "runner_key": canonical.runner_key,
        "exercise_type": canonical.exercise_type,
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


def _bounded_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _str_or_none(value: object) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)
