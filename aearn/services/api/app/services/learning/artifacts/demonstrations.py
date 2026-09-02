"""Published demonstration descriptors and exactly-once completion receipts."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from psycopg import Connection
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactCompleteDemoAction,
    TutorArtifactDemoInteractionEvidenceV1,
    TutorArtifactDemoVisibleClockEvidenceV1,
    TutorArtifactDemonstrationEventV2,
    TutorArtifactDemonstrationPresentationV1,
    TutorArtifactDemonstrationPresentationV2,
    TutorArtifactDemonstrationStepV2,
    TutorPublicArtifactItem,
    canonical_hash,
    sha256_text,
)
from app.services.learning.artifacts.owner_adapters import (
    ArtifactOwnerActionInvalid,
    ArtifactOwnerVersionConflict,
)
from app.services.learning.item_bank.contracts import (
    LearningItemDemoContentV1,
    LearningItemDemoContentV2,
    LearningItemDemoStepV2,
)

_DEMO_RECEIPT_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://aearn.local/contracts/tutor-demonstration-completion-v1",
)
_MAX_PRESENTATION_STEP_CHARS = 12_000
_MAX_PRESENTATION_STEPS = 8
_MAX_STATIC_TOTAL_SECONDS = 240


@dataclass(frozen=True, slots=True)
class DemonstrationCompletionReceipt:
    receipt_id: str
    completion_kind: str
    descriptor_hash: str
    replayed: bool = False


def calculate_static_demonstration_duration_seconds(
    *,
    source_content: str,
    instruction_markdown: str,
) -> int:
    """Return a deterministic 6..30 second fallback for one visible step."""

    source = str(source_content)
    instruction = str(instruction_markdown)
    nonblank_lines = sum(1 for line in source.splitlines() if line.strip()) or 1
    source_units = math.ceil(len(source) / 110)
    line_units = math.ceil(nonblank_lines / 4)
    instruction_units = math.ceil(len(instruction.split()) / 18)
    return max(6, min(30, 4 + source_units + line_units + instruction_units))


def build_demonstration_presentation(
    *,
    content: LearningItemDemoContentV1 | LearningItemDemoContentV2,
    item_version: str,
    instruction_markdown: str,
) -> TutorArtifactDemonstrationPresentationV1 | TutorArtifactDemonstrationPresentationV2:
    """Materialize only the published source; provider-selected fields are ignored."""

    if isinstance(content, LearningItemDemoContentV1):
        return TutorArtifactDemonstrationPresentationV1(
            demonstration_mode=(
                "interactive" if content.completion_mode == "exact_event" else "static"
            ),
            language_id=content.language_id,
            source_content=content.source_code,
            source_content_hash=sha256_text(content.source_code),
            expected_event_key=(
                content.expected_event.event_name
                if content.expected_event is not None
                else None
            ),
            duration_seconds=content.duration_seconds,
        )

    static = content.completion_mode == "static_duration"
    steps: list[TutorArtifactDemonstrationStepV2] = []
    for source_step in content.steps:
        materialized = _materialize_step(
            source_step,
            static=static,
        )
        steps.extend(materialized)
    if not steps or len(steps) > _MAX_PRESENTATION_STEPS:
        raise ArtifactOwnerActionInvalid(
            "published demonstration cannot be represented within the step bound"
        )
    total_duration = (
        sum(int(step.duration_seconds or 0) for step in steps) if static else None
    )
    if total_duration is not None and total_duration > _MAX_STATIC_TOTAL_SECONDS:
        raise ArtifactOwnerActionInvalid(
            "published demonstration duration exceeds the descriptor bound"
        )
    expected_event = (
        TutorArtifactDemonstrationEventV2(
            event_key=content.expected_event.event_name,
            payload_json=content.expected_event.payload_json,
            payload_hash=canonical_hash(content.expected_event.payload_json),
        )
        if content.expected_event is not None
        else None
    )
    return TutorArtifactDemonstrationPresentationV2(
        demonstration_mode="static" if static else "interactive",
        source_version=content.source_version,
        language_id=content.language_id,
        steps=tuple(steps),
        expected_event=expected_event,
        total_duration_seconds=total_duration,
    )


def complete_demonstration(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    request: TutorArtifactActionRequest,
    occurred_at: datetime | None = None,
) -> DemonstrationCompletionReceipt:
    action = request.action
    if not isinstance(action, TutorArtifactCompleteDemoAction):
        raise ArtifactOwnerActionInvalid(
            "demonstration completion requires the exact completion action"
        )
    presentation = artifact.presentation
    if not isinstance(presentation, TutorArtifactDemonstrationPresentationV2):
        raise ArtifactOwnerActionInvalid(
            "legacy demonstration presentation has no completion receipt protocol"
        )
    descriptor_hash = canonical_hash(presentation.model_dump(mode="json"))
    evidence = action.evidence
    _validate_completion_evidence(presentation=presentation, evidence=evidence)
    request_hash = canonical_hash(
        {
            "artifact_id": artifact.id,
            "artifact_version": artifact.version,
            "descriptor_hash": descriptor_hash,
            "client_action_id": request.client_action_id,
            "evidence": evidence.model_dump(mode="json"),
        }
    )
    existing = conn.execute(
        """
        SELECT id::text AS id, completion_kind, descriptor_hash, request_hash
        FROM tutor_demonstration_completion_receipts
        WHERE artifact_id = %s
        FOR UPDATE
        """,
        (artifact.id,),
    ).fetchone()
    if existing is not None:
        if str(existing["request_hash"]) != request_hash:
            raise ArtifactOwnerVersionConflict(
                "demonstration completion already owns a different immutable receipt"
            )
        return DemonstrationCompletionReceipt(
            receipt_id=str(existing["id"]),
            completion_kind=str(existing["completion_kind"]),
            descriptor_hash=str(existing["descriptor_hash"]),
            replayed=True,
        )

    now = _utc(occurred_at or datetime.now(UTC))
    receipt_id = str(uuid5(_DEMO_RECEIPT_NAMESPACE, artifact.id))
    completion_kind = evidence.kind
    event_key: str | None = None
    event_payload_hash: str | None = None
    source_nonce: str
    source_generation: int | None = None
    source_sequence: int | None = None
    visible_elapsed_ms: int | None = None
    required_visible_ms: int | None = None
    if isinstance(evidence, TutorArtifactDemoInteractionEvidenceV1):
        event_key = evidence.event_key
        event_payload_hash = evidence.payload_hash
        source_nonce = evidence.preview_nonce
        source_generation = evidence.preview_generation
        source_sequence = evidence.preview_sequence
    else:
        source_nonce = evidence.clock_session_id
        visible_elapsed_ms = evidence.visible_elapsed_ms
        required_visible_ms = int(presentation.total_duration_seconds or 0) * 1_000
    try:
        conn.execute(
            """
            INSERT INTO tutor_demonstration_completion_receipts (
              id, artifact_id, user_id, conversation_id, learning_track_id,
              teaching_session_id, checkpoint_id, artifact_version,
              descriptor_hash, completion_kind, event_key, event_payload_hash,
              source_nonce, source_generation, source_sequence,
              visible_elapsed_ms, required_visible_ms,
              idempotency_key, request_hash, completed_at
            ) VALUES (
              %s, %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s,
              %s, %s, %s
            )
            """,
            (
                receipt_id,
                artifact.id,
                request.user_id,
                artifact.conversation_id,
                request.learning_track_id,
                request.teaching_session_id,
                artifact.checkpoint_id,
                artifact.version,
                descriptor_hash,
                completion_kind,
                event_key,
                event_payload_hash,
                source_nonce,
                source_generation,
                source_sequence,
                visible_elapsed_ms,
                required_visible_ms,
                request.client_action_id,
                request_hash,
                now,
            ),
        )
    except (CheckViolation, ForeignKeyViolation) as exc:
        raise ArtifactOwnerVersionConflict(
            "demonstration completion authority is stale or mismatched"
        ) from exc
    except UniqueViolation as exc:
        raise ArtifactOwnerVersionConflict(
            "demonstration completion conflicts with durable evidence"
        ) from exc
    return DemonstrationCompletionReceipt(
        receipt_id=receipt_id,
        completion_kind=completion_kind,
        descriptor_hash=descriptor_hash,
    )


def _materialize_step(
    step: LearningItemDemoStepV2,
    *,
    static: bool,
) -> tuple[TutorArtifactDemonstrationStepV2, ...]:
    chunks = _split_source(step.source_code)
    if not static and len(chunks) != 1:
        raise ArtifactOwnerActionInvalid(
            "interactive demonstration source must fit one isolated Preview step"
        )
    durations = _step_durations(step=step, chunks=chunks) if static else (None,)
    count = len(chunks)
    return tuple(
        TutorArtifactDemonstrationStepV2(
            step_key=(step.step_key if count == 1 else f"{step.step_key}.part-{index + 1}"),
            title=(step.title if count == 1 else f"{step.title} · {index + 1}/{count}"),
            instruction_markdown=step.instruction_markdown,
            source_content=chunk,
            source_content_hash=sha256_text(chunk),
            duration_seconds=durations[index],
        )
        for index, chunk in enumerate(chunks)
    )


def _split_source(source: str) -> tuple[str, ...]:
    if len(source) <= _MAX_PRESENTATION_STEP_CHARS:
        return (source,)
    chunks: list[str] = []
    current = ""
    for line in source.splitlines(keepends=True):
        pending = line
        while len(pending) > _MAX_PRESENTATION_STEP_CHARS:
            room = _MAX_PRESENTATION_STEP_CHARS - len(current)
            if room > 0:
                current += pending[:room]
                pending = pending[room:]
            chunks.append(current)
            current = ""
        if current and len(current) + len(pending) > _MAX_PRESENTATION_STEP_CHARS:
            chunks.append(current)
            current = ""
        current += pending
    if current:
        chunks.append(current)
    return tuple(item.rstrip("\n") or "\n" for item in chunks)


def _step_durations(
    *,
    step: LearningItemDemoStepV2,
    chunks: Sequence[str],
) -> tuple[int, ...]:
    if step.duration_seconds is None:
        return tuple(
            calculate_static_demonstration_duration_seconds(
                source_content=chunk,
                instruction_markdown=step.instruction_markdown,
            )
            for chunk in chunks
        )
    minimum_total = 6 * len(chunks)
    total = max(step.duration_seconds, minimum_total)
    base, remainder = divmod(total, len(chunks))
    return tuple(base + (1 if index < remainder else 0) for index in range(len(chunks)))


def _validate_completion_evidence(
    *,
    presentation: TutorArtifactDemonstrationPresentationV2,
    evidence: TutorArtifactDemoInteractionEvidenceV1 | TutorArtifactDemoVisibleClockEvidenceV1,
) -> None:
    if isinstance(evidence, TutorArtifactDemoInteractionEvidenceV1):
        expected = presentation.expected_event
        if (
            presentation.demonstration_mode != "interactive"
            or expected is None
            or evidence.event_key != expected.event_key
            or evidence.payload_hash != expected.payload_hash
            or evidence.payload_json != expected.payload_json
        ):
            raise ArtifactOwnerActionInvalid(
                "demonstration interaction event does not exactly match the descriptor"
            )
        return
    required_ms = int(presentation.total_duration_seconds or 0) * 1_000
    if (
        presentation.demonstration_mode != "static"
        or required_ms < 6_000
        or evidence.visible_elapsed_ms < required_ms
        or evidence.visible_elapsed_ms > min(required_ms + 2_000, 240_000)
    ):
        raise ArtifactOwnerActionInvalid(
            "demonstration visible clock has not satisfied the descriptor"
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = (
    "DemonstrationCompletionReceipt",
    "build_demonstration_presentation",
    "calculate_static_demonstration_duration_seconds",
    "complete_demonstration",
)