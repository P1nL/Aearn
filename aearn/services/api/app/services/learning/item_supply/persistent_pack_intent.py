"""Append-only PRIVATE enhancement intent DATA, not quality/phase authority."""
from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRecord, PersistentPackTaskRef
from app.services.learning.item_supply.storage_contracts import StorageContract


class PersistentEnhancementIntentV1(StorageContract):
    schema_version: Literal["private_enhancement_intent_v1"] = "private_enhancement_intent_v1"
    pack_task_id: UUID
    user_id: UUID
    epoch: int = Field(ge=1)
    scope_id: UUID
    public_task_id: UUID
    previous_enhancement: Literal["base_only"] = "base_only"
    enhancement: Literal["prefer_private"] = "prefer_private"


def effective_enhancement(owner: Any, record: PersistentPackTaskRecord) -> PersistentPackTaskRecord:
    # Called ONLY after _task validates original header, namespace and current mapping.
    if record.enhancement!="base_only":
        return record
    ref=record.ref
    rows=owner.conn.execute("SELECT payload_json FROM tutor_item_supply_private_persistent_pack_journal "
        "WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND record_kind='private_status' "
        "AND payload_json->>'schema_version'='private_enhancement_intent_v1' ORDER BY created_at,id FOR SHARE",
        (ref.pack_task_id,ref.user_id,ref.epoch,ref.scope_id)).fetchall()
    if not rows:
        return record
    expected=PersistentEnhancementIntentV1(pack_task_id=ref.pack_task_id,user_id=ref.user_id,epoch=ref.epoch,
        scope_id=ref.scope_id,public_task_id=ref.public_task_id)
    for row in rows:
        if PersistentEnhancementIntentV1.model_validate_json(json.dumps(row["payload_json"]))!=expected:
            raise ValueError("exact append-only PRIVATE task intent required")
    return record.model_copy(update={"enhancement":"prefer_private"})


def attach_enhancement_intent(owner: Any, task: PersistentPackTaskRef) -> PersistentPackTaskRecord:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    if type(owner) is not PersistentPackTaskOwner:
        raise ValueError("original persistent owner required")
    record=owner._task(task)
    if record.enhancement=="prefer_private":
        return record
    intent=PersistentEnhancementIntentV1(pack_task_id=task.pack_task_id,user_id=task.user_id,epoch=task.epoch,
        scope_id=task.scope_id,public_task_id=task.public_task_id)
    # SQL526 (A-owned) must close this NEW schema. SQL523 stays immutable and denies it until installed.
    owner._private_event(task,"private_status",intent.model_dump(mode="json"),
        key="enhancement.intent."+task.pack_task_id.hex+".prefer_private")
    return effective_enhancement(owner,record)

