"""OFFLINE orchestration only: doubles never confer real pack/publication authority."""
from __future__ import annotations

import builtins
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

RESEARCH = Path(__file__).resolve().parents[5] / ".trellis/tasks/09-22-multi-agent-item-bank-sandbox/research"


@pytest.fixture(scope="module")
def operator():
    spec = importlib.util.spec_from_file_location("native_kc_pack_live_20261008", RESEARCH / "native_kc_pack_live_20261008.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _contents(operator):
    # Deliberately synthetic only; production resolves these through original501.
    result = []
    for index, slot in enumerate(("practice", "practice", "assessment", "assessment", "remediation")):
        content = SimpleNamespace(version_id=uuid4(), item_handle=f"OFFLINE-{index}",
            content_hash=f"content-{index}", actual_public_task_hash=f"public-{index}",
            decision_signature=f"decision-{index}", answer_leakage_signature=f"answer-{index}",
            family_id="same-family", seed=10)
        # Reused distinct current versions may have the SAME allocation variant.
        allocation = SimpleNamespace(slot=slot, variant_id=operator.TARGET + ":" + slot + "-1")
        result.append(SimpleNamespace(content=content, spec=SimpleNamespace(target_id=operator.TARGET, allocation=allocation)))
    return tuple(result)


def test_plan_and_disabled_execute_are_zero_io(operator, monkeypatch, capsys):
    original_import = builtins.__import__

    def no_runtime(name, *args, **kwargs):
        if name.startswith(("app.", "psycopg", "dotenv")):
            pytest.fail("inert entry imported runtime")
        return original_import(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("inert entry attempted IO")

    monkeypatch.setattr(builtins, "__import__", no_runtime)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    for args in ([], ["--plan"]):
        assert operator.main(args) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["database_io"] is False and report["pack_passed"] is False
        assert report["provider_calls"] == report["GETs"] == report["key_reads"] == 0
    with pytest.raises(ValueError, match="main_execute_required"):
        operator.complete_kc_pack(None, operation_key="OFFLINE")
    with pytest.raises(SystemExit) as error:
        operator.main(["--execute"])
    assert error.value.code == 2


def test_pairs_follow_exact_221_and_actual_exposure_not_family_or_seed(operator):
    from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending

    contents = _contents(operator)
    assert contents[0].spec.allocation.variant_id == contents[1].spec.allocation.variant_id
    empty = SimpleNamespace(records=())
    pairs = operator._pairs(contents, empty)
    assert len(pairs) == 7
    training_pair = frozenset((contents[0].content.version_id, contents[1].content.version_id))
    assert training_pair not in {frozenset(p) for p in pairs}
    old = _contents(operator)[0].content
    old.item_handle, old.content_hash = "historical", "historical-content"
    old.actual_public_task_hash, old.decision_signature, old.answer_leakage_signature = "h-public", "h-decision", "h-answer"
    observed = SimpleNamespace(records=(SimpleNamespace(content=old),))
    assert len(operator._pairs(contents, observed)) == 9
    old.decision_signature = contents[2].content.decision_signature
    with pytest.raises(NativeTypeEvidencePending, match="clone_or_exposed"):
        operator._pairs(contents, observed)


class OfflineConnection:
    autocommit = False

    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.events = []

    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == TransactionStatus.IDLE
        self.events.append("begin")
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql):
        assert self.info.transaction_status == TransactionStatus.INTRANS
        assert sql == "SELECT current_database() AS name"
        return SimpleNamespace(fetchone=lambda: {"name": "aearn_b1d_sandbox_20261001"})


def _offline_setup(operator, monkeypatch, tmp_path, *, pending=False):
    from app.services.learning.item_bank.native_publication import NativeLearningItemPublicationService
    from app.services.learning.item_supply.native_relation_review import NativeRelationReviewProducer
    from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
    from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner

    # Concrete-class protocol doubles with ALL database/provider methods replaced.
    # Not live owners, receipts or acceptance. Only transaction choreography tested.
    conn = OfflineConnection()
    owner = object.__new__(NativeTypeEvidenceOwner)
    owner.conn, owner.user_id, owner.epoch = conn, uuid4(), 1
    owner.query, owner.source_authority = object(), object()
    owner.mapping_owner = SimpleNamespace(runtime_owner=owner.query)
    relations = object.__new__(NativeRelationReviewProducer)
    relations.owner, relations.conn = owner, conn
    exposure = object.__new__(NativeExposureOwnerV2)
    exposure.type_owner, exposure.conn, exposure.user_id, exposure.epoch = owner, conn, owner.user_id, owner.epoch
    facts = object.__new__(SharedAdmissionFactsOwner)
    facts.conn = conn
    facts.validation_pipeline, facts.review_pipeline = SimpleNamespace(conn=conn), SimpleNamespace(conn=conn)
    publisher = object.__new__(NativeLearningItemPublicationService)
    publisher.conn, publisher.facts_owner = conn, facts
    publisher.importer = SimpleNamespace(authority=owner.source_authority)
    lease = SimpleNamespace(job_id=uuid4())
    contents = _contents(operator)
    for content in contents:
        content.publication = SimpleNamespace(lease=lease)
    live = SimpleNamespace(publisher=publisher, facts_owner=facts, validation_owner=facts.validation_pipeline,
        review_owner=facts.review_pipeline, lease=lease,
        result={"status": "published_internal_not_ready_pack", "slot": "assessment-1",
            "relation_anchor_eligible": True, "version_id": str(contents[3].content.version_id)})
    mapping_id, relation_id, reservation_id = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(owner, "resolve_mapping", lambda _: SimpleNamespace(target_id=operator.TARGET))
    monkeypatch.setattr(owner, "resolve_content", lambda v, current: next(c for c in contents if c.content.version_id == v))
    monkeypatch.setattr(exposure, "snapshot_v2", lambda: SimpleNamespace(exposure=SimpleNamespace(records=()), snapshot_id=uuid4()))
    folder = tmp_path / "repo/.runtime/offline-pack"
    monkeypatch.setattr(operator, "__file__", str(tmp_path / "repo/.trellis/tasks/task/research/operator.py"))

    def prepare(**kwargs):
        assert conn.info.transaction_status == TransactionStatus.INTRANS
        assert kwargs["lease"] is lease and kwargs["anchor_version_id"] == contents[3].content.version_id
        assert len(kwargs["pairs"]) == 7
        conn.events.append("prepare")
        return SimpleNamespace(mapping_receipt_id=mapping_id, anchor_version_id=contents[3].content.version_id,
            lease=lease, root_id=uuid4(), preparation_id=relation_id, reservation_id=uuid4(),
            resources=SimpleNamespace(requests=4), valid_until=datetime.now(UTC) + timedelta(minutes=2))

    def run(prepared):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        assert conn.events[-1] == "commit" and (folder / "relation-dispatch.json").is_file()
        conn.events.append("run")
        return SimpleNamespace(safe_reason="native_relation_provider_or_evidence_pending" if pending else "native_relation_completed", reports=())

    def settle(prepared, result):
        assert conn.info.transaction_status == TransactionStatus.INTRANS
        conn.events.append("settle")

    def persist(prepared, result):
        assert conn.events[-3:] == ["settle", "commit", "begin"]
        conn.events.append("persist")
        if pending:
            raise NativeTypeEvidencePending("native_relation_provider_or_evidence_pending")
        return relation_id

    def reserve(**kwargs):
        assert conn.events[-3:] == ["persist", "commit", "begin"]
        assert kwargs["relation_receipt_ids"] == (relation_id,)
        assert set(kwargs["candidate_version_ids"]) == {c.content.version_id for c in contents}
        conn.events.append("reserve")
        return reservation_id

    for name, method in (("prepare", prepare), ("run", run), ("settle", settle), ("persist", persist)):
        monkeypatch.setattr(relations, name, method)
    monkeypatch.setattr(exposure, "reserve_assessment", reserve)
    kwargs = dict(live=live, type_owner=owner, relation_owner=relations, exposure_owner=exposure,
        mapping_receipt_id=mapping_id, candidate_version_ids=tuple(c.content.version_id for c in contents),
        output_dir=folder, execute=True)
    return conn, kwargs, folder, reservation_id


def test_original_prepare_idle_run_settle_persist_reserve_order(operator, monkeypatch, tmp_path):
    conn, kwargs, folder, reservation_id = _offline_setup(operator, monkeypatch, tmp_path)
    prepared = operator.prepare_kc_pack(**kwargs)
    reserved = operator.complete_kc_pack(prepared, operation_key="offline.kc.pack", execute=True)
    assert reserved.reservation_id == reservation_id
    assert conn.events == ["begin", "prepare", "commit", "run", "begin", "settle", "commit",
        "begin", "persist", "commit", "begin", "reserve", "commit"]
    report = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    assert report["delivered"] is False and report["Attempt_Gate_mastery"] is False
    assert json.loads((folder / "settled.json").read_text(encoding="utf-8"))["usage_state"] == "unknown"
    with pytest.raises(ValueError, match="artifact_transaction_required"):
        operator.prepare_kc_practice_delivery(reserved, version_id=kwargs["candidate_version_ids"][0], delivery_key="offline.delivery", execute=True)


def test_pending_keeps_unknown_settlement_and_dispatch_never_retries(operator, monkeypatch, tmp_path):
    from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending

    conn, kwargs, folder, _ = _offline_setup(operator, monkeypatch, tmp_path, pending=True)
    prepared = operator.prepare_kc_pack(**kwargs)
    with pytest.raises(NativeTypeEvidencePending, match="provider_or_evidence_pending"):
        operator.complete_kc_pack(prepared, operation_key="offline.kc.pending", execute=True)
    failure_bytes = (folder / "failure.json").read_bytes()
    assert "reserve" not in conn.events and conn.events[-1] == "rollback"
    assert (folder / "settled.json").is_file() and not (folder / "result.json").exists()
    with pytest.raises(FileExistsError):
        operator.complete_kc_pack(prepared, operation_key="offline.kc.pending", execute=True)
    assert conn.events.count("run") == 1 and (folder / "failure.json").read_bytes() == failure_bytes
