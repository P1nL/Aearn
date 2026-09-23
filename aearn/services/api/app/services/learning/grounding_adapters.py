"""Explicit, read-only RAG v2 to legacy *shadow* shapes; never a public consumer."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from app.services.grounding.corpus_fixture_policy import (
    FIXTURE_DOMAIN, FIXTURE_FETCHED_AT, FIXTURE_VERSION, fixture_registry_digest, fixture_slices,
)
from app.services.grounding.grounding_citations import AgentGroundingItem, GroundingCitation
from app.services.grounding.retrieval_planner import resolve_plan
from app.services.grounding.retrieval_contracts import (
    ActiveCorpusSelector, GroundingRetrievalRequest, GroundingRetrievalResultV2, stable_hash,
)
from app.services.grounding.subject_registry import capability_projection, get_grounding_subject
from app.services.learning.lesson_contracts import LessonSourceSnapshot


@dataclass(frozen=True, slots=True)
class ShadowGroundingStatus:
    subject_id: str
    corpus_state: Literal["disabled", "unavailable", "active_fixture"]
    public_availability: Literal["unavailable"] = "unavailable"
    synthetic: bool = True


@dataclass(frozen=True, slots=True)
class ShadowEvidenceIdentity:
    source_id: str
    document_id: str
    chunk_id: str
    source_hash: str
    document_hash: str
    chunk_hash: str


@dataclass(frozen=True, slots=True)
class ShadowLegacyGrounding:
    """v1-shaped entries are inspection material, never v1 DB/source authority."""

    status: ShadowGroundingStatus
    subject_version: str | None = None
    corpus_id: UUID | None = None
    corpus_summary_hash: str | None = None
    corpus_content_hash: str | None = None
    registry_digest: str | None = None
    evidence_identities: tuple[ShadowEvidenceIdentity, ...] = ()
    lesson_sources: tuple[LessonSourceSnapshot, ...] = ()
    tutor_items: tuple[AgentGroundingItem, ...] = ()
    public_blocked: bool = True


def _active(conn: Connection[dict[str, Any]], subject_id: str) -> tuple[dict[str, Any], int] | None:
    subject = get_grounding_subject(subject_id)
    if subject is None or subject.subject_id != subject_id:
        return None
    pointer = conn.execute(
        "SELECT corpus_version_id,generation FROM grounding_active_corpora WHERE subject_id=%s",
        (subject_id,),
    ).fetchone()
    if pointer is None:
        return None
    version = conn.execute(
        "SELECT id,subject_id,subject_version,state,registry_digest,summary_hash,source_set_hash,"
        "content_hash,validation_summary_json,coverage_summary_json,retrieval_policy_version,"
        "coverage_policy_version FROM grounding_corpus_versions WHERE id=%s",
        (pointer["corpus_version_id"],),
    ).fetchone()
    if (version is None or version["id"] != pointer["corpus_version_id"]
            or version["subject_id"] != subject_id or version["state"] != "published"
            or version["subject_version"] != FIXTURE_VERSION
            or version["registry_digest"] != fixture_registry_digest(subject)
            or version["retrieval_policy_version"] != "fixture-fts-v1"
            or version["coverage_policy_version"] != "fixture-facets-v1"
            or not all(version[key] for key in ("summary_hash", "source_set_hash", "content_hash"))):
        return None
    return version, pointer["generation"]


def shadow_grounding_status(
    conn: Connection[dict[str, Any]], subject_id: str, *, enabled: bool = False,
) -> ShadowGroundingStatus:
    """Internal opt-in status: an active fixture is never public availability."""
    if not enabled:
        return ShadowGroundingStatus(subject_id, "disabled")
    capability = capability_projection(subject_id)
    if capability is None or capability.public_course_admissible:
        return ShadowGroundingStatus(subject_id, "unavailable")
    active = _active(conn, subject_id)
    verified = active is not None and _verified_rows(conn, active[0]) is not None
    return ShadowGroundingStatus(subject_id, "active_fixture" if verified else "unavailable")


def _verified_rows(
    conn: Connection[dict[str, Any]], version: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] | None:
    """Recheck the entire sealed fixture scope, including unjoined extra rows."""
    subject = get_grounding_subject(version["subject_id"])
    if subject is None:
        return None
    items = fixture_slices(subject)
    corpus_id = version["id"]
    sources = conn.execute(
        "SELECT source_id,source_hash,trust_tier,source_kind,source_version,allowed_domains_json,"
        "seed_urls_json,facets_json FROM grounding_corpus_source_snapshots "
        "WHERE corpus_version_id=%s ORDER BY source_id LIMIT %s", (corpus_id, len(items) + 1),
    ).fetchall()
    documents = conn.execute(
        "SELECT document_id,source_id,source_hash,trust_tier,canonical_url,final_url,content_type,"
        "document_version,fetched_at,document_hash,parse_status FROM grounding_corpus_documents "
        "WHERE corpus_version_id=%s ORDER BY document_id LIMIT %s", (corpus_id, len(items) + 1),
    ).fetchall()
    chunks = conn.execute(
        "SELECT chunk_id,document_id,source_id,source_hash,trust_tier,document_hash,ordinal,title,"
        "section_path,content,facets_json,topic_tags_json,chunk_hash FROM grounding_corpus_chunks "
        "WHERE corpus_version_id=%s ORDER BY chunk_id LIMIT %s", (corpus_id, len(items) + 1),
    ).fetchall()
    if any(len(rows) != len(items) for rows in (sources, documents, chunks)):
        return None
    by_source = {row["source_id"]: row for row in sources}
    by_document = {row["document_id"]: row for row in documents}
    by_chunk = {row["chunk_id"]: row for row in chunks}
    if any(len(rows) != len(items) for rows in (by_source, by_document, by_chunk)):
        return None
    trust = "official" if subject.source_trust_policy == "official" else "trusted_de_facto"
    verified: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    for item in items:
        source = by_source.get(item.source_id)
        document = by_document.get(f"{item.source_id}:document")
        chunk = by_chunk.get(f"{item.source_id}:chunk")
        source_hash = stable_hash({
            "subject_id": subject.subject_id, "subject_version": FIXTURE_VERSION,
            "source_id": item.source_id, "trust_tier": trust, "source_kind": "fixture",
            "source_version": FIXTURE_VERSION, "allowed_domains": (FIXTURE_DOMAIN,),
            "seed_urls": (item.url,), "facets": (item.facet,),
        })
        content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        if (source is None or document is None or chunk is None
                or any(source[key] != value for key, value in {
                    "source_hash": source_hash, "trust_tier": trust, "source_kind": "fixture",
                    "source_version": FIXTURE_VERSION, "allowed_domains_json": [FIXTURE_DOMAIN],
                    "seed_urls_json": [item.url], "facets_json": [item.facet],
                }.items())
                or any(document[key] != value for key, value in {
                    "source_id": item.source_id, "source_hash": source_hash, "trust_tier": trust,
                    "canonical_url": item.url, "final_url": item.url, "content_type": "text/plain",
                    "document_version": FIXTURE_VERSION, "fetched_at": FIXTURE_FETCHED_AT,
                    "document_hash": content_hash, "parse_status": "parsed",
                }.items())
                or any(chunk[key] != value for key, value in {
                    "document_id": document["document_id"], "source_id": item.source_id,
                    "source_hash": source_hash, "trust_tier": trust, "document_hash": content_hash,
                    "ordinal": 0, "title": f"Fixture: {subject.subject_id} / {item.facet}",
                    "section_path": item.facet, "content": item.content,
                    "facets_json": [item.facet], "topic_tags_json": [], "chunk_hash": content_hash,
                }.items())):
            return None
        verified[chunk["chunk_id"]] = (source, document, chunk)
    source_hash = stable_hash([{"source_id": row["source_id"], "source_hash": row["source_hash"]}
                               for row in sources])
    content_hash = stable_hash([
        [{"document_id": row["document_id"], "source_id": row["source_id"],
          "document_hash": row["document_hash"]} for row in documents],
        [{"chunk_id": row["chunk_id"], "document_id": row["document_id"],
          "chunk_hash": row["chunk_hash"]} for row in chunks],
    ])
    summary_hash = stable_hash([
        str(corpus_id), version["registry_digest"], source_hash, content_hash,
        version["validation_summary_json"], version["coverage_summary_json"],
        version["retrieval_policy_version"], version["coverage_policy_version"],
    ])
    if (version["source_set_hash"] != source_hash or version["content_hash"] != content_hash
            or version["summary_hash"] != summary_hash):
        return None
    return verified


def project_v2_legacy_shadow(
    conn: Connection[dict[str, Any]], request: GroundingRetrievalRequest,
    result: GroundingRetrievalResultV2, *, enabled: bool = False,
) -> ShadowLegacyGrounding:
    """Caller-injected result, caller-owned coherent read-only transaction.

    No retrieval invocation, mutations, clocks, or public wiring. Refuse rather
    than truncate excerpts or fabricate evidence/URL/version metadata.
    """
    if not enabled:
        return ShadowLegacyGrounding(ShadowGroundingStatus(request.subject_id, "disabled"))
    blocked = ShadowLegacyGrounding(ShadowGroundingStatus(request.subject_id, "unavailable"))
    try:
        request = GroundingRetrievalRequest.model_validate(request.model_dump())
        result = GroundingRetrievalResultV2.model_validate(result.model_dump())
    except (ValidationError, ValueError, TypeError):
        return blocked
    capability = capability_projection(request.subject_id)
    plan = result.plan
    report = result.coverage
    if (capability is None or capability.public_course_admissible or plan is None
            or request.stage not in {"lesson_authoring", "tutor_focus"}
            or not plan.synthetic_fixture or report.status != "satisfied"
            or report.freshness_state != "current" or report.version_state != "exact"
            or report.budget_state != "within"
            or report.reason_codes not in ((), ("EMBEDDING_UNAVAILABLE",))
            or (request.embedding_mode == "disabled" and report.reason_codes)
            or not result.evidence
            or len(result.evidence) > plan.budget.max_chunks):
        return blocked
    request_hash = stable_hash(request.model_dump(mode="json"))
    plan_fields = {name: getattr(plan, name) for name in type(plan).model_fields if name != "plan_hash"}
    if (request_hash != result.request_hash or plan.request_hash != request_hash
            or report.request_hash != request_hash or plan.plan_hash != stable_hash(plan_fields)
            or report.report_hash != stable_hash(report.model_dump(exclude={"report_hash"}))
            or result.result_hash != stable_hash((plan.plan_hash, report.report_hash,
                                                 tuple(item.model_dump(mode="json") for item in result.evidence)))
            or plan.subject_id != request.subject_id or plan.subject_version != request.subject_version
            or plan.stage != request.stage or plan.required_facets != request.required_facets
            or plan.optional_facets != request.optional_facets
            or report.subject_id != plan.subject_id or report.subject_version != plan.subject_version
            or report.corpus_id != plan.corpus_id or report.corpus_summary_hash != plan.corpus_summary_hash
            or report.registry_digest != plan.registry_digest
            or report.required_facets != plan.required_facets or report.covered_facets != plan.required_facets
            or report.missing_facets or report.used_chunks != len(result.evidence)):
        return blocked
    active = _active(conn, request.subject_id)
    if active is None:
        return blocked
    version, generation = active
    selector = request.corpus_selector
    if (version["id"] != plan.corpus_id or version["summary_hash"] != plan.corpus_summary_hash
            or version["content_hash"] != plan.corpus_content_hash
            or version["registry_digest"] != plan.registry_digest
            or version["subject_version"] != plan.subject_version
            or version["retrieval_policy_version"] != plan.retrieval_policy_version
            or version["coverage_policy_version"] != plan.coverage_policy_version
            or (isinstance(selector, ActiveCorpusSelector)
                and ((selector.expected_generation is not None and selector.expected_generation != generation)
                     or (selector.expected_summary_hash is not None
                         and selector.expected_summary_hash != version["summary_hash"])))
            or (not isinstance(selector, ActiveCorpusSelector)
                and (selector.corpus_id != version["id"]
                     or selector.expected_summary_hash != version["summary_hash"]))):
        return blocked
    rows = _verified_rows(conn, version)
    if rows is None:
        return blocked
    # A matching self-reported hash does not make the injected plan authoritative.
    # Re-resolve under the caller's coherent read-only snapshot to bind the
    # named budget and complete allowed source scope.
    authoritative_plan, _ = resolve_plan(conn, request)
    if authoritative_plan is None or plan != authoritative_plan:
        return blocked
    lessons: list[LessonSourceSnapshot] = []
    tutor: list[AgentGroundingItem] = []
    identities: list[ShadowEvidenceIdentity] = []
    seen: set[str] = set()
    for evidence in result.evidence:
        row = rows.get(evidence.chunk_id)
        if row is None or evidence.chunk_id in seen:
            return blocked
        seen.add(evidence.chunk_id)
        source, document, chunk = row
        if (any(getattr(evidence, field) != chunk[column] for field, column in (
                ("chunk_id", "chunk_id"), ("source_id", "source_id"),
                ("document_id", "document_id"), ("title", "title"),
                ("section_path", "section_path"), ("content", "content"),
                ("trust_tier", "trust_tier"), ("source_hash", "source_hash"),
                ("document_hash", "document_hash"), ("chunk_hash", "chunk_hash")))
                or evidence.facets != tuple(chunk["facets_json"])
                or evidence.estimated_tokens != len(chunk["content"].encode("utf-8"))
                or source["source_id"] not in plan.allowed_source_ids
                or source["trust_tier"] not in plan.allowed_trust_tiers
                or len(chunk["content"]) > 800):
            return blocked
        identities.append(ShadowEvidenceIdentity(
            source_id=evidence.source_id, document_id=evidence.document_id,
            chunk_id=evidence.chunk_id, source_hash=evidence.source_hash,
            document_hash=evidence.document_hash, chunk_hash=evidence.chunk_hash,
        ))
        identity = (str(plan.corpus_id), plan.subject_id, plan.subject_version,
                    evidence.source_id, evidence.document_id, evidence.chunk_id,
                    evidence.chunk_hash, plan.corpus_summary_hash)
        citation_id = f"cite_{stable_hash(identity)[:16]}"
        # Legacy has no `fixture` source type. `reference` is a shape-only
        # placeholder; internal trust and the public-blocked wrapper are mandatory.
        citation = GroundingCitation(
            citation_id=citation_id, source_id=evidence.source_id, title=evidence.title,
            section_path=(evidence.section_path,), canonical_url=document["canonical_url"],
            source_type="reference", source_trust_tier="internal", source_version_label=FIXTURE_VERSION,
            source_version_kind="fixed", document_content_hash=evidence.document_hash,
            content_hash=evidence.chunk_hash, fetched_at=document["fetched_at"],
        )
        lessons.append(LessonSourceSnapshot(
            citation_id=citation_id, source_id=evidence.source_id,
            display_name=evidence.title, provider="Aearn synthetic fixture", trust_tier="internal",
            source_type="reference", source_version_label=FIXTURE_VERSION,
            source_version_kind="fixed", canonical_url=document["canonical_url"],
            section_path=(evidence.section_path,),
            grounding_chunk_id=f"v2-shadow:{stable_hash(identity)[:32]}",
            document_content_hash=evidence.document_hash, chunk_content_hash=evidence.chunk_hash,
            fetched_at=document["fetched_at"], snapshotted_at=document["fetched_at"],
            evidence_excerpt=evidence.content,
        ))
        tutor.append(AgentGroundingItem(
            content=evidence.content, citation=citation, relevance_score=0.0,
            match_reasons=("synthetic_fixture", "v2_shadow"),
        ))
    if (not 1 <= plan.minimum_source_diversity <= min(2, len(plan.required_facets))
            or report.source_count != len({item.source_id for item in result.evidence})
            or report.source_count < plan.minimum_source_diversity
            or report.trust_tiers != tuple(sorted({item.trust_tier for item in result.evidence}))
            or report.used_characters != sum(len(item.content) for item in result.evidence)
            or report.used_estimated_tokens != sum(item.estimated_tokens for item in result.evidence)
            or report.used_characters > plan.budget.max_characters
            or report.used_estimated_tokens > plan.budget.max_estimated_tokens
            or set(report.covered_facets) != {
                facet for item in result.evidence for facet in item.facets
                if facet in plan.required_facets
            }):
        return blocked
    return ShadowLegacyGrounding(
        status=ShadowGroundingStatus(request.subject_id, "active_fixture"),
        subject_version=plan.subject_version, corpus_id=plan.corpus_id,
        corpus_summary_hash=plan.corpus_summary_hash,
        corpus_content_hash=plan.corpus_content_hash, registry_digest=plan.registry_digest,
        evidence_identities=tuple(identities),
        lesson_sources=tuple(lessons), tutor_items=tuple(tutor),
    )
