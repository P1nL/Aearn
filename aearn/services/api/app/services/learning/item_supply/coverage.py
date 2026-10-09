"""Pure exact coverage evaluation; caller facts do not establish live authority."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.services.learning.item_bank.contracts import LearningItemKind, LearningItemPurpose, canonical_hash
from app.services.learning.item_supply.contracts import (
    MAX_CANDIDATES,
    AssessmentSupplyDemandV1,
    AssessmentSupplyResultV1,
    CandidateAuthorityV1,
    CoverageBlueprintV1,
    SafeReason,
    Slot,
    SupplyGapV1,
    require_aware,
    revalidate_contract,
)
from app.services.learning.item_supply.exposure import ExposureSnapshotV1, check_exposure
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.runners.language_capabilities import LANGUAGE_CAPABILITIES

_SLOTS: tuple[Slot, ...] = ("practice", "assessment", "remediation")


def _candidate_reason(
    item: CandidateAuthorityV1, demand: AssessmentSupplyDemandV1,
    blueprint: CoverageBlueprintV1, now: datetime,
) -> SafeReason | None:
    scope = demand.scope
    if item.scope != scope:
        return "scope_mismatch"
    if item.slot == "assessment" and (
        scope.item_kind == LearningItemKind.DEMO or scope.purpose == LearningItemPurpose.DEMONSTRATION
    ):
        return "assessment_unsupported"
    if (item.objective_hash != demand.objective_hash or item.blueprint_hash != demand.blueprint_hash
            or item.matrix_hash != demand.matrix_hash or item.policy_version != demand.policy_version):
        return "identity_mismatch"
    if item.visibility == "private" and (
        item.owner_ref != scope.owner_ref or item.owner_ref != demand.learner_ref
    ):
        return "private_owner_mismatch"
    proof = item.proof
    if proof is None:
        return "proof_missing"
    # Actual item facts must agree with proof fields, not merely its digest.
    fields = (
        "item_handle", "content_hash", "candidate_family_id", "objective_hash", "blueprint_hash",
        "matrix_hash", "policy_version", "slot", "source_ref", "source_version", "source_usage",
        "evidence_hash",
    )
    if any(getattr(item, name) != getattr(proof, name) for name in fields):
        return "proof_mismatch"
    if (proof.scope_hash != scope.scope_hash or proof.clauses != item.clauses
            or any(getattr(proof, name) != getattr(scope, name) for name in (
                "runtime_profile_id", "runtime_profile_hash", "assessment_contract_version",
                "scorer_version", "assistance_policy_hash",
            ))):
        return "proof_mismatch"
    clauses = {clause.clause_id: clause.clause_hash for clause in blueprint.clauses}
    if any(clauses.get(clause.clause_id) != clause.clause_hash for clause in proof.clauses):
        return "proof_mismatch"
    auth = item.current_authorization
    if auth is None:
        return "authorization_missing"
    if (any(getattr(auth, name) != getattr(proof, name) for name in (
        "authorization_hash", "source_ref", "source_version", "source_usage", "scope_hash",
        "objective_hash", "content_hash", "evidence_hash",
    )) or auth.checked_at != proof.authorization_checked_at
            or auth.valid_until != proof.authorization_valid_until):
        return "authorization_mismatch"
    if not auth.active:
        return "authorization_inactive"
    if item.slot == "assessment" and item.source_usage != "assessment_evidence":
        return "source_usage_denied"
    if (not proof.checked_at <= now < proof.valid_until
            or not auth.checked_at <= now < auth.valid_until):
        return "stale"
    if not item.published:
        return "not_published"
    if scope.item_kind != LearningItemKind.DEMO and not item.materialized:
        return "not_materialized"
    if not item.runtime_available:
        return "runtime_unavailable"
    if not set(scope.required_capabilities) <= set(item.available_capabilities):
        return "capability_missing"
    return None


def _immutable_identity(item: CandidateAuthorityV1) -> str:
    # Fresh proofs/authorization/runtime observations can change without changing
    # an item. Its exact content, source, scope and coverage claims cannot.
    payload = item.model_dump(mode="json", exclude={
        "proof", "current_authorization", "published", "materialized",
        "runtime_available", "available_capabilities",
    })
    payload["clauses"] = sorted(payload["clauses"], key=lambda clause: clause["clause_id"])
    return canonical_hash(payload)


def _independent_bucket(
    items: list[CandidateAuthorityV1], required: int,
) -> list[CandidateAuthorityV1]:
    # Distinct content and family form a bounded bipartite matching problem.
    # Greedily choosing one collision can hide an otherwise complete inventory.
    by_content: dict[str, dict[str, CandidateAuthorityV1]] = {}
    for item in items:
        by_content.setdefault(item.content_hash, {}).setdefault(item.candidate_family_id, item)
    by_family: dict[str, CandidateAuthorityV1] = {}

    def augment(content_hash: str, visited: set[str]) -> bool:
        for family, item in sorted(by_content[content_hash].items()):
            if family in visited:
                continue
            visited.add(family)
            previous = by_family.get(family)
            if previous is None or augment(previous.content_hash, visited):
                by_family[family] = item
                return True
        return False

    for content_hash in sorted(by_content):
        augment(content_hash, set())
        if len(by_family) == required:
            break
    return sorted(by_family.values(), key=lambda item: item.item_handle)


def evaluate_supply(
    demand: AssessmentSupplyDemandV1,
    blueprint: CoverageBlueprintV1,
    candidates: tuple[CandidateAuthorityV1, ...],
    exposure: ExposureSnapshotV1,
    *,
    now: datetime,
) -> AssessmentSupplyResultV1:
    """Evaluate immutable caller facts without DB, environment, clock or runner IO.

    All inputs are revalidated before graph/set use. Malformed contracts raise a
    fixed ValueError; legitimate mismatches yield bounded safe gaps. Published,
    materialized and authorization facts remain the caller's responsibility.
    Demonstrations never satisfy formal assessment, even with scorer strings;
    planned/unsupported declarations cannot be promoted by runtime booleans.
    """
    try:
        require_aware(now)
        demand = revalidate_contract(demand, AssessmentSupplyDemandV1)
        blueprint = revalidate_contract(blueprint, CoverageBlueprintV1)
        if type(candidates) is not tuple or len(candidates) > MAX_CANDIDATES:
            raise ValueError("invalid candidates")
        items = tuple(revalidate_contract(item, CandidateAuthorityV1) for item in candidates)
        if type(exposure) is not ExposureSnapshotV1:
            raise ValueError("invalid exposure")
        exposure = ExposureSnapshotV1.model_validate(exposure)
        current_matrix_hash = build_support_matrix().matrix_hash
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ValueError("invalid supply input") from None

    reasons: set[SafeReason] = set()
    if demand.scope != blueprint.scope:
        reasons.add("scope_mismatch")
    if (demand.objective_hash != blueprint.objective_hash
            or demand.blueprint_hash != blueprint.blueprint_hash
            or demand.matrix_hash != blueprint.matrix_hash
            or demand.policy_version != blueprint.policy_version
            or blueprint.matrix_hash != current_matrix_hash):
        reasons.add("identity_mismatch")
    if (exposure.learner_ref != demand.learner_ref or exposure.scope_hash != demand.scope.scope_hash):
        reasons.add("exposure_denied")
    if demand.scope.visibility == "private" and demand.scope.owner_ref != demand.learner_ref:
        reasons.add("private_owner_mismatch")
    if LANGUAGE_CAPABILITIES[demand.scope.language_id].capability_state in {"planned", "unsupported"}:
        reasons.add("language_unsupported")
    reject_all = bool(reasons)

    buckets: dict[tuple[str, Slot], list[CandidateAuthorityV1]] = {
        (clause.clause_id, slot): [] for clause in blueprint.clauses for slot in _SLOTS
    }
    # Conflicting immutable identity claims invalidate every copy, not only the
    # last one. Exact replay is deduplicated by each bucket's three identities.
    identities: dict[str, set[str]] = {}
    for item in items:
        identities.setdefault(item.item_handle, set()).add(_immutable_identity(item))
    conflicting = {handle for handle, values in identities.items() if len(values) > 1}
    if not reject_all:
        for item in sorted(items, key=lambda entry: (entry.item_handle, entry.proof.proof_id if entry.proof else "")):
            reason = _candidate_reason(item, demand, blueprint, now)
            if item.item_handle in conflicting:
                reason = "identity_mismatch"
            if reason is not None:
                reasons.add(reason)
                continue
            decision = check_exposure(
                exposure, learner_ref=demand.learner_ref, scope_hash=demand.scope.scope_hash,
                item_handle=item.item_handle, candidate_family_id=item.candidate_family_id,
                independent=item.slot == "assessment",
            )
            if not decision.allowed:
                reasons.add("exposure_denied")
                continue
            for clause in item.clauses:
                buckets[(clause.clause_id, item.slot)].append(item)

    for bucket_key, bucket in buckets.items():
        if any(len({getattr(item, field) for item in bucket}) < len(bucket)
               for field in ("item_handle", "content_hash", "candidate_family_id")):
            reasons.add("duplicate_candidate")
        buckets[bucket_key] = _independent_bucket(bucket, getattr(blueprint.minimum, bucket_key[1]))

    # A child cannot have effective coverage until ALL predecessor slots are
    # satisfied. Propagate blocked prerequisites in topological order.
    completed: set[str] = set()
    satisfied: set[str] = set()
    gaps: list[SupplyGapV1] = []
    selected: set[str] = set()
    pending = {clause.clause_id: clause for clause in blueprint.clauses}
    while pending:
        ready = sorted(key for key, clause in pending.items() if set(clause.prerequisite_clause_ids) <= completed)
        for key in ready:
            objective_clause = pending.pop(key)
            blocked = not set(objective_clause.prerequisite_clause_ids) <= satisfied
            clause_ready = not blocked
            for slot in _SLOTS:
                required = getattr(blueprint.minimum, slot)
                available = 0 if blocked else len(buckets[(key, slot)])
                if available < required:
                    clause_ready = False
                    reason = "prerequisite_gap" if blocked else "insufficient_coverage"
                    gaps.append(SupplyGapV1(
                        clause_id=key, slot=slot, required=required, available=available, reason=reason,
                    ))
                    reasons.add(reason)
                if not blocked:
                    selected.update(item.item_handle for item in buckets[(key, slot)])
            completed.add(key)
            if clause_ready:
                satisfied.add(key)
    status: Literal["ready_exact", "stale", "gap"] = (
        "ready_exact" if not gaps else "stale" if "stale" in reasons else "gap"
    )
    return AssessmentSupplyResultV1(
        status=status, demand_hash=demand.demand_hash, blueprint_hash=blueprint.blueprint_hash,
        selected_handles=tuple(sorted(selected)), gaps=tuple(gaps), reasons=tuple(sorted(reasons)),
    )
