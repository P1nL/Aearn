"""Explicit native KC consumer authority; creation and later actions are distinct.

No provider, Artifact writer, Attempt, Gate or progression effects. Historical
creation DATA identifies a frozen binding; every content action re-resolves the
original current source/mapping owner and issues a NEW transaction-local receipt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability, NativeResolvedContent
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.persistent_pack_current_source import source_origin_payload
from app.services.learning.artifacts.contracts import TutorArtifactCreate, TutorPublicArtifactItem
from app.services.learning.artifacts.owner_adapters import ArtifactOwnerVersionConflict

if TYPE_CHECKING:
    from app.services.learning.teaching_artifacts import NativeTeachingPracticeDeliveryContext


class NativeConsumerPending(ArtifactOwnerVersionConflict):
    """Fixed private failure code, without source/provider bodies."""


def _flags(settings: Settings) -> None:
    if not settings.tutor_learning_artifacts_enabled or not settings.tutor_artifact_teaching_mode_enabled:
        raise NativeConsumerPending("native_consumer_disabled")


def _mapped(owner: NativeTypeEvidenceOwner, mapping_id: UUID, version_id: UUID,
            actual_catalog: str) -> tuple[Any, NativeResolvedContent, Any]:
    try:
        mapping = owner.resolve_mapping(mapping_id)
    except ValueError:
        raise NativeConsumerPending("native_consumer_current_mapping_required") from None
    node = mapping.frozen_node
    if (mapping.target_id != "python-kc-binding-v1"
            or (node.catalog_knowledge_key or node.knowledge_key) != actual_catalog):
        raise NativeConsumerPending("native_consumer_exact_catalog_mapping_required")
    try:
        content = owner.resolve_content(version_id, current=True)
        now = server_clock(owner.conn, datetime.now(UTC))
        candidate = owner._candidate(content, mapping, now)
        # The scoped owner returns the exact actually issued candidate, not a
        # second late projection. Its original dynamic current fences still run.
        final, _ = owner._guard()
        if not candidate.observed_at <= final < candidate.valid_until:
            raise ValueError('native_consumer_current_candidate_expired')
    except ValueError:
        raise NativeConsumerPending("native_consumer_current_source_and_content_required") from None
    if (candidate.member.slot != "practice" or candidate.candidate.visibility != "public"
            or candidate.owner_id is not None or candidate.epoch is not None
            or content.source.blueprint.knowledge_key != "finite." + mapping.target_id
            or content.source.public.kind.value != "knowledge_check"):
        raise NativeConsumerPending("native_consumer_exact_public_practice_required")
    return mapping, content, candidate


def creation_catalog(context: NativeTeachingPracticeDeliveryContext, *, actual_catalog: str) -> str:
    """Derive public catalog from checked original spec, never the requested row."""
    mapping, _content, _candidate = _mapped(context.exposure_owner.type_owner,
        context.mapping_receipt_id, context.selected_version_id, actual_catalog)
    return "finite." + mapping.target_id


def persist_creation(context: NativeTeachingPracticeDeliveryContext, *,
                     capability: IssuedNativePackCapability, delivery_id: UUID,
                     request: TutorArtifactCreate) -> UUID:
    owner = context.exposure_owner.type_owner
    _flags(owner.settings)
    pack = owner.require_pack(capability)
    mapping, content, candidate = _mapped(owner, context.mapping_receipt_id,
        context.selected_version_id, owner.resolve_mapping(context.mapping_receipt_id).frozen_node.catalog_knowledge_key
        or request.knowledge_key)
    node = mapping.frozen_node
    selected = next((c for c in pack.selected if c.version_id == context.selected_version_id
                     and c.member.slot == "practice"), None)
    if (selected is None
            or (selected.candidate.objective_hash, selected.candidate.scope.scope_hash, selected.proof_id,
                selected.materialization_id, selected.publication_id, selected.type_evidence.content)
            != (candidate.candidate.objective_hash, candidate.candidate.scope.scope_hash, candidate.proof_id,
                candidate.materialization_id, candidate.publication_id, candidate.type_evidence.content)
            or pack.request != mapping.pack_request
            or (request.user_id, request.learning_track_id, request.knowledge_key)
            != (str(node.user_id), str(node.track_id), node.knowledge_key)):
        raise NativeConsumerPending("native_consumer_creation_binding_required")
    now = server_clock(owner.conn, datetime.now(UTC))
    payload = {"schema_version": "native_artifact_creation_v1", "request": request.model_dump(mode="json"),
        "mapping_id": str(mapping.receipt_id), "mapping_hash": mapping.mapping_hash,
        "goal_hash": node.goal_hash, "catalog_key": node.catalog_knowledge_key or node.knowledge_key,
        "public_catalog_key": content.source.blueprint.knowledge_key,
        "version_id": str(context.selected_version_id), "proof_id": str(content.publication.proof_id),
        "publication_id": str(content.publication.publication_event_id),
        "materialization_id": str(content.publication.materialization_id),
        "content_hash": content.source.content_hash, "scope_hash": candidate.candidate.scope.scope_hash,
        "objective_hash": candidate.candidate.objective_hash,
        "current_consumption": content.consumption.model_dump(mode="json") if content.consumption else None}
    source_origin = source_origin_payload(owner, version_id=context.selected_version_id)
    if source_origin is not None:
        payload = {**payload, "schema_version": "native_artifact_creation_current_source_v2", **source_origin}
    receipt = uuid4()
    owner.conn.execute("INSERT INTO tutor_item_supply_native_consumer_receipts "
        "(id,user_id,epoch,mode,run_id,mapping_id,version_id,delivery_id,payload_json,checked_at,valid_until) "
        "VALUES(%s,%s,%s,'create',%s,%s,%s,%s,%s,%s,%s)",
        (receipt, owner.user_id, owner.epoch, request.turn_id, mapping.receipt_id,
         context.selected_version_id, delivery_id, Jsonb(payload), now,
         min(pack.valid_until, now + timedelta(seconds=30), owner.source_deadline(content))))
    owner.require_pack(capability)
    _flags(owner.settings)
    return receipt


@dataclass(frozen=True)
class IssuedNativeConsumerAuthority:
    owner: NativeArtifactConsumerOwner
    receipt_id: UUID
    artifact_id: str
    artifact_version: int
    public_version_id: str
    mode: str
    action: str


def require_consumer_authority(authority: IssuedNativeConsumerAuthority, *,
                              conn: Connection[dict[str, Any]], artifact: TutorPublicArtifactItem,
                              expected_mode: str, expected_action: str | None = None) -> UUID:
    if type(authority) is not IssuedNativeConsumerAuthority or type(authority.owner) is not NativeArtifactConsumerOwner:
        raise NativeConsumerPending("native_consumer_concrete_issued_owner_required")
    authority.owner.require(authority, conn=conn, artifact=artifact,
                            expected_mode=expected_mode, expected_action=expected_action)
    return authority.receipt_id


class NativeArtifactConsumerOwner:
    """Default-off exact existing type owner; no generic verifier/callback port."""
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 type_owner: NativeTypeEvidenceOwner, enabled: bool = False) -> None:
        if (type(type_owner) is not NativeTypeEvidenceOwner or type_owner.conn is not conn
                or type_owner.settings is not settings):
            raise NativeConsumerPending("native_consumer_concrete_owner_required")
        self.conn, self.settings, self.type_owner, self.enabled = conn, settings, type_owner, enabled
        self._issued: dict[UUID, tuple[IssuedNativeConsumerAuthority, int, dict[str, Any]]] = {}

    def _guard(self) -> tuple[datetime, int]:
        if (type(self.type_owner) is not NativeTypeEvidenceOwner or self.type_owner.conn is not self.conn
                or self.type_owner.settings is not self.settings):
            raise NativeConsumerPending("native_consumer_concrete_owner_required")
        if not self.enabled:
            raise NativeConsumerPending("native_consumer_disabled")
        _flags(self.settings)
        try:
            return self.type_owner._guard()
        except ValueError:
            raise NativeConsumerPending("native_consumer_current_transaction_owner_required") from None

    def is_bound(self, artifact: TutorPublicArtifactItem) -> bool:
        row = self.conn.execute("SELECT 1 FROM tutor_item_supply_native_artifact_bindings "
            "WHERE artifact_id=%s AND user_id=%s", (artifact.id, self.type_owner.user_id)).fetchone()
        return row is not None

    def prepare(self, *, artifact: TutorPublicArtifactItem, action: str) -> IssuedNativeConsumerAuthority:
        now, txid = self._guard()
        if action not in {"cancel", "request_hint", "request_direct_answer", "respond"}:
            raise NativeConsumerPending("native_consumer_action_unsupported")
        binding = self.conn.execute("SELECT b.*,r.payload_json AS creation FROM tutor_item_supply_native_artifact_bindings b "
            "JOIN tutor_item_supply_native_consumer_receipts r ON r.id=b.creation_receipt_id "
            "WHERE b.artifact_id=%s AND b.user_id=%s AND b.epoch=%s", (artifact.id,
            self.type_owner.user_id, self.type_owner.epoch)).fetchone()
        if binding is None or artifact.owner_id != str(binding["version_id"]) or artifact.artifact_kind.value != "knowledge_check":
            raise NativeConsumerPending("native_consumer_original_artifact_binding_required")
        creation = binding["creation"]
        content = None
        if action != "cancel":
            mapping, content, candidate = _mapped(self.type_owner, UUID(str(binding["mapping_id"])),
                UUID(artifact.owner_id), creation["catalog_key"])
            if (mapping.mapping_hash != creation["mapping_hash"]
                    or mapping.frozen_node.goal_hash != creation["goal_hash"]
                    or str(content.publication.proof_id) != creation["proof_id"]
                    or content.source.content_hash != creation["content_hash"]
                    or candidate.candidate.objective_hash != creation["objective_hash"]):
                raise NativeConsumerPending("native_consumer_frozen_goal_or_content_changed")
        now, txid = self._guard()
        mode = "cancel" if action == "cancel" else "consume"
        payload = {"schema_version": "native_artifact_consumption_v1", "artifact_id": artifact.id,
            "artifact_version": artifact.version, "action": action,
            "creation_receipt_id": str(binding["creation_receipt_id"]),
            "current_consumption": content.consumption.model_dump(mode="json") if content and content.consumption else None}
        if action != "cancel":
            source_origin = source_origin_payload(self.type_owner, version_id=UUID(artifact.owner_id))
            if source_origin is not None:
                payload = {**payload, "schema_version": "native_artifact_consumption_current_source_v2", **source_origin}
        receipt = uuid4()
        deadline = now + timedelta(seconds=30)
        if content:
            deadline = min(deadline, self.type_owner.source_deadline(content))
        self.conn.execute("INSERT INTO tutor_item_supply_native_consumer_receipts "
            "(id,user_id,epoch,mode,artifact_id,artifact_version,mapping_id,version_id,payload_json,checked_at,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (receipt, self.type_owner.user_id, self.type_owner.epoch, mode, artifact.id, artifact.version,
             binding["mapping_id"], binding["version_id"], Jsonb(payload), now, deadline))
        cap = IssuedNativeConsumerAuthority(self, receipt, artifact.id, artifact.version, artifact.owner_id, mode, action)
        self._issued[receipt] = cap, txid, dict(binding)
        self.require(cap, conn=self.conn, artifact=artifact, expected_mode=mode, expected_action=action)
        return cap

    def require(self, authority: IssuedNativeConsumerAuthority, *, conn: Connection[dict[str, Any]],
                artifact: TutorPublicArtifactItem, expected_mode: str, expected_action: str | None = None) -> str:
        if type(authority) is not IssuedNativeConsumerAuthority:
            raise NativeConsumerPending("native_consumer_current_issued_authority_required")
        now, txid = self._guard()
        entry = self._issued.get(authority.receipt_id)
        if (conn is not self.conn or type(authority) is not IssuedNativeConsumerAuthority
                or authority.owner is not self or entry is None or entry[0] is not authority or entry[1] != txid
                or str(entry[2]["user_id"]) != str(self.type_owner.user_id) or entry[2]["epoch"] != self.type_owner.epoch
                or expected_mode not in {"consume", "cancel"} or authority.mode != expected_mode
                or (expected_action is not None and authority.action != expected_action)
                or (expected_mode == "cancel" and authority.action != "cancel")
                or (expected_mode == "consume" and authority.action not in {"request_hint", "request_direct_answer", "respond"})
                or (authority.artifact_id, authority.artifact_version, authority.public_version_id)
                != (artifact.id, artifact.version, artifact.owner_id)):
            raise NativeConsumerPending("native_consumer_current_issued_authority_required")
        row = self.conn.execute("SELECT item_supply_internal.native_consumer_receipt_current(%s) AS current",
            (authority.receipt_id,)).fetchone()
        if row is None or row["current"] is not True:
            raise NativeConsumerPending("native_consumer_current_persisted_authority_required")
        if authority.mode == "consume":
            binding = entry[2]
            creation = binding["creation"]
            mapping, content, _candidate = _mapped(self.type_owner, UUID(str(binding["mapping_id"])),
                UUID(artifact.owner_id), creation["catalog_key"])
            if mapping.mapping_hash != creation["mapping_hash"] or content.source.content_hash != creation["content_hash"]:
                raise NativeConsumerPending("native_consumer_current_goal_or_source_changed")
        # The original owner can wait on source/bank locks. Recheck the NEW
        # receipt clock/CAS after those waits, not just before current resolution.
        current = self.conn.execute("SELECT item_supply_internal.native_consumer_receipt_current(%s) AS current",
            (authority.receipt_id,)).fetchone()
        if current is None or current["current"] is not True:
            raise NativeConsumerPending("native_consumer_current_persisted_authority_required")
        self._guard()
        return artifact.owner_id

