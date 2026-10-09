"""Caller-transaction private publication storage; never issues admission authority."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from psycopg import Connection, sql
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.private_publication_contracts import (
    MAX_PRIVATE_SELECTIONS,
    PrivateIdentityV1,
    PrivatePracticeMaterializationV1,
    PrivatePublicationReceiptV1,
    PrivatePublishedCoverageV1,
    PrivatePublishedRecordV1,
    PrivateSourceBindingV1,
)
from app.services.learning.item_supply.admission_facts_contracts import IssuedAdmissionFactsV1
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.repository import lock_private_namespace
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvaluationV2
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

MATERIALIZATIONS = "tutor_item_supply_private_materializations"
PUBLICATIONS = "tutor_item_supply_private_publication_events"
PROOFS = "tutor_item_supply_private_publication_proofs"
T = TypeVar("T", bound=StorageContract)


class PrivatePublicationStorageError(ValueError):
    """Safe constant reason only; private payloads must not enter diagnostics."""


def _decode(data: object, kind: type[T]) -> T:
    try:
        parsed = kind.model_validate_json(json.dumps(data, allow_nan=False))
        return checked_model(parsed, kind)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_SNAPSHOT_INVALID") from None


def _materialization(row: dict[str, Any]) -> PrivatePracticeMaterializationV1:
    payload = row["payload_json"]
    if not isinstance(payload, dict):
        raise PrivatePublicationStorageError("PRIVATE_MATERIALIZATION_INVALID")
    material = _decode(payload.get("materialization"), PrivatePracticeMaterializationV1)
    if material.storage_snapshot() != payload or material.receipt_hash != row["receipt_hash"]:
        raise PrivatePublicationStorageError("PRIVATE_MATERIALIZATION_INVALID")
    return material


def _publication(row: dict[str, Any]) -> PrivatePublicationReceiptV1:
    event = _decode(row["payload_json"], PrivatePublicationReceiptV1)
    if event.request_hash != row["request_hash"]:
        raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_SNAPSHOT_INVALID")
    return event


class PostgresPrivatePublicationRepository:
    def __init__(self, conn: Connection[dict[str, Any]], *, user_id: UUID, expected_epoch: int) -> None:
        if type(user_id) is not UUID or type(expected_epoch) is not int or expected_epoch < 1:
            raise PrivatePublicationStorageError("PRIVATE_OWNER_REQUIRED")
        self.conn = conn
        self.user_id = user_id
        self.expected_epoch = expected_epoch

    def _namespace(self, scope_id: UUID) -> None:
        if self.conn.autocommit and self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise PrivatePublicationStorageError("PRIVATE_CALLER_TRANSACTION_REQUIRED")
        isolation = self.conn.execute("SHOW transaction_isolation").fetchone()
        if isolation is None or isolation["transaction_isolation"] != "read committed":
            # A repeatable-read snapshot can predate a quarantine even after
            # waiting for its unchanged version-row lock. Require fresh SELECT
            # snapshots rather than presenting that historical state as current.
            raise PrivatePublicationStorageError("PRIVATE_READ_COMMITTED_REQUIRED")
        lock_private_namespace(self.conn, self.user_id, self.expected_epoch, scope_id)

    def _lock(self, identity: PrivateIdentityV1) -> dict[str, Any]:
        if identity.user_id != self.user_id or identity.epoch != self.expected_epoch:
            raise PrivatePublicationStorageError("PRIVATE_OWNER_MISMATCH")
        self._namespace(identity.scope_id)
        row = self.conn.execute(
            "SELECT * FROM tutor_item_supply_private_versions "
            "WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s FOR UPDATE",
            (identity.version_id, self.user_id, self.expected_epoch, identity.scope_id),
        ).fetchone()
        if row is None:
            raise PrivatePublicationStorageError("PRIVATE_VERSION_UNAVAILABLE")
        return row

    def _row(self, table: str, row_id: UUID, identity: PrivateIdentityV1) -> dict[str, Any]:
        row = self.conn.execute(
            sql.SQL("SELECT * FROM {} WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s").format(sql.Identifier(table)),
            (row_id, self.user_id, self.expected_epoch, identity.scope_id, identity.version_id),
        ).fetchone()
        if row is None:
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_PARENT_UNAVAILABLE")
        return row

    def _insert(self, table: str, fields: dict[str, object]) -> dict[str, Any] | None:
        # Only internal fixed table/field names reach this helper; data are parameters.
        return self.conn.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING RETURNING *").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, fields)),
                sql.SQL(",").join(sql.Placeholder() for _ in fields),
            ),
            tuple(fields.values()),
        ).fetchone()

    @staticmethod
    def _identity_fields(value: PrivateIdentityV1) -> dict[str, object]:
        return {"user_id": value.user_id, "epoch": value.epoch,
                "scope_id": value.scope_id, "version_id": value.version_id}

    def _latest(self, identity: PrivateIdentityV1) -> dict[str, Any] | None:
        return self.conn.execute(
            f"SELECT * FROM {PUBLICATIONS} WHERE user_id=%s AND epoch=%s AND scope_id=%s "
            "AND version_id=%s ORDER BY state_version DESC LIMIT 1",
            identity.identity(),
        ).fetchone()

    def append_materialization(self, materialization: PrivatePracticeMaterializationV1) -> PrivatePracticeMaterializationV1:
        material = checked_model(materialization, PrivatePracticeMaterializationV1)
        version = self._lock(material)
        if (material.version_payload_hash != version["payload_hash"]
                or material.source.public.model_dump(mode="json") != version["public_json"]
                or material.source.private.model_dump(mode="json") != version["private_json"]):
            raise PrivatePublicationStorageError("PRIVATE_MATERIALIZATION_VERSION_MISMATCH")
        existing = self.conn.execute(
            f"SELECT * FROM {MATERIALIZATIONS} WHERE user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s",
            material.identity(),
        ).fetchone()
        if existing is not None:
            stored = _materialization(existing)
            if stored != material:
                raise PrivatePublicationStorageError("PRIVATE_MATERIALIZATION_CONFLICT")
            return stored
        row = self._insert(MATERIALIZATIONS, {
            "id": material.materialization_id, **self._identity_fields(material),
            "source_hash": material.source_hash, "content_hash": material.content_hash,
            "version_payload_hash": material.version_payload_hash,
            "payload_json": Jsonb(material.storage_snapshot()), "created_at": material.created_at,
        })
        if row is None:
            raise PrivatePublicationStorageError("PRIVATE_MATERIALIZATION_CONFLICT")
        return _materialization(row)

    def _parents(self, event: PrivatePublicationReceiptV1) -> tuple[
        PrivatePracticeMaterializationV1, dict[str, Any], IssuedAdmissionFactsV1, AdmissionEvaluationV2
    ]:
        material = _materialization(self._row(MATERIALIZATIONS, event.materialization_id, event))
        generation = self._row("tutor_item_supply_private_generation_artifacts", event.generation_artifact_id, event)
        facts_row = self._row("tutor_item_supply_private_admission_facts", event.facts_receipt_id, event)
        evaluation_row = self._row("tutor_item_supply_private_pipeline_receipts", event.evaluation_receipt_id, event)
        facts = _decode(facts_row["payload_json"], IssuedAdmissionFactsV1)
        evaluation = _decode(evaluation_row["payload_json"], AdmissionEvaluationV2)
        if (generation["mode"] != "live" or evaluation_row["mode"] != "live"
                or evaluation_row["artifact_kind"] != "admission_evaluation"
                or evaluation.disposition != "eligible_internal"
                or evaluation.binding != facts.evidence.binding
                or evaluation.evidence_hash != canonical_hash(facts.evidence.model_dump(mode="json"))
                or facts_row["payload_hash"] != facts.receipt_hash
                or evaluation_row["receipt_hash"] != evaluation.receipt_hash
                or generation["source_json"] != material.source.model_dump(mode="json")
                or facts.receipt_id != event.facts_receipt_id
                or facts.generation_artifact_id != event.generation_artifact_id
                or facts.version_id != event.version_id
                or facts.user_id != event.user_id or facts.epoch != event.epoch or facts.scope_id != event.scope_id
                or evaluation_row["generation_artifact_id"] != event.generation_artifact_id
                or facts.lease.job_id != evaluation_row["job_id"]
                or facts.lease.generation != evaluation_row["lease_generation"]
                or facts.lease.state_version != evaluation_row["lease_state_version"]
                or evaluation.binding.version_key != str(event.version_id)
                or evaluation.binding.candidate_key != str(generation["candidate_id"])):
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_PARENT_MISMATCH")
        for name in ("source_hash", "content_hash"):
            if not getattr(event, name) == getattr(material, name) == generation[name] == getattr(evaluation.binding, name):
                raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_HASH_MISMATCH")
        if event.version_payload_hash != material.version_payload_hash:
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_HASH_MISMATCH")
        return material, generation, facts, evaluation

    def _current_admission(self, event: PrivatePublicationReceiptV1, facts: IssuedAdmissionFactsV1) -> None:
        lease = facts.lease
        control = self.conn.execute(
            "SELECT * FROM tutor_item_supply_private_job_controls "
            "WHERE job_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s FOR UPDATE",
            (lease.job_id, self.user_id, self.expected_epoch, event.scope_id),
        ).fetchone()
        clock = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
        assert clock is not None
        now: datetime = clock["now"]
        if (control is None or control["lease_generation"] != lease.generation
                or control["state_version"] != lease.state_version or control["lease_owner"] != lease.lease_owner
                or control["state"] not in {"leased", "reviewing", "simulating", "admitting"}
                or control["lease_expires_at"] is None
                or not event.checked_at <= now < event.admission_valid_until
                or event.admission_valid_until > min(control["lease_expires_at"], control["parent_deadline"])
                or event.checked_at != facts.coverage.checked_at
                or event.admission_valid_until != facts.coverage.valid_until):
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_ADMISSION_STALE")

    def append_publication(self, publication: PrivatePublicationReceiptV1) -> PrivatePublicationReceiptV1:
        event = checked_model(publication, PrivatePublicationReceiptV1)
        version = self._lock(event)
        if version["payload_hash"] != event.version_payload_hash or version["handle"] != event.handle:
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_VERSION_MISMATCH")
        existing = self.conn.execute(
            f"SELECT * FROM {PUBLICATIONS} WHERE user_id=%s AND epoch=%s AND scope_id=%s "
            "AND version_id=%s AND transition_key=%s", (*event.identity(), event.transition_key),
        ).fetchone()
        if existing is not None:
            stored = _publication(existing)
            if stored != event:
                raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_REPLAY_CONFLICT")
            return stored
        _, _, facts, _ = self._parents(event)
        previous = self._latest(event)
        if previous is None:
            if event.state != "published":
                raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_INITIAL_STATE_INVALID")
            self._current_admission(event, facts)
        else:
            predecessor = _publication(previous)
            changed = {"publication_id", "transition_key", "predecessor_event_id", "state_version", "state", "checked_at"}
            if (event.predecessor_event_id != predecessor.publication_id
                    or event.state_version != predecessor.state_version + 1
                    or predecessor.state == "retired" or event.state == "published"
                    or predecessor.state == "quarantined" and event.state != "retired"
                    or event.checked_at < predecessor.checked_at
                    or event.model_dump(exclude=changed) != predecessor.model_dump(exclude=changed)):
                raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_SUCCESSOR_CONFLICT")
        row = self._insert(PUBLICATIONS, {
            "id": event.publication_id, **self._identity_fields(event),
            "generation_artifact_id": event.generation_artifact_id, "facts_receipt_id": event.facts_receipt_id,
            "evaluation_receipt_id": event.evaluation_receipt_id, "materialization_id": event.materialization_id,
            "proof_id": event.proof_id, "source_hash": event.source_hash, "content_hash": event.content_hash,
            "version_payload_hash": event.version_payload_hash, "transition_key": event.transition_key,
            "predecessor_event_id": event.predecessor_event_id, "state_version": event.state_version,
            "state": event.state, "checked_at": event.checked_at, "admission_valid_until": event.admission_valid_until,
            "payload_json": Jsonb(event.model_dump(mode="json")),
        })
        if row is None:
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_REPLAY_CONFLICT")
        return _publication(row)

    def append_proof(self, proof: PrivatePublishedCoverageV1) -> PrivatePublishedCoverageV1:
        proof = checked_model(proof, PrivatePublishedCoverageV1)
        self._lock(proof)
        latest = self._latest(proof)
        if latest is None or latest["id"] != proof.publication_id:
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_NOT_CURRENT")
        event = _publication(latest)
        material, generation, facts, _ = self._parents(event)
        PrivatePublishedRecordV1(publication=event, materialization=material, proof=proof)
        existing = self.conn.execute(
            f"SELECT * FROM {PROOFS} WHERE publication_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s",
            (proof.publication_id, self.user_id, self.expected_epoch, proof.scope_id),
        ).fetchone()
        if existing is not None:
            if existing["proof_hash"] != proof.proof_hash or existing["payload_json"] != proof.model_dump(mode="json"):
                raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_PROOF_CONFLICT")
            return _decode(existing["payload_json"], PrivatePublishedCoverageV1)
        request = _decode(generation["request_json"], GenerationRequestV2)
        generated = _decode(generation["receipt_json"], GenerationReceiptV2)
        if len(request.materials) != len(generated.sources):
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_SOURCES_INCOMPLETE")
        expected_sources = tuple(PrivateSourceBindingV1(material=m, receipt=r)
                                 for m, r in zip(request.materials, generated.sources, strict=True))
        demand = self.conn.execute(
            "SELECT snapshot_json FROM tutor_item_supply_private_demands "
            "WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s FOR SHARE",
            (proof.demand_id, self.user_id, self.expected_epoch, proof.scope_id),
        ).fetchone()
        if (demand is None or demand["snapshot_json"] != proof.demand.model_dump(mode="json")
                or proof.demand != facts.coverage.demand or proof.blueprint != facts.coverage.coverage_blueprint
                or proof.sources != expected_sources
                or {(c.clause_id, c.clause_hash) for c in proof.clauses}
                != {(c.clause_id, c.clause_hash) for c in facts.coverage.mappings}):
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_PROOF_MISMATCH")
        self._current_admission(event, facts)
        row = self._insert(PROOFS, {
            "id": proof.proof_id, **self._identity_fields(proof),
            "publication_id": proof.publication_id, "materialization_id": proof.materialization_id,
            "generation_artifact_id": proof.generation_artifact_id, "facts_receipt_id": proof.facts_receipt_id,
            "evaluation_receipt_id": proof.evaluation_receipt_id, "demand_id": proof.demand_id,
            "source_hash": proof.source_hash, "content_hash": proof.content_hash,
            "version_payload_hash": proof.version_payload_hash, "payload_json": Jsonb(proof.model_dump(mode="json")),
        })
        if row is None or row["proof_hash"] != proof.proof_hash:
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_PROOF_CONFLICT")
        return _decode(row["payload_json"], PrivatePublishedCoverageV1)

    def load_exact(self, *, demand_id: UUID, scope_id: UUID) -> tuple[PrivatePublishedRecordV1, ...]:
        self._namespace(scope_id)
        demand = self.conn.execute(
            "SELECT snapshot_json FROM tutor_item_supply_private_demands "
            "WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s FOR SHARE",
            (demand_id, self.user_id, self.expected_epoch, scope_id),
        ).fetchone()
        if demand is None:
            raise PrivatePublicationStorageError("PRIVATE_DEMAND_UNAVAILABLE")
        # Lock versions before reading latest state. Append uses the same lock;
        # a query cannot read a predecessor while quarantine is being committed.
        versions = self.conn.execute(
            f"SELECT v.id FROM tutor_item_supply_private_versions v WHERE v.user_id=%s AND v.epoch=%s "
            f"AND v.scope_id=%s AND EXISTS(SELECT 1 FROM {PROOFS} p WHERE p.version_id=v.id "
            "AND p.user_id=v.user_id AND p.epoch=v.epoch AND p.scope_id=v.scope_id AND p.demand_id=%s) "
            "ORDER BY v.id LIMIT %s FOR SHARE OF v",
            (self.user_id, self.expected_epoch, scope_id, demand_id, MAX_PRIVATE_SELECTIONS + 1),
        ).fetchall()
        if len(versions) > MAX_PRIVATE_SELECTIONS:
            raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_QUERY_BOUND")
        result: list[PrivatePublishedRecordV1] = []
        for version in versions:
            identity = PrivateIdentityV1(user_id=self.user_id, epoch=self.expected_epoch,
                                         scope_id=scope_id, version_id=version["id"])
            latest = self._latest(identity)
            if latest is None or latest["state"] != "published":
                continue
            event = _publication(latest)
            proof_row = self.conn.execute(
                f"SELECT * FROM {PROOFS} WHERE id=%s AND publication_id=%s AND user_id=%s AND epoch=%s "
                "AND scope_id=%s AND version_id=%s AND demand_id=%s",
                (event.proof_id, event.publication_id, *identity.identity(), demand_id),
            ).fetchone()
            if proof_row is None:
                continue
            proof = _decode(proof_row["payload_json"], PrivatePublishedCoverageV1)
            material = _materialization(self._row(MATERIALIZATIONS, event.materialization_id, identity))
            if proof.proof_hash != proof_row["proof_hash"] or proof.demand.model_dump(mode="json") != demand["snapshot_json"]:
                raise PrivatePublicationStorageError("PRIVATE_PUBLICATION_PROOF_MISMATCH")
            result.append(PrivatePublishedRecordV1(publication=event, materialization=material, proof=proof))
        return tuple(result)
