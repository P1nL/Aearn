"""Recoverable server-owned LessonDocument authoring workflow."""
from __future__ import annotations

import hashlib
import json
import logging
from time import monotonic
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, TypedDict

from psycopg import Connection
from uuid import uuid4

from app.core.safe_diagnostics import log_safe_event
from app.db.connection import connect
from app.services.grounding.grounding_index_repository import search_lesson_coverage_chunks, search_persisted_grounding_chunks
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery
from app.services.grounding.grounding_processing import GroundingChunk, is_admissible_lesson_source
from app.services.grounding.grounding_sources import get_grounding_source
from app.services.learning.lesson_contracts import (
    LESSON_GENERATOR_VERSION,
    LESSON_CONTENT_STANDARD_VERSION,
    LESSON_POLICY_VERSION,
    LESSON_COMPLETION_VERSION,
    LESSON_EVIDENCE_VERSION,
    LessonEvidenceUnit,
    LessonDocumentDraft,
    ExerciseGateBlock,
    LessonSourceSnapshot,
    calculate_lesson_impact,
    canonical_lesson_author_example,
    canonical_lesson_document_payload,
    canonical_source_set_hash,
    citation_id_for_chunk,
    lesson_author_block_examples,
    lesson_author_output_schema,
    lesson_block_payload,
    parse_lesson_document_candidate,
)
from app.services.learning.lesson_quality import LessonQualityError, LessonQualityReport, require_lesson_quality
from app.services.learning.catalog_scope import resolve_catalog_knowledge_key
from app.services.learning.lesson_authoring_feedback import (
    CONSTRAINTS, REPAIRABLE, LessonAuthorFeedback, LessonFeedbackIssue, attempt_diagnostic,
)
from app.services.learning.lesson_repository import (
    LessonAuthoringRunRecord,
    LessonNotFound,
    LessonVersionConflict,
    PostgresLessonDocumentRepository,
)
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    OpenAICompatibleClient,
    select_llm_protocol,
)
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage
from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _LessonDiagnostics:
    stage: str = "claim"
    primary_code: str | None = None
    primary_stage: str | None = None


@dataclass(frozen=True, slots=True)
class LessonAuthoringEvidence:
    handle: str
    display_name: str
    provider: str
    trust_tier: str
    source_version_label: str
    source_version_kind: str
    section_path: tuple[str, ...]
    evidence_excerpt: str
    evidence_schema_version: str | None = None
    evidence_units: tuple[LessonEvidenceUnit, ...] = ()


@dataclass(frozen=True, slots=True)
class LessonAuthoringRequest:
    document_kind: str
    language_id: str
    knowledge_key: str
    title: str
    goal_text: str
    target_level: str
    required_capabilities: tuple[str, ...]
    mastery_level: str
    mastery_confidence: float
    evidence: tuple[LessonAuthoringEvidence, ...]
    standard_document: LessonDocumentDraft | None = None
    previous_attempt_feedback: LessonAuthorFeedback | None = None
    citation_handles: tuple[tuple[str, str], ...] = ()
    completion_contract_version: str | None = None
    previous_personalized_document: LessonDocumentDraft | None = None
    editable_block_ids: tuple[str, ...] = ()
    personal_preferences: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class LessonAuthoringResponse:
    candidate: Mapping[str, object]
    provider: str
    model: str
    protocol: str
    usage: LLMUsage | None = None
    response_diagnostics: LLMResponseDiagnostics | None = None


class LessonDocumentAuthorPort(Protocol):
    def author(self, request: LessonAuthoringRequest) -> LessonAuthoringResponse:
        ...


class LessonAuthoringFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, outcome: str = "failed") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.outcome = outcome
        self.stage = "provider_response"
        self.issues: tuple[LessonFeedbackIssue, ...] = (LessonFeedbackIssue("LESSON_PROVIDER_UNAVAILABLE" if outcome == "unavailable" else "LESSON_AUTHOR_INTERNAL_FAILURE"),)
        self.provider = "configured-primary"
        self.model = "configured-primary"
        self.protocol = "unknown"
        self.usage: LLMUsage | None = None
        self.response_diagnostics: LLMResponseDiagnostics | None = None
        self.execution_outcome = "unknown"


class _CompletionAuthorOptions(TypedDict, total=False):
    completion_stage: str


class PrimaryLessonDocumentAuthor:
    """Primary-only adapter. It never falls back to another provider or template."""

    def __init__(self, settings: Settings | None = None, *, client: OpenAICompatibleClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    def author(self, request: LessonAuthoringRequest) -> LessonAuthoringResponse:
        completion = request.completion_contract_version == LESSON_COMPLETION_VERSION
        if completion and not self._settings.tutor_completion_driven_enabled:
            failure = LessonAuthoringFailure("LESSON_COMPLETION_DISABLED", "完成驱动课程生成尚未启用。", outcome="unavailable")
            failure.execution_outcome = "not_started"
            raise failure
        try:
            client = self._client or OpenAICompatibleClient(self._settings)
        except LLMConfigurationError as exc:
            failure = LessonAuthoringFailure(
                "LESSON_DOCUMENT_GENERATION_UNAVAILABLE",
                "课程生成服务当前不可用。",
                outcome="unavailable",
            )
            failure.execution_outcome = "not_started"
            raise failure from exc
        messages = _author_messages(request)
        options: _CompletionAuthorOptions = {"completion_stage": "lesson_authoring"} if completion else {}
        try:
            response = client.complete_json(
                messages,
                temperature=0.1,
                max_tokens=12_000,
                output_schema=lesson_author_output_schema(),
                schema_name="lesson_document_v1",
                thinking_mode="disabled" if (
                    self._settings.llm_provider_type == "deepseek"
                    and self._settings.llm_model == "deepseek-flash"
                ) else None,
                **options,
            )
        except LLMConfigurationError as exc:
            failure = LessonAuthoringFailure("LESSON_DOCUMENT_GENERATION_UNAVAILABLE", "课程生成服务当前不可用。", outcome="unavailable")
            failure.execution_outcome = "not_started"
            raise failure from exc
        except LLMInvalidResponseError as exc:
            failure = LessonAuthoringFailure("LESSON_DOCUMENT_INVALID", "课程生成结果未通过结构校验。", outcome="invalid")
            code = "LESSON_PROVIDER_" + exc.kind.value.upper()
            if (exc.response_diagnostics is not None and (
                    exc.response_diagnostics.response_status in {"missing_terminal", "queued", "in_progress", "cancelled"}
                    or (code == "LESSON_PROVIDER_ENVELOPE_INVALID"
                        and exc.response_diagnostics.response_status == "unknown")
                    or (code == "LESSON_PROVIDER_RESPONSE_INCOMPLETE"
                        and exc.response_diagnostics.incomplete_reason != "max_output_tokens"))):
                code = "LESSON_PROVIDER_RESPONSE_INCOMPLETE_NONREPAIRABLE"
            failure.issues = (LessonFeedbackIssue(code if code in CONSTRAINTS else "LESSON_PROVIDER_UNKNOWN"),)
            failure.provider = self._settings.llm_provider_type or "configured-primary"
            failure.model = exc.model or self._settings.llm_model or "configured-primary"
            failure.protocol = select_llm_protocol(self._settings).value
            failure.usage = exc.usage
            failure.response_diagnostics = exc.response_diagnostics
            status = exc.response_diagnostics.response_status if exc.response_diagnostics is not None else None
            failure.execution_outcome = "unknown" if status in {"missing_terminal", "queued", "in_progress", "unknown"} else "known"
            raise failure from exc
        except LLMCallError as exc:
            raise LessonAuthoringFailure("LESSON_DOCUMENT_GENERATION_UNAVAILABLE", "课程生成服务当前不可用。", outcome="unavailable") from exc
        return LessonAuthoringResponse(
            candidate=response.content,
            provider=self._settings.llm_provider_type or "configured-primary",
            model=response.model,
            protocol=select_llm_protocol(self._settings).value,
            usage=response.usage,
            response_diagnostics=getattr(response, "response_diagnostics", None),
        )


AuthorFactory = Callable[[], LessonDocumentAuthorPort]
LESSON_AUTHOR_FACTORY: AuthorFactory = PrimaryLessonDocumentAuthor


def dispatch_lesson_authoring_run(
    run_id: str,
    *,
    author: LessonDocumentAuthorPort | None = None,
    now: Callable[[], datetime] | None = None,
) -> None:
    clock = now or (lambda: datetime.now(UTC))
    owner = f"lesson-author-{uuid4()}"
    claimed: LessonAuthoringRunRecord | None = None
    diagnostics = _LessonDiagnostics()
    started = monotonic()
    try:
        with connect() as conn:
            with conn.transaction():
                claimed = PostgresLessonDocumentRepository(conn).claim_authoring_run(
                    run_id=run_id, owner=owner, now=clock(),
                )
        if claimed is None:
            return
        with connect() as conn:
            with conn.transaction():
                if (getattr(claimed, "completion_contract_version", None) == LESSON_COMPLETION_VERSION
                        and claimed.state == "running"):
                    running = claimed
                else:
                    running = PostgresLessonDocumentRepository(conn).mark_authoring_running(
                        run_id=claimed.run_id, lease_generation=claimed.lease_generation,
                    )
        if getattr(running, "completion_contract_version", None) == LESSON_COMPLETION_VERSION:
            from app.services.learning.lesson_completion_stages import dispatch_completion_lesson
            dispatch_completion_lesson(run=running, author=author, clock=clock)
            return
        diagnostics.stage = "source"
        with connect() as conn:
            repository = PostgresLessonDocumentRepository(conn)
            scope = repository.read_scope(
                user_id=running.user_id, track_id=running.track_id, knowledge_key=running.knowledge_key,
            )
            catalog_key = resolve_catalog_knowledge_key(
                conn, user_id=scope.user_id, track_id=scope.track_id,
                plan_revision_id=scope.active_plan_revision_id, knowledge_key=scope.knowledge_key,
            )
            snapshots = _load_evidence_snapshots(conn, scope.language_id, catalog_key, scope.node_title, clock())
            current_state = repository.read_lesson_state(
                user_id=running.user_id, track_id=running.track_id, knowledge_key=running.knowledge_key,
            )
        if not snapshots:
            raise LessonAuthoringFailure(
                "LESSON_SOURCE_EVIDENCE_INSUFFICIENT",
                "当前没有足够的受信课程来源。",
                outcome="invalid",
            )
        source_hash = canonical_source_set_hash(snapshots)
        with connect() as conn:
            with conn.transaction():
                PostgresLessonDocumentRepository(conn).set_authoring_source_set(
                    run_id=running.run_id, lease_generation=running.lease_generation, source_set_hash=source_hash,
                )
        evidence, handles = _authoring_evidence(snapshots)
        diagnostics.stage = "provider"
        port = author or LESSON_AUTHOR_FACTORY()
        standard_request = LessonAuthoringRequest(
            document_kind="standard", language_id=scope.language_id, knowledge_key=scope.knowledge_key,
            title=scope.node_title, goal_text=scope.goal_text, target_level=scope.target_level,
            required_capabilities=scope.required_capabilities, mastery_level="unseen", mastery_confidence=0.0,
            evidence=evidence,
        )
        budget = _RepairBudget(next_attempt=running.attempt_count, remaining=1 if running.attempt_count == 1 else 0)
        standard, standard_quality = _author_and_validate(
            port=port, request=standard_request, run=running, budget=budget,
            handles=handles, snapshots=snapshots, diagnostics=diagnostics,
        )

        personalized_request = LessonAuthoringRequest(
            document_kind="personalized", language_id=scope.language_id, knowledge_key=scope.knowledge_key,
            title=scope.node_title, goal_text=scope.goal_text, target_level=scope.target_level,
            required_capabilities=scope.required_capabilities, mastery_level=scope.mastery_level,
            mastery_confidence=scope.mastery_confidence, evidence=evidence, standard_document=standard,
            citation_handles=tuple(handles.items()),
        )
        personalized, personalized_quality = _author_and_validate(
            port=port, request=personalized_request, run=running, budget=budget,
            handles=handles, snapshots=snapshots, diagnostics=diagnostics,
        )
        diagnostics.stage = "validation"
        current_document = current_state.get("document")
        impact_base = current_document if isinstance(current_document, LessonDocumentDraft) else standard
        source_value = current_state.get("sources")
        current_sources = source_value if isinstance(source_value, tuple | list) else ()
        impact = calculate_lesson_impact(
            impact_base, personalized,
            current_source_ids=tuple(snapshot.source_id for snapshot in current_sources if isinstance(snapshot, LessonSourceSnapshot)),
            candidate_source_ids=tuple(snapshot.source_id for snapshot in snapshots),
        )
        diagnostics.stage = "publish"
        with connect() as conn:
            with conn.transaction():
                PostgresLessonDocumentRepository(conn).publish_authoring_result(
                    run=running, standard_document=standard, personalized_document=personalized,
                    snapshots=snapshots, standard_quality=standard_quality.safe_summary(),
                    personalized_quality=personalized_quality.safe_summary(),
                    standard_change_summary={"kind": "standard"},
                    personalized_change_summary={"kind": "personalized", "goal_bound": True},
                    generator_version=LESSON_GENERATOR_VERSION, policy_version=LESSON_POLICY_VERSION,
                    source_set_hash=source_hash, impact=impact, now=clock(),
                )
    except LessonQualityError as exc:
        _safe_fail(run_id, claimed, "LESSON_DOCUMENT_QUALITY_BLOCKED", "课程内容未通过发布质量门。", clock(), diagnostics=diagnostics, exception=exc, duration_ms=(monotonic() - started) * 1000)
    except LessonVersionConflict as exc:
        _safe_fail(run_id, claimed, "LESSON_DOCUMENT_VERSION_CONFLICT", "课程生成期间学习路线或来源已更新。", clock(), diagnostics=diagnostics, exception=exc, duration_ms=(monotonic() - started) * 1000)
    except LessonAuthoringFailure as exc:
        _safe_fail(run_id, claimed, exc.code, exc.message, clock(), diagnostics=diagnostics, exception=exc, duration_ms=(monotonic() - started) * 1000)
    except (LessonNotFound, ValueError) as exc:
        _safe_fail(run_id, claimed, "LESSON_DOCUMENT_INVALID", "课程生成结果未通过结构校验。", clock(), diagnostics=diagnostics, exception=exc, duration_ms=(monotonic() - started) * 1000)
    except Exception as exc:
        _safe_fail(run_id, claimed, "LESSON_DOCUMENT_GENERATION_UNAVAILABLE", "课程生成服务当前不可用。", clock(), diagnostics=diagnostics, exception=exc, duration_ms=(monotonic() - started) * 1000)

@dataclass(slots=True)
class _RepairBudget:
    next_attempt: int
    remaining: int = 1


def _author_and_validate(
    *, port: LessonDocumentAuthorPort, request: LessonAuthoringRequest,
    run: LessonAuthoringRunRecord, budget: _RepairBudget,
    handles: Mapping[str, str], snapshots: tuple[LessonSourceSnapshot, ...],
    diagnostics: _LessonDiagnostics | None = None,
) -> tuple[LessonDocumentDraft, LessonQualityReport]:
    diagnostics = diagnostics or _LessonDiagnostics()
    document_attempt = 1
    while True:
        diagnostics.stage = "source"
        # Fence stale dispatchers before every additional provider call.
        with connect() as conn:
            with conn.transaction():
                repository = PostgresLessonDocumentRepository(conn)
                repository.assert_authoring_current(run=run)
                if not repository.evidence_is_current(snapshots):
                    raise LessonVersionConflict("Lesson evidence changed")
        response: LessonAuthoringResponse | None = None
        failure: LessonAuthoringFailure | None = None
        feedback: LessonAuthorFeedback | None = None
        document: LessonDocumentDraft | None = None
        quality: LessonQualityReport | None = None
        original_exception: Exception | None = None
        diagnostics.primary_code = None
        diagnostics.primary_stage = None
        diagnostics.stage = "provider"
        attempt_started = monotonic()
        try:
            response = port.author(request)
            diagnostics.stage = "validation"
            document = _parse_author_candidate(response.candidate, handles)
            _assert_candidate_identity(document, request)
            quality = require_lesson_quality(
                document, snapshots,
                document_kind="personalized" if request.document_kind == "personalized" else "standard",
                standard_document=request.standard_document,
            )
        except LessonQualityError as exc:
            original_exception = exc
            failure = LessonAuthoringFailure("LESSON_DOCUMENT_QUALITY_BLOCKED", "课程内容未通过发布质量门。", outcome="invalid")
            failure.stage = "quality_gate"
            # Classify the entire report before bounding it: an omitted fatal issue must not enable repair.
            issues = tuple(LessonFeedbackIssue(issue.code if issue.code in CONSTRAINTS else "LESSON_AUTHOR_INTERNAL_FAILURE",
                next((f"blocks[{i}]" for i, block in enumerate(document.blocks) if block.block_id == issue.block_id), "document") if document else "document")
                for issue in exc.report.issues)
            fatal = tuple(issue for issue in issues if issue.code not in REPAIRABLE)
            failure.issues = (fatal + tuple(issue for issue in issues if issue.code in REPAIRABLE))[:12]
        except LessonAuthoringFailure as exc:
            original_exception = exc
            failure = exc
        except LessonVersionConflict:
            raise
        except Exception as exc:
            original_exception = exc
            failure = LessonAuthoringFailure("LESSON_DOCUMENT_GENERATION_UNAVAILABLE", "课程生成服务当前不可用。")
        if failure is not None:
            diagnostics.primary_code = failure.code
            diagnostics.primary_stage = diagnostics.stage
            log_safe_event(
                logger, "lesson_attempt_failed", exception=original_exception,
                run_id=run.run_id, stage=diagnostics.stage, code=failure.code,
                document_kind=request.document_kind, attempt=budget.next_attempt,
                duration_ms=(monotonic() - attempt_started) * 1000,
            )
            feedback = LessonAuthorFeedback(request.document_kind, failure.stage, document_attempt, failure.issues)
        diagnostics.stage = "receipt"
        try:
            with connect() as conn:
                with conn.transaction():
                    PostgresLessonDocumentRepository(conn).record_authoring_attempt(
                        run=run, attempt_index=budget.next_attempt,
                        provider=response.provider if response else failure.provider if failure else "configured-primary",
                        model=response.model if response else failure.model if failure else "configured-primary",
                        protocol=response.protocol if response else failure.protocol if failure else "unknown",
                        outcome=failure.outcome if failure else "success", diagnostic_code=failure.code if failure else None,
                        usage=_usage_mapping(response.usage if response else failure.usage if failure else None),
                        request_hash=_hash_json(_safe_request_payload(request)),
                        response_hash=_hash_json(response.candidate) if response else None,
                        diagnostic=attempt_diagnostic(
                            request.document_kind, document_attempt, feedback,
                            response_diagnostics=response.response_diagnostics if response else failure.response_diagnostics if failure else None,
                            usage=response.usage if response else failure.usage if failure else None,
                        ),
                    )
        except Exception as exc:
            log_safe_event(
                logger, "lesson_receipt_failed", level=logging.ERROR, exception=exc,
                run_id=run.run_id, stage="receipt", code="LESSON_RECEIPT_WRITE_FAILED",
                primary_code=diagnostics.primary_code, primary_stage=diagnostics.primary_stage,
                document_kind=request.document_kind, attempt=budget.next_attempt,
            )
            raise
        diagnostics.stage = diagnostics.primary_stage or "validation"
        budget.next_attempt += 1
        if failure is None:
            assert document is not None and quality is not None
            return document, quality
        if feedback is None or not feedback.repairable or budget.remaining == 0:
            raise failure
        budget.remaining -= 1
        document_attempt += 1
        request = replace(request, previous_attempt_feedback=feedback)


def _candidate_failure(code: str, stage: str, location: str = "document") -> LessonAuthoringFailure:
    failure = LessonAuthoringFailure("LESSON_DOCUMENT_INVALID", "课程生成结果未通过结构校验。", outcome="invalid")
    failure.stage = stage
    failure.issues = (LessonFeedbackIssue(code, location),)
    return failure


def _load_evidence_snapshots(
    conn: Connection[dict[str, object]],
    language_id: str,
    knowledge_key: str,
    title: str,
    snapshotted_at: datetime,
    *,
    allow_fixtures_for_tests: bool = False,
    completion_driven: bool = False,
    required_topics: tuple[str, ...] = (),
) -> tuple[LessonSourceSnapshot, ...]:
    # No route, setting, or live dispatcher enables this offline-test-only seam.
    def admitted(chunk: GroundingChunk) -> bool:
        if not is_admissible_lesson_source(chunk, allow_fixtures_for_tests=allow_fixtures_for_tests):
            return False
        if completion_driven:
            source = get_grounding_source(chunk.source_id)
            return source is not None and (source.source_version_label, source.source_version_kind) == (
                chunk.source_version_label, chunk.source_version_kind)
        return True

    query = GroundingRetrievalQuery(
            language_id_or_alias=language_id,
            query_text=f"{title} {knowledge_key}",
            topic_tags=tuple(part for part in knowledge_key.split(".") if part),
            preferred_trust_tiers=("official", "trusted_de_facto"),
            knowledge_point_title=title,
            top_k=4,
        )
    if completion_driven:
        results, missing = search_lesson_coverage_chunks(
            conn, query, required_topics=required_topics or (knowledge_key,), admission_filter=admitted,
        )
        if missing:
            raise LessonAuthoringFailure("LESSON_SOURCE_EVIDENCE_INSUFFICIENT", "课程必要知识点的来源依据不足。", outcome="invalid")
    else:
        results = search_persisted_grounding_chunks(conn, query, admission_filter=admitted)
    snapshots: list[LessonSourceSnapshot] = []
    seen: set[str] = set()
    for result in results:
        chunk = result.chunk
        source = get_grounding_source(chunk.source_id)
        if source is None or not admitted(chunk):
            continue
        citation_id = citation_id_for_chunk(chunk.chunk_id, chunk.content_hash)
        if citation_id in seen:
            continue
        seen.add(citation_id)
        snapshots.append(
            LessonSourceSnapshot(
                citation_id=citation_id, source_id=source.source_id,
                display_name=source.display_name, provider=source.provider,
                trust_tier=source.trust_tier, source_type=source.content_type,
                source_version_label=chunk.source_version_label,
                source_version_kind=chunk.source_version_kind,
                canonical_url=chunk.canonical_url, section_path=chunk.section_path,
                grounding_chunk_id=chunk.chunk_id,
                document_content_hash=chunk.document_content_hash,
                chunk_content_hash=chunk.content_hash, fetched_at=chunk.fetched_at,
                snapshotted_at=snapshotted_at,
                evidence_excerpt=" ".join(chunk.text.split())[:1200],
                evidence_schema_version=LESSON_EVIDENCE_VERSION if completion_driven else None,
                evidence_units=(LessonEvidenceUnit(chunk.text, chunk.content_hash, 0, len(chunk.text.encode("utf-8"))),) if completion_driven else (),
            )
        )
    return tuple(snapshots)


def _authoring_evidence(
    snapshots: Sequence[LessonSourceSnapshot],
) -> tuple[tuple[LessonAuthoringEvidence, ...], dict[str, str]]:
    evidence: list[LessonAuthoringEvidence] = []
    handles: dict[str, str] = {}
    for index, snapshot in enumerate(snapshots, 1):
        handle = f"S{index}"
        handles[handle] = snapshot.citation_id
        evidence.append(
            LessonAuthoringEvidence(
                handle=handle, display_name=snapshot.display_name,
                provider=snapshot.provider, trust_tier=snapshot.trust_tier,
                source_version_label=snapshot.source_version_label,
                source_version_kind=snapshot.source_version_kind,
                section_path=snapshot.section_path,
                evidence_excerpt=snapshot.evidence_excerpt,
                evidence_schema_version=snapshot.evidence_schema_version,
                evidence_units=snapshot.evidence_units,
            )
        )
    return tuple(evidence), handles


def _parse_author_candidate(payload: Mapping[str, object], handles: Mapping[str, str]) -> LessonDocumentDraft:
    expected = {"schema_version", "title", "language_id", "knowledge_key", "content_standard_version", "coverage_keys", "blocks"}
    if set(payload) != expected or payload.get("content_standard_version") != LESSON_CONTENT_STANDARD_VERSION:
        raise _candidate_failure("LESSON_DOCUMENT_FIELDS_INVALID", "candidate_shape")
    blocks = payload.get("blocks")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 64:
        raise _candidate_failure("LESSON_DOCUMENT_FIELDS_INVALID", "candidate_shape", "blocks")
    rewritten = dict(payload)
    rewritten_blocks: list[object] = []
    for index, raw in enumerate(blocks):
        location = f"blocks[{index}]"
        if not isinstance(raw, Mapping):
            raise _candidate_failure("LESSON_BLOCK_FIELDS_INVALID", "candidate_contract", location)
        block = dict(raw)
        block_type = block.get("type")
        examples = lesson_author_block_examples(language_id="python", citation_handle="S1")
        if not isinstance(block_type, str) or block_type not in examples:
            raise _candidate_failure("LESSON_BLOCK_TYPE_INVALID", "candidate_contract", location + ".type")
        example = examples[block_type]
        if isinstance(example, Mapping) and set(block) != set(example):
            missing = sorted(set(example) - set(block))
            if missing:
                location += f".{missing[0]}"
            raise _candidate_failure("LESSON_BLOCK_FIELDS_INVALID", "candidate_contract", location)
        citations = block.get("citation_ids")
        if not isinstance(citations, list) or any(not isinstance(item, str) or item not in handles for item in citations):
            raise _candidate_failure("LESSON_CITATION_HANDLE_INVALID", "candidate_contract", location + ".citation_ids")
        block["citation_ids"] = [handles[item] for item in citations]
        # The same strict parser validates each block, adding a safe index without echoing its exception.
        from app.services.learning.lesson_contracts import _parse_block
        try:
            _parse_block(block)
        except (ValueError, TypeError) as exc:
            # Parse only trusted labels from our strict parser. Never expose
            # candidate field names, values or the original exception text.
            aliases = {"coverage_keys": ("coverage key",), "items": ("learning objectives", "next steps"),
                       "rows": ("comparison row", "comparison rows"), "required_capabilities": ("required capability",)}
            text = str(exc)
            matched_labels: list[tuple[int, str]] = []
            for field in (example if isinstance(example, Mapping) else ()):
                prefixes = (str(field), str(field).replace("_", " "), f"{block_type} {field}",
                            f"{block_type.replace('_', ' ')} {field}", *aliases.get(str(field), ()))
                matched_labels.extend((len(prefix), str(field)) for prefix in prefixes if text.startswith(prefix + " "))
            if matched_labels:
                # "code example execution_claim" outranks the broad "code".
                location += f".{max(matched_labels)[1]}"
            raise _candidate_failure("LESSON_BLOCK_FIELDS_INVALID", "candidate_contract", location) from None
        if block.get("order_index") != index:
            raise _candidate_failure("LESSON_BLOCK_ORDER_INVALID", "candidate_contract", location + ".order_index")
        rewritten_blocks.append(block)
    rewritten["blocks"] = rewritten_blocks
    try:
        return parse_lesson_document_candidate(rewritten)
    except (ValueError, TypeError):
        raise _candidate_failure("LESSON_DOCUMENT_FIELDS_INVALID", "candidate_contract") from None


def _assert_candidate_identity(document: LessonDocumentDraft, request: LessonAuthoringRequest) -> None:
    if request.previous_personalized_document is not None:
        previous = request.previous_personalized_document
        document_identity = ("schema_version", "title", "language_id", "knowledge_key", "content_standard_version", "coverage_keys")
        if any(getattr(document, field) != getattr(previous, field) for field in document_identity):
            raise _candidate_failure("LESSON_PERSONALIZED_UNAFFECTED_CHANGED", "candidate_identity")
        if tuple(block.block_id for block in document.blocks) != tuple(block.block_id for block in previous.blocks):
            raise _candidate_failure("LESSON_PERSONALIZED_UNAFFECTED_CHANGED", "candidate_identity")
        for block, prior in zip(document.blocks, previous.blocks, strict=True):
            payload, prior_payload = lesson_block_payload(block), lesson_block_payload(prior)
            structural_fields = ("type", "block_id", "order_index", "citation_ids", "coverage_keys")
            if (any(payload.get(field) != prior_payload.get(field) for field in structural_fields)
                    or (block.block_id not in request.editable_block_ids and payload != prior_payload)):
                raise _candidate_failure("LESSON_PERSONALIZED_UNAFFECTED_CHANGED", "candidate_identity", f"blocks[{block.order_index}]")
    if document.language_id != request.language_id:
        raise _candidate_failure("LESSON_CANDIDATE_SCOPE_INVALID", "candidate_identity", "language_id")
    if document.knowledge_key != request.knowledge_key:
        raise _candidate_failure("LESSON_CANDIDATE_SCOPE_INVALID", "candidate_identity", "knowledge_key")
    if request.required_capabilities:
        authorized = set(request.required_capabilities)
        # Existing Gate scope permits the exact step capability when its
        # language capability is granted. Do not break that legacy contract.
        if request.language_id in authorized:
            authorized.add(request.knowledge_key)
        for block in document.blocks:
            if isinstance(block, ExerciseGateBlock) and (
                not block.required_capabilities or not set(block.required_capabilities).issubset(authorized)
            ):
                raise _candidate_failure("LESSON_GATE_CAPABILITY_SCOPE_INVALID", "candidate_identity")


def _safe_fail(
    run_id: str,
    claimed: LessonAuthoringRunRecord | None,
    code: str,
    message: str,
    now: datetime,
    *, diagnostics: _LessonDiagnostics | None = None,
    exception: Exception | None = None, duration_ms: float | None = None,
) -> None:
    log_safe_event(
        logger, "lesson_authoring_failed", level=logging.ERROR, exception=exception,
        run_id=run_id, code=code, stage=diagnostics.stage if diagnostics else "unknown",
        primary_code=diagnostics.primary_code if diagnostics else None,
        primary_stage=diagnostics.primary_stage if diagnostics else None, duration_ms=duration_ms,
    )
    try:
        with connect() as conn:
            with conn.transaction():
                repository = PostgresLessonDocumentRepository(conn)
                current = repository.read_authoring_run(run_id=run_id, for_update=True)
                if current.state in {"completed", "failed", "cancelled"}:
                    return
                generation = claimed.lease_generation if claimed is not None else current.lease_generation
                repository.fail_authoring_run(
                    run_id=run_id, lease_generation=generation,
                    failure_code=code, failure_message=message, now=now,
                )
    except Exception as exc:
        log_safe_event(
            logger, "lesson_failure_receipt_failed", level=logging.ERROR, exception=exc,
            run_id=run_id, stage="receipt", code="LESSON_FAILURE_RECEIPT_WRITE_FAILED",
            primary_code=code, primary_stage=diagnostics.stage if diagnostics else "unknown",
        )
        return


def _author_messages(request: LessonAuthoringRequest) -> tuple[dict[str, str], ...]:
    citation_handle = request.evidence[0].handle
    official_handles = tuple(item.handle for item in request.evidence if item.trust_tier == "official")
    block_examples = lesson_author_block_examples(
        language_id=request.language_id,
        citation_handle=citation_handle,
        required_capabilities=request.required_capabilities,
    )
    if not official_handles:
        block_examples.pop("authority_note", None)
    else:
        authority_example = block_examples.get("authority_note")
        if isinstance(authority_example, dict):
            authority_example["citation_ids"] = [official_handles[0]]
    instruction = (
        "You author one strict LessonDocument JSON object. Use only the supplied evidence handles in citation_ids. "
        "Do not output URLs, HTML, Markdown, scripts, styles, commands, paths, hidden tests, answers, rubrics, or execution claims. "
        "Use schema_version lesson_document_v1 and content_standard_version programming_language_lesson_v1. "
        "Allowed block types for this request are " + ", ".join(block_examples) + ". They are not all mandatory. "
        "authority_note may cite only official evidence handles: " + json.dumps(official_handles) + ". "
        "When that list is empty, do not emit authority_note; explain supported vendor or dialect boundaries in a cited concept "
        "or comparison instead. Never relabel trusted_de_facto/internal evidence as official or fabricate an official handle. "
        "block_id values are stable lowercase keys; order_index starts at zero and is continuous. "
        "Every factual block uses at least one supplied evidence handle. code_example.execution_claim is exactly not_run. "
        "exercise_gate only contains gate_key, gate_kind, assessment_contract_version, required_capabilities, learner_prompt. "
        "Every exercise_gate uses only the exact required_capabilities supplied in the request; never invent a .core capability. "
        "Return JSON only with exact document and block fields. Exact compact document example: "
        + json.dumps(
            canonical_lesson_author_example(
                language_id=request.language_id,
                knowledge_key=request.knowledge_key,
                title=request.title,
                citation_handle=citation_handle,
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + ". Exact field examples for the allowed block types: "
        + json.dumps(
            block_examples,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    payload: dict[str, object] = _safe_request_payload(request)
    if request.standard_document is not None:
        payload["personalization_rule"] = "Preserve all coverage keys and every exercise_gate contract exactly."
    if request.previous_personalized_document is not None:
        payload["personalization_rule"] = (
            "Update only content inside editable_block_ids for the changed personal conditions. Preserve document metadata, "
            "other blocks, all block identities, types and order, coverage, citations and every exercise_gate contract exactly."
        )
    return (
        {"role": "system", "content": instruction},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    )


def _safe_request_payload(request: LessonAuthoringRequest) -> dict[str, object]:
    payload: dict[str, object] = {
        "document_kind": request.document_kind,
        "language_id": request.language_id,
        "knowledge_key": request.knowledge_key,
        "title": request.title,
        "goal_text": request.goal_text[:1200],
        "target_level": request.target_level,
        "required_capabilities": list(request.required_capabilities),
        "mastery_level": request.mastery_level,
        "mastery_confidence": round(request.mastery_confidence, 4),
        "evidence": [
            {
                "handle": item.handle,
                "display_name": item.display_name,
                "provider": item.provider,
                "trust_tier": item.trust_tier,
                "source_version_label": item.source_version_label,
                "source_version_kind": item.source_version_kind,
                "section_path": list(item.section_path),
                "evidence_excerpt": item.evidence_excerpt,
                **({"evidence_schema_version": item.evidence_schema_version,
                    "evidence_units": [unit.payload() for unit in item.evidence_units]}
                   if item.evidence_schema_version is not None else {}),
            }
            for item in request.evidence
        ],
    }
    if request.previous_attempt_feedback is not None:
        payload["previous_attempt_feedback"] = request.previous_attempt_feedback.payload()
    if request.standard_document is not None:
        standard_payload = canonical_lesson_document_payload(request.standard_document)
        reverse = {citation: handle for handle, citation in request.citation_handles}
        standard_blocks = standard_payload["blocks"]
        assert isinstance(standard_blocks, list)
        for block in standard_blocks:
            block["citation_ids"] = [reverse[citation] for citation in block["citation_ids"]]
        payload["standard_document"] = standard_payload
    if request.completion_contract_version is not None:
        payload["completion_contract_version"] = request.completion_contract_version
    if request.personal_preferences:
        payload["personal_preferences"] = dict(request.personal_preferences)
    if request.previous_personalized_document is not None:
        previous_payload = canonical_lesson_document_payload(request.previous_personalized_document)
        reverse = {citation: handle for handle, citation in request.citation_handles}
        previous_blocks = previous_payload["blocks"]
        assert isinstance(previous_blocks, list)
        for block in previous_blocks:
            block["citation_ids"] = [reverse[citation] for citation in block["citation_ids"]]
        payload["previous_personalized_document"] = previous_payload
        payload["editable_block_ids"] = list(request.editable_block_ids)
    return payload


def _usage_mapping(usage: LLMUsage | None) -> dict[str, int] | None:
    if usage is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    result = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
    if usage.total_tokens is not None:
        result["total_tokens"] = usage.total_tokens
    return result


def _hash_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
