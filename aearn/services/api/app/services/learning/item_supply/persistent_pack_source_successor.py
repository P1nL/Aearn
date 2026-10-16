"""One explicit PRIVATE source/mapping bridge, not a reissued investigation capability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.services.grounding.autonomous.confirmed_source_successor import PUBLIC_CLAIM, same_supported_source
from app.services.grounding.autonomous.source_assessment_profiles import SignedSourceAssessment
from app.services.grounding.public_course_contracts import PublicCourseEvidenceBindingV1
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, PublicMaterialV2
from app.services.learning.item_supply.persistent_pack_committed_revision import ARTIFACT, PHASE, PRIVATE, RECEIPT, ROOT, TASK
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRecord, PersistentPackTaskRef
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner

KIND = "source_mapping_successor"
KEY = "p7.source-mapping-successor." + TASK.hex + ".1"


@dataclass(frozen=True, repr=False)
class IssuedSourceMappingSuccessor:
    owner: PersistentPackTaskOwner
    record_id: UUID
    task: PersistentPackTaskRef
    public_materials: tuple[PublicMaterialV2, ...]
    course_materials: tuple[PublicMaterialV2, ...]
    source_deadlines: tuple[tuple[str, str, datetime], ...]
    valid_until: datetime
    payload: dict[str, Any]


def _history(core: PersistentPackTaskOwner, task: PersistentPackTaskRef) -> PersistentPackTaskRecord:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    if type(core) is not PersistentPackTaskOwner or type(task) is not PersistentPackTaskRef:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_ISSUER_REQUIRED")
    core._guard()
    if task.pack_task_id != TASK or (task.user_id,task.epoch)!=(core.user_id,core.epoch):
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_EXACT_TASK_REQUIRED")
    row = core.conn.execute("SELECT payload_json FROM "+PRIVATE+" WHERE id=%s AND pack_task_id=%s "
        "AND user_id=%s AND epoch=%s AND scope_id=%s AND record_kind='task' FOR SHARE",
        (TASK,TASK,task.user_id,task.epoch,task.scope_id)).fetchone()
    if row is None:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_EXACT_TASK_REQUIRED")
    record = PersistentPackTaskRecord.model_validate_json(json.dumps(row["payload_json"]))
    if record.ref != task:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_EXACT_TASK_REQUIRED")
    return record


def _current_with_mapping(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, public: tuple[PublicMaterialV2, ...],
                          course: tuple[PublicMaterialV2, ...]) -> tuple[
                              dict[str, Any], tuple[tuple[str, str, datetime], ...], datetime, FiniteCourseMappingReceiptV1]:
    """Return the mapping verified by this same fresh source fence; never retain it across calls."""
    _history(core,task)
    mapping_owner = core.type_owner.mapping_owner
    mapping = mapping_owner.resolve_source_successor(receipt_id=task.mapping_receipt_id,user_id=task.user_id,epoch=task.epoch,materials=course)
    receipts = mapping_owner.current_authority.receipts
    authority = core.type_owner.source_authority
    if authority.connection is not core.conn or receipts.conn is not core.conn:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_OWNER_REQUIRED")
    old_row = core.conn.execute("SELECT signed_proof FROM rag_assessment_source_evidence WHERE claim_handle=%s FOR SHARE",
        (PUBLIC_CLAIM,)).fetchone()
    parent = core.conn.execute("SELECT request_json,artifact_hash FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s AND root_id=%s FOR SHARE",
        (ARTIFACT,ROOT)).fetchone()
    if old_row is None or parent is None:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_HISTORY_REQUIRED")
    historical = SignedSourceAssessment.model_validate_json(json.dumps(old_row["signed_proof"])).payload.prepared
    old_request = GenerationRequestV2.model_validate_json(json.dumps(parent["request_json"]))
    if len(public) != len(old_request.materials):
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_EXACT_EXCERPTS_REQUIRED")
    deadlines = []
    bounds: list[datetime] = []
    new_public_ids = set()
    for old,raw in zip(old_request.materials,public,strict=True):
        material = checked_model(raw,PublicMaterialV2)
        if (type(material.binding) is not PublicCourseEvidenceBindingV1 or type(old.binding) is not PublicCourseEvidenceBindingV1
                or material.binding.target_id != old.binding.target_id or material.binding.course_goal_hash != old.binding.course_goal_hash
                or material.binding.target_definition_hash != old.binding.target_definition_hash
                or material.excerpt != old.excerpt or len(material.exact_claims)!=1):
            raise PipelineRepositoryError("SOURCE_SUCCESSOR_EXACT_EXCERPTS_REQUIRED")
        authority.authorize(material)
        current,_,_ = receipts._find(material.exact_claims[0].claim_receipt_id)
        if current.claim_handle == PUBLIC_CLAIM:
            raise PipelineRepositoryError("SOURCE_SUCCESSOR_NEW_PROOF_REQUIRED")
        same_supported_source(historical,current.prepared)
        coordinate = material.binding.evidence[0].binding
        reviews = authority._current.governance.source_reviews
        grant = None if reviews is None else reviews.resolve(coordinate.source_handle,coordinate.document_handle)
        if grant is None or grant.grant is None:
            raise PipelineRepositoryError("SOURCE_SUCCESSOR_CURRENT_GRANT_REQUIRED")
        deadlines.append((material.binding.binding_digest,material.exact_claims[0].claim_receipt_id,grant.grant.retained_until))
        bounds.extend((grant.grant.retained_until,current.expires_at))
        new_public_ids.add(current.evidence_id)
    if len(new_public_ids)!=1:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_UNIQUE_PUBLIC_PROOF_REQUIRED")
    for material in course:
        private,_,_ = receipts._find(material.exact_claims[0].claim_receipt_id)
        provenance = receipts.private_provenance(private.claim_handle)
        if provenance is None or provenance.public.evidence_id not in new_public_ids:
            raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_PRIVATE_PROVENANCE_REQUIRED")
        bounds.append(private.expires_at)
    until = min(bounds)
    if core._guard()>=until:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_CURRENT_GRANT_REQUIRED")
    return parent,tuple(deadlines),until,mapping


def _current(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, public: tuple[PublicMaterialV2, ...],
             course: tuple[PublicMaterialV2, ...]) -> tuple[dict[str, Any], tuple[tuple[str, str, datetime], ...], datetime]:
    parent, deadlines, until, _ = _current_with_mapping(core,task,public,course)
    return parent,deadlines,until


def prepare(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, public_materials: tuple[PublicMaterialV2, ...],
            course_materials: tuple[PublicMaterialV2, ...]) -> IssuedSourceMappingSuccessor:
    parent,deadlines,until = _current(core,task,public_materials,course_materials)
    prior = core.conn.execute("SELECT id,payload_json FROM "+PRIVATE+" WHERE pack_task_id=%s AND user_id=%s AND epoch=%s "
        "AND record_kind=%s AND operation_key=%s FOR SHARE",(TASK,task.user_id,task.epoch,KIND,KEY)).fetchone()
    if prior is not None:
        if (prior["payload_json"]["public_materials"] != [m.model_dump(mode="json") for m in public_materials]
                or prior["payload_json"]["course_materials"] != [m.model_dump(mode="json") for m in course_materials]):
            raise PipelineRepositoryError("SOURCE_SUCCESSOR_BINDING_CHANGED")
        return resolve(core,task,UUID(str(prior["id"])))
    payload = dict(schema_version="persistent_source_mapping_successor_v1",task_ref=task.model_dump(mode="json"),
        parent_artifact_id=str(ARTIFACT),parent_artifact_hash=parent["artifact_hash"],root_id=str(ROOT),historical_phase_id=str(PHASE),
        investigation_receipt_id=str(RECEIPT),historical_request_hash=canonical_hash(parent["request_json"]),
        public_materials=[m.model_dump(mode="json") for m in public_materials],course_materials=[m.model_dump(mode="json") for m in course_materials],
        source_deadlines=[dict(binding_digest=b,claim_receipt_id=c,retained_until=t.isoformat()) for b,c,t in deadlines],
        issued_at=core._guard().isoformat(),valid_until=until.isoformat())
    record_id = core._private_event(task,KIND,payload,key=KEY)
    cap = IssuedSourceMappingSuccessor(core,record_id,task,public_materials,course_materials,deadlines,until,payload)
    core._source_successors[record_id] = (cap,canonical_hash(payload))
    return cap


def resolve(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, record_id: UUID) -> IssuedSourceMappingSuccessor:
    """Fresh source-only issuance after current owners validate committed bridge DATA."""
    _history(core,task)
    row = core.conn.execute("SELECT payload_json FROM "+PRIVATE+" WHERE id=%s AND pack_task_id=%s AND user_id=%s AND epoch=%s "
        "AND record_kind=%s AND operation_key=%s FOR SHARE",(record_id,TASK,task.user_id,task.epoch,KIND,KEY)).fetchone()
    if row is None:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ACTUAL_RECORD_REQUIRED")
    payload = row["payload_json"]
    public = tuple(PublicMaterialV2.model_validate_json(json.dumps(m)) for m in payload["public_materials"])
    course = tuple(PublicMaterialV2.model_validate_json(json.dumps(m)) for m in payload["course_materials"])
    _,deadlines,until = _current(core,task,public,course)
    cap = IssuedSourceMappingSuccessor(core,record_id,task,public,course,deadlines,until,payload)
    core._source_successors[record_id] = (cap,canonical_hash(payload))
    try:
        require(cap,core,task)
    except BaseException:
        core._source_successors.pop(record_id,None)
        raise
    return cap


def compose(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, public_claim_id: str,
            course_claim_id: str) -> IssuedSourceMappingSuccessor:
    """Original material factories choose exact historical excerpts, never naked binding DTOs."""
    from app.services.grounding.assessment_material_factory import create_assessment_material
    from app.services.grounding.public_course_material_factory import create_public_course_material
    from app.services.grounding.material_contracts_v2 import EvidenceBindingV2
    _history(core,task)
    mapping = core.type_owner.mapping_owner
    receipts = mapping.current_authority.receipts
    authority = mapping.current_authority.authority
    provenance = receipts.private_provenance(course_claim_id)
    if provenance is None or provenance.public.claim_handle != public_claim_id:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_PRIVATE_PROVENANCE_REQUIRED")
    old = core.conn.execute("SELECT a.request_json,b.binding_json FROM tutor_item_supply_shared_generation_artifacts a "
        "JOIN tutor_item_supply_finite_course_mappings m ON m.id=%s JOIN rag_plan_material_bindings b ON b.id=m.assessment_binding_id "
        "WHERE a.id=%s AND a.root_id=%s",(task.mapping_receipt_id,ARTIFACT,ROOT)).fetchone()
    if old is None:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_HISTORY_REQUIRED")
    request = GenerationRequestV2.model_validate_json(json.dumps(old["request_json"]))
    binding = EvidenceBindingV2.model_validate_json(json.dumps(old["binding_json"]))

    def chunk(digest: str) -> str:
        rows = core.conn.execute("SELECT chunk_id FROM grounding_corpus_chunks WHERE corpus_version_id=%s "
            "AND document_id=%s AND chunk_hash=%s FOR SHARE",(provenance.corpus_id,provenance.public.prepared.document_handle,digest)).fetchall()
        if len(rows)!=1:
            raise PipelineRepositoryError("SOURCE_SUCCESSOR_EXACT_EXCERPTS_REQUIRED")
        return str(rows[0]["chunk_id"])

    public = tuple(create_public_course_material(core.conn,receipts=receipts,authority=authority,
        claim_receipt_id=public_claim_id,target_id="python-kc-binding-v1",chunk_id=chunk(hashlib.sha256(m.excerpt.encode()).hexdigest()),enabled=True)
        for m in request.materials)
    course = tuple(create_assessment_material(core.conn,receipts=receipts,authority=authority,
        claim_receipt_id=course_claim_id,draft=binding.draft,node_id=binding.node_id,goal_hash=binding.goal_hash,
        chunk_id=chunk(e.approved_excerpt_hash),enabled=True) for e in binding.evidence)
    return prepare(core,task,public_materials=public,course_materials=course)


def require(cap: IssuedSourceMappingSuccessor, core: PersistentPackTaskOwner, task: PersistentPackTaskRef) -> PersistentPackTaskRecord:
    if type(cap) is not IssuedSourceMappingSuccessor or cap.owner is not core or cap.task != task:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_ISSUER_REQUIRED")
    entry = core._source_successors.get(cap.record_id)
    if entry is None or entry[0] is not cap or entry[1] != canonical_hash(cap.payload):
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_ISSUER_REQUIRED")
    if (cap.payload["public_materials"] != [m.model_dump(mode="json") for m in cap.public_materials]
            or cap.payload["course_materials"] != [m.model_dump(mode="json") for m in cap.course_materials]
            or cap.payload["source_deadlines"] != [dict(binding_digest=b,claim_receipt_id=c,retained_until=t.isoformat()) for b,c,t in cap.source_deadlines]
            or datetime.fromisoformat(cap.payload["valid_until"]) != cap.valid_until):
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_BINDING_CHANGED")
    parent,deadlines,until = _current(core,task,cap.public_materials,cap.course_materials)
    if parent["artifact_hash"] != cap.payload["parent_artifact_hash"] or deadlines != cap.source_deadlines or until != cap.valid_until:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_BINDING_CHANGED")
    row = core.conn.execute("SELECT payload_json FROM "+PRIVATE+" WHERE id=%s AND pack_task_id=%s AND record_kind=%s AND operation_key=%s FOR SHARE",
        (cap.record_id,TASK,KIND,KEY)).fetchone()
    if row is None or row["payload_json"] != cap.payload:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ACTUAL_RECORD_REQUIRED")
    core.conn.execute("SELECT item_supply_internal.assert_source_mapping_successor(%s)",(Jsonb(cap.payload),))
    return _history(core,task)


def original(continuation: SharedCandidateContinuationOwner, cap: IssuedSourceMappingSuccessor) -> dict[str, Any]:
    require(cap,cap.owner,cap.task)
    if continuation.conn is not cap.owner.conn:
        raise PipelineRepositoryError("SOURCE_SUCCESSOR_ORIGINAL_ISSUER_REQUIRED")
    continuation._require(cap.owner.type_owner.source_authority)
    return continuation._original_row(ARTIFACT)  # Historical DATA; NEW proof was fenced above.
