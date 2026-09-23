"""Caller-transaction-owned operator corpus repository (never commits or fetches)."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar

from psycopg.pq import TransactionStatus
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.services.grounding.corpus_contracts import (
    ActiveCorpus, CorpusCandidate, CorpusChunk, CorpusDocument, CorpusEvent,
    CorpusSource, CorpusVersion, EventKind,
)


class CorpusConflict(ValueError):
    """Stale generation, mismatched replay or illegal lifecycle step."""


class CorpusNotFound(LookupError):
    """Unknown corpus or Subject pointer."""


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


_UNSAFE_SUMMARY_NAMES = ("token", "secret", "credential", "password", "header", "prompt", "body", "url", "path")


def _json(value: Mapping[str, str | int | bool]) -> Jsonb:
    if len(json.dumps(value, ensure_ascii=False).encode()) > 8192 or len(value) > 32:
        raise ValueError("corpus summary exceeds operator-safe bounds")
    for key, item in value.items():
        if (not key or len(key) > 80 or not key.isascii() or not key[0].isalpha()
                or not key.replace("_", "").isalnum()
                or any(name in key.lower() for name in _UNSAFE_SUMMARY_NAMES)):
            raise ValueError("corpus summary contains unsafe field names")
        if type(item) is str:
            if (not item or len(item) > 80 or not item.isascii()
                    or not item.replace("_", "").replace("-", "").replace(".", "").isalnum()):
                raise ValueError("corpus summary contains unsafe text")
        elif type(item) is int:
            if not 0 <= item <= 999_999_999:
                raise ValueError("corpus summary count is out of bounds")
        elif type(item) is not bool:
            raise ValueError("corpus summary must contain only bounded scalar facts")
    return Jsonb(dict(value))


def _version(row: Mapping[str, Any]) -> CorpusVersion:
    return CorpusVersion(
        corpus_id=row["id"], subject_id=row["subject_id"], subject_version=row["subject_version"],
        registry_digest=row["registry_digest"], state=row["state"], generation=row["generation"],
        source_set_hash=row["source_set_hash"], content_hash=row["content_hash"], summary_hash=row["summary_hash"],
        retrieval_policy_version=row["retrieval_policy_version"], coverage_policy_version=row["coverage_policy_version"],
        coverage_summary=row["coverage_summary_json"], validation_summary=row["validation_summary_json"],
    )


def _event(row: Mapping[str, Any]) -> CorpusEvent:
    return CorpusEvent(
        event_id=row["id"], corpus_id=row["corpus_version_id"], subject_id=row["subject_id"],
        event_kind=row["event_kind"], operation_id=row["operation_id"], idempotency_key=row["idempotency_key"],
        request_hash=row["request_hash"], summary_hash=row["summary_hash"],
        expected_generation=row["expected_generation"], observed_generation=row["observed_generation"],
        counts=row["counts_json"], reason_code=row["reason_code"],
    )


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _atomic(method: Callable[Concatenate[CorpusRepository, _P], _T]) -> Callable[Concatenate[CorpusRepository, _P], _T]:
    """Isolate a failed operation without committing the caller-owned transaction."""
    @wraps(method)
    def wrapped(self: CorpusRepository, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        if self.conn.autocommit:
            raise ValueError("corpus writes require a caller-owned transaction")
        # psycopg's transaction() commits if idle; start the implicit caller transaction
        # before entering so this block is always a SAVEPOINT instead.
        if self.conn.info.transaction_status == TransactionStatus.IDLE:
            self.conn.execute("SELECT 1")
        with self.conn.transaction():
            return method(self, *args, **kwargs)
    return wrapped


class CorpusRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def version(self, corpus_id: UUID, *, for_update: bool = False) -> CorpusVersion:
        row = self.conn.execute(
            "SELECT * FROM grounding_corpus_versions WHERE id=%s" + (" FOR UPDATE" if for_update else ""),
            (corpus_id,),
        ).fetchone()
        if row is None:
            raise CorpusNotFound("corpus not found")
        return _version(row)

    def active(self, subject_id: str) -> ActiveCorpus | None:
        row = self.conn.execute("SELECT * FROM grounding_active_corpora WHERE subject_id=%s", (subject_id,)).fetchone()
        return None if row is None else ActiveCorpus(
            subject_id=row["subject_id"], corpus_id=row["corpus_version_id"],
            generation=row["generation"], activation_event_id=row["activation_event_id"],
        )

    def history(self, subject_id: str, *, limit: int = 40) -> tuple[CorpusEvent, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid history limit")
        rows = self.conn.execute(
            "SELECT * FROM grounding_corpus_events WHERE subject_id=%s ORDER BY created_at DESC,id DESC LIMIT %s",
            (subject_id, limit),
        ).fetchall()
        return tuple(_event(row) for row in rows)

    def _replay(self, kind: EventKind, key: str, request_hash: str) -> CorpusEvent | None:
        if not key or len(key) > 128 or not key.replace("-", "").replace("_", "").replace(":", "").replace(".", "").isalnum():
            raise ValueError("invalid idempotency key")
        # Serializes first writes as well as retries. A SELECT FOR UPDATE on absent rows does not.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"corpus:{kind}:{key}",))
        row = self.conn.execute(
            "SELECT * FROM grounding_corpus_events WHERE event_kind=%s AND idempotency_key=%s", (kind, key)
        ).fetchone()
        if row is None:
            return None
        event = _event(row)
        if event.request_hash != request_hash:
            raise CorpusConflict("idempotency key reused with different request")
        return event

    def _append(self, *, kind: EventKind, key: str, request_hash: str, corpus_id: UUID,
                subject_id: str, summary_hash: str | None = None, expected: int | None = None,
                observed: int | None = None, counts: Mapping[str, int] | None = None,
                reason_code: str | None = None) -> CorpusEvent:
        safe_counts = counts or {}
        if len(safe_counts) > 16 or any(
            not k or not k.isascii() or not k[0].isalpha() or not k.replace("_", "").isalnum()
            or len(k) > 80 or any(name in k.lower() for name in _UNSAFE_SUMMARY_NAMES)
            or type(v) is not int or not 0 <= v <= 999_999_999
            for k, v in safe_counts.items()
        ):
            raise ValueError("unsafe corpus event counts")
        row = self.conn.execute(
            """INSERT INTO grounding_corpus_events
               (id,corpus_version_id,subject_id,event_kind,operation_id,idempotency_key,request_hash,
                summary_hash,expected_generation,observed_generation,counts_json,reason_code)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (uuid4(), corpus_id, subject_id, kind, uuid4(), key, request_hash, summary_hash,
             expected, observed, Jsonb(dict(safe_counts)), reason_code),
        ).fetchone()
        assert row is not None
        return _event(row)

    @_atomic
    def create_candidate(self, candidate: CorpusCandidate, *, idempotency_key: str) -> CorpusEvent:
        request_hash = _hash(candidate.model_dump(mode="json"))
        replay = self._replay("reindex_started", idempotency_key, request_hash)
        if replay:
            return replay
        self.conn.execute(
            """INSERT INTO grounding_corpus_versions
               (id,subject_id,subject_version,registry_digest,retrieval_policy_version,coverage_policy_version)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (candidate.corpus_id,candidate.subject_id,candidate.subject_version,candidate.registry_digest,
             candidate.retrieval_policy_version,candidate.coverage_policy_version),
        )
        return self._append(kind="reindex_started", key=idempotency_key, request_hash=request_hash,
                            corpus_id=candidate.corpus_id, subject_id=candidate.subject_id)

    @_atomic
    def add_source(self, source: CorpusSource) -> None:
        self.conn.execute(
            """INSERT INTO grounding_corpus_source_snapshots
               (corpus_version_id,subject_id,subject_version,source_id,source_hash,trust_tier,source_kind,
                source_version,allowed_domains_json,seed_urls_json,facets_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (source.corpus_id,source.subject_id,source.subject_version,source.source_id,source.source_hash,
             source.trust_tier,source.source_kind,source.source_version,Jsonb(source.allowed_domains),
             Jsonb(source.seed_urls),Jsonb(source.facets)),
        )

    @_atomic
    def add_document(self, document: CorpusDocument) -> None:
        self.conn.execute(
            """INSERT INTO grounding_corpus_documents
               (corpus_version_id,document_id,source_id,subject_id,subject_version,source_hash,trust_tier,
                canonical_url,final_url,content_type,document_version,fetched_at,document_hash,parse_status,diagnostic_code)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (document.corpus_id,document.document_id,document.source_id,document.subject_id,
             document.subject_version,document.source_hash,document.trust_tier,document.canonical_url,
             document.final_url,document.content_type,document.document_version,document.fetched_at,
             document.document_hash,document.parse_status,document.diagnostic_code),
        )

    @_atomic
    def add_chunk(self, chunk: CorpusChunk) -> None:
        self.conn.execute(
            """INSERT INTO grounding_corpus_chunks
               (corpus_version_id,chunk_id,document_id,source_id,subject_id,subject_version,source_hash,
                trust_tier,document_hash,ordinal,title,section_path,content,facets_json,topic_tags_json,chunk_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (chunk.corpus_id,chunk.chunk_id,chunk.document_id,chunk.source_id,chunk.subject_id,
             chunk.subject_version,chunk.source_hash,chunk.trust_tier,chunk.document_hash,chunk.ordinal,
             chunk.title,chunk.section_path,chunk.content,Jsonb(chunk.facets),Jsonb(chunk.topic_tags),chunk.chunk_hash),
        )

    @_atomic
    def finalize_validation(self, corpus_id: UUID, *, passed: bool, expected_generation: int,
                            validation_summary: Mapping[str, str | int | bool],
                            coverage_summary: Mapping[str, str | int | bool],
                            idempotency_key: str) -> CorpusEvent:
        kind: EventKind = "validation_passed" if passed else "validation_failed"
        request_hash = _hash([str(corpus_id), passed, expected_generation, validation_summary, coverage_summary])
        replay = self._replay(kind, idempotency_key, request_hash)
        if replay:
            return replay
        version = self.version(corpus_id, for_update=True)
        if version.state != "candidate" or version.generation != expected_generation:
            raise CorpusConflict("validation requires current candidate generation")
        source_rows = self.conn.execute(
            "SELECT source_id,source_hash FROM grounding_corpus_source_snapshots WHERE corpus_version_id=%s ORDER BY source_id", (corpus_id,)
        ).fetchall()
        document_rows = self.conn.execute(
            "SELECT document_id,source_id,document_hash FROM grounding_corpus_documents WHERE corpus_version_id=%s ORDER BY document_id", (corpus_id,)
        ).fetchall()
        chunk_rows = self.conn.execute(
            "SELECT chunk_id,document_id,chunk_hash FROM grounding_corpus_chunks WHERE corpus_version_id=%s ORDER BY chunk_id", (corpus_id,)
        ).fetchall()
        if passed and (not source_rows or not document_rows or not chunk_rows):
            raise CorpusConflict("validated corpus requires persisted source, document and chunk")
        source_hash = _hash(source_rows)
        content_hash = _hash([document_rows,chunk_rows])
        summary_hash = _hash([str(corpus_id),version.registry_digest,source_hash,content_hash,
                              validation_summary,coverage_summary,version.retrieval_policy_version,
                              version.coverage_policy_version]) if passed else None
        row = self.conn.execute(
            """UPDATE grounding_corpus_versions SET state=%s,generation=generation+1,
               source_set_hash=%s,content_hash=%s,summary_hash=%s,
               validation_summary_json=%s,coverage_summary_json=%s,validated_at=CASE WHEN %s THEN now() ELSE NULL END
               WHERE id=%s AND state='candidate' AND generation=%s RETURNING id""",
            ("validated" if passed else "failed",source_hash,content_hash,summary_hash,
             _json(validation_summary),_json(coverage_summary),passed,corpus_id,expected_generation),
        ).fetchone()
        if row is None:
            raise CorpusConflict("candidate changed during validation")
        return self._append(kind=kind,key=idempotency_key,request_hash=request_hash,corpus_id=corpus_id,
                            subject_id=version.subject_id,summary_hash=summary_hash,expected=expected_generation,
                            observed=expected_generation+1,
                            counts={"sources":len(source_rows),"documents":len(document_rows),"chunks":len(chunk_rows)})

    @_atomic
    def record_diff(self, corpus_id: UUID, *, expected_generation: int, summary_hash: str,
                    idempotency_key: str, counts: Mapping[str, int]) -> CorpusEvent:
        request_hash = _hash([str(corpus_id),expected_generation,summary_hash,counts])
        replay = self._replay("diff_generated",idempotency_key,request_hash)
        if replay:
            return replay
        version = self.version(corpus_id)
        if version.state != "validated" or version.generation != expected_generation or version.summary_hash != summary_hash:
            raise CorpusConflict("diff requires exact validated corpus")
        return self._append(kind="diff_generated",key=idempotency_key,request_hash=request_hash,
                            corpus_id=corpus_id,subject_id=version.subject_id,summary_hash=summary_hash,
                            expected=expected_generation,observed=expected_generation,counts=counts)

    def _pointer_generation(self, subject_id: str, expected: int) -> int:
        # The absent first pointer is also serialized by the subject-scoped advisory lock.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"corpus:pointer:{subject_id}",))
        current = self.active(subject_id)
        observed = current.generation if current else 0
        if observed != expected:
            raise CorpusConflict("active corpus generation mismatch")
        return observed + 1

    def _advance_pointer(self, subject_id: str, corpus_id: UUID, generation: int, event: CorpusEvent) -> None:
        if generation == 1:
            self.conn.execute(
                """INSERT INTO grounding_active_corpora
                   (subject_id,corpus_version_id,generation,activation_event_id,activation_event_kind)
                   VALUES (%s,%s,1,%s,%s)""",
                (subject_id,corpus_id,event.event_id,event.event_kind),
            )
        else:
            row = self.conn.execute(
                """UPDATE grounding_active_corpora SET corpus_version_id=%s,generation=%s,
                   activation_event_id=%s,activation_event_kind=%s,updated_at=now()
                   WHERE subject_id=%s AND generation=%s RETURNING subject_id""",
                (corpus_id,generation,event.event_id,event.event_kind,subject_id,generation-1),
            ).fetchone()
            if row is None:
                raise CorpusConflict("active corpus generation changed")

    @_atomic
    def activate(self, corpus_id: UUID, *, expected_generation: int, summary_hash: str,
                 idempotency_key: str) -> CorpusEvent:
        request_hash = _hash([str(corpus_id),expected_generation,summary_hash])
        replay = self._replay("activated",idempotency_key,request_hash)
        if replay:
            return replay
        version = self.version(corpus_id)
        generation = self._pointer_generation(version.subject_id,expected_generation)
        version = self.version(corpus_id,for_update=True)
        if version.state != "validated" or version.summary_hash != summary_hash:
            raise CorpusConflict("activation requires exact validated summary hash")
        self.conn.execute(
            "UPDATE grounding_corpus_versions SET state='published',generation=generation+1,published_at=now() WHERE id=%s", (corpus_id,)
        )
        event = self._append(kind="activated",key=idempotency_key,request_hash=request_hash,
                             corpus_id=corpus_id,subject_id=version.subject_id,summary_hash=summary_hash,
                             expected=expected_generation,observed=generation)
        self._advance_pointer(version.subject_id,corpus_id,generation,event)
        return event

    @_atomic
    def rollback(self, subject_id: str, target_corpus_id: UUID, *, expected_generation: int,
                 idempotency_key: str) -> CorpusEvent:
        request_hash = _hash([subject_id,str(target_corpus_id),expected_generation])
        replay = self._replay("rolled_back",idempotency_key,request_hash)
        if replay:
            return replay
        generation = self._pointer_generation(subject_id,expected_generation)
        target = self.version(target_corpus_id,for_update=True)
        current = self.active(subject_id)
        if target.subject_id != subject_id or target.state != "published" or current is None or current.corpus_id == target_corpus_id:
            raise CorpusConflict("rollback requires another published corpus of the same Subject")
        event = self._append(kind="rolled_back",key=idempotency_key,request_hash=request_hash,
                             corpus_id=target_corpus_id,subject_id=subject_id,summary_hash=target.summary_hash,
                             expected=expected_generation,observed=generation)
        self._advance_pointer(subject_id,target_corpus_id,generation,event)
        return event

    @_atomic
    def retire(self, corpus_id: UUID, *, expected_generation: int, idempotency_key: str) -> CorpusEvent:
        request_hash = _hash([str(corpus_id),expected_generation])
        replay = self._replay("retired",idempotency_key,request_hash)
        if replay:
            return replay
        version = self.version(corpus_id)
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                          (f"corpus:pointer:{version.subject_id}",))
        version = self.version(corpus_id,for_update=True)
        if version.generation != expected_generation or version.state not in ("candidate","validated","published"):
            raise CorpusConflict("retirement requires current eligible corpus")
        current = self.active(version.subject_id)
        if current and current.corpus_id == corpus_id:
            raise CorpusConflict("active corpus cannot retire")
        self.conn.execute(
            "UPDATE grounding_corpus_versions SET state='retired',generation=generation+1,retired_at=now() WHERE id=%s", (corpus_id,)
        )
        return self._append(kind="retired",key=idempotency_key,request_hash=request_hash,
                            corpus_id=corpus_id,subject_id=version.subject_id,
                            summary_hash=version.summary_hash,expected=expected_generation,
                            observed=expected_generation+1)
