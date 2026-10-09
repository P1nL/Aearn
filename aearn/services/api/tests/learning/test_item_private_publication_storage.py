"""Pure/structural P7 storage tests. No DB, provider or candidate execution."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.practice_adapter import LEARNING_ITEM_PRACTICE_ADAPTER_VERSION
from app.services.learning.item_bank.private_publication_contracts import (
    PrivatePracticeMaterializationV1,
    PrivatePublicationReceiptV1,
    PrivatePublishedCoverageV1,
    PrivatePublishedRecordV1,
    PrivateSourceBindingV1,
    PrivateSupplyResultV1,
    PrivateSupplySelectionV1,
)
from app.services.learning.item_bank.private_publication_repository import (
    PostgresPrivatePublicationRepository,
    PrivatePublicationStorageError,
    _materialization,
)
from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1, ClauseCoverageV1
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.generation_contracts import SourceReceiptV2
from app.services.learning.item_supply.storage_contracts import checked_model
from tests.learning.test_item_supply_contracts import make_blueprint, make_scope
from tests.learning.test_item_supply_evidence import make_material
from tests.learning.test_item_supply_sandbox_execution import python_source

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)
API = Path(__file__).resolve().parents[2]


def material_fixture() -> PrivatePracticeMaterializationV1:
    source = python_source()
    return PrivatePracticeMaterializationV1(
        user_id=uuid4(), epoch=1, scope_id=uuid4(), version_id=uuid4(), materialization_id=uuid4(),
        source=source, source_hash=source.source_hash, content_hash=source.content_hash,
        version_payload_hash="d" * 64, adapter_version=LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
        scorer_version="scorer-v1", runtime_profile_id=source.blueprint.runtime_profile_id,
        runtime_profile_hash="e" * 64, created_at=NOW,
    )


def event_fixture(material: PrivatePracticeMaterializationV1) -> PrivatePublicationReceiptV1:
    return PrivatePublicationReceiptV1(
        user_id=material.user_id, epoch=material.epoch, scope_id=material.scope_id, version_id=material.version_id,
        publication_id=uuid4(), generation_artifact_id=uuid4(), facts_receipt_id=uuid4(),
        evaluation_receipt_id=uuid4(), materialization_id=material.materialization_id, proof_id=uuid4(),
        handle=f"lip:v2:{uuid4()}", source_hash=material.source_hash, content_hash=material.content_hash,
        version_payload_hash=material.version_payload_hash, transition_key="fixture.publish",
        predecessor_event_id=None, state_version=1, state="published", checked_at=NOW,
        admission_valid_until=NOW + timedelta(minutes=1),
    )


def source_fixture() -> PrivateSourceBindingV1:
    # Structurally current-shaped fixture only; no issuer/current-source claim.
    material, _ = make_material()
    coordinate = material.binding.evidence[0]
    return PrivateSourceBindingV1(material=material, receipt=SourceReceiptV2(
        material_digest=material_digest(material), binding_digest=material.binding.binding_digest,
        corpus_version_id=UUID(coordinate.corpus_version_id), active_generation=coordinate.active_generation,
        checked_at_iso=NOW.isoformat(), claim_receipt_hashes=(coordinate.claim_receipt_hash,),
        mode="current_authority",
    ))


def test_material_uses_existing_practice_and_three_distinct_hashes() -> None:
    material = material_fixture()
    authority = material.authority_material()
    assert authority.exercise.runtime_profile_id == material.runtime_profile_id
    assert authority.rubric.private_test_bundle
    assert len({material.source_hash, material.content_hash, material.version_payload_hash}) == 3
    snapshot = material.storage_snapshot()
    assert _materialization({"payload_json": snapshot, "receipt_hash": material.receipt_hash}) == material
    assert PrivatePracticeMaterializationV1.model_validate_json(material.model_dump_json()) == material
    snapshot["runner_material"] = {"injected": True}
    with pytest.raises(PrivatePublicationStorageError, match="PRIVATE_MATERIALIZATION_INVALID"):
        _materialization({"payload_json": snapshot, "receipt_hash": canonical_hash(snapshot)})


def test_constructed_nested_extras_strict_numbers_and_bounds_are_not_laundered() -> None:
    material = material_fixture()
    bad = material.source.model_copy(update={"raw_provider": "private"})
    with pytest.raises(ValueError):
        checked_model(material.model_copy(update={"source": bad}), PrivatePracticeMaterializationV1)
    with pytest.raises(ValidationError):
        PrivatePracticeMaterializationV1.model_validate({**material.model_dump(), "epoch": True})
    with pytest.raises(ValidationError):
        PrivatePracticeMaterializationV1.model_validate({**material.model_dump(), "source_hash": material.content_hash})
    with pytest.raises(ValidationError):
        PrivateSupplyResultV1(status="pending", demand_hash="1" * 64, blueprint_hash="2" * 64,
                              raw_answer="not allowed")


def test_private_handle_and_terminal_transition_shape_preserve_legacy_boundary() -> None:
    event = event_fixture(material_fixture())
    assert PrivatePublicationReceiptV1.model_validate_json(event.model_dump_json()) == event
    assert event.request_hash == canonical_hash(event.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        PrivatePublicationReceiptV1.model_validate({**event.model_dump(), "handle": "li:" + "a" * 64})
    with pytest.raises(ValidationError):
        PrivatePublicationReceiptV1.model_validate({**event.model_dump(), "state": "quarantined"})
    terminal = PrivatePublicationReceiptV1.model_validate({
        **event.model_dump(), "publication_id": uuid4(), "predecessor_event_id": event.publication_id,
        "state_version": 2, "state": "quarantined", "checked_at": NOW + timedelta(days=1),
    })
    assert terminal.admission_valid_until < terminal.checked_at  # quarantine works after expiry


def test_complete_source_binding_and_safe_result_are_bounded_not_authority() -> None:
    source = source_fixture()
    for change in ({"mode": "synthetic"}, {"material_digest": "0" * 64},
                   {"claim_receipt_hashes": ()}, {"active_generation": 99}):
        with pytest.raises(ValueError):
            checked_model(source.model_copy(update={"receipt": source.receipt.model_copy(update=change)}), PrivateSourceBindingV1)
    event = event_fixture(material_fixture())
    selection = PrivateSupplySelectionV1(handle=event.handle, publication_id=event.publication_id,
                                         materialization_id=event.materialization_id, proof_id=event.proof_id)
    result = PrivateSupplyResultV1(status="pending", demand_hash="1" * 64, blueprint_hash="2" * 64,
                                   selected=(selection,), reasons=("insufficient_coverage",))
    assert result.selected_handles == (event.handle,)
    assert not any(key in result.model_dump_json() for key in ("source_hash", "rubric", "claims", "standard_answer"))
    with pytest.raises(ValidationError):
        PrivateSupplyResultV1(status="ready_exact", demand_hash="1" * 64, blueprint_hash="2" * 64)
    with pytest.raises(ValidationError):
        PrivateSupplyResultV1(status="pending", demand_hash="1" * 64, blueprint_hash="2" * 64, selected=(selection,) * 65)


def test_private_record_preserves_exact_scope_full_sources_and_reference_links() -> None:
    material = material_fixture()
    event = event_fixture(material)
    scope = make_scope(visibility="private", owner_ref=f"user:{material.user_id}",
                       runtime_profile_id=material.runtime_profile_id, runtime_profile_hash=material.runtime_profile_hash,
                       knowledge_key=material.source.blueprint.knowledge_key,
                       required_capabilities=material.source.blueprint.required_capabilities)
    # Real admission uses a registered public blueprint and an exact private
    # ownership projection, not a newly invented private blueprint hash.
    blueprint = make_blueprint(scope.model_copy(update={"visibility": "public", "owner_ref": None}))
    demand = AssessmentSupplyDemandV1(demand_id="fixture.demand", learner_ref=f"user:{material.user_id}",
        scope=scope, objective_hash=blueprint.objective_hash, blueprint_hash=blueprint.blueprint_hash,
        matrix_hash=blueprint.matrix_hash, policy_version=blueprint.policy_version, input_revision=1)
    proof = PrivatePublishedCoverageV1(
        user_id=material.user_id, epoch=material.epoch, scope_id=material.scope_id, version_id=material.version_id,
        proof_id=event.proof_id, publication_id=event.publication_id, materialization_id=material.materialization_id,
        generation_artifact_id=event.generation_artifact_id, facts_receipt_id=event.facts_receipt_id,
        evaluation_receipt_id=event.evaluation_receipt_id, demand_id=uuid4(), demand=demand, blueprint=blueprint,
        clauses=tuple(ClauseCoverageV1(clause_id=c.clause_id, clause_hash=c.clause_hash) for c in blueprint.clauses),
        candidate_family_id="fixture.family", slot="practice", source_hash=material.source_hash,
        content_hash=material.content_hash, version_payload_hash=material.version_payload_hash,
        sources=(source_fixture(),), checked_at=event.checked_at, valid_until=event.admission_valid_until,
    )
    record = PrivatePublishedRecordV1(publication=event, materialization=material, proof=proof)
    assert PrivatePublishedRecordV1.model_validate_json(record.model_dump_json()) == record
    assert record.proof.sources[0].material.exact_claims
    with pytest.raises(ValueError):
        checked_model(record.model_copy(update={"proof": proof.model_copy(update={"facts_receipt_id": uuid4()})}), PrivatePublishedRecordV1)


def test_material_replay_is_exact_and_conflict_does_not_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    material = material_fixture()
    row = {"payload_json": material.storage_snapshot(), "receipt_hash": material.receipt_hash}

    class Rows:
        def fetchone(self):
            return row

    class ConnectionDouble:
        def execute(self, query, parameters):
            assert str(query).startswith("SELECT")
            return Rows()

    repository = PostgresPrivatePublicationRepository(ConnectionDouble(), user_id=material.user_id, expected_epoch=1)
    monkeypatch.setattr(repository, "_lock", lambda _: {
        "payload_hash": material.version_payload_hash,
        "public_json": material.source.public.model_dump(mode="json"),
        "private_json": material.source.private.model_dump(mode="json"),
    })
    assert repository.append_materialization(material) == material
    with pytest.raises(PrivatePublicationStorageError, match="PRIVATE_MATERIALIZATION_CONFLICT"):
        repository.append_materialization(material.model_copy(update={"materialization_id": uuid4()}))


def test_schema_parent_cleanup_cas_guards_and_repository_do_not_own_io() -> None:
    schema = (API / "app/db/schema/485_learning_item_private_publication.sql").read_text(encoding="utf-8")
    for table in ("materializations", "publication_events", "publication_proofs"):
        section = schema.split(f"CREATE TABLE IF NOT EXISTS tutor_item_supply_private_{table} (")[1].split("\n);")[0]
        assert all(field in section for field in ("id uuid", "scope_id uuid", "created_at timestamptz"))
    for table in ("generation_artifacts", "admission_facts", "pipeline_receipts"):
        assert f"REFERENCES tutor_item_supply_private_{table}(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE" in schema
    assert "UNIQUE(predecessor_event_id)" in schema and "previous.state_version+1" in schema
    assert "enforce_item_supply_private_epoch()" in schema and "enforce_item_supply_immutable(''private'')" in schema
    assert "INSERT INTO item_supply_internal.reset_permits" not in schema
    assert "INSERT INTO tutor_item_supply" not in schema
    tree = ast.parse((API / "app/services/learning/item_bank/private_publication_repository.py").read_text(encoding="utf-8"))
    calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert not set(calls) & {"connect", "commit", "rollback"}


def test_owner_and_fresh_snapshot_fences_reject_before_parent_access() -> None:
    material = material_fixture()

    class Info:
        transaction_status = TransactionStatus.INTRANS

    class ConnectionDouble:
        autocommit = False
        info = Info()
        calls = 0

        def execute(self, query):
            self.calls += 1
            assert query == "SHOW transaction_isolation"
            return self

        def fetchone(self):
            return {"transaction_isolation": "repeatable read"}

    connection = ConnectionDouble()
    repository = PostgresPrivatePublicationRepository(connection, user_id=material.user_id, expected_epoch=2)
    with pytest.raises(PrivatePublicationStorageError, match="PRIVATE_OWNER_MISMATCH"):
        repository.append_materialization(material)
    assert connection.calls == 0
    with pytest.raises(PrivatePublicationStorageError, match="PRIVATE_READ_COMMITTED_REQUIRED"):
        repository.load_exact(demand_id=uuid4(), scope_id=material.scope_id)
    assert connection.calls == 1
