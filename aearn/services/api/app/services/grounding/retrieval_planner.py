"""Server-owned bounded stage policies and exact published corpus resolution."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.services.grounding.corpus_fixture_policy import fixture_registry_digest, fixture_slices
from app.services.grounding.retrieval_contracts import (
    ActiveCorpusSelector, EvidenceBudgetPolicy, GroundingRetrievalPlan,
    GroundingRetrievalRequest, ReasonCode, stable_hash,
)
from app.services.grounding.subject_registry import get_grounding_subject
from app.services.grounding.subject_contracts import GroundingSubject

# Closed profiles. Complexity scales with the number of required facets, never a fixed top-k.
_STAGE_LIMITS: Mapping[str, tuple[int, int, int]] = {
    "plan_preflight": (3, 650, 180),
    "lesson_authoring": (4, 1200, 340),
    "tutor_focus": (2, 750, 210),
    "practice": (3, 900, 250),
    "review": (3, 800, 220),
}




def _fixture_registry_current(conn: Connection[dict[str, Any]], corpus_id: UUID,
                              subject: GroundingSubject, version: dict[str, Any]) -> bool:
    """Verify the *whole* bounded synthetic corpus, not just matching joined rows.

    Fixture data is a pure policy input, not an operator call. A lower-level
    publication with a copied registry digest must not authorize extra sources.
    """
    items = fixture_slices(subject)
    if version["registry_digest"] != fixture_registry_digest(subject):
        return False
    limit = len(items) + 1
    sources = conn.execute(
        "SELECT source_id,source_hash,trust_tier,source_kind,source_version,"
        "allowed_domains_json,seed_urls_json,facets_json FROM grounding_corpus_source_snapshots "
        "WHERE corpus_version_id=%s ORDER BY source_id LIMIT %s", (corpus_id, limit),
    ).fetchall()
    documents = conn.execute(
        "SELECT document_id,source_id,source_hash,trust_tier,canonical_url,final_url,"
        "content_type,document_version,document_hash,parse_status FROM grounding_corpus_documents "
        "WHERE corpus_version_id=%s ORDER BY document_id LIMIT %s", (corpus_id, limit),
    ).fetchall()
    chunks = conn.execute(
        "SELECT chunk_id,document_id,source_id,source_hash,trust_tier,document_hash,"
        "ordinal,title,section_path,content,facets_json,topic_tags_json,chunk_hash "
        "FROM grounding_corpus_chunks WHERE corpus_version_id=%s ORDER BY chunk_id LIMIT %s",
        (corpus_id, limit),
    ).fetchall()
    if any(len(rows) != len(items) for rows in (sources, documents, chunks)):
        return False
    trust = "official" if subject.source_trust_policy == "official" else "trusted_de_facto"
    source_by_id = {row["source_id"]: row for row in sources}
    document_by_id = {row["document_id"]: row for row in documents}
    chunk_by_id = {row["chunk_id"]: row for row in chunks}
    for item in items:
        source = source_by_id.get(item.source_id)
        document = document_by_id.get(f"{item.source_id}:document")
        chunk = chunk_by_id.get(f"{item.source_id}:chunk")
        source_hash = stable_hash({
            "subject_id": subject.subject_id, "subject_version": "fixture-v1",
            "source_id": item.source_id, "trust_tier": trust, "source_kind": "fixture",
            "source_version": "fixture-v1", "allowed_domains": ("fixtures.aearn.invalid",),
            "seed_urls": (item.url,), "facets": (item.facet,),
        })
        content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        if (source is None or document is None or chunk is None
                or any(source[key] != value for key, value in {
                    "source_hash": source_hash, "trust_tier": trust, "source_kind": "fixture",
                    "source_version": "fixture-v1", "allowed_domains_json": ["fixtures.aearn.invalid"],
                    "seed_urls_json": [item.url], "facets_json": [item.facet],
                }.items())
                or any(document[key] != value for key, value in {
                    "source_id": item.source_id, "source_hash": source_hash, "trust_tier": trust,
                    "canonical_url": item.url, "final_url": item.url, "content_type": "text/plain",
                    "document_version": "fixture-v1", "document_hash": content_hash,
                    "parse_status": "parsed",
                }.items())
                or any(chunk[key] != value for key, value in {
                    "document_id": document["document_id"], "source_id": item.source_id,
                    "source_hash": source_hash, "trust_tier": trust, "document_hash": content_hash,
                    "ordinal": 0, "title": f"Fixture: {subject.subject_id} / {item.facet}",
                    "section_path": item.facet, "content": item.content,
                    "facets_json": [item.facet], "topic_tags_json": [], "chunk_hash": content_hash,
                }.items())):
            return False
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
    return (version["source_set_hash"] == source_hash
            and version["content_hash"] == content_hash
            and version["summary_hash"] == summary_hash)


def resolve_plan(
    conn: Connection[dict[str, Any]], request: GroundingRetrievalRequest,
) -> tuple[GroundingRetrievalPlan | None, ReasonCode | None]:
    subject = get_grounding_subject(request.subject_id)
    if subject is None or subject.subject_id != request.subject_id:
        return None, "SUBJECT_UNKNOWN"
    declared = set(subject.required_facets) | set(subject.optional_facets)
    if not set((*request.required_facets, *request.optional_facets)) <= declared:
        return None, "FACET_INVALID"
    if isinstance(request.corpus_selector, ActiveCorpusSelector):
        pointer = conn.execute(
            "SELECT corpus_version_id,generation FROM grounding_active_corpora WHERE subject_id=%s",
            (subject.subject_id,),
        ).fetchone()
        if pointer is None:
            return None, "CORPUS_MISSING"
        selector = request.corpus_selector
        if selector.expected_generation is not None and pointer["generation"] != selector.expected_generation:
            return None, "CORPUS_STALE"
        corpus_id = pointer["corpus_version_id"]
    else:
        corpus_id = request.corpus_selector.corpus_id
    version = conn.execute(
        """SELECT id,subject_id,subject_version,state,registry_digest,summary_hash,source_set_hash,
                  content_hash,validation_summary_json,coverage_summary_json,
                  retrieval_policy_version,coverage_policy_version FROM grounding_corpus_versions WHERE id=%s""",
        (corpus_id,),
    ).fetchone()
    if version is None:
        return None, "CORPUS_MISSING"
    if version["subject_id"] != subject.subject_id or version["subject_version"] != request.subject_version:
        return None, "VERSION_MISMATCH"
    if version["state"] == "retired":
        return None, "CORPUS_RETIRED"
    if version["state"] != "published" or not version["summary_hash"] or not version["content_hash"]:
        return None, "CORPUS_UNPUBLISHED"
    # Phase I has only synthetic fixture receipts; real embedding/index governance
    # must have its own trusted persistent receipt before a future extension.
    if (version["retrieval_policy_version"] != "fixture-fts-v1"
            or version["coverage_policy_version"] != "fixture-facets-v1"
            or version["subject_version"] != "fixture-v1"):
        return None, "CORPUS_POLICY_UNSUPPORTED"
    if not _fixture_registry_current(conn, corpus_id, subject, version):
        return None, "CORPUS_STALE"
    expected = request.corpus_selector.expected_summary_hash
    if expected is not None and expected != version["summary_hash"]:
        return None, "CORPUS_STALE"
    # Source authorization is persisted with the immutable corpus, never supplied by the caller.
    allowed_trust: tuple[str, ...] = (
        ("official",) if subject.source_trust_policy == "official"
        else ("official", "trusted_de_facto") if subject.source_trust_policy == "trusted_de_facto"
        else ()
    )
    sources = conn.execute(
        """SELECT source_id,trust_tier FROM grounding_corpus_source_snapshots
           WHERE corpus_version_id=%s AND subject_id=%s AND subject_version=%s
             AND trust_tier=ANY(%s) AND facets_json ?| %s
           ORDER BY source_id LIMIT 96""",
        (corpus_id, subject.subject_id, request.subject_version, list(allowed_trust),
         list((*request.required_facets, *request.optional_facets))),
    ).fetchall()
    # A bounded query must not silently truncate a larger source registry.
    if not sources or len(sources) == 96:
        return None, "SOURCE_SCOPE_EMPTY"
    base_chunks, base_chars, base_tokens = _STAGE_LIMITS[request.stage]
    count = len(request.required_facets)
    scale = 1 if request.budget_profile == "standard" else 0.65
    budget = EvidenceBudgetPolicy(
        max_chunks=max(1, min(24, int((base_chunks + count) * scale))),
        max_characters=max(1, min(32000, int((base_chars + 450 * count) * scale))),
        max_estimated_tokens=max(1, min(8000, int((base_tokens + 125 * count) * scale))),
        per_facet_limit=min(16, 2 + count),
        per_channel_limit=min(96, 12 + 6 * count),
    )
    request_hash = stable_hash(request.model_dump(mode="json"))
    fields: dict[str, object] = {
        "request_hash": request_hash,
        "subject_id": subject.subject_id, "subject_version": request.subject_version,
        "corpus_id": corpus_id, "corpus_summary_hash": version["summary_hash"],
        "corpus_content_hash": version["content_hash"],
        "registry_digest": version["registry_digest"],
        "retrieval_policy_version": version["retrieval_policy_version"],
        "coverage_policy_version": version["coverage_policy_version"],
        "stage": request.stage, "required_facets": request.required_facets,
        "optional_facets": request.optional_facets,
        "allowed_source_ids": tuple(row["source_id"] for row in sources),
        "allowed_trust_tiers": tuple(tier for tier in ("official", "trusted_de_facto") if tier in allowed_trust),
        "minimum_source_diversity": min(2, count), "budget": budget,
        # This marks the phase-I fixture policy, not real-source authorization.
        "synthetic_fixture": version["retrieval_policy_version"] == "fixture-fts-v1"
        and version["coverage_policy_version"] == "fixture-facets-v1",
    }
    return GroundingRetrievalPlan.model_validate({**fields, "plan_hash": stable_hash(fields)}), None
