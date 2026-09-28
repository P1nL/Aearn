"""Offline preparation checks; no PG, network, signing or real review."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
API = ROOT.parents[1] / "services" / "api"
sys.path.insert(0, str(ROOT.parent / "rag-c-source-control"))
sys.path.insert(0, str(API))
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("rag_c_review_operator", ROOT / "review_operator.py")
assert SPEC and SPEC.loader
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)

SubjectScope = importlib.import_module(
    "app.services.grounding.autonomous.contracts"
).SubjectScope
CompleteCapture = importlib.import_module(
    "app.services.grounding.autonomous.source_review_repository"
).CompleteCapture

CAPTURE_ID = UUID("00000000-0000-0000-0000-000000000001")
DISPATCH_ID = UUID("00000000-0000-0000-0000-000000000002")
BODY = b"offline synthetic fixture"
DIGEST = hashlib.sha256(BODY).hexdigest()
URL = "https://www.sqlite.org/lang_select.html"


class Conn:
    def __init__(self, database="aearn_rag260_c_test"):
        self.database = database
        self.queries = []
        self.rolled_back = False
        self.closed = False

    def execute(self, query):
        self.queries.append(query)
        return self

    def fetchone(self):
        if len(self.queries) == 1:
            return {"name": self.database}
        from datetime import UTC, datetime
        return {"now": datetime(2026, 9, 25, tzinfo=UTC)}

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def config():
    key = b"a" * 32
    return {
        "approved": True, "database_name": "aearn_rag260_c_test",
        "dsn_secret_path": str(Path(Path.cwd().anchor) / "operator" / "dsn"),
        "directory": str(Path(Path.cwd().anchor) / "run" / "rag-c-control"),
        "arm_path": "/operator/arm.json", "scope": {
            "policy_id": "registered.once", "generation": 1,
            "source_handle": "sqlite.select", "subject_id": "route.sql",
            "subject_version": "v1", "facets": ["queries"], "url": URL,
            "host": "www.sqlite.org", "path": "/lang_select.html",
            "root_id": "source.once", "dispatch_id": str(DISPATCH_ID),
            "max_bytes": 8_388_608,
        },
        "b_attestor": {
            "public_key_hex": key.hex(),
            "public_key_sha256": hashlib.sha256(key).hexdigest(),
            "deployment_id": "b-one", "policy_sha256": "b" * 64,
            "namespace_inode": 123, "allowed_ips": ["8.8.8.8"],
        },
        "worker_uid": 12001, "worker_gid": 12002,
        "trusted_gid": 12003, "worker_image_sha256": "c" * 64,
        "deployment_id": "c-one",
    }


def capture():
    return CompleteCapture(
        CAPTURE_ID, "registered", BODY, DIGEST, DIGEST,
        SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",)),
        "sqlite.select", URL, (URL,), "official", "beginner", "PublicDomain",
    )


class ReviewPreparationTests(unittest.TestCase):
    def run_preparation(self, directory, *, database="aearn_rag260_c_test", digest="d" * 64):
        conn = Conn(database)
        path = Path(directory) / "draft.json"
        data = config()
        rows = (capture(), {
            "policy_id": "registered.once", "policy_generation": 1,
            "root_id": "source.once", "fetch_attempt_id": DISPATCH_ID,
        })
        with (patch.object(review.os, "O_NOFOLLOW", getattr(review.os, "O_NOFOLLOW", 0), create=True),
              patch.object(review, "_root_json", return_value=(data, None)),
              patch.object(review, "_root_file", return_value=(b"dbname=aearn_rag260_c_test", None)),
              patch.object(review, "_private_output", return_value=path),
              patch.object(review.psycopg, "connect", return_value=conn),
              patch.object(review, "SourceReviewRepository") as repository,
              patch.object(review, "PostgresCurrentCaptureProvenanceResolver") as provenance):
            repository.return_value._capture.return_value = rows
            provenance.return_value.resolve.return_value = digest
            if database != "aearn_rag260_c_test" or digest is None:
                with self.assertRaises(ValueError):
                    review.prepare_review(Path("/operator/config.json"), CAPTURE_ID, path)
            else:
                review.prepare_review(Path("/operator/config.json"), CAPTURE_ID, path)
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.closed)
        return path

    def test_unsigned_draft_never_contains_body_or_qualified_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.run_preparation(directory)
            text = path.read_text()
            draft = json.loads(text)
            self.assertNotIn(BODY.decode(), text)
            self.assertEqual(draft["payload"]["judgment"]["technical_status"], "unknown")
            self.assertEqual(draft["payload"]["judgment"]["covered_facets"], [])
            self.assertIsNone(draft["payload"]["reviewed_at"])
            self.assertTrue(draft["human_review_required"])
            self.assertNotIn("signature_hex", text)
            with self.assertRaises(FileExistsError):
                self.run_preparation(directory)

    def test_wrong_database_or_missing_proof_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.run_preparation(directory, database="other").exists())
            self.assertFalse(self.run_preparation(directory, digest=None).exists())

    def test_output_requires_root_only_private_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                review._private_output(Path(directory) / "draft.json")


if __name__ == "__main__":
    unittest.main()