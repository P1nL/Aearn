"""Database-backed default-deny policy for the learning-plan drafting task."""
from __future__ import annotations

from psycopg import Connection

from app.agents.harness.capabilities import LEARNING_PLAN_DRAFT_CAPABILITY_ID
from app.agents.harness.contracts import TutorRunSnapshot
from app.agents.harness.skill_catalog import SkillCatalogSnapshot
from app.core.config import Settings, get_settings
from app.services.learning.teaching_sessions import TeachingSessionConflict, TeachingSessionRepository
from app.services.learning.plan_repository import (
    LearningPlanSessionNotFound,
    PostgresLearningPlanSessionRepository,
)
from app.services.tutor.capability_policy import (
    CapabilityPolicyContext,
    DefaultDenyCapabilityPolicyResolver,
)


class InteractiveLearningCapabilityPolicyResolver:
    """Grant only the exact plan Skill for a current active planning run."""

    _SKILL_ID = "tutor.learning-plan-draft"
    _SKILL_VERSION = "1.0.3"
    _TEACHING_SKILL_ID = "tutor.lesson-teaching"
    _TEACHING_SKILL_VERSION = "1.2.1"

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings | None = None,
        material_plan_v110: bool = False,
    ) -> None:
        resolved_settings = settings or get_settings()
        self._repository = PostgresLearningPlanSessionRepository(conn)
        self._teaching = TeachingSessionRepository(conn, settings=resolved_settings)
        self._plan_skill_version = "1.1.0" if material_plan_v110 else self._SKILL_VERSION

    def resolve(
        self,
        *,
        run: TutorRunSnapshot,
        catalog: SkillCatalogSnapshot,
    ) -> CapabilityPolicyContext:
        denied = DefaultDenyCapabilityPolicyResolver().resolve(run=run, catalog=catalog)
        if run.origin != "interactive" or run.cancelled:
            return denied
        try:
            teaching = self._teaching.teaching_context(user_id=run.user_id, run_id=run.run_id)
        except TeachingSessionConflict:
            return denied
        if teaching is not None:
            skill = catalog.resolve_skill(self._TEACHING_SKILL_ID, self._TEACHING_SKILL_VERSION)
            if skill is None:
                return denied
            return CapabilityPolicyContext(
                run_id=run.run_id, user_id=run.user_id, origin=run.origin,
                input_revision=run.input_revision, catalog_digest=catalog.digest,
                eligible_skill_references=(skill.reference,), eligible_capability_ids=(),
                granted_policy_tags=("lesson-teaching",), allowed_origins=("interactive",),
                consent_granted=True, runtime_available_capability_ids=(),
                remaining_capability_budget=0,
            )
        if run.input_revision < 1:
            return denied
        try:
            self._repository.active_session_for_run(
                user_id=run.user_id, run_id=run.run_id, input_revision=run.input_revision,
            )
        except LearningPlanSessionNotFound:
            return denied
        skill = catalog.resolve_skill(self._SKILL_ID, self._plan_skill_version)
        descriptor = (catalog.capability_for_skill(LEARNING_PLAN_DRAFT_CAPABILITY_ID, skill.reference)
                      if skill is not None else None)
        if skill is None or descriptor is None:
            return denied
        return CapabilityPolicyContext(
            run_id=run.run_id, user_id=run.user_id, origin=run.origin,
            input_revision=run.input_revision, catalog_digest=catalog.digest,
            eligible_skill_references=(skill.reference,),
            eligible_capability_ids=(LEARNING_PLAN_DRAFT_CAPABILITY_ID,),
            granted_policy_tags=("plan-drafting",), allowed_origins=("interactive",),
            consent_granted=True,
            runtime_available_capability_ids=(LEARNING_PLAN_DRAFT_CAPABILITY_ID,),
            remaining_capability_budget=max(0, run.policy.max_capability_calls - run.capability_call_count),
        )
