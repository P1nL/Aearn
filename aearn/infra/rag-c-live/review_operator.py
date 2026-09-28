"""Prepare an unsigned operator review draft for a previously settled C capture.

Runs in the trusted control environment only. No fetching, signing, admission,
activation or database writes. This is not a review or a quality authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.services.grounding.autonomous.registered_source_bridge_host import SignedDispatchProofVerifier
from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
from app.services.grounding.autonomous.sqlite_select_quality import SQLITE_SELECT_URL, SQLiteSelectQualityVerifier
from control_runtime import CONFIG, DB, HASH, _absolute, _root_file, _root_json
from protocol import Scope


def _private_output(path: Path) -> Path:
    if os.name != "posix" or os.geteuid() != 0 or not path.is_absolute():
        raise ValueError("OUTPUT_DENIED")
    for parent in path.parents:
        info = parent.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or mode & 0o022:
            raise ValueError("OUTPUT_DENIED")
        if parent == path.parent and mode & 0o077:
            raise ValueError("OUTPUT_DENIED")
    return path


def prepare_review(config_path: Path, capture_id: UUID, output_path: Path) -> None:
    """Check exact DB, current capture and pinned transport; create private draft."""
    config, _ = _root_json(config_path)
    if set(config) != CONFIG or config["approved"] is not True:
        raise ValueError("CONFIG_DENIED")
    database = config["database_name"]
    secret, _ = _root_file(_absolute(config["dsn_secret_path"]), limit=4096)
    dsn = secret.decode("utf-8").strip()
    if (type(database) is not str or DB.fullmatch(database) is None
            or not dsn or "\r" in dsn or "\n" in dsn
            or psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") != database):
        raise ValueError("DATABASE_DENIED")
    scope = Scope.from_wire(config["scope"])
    if (scope.url != SQLITE_SELECT_URL or scope.subject_id != "route.sql"
            or scope.facets != ("queries",)):
        raise ValueError("SCOPE_DENIED")
    pin = config["b_attestor"]
    verifier = SignedDispatchProofVerifier(
        public_key=bytes.fromhex(pin["public_key_hex"]),
        deployment_id=pin["deployment_id"], policy_sha256=pin["policy_sha256"],
        namespace_inode=pin["namespace_inode"],
        allowed_ips=frozenset(pin["allowed_ips"]),
    )
    if (verifier._key_sha256 != pin["public_key_sha256"]
            or HASH.fullmatch(config["worker_image_sha256"]) is None):
        raise ValueError("PIN_DENIED")
    destination = _private_output(_absolute(str(output_path)))
    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        row = conn.execute("SELECT current_database() AS name").fetchone()
        if row is None or row["name"] != database:
            raise ValueError("DATABASE_DENIED")
        clock = conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if clock is None or type(clock["now"]) is not datetime:
            raise ValueError("CLOCK_DENIED")
        capture, row = SourceReviewRepository(conn)._capture(
            capture_id, "registered", clock["now"]
        )
        if (capture.source_handle != scope.source_handle
                or capture.scope.subject_version != scope.subject_version
                or capture.scope.facets != scope.facets
                or capture.final_url != scope.url
                or row["policy_id"] != scope.policy_id
                or row["policy_generation"] != scope.generation
                or row["root_id"] != scope.root_id
                or row["fetch_attempt_id"] != UUID(scope.dispatch_id)
                or len(capture.body) > scope.max_bytes):
            raise ValueError("SCOPE_DENIED")
        digest = PostgresCurrentCaptureProvenanceResolver(
            conn, verifier=verifier,
            worker_image_sha256=config["worker_image_sha256"],
        ).resolve(capture)
        if type(digest) is not str or HASH.fullmatch(digest) is None:
            raise ValueError("PROVENANCE_DENIED")
        if SQLiteSelectQualityVerifier().audit(capture).code != "EVIDENCE_MISSING":
            raise ValueError("CAPTURE_DENIED")
        draft = {
            "status": "unsigned_draft_human_review_required",
            "payload": {
                "format": "aearn.sqlite-select.operator-review.v1",
                "capture_id": str(capture.capture_id), "lane": capture.lane,
                "source_handle": capture.source_handle,
                "scope": capture.scope.model_dump(mode="json"),
                "revision": capture.revision, "body_sha256": capture.digest,
                "body_bytes": len(capture.body), "final_url": capture.final_url,
                "request_chain": list(capture.request_chain),
                "origin": capture.origin, "reading_level": capture.reading_level,
                "license_id": capture.license_id, "provenance_digest": digest,
                "judgment": {
                    "version_fit": "unknown", "reading_fit": "unknown",
                    "technical_status": "unknown", "conflict_status": "unknown",
                    "known_error": "unknown", "covered_facets": [],
                    "lineage_family": "unknown",
                },
                "reviewed_at": None, "expires_at": None,
            },
            "human_review_required": [
                "privately inspect the complete captured body",
                "independently cross-check technical facts, version, conflicts and known errors",
                "assess reading fit, exact facet coverage and source lineage",
                "verify page attribution, license and current storage/use/retention grant",
                "supply review times and independently pinned reviewer signature only after judgment",
            ],
            "not_authority": ["not_signed", "not_qualified", "not_admitted", "not_active"],
        }
    finally:
        conn.rollback()
        conn.close()
    data = (json.dumps(draft, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        destination.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare private unsigned review draft")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--capture-id", type=UUID, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare_review(args.config, args.capture_id, args.output)
    except Exception:
        raise SystemExit("REVIEW_PREPARATION_DENIED") from None
    print("REVIEW_DRAFT_PREPARED_HUMAN_REVIEW_REQUIRED")


if __name__ == "__main__":
    main()