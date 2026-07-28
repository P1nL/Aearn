from __future__ import annotations

from datetime import datetime

from app.agents.harness.contracts import (
    TutorCheckpoint,
    TutorCheckpointReason,
    TutorCompactionTrigger,
    TutorRunStatus,
    build_compaction_request,
    empty_checkpoint_metadata,
)
from app.agents.harness.skill_catalog import CatalogSkillReference
from app.services.tutor.learner_state import (
    TutorLearnerStateRepository,
    build_learner_state_effect_handlers,
)
from app.services.tutor.persistence import PostgresTutorRepository, TutorCurationEnvelope
from app.services.tutor.skill_selection import TutorSkillSelection


def select_learner_state_skill(fixture, *, input_revision: int) -> None:
    skill = next(skill for skill in fixture.catalog.skills if skill.reference.key == "tutor.learner-state@1.0.0")
    fixture.repository.record_skill_selection(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        input_revision=input_revision,
        selection=TutorSkillSelection(
            reference=CatalogSkillReference(skill.manifest.id, skill.manifest.version),
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )


def learner_state_effect_repository(fixture) -> tuple[PostgresTutorRepository, TutorLearnerStateRepository]:
    learner_state = TutorLearnerStateRepository(fixture.connection)
    repository = PostgresTutorRepository(
        fixture.connection,
        effect_handlers=build_learner_state_effect_handlers(learner_state),
    )
    return repository, learner_state


def create_curation_outbox(fixture, *, now: datetime, memory_setting_version: str = "memory_settings_v1") -> str:
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="learner-state-curation-fixture",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None
    metadata = empty_checkpoint_metadata(token_budget=64)
    checkpoint = TutorCheckpoint(
        run_id=fixture.run.run_id,
        input_revision=fixture.run.input_revision,
        reason=TutorCheckpointReason.SAFE_PROGRESS,
        status=TutorRunStatus.LEASED,
        metadata=metadata,
        created_at=now,
    )
    request = build_compaction_request(
        run_id=fixture.run.run_id,
        conversation_id=fixture.conversation_id,
        input_revision=fixture.run.input_revision,
        trigger=TutorCompactionTrigger.SAFE_CHECKPOINT,
        metadata=metadata,
    )
    fixture.repository.persist_safe_checkpoint(
        user_id=fixture.user_id,
        lease=lease,
        checkpoint=checkpoint,
        envelope=TutorCurationEnvelope(
            request=request,
            memory_setting_version=memory_setting_version,
            priority=1,
        ),
    )
    row = fixture.connection.execute(
        "SELECT id::text AS id FROM tutor_memory_curation_outbox WHERE run_id = %s",
        (fixture.run.run_id,),
    ).fetchone()
    assert row is not None
    return str(row["id"])