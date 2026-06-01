from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.grounding_fetcher import GroundingDocsFetcher
from app.services.grounding_fixtures import mainstream_grounding_fixture_documents
from app.services.grounding_processing import GroundingChunk, clean_and_chunk_document
from app.services.grounding_sources import all_grounding_sources, get_grounding_source


GroundingReindexStatus = Literal["completed", "completed_with_failures", "failed"]


@dataclass(frozen=True, slots=True)
class GroundingReindexSourceReport:
    source_id: str
    language_id: str | None
    status: GroundingReindexStatus
    fetched_documents: int
    chunks_created: int
    failure_count: int
    error_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GroundingReindexReport:
    status: GroundingReindexStatus
    total_sources: int
    total_documents: int
    total_chunks: int
    total_failures: int
    source_reports: tuple[GroundingReindexSourceReport, ...]
    chunks: tuple[GroundingChunk, ...]


def run_grounding_reindex(
    fetcher: GroundingDocsFetcher,
    *,
    source_ids: tuple[str, ...] | None = None,
) -> GroundingReindexReport:
    selected_source_ids = source_ids or tuple(source.source_id for source in all_grounding_sources())
    source_reports: list[GroundingReindexSourceReport] = []
    chunks: list[GroundingChunk] = []

    for source_id in selected_source_ids:
        source = get_grounding_source(source_id)
        if source is None:
            source_reports.append(
                GroundingReindexSourceReport(
                    source_id=source_id,
                    language_id=None,
                    status="failed",
                    fetched_documents=0,
                    chunks_created=0,
                    failure_count=1,
                    error_codes=("SOURCE_NOT_REGISTERED",),
                ),
            )
            continue

        fetched_documents = 0
        source_chunks: list[GroundingChunk] = []
        error_codes: list[str] = []
        for result in fetcher.fetch_source_seed_documents(source.source_id):
            if result.status == "ok" and result.document is not None:
                fetched_documents += 1
                source_chunks.extend(clean_and_chunk_document(result.document))
            else:
                error_codes.append(result.error_code or "FETCH_FAILED")

        chunks.extend(source_chunks)
        source_reports.append(
            GroundingReindexSourceReport(
                source_id=source.source_id,
                language_id=source.language_id,
                status=_source_status(fetched_documents, len(source_chunks), len(error_codes)),
                fetched_documents=fetched_documents,
                chunks_created=len(source_chunks),
                failure_count=len(error_codes),
                error_codes=tuple(error_codes),
            ),
        )

    return _build_report(source_reports, tuple(chunks))


def run_fixture_grounding_reindex() -> GroundingReindexReport:
    source_reports: list[GroundingReindexSourceReport] = []
    chunks: list[GroundingChunk] = []

    for document in mainstream_grounding_fixture_documents():
        document_chunks = clean_and_chunk_document(document)
        chunks.extend(document_chunks)
        source_reports.append(
            GroundingReindexSourceReport(
                source_id=document.source_id,
                language_id=document.language_id,
                status=_source_status(1, len(document_chunks), 0),
                fetched_documents=1,
                chunks_created=len(document_chunks),
                failure_count=0,
                error_codes=(),
            ),
        )

    return _build_report(source_reports, tuple(chunks))


def _build_report(
    source_reports: list[GroundingReindexSourceReport],
    chunks: tuple[GroundingChunk, ...],
) -> GroundingReindexReport:
    total_documents = sum(report.fetched_documents for report in source_reports)
    total_chunks = sum(report.chunks_created for report in source_reports)
    total_failures = sum(report.failure_count for report in source_reports)
    return GroundingReindexReport(
        status=_overall_status(total_documents, total_chunks, total_failures),
        total_sources=len(source_reports),
        total_documents=total_documents,
        total_chunks=total_chunks,
        total_failures=total_failures,
        source_reports=tuple(source_reports),
        chunks=chunks,
    )


def _source_status(documents: int, chunks: int, failures: int) -> GroundingReindexStatus:
    if failures == 0 and documents > 0 and chunks > 0:
        return "completed"
    if documents > 0 or chunks > 0:
        return "completed_with_failures"
    return "failed"


def _overall_status(documents: int, chunks: int, failures: int) -> GroundingReindexStatus:
    if failures == 0 and documents > 0 and chunks > 0:
        return "completed"
    if documents > 0 or chunks > 0:
        return "completed_with_failures"
    return "failed"
