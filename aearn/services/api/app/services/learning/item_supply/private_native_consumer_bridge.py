"""PRIVATE original Artifact/action issuer; creation and ongoing actions are distinct.

Historical quality is DATA. Each ongoing action needs a newly issued same-TX
receipt, actual binding/CAS/current mapping/source. Cancel cannot grant consume.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.services.learning.artifacts.contracts import TutorPublicArtifactItem
from app.services.learning.item_supply.private_enhancement_contracts import (
    IssuedPrivateConsumerAuthority, PrivateNativePending, PrivateResolvedContent,
)
from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner


class PrivateNativeArtifactConsumerOwner:
    def __init__(self,type_owner:PrivateNativeTypeEvidenceOwner,*,enabled:bool=False,exposure_owner:Any=None)->None:
        if type(type_owner) is not PrivateNativeTypeEvidenceOwner:
            raise PrivateNativePending('private_consumer_original_type_owner_required')
        self.type_owner,self.conn,self.settings,self.enabled=type_owner,type_owner.conn,type_owner.settings,enabled
        self._issued: dict[UUID,tuple[IssuedPrivateConsumerAuthority,int,dict[str,Any]]]={}
        self.successors = None
        if exposure_owner is not None:
            from app.services.learning.item_supply.private_native_successors import PrivateNativeSuccessorOwner
            self.successors = PrivateNativeSuccessorOwner(self,exposure_owner)

    def _guard(self)->tuple[Any,int]:
        if (not self.enabled or not self.settings.tutor_learning_artifacts_enabled
                or not self.settings.tutor_artifact_teaching_mode_enabled):
            raise PrivateNativePending('private_consumer_disabled')
        return self.type_owner._guard()

    def is_bound(self,artifact:TutorPublicArtifactItem)->bool:
        self._guard()
        row=self.conn.execute('SELECT 1 FROM tutor_item_supply_private_native_artifact_bindings '
            'WHERE artifact_id=%s AND user_id=%s AND epoch=%s',
            (artifact.id,self.type_owner.user_id,self.type_owner.epoch)).fetchone()
        return row is not None

    def _content(self,binding:dict[str,Any],artifact:TutorPublicArtifactItem)->PrivateResolvedContent:
        content=self.type_owner.query.resolve_content(UUID(artifact.owner_id))
        quality=content.quality
        mapping=self.type_owner.resolve_mapping(quality.ref.mapping_receipt_id)
        candidate=self.type_owner._candidate(content,mapping)
        request=binding['creation']['request']
        if (quality.ref.pack_task_id!=UUID(str(binding['pack_task_id']))
                or candidate.member.slot!=('remediation' if request['purpose']=='remediation' else 'practice')
                or request['purpose'] not in {'knowledge_check','remediation','transfer_check'} or candidate.candidate.visibility!='private'
                or (request['user_id'],request['learning_track_id'],request['knowledge_key'])
                !=(str(mapping.frozen_node.user_id),str(mapping.frozen_node.track_id),mapping.frozen_node.knowledge_key)
                or artifact.owner_id!=str(content.publication.version_id)
                or content.publication.item_handle!='lip:v2:'+artifact.owner_id):
            raise PrivateNativePending('private_consumer_exact_frozen_goal_content_required')
        return content

    def prepare(self,*,artifact:TutorPublicArtifactItem,action:str)->IssuedPrivateConsumerAuthority:
        self._guard()
        if action not in {'request_hint','request_direct_answer','respond','cancel'}:
            raise PrivateNativePending('private_consumer_action_not_authorized')
        row=self.conn.execute('SELECT b.*,r.payload_json AS creation FROM tutor_item_supply_private_native_artifact_bindings b '
            'JOIN tutor_item_supply_private_native_consumer_receipts r ON r.id=b.creation_receipt_id '
            'WHERE b.artifact_id=%s AND b.user_id=%s AND b.epoch=%s',
            (artifact.id,self.type_owner.user_id,self.type_owner.epoch)).fetchone()
        if row is None or artifact.owner_id!=str(row['version_id']) or artifact.artifact_kind.value!='knowledge_check':
            raise PrivateNativePending('private_consumer_original_artifact_binding_required')
        binding=dict(row)
        content=None if action=='cancel' else self._content(binding,artifact)
        now,txid=self._guard()
        rid=uuid4()
        mode='cancel' if action=='cancel' else 'current'
        deadline=now+timedelta(seconds=30)
        if content is not None:
            if content.valid_until is None:
                raise PrivateNativePending('private_consumer_current_content_required')
            deadline=min(deadline,content.valid_until)
        payload={'schema_version':'private_native_action_v1','creation_receipt_id':str(binding['creation_receipt_id']),
            'artifact_id':artifact.id,'artifact_version':artifact.version,'action':action}
        self.conn.execute('INSERT INTO tutor_item_supply_private_native_consumer_receipts '
            '(id,user_id,epoch,scope_id,pack_task_id,mode,action,artifact_id,artifact_version,version_id,payload_json,checked_at,valid_until,txid) '
            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (rid,self.type_owner.user_id,self.type_owner.epoch,binding['scope_id'],binding['pack_task_id'],mode,action,
             artifact.id,artifact.version,binding['version_id'],Jsonb(payload),now,deadline,txid))
        cap=IssuedPrivateConsumerAuthority(self,rid,artifact.id,artifact.version,UUID(artifact.owner_id),mode,action)
        self._issued[rid]=(cap,txid,binding)
        self.require(cap,conn=self.conn,artifact=artifact,expected_mode=mode,expected_action=action)
        return cap

    def require(self,authority:IssuedPrivateConsumerAuthority,*,conn:Connection[dict[str,Any]],
                artifact:TutorPublicArtifactItem,expected_mode:str,expected_action:str)->PrivateResolvedContent | None:
        now,txid=self._guard()
        if type(authority) is not IssuedPrivateConsumerAuthority:
            raise PrivateNativePending('private_consumer_issued_action_required')
        saved=self._issued.get(authority.receipt_id)
        if (conn is not self.conn or authority.owner is not self or saved is None or saved[0] is not authority or saved[1]!=txid
                or expected_mode not in {'current','cancel'} or authority.mode!=expected_mode or authority.action!=expected_action
                or (expected_mode=='cancel')!=(expected_action=='cancel')
                or expected_action not in {'request_hint','request_direct_answer','respond','cancel'}
                or (authority.artifact_id,authority.artifact_version,str(authority.version_id))!=(artifact.id,artifact.version,artifact.owner_id)):
            raise PrivateNativePending('private_consumer_exact_mode_action_CAS_required')
        content=None if expected_mode=='cancel' else self._content(saved[2],artifact)
        current=self.conn.execute('SELECT item_supply_internal.private_native_consumer_current(%s) AS ok',
            (authority.receipt_id,)).fetchone()
        if current is None or current['ok'] is not True:
            raise PrivateNativePending('private_consumer_current_original_receiver_required')
        # Original source/bank locks can wait. Recheck NEW clock/flags/receipt CAS
        # after those waits. No30sec creation snapshot is restored for later actions.
        self._guard()
        return content


def require_private_consumer_authority(authority:IssuedPrivateConsumerAuthority,*,
        conn:Connection[dict[str,Any]],artifact:TutorPublicArtifactItem,
        expected_mode:str,expected_action:str)->PrivateResolvedContent | None:
    if type(authority) is not IssuedPrivateConsumerAuthority or type(authority.owner) is not PrivateNativeArtifactConsumerOwner:
        raise PrivateNativePending('private_consumer_concrete_current_issuer_required')
    return authority.owner.require(authority,conn=conn,artifact=artifact,expected_mode=expected_mode,expected_action=expected_action)
