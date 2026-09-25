"""Fail-closed B1 pre-search assessment of currently admitted material.

Phase-I active/published metadata and fixtures cannot establish C admission,
purpose, readability or revocation. C must provide a consistent current read;
this module neither queries fixture corpus nor creates admission evidence.
"""
from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from .contracts import FrozenContract, HANDLE, LearningMaterialDemand, SourceAssessment, revalidate
from .discovery_broker import CorpusAssessment
from .source_policy import SourceAuthorization


class QualifiedDocument(FrozenContract):
    """One document and its current C-owned per-purpose authorization facts."""

    assessment: SourceAssessment
    authorization: SourceAuthorization
    covered_facets: tuple[str, ...] = Field(min_length=1, max_length=24)
    unresolved_conflict: bool = False

    @model_validator(mode="after")
    def coherent_facets(self) -> QualifiedDocument:
        if (len(set(self.covered_facets)) != len(self.covered_facets)
                or set(self.covered_facets) - set(self.assessment.scope.facets)):
            raise ValueError("document facets exceed assessed scope")
        return self


class QualificationSnapshot(FrozenContract):
    """One current active pointer and C admissions read with a C-issued receipt.

    The authority must verify pointer and admissions in one read boundary;
    synthetic/replayed operator fixtures are not qualification evidence.
    """

    demand: LearningMaterialDemand
    receipt_id: str = Field(pattern=HANDLE)
    corpus_id: UUID
    subject_id: str
    subject_version: str
    active: bool
    state: Literal["candidate", "validated", "published", "failed", "retired"]
    synthetic_fixture: bool
    documents: tuple[QualifiedDocument, ...] = Field(max_length=96)


class QualificationAuthority(Protocol):
    """C-owned read port; None means unavailable/unknown, not sufficient."""

    def resolve(self, demand: LearningMaterialDemand) -> QualificationSnapshot | None: ...


def _usable(document: QualifiedDocument, demand: LearningMaterialDemand) -> bool:
    assessment, current = document.assessment, document.authorization
    return (
        assessment.scope == demand.scope and current.scope == demand.scope
        and assessment.status == "reviewed" and current.reviewed
        and current.readable and not current.revoked
        and assessment.source_handle == current.source_handle
        and assessment.document_handle == current.document_handle
        and assessment.document_revision == current.document_revision
        and assessment.document_hash == current.document_hash
        and assessment.origin == current.origin
        and assessment.reading_level == current.reading_level
        and assessment.policy_generation == current.policy_generation
        and assessment.storage_receipt_id is not None
        and assessment.storage_receipt_id == current.storage_receipt_id
        and assessment.admission_receipt_id is not None
        and assessment.admission_receipt_id == current.admission_receipt_id
        and demand.purpose in assessment.allowed_usages
        and len(set(current.allowed_usages)) == len(current.allowed_usages)
        and demand.purpose in current.allowed_usages
        and not document.unresolved_conflict
    )


class QualifiedCorpusAdapter:
    """Implements QualifiedCorpusPort without promoting seeds/staging/fixtures.

    Missing authority, malformed/stale read, or a non-published/fixture corpus
    is unknown (None); a trusted but insufficient snapshot yields a gap receipt.
    """

    def __init__(self, authority: QualificationAuthority | None) -> None:
        self._authority = authority

    def assess(self, demand: LearningMaterialDemand) -> CorpusAssessment | None:
        try:
            full = revalidate(demand, LearningMaterialDemand)
            if self._authority is None:
                return None
            raw = self._authority.resolve(full)
            if raw is None:
                return None
            snapshot = revalidate(raw, QualificationSnapshot)
            if (snapshot.demand != full or snapshot.subject_id != full.scope.subject_id
                    or not snapshot.active or snapshot.state != "published"
                    or snapshot.synthetic_fixture):
                return None
            if snapshot.subject_version != full.scope.subject_version:
                return CorpusAssessment(demand=full, status="gap", receipt_id=snapshot.receipt_id,
                                        gap_reason="version_stale")
            eligible = tuple(doc for doc in snapshot.documents if _usable(doc, full))
            covered = set().union(*(doc.covered_facets for doc in eligible)) if eligible else set()
            readable = set().union(*(
                doc.covered_facets for doc in eligible
                if doc.assessment.reading_level == full.reading_level
            )) if eligible else set()
            if set(full.scope.facets) <= readable:
                return CorpusAssessment(demand=full, status="sufficient",
                                        receipt_id=snapshot.receipt_id)
            conflicted = set().union(*(
                doc.covered_facets for doc in snapshot.documents
                if doc.unresolved_conflict and _usable(
                    doc.model_copy(update={"unresolved_conflict": False}), full,
                )
            )) if snapshot.documents else set()
            reason: Literal["reading_level", "coverage_gap", "conflict"] = (
                "reading_level" if set(full.scope.facets) <= covered
                else "conflict" if set(full.scope.facets) <= covered | conflicted
                else "coverage_gap"
            )
            return CorpusAssessment(demand=full, status="gap", receipt_id=snapshot.receipt_id,
                                    gap_reason=reason)
        except Exception:
            # Never expose resolver text or turn a failed read into ready.
            return None
