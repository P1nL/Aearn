"""Exact private publication reads; no public consumer or whole-pack readiness.

Runtime IO happens only in an explicit IDLE preflight. Query takes fresh database,
source and publication fences and never rehydrates an original P5 terminal seal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import sys
import time
from typing import Any, Literal
from uuid import UUID

from aearn_shared.execution import RuntimeImageLockV1
from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.private_publication_contracts import (
    PrivatePublishedRecordV1, PrivateSupplyResultV1, PrivateSupplySelectionV1,
)
from app.services.learning.item_bank.private_publication_repository import PostgresPrivatePublicationRepository
from app.services.learning.item_bank.publication import (
    PrivatePublicationError, candidate_family, current_sources, source_bindings, transaction_clock,
)
from app.services.learning.item_supply.admission_facts_contracts import IssuedAdmissionFactsV1
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1, CoverageBlueprintV1, SafeReason, Slot, SupplyGapV1, SupplyScopeV1,
)
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvaluationV2
from app.services.learning.item_supply.storage import PostgresPrivateSupplyStorage
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.practice.quality import require_exercise_quality


@dataclass(frozen=True)
class _RuntimeObservation:
    lock: RuntimeImageLockV1
    observed_at: datetime
    expires_at: datetime
    monotonic_deadline: float


class PrivateSupplyRuntimeOwner:
    """One-query actual candidate-runtime observation, not a generic proof port.

    Instantiate with the concrete from_docker bridge in a new query process if
    needed. observe() performs the image inspection while the connection is IDLE.
    No old execution receipt or seal is imported into this owner.
    """
    WINDOW_SECONDS = 30

    def __init__(self, conn: Connection[dict[str, Any]], *, runner: object) -> None:
        self.conn = conn
        self._runner = runner
        self._pending: _RuntimeObservation | None = None
        self._active: _RuntimeObservation | None = None

    def _concrete_runner(self) -> Any:
        bridge = sys.modules.get("aearn_executor.item_supply_bridge")
        client = sys.modules.get("aearn_executor.docker_client")
        bridge_type = getattr(bridge, "ItemSupplyRunnerBridge", None)
        client_type = getattr(client, "DockerContainerRuntimeClient", None)
        runner = self._runner
        if (bridge_type is None or client_type is None or type(runner) is not bridge_type
                or getattr(runner, "_live", None) is not True
                or type(getattr(runner, "_client", None)) is not client_type):
            raise PrivatePublicationError("PRIVATE_SUPPLY_ACTUAL_RUNTIME_REQUIRED")
        return runner

    def observe(self, *, runtime_id: str) -> None:
        self._pending = self._active = None
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PrivatePublicationError("PRIVATE_SUPPLY_RUNTIME_IO_REQUIRES_IDLE")
        runner = self._concrete_runner()
        lock = runner._locks.get(runtime_id)
        if type(lock) is not RuntimeImageLockV1 or lock.runtime_id != runtime_id or not runner._verify_image(lock):
            raise PrivatePublicationError("PRIVATE_SUPPLY_RUNTIME_UNAVAILABLE")
        # The bound is only an observation's maximum age, NOT a source/proof TTL.
        # Both wall and monotonic clocks prevent waiting/clock jumps extending it.
        monotonic_deadline = time.monotonic() + self.WINDOW_SECONDS
        # Obtain the database clock separately AFTER image IO. This short clock
        # transaction ends before the caller starts its selection transaction.
        with self.conn.transaction():
            now = transaction_clock(self.conn)
        self._pending = _RuntimeObservation(lock, now, now + timedelta(seconds=self.WINDOW_SECONDS),
                                           monotonic_deadline)

    def begin_query(self) -> None:
        if self.conn.info.transaction_status != TransactionStatus.INTRANS or self._pending is None:
            raise PrivatePublicationError("PRIVATE_SUPPLY_RUNTIME_OBSERVATION_REQUIRED")
        self._active, self._pending = self._pending, None

    def assert_matches(self, *, runtime_id: str, fingerprints: set[str], now: datetime) -> None:
        observed = self._active
        runner = self._concrete_runner()
        lock = runner._locks.get(runtime_id)
        if (observed is None or type(lock) is not RuntimeImageLockV1 or lock != observed.lock
                or lock.runtime_id != runtime_id or fingerprints != {lock.fingerprint}
                or not observed.observed_at <= now < observed.expires_at
                or time.monotonic() >= observed.monotonic_deadline):
            raise PrivatePublicationError("PRIVATE_SUPPLY_RUNTIME_OBSERVATION_STALE")

    def finish_query(self) -> None:
        self._active = None


class PrivateSupplyExposureOwner:
    """Read-only existing binding owner; no fabricated private exposure ledger.

    440 bindings do not record hints/direct answers or complete family exposure.
    Until the real collector owns those records, absence of a binding cannot
    certify an unseen independent assessment. This narrow owner never says so.
    """
    def __init__(self, conn: Connection[dict[str, Any]], *, user_id: UUID, expected_epoch: int) -> None:
        self.conn, self.user_id, self.epoch = conn, user_id, expected_epoch

    def reason(self, record: PrivatePublishedRecordV1) -> SafeReason | None:
        proof = record.proof
        if (proof.user_id != self.user_id or proof.epoch != self.epoch
                or self.conn.info.transaction_status != TransactionStatus.INTRANS):
            return "private_owner_mismatch"
        # Invalidated bindings still count as prior exposure; never filter active.
        bindings = self.conn.execute(
            """SELECT b.version_id,p.payload_json
               FROM tutor_item_supply_private_bindings b
               LEFT JOIN tutor_item_supply_private_publication_proofs p
                 ON p.version_id=b.version_id AND p.user_id=b.user_id AND p.epoch=b.epoch
               WHERE b.user_id=%s AND b.epoch=%s LIMIT 4097 FOR SHARE OF b""",
            (self.user_id, self.epoch),
        ).fetchall()
        if len(bindings) > 4096:
            return "exposure_denied"
        for binding in bindings:
            if UUID(str(binding["version_id"])) == proof.version_id:
                return "exposure_denied"
            payload = binding["payload_json"]
            if payload is None or payload.get("candidate_family_id") == proof.candidate_family_id:
                return "exposure_denied"
        # No trusted complete hint/answer collector or slot-family mapping exists
        # yet. This bounded slice returns pending, rather than accepting a caller
        # ExposureSnapshot or claiming that an empty legacy binding set is proof.
        return "exposure_denied"


class SupplyQuery:
    def __init__(self, conn: Connection[dict[str, Any]], repository: PostgresPrivatePublicationRepository) -> None:
        self.conn, self.repository = conn, repository

    def _demand(self, demand_id: UUID, scope_id: UUID) -> tuple[AssessmentSupplyDemandV1, CoverageBlueprintV1]:
        repo = self.repository
        stored = PostgresPrivateSupplyStorage(self.conn, user_id=repo.user_id, expected_epoch=repo.expected_epoch)._scope(scope_id)
        scope = SupplyScopeV1.model_validate_json(json.dumps(stored["snapshot_json"]))
        row = self.conn.execute(
            """SELECT * FROM tutor_item_supply_private_demands
               WHERE id=%s AND scope_id=%s AND user_id=%s AND epoch=%s FOR SHARE""",
            (demand_id, scope_id, repo.user_id, repo.expected_epoch),
        ).fetchone()
        if row is None:
            raise PrivatePublicationError("PRIVATE_SUPPLY_DEMAND_UNAVAILABLE")
        demand = AssessmentSupplyDemandV1.model_validate_json(json.dumps(row["snapshot_json"]))
        node = self.conn.execute(
            """SELECT n.id,n.title,n.description,n.required_capabilities_json,n.prerequisite_keys_json,t.language_id
               FROM tutor_track_plan_nodes n JOIN tutor_track_active_plans p
                 ON p.revision_id=n.revision_id AND p.track_id=n.track_id AND p.user_id=n.user_id
               JOIN tutor_learning_tracks t ON t.id=n.track_id AND t.user_id=n.user_id
               WHERE n.user_id=%s AND n.track_id=%s AND n.revision_id=%s AND n.knowledge_key=%s
               FOR SHARE OF n,p,t""",
            (repo.user_id, stored["track_id"], stored["revision_id"], stored["knowledge_key"]),
        ).fetchone()
        if node is None:
            raise PrivatePublicationError("PRIVATE_SUPPLY_ACTIVE_SCOPE_STALE")
        node_snapshot = {key: str(value) if isinstance(value, UUID) else value for key, value in node.items()}
        scoped_hash = canonical_hash({"contract": scope.model_dump(mode="json"), "track_id": str(stored["track_id"]),
                                      "revision_id": str(stored["revision_id"]), "node_id": str(node["id"])})
        if (demand.scope != scope or demand.learner_ref != "user:" + str(repo.user_id)
                or scope.visibility != "private" or scope.owner_ref != demand.learner_ref
                or demand.demand_hash != row["demand_hash"] or demand.objective_hash != stored["objective_hash"]
                or stored["objective_hash"] != canonical_hash(node_snapshot) or stored["scope_hash"] != scoped_hash):
            raise PrivatePublicationError("PRIVATE_SUPPLY_ACTIVE_SCOPE_STALE")
        blueprint_row = self.conn.execute(
            "SELECT snapshot_json FROM tutor_item_supply_shared_blueprints WHERE blueprint_hash=%s FOR SHARE",
            (demand.blueprint_hash,),
        ).fetchone()
        if blueprint_row is None:
            raise PrivatePublicationError("PRIVATE_SUPPLY_BLUEPRINT_UNAVAILABLE")
        blueprint = CoverageBlueprintV1.model_validate_json(json.dumps(blueprint_row["snapshot_json"]))
        if (blueprint.blueprint_hash != demand.blueprint_hash or blueprint.objective_hash != demand.objective_hash
                or blueprint.matrix_hash != demand.matrix_hash or demand.matrix_hash != build_support_matrix().matrix_hash
                or blueprint.policy_version != demand.policy_version
                or blueprint.scope.model_dump(exclude={"visibility", "owner_ref"})
                   != scope.model_dump(exclude={"visibility", "owner_ref"})):
            raise PrivatePublicationError("PRIVATE_SUPPLY_BLUEPRINT_STALE")
        return demand, blueprint

    def _record(self, record: PrivatePublishedRecordV1, *, demand_id: UUID,
                scope_id: UUID, demand: AssessmentSupplyDemandV1, blueprint: CoverageBlueprintV1,
                now: datetime) -> IssuedAdmissionFactsV1:
        record = checked_model(record, PrivatePublishedRecordV1)
        pub, proof, materialization = record.publication, record.proof, record.materialization
        if (pub.user_id != self.repository.user_id or pub.epoch != self.repository.expected_epoch
                or pub.scope_id != scope_id or pub.state != "published"
                or proof.demand_id != demand_id or proof.demand != demand or proof.blueprint != blueprint
                or not proof.checked_at <= now < proof.valid_until):
            raise PrivatePublicationError("PRIVATE_SUPPLY_PROOF_STALE")
        # Require committed publisher authority, not own uncommitted writes or a
        # naked pre-admission JSON receipt. Normal MVCC excludes other writers.
        for table, identity in (("tutor_item_supply_private_materializations", pub.materialization_id),
                                ("tutor_item_supply_private_publication_events", pub.publication_id),
                                ("tutor_item_supply_private_publication_proofs", pub.proof_id)):
            state = self.conn.execute(
                f"SELECT pg_xact_status(xmin::text::xid8) AS status FROM {table} WHERE id=%s AND user_id=%s AND epoch=%s",
                (identity, pub.user_id, pub.epoch),
            ).fetchone()
            if state is None or state["status"] != "committed":
                raise PrivatePublicationError("PRIVATE_SUPPLY_COMMITTED_PUBLICATION_REQUIRED")
        artifact = self.conn.execute(
            """SELECT * FROM tutor_item_supply_private_generation_artifacts
               WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s FOR SHARE""",
            (pub.generation_artifact_id, pub.user_id, pub.epoch, pub.scope_id, pub.version_id),
        ).fetchone()
        fact_row = self.conn.execute(
            """SELECT payload_json,payload_hash FROM tutor_item_supply_private_admission_facts
               WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s FOR SHARE""",
            (pub.facts_receipt_id, pub.user_id, pub.epoch, pub.scope_id, pub.version_id),
        ).fetchone()
        eval_row = self.conn.execute(
            """SELECT payload_json,receipt_hash FROM tutor_item_supply_private_pipeline_receipts
               WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s
                 AND generation_artifact_id=%s AND artifact_kind='admission_evaluation' AND mode='live' FOR SHARE""",
            (pub.evaluation_receipt_id, pub.user_id, pub.epoch, pub.scope_id, pub.version_id, pub.generation_artifact_id),
        ).fetchone()
        if artifact is None or fact_row is None or eval_row is None:
            raise PrivatePublicationError("PRIVATE_SUPPLY_PUBLISHED_AUTHORITY_MISSING")
        facts = IssuedAdmissionFactsV1.model_validate_json(json.dumps(fact_row["payload_json"]))
        evaluation = AdmissionEvaluationV2.model_validate_json(json.dumps(eval_row["payload_json"]))
        if (facts.receipt_hash != fact_row["payload_hash"] or facts.receipt_id != pub.facts_receipt_id
                or facts.generation_artifact_id != pub.generation_artifact_id or facts.coverage.demand != demand
                or facts.coverage.coverage_blueprint != blueprint or candidate_family(facts) != proof.candidate_family_id
                or evaluation.evaluation_hash != eval_row["receipt_hash"]
                or evaluation.disposition != "eligible_internal" or evaluation.binding != facts.coverage.binding
                or evaluation.evidence_hash != canonical_hash(facts.evidence.model_dump(mode="json"))
                or tuple((m.clause_id, m.clause_hash) for m in facts.coverage.mappings)
                   != tuple((c.clause_id, c.clause_hash) for c in proof.clauses)
                or source_bindings(artifact, materialization.source) != proof.sources
                or tuple(binding.receipt for binding in proof.sources) != facts.coverage.source_receipts):
            raise PrivatePublicationError("PRIVATE_SUPPLY_PUBLISHED_AUTHORITY_MISMATCH")
        material = materialization.authority_material()
        require_exercise_quality(material.exercise, material.rubric, model_review_validation=material.model_review_validation)
        return facts

    def query_exact(self, *, demand_id: UUID, scope_id: UUID, source_authority: RagSourceAuthority,
                    runtime_facts: PrivateSupplyRuntimeOwner, exposure: PrivateSupplyExposureOwner) -> PrivateSupplyResultV1:
        repo = self.repository
        if (type(repo) is not PostgresPrivatePublicationRepository or repo.conn is not self.conn
                or type(source_authority) is not RagSourceAuthority or source_authority.connection is not self.conn
                or type(runtime_facts) is not PrivateSupplyRuntimeOwner or runtime_facts.conn is not self.conn
                or type(exposure) is not PrivateSupplyExposureOwner or exposure.conn is not self.conn
                or exposure.user_id != repo.user_id or exposure.epoch != repo.expected_epoch):
            raise PrivatePublicationError("PRIVATE_SUPPLY_CURRENT_OWNERS_REQUIRED")
        transaction_clock(self.conn)
        demand, blueprint = self._demand(demand_id, scope_id)
        reasons: list[SafeReason] = []
        selected: list[PrivateSupplySelectionV1] = []
        try:
            runtime_facts.begin_query()
            records = repo.load_exact(demand_id=demand_id, scope_id=scope_id)
            for record in records:
                try:
                    facts = self._record(record, demand_id=demand_id, scope_id=scope_id,
                                         demand=demand, blueprint=blueprint, now=transaction_clock(self.conn))
                    current_sources(self.conn, source_authority, record.proof.sources)
                    fingerprints = {r.lock_fingerprint for r in facts.coverage.execution_terminals}
                    fingerprints.update(r.lock_fingerprint for r in facts.ambiguity.terminals)
                    fingerprints.update(r.lock_fingerprint for r in facts.coverage.blind_terminals)
                    if fingerprints != {demand.scope.runtime_profile_hash}:
                        raise PrivatePublicationError("PRIVATE_SUPPLY_RUNTIME_SCOPE_MISMATCH")
                    runtime_id = "python-stdout-v1" if demand.scope.language_id == "python" else "sqlite-query-v1"
                    runtime_facts.assert_matches(runtime_id=runtime_id, fingerprints=fingerprints, now=transaction_clock(self.conn))
                    reason = exposure.reason(record)
                    # Exposure may wait on a binding lock. Recheck source and real
                    # observation/proof time after that wait, before any selection.
                    current_sources(self.conn, source_authority, record.proof.sources)
                    now = transaction_clock(self.conn)
                    runtime_facts.assert_matches(runtime_id=runtime_id, fingerprints=fingerprints, now=now)
                    if not record.proof.checked_at <= now < record.proof.valid_until:
                        raise PrivatePublicationError("PRIVATE_SUPPLY_PROOF_STALE")
                    if reason is not None:
                        reasons.append(reason)
                        continue
                    selected.append(PrivateSupplySelectionV1(handle=record.publication.handle,
                        publication_id=record.publication.publication_id,
                        materialization_id=record.publication.materialization_id, proof_id=record.proof.proof_id))
                except ValueError:
                    # Stable safe projection only; never leak private source or
                    # PostgreSQL/provider exception text. Transaction failures are
                    # not swallowed (psycopg errors propagate to caller rollback).
                    reasons.append("stale")
        except PrivatePublicationError:
            reasons.append("runtime_unavailable")
        finally:
            runtime_facts.finish_query()
        # This slice deliberately has no pack/slot-family/exposure authority.
        # Counts below do NOT count a discovered candidate as an independent slot.
        gaps = tuple(SupplyGapV1(clause_id=clause.clause_id, slot=slot,
                                required=getattr(blueprint.minimum, slot), available=0,
                                reason="insufficient_coverage")
                     for clause in blueprint.clauses for slot in _SLOTS)
        reasons.append("insufficient_coverage")
        status: Literal["pending", "stale", "gap"] = "pending" if "exposure_denied" in reasons else "stale" if "stale" in reasons else "gap"
        return PrivateSupplyResultV1(status=status,
            demand_hash=demand.demand_hash, blueprint_hash=blueprint.blueprint_hash,
            selected=tuple(selected), gaps=gaps, reasons=tuple(dict.fromkeys(reasons)))


_SLOTS: tuple[Slot, ...] = ("practice", "assessment", "remediation")
