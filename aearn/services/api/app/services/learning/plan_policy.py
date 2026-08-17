"""Database-backed default-deny policy for the learning-plan drafting task."""
from __future__ import annotations

from psycopg import Connection

from app.agents.harness.capabilities import LEARNING_PLAN_DRAFT_CAPABILITY_ID
from app.agents.harness.contracts import TutorRunSnapshot
from app.agents.harness.skill_catalog import SkillCatalogSnapshot
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
    _SKILL_VERSION = "1.0.1"

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._repository = PostgresLearningPlanSessionRepository(conn)

    def resolve(
        self,
        *,
        run: TutorRunSnapshot,
        catalog: SkillCatalogSnapshot,
    ) -> CapabilityPolicyContext:
        denied = DefaultDenyCapabilityPolicyResolver().resolve(run=run, catalog=catalog)
        if run.origin != "interactive" or run.cancelled or run.input_revision < 1:
            return denied
        try:
            self._repository.active_session_for_run(
                user_id=run.user_id,
                run_id=run.run_id,
                input_revision=run.input_revision,
            )
        except LearningPlanSessionNotFound:
            return denied
        skill = catalog.resolve_skill(self._SKILL_ID, self._SKILL_VERSION)
        descriptor = catalog.capability(LEARNING_PLAN_DRAFT_CAPABILITY_ID)
        if skill is None or descriptor is None:
            return denied
        return CapabilityPolicyContext(
            run_id=run.run_id,
            user_id=run.user_id,
            origin=run.origin,
            input_revision=run.input_revision,
            catalog_digest=catalog.digest,
            eligible_skill_references=(skill.reference,),
            eligible_capability_ids=(LEARNING_PLAN_DRAFT_CAPABILITY_ID,),
            granted_policy_tags=("plan-drafting",),
            allowed_origins=("interactive",),
            consent_granted=True,
            runtime_available_capability_ids=(LEARNING_PLAN_DRAFT_CAPABILITY_ID,),
            remaining_capability_budget=max(
                0,
                run.policy.max_capability_calls - run.capability_call_count,
            ),
        )
