"""Explicit confirmed-course source reissuance; historical proof is DATA only.

New capture authority, oracle execution, signing, and persistence remain with
the original assessment owners. This module never renews an old timestamp.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from psycopg.types.json import Jsonb

from .source_assessment_profiles import (
    PreparedActualDSourceAssessment, PreparedSourceAssessment, SignedSourceAssessment, SourceAssessmentDenied, revalidate_prepared,
)

if TYPE_CHECKING:
    from .assessment_receipt_repository import AssessmentReceiptRepository

MAPPING = UUID("d8e34e01-3514-41a3-9bbd-55ee3e627134")
PRIVATE_CLAIM = "source-claim.b56c9153e8e84d70ac6262dbcc0c9828"
PUBLIC_CLAIM = "source-claim.1528a8007c694a1cb4956aba272bd2e1"
ORACLE_RUN = UUID("366ab674-3091-5a37-bdcb-8984c75e9717")


def same_supported_source(old: PreparedSourceAssessment, new: PreparedSourceAssessment) -> None:
    """Pure continuity, NOT authority. Ignore offsets/scaffolding, never supported bytes."""
    old, new = revalidate_prepared(old), revalidate_prepared(new)
    def semantic(p: PreparedSourceAssessment) -> tuple[object, ...]:
        return (p.profile_id,p.source_handle,p.license_id,p.origin,p.reading_level,p.demand,p.execution_scope,
            tuple((s.unit,s.sha256,s.end_byte-s.start_byte) for s in p.spans))
    if type(old) is not type(new) or semantic(old) != semantic(new):
        raise SourceAssessmentDenied("SOURCE_SUCCESSOR_SUPPORTED_CONTENT_CHANGED")
    if isinstance(old,PreparedActualDSourceAssessment):
        if (not isinstance(new,PreparedActualDSourceAssessment)
                or old.actual_d.model_dump(exclude={"oracle_run_id"}) != new.actual_d.model_dump(exclude={"oracle_run_id"})):
            raise SourceAssessmentDenied("SOURCE_SUCCESSOR_CONFIRMED_SCOPE_CHANGED")


def require_confirmed_successor(repo: AssessmentReceiptRepository, prepared: PreparedActualDSourceAssessment) -> None:
    repo.require_transaction()
    if prepared.profile_id != "python-binding-actual-d-source-v1" or prepared.actual_d.oracle_run_id != ORACLE_RUN:
        raise SourceAssessmentDenied("SOURCE_CONFIRMED_SUCCESSOR_REQUIRED")
    row = repo.conn.execute("SELECT item_supply_internal.confirmed_source_successor_allowed(%s) AS allowed",
        (Jsonb(prepared.model_dump(mode="json")),)).fetchone()
    if row is None or row["allowed"] is not True:
        raise SourceAssessmentDenied("SOURCE_CONFIRMED_SUCCESSOR_REQUIRED")


def prepare_confirmed_successor(repo: AssessmentReceiptRepository, *, capture_id: UUID,
                               document_handle: str, mapping_receipt_id: UUID) -> PreparedActualDSourceAssessment:
    repo.require_transaction()
    if mapping_receipt_id != MAPPING:
        raise SourceAssessmentDenied("SOURCE_CONFIRMED_SUCCESSOR_REQUIRED")
    row = repo.conn.execute("SELECT signed_proof FROM rag_assessment_source_evidence WHERE claim_handle=%s FOR SHARE",
        (PRIVATE_CLAIM,)).fetchone()
    if row is None:
        raise SourceAssessmentDenied("SOURCE_SUCCESSOR_HISTORY_MISSING")
    old = SignedSourceAssessment.model_validate_json(json.dumps(row["signed_proof"])).payload.prepared
    if type(old) is not PreparedActualDSourceAssessment or capture_id == old.capture_id:
        raise SourceAssessmentDenied("SOURCE_CONFIRMED_SUCCESSOR_REQUIRED")
    prepared = repo._prepare_actual_d(capture_id=capture_id,document_handle=document_handle,
        draft=old.actual_d.draft,base_selection_handle=old.actual_d.base_selection_handle,
        node_id=old.actual_d.node_id,target_id=old.actual_d.target_id,companion_capture_ids=None,
        oracle_run_id=ORACLE_RUN,allow_confirmed=True)
    if type(prepared) is not PreparedActualDSourceAssessment:
        raise SourceAssessmentDenied("SOURCE_CONFIRMED_SUCCESSOR_REQUIRED")
    same_supported_source(old,prepared)
    require_confirmed_successor(repo,prepared)
    return prepared
