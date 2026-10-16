"""Current PRIVATE relation failure -> exact same-slot repair lineage, not fallback.

A negative lineage record revokes selection of that head until a genuine child
passes full admission. It never fabricates a six-peer finding or semantic child.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending


@dataclass(frozen=True)
class PrivateRelationRepairRef:
    request_id: UUID
    pack_task_id: UUID
    slot_id: UUID
    parent_version_id: UUID
    left_version_id: UUID
    right_version_id: UUID
    relation_receipt_id: UUID | None


class PrivateNativeRelationRepairOwner:
    def __init__(self, service: Any) -> None:
        from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
        if type(service) is not PrivateEnhancementService:
            raise PrivateNativePending('private_relation_repair_concrete_service_required')
        self.service,self.conn=service,service.conn

    def request(self, task: PersistentPackTaskRef, *, parent_version_id: UUID,
                left_version_id: UUID, right_version_id: UUID,
                relation_receipt_id: UUID | None = None) -> PrivateRelationRepairRef:
        self.service._guard()
        record=self.service.core._task(task)
        parent=self.service.type_owner.query.resolve_content(parent_version_id)
        ref=parent.quality.ref
        if ref.pack_task_id!=task.pack_task_id or ref.slot!='assessment' or ref.slot_id not in {s.slot_id for s in record.slots}:
            raise PrivateNativePending('private_relation_repair_same_original_assessment_slot_required')
        existing=self.conn.execute("SELECT id,payload_json FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=%s AND epoch=%s AND pack_task_id=%s AND record_kind='private_status' AND payload_json->>'schema_version'='private_native_relation_repair_required_v1' AND payload_json->>'parent_version_id'=%s ORDER BY created_at DESC,id DESC LIMIT 1",
            (task.user_id,task.epoch,task.pack_task_id,str(parent_version_id))).fetchone()
        if existing is not None:
            p=existing['payload_json']
            self._current(UUID(str(existing['id'])))
            return PrivateRelationRepairRef(UUID(str(existing['id'])),task.pack_task_id,ref.slot_id,parent_version_id,
                UUID(p['left_version_id']),UUID(p['right_version_id']),None if p['relation_receipt_id'] is None else UUID(p['relation_receipt_id']))
        rid=uuid4()
        payload={'schema_version':'private_native_relation_repair_required_v1','ref':ref.model_dump(mode='json'),
            'parent_version_id':str(parent_version_id),'left_version_id':str(left_version_id),
            'right_version_id':str(right_version_id),'relation_receipt_id':None if relation_receipt_id is None else str(relation_receipt_id)}
        self.conn.execute('SELECT item_supply_internal.private_native_request_relation_repair(%s,%s)',(rid,Jsonb(payload)))
        self._current(rid)
        return PrivateRelationRepairRef(rid,task.pack_task_id,ref.slot_id,parent_version_id,left_version_id,right_version_id,relation_receipt_id)

    def _current(self, rid: UUID) -> None:
        self.service._guard()
        row=self.conn.execute('SELECT item_supply_internal.private_native_relation_repair_current(%s) AS ok',(rid,)).fetchone()
        if row is None or row['ok'] is not True:
            raise PrivateNativePending('private_relation_repair_current_exact_failure_lineage_required')

    def pending(self, task: PersistentPackTaskRef) -> PrivateRelationRepairRef | None:
        self.service._guard()
        self.service.core._task(task)
        row=self.conn.execute("SELECT repair.id,repair.payload_json FROM tutor_item_supply_private_persistent_pack_journal repair JOIN LATERAL (SELECT version_id FROM tutor_item_supply_private_native_publications WHERE user_id=repair.user_id AND epoch=repair.epoch AND pack_task_id=repair.pack_task_id AND slot_id=(repair.payload_json->'ref'->>'slot_id')::uuid AND state='published' ORDER BY created_at DESC,id DESC LIMIT 1) head ON head.version_id::text=repair.payload_json->>'parent_version_id' WHERE repair.user_id=%s AND repair.epoch=%s AND repair.pack_task_id=%s AND repair.record_kind='private_status' AND repair.payload_json->>'schema_version'='private_native_relation_repair_required_v1' ORDER BY repair.created_at,repair.id LIMIT 1",
            (task.user_id,task.epoch,task.pack_task_id)).fetchone()
        if row is None:
            return None
        self._current(UUID(str(row['id'])))
        p=row['payload_json']
        return PrivateRelationRepairRef(UUID(str(row['id'])),task.pack_task_id,UUID(p['ref']['slot_id']),UUID(p['parent_version_id']),
            UUID(p['left_version_id']),UUID(p['right_version_id']),None if p['relation_receipt_id'] is None else UUID(p['relation_receipt_id']))
