"""Offline safety checks for the root-only admission runner; no real DB or GET."""
from __future__ import annotations

import hashlib
import importlib
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
SPEC = importlib.util.spec_from_file_location("rag_c_automated_admission", ROOT / "automated_admission.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SubjectScope = importlib.import_module("app.services.grounding.autonomous.contracts").SubjectScope
CompleteCapture = importlib.import_module(
    "app.services.grounding.autonomous.source_review_repository"
).CompleteCapture
Scope = importlib.import_module("protocol").Scope
CAPTURE = UUID("00000000-0000-0000-0000-000000000011")
CORPUS = UUID("00000000-0000-0000-0000-000000000012")
URL = "https://www.sqlite.org/lang_select.html"


class RunnerOfflineTests(unittest.TestCase):
    def _call(self, *, approved=False):
        return module.admit_existing_capture(
            config_path=Path("/etc/config"), capture_id=CAPTURE, corpus_id=CORPUS,
            run_id="stable-run-001", expected_active_generation=0,
            private_key_path=Path("/etc/private"), public_key_path=Path("/etc/public"),
            public_key_sha256="0" * 64, receipt_output=Path("/etc/output"),
            approved=approved,
        )

    def test_default_denies_before_files_or_database(self):
        with patch.object(module, "_inputs") as inputs, patch.object(module.psycopg, "connect") as connect:
            with self.assertRaisesRegex(ValueError, "DEFAULT_OFF"):
                self._call()
            inputs.assert_not_called()
            connect.assert_not_called()

    def test_invalid_run_id_denies_before_files_or_database(self):
        with patch.object(module, "_inputs") as inputs:
            with self.assertRaisesRegex(ValueError, "INPUT_DENIED"):
                module.admit_existing_capture(
                    config_path=Path("/etc/config"), capture_id=CAPTURE, corpus_id=CORPUS,
                    run_id="", expected_active_generation=0,
                    private_key_path=Path("/etc/private"), public_key_path=Path("/etc/public"),
                    public_key_sha256="0" * 64, receipt_output=Path("/etc/output"), approved=True,
                )
            inputs.assert_not_called()

    def test_snapshot_uses_only_exact_reviewed_substrings(self):
        body = b"<html><p>approved finite claim</p><p>unreviewed claim</p></html>"
        digest = hashlib.sha256(body).hexdigest()
        scope = Scope.from_wire({
            "policy_id": "registered.once", "generation": 1,
            "source_handle": "sqlite.select", "subject_id": "route.sql",
            "subject_version": "v1", "facets": ["queries"], "url": URL,
            "host": "www.sqlite.org", "path": "/lang_select.html",
            "root_id": "source.once", "dispatch_id": str(CAPTURE),
            "max_bytes": 8_388_608,
        })
        capture = CompleteCapture(
            capture_id=CAPTURE, lane="registered", body=body, digest=digest,
            revision=digest, scope=SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",)),
            source_handle="sqlite.select", final_url=URL, request_chain=(URL,),
            origin="official", reading_level="beginner", license_id="PublicDomain",
        )
        from datetime import UTC, datetime
        row = {"origin": "official", "content_type": "text/html", "fetched_at": datetime(2026, 9, 25, tzinfo=UTC)}
        _, _, _, chunks, _ = module._snapshot(
            capture=capture, row=row, scope=scope, corpus_id=CORPUS,
            excerpts=("approved finite claim",),
        )
        self.assertEqual(tuple(chunk.content for chunk in chunks), ("approved finite claim",))
        self.assertNotIn("unreviewed", chunks[0].content)
        with self.assertRaisesRegex(ValueError, "EXCERPT_DENIED"):
            module._snapshot(capture=capture, row=row, scope=scope, corpus_id=CORPUS,
                             excerpts=("invented claim",))

    def test_provisional_reuse_requires_exact_envelope_and_service_scope(self):
        from types import SimpleNamespace
        review = SimpleNamespace(service_key_id=module.KEY_ID, payload=SimpleNamespace(
            capture_id=CAPTURE, profile="sqlite-select-exact-excerpts-v1",
            quality_scope="approved_excerpts_only", usages=(module.PURPOSE,),
        ))
        envelope = {
            "status": "provisional_not_database_commit", "run_id": "stable-run-001",
            "corpus_id": str(CORPUS), "capture_id": str(CAPTURE),
            "service_public_sha256": module.SERVICE_PUBLIC_SHA256,
            "signed_review": {"placeholder": "parsed by model"},
        }
        with patch.object(module, "_private_output", side_effect=lambda p: p), patch.object(
            module, "_root_json", return_value=(envelope, None)
        ), patch.object(module.SignedAutomatedReview, "model_validate_json", return_value=review):
            result = module._read_provisional(Path(Path.cwd().anchor) / "private" / "receipt.json", run_id="stable-run-001",
                                              corpus_id=CORPUS, capture_id=CAPTURE)
            self.assertIs(result, review)
            with self.assertRaisesRegex(ValueError, "RECEIPT_MISMATCH"):
                module._read_provisional(Path(Path.cwd().anchor) / "private" / "receipt.json", run_id="other-run-id",
                                         corpus_id=CORPUS, capture_id=CAPTURE)

    def test_completed_replay_requires_exact_active_event_and_current_audit(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        event_id = UUID("00000000-0000-0000-0000-000000000013")
        active = SimpleNamespace(corpus_id=CORPUS, generation=1, activation_event_id=event_id)
        version = SimpleNamespace(state="published", summary_hash="a" * 64,
                                  coverage_summary={"required": 2, "covered": 1, "gap": 1, "partial": True})
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [(1,), (1,), (1,)]
        governance = MagicMock()
        governance.repo.version.return_value = version
        governance._rows.return_value = (version, [{"registered_capture_id": CAPTURE}])
        result = module._existing_result(conn, governance, active=active, corpus_id=CORPUS,
                                         capture_id=CAPTURE, run_id="stable-run-001", expected_generation=0)
        self.assertEqual(result["status"], "already_completed_isolated_db")
        governance._verified.assert_called_once_with(CORPUS, summary_hash="a" * 64,
                                                       purpose=module.PURPOSE)
        with self.assertRaisesRegex(ValueError, "CORPUS_ALREADY_EXISTS"):
            module._existing_result(conn, governance, active=active, corpus_id=CORPUS,
                                    capture_id=CAPTURE, run_id="stable-run-001", expected_generation=1)
    def test_receipt_is_exclusive_and_never_claims_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "receipt.json"
            with patch.object(module.os, "O_NOFOLLOW", 0, create=True), patch.object(module.os, "O_CLOEXEC", 0, create=True), patch.object(module, "_private_output", side_effect=lambda p: p), patch.object(
                module, "canonical_signed_review", return_value=b'{"signature_hex":"safe"}'
            ):
                module._save_provisional(path, object(), run_id="stable-run-001",
                                         corpus_id=CORPUS, capture_id=CAPTURE)
                content = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(content["status"], "provisional_not_database_commit")
                self.assertEqual(content["signed_review"], {"signature_hex": "safe"})
                with self.assertRaises(FileExistsError):
                    module._save_provisional(path, object(), run_id="stable-run-001",
                                         corpus_id=CORPUS, capture_id=CAPTURE)


if __name__ == "__main__":
    unittest.main()
