"""Explicit content-aware owner alongside, never instead of, the 495 collector.

Only native DB owners issue the pack capability. Writes share the caller's short
READ COMMITTED transaction, before the original Artifact writer. No Gate effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash, stable_key
from app.services.learning.item_supply.native_exposure import NativeExposureOwner
from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
from app.services.learning.item_supply.native_type_exposure_contracts import (
    TYPE_COLLECTOR_VERSION, NativeTypeExposurePending, NativeTypeExposureSnapshot,
)
from app.services.learning.item_supply.pack_contracts import CompleteExposureV2, NativeExposureV2, PackSnapshotV2
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.type_evidence import ContentIdentityV2, assessment_clone


@dataclass(frozen=True)
class _ExposureHistory:
    # Exact original inbox/event rows, including metadata, not just version IDs.
    manifest: dict[str, Any]
    contents: dict[UUID, Any]


def _ids(values: tuple[UUID, ...], *, maximum: int) -> tuple[UUID, ...]:
    if (not isinstance(values, tuple) or not 1 <= len(values) <= maximum
            or any(type(v) is not UUID for v in values) or len(set(values)) != len(values)):
        raise NativeTypeExposurePending("native_type_exact_ids_required")
    return tuple(sorted(values, key=str))


def _protected(pack: PackSnapshotV2, exposure: CompleteExposureV2) -> tuple[ContentIdentityV2, ...]:
    """Defence in depth; never substitutes for 501's native evidence authority."""
    counts = {slot: sum(c.member.slot == slot for c in pack.selected)
              for slot in ("practice", "assessment", "remediation")}
    if counts != {"practice": 2, "assessment": 2, "remediation": 1}:
        raise NativeTypeExposurePending("native_type_exact_221_required")
    pair = tuple(c.type_evidence.content for c in pack.selected if c.member.slot == "assessment")
    if (assessment_clone(*pair) or any(assessment_clone(b, r.content) for b in pair for r in exposure.records)
            or any(assessment_clone(b, c.type_evidence.content) for b in pair for c in pack.selected
                   if c.member.slot != "assessment")):
        raise NativeTypeExposurePending("native_type_assessment_clone_or_exposed")
    return tuple(sorted(pair, key=lambda b: str(b.version_id)))


class NativeExposureOwnerV2:
    def __init__(self, conn: Connection[dict[str, Any]], *, user_id: UUID, expected_epoch: int,
                 type_owner: NativeTypeEvidenceOwner, enabled: bool = False) -> None:
        if (type(type_owner) is not NativeTypeEvidenceOwner or type_owner.conn is not conn
                or type_owner.user_id != user_id or type_owner.epoch != expected_epoch):
            raise NativeTypeExposurePending("native_type_concrete_owner_required")
        self.conn, self.user_id, self.epoch = conn, user_id, expected_epoch
        self.enabled, self.type_owner = enabled, type_owner
        self.collector = NativeExposureOwner(conn, user_id=user_id, expected_epoch=expected_epoch,
            published_query=type_owner.query, source_authority=type_owner.source_authority, enabled=enabled)

    def _lock(self) -> datetime:
        self.collector._lock()
        if not self.enabled:
            raise NativeTypeExposurePending("native_type_exposure_disabled")
        row = self.conn.execute("SELECT current_setting('transaction_isolation') AS isolation").fetchone()
        if row is None or row["isolation"] != "read committed":
            raise NativeTypeExposurePending("native_type_read_committed_required")
        # Re-read epoch and DB time after lock waits, not transaction-start time.
        self.conn.execute("SELECT item_supply_internal.native_exposure_lock(%s,%s)", (self.user_id, self.epoch))
        self.collector.private._check_epoch()
        return server_clock(self.conn, datetime.now(UTC))

    def _history_manifest(self) -> dict[str, Any]:
        self._lock()
        rows = self.conn.execute(
            "SELECT to_jsonb(i) AS inbox,to_jsonb(e) AS event "
            "FROM tutor_item_supply_native_exposure_inbox i "
            "LEFT JOIN tutor_item_supply_native_exposure_events e ON e.inbox_id=i.id "
            "AND e.user_id=i.user_id AND e.epoch=i.epoch "
            "WHERE i.user_id=%s AND i.epoch=%s ORDER BY i.sequence LIMIT 4097",
            (self.user_id, self.epoch),
        ).fetchall()
        birth = self.conn.execute("SELECT to_jsonb(b) AS birth FROM tutor_item_supply_native_exposure_births b "
            "WHERE user_id=%s AND epoch=%s", (self.user_id, self.epoch)).fetchall()
        hooks = self.conn.execute("SELECT item_supply_internal.native_exposure_hooks_current() AS current").fetchone()
        counts = self.conn.execute("SELECT COALESCE(max(sequence),0) AS watermark,count(*) AS total "
            "FROM tutor_item_supply_native_exposure_inbox WHERE user_id=%s AND epoch=%s",
            (self.user_id, self.epoch)).fetchone()
        if (len(rows) > 4096 or not birth or hooks is None or hooks['current'] is not True
                or counts is None or counts['total'] != len(rows)
                or any(r['inbox']['kind'] != 'metadata' and r['event'] is None for r in rows)):
            raise NativeTypeExposurePending("native_type_exposure_history_mismatch")
        return {'rows': rows, 'birth': birth, 'hooks': hooks, 'counts': counts}

    def _prepare_history(self) -> _ExposureHistory:
        self._lock()
        pending = self.collector.collect()
        if pending:
            raise NativeTypeExposurePending(pending)
        manifest = self._history_manifest()
        contents = {}
        for row in manifest['rows']:
            event = row['event']
            if event is None:
                continue
            resolved = self.type_owner.resolve_content(UUID(event['version_id']), current=False)
            binding = event['binding_json']
            if (event['proof_id'] != str(resolved.publication.proof_id)
                    or binding['proof_hash'] != resolved.publication.proof_hash
                    or event['binding_hash'] != canonical_hash(binding)
                    or (binding['item_handle'], binding['content_hash'])
                    != (resolved.content.item_handle, resolved.content.content_hash)):
                raise NativeTypeExposurePending("native_type_exposure_content_mismatch")
            contents[resolved.content.version_id] = resolved
        return _ExposureHistory(manifest, contents)

    def snapshot_v2(self) -> NativeTypeExposureSnapshot:
        self._lock()
        scoped = self.type_owner._scoped_observation(self)
        if scoped is not None:
            return scoped
        try:
            history = self._prepare_history()
        except (NativeTypeExposurePending, NativeTypeEvidencePending) as exc:
            return NativeTypeExposureSnapshot("pending", str(exc))
        return self._snapshot_from_history(history)

    def _snapshot_from_history(self, history: _ExposureHistory) -> NativeTypeExposureSnapshot:
        self._lock()
        if self._history_manifest() != history.manifest:
            raise NativeTypeExposurePending("native_type_exposure_history_changed")
        original = self.collector.snapshot()
        if original.exposure is None or original.watermark_id is None:
            return NativeTypeExposureSnapshot("pending", original.safe_reason)
        # Original collector clocks only after its complete locked collection.
        # Recheck the complete exact set, never re-stamp a pre-read manifest.
        if self._history_manifest() != history.manifest:
            raise NativeTypeExposurePending("native_type_exposure_history_changed")
        rows = [r for r in history.manifest['rows'] if r['event'] is not None]
        if len(rows) != len(original.exposure.records):
            return NativeTypeExposureSnapshot("pending", "native_type_exposure_history_mismatch")
        records = []
        for row, old in zip(rows, original.exposure.records, strict=True):
            event, inbox = row['event'], row['inbox']
            resolved = history.contents[UUID(event['version_id'])]
            content = resolved.content
            if (UUID(inbox["id"]) != old.event_id or inbox["kind"] != old.kind
                    or (content.item_handle, content.content_hash) != (old.item_handle, old.content_hash)
                    or content.version_id != UUID(event["version_id"])):
                return NativeTypeExposureSnapshot("pending", "native_type_exposure_content_mismatch")
            records.append(NativeExposureV2(**old.model_dump(), content=content))
        manifest = {"original_watermark_id": str(original.watermark_id),
                    "original_receipt_hash": original.exposure.completeness_receipt_hash,
                    "records": [r.model_dump(mode="json") for r in records]}
        exposure = CompleteExposureV2(learner_id=self.user_id, epoch=self.epoch,
            collector_version=TYPE_COLLECTOR_VERSION, watermark=original.exposure.watermark,
            completeness_receipt_hash=canonical_hash(manifest), observed_at=original.exposure.observed_at,
            valid_until=original.exposure.valid_until, records=tuple(records))
        snapshot_id = uuid4()
        self.conn.execute("INSERT INTO tutor_item_supply_type_exposure_snapshots "
            "(id,user_id,epoch,original_watermark_id,snapshot_json,checked_at,valid_until) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (snapshot_id, self.user_id, self.epoch, original.watermark_id, Jsonb(exposure.model_dump(mode="json")),
             exposure.observed_at, exposure.valid_until))
        return NativeTypeExposureSnapshot("complete", "native_type_exposure_current", exposure, snapshot_id, original.watermark_id)

    def _effect_observation(self) -> NativeTypeExposureSnapshot:
        """Exact scoped DATA for one atomic effect; _pack still fences authority."""
        self._lock()
        scoped = self.type_owner._current_pack_data()
        if scoped is None:
            return self.snapshot_v2()
        if (scoped.exposure_owner is not self or scoped.observation is None
                or scoped.capability is None):
            raise NativeTypeExposurePending('native_type_pack_exact_scope_required')
        self.type_owner._guard()
        return scoped.observation

    def _pack(self, *, mapping_receipt_id: UUID, candidate_version_ids: tuple[UUID, ...],
              relation_receipt_ids: tuple[UUID, ...], observation: NativeTypeExposureSnapshot) -> tuple[UUID, PackSnapshotV2]:
        if observation.exposure is None or observation.snapshot_id is None:
            raise NativeTypeExposurePending(observation.safe_reason)
        scoped = self.type_owner._current_pack_data()
        if scoped is None:
            capability = self.type_owner.resolve_pack(mapping_receipt_id=mapping_receipt_id,
                candidate_version_ids=candidate_version_ids, exposure_snapshot_id=observation.snapshot_id,
                relation_receipt_ids=relation_receipt_ids)
        else:
            self.type_owner._validate_pack_refs(candidate_version_ids, relation_receipt_ids)
            if (scoped.exposure_owner is not self or scoped.observation is not observation
                    or scoped.capability is None or mapping_receipt_id != scoped.mapping_id
                    or set(candidate_version_ids) != set(scoped.versions)
                    or set(relation_receipt_ids) != set(scoped.relation_ids)):
                raise NativeTypeExposurePending('native_type_pack_exact_scope_required')
            capability = scoped.capability
        pack = self.type_owner.require_pack(capability)
        self._lock()
        fence = self.conn.execute("SELECT item_supply_internal.type_exposure_current(%s,%s,%s) AS exposure",
            (observation.snapshot_id, self.user_id, self.epoch)).fetchone()
        # The SQL reconstruction also acquires locks. Its wait must not leave the
        # Python effect check using the earlier clock returned by _lock().
        now = server_clock(self.conn, datetime.now(UTC))
        if fence is None or fence["exposure"] != observation.exposure.model_dump(mode="json"):
            raise NativeTypeExposurePending("native_type_exposure_current_fence_required")
        if (pack.request.learner_id != self.user_id or pack.request.epoch != self.epoch
                or pack.exposure_receipt_hash != observation.exposure.completeness_receipt_hash
                or pack.exposure_watermark != observation.exposure.watermark
                or not pack.checked_at <= now < min(pack.valid_until, observation.exposure.valid_until)):
            raise NativeTypeExposurePending("native_type_pack_current_fence_required")
        _protected(pack, observation.exposure)
        return capability.eligibility_id, pack

    def reserve_assessment(self, *, mapping_receipt_id: UUID, candidate_version_ids: tuple[UUID, ...],
                           relation_receipt_ids: tuple[UUID, ...], operation_key: str) -> UUID:
        self._lock()
        key = stable_key(operation_key, label="native type reservation")
        candidates = _ids(candidate_version_ids, maximum=16)
        relations = _ids(relation_receipt_ids, maximum=16)
        observation = self._effect_observation()
        eligibility_id, pack = self._pack(mapping_receipt_id=mapping_receipt_id,
            candidate_version_ids=candidates, relation_receipt_ids=relations, observation=observation)
        assert observation.exposure is not None
        bindings = [b.model_dump(mode="json") for b in _protected(pack, observation.exposure)]
        request = {"mapping_receipt_id": str(mapping_receipt_id), "candidate_version_ids": [str(v) for v in candidates],
            "relation_receipt_ids": [str(v) for v in relations], "pack_request_hash": pack.request.request_hash,
            "selected_version_ids": sorted(str(c.type_evidence.content.version_id) for c in pack.selected), "bindings": bindings}
        digest = canonical_hash(request)
        row = self.conn.execute("INSERT INTO tutor_item_supply_type_exposure_reservations "
            "(user_id,epoch,scope_id,operation_key,request_hash,request_json,eligibility_id,exposure_snapshot_id,bindings_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,epoch,operation_key) DO NOTHING RETURNING id,request_hash",
            (self.user_id, self.epoch, pack.request.storage_scope_id, key, digest, Jsonb(request), eligibility_id,
             observation.snapshot_id, Jsonb(bindings))).fetchone()
        if row is None:
            row = self.conn.execute("SELECT id,request_hash FROM tutor_item_supply_type_exposure_reservations "
                "WHERE user_id=%s AND epoch=%s AND operation_key=%s", (self.user_id, self.epoch, key)).fetchone()
        if row is None or row["request_hash"] != digest:
            raise NativeTypeExposurePending("native_type_reservation_conflict")
        return UUID(str(row["id"]))

    def prepare_practice_delivery(self, *, reservation_key: str, version_id: UUID, delivery_key: str) -> UUID:
        """Call before the original Artifact writer, in this SAME transaction."""
        self._lock()
        key = stable_key(delivery_key, label="native type practice delivery")
        reserved = self.conn.execute("SELECT * FROM tutor_item_supply_type_exposure_reservations "
            "WHERE user_id=%s AND epoch=%s AND operation_key=%s",
            (self.user_id, self.epoch, stable_key(reservation_key, label="native type reservation"))).fetchone()
        if reserved is None:
            raise NativeTypeExposurePending("native_type_reservation_required")
        request = reserved["request_json"]
        observation = self._effect_observation()
        eligibility_id, pack = self._pack(mapping_receipt_id=UUID(request["mapping_receipt_id"]),
            candidate_version_ids=tuple(UUID(v) for v in request["candidate_version_ids"]),
            relation_receipt_ids=tuple(UUID(v) for v in request["relation_receipt_ids"]), observation=observation)
        assert observation.exposure is not None
        protected = [b.model_dump(mode="json") for b in _protected(pack, observation.exposure)]
        if (pack.request.storage_scope_id != UUID(str(reserved["scope_id"]))
                or pack.request.request_hash != request["pack_request_hash"]
                or sorted(str(c.type_evidence.content.version_id) for c in pack.selected) != request["selected_version_ids"]
                or protected != reserved["bindings_json"]):
            raise NativeTypeExposurePending("native_type_reservation_stale")
        practice = next((c for c in pack.selected if c.member.slot == "practice"
                         and c.type_evidence.content.version_id == version_id), None)
        if practice is None:
            raise NativeTypeExposurePending("native_type_selected_practice_required")
        binding = practice.type_evidence.content.model_dump(mode="json")
        digest = canonical_hash({"reservation_id": str(reserved["id"]), "binding": binding})
        row = self.conn.execute("INSERT INTO tutor_item_supply_type_exposure_deliveries "
            "(id,user_id,epoch,scope_id,reservation_id,version_id,delivery_key,request_hash,binding_json,eligibility_id,exposure_snapshot_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,epoch,delivery_key) DO NOTHING "
            "RETURNING id,request_hash,delivery_txid=txid_current() AS current_tx",
            (uuid4(), self.user_id, self.epoch, reserved["scope_id"], reserved["id"], version_id, key, digest,
             Jsonb(binding), eligibility_id, observation.snapshot_id)).fetchone()
        if row is None:
            row = self.conn.execute("SELECT id,request_hash,delivery_txid=txid_current() AS current_tx "
                "FROM tutor_item_supply_type_exposure_deliveries WHERE user_id=%s AND epoch=%s AND delivery_key=%s",
                (self.user_id, self.epoch, key)).fetchone()
        if row is None or row["request_hash"] != digest or row["current_tx"] is not True:
            raise NativeTypeExposurePending("native_type_delivery_conflict")
        return UUID(str(row["id"]))
