"""OFFLINE read-only protocol doubles/SQL contracts, NOT PostgreSQL acceptance."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation
from psycopg.pq import TransactionStatus
from pydantic import ValidationError

from app.services.grounding.autonomous.actual_d_lifecycle import (
    ACTUAL_D_FORMAT, EXPORT_LIMIT, assert_actual_d_purged, current_actual_d_epoch, export_actual_d_private,
    finish_actual_d_private_purge,
)
from app.services.grounding.autonomous.source_assessment_profiles import SignedSourceAssessment, SourceAssessmentDenied
from app.services.grounding.assessment_course_selection import AssessmentCourseSelectionProducer
from app.services.grounding.assessment_material_factory import compose_assessment_authority, create_assessment_material
from app.services.grounding.current_authorization import EvidenceDenied
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_binding_repository import PostgresMaterialBindingRepository
from app.services.repositories import local_user_data_repository as local
from tests.grounding import test_actual_d_finite_source as previous


@pytest.fixture
def installed_protocol(monkeypatch):
    """Extend original read-only D double with the new schema/epoch seam only."""
    original = previous.OfflineD.execute
    original_init = previous.AssessmentReceiptRepository.__init__

    def enabled_fixture(self, *args, **kwargs):
        kwargs.setdefault("actual_d_private_provenance_enabled", True)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(previous.AssessmentReceiptRepository, "__init__", enabled_fixture)

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        if "to_regprocedure" in q:
            row = {"installed": getattr(self, "installed", True)}
        elif "to_regclass('public.rag_actual_d_private_provenance')" in q:
            row = {"installed": getattr(self, "installed", True)}
        elif "rag_actual_d_private_epoch" in q:
            user, expected, _ = params
            epoch = getattr(self, "epoch", 1)
            if (str(user) != self.scope.user_id or self.owner_deleted or not getattr(self, "epoch_enabled", True)
                    or getattr(self, "reset_pending", False)
                    or (expected is not None and expected != epoch)):
                raise CheckViolation("offline context denied")
            row = {"epoch": epoch}
        else:
            return original(self, sql, params)
        return SimpleNamespace(fetchone=lambda: row)

    monkeypatch.setattr(previous.OfflineD, "execute", execute)


@pytest.mark.parametrize("regression", [
    previous.test_actual_d_python_new_identity_nonce_and_no_public_proof_relabel,
    previous.test_actual_d_current_goal_selection_and_confirmed_frozen_plan_fences,
    previous.test_actual_d_sqlite_three_capture_minimum_and_additive_bootstrap_contract,
])
def test_existing_actual_d_protocol_under_installed_private_epoch(regression, installed_protocol, monkeypatch):
    regression(monkeypatch)


def test_original_prepare_and_persist_gate_schema_owner_epoch_and_late_worker(installed_protocol, monkeypatch):
    conn = previous.OfflineD("python-state-update-v1")
    repo = previous.repository(monkeypatch, conn)
    conn.installed = False
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE|PRIVATE_PROVENANCE"):
        previous.prepare(repo, conn)
    conn.installed = True
    conn.reset_pending = True
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        previous.prepare(repo, conn)
    conn.reset_pending = False
    conn.epoch_enabled = False
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        previous.prepare(repo, conn)
    conn.epoch_enabled = True
    q = previous.prepare(repo, conn)
    assert q.actual_d.user_epoch == 1
    signed, _, _ = previous.sign(repo, q)
    conn.epoch = 2  # Original reset advanced epoch; retained draft is not permission.
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        repo.persist(signed)
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        repo._verify_current(signed)
    conn.epoch = 1
    conn.installed = False
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE|PRIVATE_PROVENANCE"):
        repo.persist(signed)
    assert conn.writes == []


def test_signed_epoch_and_format_cannot_be_null_relabelled_or_crossowned(installed_protocol, monkeypatch):
    conn = previous.OfflineD("python-state-update-v1")
    repo = previous.repository(monkeypatch, conn)
    q = previous.prepare(repo, conn)
    for value in (None, 0, -1, True, "1"):
        with pytest.raises(ValidationError):
            type(q.actual_d).model_validate(q.actual_d.model_dump(mode="json") | {"user_epoch": value})
    signed, _, _ = previous.sign(repo, q)
    for wrong_format in ("aearn.rag.fresh-assessment-source.v1", "aearn.rag.fresh-assessment-source.v2", None):
        payload = signed.model_dump(mode="json")
        payload["payload"]["format"] = wrong_format
        with pytest.raises(ValidationError):
            SignedSourceAssessment.model_validate_json(json.dumps(payload))
    wrong = q.actual_d.draft.model_copy(update={"user_id": str(uuid4())})
    with pytest.raises(SourceAssessmentDenied, match="ACTUAL_D_SCOPE_STALE"):
        repo.prepare_actual_d(**(conn.args() | {"draft": wrong}), capture_id=q.capture_id,
                              document_handle="document.wrong-owner")
    with pytest.raises(ValueError, match="owner/epoch invalid"):
        current_actual_d_epoch(conn, user_id=None)
    assert conn.writes == []


def test_actual_existing_factory_and_course_consumer_expose_missing_private_provenance(installed_protocol, monkeypatch):
    """Positive source verification does NOT imply source→material→496 reachability.

    Real factory/resolver/producer interfaces, no fake factory or true callback.
    With private links forbidden and no bridge, the consumer must stay pending.
    This test documents an OPEN gate; it is not the requested end-to-end positive.
    """
    conn = previous.OfflineD("python-state-update-v1")
    repo = previous.repository(monkeypatch, conn)
    q = previous.prepare(repo, conn)
    signed, _, _ = previous.sign(repo, q)
    assert repo._verify_current(signed)[0] == signed.payload
    execute = conn.execute
    corpus_reads = []

    def read_only(sql, params=()):
        if "FROM grounding_corpus_versions" in sql:
            corpus_reads.append((sql, params))
            # No legitimate shared private-admission links exist under503.
            return SimpleNamespace(fetchall=lambda: [])
        return execute(sql, params)

    monkeypatch.setattr(conn, "execute", read_only)
    _, authority = compose_assessment_authority(conn, receipts=repo, enabled=True)
    repo.actual_d_private_provenance_enabled = False  # Legacy missing-carrier diagnostic branch only.
    with pytest.raises(SourceAssessmentDenied, match="SOURCE_CORPUS_STALE"):
        create_assessment_material(conn, receipts=repo, authority=authority,
            claim_receipt_id=signed.payload.claim_handle, draft=conn.scope,
            node_id=q.actual_d.node_id, goal_hash=q.actual_d.goal_hash, enabled=True)
    teaching = object.__new__(EvidenceSelection)
    teaching.conn, teaching.selections = conn, PostgresMaterialBindingRepository(conn)
    producer = AssessmentCourseSelectionProducer(conn, receipts=repo, teaching_authority=teaching, enabled=True)
    with pytest.raises(EvidenceDenied, match="CLAIM_VERIFICATION_REQUIRED"):
        producer._finite_prepared(authority, signed.payload.claim_handle, q.actual_d.target_id)
    assert len(corpus_reads) == 2 and conn.writes == []


class ReadOnlyLifecycle:
    autocommit = False

    def __init__(self, owner):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.owner = owner
        self.installed = True
        self.remaining = 0
        self.rows = []
        self.queries = []
        self.children_present = False
        self.permit = False
        self.epoch = 1
        self.tail_called = False

    def execute(self, sql, params=()):
        assert sql.lstrip().startswith("SELECT"), "protocol double forbids writes"
        self.queries.append((sql, params))
        if "to_regprocedure" in sql:
            row = {"installed": self.installed}
        elif "to_regclass" in sql:
            row = {"present": "rag_actual_d_private_provenance" not in sql}
        elif "count(*) AS count" in sql:
            assert params == (ACTUAL_D_FORMAT, str(self.owner))
            row = {"count": self.remaining}
        elif "public.rag_actual_d_private_purge" in sql:
            assert params == (self.owner,)
            if self.remaining and (self.children_present or not self.permit or self.epoch <= 1):
                raise CheckViolation("offline original tail blocked")
            # Protocol response only; NOT evidence that PostgreSQL purged anything.
            self.tail_called = True
            self.remaining = 0
            self.permit = False
            row = None
        else:
            assert "private_user_id=%s" in sql and params == (self.owner, ACTUAL_D_FORMAT, EXPORT_LIMIT)
            row = None
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: self.rows)


def test_safe_bounded_export_and_unclassified_private_data_fail_closed():
    owner = uuid4()
    conn = ReadOnlyLifecycle(owner)
    conn.rows = [{"id": uuid4(), "issued_at": previous.NOW, "expires_at": previous.NOW,
                  "revoked_at": None, "total_count": 101, "signed_proof": {"user_id": str(uuid4())},
                  "proof_hash": "private-secret-hash"} for _ in range(EXPORT_LIMIT)]
    result = export_actual_d_private(conn, owner)
    assert result["count"] == 101 and result["has_more"] is True
    assert len(result["items"]) == EXPORT_LIMIT
    assert set(result["items"][0]) == {"id", "status", "issued_at", "expires_at", "revoked_at"}
    assert "signed_proof" not in json.dumps(result) and "private-secret-hash" not in json.dumps(result)
    conn.installed = False
    assert export_actual_d_private(conn, owner)["status"] == "lifecycle_not_installed"
    conn.remaining = 1
    with pytest.raises(ValueError, match="purge blocked"):
        export_actual_d_private(conn, owner)
    with pytest.raises(ValueError, match="purge blocked"):
        assert_actual_d_purged(conn, owner)


@pytest.mark.parametrize("permit,epoch,children", [(False, 2, False), (True, 1, False), (True, 2, True)])
def test_source_tail_needs_original_permit_advanced_epoch_and_removed_d_children(permit, epoch, children):
    owner = uuid4()
    conn = ReadOnlyLifecycle(owner)
    conn.remaining = 1
    conn.permit, conn.epoch, conn.children_present = permit, epoch, children
    with pytest.raises(CheckViolation, match="original tail blocked"):
        finish_actual_d_private_purge(conn, owner)
    assert conn.remaining == 1 and conn.tail_called is False


@pytest.mark.parametrize("deleting", [False, True])
def test_original_reset_delete_entrypoints_check_private_purge_before_d_parents(monkeypatch, deleting):
    owner = uuid4()
    conn = ReadOnlyLifecycle(owner)
    steps = []

    class ReachedDParents(Exception):
        pass

    monkeypatch.setattr(local, "_ensure_user", lambda *_: {"id": str(owner)})
    monkeypatch.setattr(local, "get_user_data_summary", lambda *_: {})
    monkeypatch.setattr(local, "_unlink_rag_refs", lambda *_: steps.append("unlink"))

    def original_epoch_purge(c, user, *, deleting=False):
        assert c is conn and user == owner
        steps.append(("original_epoch_purge", deleting))
        conn.epoch = 2
        conn.permit = bool(conn.remaining)
        return 2

    def d_parents(*_):
        steps.append("original D children")
        finish_actual_d_private_purge(conn, owner)
        steps.append("source tail checked")
        steps.append("D parents")
        raise ReachedDParents

    monkeypatch.setattr(local, "purge_private_supply", original_epoch_purge)
    monkeypatch.setattr(local, "_delete_learning_track_data", d_parents)
    entry = local.delete_user_data if deleting else local.reset_user_data
    conn.remaining = 1
    conn.children_present = True  # Missing D cleanup MUST block before draft parents.
    with pytest.raises(CheckViolation, match="tail blocked"):
        entry(conn, str(owner))
    assert "D parents" not in steps
    steps.clear()
    conn.children_present = False
    with pytest.raises(ReachedDParents):
        entry(conn, str(owner))
    assert conn.tail_called and conn.remaining == 0 and conn.permit is False
    assert steps == ["unlink", ("original_epoch_purge", deleting), "original D children", "source tail checked", "D parents"]


def test_503_conditional_sql_fk_and_original_guard_contracts():
    schema = Path(__file__).parents[2] / "app" / "db" / "schema"
    migration = (schema / "503_rag_actual_d_private_lifecycle.sql").read_text(encoding="utf8")
    assert "actual_d'->'draft'->>'user_id'" in migration and "user_epoch" in migration
    assert "CASE WHEN signed_proof->'payload'->>'format'" in migration
    assert "unclassified historical actual D proofs require explicit reconciliation" in migration
    assert "PERFORM rag_actual_d_private_epoch(NEW.private_user_id,NEW.private_epoch,false)" in migration
    assert "item_supply_internal.permitted(target_user)" in migration
    assert "actual D private reset in progress" in migration
    assert "u.epoch>e.private_epoch" in migration and "FOR SHARE NOWAIT" in migration
    assert "actual D private independent reference denied" in migration
    assert "actual D private cross admission reference denied" in migration
    assert "actual D private cross owner reference denied" in migration
    assert "actual D private reference to shared corpus blocked" in migration
    assert "AS scalars(value)" in migration
    assert "TG_TABLE_NAME=''rag_source_claim_receipts''" in migration
    deletes = re.findall(r"DELETE FROM (\w+)", migration)
    assert deletes == ["item_supply_internal", "public", "rag_source_claim_receipts", "rag_source_admissions", "rag_source_reviews", "rag_assessment_source_evidence", "item_supply_internal"]
    assert migration.count("private_user_id=target_user AND e.private_epoch<active_epoch") == 3
    assert "private_user_id=target_user AND private_epoch<active_epoch" in migration
    assert "DEFERRABLE INITIALLY DEFERRED" in migration
    assert "actual D source purge requires original D children first" in migration
    assert "actual D original reset tail incomplete" in migration
    assert "503 retain original permit until original D children are removed" in migration
    assert "purge_actual_d_private_on_epoch_advance" not in migration
    assert "UPDATE rag_" not in migration and "DISABLE TRIGGER" not in migration
    # The old 330/480 guards are byte-preserved; 503 only adds a scoped DELETE branch.
    for name, filename, expected in (
        ("rag_source_review_guard", "330_rag_source_admission.sql", "6894300a6cf1b8f31bf6c3f9284b22ec"),
        ("rag_source_admission_guard", "330_rag_source_admission.sql", "13104409dae8049b31adc7c77fdbcec1"),
        ("rag_source_claim_guard", "480_rag_assessment_execution_authority.sql", "7e473752ae96a43c5d455a5c2a931444"),
    ):
        text = (schema / filename).read_text(encoding="utf8")
        body = re.search(r"CREATE OR REPLACE FUNCTION " + name + r"\(\).*? AS \$\$(.*?)\$\$;", text, re.S).group(1)
        assert hashlib.md5(body.encode()).hexdigest() == expected and expected in migration
    assert "a547c4cf6f0710e894f294380f40f351" in migration
    original = (schema / "470_learning_item_supply_sandbox_execution.sql").read_text(encoding="utf8")
    body = re.search(r"CREATE OR REPLACE FUNCTION purge_item_supply_private\(.*? AS \$\$(.*?)\$\$;", original, re.S).group(1)
    assert hashlib.md5(body.encode()).hexdigest() == "550fef67701f985e654e310defe7858f"
    assert "550fef67701f985e654e310defe7858f" in migration
    local_source = Path(local.__file__).read_text(encoding="utf8")
    assert '"actual_d_private_source_summaries": export_actual_d_private(conn, UUID(user_id))' in local_source
    assert local_source.index('DELETE FROM rag_material_selections WHERE user_id') < local_source.index("finish_actual_d_private_purge(conn, UUID(user_id))")
    assert local_source.index("finish_actual_d_private_purge(conn, UUID(user_id))") < local_source.index("UPDATE tutor_learning_plan_sessions\n        SET status = 'cancelled'")


def test_complete_source_guard_digest_reconstructed_from_final_488_497_499():
    """Full prosrc, not a486 baseline or a hash copied from an earlier report."""
    schema = Path(__file__).parents[2] / "app" / "db" / "schema"
    original = (schema / "488_rag_public_sqlite_course_source.sql").read_text(encoding="utf8")
    body = re.search(r"CREATE OR REPLACE FUNCTION rag_assessment_source_evidence_guard\(\).*? AS \$\$(.*?)\$\$;", original, re.S).group(1)
    body = body.replace("(proof->>'format') IS DISTINCT FROM 'aearn.rag.fresh-assessment-source.v1'",
        "rag_course_material_proof_lifetime_allowed(NEW.signed_proof,NEW.profile_id,NEW.issued_at,NEW.expires_at) IS DISTINCT FROM true")
    line = "  SELECT * INTO capture FROM rag_registered_source_captures WHERE id=NEW.capture_id FOR SHARE;"
    body = body.replace(line, "  IF (NEW.signed_proof->'payload'->>'format')='aearn.rag.actual-d-finite-source.v3' THEN\n"
        "    PERFORM rag_actual_d_finite_source_scope_check(NEW);\n  END IF;\n" + line)
    for pattern in ("(NEW.profile_id IN ('python-state-source-v1','python-binding-source-v1') AND",
                    "(NEW.profile_id='sqlite-predicate-source-v1' AND"):
        body = body.replace(pattern, pattern + " (proof->>'format') IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3' AND")
    body = body.replace("(prepared->>'profile_id') IS DISTINCT FROM NEW.profile_id",
        "(CASE WHEN proof->>'format'='aearn.rag.actual-d-finite-source.v3' THEN rag_actual_d_finite_storage_profile(prepared->>'profile_id') ELSE prepared->>'profile_id' END) IS DISTINCT FROM NEW.profile_id")
    body = body.replace("(proof->'terminal'->>'probe_name') IS DISTINCT FROM 'source_assessment_oracle'",
        "(proof->'terminal'->>'probe_name') IS DISTINCT FROM (CASE WHEN proof->>'format'='aearn.rag.actual-d-finite-source.v3' THEN 'actual_d_finite_source_oracle' ELSE 'source_assessment_oracle' END)")
    body = body.replace("  RETURN NEW;\nEND ", "  IF proof->>'format'='aearn.rag.actual-d-finite-source.v3' THEN\n"
        "    clock := clock_timestamp();\n    IF NEW.issued_at>clock OR NEW.expires_at<=clock THEN\n"
        "      RAISE check_violation USING MESSAGE='actual D source proof expired after locks';\n"
        "    END IF;\n  END IF;\n  RETURN NEW;\nEND ")
    assert hashlib.md5(body.encode()).hexdigest() == "a547c4cf6f0710e894f294380f40f351"
    clause = ("  --503 conditional private deletion\n  IF TG_OP='DELETE' THEN\n"
              "    IF rag_actual_d_private_delete_allowed(OLD.id) THEN RETURN OLD; END IF;\n  END IF;\n")
    upgraded = body.replace("BEGIN\n", "BEGIN\n" + clause)
    assert upgraded.replace(clause, "") == body
    # This pin is only guard shape/replay evidence, not signer/runtime authority.
    assert hashlib.md5(upgraded.encode()).hexdigest() == "6cf698478cdeb60671238cd9f0dee2fe"
