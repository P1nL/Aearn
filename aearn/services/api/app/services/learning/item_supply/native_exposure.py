"""B1d native exposure collector and serialized pre-practice reservation fence.

Actual owner-table triggers supply the durable inbox. No caller events, family
labels, complete flags or pure PackInputs snapshots become persistence authority.
Historical/unknown surfaces fail pending. These ports do not grant pack readiness.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash, stable_key
from app.services.learning.item_bank.native_publication import NativePublishedItemQuery
from app.services.learning.item_bank.native_publication_contracts import NativePublicationPending, NativePublicationProofV1
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.native_exposure_contracts import (
    COLLECTOR_VERSION, NativeExposureBindingV1, NativeExposurePending, NativeExposureSnapshot,
)
from app.services.learning.item_supply.pack_contracts import CompleteExposureV1, NativeExposureV1
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.storage import PostgresPrivateSupplyStorage


def _unseen(bindings: tuple[NativeExposureBindingV1, ...], exposure: CompleteExposureV1) -> bool:
    return not any(b.item_handle == r.item_handle or b.content_hash == r.content_hash
        or b.family_id == r.family_id or b.semantic_signature == r.semantic_signature
        for b in bindings for r in exposure.records)


class NativeExposureOwner:
    def __init__(self, conn: Connection[dict[str, Any]], *, user_id: UUID, expected_epoch: int,
                 published_query: NativePublishedItemQuery, source_authority: RagSourceAuthority,
                 enabled: bool = False) -> None:
        if (type(published_query) is not NativePublishedItemQuery or published_query.conn is not conn
                or type(source_authority) is not RagSourceAuthority or source_authority.connection is not conn):
            raise NativeExposurePending("native_exposure_concrete_owners_required")
        self.conn, self.user_id, self.epoch, self.enabled = conn, user_id, expected_epoch, enabled
        self.query, self.authority = published_query, source_authority
        self.private = PostgresPrivateSupplyStorage(conn, user_id=user_id, expected_epoch=expected_epoch)

    def _lock(self) -> None:
        if not self.enabled or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise NativeExposurePending("native_exposure_caller_transaction_required")
        self.query.artifacts.require_owner()
        self.private._check_epoch()
        # Same ordering as capture triggers: user/epoch fences, then this lock.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('native-exposure'),hashtext(%s))", (str(self.user_id),))

    def _binding(self, version_id: UUID, *, current: bool) -> tuple[NativeExposureBindingV1, FiniteCandidateSpecV1]:
        row = self.conn.execute(
            "SELECT n.proof_json,n.proof_hash,p.payload_json->'spec' AS spec_json "
            "FROM tutor_learning_item_native_publication_proofs n "
            "JOIN tutor_learning_item_validation_receipts v ON v.id=(n.proof_json->>'bank_validation_id')::uuid "
            "JOIN tutor_item_supply_shared_validation_evidence e ON e.id=v.native_validation_evidence_id "
            "JOIN tutor_item_supply_shared_validation_preparations p ON p.id=e.preparation_id "
            "WHERE n.version_id=%s ORDER BY n.created_at DESC LIMIT 2", (version_id,),
        ).fetchall()
        if len(row) != 1:
            raise NativeExposurePending("native_exposure_exact_publication_required")
        try:
            proof = NativePublicationProofV1.model_validate_json(json.dumps(row[0]["proof_json"]))
            spec = FiniteCandidateSpecV1.model_validate_json(json.dumps(row[0]["spec_json"]))
            family = next((f for f in families_for_course(spec.target_id) if f.family_id == spec.allocation.family_id), None)
        except (ValueError, TypeError, KeyError):
            raise NativeExposurePending("native_exposure_origin_unmapped") from None
        if (family is None or family.definition_hash != spec.family_definition_hash
                or spec.allocation.family_definition_hash != spec.family_definition_hash
                or row[0]["proof_hash"] != proof.proof_hash or proof.version_id != version_id
                or proof.target_id != spec.target_id or proof.specification_hash != spec.specification_hash):
            raise NativeExposurePending("native_exposure_immutable_family_mismatch")
        if current:
            try:
                found = self.query.query_exact(handle=proof.item_handle, spec=spec, source_authority=self.authority)
            except NativePublicationPending:
                raise NativeExposurePending("native_exposure_publication_stale") from None
            if found is None or found.proof_id != proof.proof_id:
                raise NativeExposurePending("native_exposure_publication_stale")
        return NativeExposureBindingV1(version_id=version_id, item_handle=proof.item_handle,
            content_hash=proof.content_hash, proof_id=proof.proof_id, proof_hash=proof.proof_hash,
            specification_hash=spec.specification_hash, family_id=family.family_id,
            family_definition_hash=family.definition_hash, semantic_signature=family.definition_hash,
            allocation_slot=spec.allocation.slot), spec

    def collect(self) -> str | None:
        """Consume actual durable owner rows; a gap never becomes empty history."""
        self._lock()
        rows = self.conn.execute(
            "SELECT i.* FROM tutor_item_supply_native_exposure_inbox i "
            "WHERE i.user_id=%s AND i.epoch=%s ORDER BY i.sequence LIMIT 4097", (self.user_id, self.epoch),
        ).fetchall()
        if len(rows) > 4096:
            return "native_exposure_history_bound_exceeded"
        pending = None
        for row in rows:
            if row["kind"] == "metadata":
                continue
            if row["kind"] == "untracked" or row["version_id"] is None:
                pending = "native_exposure_origin_unmapped"
                continue
            try:
                binding, _ = self._binding(UUID(str(row["version_id"])), current=False)
            except NativeExposurePending:
                pending = "native_exposure_origin_unmapped"
                continue
            payload = binding.model_dump(mode="json")
            self.conn.execute(
                "INSERT INTO tutor_item_supply_native_exposure_events "
                "(inbox_id,user_id,epoch,version_id,proof_id,binding_json) VALUES(%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(inbox_id) DO NOTHING",
                (row["id"], self.user_id, self.epoch, binding.version_id, binding.proof_id, Jsonb(payload)),
            )
            stored = self.conn.execute("SELECT binding_hash FROM tutor_item_supply_native_exposure_events "
                                       "WHERE inbox_id=%s AND user_id=%s AND epoch=%s",
                                       (row["id"], self.user_id, self.epoch)).fetchone()
            if stored is None or stored["binding_hash"] != canonical_hash(payload):
                raise NativeExposurePending("native_exposure_event_conflict")
        return pending

    def snapshot(self) -> NativeExposureSnapshot:
        pending = self.collect()
        birth = self.conn.execute("SELECT id FROM tutor_item_supply_native_exposure_births "
                                  "WHERE user_id=%s AND epoch=%s AND collector_version=%s",
                                  (self.user_id, self.epoch, COLLECTOR_VERSION)).fetchone()
        hooks = self.conn.execute("SELECT item_supply_internal.native_exposure_hooks_current() AS current").fetchone()
        if birth is None or hooks is None or hooks["current"] is not True or pending:
            return NativeExposureSnapshot("pending", pending or "native_exposure_complete_start_unproven")
        raw = self.conn.execute("SELECT COALESCE(max(sequence),0) AS watermark,count(*) AS total "
            "FROM tutor_item_supply_native_exposure_inbox WHERE user_id=%s AND epoch=%s", (self.user_id, self.epoch)).fetchone()
        assert raw is not None
        rows = self.conn.execute("SELECT i.id,i.kind,e.binding_json FROM tutor_item_supply_native_exposure_events e "
            "JOIN tutor_item_supply_native_exposure_inbox i ON i.id=e.inbox_id AND i.user_id=e.user_id AND i.epoch=e.epoch "
            "WHERE e.user_id=%s AND e.epoch=%s ORDER BY i.sequence", (self.user_id, self.epoch)).fetchall()
        records = tuple(NativeExposureV1(event_id=UUID(str(r["id"])), item_handle=r["binding_json"]["item_handle"],
            content_hash=r["binding_json"]["content_hash"], family_id=r["binding_json"]["family_id"],
            semantic_signature=r["binding_json"]["semantic_signature"], kind=r["kind"]) for r in rows)
        payload = {"user_id": str(self.user_id), "epoch": self.epoch, "birth_id": str(birth["id"]),
            "collector_version": COLLECTOR_VERSION, "watermark": raw["watermark"], "origin_count": raw["total"],
            "records_hash": canonical_hash([r.model_dump(mode="json") for r in records])}
        digest = canonical_hash(payload)
        receipt = self.conn.execute("INSERT INTO tutor_item_supply_native_exposure_watermarks "
            "(user_id,epoch,birth_id,watermark,payload_json) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT(user_id,epoch,payload_hash) DO NOTHING RETURNING id",
            (self.user_id, self.epoch, birth["id"], raw["watermark"], Jsonb(payload))).fetchone()
        if receipt is None:
            receipt = self.conn.execute("SELECT id FROM tutor_item_supply_native_exposure_watermarks "
                "WHERE user_id=%s AND epoch=%s AND payload_hash=%s", (self.user_id, self.epoch, digest)).fetchone()
        assert receipt is not None
        now = server_clock(self.conn, datetime.now(UTC))
        # A bounded projection, not a cached authorization: every reservation and
        # delivery reacquires the lock and calls snapshot() again in its own tx.
        return NativeExposureSnapshot("complete", "native_exposure_current", CompleteExposureV1(
            learner_id=self.user_id, epoch=self.epoch, collector_version=COLLECTOR_VERSION,
            watermark=raw["watermark"], completeness_receipt_hash=digest, observed_at=now,
            valid_until=now + timedelta(seconds=30), records=records), UUID(str(receipt["id"])))

    def _scope_binding(self, scope_id: UUID, version_id: UUID) -> NativeExposureBindingV1:
        scope = self.private._scope(scope_id)
        binding, spec = self._binding(version_id, current=True)
        stored_scope = scope["snapshot_json"]
        if not isinstance(stored_scope, dict):
            raise NativeExposurePending("native_exposure_exact_scope_required")
        private = {k: v for k, v in stored_scope.items() if k not in {"visibility", "owner_ref"}}
        public = {k: v for k, v in spec.coverage_blueprint.scope.model_dump(mode="json").items()
                  if k not in {"visibility", "owner_ref"}}
        if private != public:
            raise NativeExposurePending("native_exposure_exact_scope_required")
        return binding

    def reserve_assessment(self, *, scope_id: UUID, version_ids: tuple[UUID, UUID], operation_key: str) -> UUID:
        self._lock()
        key = stable_key(operation_key, label="native assessment reservation")
        if len(version_ids) != 2 or len(set(version_ids)) != 2:
            raise NativeExposurePending("native_assessment_two_exact_versions_required")
        snapshot = self.snapshot()
        if snapshot.exposure is None:
            raise NativeExposurePending(snapshot.safe_reason)
        bindings = tuple(self._scope_binding(scope_id, version) for version in version_ids)
        if (len(set(version_ids)) != 2 or len({b.family_id for b in bindings}) != 2
                or any(b.allocation_slot != "assessment" for b in bindings) or not _unseen(bindings, snapshot.exposure)):
            raise NativeExposurePending("native_assessment_not_unexposed")
        data = [b.model_dump(mode="json") for b in bindings]
        request_hash = canonical_hash({"scope_id": str(scope_id), "bindings": data})
        row = self.conn.execute("INSERT INTO tutor_item_supply_native_exposure_reservations "
            "(user_id,epoch,scope_id,operation_key,request_hash,watermark_id,bindings_json) VALUES(%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(user_id,epoch,operation_key) DO NOTHING RETURNING id,request_hash",
            (self.user_id, self.epoch, scope_id, key, request_hash, snapshot.watermark_id, Jsonb(data))).fetchone()
        if row is None:
            row = self.conn.execute("SELECT id,request_hash FROM tutor_item_supply_native_exposure_reservations "
                "WHERE user_id=%s AND epoch=%s AND operation_key=%s", (self.user_id, self.epoch, key)).fetchone()
        if row is None or row["request_hash"] != request_hash:
            raise NativeExposurePending("native_assessment_reservation_conflict")
        return UUID(str(row["id"]))

    def prepare_practice_delivery(self, *, scope_id: UUID, version_id: UUID,
                                  reservation_key: str, delivery_key: str) -> UUID:
        """Exposure fence only; caller still needs actual complete pack authority.

        Call BEFORE Artifact creation in the SAME transaction. This does not
        authorize P8 assessment delivery or assert family-pair independence.
        """
        self._lock()
        key = stable_key(delivery_key, label="native practice delivery")
        reserved = self.conn.execute("SELECT * FROM tutor_item_supply_native_exposure_reservations "
            "WHERE user_id=%s AND epoch=%s AND scope_id=%s AND operation_key=%s",
            (self.user_id, self.epoch, scope_id, stable_key(reservation_key, label="native reservation"))).fetchone()
        if reserved is None:
            raise NativeExposurePending("native_assessment_reservation_required")
        snapshot = self.snapshot()
        if snapshot.exposure is None:
            raise NativeExposurePending(snapshot.safe_reason)
        protected = tuple(NativeExposureBindingV1.model_validate_json(json.dumps(b)) for b in reserved["bindings_json"])
        for b in protected:
            if self._scope_binding(scope_id, b.version_id) != b:
                raise NativeExposurePending("native_assessment_reservation_stale")
        if not _unseen(protected, snapshot.exposure):
            raise NativeExposurePending("native_assessment_reservation_exposed")
        practice = self._scope_binding(scope_id, version_id)
        if practice.allocation_slot != "practice" or any(practice.family_id == b.family_id
                or practice.semantic_signature == b.semantic_signature for b in protected):
            raise NativeExposurePending("native_practice_reservation_conflict")
        payload = practice.model_dump(mode="json")
        request_hash = canonical_hash({"scope_id": str(scope_id), "reservation_id": str(reserved["id"]), "binding": payload})
        row = self.conn.execute("INSERT INTO tutor_item_supply_native_exposure_deliveries "
            "(id,user_id,epoch,scope_id,reservation_id,version_id,delivery_key,request_hash,binding_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,epoch,delivery_key) DO NOTHING "
            "RETURNING id,request_hash,delivery_txid=txid_current() AS current_tx",
            (uuid4(), self.user_id, self.epoch, scope_id, reserved["id"], version_id, key, request_hash, Jsonb(payload))).fetchone()
        if row is None:
            row = self.conn.execute("SELECT id,request_hash,delivery_txid=txid_current() AS current_tx "
                "FROM tutor_item_supply_native_exposure_deliveries WHERE user_id=%s AND epoch=%s AND delivery_key=%s",
                (self.user_id, self.epoch, key)).fetchone()
        if row is None or row["request_hash"] != request_hash or row["current_tx"] is not True:
            raise NativeExposurePending("native_practice_delivery_conflict")
        return UUID(str(row["id"]))
