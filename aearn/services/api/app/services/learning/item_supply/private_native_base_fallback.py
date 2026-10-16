"""Fresh whole PUBLIC base under complete PUBLIC+PRIVATE protection.

Separate concrete issuer: never calls a public candidate PRIVATE or revives a
creation snapshot. This does not terminate the persistent PRIVATE business work.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.native_exposure_contracts import CURRENT_PACK_TTL
from app.services.learning.item_supply.type_evidence import ContentRelationshipEvidenceV2

from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner, _CurrentPackData
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import PackInputsV2, PackSnapshotV2
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.persistent_pack_current_source import VERSIONS, source_origin_payload

@dataclass(frozen=True)
class IssuedPrivateBaseFallback:
    owner: Any
    receipt_id: UUID
    public_capability: IssuedNativePackCapability
    snapshot: PackSnapshotV2
    task_ref: PersistentPackTaskRef
    inputs: PackInputsV2
    exposure_snapshot_id: UUID


@dataclass(frozen=True)
class _SameScopeUnion:
    scope: _CurrentPackData
    cap: IssuedPrivateBaseFallback
    inputs: PackInputsV2
    snapshot: PackSnapshotV2
    public_inputs: PackInputsV2
    mapping: Any
    graph: tuple[Any, ...]
    contents: tuple[tuple[UUID, Any], ...]
    versions: tuple[UUID, ...]
    public_relations: tuple[UUID, ...]
    private_relations: tuple[UUID, ...]
    payload: dict[str, Any]
    seal: str


class PrivateNativeBaseFallbackOwner:
    def __init__(self, service: Any) -> None:
        from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
        if type(service) is not PrivateEnhancementService:
            raise PrivateNativePending('private_fallback_original_concrete_service_required')
        self.service,self.conn,self.settings=service,service.conn,service.settings
        self._issued: dict[UUID,tuple[IssuedPrivateBaseFallback,int]]={}
        self._recent_scope: _CurrentPackData | None = None
        self._scope_union: _SameScopeUnion | None = None

    def _scope_graph(self, scoped: _CurrentPackData) -> tuple[Any, ...]:
        public=self.service.base_service.type_owner
        return (self.service,self.conn,self.settings,self.service.conn,self.service.settings,self.service.core,
            self.service.base_service,public,self.service.base_service.exposure_owner,self.service.type_owner,
            self.service.exposure_owner,getattr(self.service.type_owner,'query',None),
            getattr(public,'mapping_owner',None),getattr(public,'source_authority',None),
            scoped.source_binding,scoped.observation,scoped.capability)

    @staticmethod
    def _union_seal(cap: IssuedPrivateBaseFallback, base: PackInputsV2, payload: dict[str, Any],
                    scoped: _CurrentPackData, versions: tuple[UUID, ...],
                    public_relations: tuple[UUID, ...], private_relations: tuple[UUID, ...]) -> str:
        # The real issuance payload and decoded DATA, not a cached require result.
        return canonical_hash(dict(payload=payload,receipt_id=str(cap.receipt_id),
            exposure_snapshot_id=str(cap.exposure_snapshot_id),public_eligibility_id=str(cap.public_capability.eligibility_id),
            task=cap.task_ref.model_dump(mode='json'),inputs=cap.inputs.model_dump(mode='json'),
            snapshot=cap.snapshot.model_dump(mode='json'),public_inputs=base.model_dump(mode='json'),
            public_snapshot=cap.public_capability.snapshot.model_dump(mode='json'),
            locators=[[str(value) for value in values] for values in (versions,public_relations,private_relations)],
            public_scope=dict(txid=scoped.txid,mapping_receipt_id=str(scoped.mapping_id),
                versions=[str(v) for v in scoped.versions],relations=[str(r) for r in scoped.relation_ids],
                exposure_snapshot_id=str(scoped.observation.snapshot_id) if scoped.observation is not None else None)))

    def _reuse_union(self, scoped: _CurrentPackData, task: PersistentPackTaskRef, base: PackInputsV2,
                     mapping: Any, ids: tuple[UUID, ...], relations: tuple[UUID, ...],
                     private_ids: tuple[UUID, ...]) -> IssuedPrivateBaseFallback:
        cached=self._scope_union
        if type(cached) is not _SameScopeUnion or cached.scope is not scoped:
            raise PrivateNativePending('private_fallback_same_scope_union_data_required')
        cap=cached.cap
        if type(cap) is not IssuedPrivateBaseFallback:
            raise PrivateNativePending('private_fallback_same_scope_union_data_required')
        graph=self._scope_graph(scoped)
        saved=self._issued.get(cap.receipt_id)
        if (cap.owner is not self or type(saved) is not tuple or len(saved)!=2
                or saved[0] is not cap or saved[1]!=scoped.txid or cap.task_ref!=task
                or cap.public_capability is not scoped.capability or cap.inputs is not cached.inputs
                or cap.snapshot is not cached.snapshot or base is not cached.public_inputs or mapping is not cached.mapping
                or ids!=cached.versions or relations!=cached.public_relations or private_ids!=cached.private_relations
                or len(graph)!=len(cached.graph) or any(actual is not original for actual,original in zip(graph,cached.graph,strict=True))
                or any((scoped.contents if version in ids else scoped.historical).get(version) is not content
                    for version,content in cached.contents)
                or self._union_seal(cap,base,cached.payload,scoped,ids,relations,private_ids)!=cached.seal):
            raise PrivateNativePending('private_fallback_same_scope_union_data_required')
        # Always reacquire PUBLIC and SQL549/PRIVATE/source/epoch/final-clock
        # permission. A denial MUST propagate; never rebuild/restamp this scope.
        self.require(cap)
        return cap

    def resolve(self, task: PersistentPackTaskRef) -> IssuedPrivateBaseFallback:
        self.service._guard()
        record=self.service.core._task(task)
        if record.enhancement!='prefer_private':
            raise PrivateNativePending('private_fallback_original_task_intent_required')
        selected: tuple[UUID | None,...]
        retained=self.service.base_service._reservation(task.demand_id)
        if retained is not None:
            refs=retained['request_json']
            if refs['mapping_receipt_id']!=str(task.mapping_receipt_id):
                raise PrivateNativePending('private_fallback_retained_original_mapping_required')
            selected=tuple(UUID(v) for v in refs['candidate_version_ids'])
        else:
            versions=self.service.core._versions(task)
            selected=tuple(v.published_version_id for v in versions.values())
        if len(selected)!=5 or any(v is None for v in selected):
            raise PrivateNativePending('private_fallback_retained_exact_whole_base_required')
        ids=tuple(v for v in selected if v is not None)
        public=self.service.base_service.type_owner
        raw_scope=getattr(public,'_pack_scope',None)
        if raw_scope is not None and (type(public) is not NativeTypeEvidenceOwner or type(raw_scope) is not _CurrentPackData):
            raise PrivateNativePending('private_fallback_exact_live_public_scope_required')
        scoped=NativeTypeEvidenceOwner._current_pack_data(public)
        if scoped is not None and scoped is self._recent_scope:
            cached=self._scope_union
            # A damaged same-scope binding must fail BEFORE resolve_pack could
            # see a missing capability and issue a replacement PUBLIC snapshot.
            if (type(cached) is not _SameScopeUnion or cached.scope is not scoped
                    or type(cached.cap) is not IssuedPrivateBaseFallback
                    or scoped.capability is not cached.cap.public_capability
                    or scoped.inputs is not cached.public_inputs or scoped.mapping is not cached.mapping
                    or scoped.observation is None):
                raise PrivateNativePending('private_fallback_same_scope_union_data_required')
        elif scoped is not self._recent_scope:
            self._recent_scope=None
            self._scope_union=None
        observation=self.service.base_service.exposure_owner.snapshot_v2()
        if observation.snapshot_id is None:
            raise PrivateNativePending('private_fallback_original_complete_public_exposure_required')
        rows=self.conn.execute('SELECT id FROM tutor_item_supply_native_relation_batches WHERE user_id=%s AND epoch=%s AND mapping_receipt_id=%s AND valid_until>clock_timestamp() ORDER BY checked_at DESC,id LIMIT 16',
            (task.user_id,task.epoch,task.mapping_receipt_id)).fetchall()
        relations=tuple(UUID(str(r['id'])) for r in rows)
        public_cap=public.resolve_pack(task.mapping_receipt_id,ids,observation.snapshot_id,relations)
        if scoped is not None:
            # resolve_pack already performed the original full dynamic require.
            # Reuse only its exact same-TOP immutable DATA, never its permission.
            _,public_txid=public._guard()
            if (NativeTypeEvidenceOwner._current_pack_data(public) is not scoped
                    or public.conn is not self.conn or public.settings is not self.settings
                    or (public.user_id,public.epoch)!=(task.user_id,task.epoch)
                    or scoped.txid!=public_txid or scoped.capability is not public_cap
                    or (scoped.source_binding is not None and
                        (scoped.source_binding.owner is not self.service.core or scoped.source_binding.task!=task))
                    or scoped.exposure_owner is not self.service.base_service.exposure_owner
                    or scoped.observation is not observation or scoped.mapping_id!=task.mapping_receipt_id
                    or scoped.versions!=tuple(sorted(ids,key=str))
                    or scoped.relation_ids!=tuple(sorted(relations,key=str))
                    or scoped.inputs is None or scoped.mapping is None
                    or scoped.mapping.receipt_id!=task.mapping_receipt_id
                    or scoped.inputs.request!=scoped.mapping.pack_request
                    or (scoped.inputs.request.learner_id,scoped.inputs.request.epoch)!=(task.user_id,task.epoch)
                    or scoped.inputs.exposure!=observation.exposure
                    or set(scoped.contents)!=set(ids)
                    or len(scoped.inputs.candidates)!=len(ids)
                    or {c.version_id for c in scoped.inputs.candidates}!=set(ids)):
                raise PrivateNativePending('private_fallback_exact_live_public_scope_required')
            base,mapping=scoped.inputs,scoped.mapping
            contents=dict(scoped.contents)
            for candidate in base.candidates:
                content=contents[candidate.version_id]
                proof=content.publication
                if (candidate.type_evidence is None or candidate.type_evidence.content!=content.content
                        or content.content.version_id!=candidate.version_id or proof.version_id!=candidate.version_id
                        or proof.proof_id!=candidate.proof_id or proof.publication_event_id!=candidate.publication_id
                        or proof.materialization_id!=candidate.materialization_id):
                    raise PrivateNativePending('private_fallback_exact_live_public_scope_required')
        else:
            if NativeTypeEvidenceOwner._current_pack_data(public) is not None:
                raise PrivateNativePending('private_fallback_exact_live_public_scope_required')
            public.require_pack(public_cap)
            base=public._inputs(task.mapping_receipt_id,ids,observation.snapshot_id,relations)
        # Keep the no-scope strict read order; a scope hit needs fresh PRIVATE
        # relation locators before it may reuse any prior decoded union DATA.
        union=self.service.exposure_owner.snapshot_complete() if scoped is None else None
        private_rows=self.conn.execute("SELECT id FROM tutor_item_supply_private_native_quality_evidence WHERE user_id=%s AND epoch=%s AND pack_task_id=%s AND kind='relation' AND valid_until>clock_timestamp() ORDER BY checked_at DESC,id LIMIT 16",
            (task.user_id,task.epoch,task.pack_task_id)).fetchall()
        private_ids=tuple(UUID(str(r['id'])) for r in private_rows)
        if scoped is not None and scoped is self._recent_scope:
            return self._reuse_union(scoped,task,base,mapping,ids,relations,private_ids)
        if union is None:
            union=self.service.exposure_owner.snapshot_complete()
        if scoped is None:
            contents={v:public.resolve_content(v,current=True) for v in ids}
        history={content.version_id for relation in base.relationships for content in (relation.left,relation.right)
            if content.item_handle.startswith('li:') and content.version_id not in contents}
        history.update(event.content.version_id for event in union.exposure.records
            if event.content.item_handle.startswith('li:') and event.content.version_id not in contents)
        for version in sorted(history,key=str):
            if scoped is None:
                contents[version]=public.resolve_content(version,current=False)
            else:
                historical=scoped.historical.get(version)
                if (historical is None or historical.content.version_id!=version
                        or historical.publication.version_id!=version or not historical.content.item_handle.startswith('li:')):
                    raise PrivateNativePending('private_fallback_exact_live_public_scope_required')
                contents[version]=historical
        if scoped is None:
            mapping=public.resolve_mapping(task.mapping_receipt_id)
        projection_now,projection_txid=self.service.type_owner._guard()
        if scoped is not None and (NativeTypeEvidenceOwner._current_pack_data(public) is not scoped
                or scoped.txid!=projection_txid or scoped.capability is not public_cap
                or scoped.inputs is not base or scoped.mapping is not mapping
                or any(scoped.contents.get(v) is not contents[v] for v in ids)):
            raise PrivateNativePending('private_fallback_exact_live_public_scope_required')
        projected=public._relations(relations,mapping,contents,union.exposure,projection_now)
        extra: tuple[ContentRelationshipEvidenceV2,...]=()
        if private_ids:
            extra=self.service.type_owner._relations(private_ids,mapping,contents,union.exposure)
        inputs=PackInputsV2(request=base.request,candidates=base.candidates,exposure=union.exposure,
            relationships=tuple({r.binding_hash:r for r in (*projected,*extra)}.values()))
        now,txid=self.service.type_owner._guard()
        result=build_pack(inputs,now=now)
        if result.snapshot is None:
            raise PrivateNativePending('private_fallback_whole_current_union_or_relation_unavailable')
        snapshot=result.snapshot
        rid=uuid4()
        payload=dict(schema_version='private_native_base_union_v1',public_eligibility_id=str(public_cap.eligibility_id),
            exposure_snapshot_id=str(union.snapshot_id),snapshot=snapshot.model_dump(mode='json'),relations=[str(r) for r in private_ids],
            checked_at=now.isoformat(),valid_until=min(snapshot.valid_until,now+CURRENT_PACK_TTL).isoformat(),txid=txid)
        source_origin=source_origin_payload(public)
        if source_origin is not None:
            cap_source=getattr(public,'current_source_binding')
            if cap_source.task != task or set(ids) != set(VERSIONS.values()):
                raise PrivateNativePending('private_fallback_current_source_exact_task_required')
            payload={**payload,'schema_version':'private_native_base_union_current_source_v2',**source_origin}
        self.service.core._private_event(task,'private_status',payload,key='private.base.union.'+rid.hex)
        row=self.conn.execute("SELECT id FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=%s AND operation_key=%s AND record_kind='private_status'",(task.pack_task_id,'private.base.union.'+rid.hex)).fetchone()
        if row is None:
            raise PrivateNativePending('private_fallback_current_original_receipt_required')
        cap=IssuedPrivateBaseFallback(self,UUID(str(row['id'])),public_cap,snapshot,task,inputs,union.snapshot_id)
        self._issued[cap.receipt_id]=(cap,txid)
        if scoped is not None:
            self._recent_scope=scoped
            self._scope_union=_SameScopeUnion(scoped,cap,inputs,snapshot,base,mapping,self._scope_graph(scoped),
                tuple(contents.items()),ids,relations,private_ids,payload,
                self._union_seal(cap,base,payload,scoped,ids,relations,private_ids))
        self.require(cap)
        return cap

    def require(self, cap: IssuedPrivateBaseFallback) -> PackSnapshotV2:
        _,txid=self.service.type_owner._guard()
        if type(cap) is not IssuedPrivateBaseFallback:
            raise PrivateNativePending('private_fallback_same_TX_concrete_issuer_required')
        saved=self._issued.get(cap.receipt_id)
        if (cap.owner is not self or type(saved) is not tuple or len(saved)!=2
                or saved[0] is not cap or saved[1]!=txid):
            raise PrivateNativePending('private_fallback_same_TX_concrete_issuer_required')
        self.service.base_service.type_owner.require_pack(cap.public_capability)
        row=self.conn.execute('SELECT item_supply_internal.private_native_base_union_current(%s) AS ok',(cap.receipt_id,)).fetchone()
        if row is None or row['ok'] is not True:
            raise PrivateNativePending('private_fallback_current_whole_union_receiver_required')
        return cap.snapshot
