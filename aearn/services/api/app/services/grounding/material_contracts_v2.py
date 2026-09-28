"""D internal whole-draft material selection and exact evidence contracts.

Hashes prove deterministic identity, never source authenticity or current authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.services.grounding.autonomous.contracts import (
    FrozenContract, LearningMaterialDemand, RagEvidenceBinding, Usage, revalidate,
)

_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_HASH = r"^[0-9a-f]{64}$"
_KEY = r"^[a-z0-9][a-z0-9._:-]{0,159}$"
_HANDLE = r"^selection\.[0-9a-f]{32}$"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


class DraftScope(FrozenContract):
    user_id: str = Field(pattern=_UUID)
    conversation_id: str = Field(pattern=_UUID)
    session_id: str = Field(pattern=_UUID)
    draft_id: str = Field(pattern=_UUID)
    draft_version: int = Field(ge=1)
    content_hash: str = Field(pattern=_HASH)
    source_run_id: str = Field(pattern=_UUID)
    source_input_revision: int = Field(ge=1)


class NodeMaterialRequirement(FrozenContract):
    node_id: str = Field(pattern=_KEY)
    goal_hash: str = Field(pattern=_HASH)
    prerequisites: tuple[str, ...] = Field(default=(), max_length=64)
    demand: LearningMaterialDemand

    @model_validator(mode="after")
    def coherent(self) -> NodeMaterialRequirement:
        demand = revalidate(self.demand, LearningMaterialDemand)
        if (len(set(self.prerequisites)) != len(self.prerequisites)
                or self.node_id in self.prerequisites
                or any(re.fullmatch(_KEY, key) is None for key in self.prerequisites)
                or demand.node_ref != f"node.{self.node_id}"):
            raise ValueError("node demand does not match server plan")
        return self


class EvidenceCoordinate(FrozenContract):
    """One exact C-admitted chunk; no body, URL, or caller-defined SQL."""
    binding: RagEvidenceBinding
    subject_id: str = Field(pattern=r"^[a-z][a-z0-9.-]{2,99}$")
    corpus_version_id: str = Field(pattern=_UUID)
    active_generation: int = Field(ge=1)
    summary_hash: str = Field(pattern=_HASH)
    validation_hash: str = Field(pattern=_HASH)
    registry_digest: str = Field(pattern=_HASH)
    source_review_id: str = Field(pattern=_UUID)
    source_policy_id: str = Field(pattern=_KEY)
    source_policy_generation: int = Field(ge=1)
    chunk_id: str = Field(pattern=_KEY)
    chunk_hash: str = Field(pattern=_HASH)
    approved_excerpt_hash: str = Field(pattern=_HASH)
    retrieval_hash: str = Field(pattern=_HASH)
    coverage_hash: str = Field(pattern=_HASH)
    claim_id: str | None = Field(default=None, pattern=_KEY)
    claim_receipt_hash: str | None = Field(default=None, pattern=_HASH)
    corroboration_id: str | None = Field(default=None, pattern=_KEY)
    execution_receipt_id: str | None = Field(default=None, pattern=_KEY)

    @model_validator(mode="after")
    def coherent(self) -> EvidenceCoordinate:
        binding = revalidate(self.binding, RagEvidenceBinding)
        if self.subject_id != binding.scope.subject_id:
            raise ValueError("corpus subject differs from A binding")
        if binding.purpose == "assessment_evidence":
            if not (binding.claim_receipt_id and self.claim_id and self.claim_receipt_hash
                    and (self.corroboration_id or self.execution_receipt_id)):
                raise ValueError("assessment requires exact independent claim evidence")
        elif any((self.claim_id, self.claim_receipt_hash, self.corroboration_id,
                  self.execution_receipt_id, binding.claim_receipt_id)):
            raise ValueError("claim evidence cannot be laundered into teaching")
        return self


class MaterialSelectionEntry(FrozenContract):
    node_id: str = Field(pattern=_KEY)
    goal_hash: str = Field(pattern=_HASH)
    purpose: Usage
    status: Literal["disabled", "pending", "gap", "partial", "ready"]
    covered_facets: tuple[str, ...] = Field(default=(), max_length=24)
    gaps: tuple[Literal["missing_material", "insufficient_coverage", "prerequisite_blocked",
                        "source_stale", "usage_denied", "claim_unverified", "existing_only"], ...] = Field(default=(), max_length=16)
    evidence: tuple[EvidenceCoordinate, ...] = Field(default=(), max_length=12)
    preparation_job_id: str | None = Field(default=None, pattern=_UUID)

    @model_validator(mode="after")
    def coherent(self) -> MaterialSelectionEntry:
        if (len(set(self.covered_facets)) != len(self.covered_facets)
                or len(set(self.gaps)) != len(self.gaps)
                or len({digest(e.model_dump(mode="json")) for e in self.evidence}) != len(self.evidence)
                or self.status == "ready" and (self.gaps or not self.evidence)
                or self.status != "ready" and not self.gaps and self.status != "disabled"
                or (self.status == "pending") != (self.preparation_job_id is not None)
                or self.status == "disabled" and (self.evidence or self.covered_facets)
                or any(revalidate(e, EvidenceCoordinate).binding.purpose != self.purpose
                       for e in self.evidence)):
            raise ValueError("incoherent material selection entry")
        return self


def apply_material_dependencies(
    requirements: tuple[NodeMaterialRequirement, ...],
    entries: tuple[MaterialSelectionEntry, ...],
) -> tuple[MaterialSelectionEntry, ...]:
    """Normalize whole-draft readiness against the main-teaching prerequisite DAG.

    Both input sequences may be independently ordered. The returned entries follow
    requirements order, so callers can pair them without relying on resolver order.
    """
    reqs = [revalidate(req, NodeMaterialRequirement) for req in requirements]
    items = [revalidate(entry, MaterialSelectionEntry) for entry in entries]
    req_by_key = {(r.node_id, r.goal_hash, r.demand.purpose): r for r in reqs}
    item_by_key = {(e.node_id, e.goal_hash, e.purpose): e for e in items}
    if (not reqs or len(req_by_key) != len(reqs)
            or len(item_by_key) != len(items) or req_by_key.keys() != item_by_key.keys()):
        raise ValueError("material requirements and entries must match exactly")

    graph: dict[str, tuple[str, ...]] = {}
    goals: dict[str, str] = {}
    for req in reqs:
        if (req.node_id in graph and graph[req.node_id] != req.prerequisites
                or req.node_id in goals and goals[req.node_id] != req.goal_hash):
            raise ValueError("inconsistent material node prerequisites or goal")
        graph[req.node_id] = req.prerequisites
        goals[req.node_id] = req.goal_hash

    visited: set[str] = set()
    active: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in active:
            raise ValueError("cyclic material prerequisite graph")
        if node_id in visited:
            return
        active.add(node_id)
        for parent in graph[node_id]:
            if parent not in graph:
                raise ValueError("unknown material prerequisite node")
            visit(parent)
        active.remove(node_id)
        visited.add(node_id)

    for node_id in graph:
        visit(node_id)

    main_ready = {e.node_id for e in items
                  if e.purpose == "main_teaching" and e.status == "ready"}
    effective: dict[str, bool] = {}

    def ready(node_id: str) -> bool:
        if node_id not in effective:
            effective[node_id] = node_id in main_ready and all(
                ready(parent) for parent in graph[node_id]
            )
        return effective[node_id]

    result: list[MaterialSelectionEntry] = []
    for req in reqs:
        entry = item_by_key[(req.node_id, req.goal_hash, req.demand.purpose)]
        if any(not ready(parent) for parent in req.prerequisites):
            gaps = entry.gaps
            if "prerequisite_blocked" not in gaps:
                gaps += ("prerequisite_blocked",)
            entry = MaterialSelectionEntry.model_validate(entry.model_copy(update={
                "status": "gap", "gaps": gaps, "preparation_job_id": None,
            }).model_dump(mode="python"))
        result.append(entry)
    return tuple(result)


class MaterialSelectionResult(FrozenContract):
    contract_version: Literal["rag_d_selection_v2"] = "rag_d_selection_v2"
    handle: str = Field(pattern=_HANDLE)
    draft: DraftScope
    requirements: tuple[NodeMaterialRequirement, ...] = Field(min_length=1, max_length=128)
    entries: tuple[MaterialSelectionEntry, ...] = Field(min_length=1, max_length=128)
    selection_digest: str = Field(pattern=_HASH)

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"selection_digest"})

    @model_validator(mode="after")
    def coherent(self) -> MaterialSelectionResult:
        scope = revalidate(self.draft, DraftScope)
        requirements = [revalidate(r, NodeMaterialRequirement) for r in self.requirements]
        entries = [revalidate(e, MaterialSelectionEntry) for e in self.entries]
        normalized = apply_material_dependencies(self.requirements, self.entries)
        keys = [(r.node_id, r.goal_hash, r.demand.purpose) for r in requirements]
        if (len(set(keys)) != len(keys)
                or set(keys) != {(e.node_id, e.goal_hash, e.purpose) for e in entries}
                or len(keys) != len(entries)
                or any(r.demand.draft_revision != scope.draft_version
                       or r.demand.plan_ref != f"draft.{scope.draft_id}"
                       for r in requirements)
                or any(set(e.covered_facets) - set(r.demand.scope.facets)
                       or e.status == "ready" and set(e.covered_facets) != set(r.demand.scope.facets)
                       or any(c.binding.scope != r.demand.scope
                              or c.binding.demand_hash != r.demand.demand_hash
                              for c in e.evidence)
                       for r in requirements for e in entries
                       if (r.node_id, r.goal_hash, r.demand.purpose)
                          == (e.node_id, e.goal_hash, e.purpose))
                or {(e.node_id, e.goal_hash, e.purpose): e for e in entries}
                   != {(e.node_id, e.goal_hash, e.purpose): e for e in normalized}
                or digest(self.payload()) != self.selection_digest):
            raise ValueError("selection scope or digest mismatch")
        return self


class EvidenceBindingV2(FrozenContract):
    contract_version: Literal["rag_d_binding_v2"] = "rag_d_binding_v2"
    selection_handle: str = Field(pattern=_HANDLE)
    selection_digest: str = Field(pattern=_HASH)
    draft: DraftScope
    node_id: str = Field(pattern=_KEY)
    goal_hash: str = Field(pattern=_HASH)
    purpose: Usage
    evidence: tuple[EvidenceCoordinate, ...] = Field(min_length=1, max_length=12)
    binding_digest: str = Field(pattern=_HASH)

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"binding_digest"})

    @model_validator(mode="after")
    def coherent(self) -> EvidenceBindingV2:
        revalidate(self.draft, DraftScope)
        coords = [revalidate(e, EvidenceCoordinate) for e in self.evidence]
        if (len({digest(e.model_dump(mode="json")) for e in coords}) != len(coords)
                or tuple(sorted(coords, key=lambda e: digest(e.model_dump(mode="json")))) != tuple(coords)
                or any(e.binding.purpose != self.purpose for e in coords)
                or digest(self.payload()) != self.binding_digest):
            raise ValueError("binding evidence or digest mismatch")
        return self


class MaterialFeedbackRef(FrozenContract):
    selection_handle: str = Field(pattern=_HANDLE)
    selection_digest: str = Field(pattern=_HASH)
    draft: DraftScope
    target_run_id: str = Field(pattern=_UUID)
    target_input_revision: int = Field(ge=1)
    expected_session_version: int = Field(ge=1)
    assignment_digest: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def coherent(self) -> MaterialFeedbackRef:
        revalidate(self.draft, DraftScope)
        if digest(self.model_dump(mode="json", exclude={"assignment_digest"})) != self.assignment_digest:
            raise ValueError("feedback assignment digest mismatch")
        return self


MaterialFeedbackAssignment = MaterialFeedbackRef


class CurrentMaterialAuthorizationReceipt(FrozenContract):
    """Same-transaction P2 verification result, bound to this exact request.

    No signature or independent grant: the injected trusted adapter must verify C
    current authority and issue this after its final current read.
    """
    kind: Literal["selection", "binding"]
    object_digest: str = Field(pattern=_HASH)
    draft: DraftScope
    purposes: tuple[Usage, ...] = Field(min_length=1, max_length=3)
    authorization_digest: str = Field(pattern=_HASH)
    checked_at: datetime

    @model_validator(mode="after")
    def coherent(self) -> CurrentMaterialAuthorizationReceipt:
        revalidate(self.draft, DraftScope)
        if (self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None
                or tuple(sorted(set(self.purposes))) != self.purposes):
            raise ValueError("authorization receipt scope is invalid")
        return self
