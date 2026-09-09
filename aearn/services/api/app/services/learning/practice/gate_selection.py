"""Finite server-owned selection and compatibility rules for Lesson Gates."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from psycopg import Connection

from app.services.learning.item_bank.contracts import LearningItemKind, LearningItemPurpose
from app.services.learning.item_bank.repository import PostgresLearningItemBankRepository
from app.services.learning.practice.contracts import ExecutionRequirement, ExerciseType


LEGACY_GATE_CONTRACT = "lesson_gate_v1"
KNOWLEDGE_CHECK_GATE_CONTRACT = "knowledge_check_v1"
MODEL_REVIEW_GATE_CONTRACT = "model_code_review_v1"
SUPPORTED_GATE_CONTRACTS = frozenset(
    {LEGACY_GATE_CONTRACT, KNOWLEDGE_CHECK_GATE_CONTRACT, MODEL_REVIEW_GATE_CONTRACT}
)
SUPPORTED_KNOWLEDGE_RESPONSE_KINDS = frozenset(
    {"short_text", "prediction", "single_choice"}
)
INCOMPATIBLE_BINDING_DISCLOSURE = (
    "该历史 Gate binding 与当前 assessment contract 不兼容；系统保留已有历史，"
    "但不接受新的提示、运行或提交。"
)


class GateSelectionUnavailable(ValueError):
    """No published exercise satisfies the exact Gate contract."""


@dataclass(frozen=True, slots=True)
class GateExerciseSelection:
    exercise_version_id: str
    exercise_key: str
    exercise_version: str
    execution_required: bool
    pass_threshold: float

    @property
    def execution_requirement(self) -> ExecutionRequirement:
        return execution_requirement_for(self.execution_required)


@dataclass(frozen=True, slots=True)
class GateBindingCompatibility:
    actionable: bool
    disclosure: str | None = None


def assessment_contract_supported(value: object) -> bool:
    return str(value or "") in SUPPORTED_GATE_CONTRACTS


def gate_slot_is_compatible(row: Mapping[str, object]) -> bool:
    """Return whether a supported Gate slot stays within its active node scope."""

    return assessment_contract_supported(
        row.get("assessment_contract_version")
    ) and _slot_capabilities_are_active(row)


def execution_requirement_for(execution_required: bool) -> ExecutionRequirement:
    return (
        ExecutionRequirement.REQUIRED
        if execution_required
        else ExecutionRequirement.FORBIDDEN
    )


def select_published_knowledge_check(
    conn: Connection[dict[str, object]],
    *,
    language_id: str,
    knowledge_key: str,
    required_capabilities: Sequence[str],
    available_capabilities: Sequence[str],
) -> GateExerciseSelection:
    capabilities = _exact_capabilities(required_capabilities)
    available = _exact_capabilities(available_capabilities)
    if not _capabilities_are_in_scope(
        capabilities,
        available,
        language_id=language_id,
        knowledge_key=knowledge_key,
    ):
        raise GateSelectionUnavailable(
            "Gate capabilities are outside the active track node scope"
        )
    candidates = PostgresLearningItemBankRepository(conn).published_candidates(
        knowledge_key=knowledge_key,
        purpose=LearningItemPurpose.KNOWLEDGE_CHECK,
        language_id=language_id,
        kinds=(LearningItemKind.KNOWLEDGE_CHECK,),
        available_capabilities=capabilities,
        exact_capabilities=True,
        limit=8,
    )
    for candidate in candidates:
        locked_version = conn.execute(
            """
            SELECT id
            FROM tutor_learning_item_versions
            WHERE handle = %s
            FOR UPDATE
            """,
            (candidate.handle,),
        ).fetchone()
        if locked_version is None:
            continue
        row = conn.execute(
            """
            SELECT versions.id AS learning_item_version_id,
                   versions.handle AS item_handle,
                   versions.item_key, versions.version AS item_version,
                   versions.item_kind, versions.purpose,
                   versions.knowledge_key AS item_knowledge_key,
                   versions.language_id AS item_language_id,
                   versions.required_capabilities_json AS item_capabilities_json,
                   versions.content_hash AS item_content_hash,
                   public.public_json,
                   publication.state AS publication_state,
                   materializations.item_handle AS materialization_handle,
                   materializations.content_hash AS materialization_content_hash,
                   materializations.exercise_version_id,
                   materializations.exercise_key AS materialization_exercise_key,
                   materializations.exercise_version AS materialization_exercise_version,
                   materializations.exercise_content_hash AS materialization_exercise_content_hash,
                   materializations.rubric_hash AS materialization_rubric_hash,
                   exercises.language_id AS exercise_language_id,
                   exercises.exercise_key, exercises.version AS exercise_version,
                   exercises.exercise_type, exercises.source_kind,
                   exercises.required_capabilities_json AS exercise_capabilities_json,
                   exercises.runtime_profile_key, exercises.execution_required,
                   exercises.validation_status,
                   exercises.content_hash AS exercise_content_hash,
                   rubrics.reference_answer_json, rubrics.score_policy_json,
                   rubrics.rubric_hash
            FROM tutor_learning_item_versions AS versions
            JOIN tutor_learning_item_public_contents AS public
              ON public.version_id = versions.id
            JOIN LATERAL (
              SELECT events.state
              FROM tutor_learning_item_publication_events AS events
              WHERE events.version_id = versions.id
              ORDER BY events.state_version DESC LIMIT 1
            ) AS publication ON true
            JOIN tutor_learning_item_practice_materializations AS materializations
              ON materializations.version_id = versions.id
            JOIN tutor_exercise_versions AS exercises
              ON exercises.id = materializations.exercise_version_id
            JOIN tutor_exercise_private_rubrics AS rubrics
              ON rubrics.exercise_version_id = exercises.id
            WHERE versions.id = %s
            """,
            (locked_version["id"],),
        ).fetchone()
        if row is not None and _published_knowledge_row_is_compatible(
            row,
            language_id=language_id,
            knowledge_key=knowledge_key,
            capabilities=capabilities,
        ):
            score_policy = _mapping(row.get("score_policy_json"))
            return GateExerciseSelection(
                exercise_version_id=str(row["exercise_version_id"]),
                exercise_key=str(row["exercise_key"]),
                exercise_version=str(row["exercise_version"]),
                execution_required=bool(row["execution_required"]),
                pass_threshold=_threshold(score_policy.get("threshold")),
            )
    raise GateSelectionUnavailable(
        "no published static knowledge check matches the exact Gate scope"
    )


def gate_binding_compatibility(row: Mapping[str, object]) -> GateBindingCompatibility:
    contract = str(row.get("assessment_contract_version") or "")
    if contract == LEGACY_GATE_CONTRACT:
        compatible = _legacy_binding_is_compatible(row)
    elif contract == KNOWLEDGE_CHECK_GATE_CONTRACT:
        compatible = _knowledge_binding_is_compatible(row)
    elif contract == MODEL_REVIEW_GATE_CONTRACT:
        compatible = _model_review_binding_is_compatible(row)
    else:
        compatible = False
    return GateBindingCompatibility(
        actionable=compatible,
        disclosure=None if compatible else INCOMPATIBLE_BINDING_DISCLOSURE,
    )


def _legacy_binding_is_compatible(row: Mapping[str, object]) -> bool:
    if (
        not _base_scope_is_compatible(row)
        or str(row.get("source_kind") or "") != "curated_fixture"
    ):
        return False
    exercise_type = str(row.get("exercise_type") or "")
    if exercise_type == ExerciseType.STATIC_CODE_REASONING.value:
        reference = _mapping(row.get("reference_answer_json"))
        score_policy = _mapping(row.get("score_policy_json"))
        return (
            not bool(row.get("execution_required"))
            and row.get("runtime_profile_key") is None
            and str(row.get("execution_requirement") or "")
            == ExecutionRequirement.FORBIDDEN.value
            and bool(_accepted_answers(reference.get("accepted_answers")))
            and str(score_policy.get("kind") or "") == "exact_normalized"
            and _thresholds_match(
                score_policy.get("threshold"), row.get("pass_threshold")
            )
        )
    return (
        exercise_type
        in {
            ExerciseType.CODE_COMPLETION.value,
            ExerciseType.SQL_QUERY.value,
            ExerciseType.BROWSER_PREVIEW.value,
        }
        and bool(row.get("execution_required"))
        and row.get("runtime_profile_key") is not None
        and str(row.get("execution_requirement") or "")
        == ExecutionRequirement.REQUIRED.value
    )


def _knowledge_binding_is_compatible(row: Mapping[str, object]) -> bool:
    public = _mapping(row.get("item_public_json"))
    return (
        _base_scope_is_compatible(row)
        and str(row.get("exercise_type") or "")
        == ExerciseType.STATIC_CODE_REASONING.value
        and str(row.get("source_kind") or "") == "curated_fixture"
        and not bool(row.get("execution_required"))
        and row.get("runtime_profile_key") is None
        and str(row.get("execution_requirement") or "")
        == ExecutionRequirement.FORBIDDEN.value
        and str(row.get("latest_publication_state") or "") == "published"
        and str(row.get("item_kind") or "") == LearningItemKind.KNOWLEDGE_CHECK.value
        and str(row.get("item_purpose") or "")
        == LearningItemPurpose.KNOWLEDGE_CHECK.value
        and str(row.get("item_knowledge_key") or "")
        == str(row.get("scope_knowledge_key") or "")
        and str(row.get("item_language_id") or "")
        == str(row.get("scope_language_id") or "")
        and _capabilities(row.get("item_capabilities_json"))
        == _capabilities(row.get("slot_capabilities_json"))
        and str(row.get("materialization_handle") or "")
        == str(row.get("item_handle") or "")
        and str(row.get("materialization_content_hash") or "")
        == str(row.get("item_content_hash") or "")
        and str(row.get("materialization_exercise_version_id") or "")
        == str(row.get("exercise_version_id") or "")
        and str(row.get("materialization_exercise_key") or "")
        == str(row.get("exercise_key") or "")
        and str(row.get("materialization_exercise_version") or "")
        == str(row.get("exercise_version") or "")
        and str(row.get("materialization_exercise_content_hash") or "")
        == str(row.get("exercise_content_hash") or "")
        and str(row.get("materialization_rubric_hash") or "")
        == str(row.get("stored_rubric_hash") or "")
        and _knowledge_response_contract_is_supported(
            public,
            _mapping(row.get("reference_answer_json")),
            _mapping(row.get("score_policy_json")),
        )
    )


def _model_review_binding_is_compatible(row: Mapping[str, object]) -> bool:
    return (
        _base_scope_is_compatible(row)
        and str(row.get("exercise_type") or "") == ExerciseType.MODEL_CODE_REVIEW.value
        and str(row.get("source_kind") or "") == "registered_author"
        and not bool(row.get("execution_required"))
        and row.get("runtime_profile_key") is None
        and str(row.get("execution_requirement") or "")
        == ExecutionRequirement.FORBIDDEN.value
    )


def _base_scope_is_compatible(row: Mapping[str, object]) -> bool:
    expected_requirement = {
        "knowledge_check": "required",
        "guided_practice": "recommended",
        "independent_practice": "diagnostic",
    }.get(str(row.get("gate_kind") or ""))
    slot_capabilities = _capabilities(row.get("slot_capabilities_json"))
    return (
        expected_requirement is not None
        and str(row.get("requirement_kind") or "") == expected_requirement
        and str(row.get("binding_knowledge_key") or "")
        == str(row.get("scope_knowledge_key") or "")
        and str(row.get("exercise_language_id") or "")
        == str(row.get("scope_language_id") or "")
        and _capabilities(row.get("exercise_capabilities_json")) == slot_capabilities
        and _slot_capabilities_are_active(row)
    )


def _slot_capabilities_are_active(row: Mapping[str, object]) -> bool:
    slot_capabilities = _capabilities(
        row.get("slot_capabilities_json")
        if row.get("slot_capabilities_json") is not None
        else row.get("required_capabilities_json")
    )
    node_capabilities = _capabilities(row.get("node_capabilities_json"))
    return bool(slot_capabilities) and _capabilities_are_in_scope(
        slot_capabilities,
        node_capabilities,
        language_id=str(
            row.get("scope_language_id") or row.get("language_id") or ""
        ),
        knowledge_key=str(
            row.get("scope_knowledge_key") or row.get("knowledge_key") or ""
        ),
    )


def _capabilities_are_in_scope(
    required: Sequence[str],
    available: Sequence[str],
    *,
    language_id: str,
    knowledge_key: str,
) -> bool:
    authorized = set(available)
    if language_id in authorized and knowledge_key:
        authorized.add(knowledge_key)
    return set(required).issubset(authorized)


def _knowledge_response_contract_is_supported(
    public: Mapping[str, object],
    reference: Mapping[str, object],
    score_policy: Mapping[str, object],
) -> bool:
    content = _mapping(public.get("content"))
    accepted = _accepted_answers(reference.get("accepted_answers"))
    response_kind = str(content.get("response_kind") or "")
    if (
        content.get("type") != "knowledge_check"
        or response_kind not in SUPPORTED_KNOWLEDGE_RESPONSE_KINDS
        or not accepted
        or str(score_policy.get("kind") or "") != "static_exact"
        or not _valid_threshold(score_policy.get("threshold"))
    ):
        return False
    if response_kind != "single_choice":
        return True
    options = content.get("options")
    if not isinstance(options, (list, tuple)):
        return False
    option_ids = {
        str(option.get("option_id"))
        for option in options
        if isinstance(option, Mapping) and option.get("option_id") is not None
    }
    return len(accepted) == 1 and accepted[0] in option_ids


def _published_knowledge_row_is_compatible(
    row: Mapping[str, object],
    *,
    language_id: str,
    knowledge_key: str,
    capabilities: tuple[str, ...],
) -> bool:
    public = _mapping(row.get("public_json"))
    reference = _mapping(row.get("reference_answer_json"))
    score_policy = _mapping(row.get("score_policy_json"))
    return (
        _knowledge_response_contract_is_supported(public, reference, score_policy)
        and str(row.get("publication_state") or "") == "published"
        and str(row.get("item_handle") or "")
        == str(row.get("materialization_handle") or "")
        and str(row.get("item_content_hash") or "")
        == str(row.get("materialization_content_hash") or "")
        and str(row.get("item_kind") or "") == LearningItemKind.KNOWLEDGE_CHECK.value
        and str(row.get("purpose") or "") == LearningItemPurpose.KNOWLEDGE_CHECK.value
        and str(row.get("item_knowledge_key") or "") == knowledge_key
        and str(row.get("item_language_id") or "") == language_id
        and _capabilities(row.get("item_capabilities_json")) == capabilities
        and str(row.get("materialization_exercise_key") or "")
        == str(row.get("item_key") or "")
        and str(row.get("materialization_exercise_version") or "")
        == str(row.get("item_version") or "")
        and str(row.get("materialization_exercise_content_hash") or "")
        == str(row.get("exercise_content_hash") or "")
        and str(row.get("materialization_rubric_hash") or "")
        == str(row.get("rubric_hash") or "")
        and str(row.get("exercise_language_id") or "") == language_id
        and str(row.get("exercise_type") or "")
        == ExerciseType.STATIC_CODE_REASONING.value
        and str(row.get("source_kind") or "") == "curated_fixture"
        and _capabilities(row.get("exercise_capabilities_json")) == capabilities
        and row.get("runtime_profile_key") is None
        and not bool(row.get("execution_required"))
        and str(row.get("validation_status") or "") == "ready"
    )


def _exact_capabilities(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip().lower() for value in values)
    if not normalized or any(not value for value in normalized):
        raise GateSelectionUnavailable("Gate capabilities must be non-empty")
    if len(normalized) != len(set(normalized)):
        raise GateSelectionUnavailable("Gate capabilities must be unique")
    return tuple(sorted(normalized))


def _capabilities(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    normalized = tuple(str(item) for item in value)
    if len(normalized) != len(set(normalized)):
        return ()
    return tuple(sorted(normalized))


def _accepted_answers(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    answers = tuple(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    return answers if len(answers) == len(value) and len(answers) == len(set(answers)) else ()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _valid_threshold(value: object) -> bool:
    try:
        threshold = float(str(value))
    except (TypeError, ValueError):
        return False
    return 0 < threshold <= 1


def _thresholds_match(left: object, right: object) -> bool:
    return (
        _valid_threshold(left)
        and _valid_threshold(right)
        and float(str(left)) == float(str(right))
    )


def _threshold(value: object) -> float:
    if not _valid_threshold(value):
        raise GateSelectionUnavailable("knowledge-check score threshold is invalid")
    return float(str(value))


__all__ = (
    "GateBindingCompatibility",
    "GateExerciseSelection",
    "GateSelectionUnavailable",
    "INCOMPATIBLE_BINDING_DISCLOSURE",
    "KNOWLEDGE_CHECK_GATE_CONTRACT",
    "LEGACY_GATE_CONTRACT",
    "MODEL_REVIEW_GATE_CONTRACT",
    "SUPPORTED_KNOWLEDGE_RESPONSE_KINDS",
    "assessment_contract_supported",
    "execution_requirement_for",
    "gate_binding_compatibility",
    "gate_slot_is_compatible",
    "select_published_knowledge_check",
)
