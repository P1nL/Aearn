"""Default-off finite P7 supply service, not a generator, publisher or Gate.

Ready means a fresh original501 capability AND original502 assessment reservation.
Only .learner may be projected to a learner. No JSON capability, proof Boolean,
callback/verifier, private-content relabel or cached ready snapshot is accepted.
An optional concrete persistent owner keeps ONE task; it grants no ready authority.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import replace
from typing import Any, Iterator, Literal, TYPE_CHECKING
from uuid import UUID

from psycopg import Connection

from app.core.config import Settings
from app.services.learning.item_supply.contracts import SupplyGapV1
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
from app.services.learning.item_supply.native_supply_service_contracts import (
    NativeSupplyDemandRef, NativeSupplyFallbackReadyV1, NativeSupplyLearnerStatusV1, NativeSupplyReadyV1,
    NativeSupplyResultV1, SupplyDiagnostic,
)
from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2, _protected
from app.services.learning.item_supply.pack_contracts import CompleteExposureV2, PackCandidateV2, PackInputsV2, PackSnapshotV2
from app.services.learning.item_supply.selection import select_pack

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
    from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService


class _Unavailable(ValueError):
    def __init__(self, diagnostic: SupplyDiagnostic, *,
                 status: Literal["gap", "failed", "stale"] = "stale",
                 gaps: tuple[SupplyGapV1, ...] = ()) -> None:
        super().__init__(diagnostic)
        self.diagnostic, self.status, self.gaps = diagnostic, status, gaps


class NativeSupplyService:
    """One concrete connection/user/epoch/actual496 goal; caller owns transaction.

    enabled only allows attempting original authority resolution; it never makes
    a pack ready. No new root/window/jobs or consumer Artifact/Attempt are written.
    Request memory holds locators only; all three entrypoints do current reads.
    """
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 type_owner: NativeTypeEvidenceOwner, exposure_owner: NativeExposureOwnerV2,
                 mapping_receipt_id: UUID, enabled: bool = False,
                 persistent_owner: PersistentPackTaskOwner | None = None) -> None:
        if (type(type_owner) is not NativeTypeEvidenceOwner or type(exposure_owner) is not NativeExposureOwnerV2
                or type_owner.conn is not conn or exposure_owner.conn is not conn
                or type_owner.settings is not settings or exposure_owner.type_owner is not type_owner
                or (type_owner.user_id, type_owner.epoch) != (exposure_owner.user_id, exposure_owner.epoch)
                or type(mapping_receipt_id) is not UUID or type(enabled) is not bool):
            raise ValueError("native_supply_concrete_same_connection_required")
        self.conn, self.settings = conn, settings
        self.type_owner, self.exposure_owner = type_owner, exposure_owner
        self.mapping_id, self.enabled = mapping_receipt_id, enabled
        self.user_id, self.epoch = type_owner.user_id, type_owner.epoch
        self._requests: dict[UUID, NativeSupplyDemandRef] = {}
        self.persistent_owner = persistent_owner
        self.private_owner: PrivateEnhancementService | None = None
        self._handoff_stack: ExitStack | None = None
        if persistent_owner is not None:
            from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
            if (type(persistent_owner) is not PersistentPackTaskOwner
                    or persistent_owner.conn is not conn or persistent_owner.settings is not settings
                    or persistent_owner.type_owner is not type_owner
                    or persistent_owner.exposure_owner is not exposure_owner):
                raise ValueError("native_supply_persistent_original_owner_required")

    def _guard(self) -> None:
        if not self.enabled:
            raise _Unavailable("disabled", status="failed")
        if (type(self.type_owner) is not NativeTypeEvidenceOwner
                or type(self.exposure_owner) is not NativeExposureOwnerV2
                or self.type_owner.conn is not self.conn or self.exposure_owner.conn is not self.conn
                or self.type_owner.settings is not self.settings
                or self.exposure_owner.type_owner is not self.type_owner
                or (self.type_owner.user_id, self.type_owner.epoch) != (self.user_id, self.epoch)
                or (self.exposure_owner.user_id, self.exposure_owner.epoch) != (self.user_id, self.epoch)):
            raise _Unavailable("current_authority_unavailable")
        # Original guards require non-autocommit INTRANS, READ COMMITTED,
        # actual private epoch/namespace, current source/runtime and feature gates.
        self.type_owner._guard()
        self.exposure_owner._lock()

    @staticmethod
    def _not_ready(diagnostic: SupplyDiagnostic, *,
                   status: Literal["gap", "failed", "stale"] = "stale",
                   gaps: tuple[SupplyGapV1, ...] = (),
                   demand: NativeSupplyDemandRef | None = None) -> NativeSupplyResultV1:
        disabled = diagnostic == "disabled"
        return NativeSupplyResultV1(status=status, diagnostic=diagnostic,
            learner=NativeSupplyLearnerStatusV1(status="unavailable",
                reason="disabled" if disabled else "not_available",
                allowed_actions=() if disabled else ("refresh",)), gaps=gaps,
            enhancement_status="unsupported" if demand is not None and demand.enhancement == "prefer_private" else "not_requested")

    def ensure_supply(self, demand: NativeSupplyDemandRef) -> NativeSupplyResultV1:
        """Resolve original owners; optional persistent work never fabricates ready.

        PRIVATE success and explicit whole-base fallback retain distinct concrete
        capabilities. Only the tiny learner projection is safe to export.
        """
        if type(demand) is NativeSupplyDemandRef and demand.enhancement == "prefer_private":
            return self._enhanced_attempt(demand)
        return self._attempt(demand, reserve=True)

    @contextmanager
    def current_handoff(self, demand: NativeSupplyDemandRef, *, reserve: bool = True
                        ) -> Iterator[NativeSupplyResultV1]:
        """Keep exact original selection/reservation/consumer/Artifact in ONE TOP.

        Yield the existing result DTO. PRIVATE enhancement retains its separate
        original union owner. Never put provider IO or commit inside this scope.
        """
        if self._handoff_stack is not None or type(reserve) is not bool:
            raise ValueError('native_supply_single_lexical_handoff_required')
        with ExitStack() as stack:
            try:
                self._guard()
                mapping = self._mapping(demand)
                old = self._reservation(demand.demand_id)
                if old is not None:
                    prior = self._request_for(demand.demand_id)
                    if ((demand.candidate_version_ids is not None
                            and self._ids(demand.candidate_version_ids) != prior.candidate_version_ids)
                            or (demand.relation_receipt_ids is not None
                            and self._ids(demand.relation_receipt_ids) != prior.relation_receipt_ids)):
                        raise _Unavailable('reservation_conflict')
                    demand = replace(prior, enhancement=demand.enhancement)
                if demand.candidate_version_ids is None and self.persistent_owner is not None:
                    source = self.type_owner._source_binding()
                    task = source.task if source is not None else self.ensure_pack_task(demand)
                    record = self.persistent_owner._task(task)
                    if (task.demand_id, task.mapping_receipt_id, task.user_id, task.epoch) != (
                            demand.demand_id, self.mapping_id, self.user_id, self.epoch):
                        raise _Unavailable('current_authority_unavailable')
                    versions = self.persistent_owner._versions(task)
                    ids = tuple(versions[s.slot].published_version_id for s in record.slots
                        if s.slot in versions and versions[s.slot].published_version_id is not None)
                    if len(ids) == 5:
                        demand = replace(demand, candidate_version_ids=tuple(v for v in ids if v is not None))
                if demand.candidate_version_ids is None:
                    ids, _ = self._candidates(demand, mapping)
                    demand = replace(demand, candidate_version_ids=ids)
                relations = self._relations(demand, mapping)
                demand = replace(demand, candidate_version_ids=self._ids(demand.candidate_version_ids or ()),
                    relation_receipt_ids=self._ids(relations))
                relations = demand.relation_receipt_ids or ()
                if len(demand.candidate_version_ids or ()) >= 5 and relations:
                    stack.enter_context(self.type_owner.current_pack(self.mapping_id,
                        demand.candidate_version_ids or (), relations, self.exposure_owner))
                self._handoff_stack = stack
                self._requests[demand.demand_id] = demand
                result = self._enhanced_attempt(demand) if demand.enhancement == 'prefer_private' else (
                    self._attempt(demand, reserve=reserve))
            except _Unavailable as exc:
                result = self._not_ready(exc.diagnostic, status=exc.status, gaps=exc.gaps, demand=demand)
            except ValueError:
                result = self._not_ready('current_authority_unavailable', demand=demand)
            try:
                yield result
            finally:
                self._handoff_stack = None

    def bind_private_owner(self, owner: PrivateEnhancementService) -> None:
        """Trusted composition only: one concrete PRIVATE owner, no callback port."""
        from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
        if (type(owner) is not PrivateEnhancementService or owner.base_service is not self
                or owner.conn is not self.conn or owner.settings is not self.settings
                or owner.core is not self.persistent_owner
                or self.private_owner is not None):
            raise ValueError("native_supply_private_original_owner_required")
        self.private_owner = owner

    def _enhanced_attempt(self, demand: NativeSupplyDemandRef) -> NativeSupplyResultV1:
        if self.private_owner is None:
            base = self._attempt(demand, reserve=True)
            if base.ready is None:
                return base
            # Public-only authority is not a fresh union-exposure fallback grant.
            return self._not_ready("private_authority_unavailable", demand=demand)
        try:
            from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackIntentV1
            if self.persistent_owner is None:
                raise ValueError("persistent_original_owner_required")
            self._guard()
            # An existing task may continue after its base reservation; no initial
            # adoption/replacement occurs through this original owner lookup.
            if self._reservation(demand.demand_id) is None:
                task = self.ensure_pack_task(demand)
            else:
                existing = self.conn.execute(
                    "SELECT id FROM tutor_item_supply_private_persistent_pack_journal "
                    "WHERE user_id=%s AND epoch=%s AND record_kind='task' "
                    "AND payload_json->'ref'->>'mapping_receipt_id'=%s LIMIT 1",
                    (self.user_id, self.epoch, str(self.mapping_id)),
                ).fetchone()
                if existing is None:
                    return self._not_ready("private_authority_unavailable", demand=demand)
                task = self.persistent_owner.ensure_task(replace(demand, candidate_version_ids=None),
                    PersistentPackIntentV1(enhancement="prefer_private"))
            enhanced = self.private_owner.ensure_supply(demand, task_ref=task)
            if enhanced.ready is not None and enhanced.enhancement_status == "ready":
                self.private_owner.type_owner.require_pack(enhanced.ready.capability)
                return NativeSupplyResultV1(status="ready_exact", diagnostic="exact_private_reserved",
                    learner=enhanced.learner, enhancement_status="ready", private_ready=enhanced.ready)
            return NativeSupplyResultV1(status="pending" if enhanced.learner.status == "preparing" else "stale",
                diagnostic="private_enhancement_preparing" if enhanced.learner.status == "preparing" else
                    "private_authority_unavailable", learner=enhanced.learner,
                enhancement_status="preparing" if enhanced.learner.status == "preparing" else "unavailable")
        except ValueError:
            return self._not_ready("private_authority_unavailable", demand=demand)

    def end_private_wait(self, demand_id: UUID) -> NativeSupplyResultV1:
        """Explicit consumer cancellation, not phase expiry or task cancellation.

        No task or first reservation is created here. Both the retained whole-base
        reservation and a fresh same-transaction union capability must survive
        until the original consumer checks them; this result grants no delivery.
        """
        from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRecord
        self._guard()
        demand = self._request_for(demand_id)
        if (demand.enhancement != "prefer_private" or self.private_owner is None
                or self.persistent_owner is None):
            raise ValueError("native_supply_private_original_owner_required")
        self._mapping(demand)
        retained = self._reservation(demand_id)
        if retained is None:
            raise ValueError("native_supply_original_base_reservation_required")
        existing = self.conn.execute(
            "SELECT payload_json::text AS payload_json FROM tutor_item_supply_private_persistent_pack_journal "
            "WHERE user_id=%s AND epoch=%s AND record_kind='task' "
            "AND payload_json->'ref'->>'mapping_receipt_id'=%s LIMIT 1",
            (self.user_id, self.epoch, str(self.mapping_id)),
        ).fetchone()
        if existing is None:
            raise ValueError("native_supply_existing_persistent_task_required")
        task = PersistentPackTaskRecord.model_validate_json(existing["payload_json"]).ref
        record = self.persistent_owner._task(task)
        if (record.enhancement != "prefer_private"
                or (task.demand_id, task.mapping_receipt_id) != (demand_id, self.mapping_id)):
            raise ValueError("native_supply_same_original_task_demand_required")
        self.private_owner.end_wait(task_ref=task)
        fallback = self.private_owner.fallback(demand, task_ref=task)
        if fallback.fallback is None or fallback.base is None or fallback.base.ready is None:
            return self._not_ready("whole_pack_unavailable", demand=demand)
        if fallback.base.ready.reservation_id != UUID(str(retained["id"])):
            raise ValueError("native_supply_retained_base_reservation_required")
        handoff = NativeSupplyFallbackReadyV1(base=fallback.base.ready,
            whole_base_fallback=fallback.fallback)
        self.require_fallback_ready(handoff)
        return NativeSupplyResultV1(status="ready_exact", diagnostic="exact_whole_base_fallback",
            learner=fallback.learner, enhancement_status="waiting_ended", fallback_ready=handoff)

    def require_fallback_ready(self, handoff: NativeSupplyFallbackReadyV1) -> NativeSupplyReadyV1:
        """Explicit original-consumer handoff; not cached or cross-TX permission.

        Call again in the actual consume/terminal transaction. This wrapper is
        DATA only: both concrete owner capabilities and the retained reservation
        must still be current, even if the facade required them before returning.
        """
        self._guard()
        if (type(handoff) is not NativeSupplyFallbackReadyV1
                or type(handoff.base) is not NativeSupplyReadyV1 or self.private_owner is None):
            raise ValueError("native_supply_explicit_original_fallback_handoff_required")
        union = self.private_owner.require_fallback(handoff.whole_base_fallback)
        base = handoff.base
        pack = self.type_owner.require_pack(base.capability)
        self._mapping(base.demand)
        task = handoff.whole_base_fallback.task_ref
        if ((task.user_id, task.epoch, task.mapping_receipt_id, task.demand_id)
                != (self.user_id, self.epoch, self.mapping_id, base.demand.demand_id)
                or pack.request != union.request or self._bindings(pack) != self._bindings(union)):
            raise ValueError("native_supply_same_task_reserved_whole_base_union_required")
        exposure = handoff.whole_base_fallback.inputs.exposure
        if exposure is None:
            raise ValueError("native_supply_complete_current_union_required")
        reservation = self._verify_reservation(base.demand, pack, exposure)
        if reservation != base.reservation_id or base.reservation_key != self._key(base.demand.demand_id):
            raise ValueError("native_supply_retained_base_reservation_required")
        return base

    def revalidate_supply(self, demand_id: UUID) -> NativeSupplyResultV1:
        """Fresh original owner resolution; never returns an old cached capability."""
        try:
            self._guard()
            demand = self._request_for(demand_id)
            if demand.enhancement == "prefer_private":
                return self._enhanced_attempt(demand)
            return self._attempt(demand, reserve=False)
        except _Unavailable as exc:
            return self._not_ready(exc.diagnostic, status=exc.status, gaps=exc.gaps)
        except ValueError:
            return self._not_ready("current_authority_unavailable")

    def get_supply_status(self, demand_id: UUID) -> NativeSupplyLearnerStatusV1:
        """Safe refresh/reconnect projection; no receipt/goal/hash/handle exposed."""
        return self.revalidate_supply(demand_id).learner

    def ensure_pack_task(self, demand: NativeSupplyDemandRef) -> PersistentPackTaskRef:
        """Internal DATA handoff. No network, new wallet, or ready capability.

        A pre-existing assessment reservation is never replaced or re-adopted.
        Initial discovery chooses only freshly accepted items, explicitly binds
        the five slots, and stops discovering replacements after task creation.
        """
        from app.services.learning.item_supply.persistent_pack_contracts import (
            PersistentPackIntentV1, PersistentPackPending,
        )
        self._guard()
        if self.persistent_owner is None:
            raise PersistentPackPending("persistent_pack_disabled")
        mapping = self._mapping(demand)
        if self._reservation(demand.demand_id) is not None:
            raise PersistentPackPending("existing_reservation_must_not_be_replaced")
        existing = self.conn.execute(
            "SELECT id FROM tutor_item_supply_private_persistent_pack_journal "
            "WHERE user_id=%s AND epoch=%s AND record_kind='task' "
            "AND payload_json->'ref'->>'mapping_receipt_id'=%s LIMIT 1",
            (self.user_id, self.epoch, str(self.mapping_id)),
        ).fetchone()
        if existing is not None:
            # The real owner resolves the confirmed goal and exact task anew;
            # a locator read is not a capability and cannot re-adopt inventory.
            return self.persistent_owner.ensure_task(
                replace(demand, candidate_version_ids=None),
                PersistentPackIntentV1(enhancement=demand.enhancement),
            )
        initial = demand.candidate_version_ids
        if initial is None:
            ids, records = self._candidates(demand, mapping)
            quotas = {"practice": 2, "assessment": 2, "remediation": 1}
            chosen: list[UUID] = []
            for version, record in zip(ids, records, strict=True):
                slot = record.member.slot
                if quotas[slot] > 0:
                    chosen.append(version)
                    quotas[slot] -= 1
            initial = tuple(chosen)
        elif len(initial) > 5:
            raise PersistentPackPending("persistent_initial_five_slot_bound")
        return self.persistent_owner.ensure_task(
            replace(demand, candidate_version_ids=initial),
            PersistentPackIntentV1(enhancement=demand.enhancement),
        )

    def _persistent_pending(self, demand: NativeSupplyDemandRef,
                            gaps: tuple[SupplyGapV1, ...]) -> NativeSupplyResultV1:
        if self.persistent_owner is None:
            return self._not_ready("gap_dispatch_owner_missing" if gaps else
                "relationship_evidence_missing", status="gap", gaps=gaps, demand=demand)
        task = self.ensure_pack_task(demand)
        status = self.persistent_owner.get_status(task)
        if status.status in {"blocked", "paused"}:
            return self._not_ready("persistent_pack_paused" if status.status == "paused" else
                "persistent_pack_blocked", gaps=gaps, demand=demand)
        return NativeSupplyResultV1(status="pending", diagnostic="persistent_pack_preparing",
            learner=NativeSupplyLearnerStatusV1(status="preparing", reason="preparing",
                allowed_actions=("refresh",)), gaps=gaps,
            enhancement_status="unsupported" if demand.enhancement == "prefer_private" else "not_requested")

    def _mapping(self, demand: NativeSupplyDemandRef) -> FiniteCourseMappingReceiptV1:
        if type(demand) is not NativeSupplyDemandRef or demand.mapping_receipt_id != self.mapping_id:
            raise _Unavailable("invalid_request", status="failed")
        mapping = self.type_owner.resolve_mapping(self.mapping_id)
        node, request = mapping.frozen_node, mapping.pack_request
        if ((node.user_id, node.epoch) != (self.user_id, self.epoch)
                or (request.learner_id, request.epoch, request.track_id, request.revision_id, request.node_id)
                != (self.user_id, self.epoch, node.track_id, node.revision_id, node.node_id)
                or not any(entry.demand_id == demand.demand_id for entry in mapping.stored_demands)
                or any(entry.demand.scope.visibility != "private"
                    or entry.demand.scope.owner_ref != "user:" + str(self.user_id)
                    or entry.demand.scope.knowledge_key != node.knowledge_key for entry in request.demands)):
            raise _Unavailable("invalid_request", status="failed")
        # Original496.resolve has re-read its actual stored demands/blueprints,
        # confirmed D/node/active revision/goal and C/claim source authority.
        return mapping

    @staticmethod
    def _key(demand_id: UUID) -> str:
        return "native-supply." + demand_id.hex

    def _reservation(self, demand_id: UUID) -> dict[str, Any] | None:
        return self.conn.execute("SELECT id,scope_id,request_json,bindings_json FROM tutor_item_supply_type_exposure_reservations "
            "WHERE user_id=%s AND epoch=%s AND operation_key=%s",
            (self.user_id, self.epoch, self._key(demand_id))).fetchone()

    def _request_for(self, demand_id: UUID) -> NativeSupplyDemandRef:
        if type(demand_id) is not UUID:
            raise _Unavailable("invalid_request", status="failed")
        prior = self._requests.get(demand_id)
        enhancement = prior.enhancement if prior is not None else "base_only"
        if self.persistent_owner is not None:
            from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRecord
            saved_task = self.conn.execute(
                "SELECT payload_json::text AS payload_json FROM "
                "tutor_item_supply_private_persistent_pack_journal WHERE user_id=%s "
                "AND epoch=%s AND record_kind='task' "
                "AND payload_json->'ref'->>'mapping_receipt_id'=%s LIMIT 1",
                (self.user_id, self.epoch, str(self.mapping_id)),
            ).fetchone()
            if saved_task is not None:
                task = PersistentPackTaskRecord.model_validate_json(saved_task["payload_json"]).ref
                enhancement = self.persistent_owner._task(task).enhancement
        row = self._reservation(demand_id)
        if row is not None:
            refs = row["request_json"]
            # Immutable reservation coordinates are DATA only. Every use below
            # resolves source/pack/owner anew; no eligibility/snapshot JSON restore.
            return NativeSupplyDemandRef(demand_id, UUID(refs["mapping_receipt_id"]),
                tuple(UUID(v) for v in refs["candidate_version_ids"]),
                tuple(UUID(v) for v in refs["relation_receipt_ids"]),
                enhancement)
        return prior or NativeSupplyDemandRef(demand_id, self.mapping_id, enhancement=enhancement)

    @staticmethod
    def _ids(refs: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(refs, key=str))

    def _candidates(self, demand: NativeSupplyDemandRef, mapping: FiniteCourseMappingReceiptV1
                    ) -> tuple[tuple[UUID, ...], tuple[PackCandidateV2, ...]]:
        explicit = demand.candidate_version_ids is not None
        if explicit:
            ids = demand.candidate_version_ids or ()
        else:
            # Discovery is bounded, bodyless public metadata, NOT live authority.
            rows = self.conn.execute("SELECT p.version_id FROM tutor_learning_item_native_publication_proofs p "
                "JOIN tutor_learning_item_versions v ON v.id=p.version_id "
                "JOIN LATERAL(SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=v.id "
                "ORDER BY state_version DESC LIMIT 1) pe ON pe.id=p.publication_event_id AND pe.state='published' "
                "WHERE p.proof_json->>'target_id'=%s ORDER BY p.created_at DESC,p.version_id LIMIT 17",
                (mapping.target_id,)).fetchall()
            if len(rows) > 16:
                raise _Unavailable("inventory_bound_exceeded", status="gap")
            ids = tuple(UUID(str(row["version_id"])) for row in rows)
        records: list[PackCandidateV2] = []
        accepted: list[UUID] = []
        for version in self._ids(ids):
            try:
                content = self.type_owner.resolve_content(version, current=True)
                now, _ = self.type_owner._guard()
                record = self.type_owner._candidate(content, mapping, now)
            except ValueError:
                if explicit:
                    raise _Unavailable("base_invalidated") from None
                # Invalid discovered items are not granted authority or relabelled.
                # Explicit reserved requests NEVER silently replace a stale member.
                continue
            accepted.append(version)
            records.append(record)
        return tuple(accepted), tuple(records)

    def _relations(self, demand: NativeSupplyDemandRef, mapping: FiniteCourseMappingReceiptV1) -> tuple[UUID, ...]:
        if demand.relation_receipt_ids is not None:
            return self._ids(demand.relation_receipt_ids)
        rows = self.conn.execute("SELECT id FROM tutor_item_supply_native_relation_batches "
            "WHERE user_id=%s AND epoch=%s AND mapping_receipt_id=%s AND request_hash=%s "
            "AND checked_at<=clock_timestamp() AND valid_until>clock_timestamp() ORDER BY created_at DESC,id LIMIT 17",
            (self.user_id, self.epoch, self.mapping_id, mapping.pack_request.request_hash)).fetchall()
        if len(rows) > 16:
            raise _Unavailable("inventory_bound_exceeded", status="gap")
        return self._ids(tuple(UUID(str(row["id"])) for row in rows))

    @staticmethod
    def _gaps(mapping: FiniteCourseMappingReceiptV1, records: tuple[PackCandidateV2, ...]) -> tuple[SupplyGapV1, ...]:
        # Quantity diagnostics only, not a new coverage/independence evaluator.
        # Ready always requires original V2 whole-pack/four-role checks below.
        gaps: list[SupplyGapV1] = []
        for entry in mapping.pack_request.demands:
            for clause in entry.blueprint.clauses:
                count = len({r.candidate.content_hash for r in records if r.member.slot == entry.slot
                    and any(c.clause_id == clause.clause_id and c.clause_hash == clause.clause_hash for c in r.candidate.clauses)})
                required = getattr(entry.blueprint.minimum, entry.slot)
                if count < required:
                    gaps.append(SupplyGapV1(clause_id=clause.clause_id, slot=entry.slot,
                        required=required, available=count, reason="insufficient_coverage"))
        return tuple(gaps)

    @staticmethod
    def _bindings(pack: PackSnapshotV2) -> tuple[object, ...]:
        # Ignore fresh observation timestamps/IDs, never immutable item/goal facts.
        return tuple((c.version_id, c.publication_id, c.materialization_id, c.proof_id,
            c.member, c.type_evidence.content, c.candidate.scope, c.candidate.clauses,
            c.candidate.objective_hash, c.candidate.blueprint_hash) for c in pack.selected)

    def _verify_reservation(self, demand: NativeSupplyDemandRef, pack: PackSnapshotV2,
                            exposure: CompleteExposureV2) -> UUID:
        row = self._reservation(demand.demand_id)
        if row is None:
            raise _Unavailable("reservation_required", status="gap")
        refs = row["request_json"]
        protected = [c.model_dump(mode="json") for c in _protected(pack, exposure)]
        if (str(row["scope_id"]) != str(pack.request.storage_scope_id)
                or refs.get("mapping_receipt_id") != str(self.mapping_id)
                or refs.get("candidate_version_ids") != [str(v) for v in demand.candidate_version_ids or ()]
                or refs.get("relation_receipt_ids") != [str(v) for v in demand.relation_receipt_ids or ()]
                or refs.get("pack_request_hash") != pack.request.request_hash
                or refs.get("selected_version_ids") != sorted(str(c.version_id) for c in pack.selected)
                or refs.get("bindings") != protected or row["bindings_json"] != protected):
            raise _Unavailable("reservation_conflict")
        return UUID(str(row["id"]))

    def _attempt(self, demand: NativeSupplyDemandRef, *, reserve: bool) -> NativeSupplyResultV1:
        if type(demand) is not NativeSupplyDemandRef:
            return self._not_ready("invalid_request", status="failed")
        try:
            self._guard()
            scoped = self.type_owner._current_pack_data() if self._handoff_stack is not None else None
            if scoped is not None:
                if (scoped.mapping is None or scoped.inputs is None or scoped.observation is None
                        or scoped.capability is None or scoped.exposure_owner is not self.exposure_owner
                        or demand.mapping_receipt_id != self.mapping_id or self.mapping_id != scoped.mapping_id
                        or demand.candidate_version_ids is not None
                        and self._ids(demand.candidate_version_ids) != scoped.versions
                        or demand.relation_receipt_ids is not None
                        and self._ids(demand.relation_receipt_ids) != scoped.relation_ids):
                    raise _Unavailable('current_authority_unavailable')
                # Exact scoped inputs/mapping are DATA for pure selection only.
                # Reservation and the final handoff still require actual authority.
                mapping = scoped.mapping
            else:
                mapping = self._mapping(demand)
            old = self._reservation(demand.demand_id)
            if old is not None:
                prior = self._request_for(demand.demand_id)
                if ((demand.candidate_version_ids is not None and self._ids(demand.candidate_version_ids) != prior.candidate_version_ids)
                        or (demand.relation_receipt_ids is not None and self._ids(demand.relation_receipt_ids) != prior.relation_receipt_ids)):
                    raise _Unavailable("reservation_conflict")
                demand = replace(prior, enhancement=demand.enhancement)
            # Keep discovery intent as DATA until a real immutable reservation
            # exists. A shortage must be able to observe newly published members
            # on refresh; an explicit/frozen reserved request never changes IDs.
            self._requests[demand.demand_id] = demand
            if old is None and self.persistent_owner is not None and scoped is None:
                task = self.ensure_pack_task(demand)
                task_status = self.persistent_owner.get_status(task)
                if task_status.status != "ready":
                    return self._persistent_pending(demand, ())
                # A created task has fixed five slots. Never rediscover an
                # alternative set merely because later inventory is available.
                demand = replace(demand, candidate_version_ids=task_status.current_version_ids)
            if scoped is not None and scoped.inputs is not None:
                ids, records = self._ids(scoped.versions), scoped.inputs.candidates
                relation_ids = self._ids(scoped.relation_ids)
            else:
                ids, records = self._candidates(demand, mapping)
                relation_ids = self._relations(demand, mapping)
            demand = replace(demand, candidate_version_ids=ids, relation_receipt_ids=relation_ids)
            observation = scoped.observation if scoped is not None else self.exposure_owner.snapshot_v2()
            if observation is None or observation.snapshot_id is None or observation.exposure is None:
                raise _Unavailable("current_authority_unavailable")
            if scoped is not None and scoped.inputs is not None:
                inputs = scoped.inputs
            elif len(ids) < 5 or not relation_ids:
                # Real current issuer DATA + real exposure; no offline contract stub.
                inputs = PackInputsV2(request=mapping.pack_request, candidates=records, exposure=observation.exposure)
            else:
                inputs = self.type_owner._inputs(self.mapping_id, ids, observation.snapshot_id, relation_ids)
            now, _ = self.type_owner._guard()
            selection = select_pack(inputs, now=now)
            if selection.status != "computed_base" or selection.pack is None:
                gaps = self._gaps(mapping, inputs.candidates)
                if old is None and self.persistent_owner is not None:
                    # Preserve discovery intent for initial binding. This owner
                    # runs no HTTP inside the caller's selection transaction.
                    return self._persistent_pending(self._requests[demand.demand_id], gaps)
                diagnostic: SupplyDiagnostic = "gap_dispatch_owner_missing" if gaps else (
                    "relationship_evidence_missing" if not relation_ids else "whole_pack_unavailable")
                raise _Unavailable(diagnostic,
                    status="gap", gaps=gaps)
            # Pure selection is computation only. Original owner separately issues
            # and checks the real same-TX capability; no new ready permission port.
            if scoped is not None and scoped.capability is not None:
                capability = scoped.capability
                pack = capability.snapshot  # DATA comparison, no permission effect.
            else:
                capability = self.type_owner.resolve_pack(self.mapping_id, ids, observation.snapshot_id, relation_ids)
                pack = self.type_owner.require_pack(capability)
            if self._bindings(selection.pack) != self._bindings(pack):
                raise _Unavailable("base_invalidated")
            if reserve:
                self.exposure_owner.reserve_assessment(mapping_receipt_id=self.mapping_id,
                    candidate_version_ids=ids, relation_receipt_ids=relation_ids,
                    operation_key=self._key(demand.demand_id))
            reservation_id = self._verify_reservation(demand, pack, observation.exposure)
            pack = self.type_owner.require_pack(capability)
            self._guard()
            final, _ = self.type_owner._guard()
            if final >= pack.valid_until:
                raise NativeTypeEvidencePending("native_pack_deadline_elapsed")
            selection = selection.model_copy(update={"pack": pack, "valid_until": pack.valid_until})
            return NativeSupplyResultV1(status="ready_exact", diagnostic="exact_base_reserved",
                learner=NativeSupplyLearnerStatusV1(status="ready", reason="available", allowed_actions=("continue",)),
                enhancement_status="unsupported" if demand.enhancement == "prefer_private" else "not_requested",
                ready=NativeSupplyReadyV1(demand, capability, selection, reservation_id, self._key(demand.demand_id)))
        except _Unavailable as exc:
            return self._not_ready(exc.diagnostic, status=exc.status, gaps=exc.gaps, demand=demand)
        except ValueError:
            # Never expose owner/source/provider/SQL exception prose as status.
            # DB transaction failures are not ValueError and must roll back upstream.
            return self._not_ready("current_authority_unavailable", demand=demand)

