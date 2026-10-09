"""Whole native base/enhancement selection, with freshly resolved base fallback."""
from __future__ import annotations

from datetime import datetime
from typing import overload

from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import (
    CrossPoolMappingV1, NativeScopedCandidateV2, PackInputsV1, PackInputsV2, PackSelectionV1, PackSelectionV2,
)
from app.services.learning.item_supply.storage_contracts import checked_model


def _select_pack_v1(base: PackInputsV1, *, now: datetime, enhancement: PackInputsV1 | None = None,
                mapping: CrossPoolMappingV1 | None = None) -> PackSelectionV1:
    base = checked_model(base, PackInputsV1)
    if any(entry.demand.scope.visibility != "public" for entry in base.request.demands):
        raise ValueError("native public base required")
    base_result = build_pack(base, now=now)
    if base_result.snapshot is None:
        return PackSelectionV1(status="unavailable", reasons=base_result.reasons)
    if enhancement is not None:
        enhancement = checked_model(enhancement, PackInputsV1)
        if mapping is not None:
            mapping = checked_model(mapping, CrossPoolMappingV1)
            a, b = base.request, enhancement.request
            compatible = (
                mapping.base_request_hash == a.request_hash and mapping.enhancement_request_hash == b.request_hash
                and mapping.checked_at <= now < mapping.valid_until
                and (a.learner_id, a.epoch, a.track_id, a.revision_id, a.node_id, a.target_definition_hash, a.clause_mapping)
                    == (b.learner_id, b.epoch, b.track_id, b.revision_id, b.node_id, b.target_definition_hash, b.clause_mapping)
                and all(entry.demand.scope.visibility == "private" for entry in b.demands)
                and {entry.slot: entry.demand.scope.model_dump(exclude={"visibility", "owner_ref"}) for entry in a.demands}
                    == {entry.slot: entry.demand.scope.model_dump(exclude={"visibility", "owner_ref"}) for entry in b.demands}
            )
            if compatible:
                result = build_pack(enhancement, now=now)
                if result.snapshot is not None:
                    return PackSelectionV1(status="computed_enhancement", pack=result.snapshot,
                        cross_pool_mapping_hash=mapping.mapping_receipt_hash,
                        valid_until=min(result.snapshot.valid_until, mapping.valid_until))
    # Callers supply a newly resolved base, not a previous selected snapshot.
    # Failed/expired/missing enhancement cannot make a stale base selectable.
    return PackSelectionV1(status="computed_base", pack=base_result.snapshot, valid_until=base_result.snapshot.valid_until)


@overload
def select_pack(base: PackInputsV1, *, now: datetime, enhancement: PackInputsV1 | PackInputsV2 | None = None,
                mapping: CrossPoolMappingV1 | None = None) -> PackSelectionV1: ...


@overload
def select_pack(base: PackInputsV2, *, now: datetime, enhancement: PackInputsV2 | PackInputsV1 | None = None,
                mapping: CrossPoolMappingV1 | None = None) -> PackSelectionV2: ...


def select_pack(base: PackInputsV1 | PackInputsV2, *, now: datetime,
                enhancement: PackInputsV1 | PackInputsV2 | None = None,
                mapping: CrossPoolMappingV1 | None = None) -> PackSelectionV1 | PackSelectionV2:
    if type(base) is PackInputsV2:
        return _select_pack_v2(base, now=now, enhancement=enhancement, mapping=mapping)
    # Never reinterpret a V2 enhancement as legacy family evidence. Both version
    # directions retain the freshly computed whole base as their safe fallback.
    if type(enhancement) is PackInputsV2:
        enhancement = None
    if not isinstance(base, PackInputsV1) or (enhancement is not None and not isinstance(enhancement, PackInputsV1)):
        raise ValueError("invalid pack selection version")
    base = checked_model(base, PackInputsV1)
    legacy_enhancement = checked_model(enhancement, PackInputsV1) if enhancement is not None else None
    return _select_pack_v1(base, now=now, enhancement=legacy_enhancement, mapping=mapping)


def _select_pack_v2(base: PackInputsV2, *, now: datetime,
                    enhancement: PackInputsV1 | PackInputsV2 | None = None,
                    mapping: CrossPoolMappingV1 | None = None) -> PackSelectionV2:
    base = checked_model(base, PackInputsV2)
    if any(entry.demand.scope.visibility != "public" for entry in base.request.demands):
        request = base.request
        # Only explicitly mapped PUBLIC content can serve as a public base in
        # this private learning context. Ordinary private items remain denied.
        if not base.candidates or not all(
                isinstance(r.candidate, NativeScopedCandidateV2)
                and r.candidate.visibility == "public" and r.owner_id is None and r.epoch is None
                and r.candidate.learner_id == request.learner_id and r.candidate.epoch == request.epoch
                and r.candidate.course_mapping_hash == request.course_mapping_hash
                and r.candidate.scope.owner_ref == "user:" + str(request.learner_id)
                for r in base.candidates):
            raise ValueError("native public base required")
    base_result = build_pack(base, now=now)
    if base_result.snapshot is None:
        return PackSelectionV2(status="unavailable", reasons=base_result.reasons)
    # Cross-version enhancement is not reinterpreted as V2 evidence; a newly
    # resolved current base remains the whole fallback, not a mixed item set.
    if type(enhancement) is PackInputsV2 and mapping is not None:
        enhancement = checked_model(enhancement, PackInputsV2)
        mapping = checked_model(mapping, CrossPoolMappingV1)
        a, b = base.request, enhancement.request
        compatible = (
            mapping.base_request_hash == a.request_hash and mapping.enhancement_request_hash == b.request_hash
            and mapping.checked_at <= now < mapping.valid_until
            and (a.learner_id, a.epoch, a.track_id, a.revision_id, a.node_id, a.target_definition_hash, a.clause_mapping)
                == (b.learner_id, b.epoch, b.track_id, b.revision_id, b.node_id, b.target_definition_hash, b.clause_mapping)
            and all(entry.demand.scope.visibility == "private" for entry in b.demands)
            # A different/empty enhancement ledger cannot erase already-known
            # learner exposures, even while both observation TTLs are current.
            and base.exposure == enhancement.exposure
            and {entry.slot: entry.demand.scope.model_dump(exclude={"visibility", "owner_ref"}) for entry in a.demands}
                == {entry.slot: entry.demand.scope.model_dump(exclude={"visibility", "owner_ref"}) for entry in b.demands}
        )
        if compatible:
            result = build_pack(enhancement, now=now)
            if result.snapshot is not None:
                return PackSelectionV2(status="computed_enhancement", pack=result.snapshot,
                    cross_pool_mapping_hash=mapping.mapping_receipt_hash,
                    valid_until=min(result.snapshot.valid_until, mapping.valid_until))
    return PackSelectionV2(status="computed_base", pack=base_result.snapshot,
        valid_until=base_result.snapshot.valid_until)
