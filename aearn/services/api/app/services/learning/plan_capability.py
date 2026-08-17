"""Server-owned handler for the exact learning.plan.draft capability."""
from __future__ import annotations

import json
from psycopg import Connection

from app.agents.harness.capabilities import (
    LearningPlanDraftCapabilityInput,
    LearningPlanDraftCapabilityOutput,
)
from app.agents.harness.contracts import TutorCapabilityStatus, TutorRunSnapshot
from app.services.grounding.grounding_sources import GroundingSource, sources_for_language
from app.services.learning.plan_drafting import (
    LearningPlanDraftArtifact,
    LearningPlanSourceSummary,
    decode_compact_profile,
    decode_plan_draft,
)
from app.services.learning.planning_facts import PlanningFactError, PostgresPlanningFactRepository
from app.services.learning.plan_repository import (
    LearningPlanDraftConflict,
    LearningPlanSessionConflict,
    LearningPlanSessionNotFound,
    PostgresLearningPlanSessionRepository,
)
from app.services.runners.language_capabilities import (
    LanguageCapability,
    capabilities_for_public_course_language,
    get_language_capability,
)


class LearningPlanDraftCapabilityError(ValueError):
    """Typed learner-safe capability failure that can cross transaction boundaries."""

    def __init__(
        self,
        *,
        code: str,
        diagnostic_code: str,
        status: TutorCapabilityStatus,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.diagnostic_code = diagnostic_code
        self.status = status


class LearningPlanDraftCapabilityHandler:
    """Validate nested compact input and persist only the typed domain artifact."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._repository = PostgresLearningPlanSessionRepository(conn)
        self._facts = PostgresPlanningFactRepository(conn)

    def generate(
        self,
        *,
        run: TutorRunSnapshot,
        capability_input: LearningPlanDraftCapabilityInput,
    ) -> LearningPlanDraftCapabilityOutput:
        session_id: str | None = None
        try:
            with self._conn.transaction():
                session = self._repository.active_session_for_run(
                    user_id=run.user_id,
                    run_id=run.run_id,
                    input_revision=run.input_revision,
                    for_update=True,
                )
                session_id = str(session["id"])
                artifact = self._artifact(session=session, capability_input=capability_input)
                facts_fingerprint, facts_revision = self._facts.validate_profile(
                    user_id=run.user_id,
                    session_id=session_id,
                    profile=artifact.profile.model_dump(mode="json"),
                    require_complete=False,
                )
                row, _replayed = self._repository.append_draft(
                    user_id=run.user_id,
                    run_id=run.run_id,
                    input_revision=run.input_revision,
                    artifact=artifact,
                    facts_fingerprint=facts_fingerprint,
                    facts_revision=facts_revision,
                )
                return LearningPlanDraftCapabilityOutput(
                    status="completed",
                    draft_id=str(row["id"]),
                    draft_version=_int(row["draft_version"]),
                    content_hash=str(row["content_hash"]),
                    quality_status="passed",
                )
        except PlanningFactError as exc:
            if session_id is not None:
                self._repository.record_safe_error(
                    user_id=run.user_id,
                    session_id=session_id,
                    code="LEARNING_PLAN_DRAFT_INVALID",
                )
            raise _invalid() from exc
        except LearningPlanDraftCapabilityError as exc:
            if session_id is not None:
                self._repository.record_safe_error(
                    user_id=run.user_id,
                    session_id=session_id,
                    code=exc.code,
                )
            raise
        except LearningPlanSessionNotFound as exc:
            raise LearningPlanDraftCapabilityError(
                code="LEARNING_PLAN_CAPABILITY_UNAVAILABLE",
                diagnostic_code="learning_plan_session_unavailable",
                status=TutorCapabilityStatus.DENIED,
            ) from exc
        except (LearningPlanDraftConflict, LearningPlanSessionConflict) as exc:
            if session_id is not None:
                self._repository.record_safe_error(
                    user_id=run.user_id,
                    session_id=session_id,
                    code="LEARNING_PLAN_DRAFT_INVALID",
                )
            raise LearningPlanDraftCapabilityError(
                code="LEARNING_PLAN_DRAFT_INVALID",
                diagnostic_code="learning_plan_draft_conflict",
                status=TutorCapabilityStatus.DENIED,
            ) from exc

    def _artifact(
        self,
        *,
        session: dict[str, object],
        capability_input: LearningPlanDraftCapabilityInput,
    ) -> LearningPlanDraftArtifact:
        try:
            profile = decode_compact_profile(capability_input.profile_json)
        except ValueError as exc:
            raise _invalid() from exc
        canonical, language_capabilities = _language(profile.language_id)
        if not language_capabilities or not all(item.enabled_for_public_selection for item in language_capabilities):
            raise LearningPlanDraftCapabilityError(
                code="LEARNING_LANGUAGE_NOT_SELECTABLE",
                diagnostic_code="learning_language_not_selectable",
                status=TutorCapabilityStatus.DENIED,
            )
        preferred = str(session.get("preferred_language_id") or "")
        if preferred and preferred != canonical:
            raise _invalid()
        sources = _source_summaries(language_capabilities)
        if not sources:
            raise LearningPlanDraftCapabilityError(
                code="LEARNING_PLAN_DRAFT_QUALITY_BLOCKED",
                diagnostic_code="learning_plan_source_quality_blocked",
                status=TutorCapabilityStatus.UNAVAILABLE,
            )
        normalized_profile = profile.model_copy(update={"language_id": canonical})
        try:
            artifact = decode_plan_draft(
                profile_json=json.dumps(
                    normalized_profile.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                module_json_values=capability_input.module_values(),
                sources=sources,
                change_reason=(
                    "Create the learner-confirmable initial learning plan draft."
                    if session.get("current_draft_id") is None
                    else "Replace the current learning plan draft after learner-requested changes."
                ),
            )
        except ValueError as exc:
            raise _invalid() from exc
        _validate_quality(artifact=artifact, capabilities=language_capabilities, canonical_language_id=canonical)
        return artifact


def _language(value: str) -> tuple[str, tuple[LanguageCapability, ...]]:
    normalized = value.strip().lower()
    direct = get_language_capability(normalized)
    if direct is not None:
        return direct.language_id, (direct,)
    public = capabilities_for_public_course_language(normalized)
    if public:
        return normalized, public
    raise LearningPlanDraftCapabilityError(
        code="LEARNING_LANGUAGE_NOT_SELECTABLE",
        diagnostic_code="learning_language_not_selectable",
        status=TutorCapabilityStatus.DENIED,
    )


def _source_summaries(capabilities: tuple[LanguageCapability, ...]) -> tuple[LearningPlanSourceSummary, ...]:
    accepted: list[GroundingSource] = []
    seen: set[str] = set()
    for capability in capabilities:
        for source in sources_for_language(capability.language_id):
            if source.source_id in seen or not _trust_matches(source.trust_tier, capability.source_trust_policy):
                continue
            seen.add(source.source_id)
            accepted.append(source)
    return tuple(
        LearningPlanSourceSummary(
            source_id=source.source_id,
            display_name=source.display_name,
            trust_tier=source.trust_tier,
        )
        for source in accepted[:8]
    )


def _trust_matches(trust_tier: str, policy: str) -> bool:
    if policy == "official":
        return trust_tier == "official"
    if policy == "trusted_de_facto":
        return trust_tier in {"official", "trusted_de_facto"}
    return trust_tier == "internal" if policy == "internal" else False


def _validate_quality(
    *,
    artifact: LearningPlanDraftArtifact,
    capabilities: tuple[LanguageCapability, ...],
    canonical_language_id: str,
) -> None:
    if not any(module.is_core for module in artifact.plan.modules) or not any(node.is_core for node in artifact.plan.nodes):
        raise _quality_blocked()
    allowed_capabilities = {canonical_language_id}
    for capability in capabilities:
        allowed_capabilities.add(capability.language_id)
        if capability.runner_key != "none":
            allowed_capabilities.add(capability.runner_key)
    if any(
        required not in allowed_capabilities
        for node in artifact.plan.nodes
        for required in node.required_capabilities
    ):
        raise _quality_blocked()


def _invalid() -> LearningPlanDraftCapabilityError:
    return LearningPlanDraftCapabilityError(
        code="LEARNING_PLAN_DRAFT_INVALID",
        diagnostic_code="learning_plan_draft_invalid",
        status=TutorCapabilityStatus.DENIED,
    )


def _quality_blocked() -> LearningPlanDraftCapabilityError:
    return LearningPlanDraftCapabilityError(
        code="LEARNING_PLAN_DRAFT_QUALITY_BLOCKED",
        diagnostic_code="learning_plan_draft_quality_blocked",
        status=TutorCapabilityStatus.UNAVAILABLE,
    )


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
