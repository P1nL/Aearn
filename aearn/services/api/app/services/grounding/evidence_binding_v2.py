"""D exact material selection over the sole active formal corpus.

No staging, B search, network or fixture shadow is consulted. A missing C current
review is a gap; it never becomes a synthetic ready recommendation.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Any
from uuid import uuid4

from psycopg import Connection

from app.services.grounding.autonomous.access_policy import (
    AccessRequest, AuthorityResolver, AutonomousGates, check_access,
)
from app.services.grounding.autonomous.contracts import (
    RagEvidenceBinding, revalidate,
)
from app.services.grounding.autonomous.corpus_governance import CorpusGovernance
from app.services.grounding.autonomous.source_policy import authorize_binding
from app.services.grounding.corpus_repository import _hash
from app.services.grounding.material_binding_repository import PostgresMaterialBindingRepository
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceBindingV2, EvidenceCoordinate, MaterialSelectionEntry,
    MaterialSelectionResult, NodeMaterialRequirement, apply_material_dependencies, digest,
)
from app.services.grounding.current_authorization import (
    AuthorizationReceipt, CurrentAuthorization, EvidenceDenied, project_covered_facets,
)

RequestFor = Callable[[NodeMaterialRequirement], AccessRequest]


class EvidenceSelection(CurrentAuthorization):
    """Bound D port; scope/actor demands originate from server-side plan authority."""

    def __init__(self, conn: Connection[dict[str, Any]], *, governance: CorpusGovernance,
                 request_for: RequestFor,
                 selections: PostgresMaterialBindingRepository | None = None,
                 gates: AutonomousGates | None = None,
                 authority_resolver: AuthorityResolver | None = None,
                 enabled: bool = False) -> None:
        super().__init__(conn, governance=governance, gates=gates,
                         authority_resolver=authority_resolver, enabled=enabled)
        self.request_for = request_for
        self.selections = selections

    def resolve(self, conn: Connection[dict[str, Any]],
                requirement: NodeMaterialRequirement,
                draft: DraftScope) -> MaterialSelectionEntry:
        """Learning-facing one-node projection, never authoritative by itself."""
        if conn is not self.conn:
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self.require_transaction()
        scope = revalidate(draft, DraftScope)
        req = revalidate(requirement, NodeMaterialRequirement)
        if (req.demand.draft_revision != scope.draft_version
                or req.demand.plan_ref != f"draft.{scope.draft_id}"):
            raise EvidenceDenied("DRAFT_REVISION_STALE")
        return self._select(req)

    def resolve_evidence(self, draft_scope: DraftScope,
                         requirements: Sequence[NodeMaterialRequirement], *,
                         handle: str | None = None) -> MaterialSelectionResult:
        self.require_transaction()
        draft = revalidate(draft_scope, DraftScope)
        reqs = tuple(revalidate(r, NodeMaterialRequirement) for r in requirements)
        if not reqs or len(reqs) > 128:
            raise EvidenceDenied("EVIDENCE_INSUFFICIENT")
        entries = apply_material_dependencies(
            reqs, tuple(self.resolve(self.conn, r, draft) for r in reqs),
        )
        payload = dict(handle=handle or f"selection.{uuid4().hex}", draft=draft,
                       requirements=reqs, entries=entries)
        raw = MaterialSelectionResult.model_construct(selection_digest="0" * 64, **payload)  # type: ignore[arg-type]
        return MaterialSelectionResult.model_validate({**payload,
            "selection_digest": digest(raw.payload())})

    def _select(self, requirement: NodeMaterialRequirement) -> MaterialSelectionEntry:
        demand = requirement.demand
        key = dict(node_id=requirement.node_id, goal_hash=requirement.goal_hash,
                   purpose=demand.purpose)
        # Assessment cannot pass C's per-claim independent port yet, regardless
        # of a source's historical admission or a SQL claim_receipt row.
        if demand.purpose == "assessment_evidence":
            return MaterialSelectionEntry.model_validate({**key, "status": "gap", "gaps": ("claim_unverified",)})
        try:
            request = self.request_for(requirement)
            if (request.demand_hash != demand.demand_hash or request.scope != demand.scope
                    or request.purpose != demand.purpose or request.action != "consume"):
                raise EvidenceDenied("BINDING_MISMATCH")
            # Pointer is read without lock here; version is locked before final
            # pointer FOR SHARE. A changed pointer is rejected below.
            active = self.governance.repo.active(demand.scope.subject_id)
            if active is None:
                return MaterialSelectionEntry.model_validate({**key, "status": "gap", "gaps": ("missing_material",)})
            version = self.governance.repo.version(active.corpus_id, for_share=True)
            if (version.state != "published" or version.summary_hash is None
                    or version.subject_id != demand.scope.subject_id
                    or version.subject_version != demand.scope.subject_version):
                return MaterialSelectionEntry.model_validate({**key, "status": "gap", "gaps": ("source_stale",)})
            self.governance._verified(active.corpus_id, summary_hash=version.summary_hash,
                                      purpose=demand.purpose, consumption_read=True)
            _, rows = self.governance._rows(active.corpus_id, consumption_read=True)
            chunks = self.conn.execute(
                "SELECT chunk_id,chunk_hash,content,facets_json,document_id FROM grounding_corpus_chunks "
                "WHERE corpus_version_id=%s ORDER BY document_id,chunk_id FOR SHARE",
                (active.corpus_id,),
            ).fetchall()
            pointer = self.conn.execute(
                "SELECT corpus_version_id,generation,activation_event_id "
                "FROM grounding_active_corpora WHERE subject_id=%s FOR SHARE",
                (version.subject_id,),
            ).fetchone()
            if (pointer is None or pointer["corpus_version_id"] != active.corpus_id
                    or pointer["generation"] != active.generation
                    or pointer["activation_event_id"] != active.activation_event_id):
                return MaterialSelectionEntry.model_validate({**key, "status": "gap", "gaps": ("source_stale",)})
            reviews = self.governance.source_reviews
            if reviews is None:
                raise EvidenceDenied("AUTHORITY_MISSING")
            current: list[EvidenceCoordinate] = []
            for row in rows:
                if (row["reading_level"] != demand.reading_level
                        or demand.purpose not in row["admitted_usages"]
                        or not set(demand.scope.facets) <= set(row["review_facets"])):
                    continue
                source = self._source_view(
                    row["source_handle"], row["document_handle"],
                    demand.scope, demand.purpose,
                )
                if (source is None or source.review_id != str(row["review_id"])):
                    continue
                binding = RagEvidenceBinding(
                    scope=demand.scope, demand_hash=demand.demand_hash,
                    purpose=demand.purpose, source_handle=row["source_handle"],
                    document_handle=row["document_handle"],
                    document_revision=row["document_revision"],
                    document_hash=row["reviewed_hash"],
                    admission_receipt_id=row["receipt_handle"],
                )
                allowed = authorize_binding(
                    binding, source.assessment, request=request, gates=self.gates,
                    authority_resolver=self.authority_resolver,
                    source_resolver=source, now=self._clock(),
                )
                if not allowed.allowed:
                    continue
                for chunk in chunks:
                    if chunk["document_id"] != row["document_id"]:
                        continue
                    facets = tuple(chunk["facets_json"])
                    if not set(facets) & set(demand.scope.facets):
                        continue
                    current.append(EvidenceCoordinate(
                        binding=binding, subject_id=version.subject_id,
                        corpus_version_id=str(active.corpus_id),
                        active_generation=active.generation,
                        summary_hash=version.summary_hash,
                        validation_hash=_hash(version.validation_summary),
                        registry_digest=version.registry_digest,
                        source_review_id=str(row["review_id"]),
                        source_policy_id=row["policy_id"],
                        source_policy_generation=row["review_generation"],
                        chunk_id=chunk["chunk_id"], chunk_hash=chunk["chunk_hash"],
                        approved_excerpt_hash=hashlib.sha256(chunk["content"].encode()).hexdigest(),
                        retrieval_hash=digest(version.retrieval_policy_version),
                        coverage_hash=_hash(version.coverage_summary),
                    ))
            # Final C current-use/expiry check after any pointer wait.
            self.governance._verified(active.corpus_id, summary_hash=version.summary_hash,
                                      purpose=demand.purpose, consumption_read=True)
            selected = tuple(current[:12])
            selected_ids = {coord.chunk_id for coord in selected}
            selected_facets = project_covered_facets(
                demand.scope.facets,
                [chunk["facets_json"] for chunk in chunks if chunk["chunk_id"] in selected_ids],
            )
            missing = set(demand.scope.facets) - set(selected_facets)
            if not selected:
                return MaterialSelectionEntry.model_validate({**key, "status": "gap", "gaps": ("missing_material",)})
            if missing or len(current) > 12:
                return MaterialSelectionEntry.model_validate({**key, "status": "partial",
                                              "covered_facets": selected_facets,
                                              "gaps": ("insufficient_coverage",), "evidence": selected})
            return MaterialSelectionEntry.model_validate({**key, "status": "ready",
                                          "covered_facets": selected_facets, "evidence": selected})
        except EvidenceDenied:
            raise
        except Exception:
            # C verifier/DB failure must never produce a ready recommendation.
            return MaterialSelectionEntry.model_validate({**key, "status": "gap", "gaps": ("source_stale",)})

    def authorize_selection(self, conn: Connection[dict[str, Any]],
                            selection: MaterialSelectionResult) -> CurrentMaterialAuthorizationReceipt:
        if conn is not self.conn:
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self.require_transaction()
        item = revalidate(selection, MaterialSelectionResult)
        receipts: list[AuthorizationReceipt] = []
        for requirement, entry in zip(item.requirements, item.entries, strict=True):
            request = self.request_for(requirement)
            if (request.demand_hash != requirement.demand.demand_hash
                    or request.scope != requirement.demand.scope
                    or request.purpose != requirement.demand.purpose
                    or request.action != "consume"):
                raise EvidenceDenied("BINDING_MISMATCH")
            if not check_access(request, gates=self.gates, resolver=self.authority_resolver,
                                now=self._clock(), demand=requirement.demand).allowed:
                raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE")
            if (entry.status == "ready" and (not entry.evidence or
                    set(entry.covered_facets) != set(requirement.demand.scope.facets))):
                raise EvidenceDenied("EVIDENCE_INSUFFICIENT")
            if entry.evidence:
                if requirement.demand.purpose == "assessment_evidence":
                    raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
                payload = dict(selection_handle=item.handle,
                               selection_digest=item.selection_digest, draft=item.draft,
                               node_id=entry.node_id, goal_hash=entry.goal_hash,
                               purpose=entry.purpose,
                               evidence=tuple(sorted(entry.evidence,
                                   key=lambda e: digest(e.model_dump(mode="json")))))
                unsigned = EvidenceBindingV2.model_construct(
                    binding_digest="0" * 64, **payload,  # type: ignore[arg-type]
                )
                binding = EvidenceBindingV2.model_validate({**payload,
                    "binding_digest": digest(unsigned.payload())})
                receipt = self.check_current_authorization(
                    binding, entry.purpose, request=request,
                )
                if set(entry.covered_facets) != set(receipt.covered_facets):
                    raise EvidenceDenied("EVIDENCE_INSUFFICIENT")
                receipts.append(receipt)
        checked_at = self._clock()
        return CurrentMaterialAuthorizationReceipt(
            kind="selection", object_digest=item.selection_digest,
            draft=item.draft,
            purposes=tuple(sorted({r.demand.purpose for r in item.requirements})),
            authorization_digest=digest([(r.binding_digest, r.corpus_version_id, r.active_generation,
                    r.exact_evidence_digest, r.covered_facets, r.source_policy_generations,
                    r.admission_receipt_ids, r.original_source_digests,
                    r.checked_at.isoformat()) for r in receipts]
                    or [item.selection_digest, "scope_only_no_source_claim"]), checked_at=checked_at,
        )

    def authorize_binding(self, conn: Connection[dict[str, Any]],
                          binding: EvidenceBindingV2) -> CurrentMaterialAuthorizationReceipt:
        if conn is not self.conn:
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self.require_transaction()  # Closed gate must not read the selection repository.
        item = revalidate(binding, EvidenceBindingV2)
        if self.selections is None or self.selections.conn is not self.conn:
            raise EvidenceDenied("AUTHORITY_MISSING")
        selection = self.selections.get_selection(handle=item.selection_handle, draft=item.draft)
        if item.selection_digest != selection.selection_digest:
            raise EvidenceDenied("BINDING_MISMATCH")
        matches = [(r, e) for r, e in zip(selection.requirements, selection.entries, strict=True)
                   if (r.node_id, r.goal_hash, r.demand.purpose) ==
                      (item.node_id, item.goal_hash, item.purpose)]
        if len(matches) != 1 or matches[0][1].status != "ready" or (
                tuple(sorted(matches[0][1].evidence,
                             key=lambda e: digest(e.model_dump(mode="json")))) != item.evidence):
            raise EvidenceDenied("BINDING_MISMATCH")
        request = self.request_for(matches[0][0])
        receipt = self.check_current_authorization(item, item.purpose, request=request)
        if (set(receipt.covered_facets) != set(matches[0][0].demand.scope.facets)
                or set(receipt.covered_facets) != set(matches[0][1].covered_facets)):
            raise EvidenceDenied("EVIDENCE_INSUFFICIENT")
        return CurrentMaterialAuthorizationReceipt(
            kind="binding", object_digest=item.binding_digest,
            draft=item.draft, purposes=(item.purpose,),
            authorization_digest=digest((receipt.binding_digest, receipt.corpus_version_id,
                receipt.active_generation, receipt.exact_evidence_digest,
                receipt.covered_facets,
                receipt.source_policy_generations, receipt.admission_receipt_ids,
                receipt.original_source_digests,
                receipt.checked_at.isoformat())), checked_at=receipt.checked_at,
        )

    def freeze_binding(self, selection: MaterialSelectionResult, *, node_id: str,
                       goal_hash: str, purpose: str, request: AccessRequest) -> tuple[EvidenceBindingV2, AuthorizationReceipt]:
        self.require_transaction()
        result = revalidate(selection, MaterialSelectionResult)
        entry = next((e for e in result.entries if e.node_id == node_id
                      and e.goal_hash == goal_hash and e.purpose == purpose), None)
        if entry is None or entry.status != "ready":
            raise EvidenceDenied("EVIDENCE_INSUFFICIENT")
        payload = dict(selection_handle=result.handle, selection_digest=result.selection_digest,
                       draft=result.draft, node_id=node_id, goal_hash=goal_hash,
                       purpose=purpose, evidence=tuple(sorted(entry.evidence,
                           key=lambda e: digest(e.model_dump(mode="json")))))
        unsigned = EvidenceBindingV2.model_construct(binding_digest="0" * 64, **payload)  # type: ignore[arg-type]
        binding = EvidenceBindingV2.model_validate({**payload,
            "binding_digest": digest(unsigned.payload())})
        receipt = self.check_current_authorization(binding, binding.purpose, request=request)
        if set(receipt.covered_facets) != set(entry.covered_facets):
            raise EvidenceDenied("EVIDENCE_INSUFFICIENT")
        return binding, receipt


def resolve_evidence(conn: Connection[dict[str, Any]], draft_scope: DraftScope,
                     requirements: Sequence[NodeMaterialRequirement], *,
                     governance: CorpusGovernance, request_for: RequestFor,
                     gates: AutonomousGates | None = None,
                     authority_resolver: AuthorityResolver | None = None,
                     enabled: bool = False) -> MaterialSelectionResult:
    return EvidenceSelection(conn, governance=governance, request_for=request_for,
                             gates=gates, authority_resolver=authority_resolver,
                             enabled=enabled).resolve_evidence(draft_scope, requirements)
