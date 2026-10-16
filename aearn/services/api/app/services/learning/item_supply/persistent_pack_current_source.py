"""Original-owner whole-pack source permission, distinct from revision authority.

PRIVATE origin rows are current-transaction DATA. They cannot deserialize this
capability and do not authorize providers, eligibility, publication or delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from datetime import datetime
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.native_publication_contracts import NativePublicationProofV1
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2, SourceReceiptV2
from app.services.learning.item_supply.persistent_pack_contracts import SLOTS, PersistentPackTaskRef
from app.services.learning.item_supply.persistent_pack_current_source_materials import require_historical_material
from app.services.learning.item_supply.persistent_pack_source_successor import KIND as SUCCESSOR_KIND, _current, _current_with_mapping, _history
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

if TYPE_CHECKING:
    from psycopg import Connection
    from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority

TASK = UUID("6739d3c5-6619-44ce-970f-0ab1e49f3acc")
PUBLIC_TASK = UUID("9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c")
SOURCE_DATA = UUID("3fd36e85-711c-43c9-8350-46fdf4d57e72")
KIND = "current_pack_source_origin"
VERSIONS = {
    "practice-1": UUID("36b07034-c81a-530a-90ac-c7f62a92a8dd"),
    "practice-2": UUID("7a2898e0-c24e-5a33-9596-387a64dcdcaa"),
    "assessment-1": UUID("2d8325e7-5cb5-56f1-a004-ecec3abd60e5"),
    "assessment-2": UUID("8ba4ca51-e8f4-540a-b52a-eaec8a0a6764"),
    "guided-remediation": UUID("a2b435f4-2d4e-5048-a1cc-c482f4ffa5fe"),
}
PRIVATE = "tutor_item_supply_private_persistent_pack_journal"
SHARED = "tutor_item_supply_shared_persistent_pack_journal"


@dataclass(frozen=True, repr=False)
class IssuedCurrentPackSourceBinding:
    owner: PersistentPackTaskOwner
    binding_id: UUID
    task: PersistentPackTaskRef
    source_data_hash: str
    selection_hash: str
    source_authorization_hash: str
    source_deadline: datetime
    public_materials: tuple[PublicMaterialV2, ...]
    course_materials: tuple[PublicMaterialV2, ...]
    mapping: FiniteCourseMappingReceiptV1

    def current_scope(self) -> AbstractContextManager[None]:
        """Enter before core front/snapshot and retain the entire same-TOP handoff.

        The original owner must freshly issue/attach this cap, with its genuinely
        emitted current-TOP origin, as type_owner.current_source_binding first.
        A later TOP must issue/attach anew; this port never restores an origin.
        """
        return _current_scope(self)

    def current_pack_invocation(self, *, query: Any, source_authority: RagSourceAuthority,
                                proof_bindings: tuple[tuple[NativePublicationProofV1, datetime], ...]
                                ) -> AbstractContextManager[None]:
        """One original synchronous five-member require, never a handoff scope.

        Core may only run its bank SHARE/latest/health and relation waits inside;
        no callback, await, caller yield, DB write or capability issuance.
        Independent next requires repeat the complete initial/final fences.
        """
        return _current_pack_invocation(self, query=query, source_authority=source_authority,
            proof_bindings=proof_bindings)

    def require(self) -> FiniteCourseMappingReceiptV1:
        return require(self)

    def resolve_mapping(self, receipt_id: UUID) -> FiniteCourseMappingReceiptV1:
        with _source_use(self):
            if receipt_id != self.task.mapping_receipt_id:
                raise PipelineRepositoryError("CURRENT_PACK_SOURCE_MAPPING_MISMATCH")
            return require(self)

    def current_receipts(self, *, query: Any, proof: NativePublicationProofV1,
                         published_at: datetime | None = None, source_authority: RagSourceAuthority) -> tuple[SourceReceiptV2, ...]:
        with _source_use(self):
            if query is not self.owner.type_owner.query or source_authority is not self.owner.type_owner.source_authority:
                raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_QUERY_REQUIRED")
            if published_at is None:
                state = _CURRENT_SOURCE_SCOPE.get()
                if state is None or state.cap is not self or state.front is None:
                    raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_PUBLICATION_TIME_REQUIRED")
                entry = next((p for p in state.front[1] if p["version_id"] == str(proof.version_id)), None)
                fingerprint = canonical_hash(proof.model_dump(mode="json")) if state.invocation is not None else proof.proof_hash
                if entry is None or (entry["proof_id"],entry["proof_hash"]) != (str(proof.proof_id),fingerprint):
                    raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_PUBLICATION_REQUIRED")
                published_at = datetime.fromisoformat(entry["published_at"])
            receipts = self._receipts_for_proof(proof, published_at=published_at)
            state = _CURRENT_SOURCE_SCOPE.get()
            if state is not None and state.invocation is not None:
                _require_invocation_receipts(self, state.invocation, receipts)
                return receipts
            # Keep the original PUBLIC corpus/governance predicates. Its inner
            # source reads now share this invocation's initial/final SQL549 fence.
            for material, receipt in zip(self.public_materials, receipts, strict=True):
                source_authority.assert_current(material, receipt)
            return receipts

    def _receipts_for_proof(self, proof: NativePublicationProofV1, *,
                            published_at: datetime | None = None) -> tuple[SourceReceiptV2, ...]:
        # Original issuer rechecks CURRENT C/D/selection/history before returning
        # its current-transaction receipt DATA. No old receipt is relabelled.
        with _source_use(self):
            _, payload = origin(self)
            state = _CURRENT_SOURCE_SCOPE.get()
            if state is not None and state.invocation is not None and not any(
                    original is proof and (published_at is None or at == published_at)
                    for original,at in state.invocation.proof_bindings):
                raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_PUBLICATION_REQUIRED")
            fingerprint = canonical_hash(proof.model_dump(mode="json")) if state is not None and state.invocation is not None else proof.proof_hash
            entry = next((p for p in payload["selected"] if p["version_id"] == str(proof.version_id)), None)
            if (entry is None or entry["proof_id"] != str(proof.proof_id) or entry["proof_hash"] != fingerprint
                    or published_at is not None and datetime.fromisoformat(entry["published_at"]) != published_at):
                raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_PUBLICATION_REQUIRED")
            if state is not None and state.public_receipts is not None:
                return state.public_receipts
            return tuple(SourceReceiptV2.model_validate_json(json.dumps(r)) for r in payload["public_receipts"])

    def relation_binding_hash(self) -> str:
        """Pure registered identity fingerprint, NOT a fresh source/provider grant."""
        try:
            fingerprint = _seal(self)
            entry = self.owner._current_source_bindings.get(self.binding_id)
            if entry is None or entry[0] is not self or entry[1] != fingerprint:
                raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_ISSUER_REQUIRED")
            return fingerprint
        except BaseException:
            active = _CURRENT_SOURCE_SCOPE.get()
            if active is not None:
                _invalidate_current_scope(active.cap)
            raise

    def _relation_owner(self, owner: Any) -> None:
        if (self.owner.type_owner is not owner or self.owner.conn is not owner.conn
                or (self.task.user_id,self.task.epoch) != (owner.user_id,owner.epoch)
                or getattr(owner,"current_source_binding",None) is not self
                or owner.source_authority is not self.owner.type_owner.source_authority
                or owner.source_authority.connection is not self.owner.conn):
            raise PipelineRepositoryError("CURRENT_PACK_RELATION_ORIGINAL_OWNER_REQUIRED")
        self.relation_binding_hash()

    def require_relation(self, *, owner: Any, task: PersistentPackTaskRef,
                         candidate_version_ids: tuple[UUID, ...]) -> None:
        with _source_use(self):
            self._relation_owner(owner)
            if (task != self.task or len(candidate_version_ids) != 5
                    or set(candidate_version_ids) != set(VERSIONS.values())):
                raise PipelineRepositoryError("CURRENT_PACK_RELATION_EXACT_TASK_SELECTION_REQUIRED")
            require(self)

    def relation_sources(self, *, owner: Any, proof: NativePublicationProofV1
                         ) -> tuple[tuple[PublicMaterialV2, ...], tuple[SourceReceiptV2, ...]]:
        with _source_use(self):
            self._relation_owner(owner)
            return self.public_materials, self._receipts_for_proof(proof)

    def origin_id(self) -> UUID:
        return origin(self)[0]


def _data(core: PersistentPackTaskOwner, task: PersistentPackTaskRef) -> dict[str, Any]:
    _history(core, task)
    if task.pack_task_id != TASK or task.public_task_id != PUBLIC_TASK:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_CASE_REQUIRED")
    row = core.conn.execute("SELECT payload_json FROM " + PRIVATE +
        " WHERE id=%s AND pack_task_id=%s AND user_id=%s AND epoch=%s AND record_kind=%s FOR SHARE",
        (SOURCE_DATA,TASK,task.user_id,task.epoch,SUCCESSOR_KIND)).fetchone()
    if row is None:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_DATA_MISSING")
    data = row["payload_json"]
    if data["task_ref"] != task.model_dump(mode="json"):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_DATA_CHANGED")
    # Original receiver checks CURRENT actual-D/provenance; no revision cap is restored.
    core.conn.execute("SELECT item_supply_internal.assert_source_mapping_successor(%s)", (Jsonb(data),))
    return data


def _selection(core: PersistentPackTaskOwner, task: PersistentPackTaskRef,
               materials: tuple[PublicMaterialV2, ...]) -> tuple[list[dict[str, Any]], str]:
    record = _history(core, task)
    header = core.conn.execute("SELECT payload_json FROM " + SHARED +
        " WHERE public_task_id=%s AND record_kind='task' FOR SHARE", (PUBLIC_TASK,)).fetchone()
    if header is None:
        raise PipelineRepositoryError("CURRENT_PACK_PUBLIC_HEADER_MISSING")
    versions = core._versions(task)
    if set(versions) != set(VERSIONS):
        raise PipelineRepositoryError("CURRENT_PACK_EXACT_FIVE_SELECTION_REQUIRED")
    selected = []
    repo = core.type_owner.mapping_owner.current_authority.receipts
    for slot in SLOTS:
        version = versions[slot]
        private_slot = next(s for s in record.slots if s.slot == slot)
        if (version.published_version_id != VERSIONS[slot] or version.public_task_id != PUBLIC_TASK
                or version.public_slot_id != private_slot.public_slot_id):
            raise PipelineRepositoryError("CURRENT_PACK_SELECTION_CHANGED")
        row = core.conn.execute("SELECT p.proof_json,p.proof_hash,e.occurred_at AS published_at,"
            "g.root_id,g.candidate_id,item_supply_internal.controlled_counterexample_held(g.job_id) AS held "
            "FROM tutor_learning_item_native_publication_proofs p "
            "JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=p.generation_artifact_id "
            "JOIN tutor_learning_item_publication_events e ON e.id=p.publication_event_id "
            "JOIN LATERAL(SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=p.version_id "
            "ORDER BY state_version DESC LIMIT 1) latest ON latest.id=p.publication_event_id AND latest.state='published' "
            "WHERE p.version_id=%s", (version.published_version_id,)).fetchone()
        if row is None or row["held"] is not False:
            raise PipelineRepositoryError("CURRENT_PACK_EXACT_PUBLICATION_REQUIRED")
        proof = NativePublicationProofV1.model_validate_json(json.dumps(row["proof_json"]))
        if (proof.proof_hash != row["proof_hash"] or proof.generation_artifact_id != version.artifact_id
                or row["root_id"] != version.root_id or row["candidate_id"] != version.candidate_id
                or not proof.checked_at <= row["published_at"] < proof.valid_until
                or proof.specification_hash != version.specification.specification_hash):
            raise PipelineRepositoryError("CURRENT_PACK_EXACT_PUBLICATION_REQUIRED")
        for old, old_receipt, new in zip(proof.materials,proof.source_receipts,materials,strict=True):
            require_historical_material(repo,old,old_receipt,published_at=row["published_at"],new=new)
        selected.append(dict(slot=slot,version=version.model_dump(mode="json"),version_id=str(proof.version_id),
            proof_id=str(proof.proof_id),proof_hash=proof.proof_hash,published_at=row["published_at"].isoformat()))
    return selected, canonical_hash(dict(task=record.model_dump(mode="json"),header=header["payload_json"],selected=selected))


def _authorization(mapping: FiniteCourseMappingReceiptV1, public: tuple[PublicMaterialV2, ...],
                   course: tuple[PublicMaterialV2, ...], receipts: tuple[SourceReceiptV2, ...]) -> str:
    return canonical_hash(dict(purpose="whole_pack_current_source_only",mapping_hash=mapping.mapping_hash,
        public_materials=[m.model_dump(mode="json") for m in public],
        course_materials=[m.model_dump(mode="json") for m in course],
        receipts=[r.model_dump(mode="json",exclude={"checked_at_iso"}) for r in receipts]))


def issue(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, source_data_id: UUID) -> IssuedCurrentPackSourceBinding:
    if source_data_id != SOURCE_DATA:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_DATA_REQUIRED")
    data = _data(core,task)
    public = tuple(PublicMaterialV2.model_validate_json(json.dumps(m)) for m in data["public_materials"])
    course = tuple(PublicMaterialV2.model_validate_json(json.dumps(m)) for m in data["course_materials"])
    _, _, deadline = _current(core,task,public,course)
    mapping = core.type_owner.mapping_owner.resolve_source_successor(receipt_id=task.mapping_receipt_id,
        user_id=task.user_id,epoch=task.epoch,materials=course)
    _, selection_hash = _selection(core,task,public)
    receipts = tuple(core.type_owner.source_authority.authorize(m) for m in (*public,*course))
    cap = IssuedCurrentPackSourceBinding(core,uuid4(),task,canonical_hash(data),selection_hash,
        _authorization(mapping,public,course,receipts),deadline,public,course,mapping)
    core._current_source_bindings[cap.binding_id] = (cap,_seal(cap))
    try:
        origin(cap)
    except BaseException:
        core._current_source_bindings.pop(cap.binding_id,None)
        raise
    return cap


def _seal(cap: IssuedCurrentPackSourceBinding) -> str:
    return canonical_hash(dict(binding_id=str(cap.binding_id),task=cap.task.model_dump(mode="json"),
        data_hash=cap.source_data_hash,selection_hash=cap.selection_hash,source_hash=cap.source_authorization_hash,
        deadline=cap.source_deadline.isoformat(),mapping=cap.mapping.model_dump(mode="json"),
        public=[m.model_dump(mode="json") for m in cap.public_materials],course=[m.model_dump(mode="json") for m in cap.course_materials]))


@dataclass
class _CurrentSourceData:
    cap: IssuedCurrentPackSourceBinding
    conn: Connection[dict[str, Any]]
    repository: AssessmentReceiptRepository
    type_owner: Any
    authority: RagSourceAuthority
    txid: int
    seal: str
    origin_id: UUID
    payload: dict[str, Any]
    digest: str
    provenance: object | None = None
    authorization_config: tuple[Any, ...] = ()
    invocation: _PackSourceInvocation | None = None
    front: tuple[FiniteCourseMappingReceiptV1, list[dict[str, Any]]] | None = None
    public_receipts: tuple[SourceReceiptV2, ...] | None = None
    use_depth: int = 0
    closed: bool = False


_CURRENT_SOURCE_SCOPE: ContextVar[_CurrentSourceData | None] = ContextVar("current_pack_source_data", default=None)


def _authorization_config(authority: RagSourceAuthority) -> tuple[Any, ...]:
    current = getattr(authority,"_current",None)
    if current is None:
        return ()
    claims = authority._claims
    return (current,claims,current.governance,current.gates,current.authority_resolver,
        current.claim_resolver,current.execution_resolver,
        getattr(claims,"repository",None),getattr(claims,"preparation_owner",None),
        getattr(current.authority_resolver,"repository",None),getattr(current.authority_resolver,"preparation_owner",None),
        getattr(current.execution_resolver,"repository",None),getattr(current.execution_resolver,"preparation_owner",None))


def _invalidate_current_scope(cap: IssuedCurrentPackSourceBinding) -> None:
    state = _CURRENT_SOURCE_SCOPE.get()
    if state is not None and state.cap is cap:
        state.closed = True
        state.front = None
        state.public_receipts = None
        state.invocation = None
        state.repository._clear_current_scope(cap)


def _scope_origin_guard(cap: IssuedCurrentPackSourceBinding, *, repository: AssessmentReceiptRepository | None = None,
                        final: bool = False) -> None:
    """Exact original emitted origin plus SQL549, never an independent issuer."""
    state = _CURRENT_SOURCE_SCOPE.get()
    if state is None or state.closed or state.cap is not cap or type(cap) is not IssuedCurrentPackSourceBinding:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_SCOPE_REQUIRED")
    core = cap.owner
    entry = core._current_source_bindings.get(cap.binding_id)
    config = _authorization_config(state.authority)
    if (entry is None or entry[0] is not cap or entry[1] != state.seal
            or core.conn is not state.conn or core.type_owner is not state.type_owner
            or core.type_owner.conn is not state.conn or core.type_owner.source_authority is not state.authority
            or getattr(state.type_owner,"current_source_binding",None) is not cap
            or state.authority.connection is not state.conn
            or core.type_owner.mapping_owner.current_authority.receipts is not state.repository
            or state.repository.conn is not state.conn
            or state.repository.provenance is not state.provenance
            or getattr(state.repository.provenance,"conn",None) is not state.conn
            or len(config) != len(state.authorization_config)
            or any(current is not original for current,original in zip(config,state.authorization_config,strict=True))
            or repository is not None and repository is not state.repository
            or (core.user_id,core.epoch) != (cap.task.user_id,cap.task.epoch)
            or (state.type_owner.user_id,state.type_owner.epoch) != (cap.task.user_id,cap.task.epoch)):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_ISSUER_REQUIRED")
    # Only an enclosing ORIGINAL source-port invocation can share its guard.
    # Identity/config and every current-row predicate still execute on inner
    # repository reads; the outer guard rechecks seal, receiver and clock last.
    if state.use_depth and not final:
        return
    if _seal(cap) != state.seal:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_ISSUER_REQUIRED")
    # PRIVATE default-off and installed lifecycle/schema are ORIGINAL gates.
    # Invoke once at each outer initial/final fence, not per nested row read.
    from app.services.grounding.autonomous.actual_d_private_provenance import require_private_provenance
    require_private_provenance(state.repository)
    if config:
        config[0].require_transaction()
    core._guard()
    clock = core.conn.execute("SELECT clock_timestamp() AS now,txid_current() AS txid").fetchone()
    original = core._current_source_origins.get((cap.binding_id,state.txid))
    if (clock is None or int(clock["txid"]) != state.txid or not state.payload["issued_at"]
            or not datetime.fromisoformat(state.payload["issued_at"]) <= clock["now"] < cap.source_deadline
            or original is None or original[0] != state.origin_id or original[1] is not state.payload
            or original[2] != state.digest or canonical_hash(state.payload) != state.digest
            or state.payload["capture_txid"] != state.txid
            or state.payload["task_ref"] != cap.task.model_dump(mode="json")
            or state.payload["selection_hash"] != cap.selection_hash
            or state.payload["source_authorization_hash"] != cap.source_authorization_hash
            or state.front is not None and (state.front[0] != cap.mapping or state.front[1] != state.payload["selected"])
            or state.public_receipts is not None and [r.model_dump(mode="json") for r in state.public_receipts] != state.payload["public_receipts"]
            or len(state.payload["selected"]) != 5
            or {p["version_id"] for p in state.payload["selected"]} != {str(v) for v in VERSIONS.values()}):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGIN_CHANGED")
    row = core.conn.execute("SELECT item_supply_internal.current_pack_source_origin_current(%s,%s,%s,%s) AS ok",
        (state.origin_id,cap.task.user_id,cap.task.epoch,cap.task.mapping_receipt_id)).fetchone()
    if row is None or row["ok"] is not True:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGIN_STALE")


@contextmanager
def _source_use(cap: IssuedCurrentPackSourceBinding) -> Iterator[None]:
    """One verifier invocation, not a scope/TOP-wide permission cache."""
    state = _CURRENT_SOURCE_SCOPE.get()
    if state is None:
        yield None
        return
    outer = not state.use_depth
    try:
        _scope_origin_guard(cap)
        if not outer:
            yield None
            return
        state.use_depth = 1
        if state.front is not None:
            state.repository._require_current_records(cap)
        yield None
        if state.front is not None:
            state.repository._require_current_records(cap)
        # SQL549 and its final DB clock follow ALL inner source/corpus lock waits.
        _scope_origin_guard(cap, final=True)
    except BaseException:
        _invalidate_current_scope(state.cap)
        raise
    finally:
        if outer:
            state.use_depth = 0


@dataclass(frozen=True)
class _PackSourceInvocation:
    owner: Any
    pack_scope: Any
    proof_bindings: tuple[tuple[NativePublicationProofV1, datetime], ...]
    # Actual original assert_current results, not a positive verified flag.
    sources: tuple[tuple[PublicMaterialV2, SourceReceiptV2, SourceReceiptV2], ...]


def _require_invocation_members(cap: IssuedCurrentPackSourceBinding, query: Any,
                                authority: RagSourceAuthority,
                                proof_bindings: tuple[tuple[NativePublicationProofV1, datetime], ...]) -> Any:
    from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner

    state = _CURRENT_SOURCE_SCOPE.get()
    owner = cap.owner.type_owner
    if (state is None or state.closed or state.cap is not cap or state.front is None
            or state.public_receipts is None or type(owner) is not NativeTypeEvidenceOwner
            or owner is not state.type_owner or query is not owner.query or authority is not owner.source_authority
            or not isinstance(proof_bindings, tuple) or len(proof_bindings) != 5
            or any(not isinstance(pair,tuple) or len(pair) != 2 or type(pair[0]) is not NativePublicationProofV1
                or not isinstance(pair[1],datetime) or pair[1].tzinfo is None for pair in proof_bindings)
            or len({p.version_id for p,_ in proof_bindings}) != 5
            or {p.version_id for p,_ in proof_bindings} != set(VERSIONS.values())):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_INVOCATION_REQUIRED")
    scope = NativeTypeEvidenceOwner._current_pack_data(owner)
    if (scope is None or scope.source_binding is not cap or scope.txid != state.txid
            or scope.mapping_id != cap.task.mapping_receipt_id or len(scope.versions) != 5
            or set(scope.versions) != set(VERSIONS.values()) or scope.capability is None):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_INVOCATION_REQUIRED")
    registered = owner._issued.get(scope.capability.eligibility_id)
    if registered is None or registered[0] is not scope.capability or registered[1] != state.txid:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_INVOCATION_REQUIRED")
    selected = {p["version_id"]: p for p in state.payload["selected"]}
    for proof,published_at in proof_bindings:
        original = selected[str(proof.version_id)]
        resolved = scope.contents.get(proof.version_id)
        if (resolved is None or resolved.publication is not proof
                # This exact object already traversed full native front checks.
                # Pure canonical bytes detect mutation without proof_hash's
                # checked_model/finite-definition reconstruction in the tail.
                or (original["proof_id"],original["proof_hash"]) != (str(proof.proof_id),canonical_hash(proof.model_dump(mode="json")))
                or datetime.fromisoformat(original["published_at"]) != published_at
                or scope.published_at.get(proof.version_id) != published_at):
            raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_PUBLICATION_REQUIRED")
    return scope


def _require_invocation_receipts(cap: IssuedCurrentPackSourceBinding, invocation: _PackSourceInvocation,
                                 receipts: tuple[SourceReceiptV2, ...]) -> None:
    if len(receipts) != len(invocation.sources) or len(cap.public_materials) != len(invocation.sources):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_INVOCATION_DATA_CHANGED")
    for material,receipt,(original,expected,actual) in zip(cap.public_materials,receipts,invocation.sources,strict=True):
        if (material is not original or receipt is not expected
                or actual.model_dump(mode="json",exclude={"checked_at_iso"})
                    != expected.model_dump(mode="json",exclude={"checked_at_iso"})):
            raise PipelineRepositoryError("CURRENT_PACK_SOURCE_INVOCATION_DATA_CHANGED")


@contextmanager
def _current_pack_invocation(cap: IssuedCurrentPackSourceBinding, *, query: Any,
                             source_authority: RagSourceAuthority,
                             proof_bindings: tuple[tuple[NativePublicationProofV1, datetime], ...]) -> Iterator[None]:
    with _source_use(cap):
        state = _CURRENT_SOURCE_SCOPE.get()
        scope = _require_invocation_members(cap,query,source_authority,proof_bindings)
        if state is None or state.invocation is not None or state.public_receipts is None:
            raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_INVOCATION_REQUIRED")
        sources = []
        for material,receipt in zip(cap.public_materials,state.public_receipts,strict=True):
            actual = source_authority.assert_current(material,receipt)  # FULL original PUBLIC initial fence.
            if type(actual) is not SourceReceiptV2:
                raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_RECEIPT_DATA_REQUIRED")
            sources.append((material,receipt,actual))
        invocation = _PackSourceInvocation(state.type_owner,scope,proof_bindings,tuple(sources))
        _require_invocation_receipts(cap,invocation,state.public_receipts)
        state.invocation = invocation
        try:
            yield None
            if _require_invocation_members(cap,query,source_authority,proof_bindings) is not scope:
                raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_INVOCATION_REQUIRED")
            _require_invocation_receipts(cap,invocation,state.public_receipts)
            for material,receipt,initial in invocation.sources:
                actual = source_authority.assert_current(material,receipt)  # FULL PUBLIC after ALL bank/relation waits.
                if (type(actual) is not SourceReceiptV2 or actual.model_dump(mode="json",exclude={"checked_at_iso"})
                        != initial.model_dump(mode="json",exclude={"checked_at_iso"})):
                    raise PipelineRepositoryError("CURRENT_PACK_SOURCE_INVOCATION_DATA_CHANGED")
            # _source_use now performs final complete PRIVATE/PUBLIC record,
            # signed/raw/payload/config/schema/SQL549 and DB-clock fences.
        finally:
            state.invocation = None


@contextmanager
def _current_scope(cap: IssuedCurrentPackSourceBinding) -> Iterator[None]:
    active = _CURRENT_SOURCE_SCOPE.get()
    if type(cap) is not IssuedCurrentPackSourceBinding:
        if active is not None:
            _invalidate_current_scope(active.cap)
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_ISSUER_REQUIRED")
    if active is not None:
        try:
            _scope_origin_guard(cap)
            active.repository._require_current_records(cap)
            yield None
        except BaseException:
            _invalidate_current_scope(active.cap)
            raise
        return
    core = cap.owner
    core._guard()
    clock = core.conn.execute("SELECT clock_timestamp() AS now,txid_current() AS txid").fetchone()
    if clock is None:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_TRANSACTION_REQUIRED")
    txid = int(clock["txid"])
    original = core._current_source_origins.get((cap.binding_id,txid))
    # issue() already emitted this original origin. No UUID/file can restore it.
    if original is None:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_ORIGIN_REQUIRED")
    rid,payload,digest = original
    repo = core.type_owner.mapping_owner.current_authority.receipts
    state = _CurrentSourceData(cap,core.conn,repo,core.type_owner,core.type_owner.source_authority,
        txid,_seal(cap),rid,payload,digest)
    state.provenance = repo.provenance
    state.authorization_config = _authorization_config(state.authority)
    token = _CURRENT_SOURCE_SCOPE.set(state)
    try:
        _scope_origin_guard(cap)
        with repo._current_scope(cap):
            # Each exact evidence first traverses the ORIGINAL full verifier.
            with _source_use(cap):
                state.front = _require_current(cap)
            state.public_receipts = tuple(SourceReceiptV2.model_validate_json(json.dumps(r)) for r in payload["public_receipts"])
            origin(cap)
            yield None
    finally:
        _invalidate_current_scope(cap)
        _CURRENT_SOURCE_SCOPE.reset(token)


def _require_current(cap: IssuedCurrentPackSourceBinding) -> tuple[FiniteCourseMappingReceiptV1, list[dict[str, Any]]]:
    """Keep fresh mapping/selection results local to this verifier invocation."""
    if type(cap) is not IssuedCurrentPackSourceBinding:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_ISSUER_REQUIRED")
    state = _CURRENT_SOURCE_SCOPE.get()
    if state is not None:
        _scope_origin_guard(cap)
        if state.front is not None:
            if state.use_depth:
                return state.front
            with _source_use(cap):
                return state.front
    core = cap.owner
    entry = core._current_source_bindings.get(cap.binding_id)
    if entry is None or entry[0] is not cap or entry[1] != _seal(cap):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_ISSUER_REQUIRED")
    data = _data(core,cap.task)
    if (canonical_hash(data) != cap.source_data_hash
            or data["public_materials"] != [m.model_dump(mode="json") for m in cap.public_materials]
            or data["course_materials"] != [m.model_dump(mode="json") for m in cap.course_materials]):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_DATA_CHANGED")
    _, _, deadline, mapping = _current_with_mapping(core,cap.task,cap.public_materials,cap.course_materials)
    selected, selection_hash = _selection(core,cap.task,cap.public_materials)
    receipts = tuple(core.type_owner.source_authority.authorize(m) for m in (*cap.public_materials,*cap.course_materials))
    if (deadline != cap.source_deadline or core._guard() >= deadline or mapping != cap.mapping
            or selection_hash != cap.selection_hash
            or _authorization(mapping,cap.public_materials,cap.course_materials,receipts) != cap.source_authorization_hash):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_CURRENT_BINDING_CHANGED")
    return mapping,selected


def require(cap: IssuedCurrentPackSourceBinding) -> FiniteCourseMappingReceiptV1:
    with _source_use(cap):
        return _require_current(cap)[0]


def origin(cap: IssuedCurrentPackSourceBinding) -> tuple[UUID, dict[str, Any]]:
    with _source_use(cap):
        return _origin(cap)


def _origin(cap: IssuedCurrentPackSourceBinding) -> tuple[UUID, dict[str, Any]]:
    _, selected = _require_current(cap)
    state = _CURRENT_SOURCE_SCOPE.get()
    if state is not None:
        # _require_current just checked this exact emitted origin, SQL549 and
        # all original PUBLIC/PRIVATE current rows, including the final clock.
        return state.origin_id,state.payload
    core = cap.owner
    clock = core.conn.execute("SELECT clock_timestamp() AS now,txid_current() AS txid").fetchone()
    if clock is None:
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_TRANSACTION_REQUIRED")
    key = (cap.binding_id,int(clock["txid"]))
    cached = core._current_source_origins.get(key)
    if cached is not None:
        rid, payload, seal = cached
        if canonical_hash(payload) != seal:
            raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGIN_CHANGED")
        row = core.conn.execute("SELECT item_supply_internal.current_pack_source_origin_current(%s,%s,%s,%s) AS ok",
            (rid,cap.task.user_id,cap.task.epoch,cap.task.mapping_receipt_id)).fetchone()
        if row is None or row["ok"] is not True:
            raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGIN_STALE")
        return rid,payload
    authority = core.type_owner.source_authority
    public_receipts = tuple(authority.authorize(m) for m in cap.public_materials)
    course_receipts = tuple(authority.authorize(m) for m in cap.course_materials)
    payload = dict(schema_version="current_pack_source_origin_v1",purpose="whole_pack_current_source_only",
        task_ref=cap.task.model_dump(mode="json"),source_successor_id=str(SOURCE_DATA),source_successor_hash=cap.source_data_hash,
        selection_hash=cap.selection_hash,mapping_hash=cap.mapping.mapping_hash,source_authorization_hash=cap.source_authorization_hash,
        selected=selected,public_materials=[m.model_dump(mode="json") for m in cap.public_materials],
        course_materials=[m.model_dump(mode="json") for m in cap.course_materials],
        public_receipts=[r.model_dump(mode="json") for r in public_receipts],course_receipts=[r.model_dump(mode="json") for r in course_receipts],
        issued_at=clock["now"].isoformat(),valid_until=cap.source_deadline.isoformat(),capture_txid=int(clock["txid"]))
    rid = core._private_event(cap.task,KIND,payload,key="current.source."+uuid4().hex)
    core._current_source_origins[key] = (rid,payload,canonical_hash(payload))
    return rid,payload


def source_origin_payload(owner: Any, *, version_id: UUID | None = None) -> dict[str, str] | None:
    """Only explicit installed original context selects the NEW receiver mode."""
    cap = getattr(owner,"current_source_binding",None)
    if cap is None:
        return None
    with _source_use(cap):
        if type(cap) is not IssuedCurrentPackSourceBinding or cap.owner.type_owner is not owner:
            raise PipelineRepositoryError("CURRENT_PACK_SOURCE_ORIGINAL_TYPE_OWNER_REQUIRED")
        if version_id is not None and version_id not in VERSIONS.values():
            raise PipelineRepositoryError("CURRENT_PACK_SOURCE_EXACT_VERSION_REQUIRED")
        return dict(source_mode="current_pack_source_origin_v1",current_source_origin_id=str(cap.origin_id()))
