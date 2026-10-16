"""Caller-transaction P2 repositories; no claim, provider or ready/publication path."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import (
    LearningItemPrivateV1,
    LearningItemPublicV1,
    canonical_hash,
)
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1,
    CoverageBlueprintV1,
    SupplyScopeV1,
    revalidate_contract,
)
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.storage_contracts import (
    AdmissionDecisionV2,
    AutonomousEvidencePolicyV2,
    EvidenceV2,
    ObservationV2,
    SourceCoordinatesV2,
    checked_model,
)
from app.services.learning.item_supply.storage_tables import (
    NATIVE_EXPOSURE_UNSCOPED_TABLES, NATIVE_TYPE_UNSCOPED_TABLES,
    P7_FINITE_COURSE_MAPPING_TABLES, P7_NATIVE_CONSUMER_TABLES, PRIVATE_TABLES,
    PRIVATE_NATIVE_UNSCOPED_TABLES,
)


class SupplyStorageError(ValueError):
    """Uniform private scope failure: no cross-owner existence disclosure."""


@dataclass(frozen=True)
class FrozenPrivateScope:
    id: UUID
    scope_hash: str
    objective_hash: str


@dataclass(frozen=True)
class PrivateVersionIdentity:
    id: UUID
    handle: str
    payload_hash: str


def _append(
    conn: Connection[dict[str, object]], table: str,
    facts: Mapping[str, object], identity: Sequence[str],
) -> dict[str, object]:
    """Same immutable idempotency identity permits only identical facts."""
    keys = tuple(facts)
    values = tuple(Jsonb(value) if isinstance(value, dict) else value for value in facts.values())
    row = conn.execute(sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING RETURNING *"
    ).format(sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, keys)),
             sql.SQL(",").join(sql.Placeholder() for _ in keys)), values).fetchone()
    if row is not None:
        return row
    predicate = sql.SQL(" AND ").join(
        sql.SQL("{} IS NOT DISTINCT FROM %s").format(sql.Identifier(key)) for key in identity
    )
    row = conn.execute(sql.SQL("SELECT * FROM {} WHERE {}").format(
        sql.Identifier(table), predicate,
    ), tuple(Jsonb(facts[key]) if isinstance(facts[key], dict) else facts[key] for key in identity)).fetchone()
    if row is None:
        raise SupplyStorageError("immutable supply identity conflict")
    # SQL equality normalizes jsonb and UUID values; do not compare JSON strings.
    same = conn.execute(sql.SQL("SELECT id FROM {} WHERE id=%s AND {}").format(
        sql.Identifier(table), sql.SQL(" AND ").join(
            sql.SQL("{} IS NOT DISTINCT FROM %s").format(sql.Identifier(key)) for key in keys
        ),
    ), (row["id"], *values)).fetchone()
    if same is None:
        raise SupplyStorageError("immutable supply identity conflict")
    return row


def _source_columns(source: SourceCoordinatesV2 | None) -> dict[str, object]:
    if source is None:
        return dict.fromkeys(("source_subject", "source_corpus", "source_document", "source_chunk", "source_receipt"))
    checked = checked_model(source, SourceCoordinatesV2)
    return {
        "source_subject": checked.subject, "source_corpus": checked.corpus_id,
        "source_document": checked.document_id, "source_chunk": checked.chunk_id,
        "source_receipt": checked.receipt_id,
    }


class PostgresSharedSupplyStorage:
    """Public-only authority snapshots; no private pool search or promotion."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self.conn = conn

    def register_policy(self, policy: AutonomousEvidencePolicyV2) -> UUID:
        checked = checked_model(policy, AutonomousEvidencePolicyV2)
        row = _append(self.conn, "tutor_item_supply_shared_policies", {
            "policy_version": checked.policy_version, "policy_hash": checked.policy_hash,
            "policy_json": checked.model_dump(mode="json"),
        }, ("policy_version",))
        return UUID(str(row["id"]))

    def register_blueprint(self, blueprint: CoverageBlueprintV1) -> UUID:
        checked = revalidate_contract(blueprint, CoverageBlueprintV1)
        if checked.scope.visibility != "public" or checked.scope.owner_ref is not None:
            raise SupplyStorageError("private blueprint cannot enter shared storage")
        matrix = build_support_matrix()
        if checked.matrix_hash != matrix.matrix_hash:
            raise SupplyStorageError("matrix identity mismatch")
        _append(self.conn, "tutor_item_supply_shared_matrices", {
            "matrix_hash": matrix.matrix_hash, "snapshot_json": matrix.model_dump(mode="json"),
        }, ("matrix_hash",))
        row = _append(self.conn, "tutor_item_supply_shared_blueprints", {
            "blueprint_hash": checked.blueprint_hash, "objective_hash": checked.objective_hash,
            "matrix_hash": checked.matrix_hash, "policy_version": checked.policy_version,
            "snapshot_json": checked.model_dump(mode="json"),
        }, ("blueprint_hash",))
        for clause in checked.clauses:
            for slot in ("practice", "assessment", "remediation"):
                _append(self.conn, "tutor_item_supply_shared_slots", {
                    "blueprint_id": row["id"], "clause_id": clause.clause_id,
                    "clause_hash": clause.clause_hash, "slot": slot,
                    "required_count": getattr(checked.minimum, slot),
                }, ("blueprint_id", "clause_id", "slot"))
        return UUID(str(row["id"]))


class PostgresPrivateSupplyStorage:
    """Trusted service identity bound once, and rechecked for every operation.

    expected_epoch is a frozen request/worker fact. Never silently refresh it
    after reset; a new epoch requires a newly authorized request.
    """

    def __init__(self, conn: Connection[dict[str, object]], *, user_id: UUID, expected_epoch: int) -> None:
        if type(user_id) is not UUID or type(expected_epoch) is not int or expected_epoch < 1:
            raise SupplyStorageError("private supply scope unavailable")
        self.conn = conn
        self.user_id = user_id
        self.epoch = expected_epoch

    def _check_epoch(self) -> None:
        user = self.conn.execute(
            "SELECT id FROM users WHERE id=%s AND deleted_at IS NULL FOR SHARE", (self.user_id,),
        ).fetchone()
        if user is None:
            raise SupplyStorageError("private supply scope unavailable")
        self.conn.execute(
            "INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(%s) ON CONFLICT DO NOTHING",
            (self.user_id,),
        )
        row = self.conn.execute(
            "SELECT epoch,enabled FROM tutor_item_supply_user_epochs WHERE user_id=%s FOR SHARE",
            (self.user_id,),
        ).fetchone()
        if row is None or row["epoch"] != self.epoch or row["enabled"] is not True:
            raise SupplyStorageError("stale supply epoch")

    def bind_scope(self, *, track_id: UUID, revision_id: UUID, scope: SupplyScopeV1) -> FrozenPrivateScope:
        self._check_epoch()
        checked = revalidate_contract(scope, SupplyScopeV1)
        if checked.visibility != "private" or checked.owner_ref != f"user:{self.user_id}":
            raise SupplyStorageError("private supply scope unavailable")
        node = self.conn.execute(
            """SELECT n.id,n.title,n.description,n.required_capabilities_json,n.prerequisite_keys_json,t.language_id
               FROM tutor_track_plan_nodes n JOIN tutor_track_active_plans p
               ON p.revision_id=n.revision_id AND p.track_id=n.track_id AND p.user_id=n.user_id
               JOIN tutor_learning_tracks t ON t.id=n.track_id AND t.user_id=n.user_id
               WHERE n.user_id=%s AND n.track_id=%s AND n.revision_id=%s AND n.knowledge_key=%s
               FOR SHARE OF n,p""",
            (self.user_id, track_id, revision_id, checked.knowledge_key),
        ).fetchone()
        if node is None or node["language_id"] != checked.language_id:
            raise SupplyStorageError("private supply scope unavailable")
        objective_hash = canonical_hash({key: str(value) if isinstance(value, UUID) else value
                                         for key, value in node.items()})
        scope_hash = canonical_hash({
            "contract": checked.model_dump(mode="json"), "track_id": str(track_id),
            "revision_id": str(revision_id), "node_id": str(node["id"]),
        })
        row = _append(self.conn, "tutor_item_supply_private_scopes", {
            "user_id": self.user_id, "epoch": self.epoch, "track_id": track_id,
            "revision_id": revision_id, "knowledge_key": checked.knowledge_key,
            "scope_hash": scope_hash, "objective_hash": objective_hash,
            "snapshot_json": checked.model_dump(mode="json"),
        }, ("user_id", "epoch", "scope_hash"))
        return FrozenPrivateScope(UUID(str(row["id"])), scope_hash, objective_hash)

    def _scope(self, scope_id: UUID) -> dict[str, object]:
        self._check_epoch()
        row = self.conn.execute(
            """SELECT s.* FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
               ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
               WHERE s.id=%s AND s.user_id=%s AND s.epoch=%s FOR SHARE OF s,p""",
            (scope_id, self.user_id, self.epoch),
        ).fetchone()
        if row is None:
            raise SupplyStorageError("private supply scope unavailable")
        return row

    def _facts(self, scope_id: UUID) -> dict[str, object]:
        self._scope(scope_id)
        return {"user_id": self.user_id, "epoch": self.epoch, "scope_id": scope_id}

    def store_material(
        self, *, scope_id: UUID, material_key: str, content_text: str,
        source: SourceCoordinatesV2 | None = None,
    ) -> UUID:
        if type(content_text) is not str or len(content_text.encode("utf-8")) > 262144:
            raise SupplyStorageError("invalid private material")
        row = _append(self.conn, "tutor_item_supply_private_materials", {
            **self._facts(scope_id), "material_key": material_key, "content_text": content_text,
            **_source_columns(source),
        }, ("user_id", "epoch", "material_key"))
        return UUID(str(row["id"]))

    def store_candidate(
        self, *, scope_id: UUID, candidate_key: str, material_id: UUID | None = None,
        parent_candidate_id: UUID | None = None,
    ) -> UUID:
        row = _append(self.conn, "tutor_item_supply_private_candidates", {
            **self._facts(scope_id), "candidate_key": candidate_key, "material_id": material_id,
            "parent_candidate_id": parent_candidate_id,
        }, ("user_id", "epoch", "candidate_key"))
        return UUID(str(row["id"]))

    def store_version(
        self, *, scope_id: UUID, candidate_id: UUID, version: int,
        public: LearningItemPublicV1, private: LearningItemPrivateV1,
    ) -> PrivateVersionIdentity:
        public_checked = checked_model(public, LearningItemPublicV1)
        private_checked = checked_model(private, LearningItemPrivateV1)
        if (public_checked.item_key, public_checked.version, public_checked.kind) != (
            private_checked.item_key, private_checked.version, private_checked.kind
        ):
            raise SupplyStorageError("private version identity mismatch")
        row = _append(self.conn, "tutor_item_supply_private_versions", {
            **self._facts(scope_id), "candidate_id": candidate_id, "version": version,
            "public_json": public_checked.model_dump(mode="json"),
            "private_json": private_checked.model_dump(mode="json"),
        }, ("candidate_id", "version", "user_id", "epoch"))
        return PrivateVersionIdentity(UUID(str(row["id"])), str(row["handle"]), str(row["payload_hash"]))

    def get_version(self, *, scope_id: UUID, handle: str) -> PrivateVersionIdentity:
        self._scope(scope_id)
        row = self.conn.execute(
            "SELECT id,handle,payload_hash FROM tutor_item_supply_private_versions "
            "WHERE scope_id=%s AND handle=%s AND user_id=%s AND epoch=%s",
            (scope_id, handle, self.user_id, self.epoch),
        ).fetchone()
        if row is None:
            raise SupplyStorageError("private supply scope unavailable")
        return PrivateVersionIdentity(UUID(str(row["id"])), str(row["handle"]), str(row["payload_hash"]))

    def store_demand(self, *, scope_id: UUID, request_key: str, demand: AssessmentSupplyDemandV1) -> UUID:
        stored = self._scope(scope_id)
        checked = revalidate_contract(demand, AssessmentSupplyDemandV1)
        if (checked.learner_ref != f"user:{self.user_id}"
                or canonical_hash(checked.scope.model_dump(mode="json")) != canonical_hash(stored["snapshot_json"])
                or checked.objective_hash != stored["objective_hash"]):
            raise SupplyStorageError("demand scope mismatch")
        row = _append(self.conn, "tutor_item_supply_private_demands", {
            **self._facts(scope_id), "request_key": request_key, "demand_hash": checked.demand_hash,
            "snapshot_json": checked.model_dump(mode="json"),
        }, ("user_id", "epoch", "request_key"))
        return UUID(str(row["id"]))

    def store_observation(self, *, scope_id: UUID, job_id: UUID, observation: ObservationV2) -> UUID:
        checked = checked_model(observation, ObservationV2)
        if checked.origin == "real_learner" and checked.actor_id != self.user_id:
            raise SupplyStorageError("observation scope mismatch")
        row = _append(self.conn, "tutor_item_supply_private_observations", {
            **self._facts(scope_id), "job_id": job_id,
            **checked.model_dump(mode="python"),
        }, ("job_id", "event_key", "user_id", "epoch"))
        return UUID(str(row["id"]))

    def store_evidence(
        self, *, scope_id: UUID, job_id: UUID, version_id: UUID, evidence: EvidenceV2,
    ) -> UUID:
        checked = checked_model(evidence, EvidenceV2)
        facts = self._facts(scope_id)
        version = self.conn.execute(
            "SELECT payload_hash FROM tutor_item_supply_private_versions "
            "WHERE id=%s AND scope_id=%s AND user_id=%s AND epoch=%s",
            (version_id, scope_id, self.user_id, self.epoch),
        ).fetchone()
        if version is None:
            raise SupplyStorageError("private supply scope unavailable")
        row = _append(self.conn, "tutor_item_supply_private_evidence", {
            **facts, "job_id": job_id, "version_id": version_id, "item_hash": version["payload_hash"],
            **checked.model_dump(mode="python", exclude={"source"}), **_source_columns(checked.source),
        }, ("job_id", "evidence_key", "user_id", "epoch"))
        return UUID(str(row["id"]))

    def store_admission(
        self, *, scope_id: UUID, evidence_id: UUID, decision: AdmissionDecisionV2,
    ) -> UUID:
        checked = checked_model(decision, AdmissionDecisionV2)
        facts = self._facts(scope_id)
        evidence = self.conn.execute(
            "SELECT version_id,item_hash,policy_version FROM tutor_item_supply_private_evidence "
            "WHERE id=%s AND scope_id=%s AND user_id=%s AND epoch=%s",
            (evidence_id, scope_id, self.user_id, self.epoch),
        ).fetchone()
        if evidence is None:
            raise SupplyStorageError("private supply scope unavailable")
        row = _append(self.conn, "tutor_item_supply_private_admissions", {
            **facts, **evidence, "evidence_id": evidence_id, **checked.model_dump(mode="python"),
        }, ("user_id", "epoch", "admission_key"))
        return UUID(str(row["id"]))


def purge_private_supply(conn: Connection[dict[str, object]], user_id: UUID, *, deleting: bool = False) -> int:
    """Only call from the confirmed existing reset/delete owner transaction.

    EXECUTE is revoked from PUBLIC. Explicit deployment maintenance grants are
    separate from ordinary writer privileges; no GUC grants this capability.
    """
    row = conn.execute("SELECT purge_item_supply_private(%s,%s) AS epoch", (user_id, deleting)).fetchone()
    if row is None:
        raise SupplyStorageError("private supply purge failed")
    return int(str(row["epoch"]))


def export_private_supply(conn: Connection[dict[str, object]], user_id: UUID) -> dict[str, object]:
    """All private responsibilities are classified, with safe bounded projections."""
    result: dict[str, object] = {}
    for table in PRIVATE_TABLES:
        if table.endswith("_scopes"):
            scope_column = "id AS scope_id"
        elif (table == "tutor_item_supply_private_runtime_user_limits"
              or table in NATIVE_EXPOSURE_UNSCOPED_TABLES
              or table in NATIVE_TYPE_UNSCOPED_TABLES
              or table in P7_FINITE_COURSE_MAPPING_TABLES
              or table in P7_NATIVE_CONSUMER_TABLES
              or table in PRIVATE_NATIVE_UNSCOPED_TABLES):
            scope_column = "NULL::uuid AS scope_id"
        else:
            scope_column = "scope_id"
        identity_column = (
            "artifact_id AS id"
            if table in {"tutor_item_supply_native_artifact_bindings",
                         "tutor_item_supply_private_native_artifact_bindings"} else "id"
        )
        rows = conn.execute(sql.SQL(
            "SELECT " + identity_column + "," + scope_column
            + ",created_at FROM {} WHERE user_id=%s ORDER BY created_at,id LIMIT 1001"
        ).format(sql.Identifier(table)), (user_id,)).fetchall()
        result[table] = {
            "records": [{"id": str(row["id"]),
                         "scope_id": None if row["scope_id"] is None else str(row["scope_id"]),
                         "created_at": str(row["created_at"])} for row in rows[:1000]],
            "truncated": len(rows)>1000,
        }
    epoch = conn.execute(
        "SELECT epoch,enabled FROM tutor_item_supply_user_epochs WHERE user_id=%s", (user_id,),
    ).fetchone()
    result["epoch"] = epoch
    return result
