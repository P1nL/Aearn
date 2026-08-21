"""Adapter from Aearn Runtime DTOs to Tutor durable projection DTOs."""
from __future__ import annotations

from datetime import datetime

from app.services.tutor.runtime_projection import (
    PostgresTutorRuntimeProjectionRepository,
    TutorRuntimeProjectionEvent,
    TutorRuntimeProjectionFence,
    TutorRuntimeProjectionReceipt,
)

from .contracts import RuntimeEvent, RuntimeTurnResult


class TutorRuntimeEventProjector:
    def __init__(
        self,
        repository: PostgresTutorRuntimeProjectionRepository,
        *,
        binding_id: str,
        fence: TutorRuntimeProjectionFence,
    ) -> None:
        self._repository = repository
        self._binding_id = binding_id
        self._fence = fence

    def project_event(
        self,
        event: RuntimeEvent,
        *,
        sequence: int,
        occurred_at: datetime,
        defer_public_message: bool = False,
    ) -> TutorRuntimeProjectionReceipt:
        return self._repository.project(
            binding_id=self._binding_id,
            fence=self._fence,
            event=TutorRuntimeProjectionEvent(
                kind=event.kind.value,
                thread_id=event.thread_id,
                sequence=sequence,
                occurred_at=occurred_at,
                turn_id=event.turn_id,
                item_id=event.item_id,
                visible_text=event.visible_text,
                content_hash=event.content_sha256,
                safe_code=event.safe_code,
                terminal_status=(
                    event.terminal_status.value if event.terminal_status is not None else None
                ),
                tool_name=event.tool_name,
                input_hash=event.input_sha256,
                result_hash=event.result_sha256,
                item_type=event.item_type,
                phase=event.phase,
                defer_public_message=defer_public_message,
            ),
        )

    def project_result(
        self,
        result: RuntimeTurnResult,
        *,
        occurred_at: datetime,
    ) -> tuple[TutorRuntimeProjectionReceipt, ...]:
        if result.thread.generation != self._fence.connection_generation:
            raise ValueError("runtime result connection generation is stale")
        return tuple(
            self.project_event(
                event,
                sequence=event.sequence or index,
                occurred_at=occurred_at,
            )
            for index, event in enumerate(result.events, start=1)
        )
