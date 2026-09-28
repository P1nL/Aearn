"""Root-only, default-off admission of one already settled SQLite SELECT capture.

No fetch, provider, network or key creation. The private signed review file stays
provisional; only the dedicated DB commit establishes admission and partial CAS.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.grounding.autonomous.corpus_governance import CorpusGovernance, PostgresCorpusAuthority
from app.services.grounding.autonomous.registered_source_bridge_host import SignedDispatchProofVerifier
from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
from app.services.grounding.autonomous.sqlite_select_automated_review import (
    SignedAutomatedReview, SQLiteSelectAutomatedReviewVerifier,
    canonical_signed_review, evaluate, sign_service_review,
)
from app.services.grounding.autonomous.sqlite_select_quality import SQLITE_SELECT_URL
from app.services.grounding.corpus_contracts import CorpusCandidate, CorpusChunk, CorpusDocument, CorpusSource
from app.services.grounding.corpus_repository import _hash
from app.services.grounding.subject_registry import get_grounding_subject
from control_runtime import CONFIG, DB, HASH, PIN, _absolute, _root_file, _root_json
from review_operator import _private_output
from protocol import Scope

KEY_ID = "service.sqlite-select.core.v1"
SERVICE_PUBLIC_SHA256 = "c3f7b56d5ccf7fa765ca6fabc50c9f519b18d8e5b0f032673cb1474906109e68"
RUN_ID = re.compile(r"[A-Za-z0-9._:-]{8,100}\Z")
PURPOSE = "supplementary_explanation"


def _inputs(config_path: Path, private_path: Path, public_path: Path,
            public_sha256: str) -> tuple[dict, str, Ed25519PrivateKey, bytes, Scope, SignedDispatchProofVerifier]:
    config, _ = _root_json(config_path)
    if set(config) != CONFIG or config["approved"] is not True:
        raise ValueError("CONFIG_DENIED")
    database = config["database_name"]
    secret, _ = _root_file(_absolute(config["dsn_secret_path"]), limit=4096)
    dsn = secret.decode("utf-8").strip()
    if (type(database) is not str or DB.fullmatch(database) is None
            or not dsn or "\n" in dsn or "\r" in dsn
            or psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") != database):
        raise ValueError("DATABASE_DENIED")
    scope = Scope.from_wire(config["scope"])
    if (scope.url != SQLITE_SELECT_URL or scope.subject_id != "route.sql"
            or scope.facets != ("queries",) or scope.host != "www.sqlite.org"
            or scope.path != "/lang_select.html"):
        raise ValueError("SCOPE_DENIED")
    pin = config["b_attestor"]
    if (type(pin) is not dict or set(pin) != PIN
            or type(pin["public_key_hex"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", pin["public_key_hex"]) is None
            or type(config["worker_image_sha256"]) is not str
            or HASH.fullmatch(config["worker_image_sha256"]) is None):
        raise ValueError("PIN_DENIED")
    transport = SignedDispatchProofVerifier(
        public_key=bytes.fromhex(pin["public_key_hex"]),
        deployment_id=pin["deployment_id"], policy_sha256=pin["policy_sha256"],
        namespace_inode=pin["namespace_inode"], allowed_ips=frozenset(pin["allowed_ips"]),
    )
    if transport._key_sha256 != pin["public_key_sha256"]:
        raise ValueError("PIN_DENIED")
    if type(public_sha256) is not str or public_sha256 != SERVICE_PUBLIC_SHA256:
        raise ValueError("SERVICE_PIN_DENIED")
    private_bytes, _ = _root_file(_absolute(str(private_path)), limit=64)
    public_bytes, _ = _root_file(_absolute(str(public_path)), limit=64)
    if (len(private_bytes) != 32 or len(public_bytes) != 32
            or hashlib.sha256(public_bytes).hexdigest() != public_sha256):
        raise ValueError("SERVICE_PIN_DENIED")
    key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    actual_public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    if actual_public != public_bytes:
        raise ValueError("SERVICE_PIN_DENIED")
    return config, dsn, key, public_bytes, scope, transport


def _save_provisional(path: Path, signed_review: SignedAutomatedReview, *,
                      run_id: str, corpus_id: UUID, capture_id: UUID) -> None:
    destination = _private_output(_absolute(str(path)))
    raw = json.dumps({
        "status": "provisional_not_database_commit",
        "run_id": run_id,
        "corpus_id": str(corpus_id), "capture_id": str(capture_id),
        "service_public_sha256": SERVICE_PUBLIC_SHA256,
        "signed_review": json.loads(canonical_signed_review(signed_review)),
    }, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 8192:
        raise ValueError("RECEIPT_OVERSIZE")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        # Only this invocation's O_EXCL-created output can be removed.
        destination.unlink()
        raise


def _read_provisional(path: Path, *, run_id: str, corpus_id: UUID,
                      capture_id: UUID) -> SignedAutomatedReview:
    document, _ = _root_json(_private_output(_absolute(str(path))))
    if (set(document) != {"status", "run_id", "corpus_id", "capture_id",
                          "service_public_sha256", "signed_review"}
            or document["status"] != "provisional_not_database_commit"
            or document["run_id"] != run_id or document["corpus_id"] != str(corpus_id)
            or document["capture_id"] != str(capture_id)
            or document["service_public_sha256"] != SERVICE_PUBLIC_SHA256):
        raise ValueError("RECEIPT_MISMATCH")
    signed = SignedAutomatedReview.model_validate_json(json.dumps(document["signed_review"]))
    if (signed.service_key_id != KEY_ID or signed.payload.capture_id != capture_id
            or signed.payload.profile != "sqlite-select-exact-excerpts-v1"
            or signed.payload.quality_scope != "approved_excerpts_only"
            or signed.payload.usages != (PURPOSE,)):
        raise ValueError("RECEIPT_MISMATCH")
    return signed

def _snapshot(*, capture: object, row: dict, scope: Scope, corpus_id: UUID,
              excerpts: tuple[str, ...]) -> tuple[CorpusCandidate, CorpusSource, CorpusDocument, tuple[CorpusChunk, ...], str]:
    subject = get_grounding_subject("route.sql")
    if (subject is None or row["origin"] not in ("official", "maintainer", "tutorial", "repository", "community", "blog")
            or not excerpts or len(excerpts) > 12 or len(set(excerpts)) != len(excerpts)):
        raise ValueError("SNAPSHOT_DENIED")
    trust = "official" if row["origin"] == "official" else "trusted_de_facto"
    body = capture.body
    if any(type(text) is not str or not text.strip() or len(text) > 8000
           or text.encode("utf-8") not in body for text in excerpts):
        raise ValueError("EXCERPT_DENIED")
    source_id = scope.source_handle
    document_id = f"{source_id}.select.{capture.capture_id.hex[:16]}"
    source_hash = _hash([source_id, scope.policy_id, scope.generation, capture.digest])
    common = dict(corpus_id=corpus_id, subject_id=scope.subject_id,
                  subject_version=scope.subject_version)
    candidate = CorpusCandidate(
        **common, registry_digest=_hash(subject.model_dump(mode="json")),
        retrieval_policy_version="fts-v2", coverage_policy_version="dynamic-c-v1",
    )
    source = CorpusSource(
        **common, source_id=source_id, source_hash=source_hash, trust_tier=trust,
        source_kind="documentation", source_version=capture.revision,
        allowed_domains=(scope.host,), seed_urls=(scope.url,), facets=("queries",),
    )
    document = CorpusDocument(
        **common, document_id=document_id, source_id=source_id, source_hash=source_hash,
        trust_tier=trust, canonical_url=scope.url, final_url=capture.final_url,
        content_type=row["content_type"], document_version=capture.revision,
        fetched_at=row["fetched_at"], document_hash=capture.digest, parse_status="parsed",
    )
    chunks = tuple(CorpusChunk(
        **common, chunk_id=f"chunk.{capture.capture_id.hex}.{n}",
        document_id=document_id, source_id=source_id, source_hash=source_hash,
        trust_tier=trust, document_hash=capture.digest, ordinal=n,
        title="SQLite SELECT", section_path=f"SELECT reviewed excerpt {n + 1}",
        content=text, facets=("queries",), topic_tags=(),
        chunk_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    ) for n, text in enumerate(excerpts))
    return candidate, source, document, chunks, document_id


def _existing_result(conn: object, governance: CorpusGovernance, *,
                     active: object, corpus_id: UUID, capture_id: UUID,
                     run_id: str, expected_generation: int) -> dict[str, object] | None:
    exists = conn.execute("SELECT 1 FROM grounding_corpus_versions WHERE id=%s", (corpus_id,)).fetchone()
    if exists is None:
        reviewed = conn.execute(
            "SELECT 1 FROM rag_source_reviews WHERE registered_capture_id=%s", (capture_id,),
        ).fetchone()
        if reviewed is not None:
            raise ValueError("CAPTURE_ALREADY_REVIEWED")
        return None
    if (active is None or active.corpus_id != corpus_id
            or active.generation != expected_generation + 1):
        raise ValueError("CORPUS_ALREADY_EXISTS")
    event = conn.execute(
        "SELECT 1 FROM grounding_corpus_events WHERE id=%s AND corpus_version_id=%s "
        "AND event_kind='activated' AND idempotency_key=%s AND expected_generation=%s",
        (active.activation_event_id, corpus_id, f"{run_id}.activate", expected_generation),
    ).fetchone()
    version = governance.repo.version(corpus_id)
    if (event is None or version.state != "published" or version.summary_hash is None
            or version.coverage_summary != {"required": 2, "covered": 1, "gap": 1, "partial": True}):
        raise ValueError("COMPLETION_UNVERIFIED")
    governance._verified(corpus_id, summary_hash=version.summary_hash, purpose=PURPOSE)
    _, links = governance._rows(corpus_id)
    if len(links) != 1 or links[0]["registered_capture_id"] != capture_id:
        raise ValueError("COMPLETION_UNVERIFIED")
    return {"status": "already_completed_isolated_db", "corpus_id": str(corpus_id),
            "gap": "schema", "consumer_enabled": False}

def admit_existing_capture(*, config_path: Path, capture_id: UUID, corpus_id: UUID,
                           run_id: str, expected_active_generation: int,
                           private_key_path: Path, public_key_path: Path,
                           public_key_sha256: str, receipt_output: Path,
                           approved: bool = False) -> dict[str, object]:
    """One DB transaction, with bounded receipt reuse and verified completion replay."""
    if not approved:
        raise ValueError("DEFAULT_OFF")
    if (type(capture_id) is not UUID or type(corpus_id) is not UUID
            or type(run_id) is not str or RUN_ID.fullmatch(run_id) is None
            or type(expected_active_generation) is not int or expected_active_generation < 0):
        raise ValueError("INPUT_DENIED")
    config, dsn, private, public, scope, transport = _inputs(
        config_path, private_key_path, public_key_path, public_key_sha256,
    )
    _private_output(_absolute(str(receipt_output)))
    receipt_exists = receipt_output.exists() or receipt_output.is_symlink()
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.transaction():
            current = conn.execute("SELECT current_database() AS name").fetchone()
            if current is None or current["name"] != config["database_name"]:
                raise ValueError("DATABASE_DENIED")
            now_row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
            if now_row is None or type(now_row["now"]) is not datetime:
                raise ValueError("CLOCK_DENIED")
            now = now_row["now"].astimezone(UTC)
            provenance = PostgresCurrentCaptureProvenanceResolver(
                conn, verifier=transport,
                worker_image_sha256=config["worker_image_sha256"],
            )
            reviewer = SourceReviewRepository(conn)
            capture, row = reviewer._capture(capture_id, "registered", now)
            if (capture.source_handle != scope.source_handle
                    or capture.scope.subject_id != scope.subject_id
                    or capture.scope.subject_version != scope.subject_version
                    or capture.scope.facets != scope.facets
                    or capture.final_url != scope.url
                    or row["policy_id"] != scope.policy_id
                    or row["policy_generation"] != scope.generation
                    or row["root_id"] != scope.root_id
                    or row["fetch_attempt_id"] != UUID(scope.dispatch_id)
                    or len(capture.body) > scope.max_bytes):
                raise ValueError("SCOPE_DENIED")
            governance = CorpusGovernance(conn, authority=PostgresCorpusAuthority(),
                                          source_reviews=reviewer, isolated_operator_enabled=True)
            active = governance.repo.active("route.sql")
            # An existing artifact is only a provisional review, never a DB receipt.
            # Its signature/body/provenance are reverified below in either path.
            if receipt_exists:
                signed = _read_provisional(
                    receipt_output, run_id=run_id, corpus_id=corpus_id, capture_id=capture_id,
                )
            else:
                if conn.execute("SELECT 1 FROM grounding_corpus_versions WHERE id=%s", (corpus_id,)).fetchone():
                    raise ValueError("RECEIPT_MISSING")
                if (active.generation if active else 0) != expected_active_generation:
                    raise ValueError("ACTIVE_GENERATION_STALE")
                expires_at = min(now + timedelta(hours=24), row["expires_at"],
                                 row["policy_retention"], row["retention_until"])
                if expires_at <= now:
                    raise ValueError("REVIEW_EXPIRED")
                if evaluate(capture).code != "SUPPORTED":
                    raise ValueError("AUTOMATED_REVIEW_QUARANTINED")
                signed = sign_service_review(
                    capture, provenance=provenance, private_key=private,
                    service_key_id=KEY_ID, now=now, expires_at=expires_at, enabled=True,
                )
            verifier = SQLiteSelectAutomatedReviewVerifier(
                review=signed, service_key_id=KEY_ID, service_public_key=public,
                provenance=provenance, enabled=True,
            )
            reviewer.verifier = verifier
            excerpts = reviewer.reviewed_excerpts(capture)
            if (excerpts is None or not excerpts
                    or verifier.reviewed_usages(capture) != (PURPOSE,)
                    or verifier.verify(capture).mode != "production"):
                raise ValueError("REVIEW_DENIED")
            candidate, source, document, chunks, document_id = _snapshot(
                capture=capture, row=row, scope=scope, corpus_id=corpus_id, excerpts=excerpts,
            )
            if receipt_exists:
                completed = _existing_result(
                    conn, governance, active=active, corpus_id=corpus_id,
                    capture_id=capture_id, run_id=run_id,
                    expected_generation=expected_active_generation,
                )
                if completed is not None:
                    return completed
            if (active.generation if active else 0) != expected_active_generation:
                raise ValueError("ACTIVE_GENERATION_STALE")
            # Write private *provisional* evidence before C mutation. On DB failure
            # this artifact cannot be misread as a committed admission receipt.
            if not receipt_exists:
                _save_provisional(receipt_output, signed, run_id=run_id,
                                  corpus_id=corpus_id, capture_id=capture_id)
            review_id = reviewer.review_and_admit(
                capture_id=capture_id, lane="registered", document_handle=document_id,
                requested_usages=(PURPOSE,), now=now,
            )
            admission_row = conn.execute(
                "SELECT id FROM rag_source_admissions WHERE review_id=%s AND active "
                "AND revoked_at IS NULL AND allowed_usages=ARRAY[%s]::text[]",
                (review_id, PURPOSE),
            ).fetchone()
            if admission_row is None:
                raise ValueError("ADMISSION_DENIED")
            governance.create_candidate(
                candidate, sources=(source,), documents=(document,), chunks=chunks,
                admissions={document_id: admission_row["id"]}, purpose=PURPOSE,
                idempotency_key=f"{run_id}.create",
            )
            governance.validate(corpus_id, expected_generation=0, purpose=PURPOSE,
                                idempotency_key=f"{run_id}.validate")
            sealed = governance.repo.version(corpus_id)
            if sealed.summary_hash is None or sealed.coverage_summary != {
                "required": 2, "covered": 1, "gap": 1, "partial": True,
            }:
                raise ValueError("PARTIAL_COVERAGE_DENIED")
            governance.activate(
                corpus_id, expected_generation=expected_active_generation,
                summary_hash=sealed.summary_hash, purpose=PURPOSE,
                idempotency_key=f"{run_id}.activate",
            )
            result = {"status": "partial_queries_activated_isolated_db",
                      "corpus_id": str(corpus_id), "gap": "schema", "consumer_enabled": False}
    # psycopg connection context commits before returning. No body/DSN/key output.
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Default-off existing C capture admission")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--capture-id", type=UUID, required=True)
    parser.add_argument("--corpus-id", type=UUID, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-active-generation", type=int, required=True)
    parser.add_argument("--service-private-key", type=Path, required=True)
    parser.add_argument("--service-public-key", type=Path, required=True)
    parser.add_argument("--service-public-sha256", required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        outcome = admit_existing_capture(
            config_path=args.config, capture_id=args.capture_id, corpus_id=args.corpus_id,
            run_id=args.run_id, expected_active_generation=args.expected_active_generation,
            private_key_path=args.service_private_key, public_key_path=args.service_public_key,
            public_key_sha256=args.service_public_sha256, receipt_output=args.receipt_output,
            approved=args.execute,
        )
    except Exception:
        # Library/DB exceptions can contain URLs, DSNs, key bytes or body.
        raise SystemExit("AUTOMATED_ADMISSION_DENIED") from None
    print(json.dumps(outcome, sort_keys=True))


if __name__ == "__main__":
    main()
