"""Local operator corpus governance; fixture-only ingestion and machine validation.

All network-backed ingestion is explicitly unsupported until Subject-specific versioned
source maps exist. No learner route, scheduler, or legacy grounding index uses this service.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection

from app.services.grounding.corpus_contracts import CorpusCandidate, CorpusChunk, CorpusDocument, CorpusEvent, CorpusSource
from app.services.grounding.corpus_fixtures import (
    FIXTURE_DOMAIN, FIXTURE_FETCHED_AT, FIXTURE_VERSION, FixtureSlice, digest,
    fixture_registry_digest, fixture_slices,
)
from app.services.grounding.corpus_repository import CorpusConflict, CorpusRepository, _hash
from app.services.grounding.subject_contracts import GroundingSubject
from app.services.grounding.subject_registry import get_grounding_subject


class CorpusOperationError(ValueError):
    """Stable, safe operator diagnostic; never contains source or provider text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _subject(subject_id: str) -> GroundingSubject:
    subject = get_grounding_subject(subject_id)
    if subject is None or subject.subject_id != subject_id:
        raise CorpusOperationError("SUBJECT_UNSUPPORTED")
    return subject


def _source(corpus_id: UUID, subject: GroundingSubject, item: FixtureSlice) -> CorpusSource:
    trust: Literal["official", "trusted_de_facto"] = (
        "official" if subject.source_trust_policy == "official" else "trusted_de_facto"
    )
    fields = {
        "subject_id": subject.subject_id, "subject_version": FIXTURE_VERSION,
        "source_id": item.source_id, "trust_tier": trust, "source_kind": "fixture",
        "source_version": FIXTURE_VERSION, "allowed_domains": (FIXTURE_DOMAIN,),
        "seed_urls": (item.url,), "facets": (item.facet,),
    }
    return CorpusSource(
        corpus_id=corpus_id, subject_id=subject.subject_id,
        subject_version=FIXTURE_VERSION, source_id=item.source_id,
        source_hash=digest(fields), trust_tier=trust, source_kind="fixture",
        source_version=FIXTURE_VERSION, allowed_domains=(FIXTURE_DOMAIN,),
        seed_urls=(item.url,), facets=(item.facet,),
    )


def _document(corpus_id: UUID, subject: GroundingSubject, item: FixtureSlice,
              source: CorpusSource, *, failed: bool = False) -> CorpusDocument:
    return CorpusDocument(
        corpus_id=corpus_id, document_id=f"{item.source_id}:document", source_id=item.source_id,
        subject_id=subject.subject_id, subject_version=FIXTURE_VERSION,
        source_hash=source.source_hash, trust_tier=source.trust_tier,
        canonical_url=item.url, final_url=item.url, content_type="text/plain",
        document_version=FIXTURE_VERSION, fetched_at=FIXTURE_FETCHED_AT,
        document_hash=digest("") if failed else _content_hash(item.content),
        parse_status="failed" if failed else "parsed",
        diagnostic_code="FIXTURE_PROCESS_FAILED" if failed else None,
    )


def _content_hash(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chunk(corpus_id: UUID, subject: GroundingSubject, item: FixtureSlice,
           source: CorpusSource, document: CorpusDocument) -> CorpusChunk:
    return CorpusChunk(
        corpus_id=corpus_id, chunk_id=f"{item.source_id}:chunk", document_id=document.document_id,
        source_id=item.source_id, subject_id=subject.subject_id, subject_version=FIXTURE_VERSION,
        source_hash=source.source_hash, trust_tier=source.trust_tier,
        document_hash=document.document_hash, ordinal=0, title=f"Fixture: {subject.subject_id} / {item.facet}",
        section_path=item.facet, content=item.content, facets=(item.facet,), topic_tags=(),
        chunk_hash=_content_hash(item.content),
    )


def _event(event: CorpusEvent) -> dict[str, object]:
    return {"event_id": str(event.event_id), "event_kind": event.event_kind,
            "corpus_id": str(event.corpus_id), "subject": event.subject_id,
            "summary_hash": event.summary_hash, "expected_generation": event.expected_generation,
            "observed_generation": event.observed_generation, "counts": event.counts,
            "reason_code": event.reason_code}


class CorpusService:
    def __init__(self, conn: Connection[dict[str, Any]], *,
                 fixture_renderer: Callable[[FixtureSlice], str] | None = None) -> None:
        self.conn = conn
        self.repo = CorpusRepository(conn)
        # Only content rendering can fail in tests; identity/scope are always server-owned.
        self._render = fixture_renderer or (lambda item: item.content)

    def status(self, subject_id: str) -> dict[str, object]:
        subject = _subject(subject_id)
        active = self.repo.active(subject.subject_id)
        rows = self.conn.execute(
            """SELECT id,state,generation,subject_version,summary_hash,coverage_summary_json
               FROM grounding_corpus_versions WHERE subject_id=%s
               ORDER BY created_at DESC,id DESC LIMIT 10""", (subject.subject_id,),
        ).fetchall()
        return {"ok": True, "code": "STATUS", "subject": subject.subject_id,
                "release_state": subject.release_state, "corpus_mode": "fixture_only",
                "active": None if active is None else {"corpus_id": str(active.corpus_id),
                         "generation": active.generation},
                "recent": [{"corpus_id": str(row["id"]), "state": row["state"],
                            "generation": row["generation"], "subject_version": row["subject_version"],
                            "summary_hash": row["summary_hash"],
                            "coverage": {key: row["coverage_summary_json"][key]
                                         for key in ("required", "covered", "source_diversity", "fixture_only")
                                         if key in row["coverage_summary_json"]}} for row in rows]}

    def reindex(self, subject_id: str, subject_version: str, *, mode: str,
                idempotency_key: str) -> dict[str, object]:
        subject = _subject(subject_id)
        if mode == "fetch":
            # Legacy language-level seed URLs are not Subject/version/facet-scoped.
            raise CorpusOperationError("FETCH_NOT_READY")
        if mode != "fixture" or subject_version != FIXTURE_VERSION:
            raise CorpusOperationError("VERSION_UNSUPPORTED")
        corpus_id = uuid5(NAMESPACE_URL, f"aearn-corpus-fixture-v1:{subject_id}:{subject_version}:{idempotency_key}")
        candidate = CorpusCandidate(
            corpus_id=corpus_id, subject_id=subject.subject_id, subject_version=subject_version,
            registry_digest=fixture_registry_digest(subject), retrieval_policy_version="fixture-fts-v1",
            coverage_policy_version="fixture-facets-v1",
        )
        items = fixture_slices(subject)
        # Render outside the DB transaction. A fixture renderer cannot supply source identity.
        rendered: list[tuple[FixtureSlice, str | None]] = []
        for item in items:
            try:
                text = self._render(item)
                rendered.append((item, text if text == item.content else None))
            except Exception:
                rendered.append((item, None))
        with self.conn.transaction():
            started = self.repo.create_candidate(candidate, idempotency_key=idempotency_key)
            completed = self.repo._replay("reindex_completed", idempotency_key, started.request_hash)
            if completed is not None:
                return {"ok": True, "code": "REINDEX_REPLAY", "mode": "fixture", **_event(completed)}
            failures = 0
            for item, rendered_text in rendered:
                source = _source(corpus_id, subject, item)
                self.repo.add_source(source)
                failed = rendered_text is None
                document = _document(corpus_id, subject, item, source, failed=failed)
                self.repo.add_document(document)
                if failed:
                    failures += 1
                else:
                    self.repo.add_chunk(_chunk(corpus_id, subject, item, source, document))
            completed = self.repo._append(
                kind="reindex_completed", key=idempotency_key, request_hash=started.request_hash,
                corpus_id=corpus_id, subject_id=subject.subject_id,
                counts={"sources": len(items), "documents": len(items), "chunks": len(items) - failures,
                        "failures": failures}, reason_code="FIXTURE_ONLY",
            )
            return {"ok": True, "code": "REINDEXED", "mode": "fixture", **_event(completed)}

    def _audit(self, corpus_id: UUID) -> tuple[bool, dict[str, str | int | bool], dict[str, str | int | bool]]:
        version = self.repo.version(corpus_id)
        subject = _subject(version.subject_id)
        if (version.subject_version != FIXTURE_VERSION
                or version.registry_digest != fixture_registry_digest(subject)):
            raise CorpusOperationError("REGISTRY_DRIFT")
        expected_candidate = CorpusCandidate(
            corpus_id=corpus_id, subject_id=subject.subject_id, subject_version=FIXTURE_VERSION,
            registry_digest=fixture_registry_digest(subject), retrieval_policy_version="fixture-fts-v1",
            coverage_policy_version="fixture-facets-v1",
        )
        items = fixture_slices(subject)
        expected = {item.source_id: (item, _source(corpus_id, subject, item)) for item in items}
        sources = self.conn.execute(
            "SELECT * FROM grounding_corpus_source_snapshots WHERE corpus_version_id=%s ORDER BY source_id", (corpus_id,),
        ).fetchall()
        documents = self.conn.execute(
            "SELECT * FROM grounding_corpus_documents WHERE corpus_version_id=%s ORDER BY document_id", (corpus_id,),
        ).fetchall()
        chunks = self.conn.execute(
            "SELECT *, (search_vector = to_tsvector('simple'::regconfig, title || ' ' || section_path || ' ' || content)) AS fts_ready "
            "FROM grounding_corpus_chunks WHERE corpus_version_id=%s ORDER BY chunk_id", (corpus_id,),
        ).fetchall()
        errors: set[str] = set()
        if (version.retrieval_policy_version != expected_candidate.retrieval_policy_version
                or version.coverage_policy_version != expected_candidate.coverage_policy_version):
            errors.add("POLICY_SCOPE_INVALID")
        receipts = self.conn.execute(
            """SELECT event_kind, idempotency_key, request_hash, reason_code, counts_json
               FROM grounding_corpus_events WHERE corpus_version_id=%s
                 AND event_kind IN ('reindex_started','reindex_completed')""", (corpus_id,),
        ).fetchall()
        started = next((row for row in receipts if row["event_kind"] == "reindex_started"), None)
        completed = next((row for row in receipts if row["event_kind"] == "reindex_completed"), None)
        if (len(receipts) != 2 or started is None or completed is None
                or started["request_hash"] != _hash(expected_candidate.model_dump(mode="json"))
                or completed["request_hash"] != started["request_hash"]
                or completed["idempotency_key"] != started["idempotency_key"]
                or completed["reason_code"] != "FIXTURE_ONLY"
                or corpus_id != uuid5(NAMESPACE_URL, f"aearn-corpus-fixture-v1:{subject.subject_id}:{FIXTURE_VERSION}:{started['idempotency_key']}")):
            errors.add("OPERATOR_PROVENANCE_INVALID")
        if len(sources) != len(expected) or {row["source_id"] for row in sources} != set(expected):
            errors.add("SOURCE_SCOPE_INVALID")
        for row in sources:
            item_source = expected.get(row["source_id"])
            if item_source is None:
                continue
            _, source = item_source
            if any((row[column] != value) for column, value in {
                "subject_id": subject.subject_id, "subject_version": FIXTURE_VERSION,
                "source_hash": source.source_hash, "trust_tier": source.trust_tier,
                "source_kind": "fixture", "source_version": FIXTURE_VERSION,
                "allowed_domains_json": list(source.allowed_domains),
                "seed_urls_json": list(source.seed_urls), "facets_json": list(source.facets),
            }.items()):
                errors.add("SOURCE_SCOPE_INVALID")
        covered: set[str] = set()
        for row in documents:
            entry = expected.get(row["source_id"])
            if entry is None:
                errors.add("DOCUMENT_SCOPE_INVALID")
                continue
            item, source = entry
            failed = row["parse_status"] == "failed"
            document = _document(corpus_id, subject, item, source, failed=failed)
            if any(row[column] != value for column, value in {
                "document_id": document.document_id, "source_hash": source.source_hash,
                "subject_id": subject.subject_id, "subject_version": FIXTURE_VERSION,
                "trust_tier": source.trust_tier, "canonical_url": item.url, "final_url": item.url,
                "content_type": "text/plain", "document_version": FIXTURE_VERSION,
                "document_hash": document.document_hash, "parse_status": document.parse_status,
                "fetched_at": FIXTURE_FETCHED_AT, "diagnostic_code": document.diagnostic_code,
            }.items()):
                errors.add("DOCUMENT_SCOPE_INVALID")
            if failed:
                errors.add("SOURCE_FAILURE")
        if len(documents) != len(expected):
            errors.add("DOCUMENT_SCOPE_INVALID")
        for row in chunks:
            entry = expected.get(row["source_id"])
            if entry is None:
                errors.add("CHUNK_SCOPE_INVALID")
                continue
            item, source = entry
            document = _document(corpus_id, subject, item, source)
            chunk = _chunk(corpus_id, subject, item, source, document)
            if any(row[column] != value for column, value in {
                "chunk_id": chunk.chunk_id, "document_id": chunk.document_id,
                "subject_id": subject.subject_id, "subject_version": FIXTURE_VERSION,
                "source_hash": chunk.source_hash, "trust_tier": chunk.trust_tier,
                "document_hash": chunk.document_hash, "ordinal": 0, "title": chunk.title,
                "section_path": item.facet, "content": item.content,
                "facets_json": [item.facet], "topic_tags_json": [], "chunk_hash": chunk.chunk_hash,
            }.items()) or not row["fts_ready"]:
                errors.add("CHUNK_SCOPE_INVALID")
            else:
                covered.add(item.facet)
        if len(chunks) != len(expected) or len({row["source_id"] for row in chunks}) != len(chunks):
            errors.add("CHUNK_SCOPE_INVALID")
        if completed is not None and completed["counts_json"] != {
            "sources": len(sources), "documents": len(documents), "chunks": len(chunks),
            "failures": sum(row["parse_status"] == "failed" for row in documents),
        }:
            errors.add("OPERATOR_PROVENANCE_INVALID")
        if not set(subject.required_facets) <= covered:
            errors.add("MISSING_FACETS")
        fts_index = self.conn.execute(
            """SELECT 1 FROM pg_index AS idx
               JOIN pg_class AS rel ON rel.oid=idx.indexrelid
               JOIN pg_am AS method ON method.oid=rel.relam
               JOIN pg_attribute AS col ON col.attrelid=idx.indrelid AND col.attname='search_vector'
               WHERE idx.indexrelid=to_regclass('idx_grounding_corpus_chunks_search')
                 AND idx.indisvalid AND idx.indisready AND method.amname='gin'
                 AND idx.indnatts=1 AND idx.indkey[0]=col.attnum"""
        ).fetchone()
        if fts_index is None:
            errors.add("FTS_UNAVAILABLE")
        passed = not errors and bool(chunks)
        coverage: dict[str, str | int | bool] = {
            "required": len(subject.required_facets), "covered": len(covered),
            "source_diversity": len({row["source_id"] for row in chunks}), "fixture_only": True,
        }
        validation: dict[str, str | int | bool] = {
            "passed": passed, "sources": len(sources), "documents": len(documents), "chunks": len(chunks),
            "error_count": len(errors), "reason_code": (
                "MISSING_FACETS" if "MISSING_FACETS" in errors else
                sorted(errors)[0] if errors else "FIXTURE_ONLY"
            ),
        }
        return passed, validation, coverage

    def _verified(self, corpus_id: UUID) -> None:
        """A repository-level boolean alone is not an operator validation receipt."""
        version = self.repo.version(corpus_id)
        passed, validation, coverage = self._audit(corpus_id)
        receipt = self.conn.execute(
            """SELECT id FROM grounding_corpus_events WHERE corpus_version_id=%s
               AND event_kind='validation_passed' AND summary_hash=%s LIMIT 1""",
            (corpus_id, version.summary_hash),
        ).fetchone()
        if (not passed or version.validation_summary != validation
                or version.coverage_summary != coverage or receipt is None):
            raise CorpusOperationError("CORPUS_SCOPE_INVALID")

    def validate(self, corpus_id: UUID, *, expected_generation: int,
                 idempotency_key: str) -> dict[str, object]:
        with self.conn.transaction():
            version = self.repo.version(corpus_id, for_update=True)
            # Pass/fail use distinct event kinds in the repository. A command-level
            # lock prevents the same validation key from crossing those kinds.
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                              (f"corpus:validation:{idempotency_key}",))
            prior_rows = self.conn.execute(
                """SELECT event_kind,corpus_version_id,expected_generation,request_hash
                   FROM grounding_corpus_events WHERE idempotency_key=%s
                     AND event_kind IN ('validation_passed','validation_failed')""",
                (idempotency_key,),
            ).fetchall()
            if len(prior_rows) > 1:
                raise CorpusConflict("ambiguous validation key")
            if prior_rows:
                prior = prior_rows[0]
                if prior["corpus_version_id"] != corpus_id or prior["expected_generation"] != expected_generation:
                    raise CorpusConflict("validation key reused with different request")
                replay = self.repo._replay(prior["event_kind"], idempotency_key, prior["request_hash"])
                assert replay is not None
                passed = prior["event_kind"] == "validation_passed"
                return {"ok": passed, "code": "VALIDATION_REPLAY", "mode": "fixture",
                        "coverage": version.coverage_summary, "validation": version.validation_summary,
                        **_event(replay)}
            passed, validation, coverage = self._audit(corpus_id)
            event = self.repo.finalize_validation(
                corpus_id, passed=passed, expected_generation=expected_generation,
                validation_summary=validation, coverage_summary=coverage, idempotency_key=idempotency_key,
            )
            return {"ok": passed, "code": "VALIDATED" if passed else "VALIDATION_FAILED",
                    "mode": "fixture", "coverage": coverage, "validation": validation, **_event(event)}

    def diff(self, candidate_id: UUID, *, idempotency_key: str) -> dict[str, object]:
        with self.conn.transaction():
            request_hash = digest(["diff-v1", str(candidate_id)])
            replay = self.repo._replay("diff_generated", idempotency_key, request_hash)
            if replay is not None:
                base_generation = replay.counts.get("base_generation", 0)
                base_event = self.conn.execute(
                    """SELECT corpus_version_id FROM grounding_corpus_events
                       WHERE subject_id=%s AND event_kind IN ('activated','rolled_back')
                       AND observed_generation=%s ORDER BY created_at DESC,id DESC LIMIT 1""",
                    (replay.subject_id, base_generation),
                ).fetchone() if base_generation else None
                return {"ok": True, "code": "DIFF_REPLAY", "mode": "fixture",
                        "base_corpus_id": str(base_event["corpus_version_id"]) if base_event else None,
                        "base_generation": base_generation, **_event(replay)}
            candidate = self.repo.version(candidate_id)
            if candidate.state != "validated" or candidate.summary_hash is None:
                raise CorpusConflict("diff requires a validated candidate")
            self._verified(candidate_id)
            # Serialize selection of the exact base with activate/rollback/retire.
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                              (f"corpus:pointer:{candidate.subject_id}",))
            active = self.repo.active(candidate.subject_id)
            base_id = active.corpus_id if active else None
            counts: dict[str, int] = {"base_generation": active.generation if active else 0}
            comparisons = (
                ("sources", "grounding_corpus_source_snapshots",
                 "source_id,source_hash,source_version,facets_json"),
                ("documents", "grounding_corpus_documents",
                 "document_id,source_id,document_version,document_hash,parse_status"),
                ("chunks", "grounding_corpus_chunks",
                 "chunk_id,source_id,document_id,chunk_hash,facets_json"),
            )
            for name, table, columns in comparisons:
                def fingerprints(corpus: UUID | None) -> set[str]:
                    if corpus is None:
                        return set()
                    rows = self.conn.execute(
                        f"SELECT {columns} FROM {table} WHERE corpus_version_id=%s", (corpus,),
                    ).fetchall()
                    return {digest(row) for row in rows}
                current, prior = fingerprints(candidate_id), fingerprints(base_id)
                counts[f"{name}_added"] = len(current - prior)
                counts[f"{name}_removed"] = len(prior - current)
            def facets(corpus: UUID | None) -> set[str]:
                if corpus is None:
                    return set()
                rows = self.conn.execute(
                    "SELECT facets_json FROM grounding_corpus_chunks WHERE corpus_version_id=%s", (corpus,),
                ).fetchall()
                return {facet for row in rows for facet in row["facets_json"]}
            current_facets, prior_facets = facets(candidate_id), facets(base_id)
            counts["facets_added"] = len(current_facets - prior_facets)
            counts["facets_removed"] = len(prior_facets - current_facets)
            base_version = self.repo.version(base_id) if base_id else None
            counts["versions_changed"] = int(
                base_version is not None and candidate.subject_version != base_version.subject_version
            )
            counts["coverage_changed"] = int(
                base_version is not None and candidate.coverage_summary != base_version.coverage_summary
            )
            report_hash = digest([str(candidate_id), candidate.summary_hash, str(base_id),
                                  active.generation if active else 0, counts])
            event = self.repo._append(
                kind="diff_generated", key=idempotency_key, request_hash=request_hash,
                corpus_id=candidate_id, subject_id=candidate.subject_id, summary_hash=report_hash,
                expected=active.generation if active else 0, observed=candidate.generation,
                counts=counts, reason_code="FIXTURE_ONLY",
            )
            return {"ok": True, "code": "DIFF", "mode": "fixture", "base_corpus_id": str(base_id) if base_id else None,
                    "base_generation": counts["base_generation"], **_event(event)}

    def activate(self, candidate_id: UUID, *, expected_generation: int, summary_hash: str,
                 idempotency_key: str) -> dict[str, object]:
        with self.conn.transaction():
            replay = self.repo._replay("activated", idempotency_key,
                                       _hash([str(candidate_id), expected_generation, summary_hash]))
            if replay is not None:
                return {"ok": True, "code": "ACTIVATION_REPLAY", "mode": "fixture", **_event(replay)}
            self._verified(candidate_id)
            event = self.repo.activate(candidate_id, expected_generation=expected_generation,
                                       summary_hash=summary_hash, idempotency_key=idempotency_key)
            return {"ok": True, "code": "ACTIVATED", "mode": "fixture", **_event(event)}

    def rollback(self, subject_id: str, target_corpus_id: UUID, *, expected_generation: int,
                 idempotency_key: str) -> dict[str, object]:
        subject = _subject(subject_id)
        with self.conn.transaction():
            replay = self.repo._replay("rolled_back", idempotency_key,
                                       _hash([subject.subject_id, str(target_corpus_id), expected_generation]))
            if replay is not None:
                return {"ok": True, "code": "ROLLBACK_REPLAY", "mode": "fixture", **_event(replay)}
            target = self.repo.version(target_corpus_id)
            if target.subject_id != subject.subject_id:
                raise CorpusOperationError("CORPUS_SCOPE_INVALID")
            self._verified(target_corpus_id)
            event = self.repo.rollback(subject.subject_id, target_corpus_id,
                                       expected_generation=expected_generation, idempotency_key=idempotency_key)
            return {"ok": True, "code": "ROLLED_BACK", "mode": "fixture", **_event(event)}

    def retire(self, corpus_id: UUID, *, idempotency_key: str) -> dict[str, object]:
        with self.conn.transaction():
            version = self.repo.version(corpus_id)
            # A retired version's generation was incremented by the original request.
            if version.state == "retired":
                replay = self.repo._replay("retired", idempotency_key,
                                           _hash([str(corpus_id), version.generation - 1]))
                if replay is not None:
                    return {"ok": True, "code": "RETIRE_REPLAY", "mode": "fixture", **_event(replay)}
            event = self.repo.retire(corpus_id, expected_generation=version.generation,
                                     idempotency_key=idempotency_key)
            return {"ok": True, "code": "RETIRED", "mode": "fixture", **_event(event)}
