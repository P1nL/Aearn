"""Opt-in NORMAL substantive child permission for ORIGINAL full admission.

No finding discharge, provider callbacks, publication, or JSON capability restore.
Controlled ancestry is denied before any readmission comparison. Old V3 payloads
are unchanged; an immutable side receipt binds the exact full original facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3, policy_for_hash
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.native_revision_recheck import (
    CommittedNativeRevisionRecheckInputs, NativeRevisionRecheckOwner, PreparedNativeRevisionRecheck,
)
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
    from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1

POLICY = "normal_revision_readmission_v1"
TABLE = "tutor_item_supply_shared_normal_revision_readmissions"
# Exact reviewed 522 body pin is populated with the migration, not a substring.
READMISSION_GUARD_SHA256 = "c95c1e10e96c968e4b6377440bcf4fefd23c16271d4640e1940badc8aef10d9b"
GUARD_BODY_PINS = {
    "item_supply_internal.assert_normal_revision_readmission(jsonb)": "db1ab4aaf95bfb60fd2e48d6237cffb46f4d09384e4529a83a90ecb8c9ec72ae",
    "item_supply_internal.assert_normal_revision_readmission_v2(jsonb)": "de5e9d508af74c23d6e83f3efdfaf0562c799e1625207988840be4fc4b42da5c",
    "item_supply_internal.enforce_normal_revision_readmission_insert()": "4000dcccef78eb5a6e00039270d96cf26d259e94a9ea51291417d9bd86efe1fd",
    "item_supply_internal.normal_revision_readmission_matches(uuid,uuid,text)": "5ea5a21ac6fddf078da074274e4fd8efea563afd0ee8c5a4bd5428ecf4deda34",
    "item_supply_internal.deny_revision_admission_without_discharge()": "c95c1e10e96c968e4b6377440bcf4fefd23c16271d4640e1940badc8aef10d9b"
}


@dataclass(frozen=True, repr=False)
class PreparedNormalRevisionReadmission:
    receipt_id: UUID
    recheck: PreparedNativeRevisionRecheck
    recheck_receipt_id: UUID
    recheck_hash: str
    lease: JobLeaseV1
    checked_at: datetime
    valid_until: datetime

    def seal_payload(self) -> dict[str, Any]:
        return dict(policy=POLICY, receipt_id=str(self.receipt_id), recheck_id=str(self.recheck.preparation_id),
            recheck_hash=self.recheck_hash, lineage_hash=self.recheck.lineage_hash,
            recheck_receipt_id=str(self.recheck_receipt_id), lease=self.lease.model_dump(mode="json"),
            checked_at=self.checked_at.isoformat(), valid_until=self.valid_until.isoformat())


class NativeNormalRevisionReadmissionOwner:
    def __init__(self, recheck: NativeRevisionRecheckOwner | None, *, enabled: bool = False,
                 committed_admission: IssuedCommittedChildAdmission | None = None) -> None:
        self._committed_admission = committed_admission
        self._committed_payloads: dict[UUID,dict[str,Any]] = {}
        if committed_admission is not None:
            from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
            if type(committed_admission) is not IssuedCommittedChildAdmission or recheck is not None:
                raise PipelineRepositoryError("COMMITTED_ADMISSION_NORMAL_ORIGINAL_FRAME_REQUIRED")
            self.conn,self.enabled = committed_admission.owner.conn,enabled
            return
        if type(recheck) is not NativeRevisionRecheckOwner:
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_RECHECK_OWNER_REQUIRED")
        self.recheck, self.conn, self.enabled = recheck, recheck.conn, enabled
        self._prepared: dict[UUID, tuple[PreparedNormalRevisionReadmission, str, Any]] = {}
        self._persisted: dict[UUID, tuple[dict[str, Any], str]] = {}
        self._started: set[UUID] = set()
        self._fact_frames: dict[UUID, tuple[SharedAdmissionFactsOwner, IssuedSharedAdmissionFactsV1]] = {}

    def require_schema(self) -> None:
        if self._committed_admission is not None:
            from app.services.learning.item_supply.persistent_pack_committed_admission import require_schema
            if not self.enabled:
                raise PipelineRepositoryError("NORMAL_READMISSION_DISABLED")
            require_schema(self.conn)
            return
        self.recheck._guard()
        if not self.enabled:
            raise PipelineRepositoryError("NORMAL_READMISSION_DISABLED")
        row = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_normal_revision_readmissions') AS t").fetchone()
        import hashlib
        if row is None or row["t"] is None:
            raise PipelineRepositoryError("NORMAL_READMISSION_522_EXACT_GUARD_REQUIRED")
        for signature, pin in GUARD_BODY_PINS.items():
            body = self.conn.execute("SELECT p.prosrc,p.prosecdef,p.proconfig,l.lanname FROM pg_proc p "
                "JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)", (signature,)).fetchone()
            if (body is None or hashlib.sha256(body["prosrc"].encode("utf-8")).hexdigest() != pin
                    or body["prosecdef"] is not True or body["lanname"] != "plpgsql"
                    or body["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]):
                raise PipelineRepositoryError("NORMAL_READMISSION_522_EXACT_GUARD_REQUIRED")

    def _noncontrolled(self, p: PreparedNativeRevisionRecheck) -> None:
        # Original process identity first, then ORIGINAL recursive controlled hold.
        # A normal receipt can never mask a marker on this job or any ancestor.
        if (type(self) is not NativeNormalRevisionReadmissionOwner
                or type(self.recheck) is not NativeRevisionRecheckOwner or self.recheck.conn is not self.conn):
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_RECHECK_OWNER_REQUIRED")
        self.recheck._issued(p)
        row = self.conn.execute("SELECT to_regprocedure('item_supply_internal.controlled_counterexample_held(uuid)') AS g").fetchone()
        if row is None or row["g"] is None:
            raise PipelineRepositoryError("SHARED_CONTROLLED_EXPERIMENT_HELD")
        held = self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(%s) AS held", (p.lease.job_id,)).fetchone()
        if held is None or held["held"] is not False:
            raise PipelineRepositoryError("SHARED_CONTROLLED_EXPERIMENT_HELD")
        if p.committed_child is not None:
            producer = self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(job_id) AS held "
                "FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s", (p.artifact_id,)).fetchone()
            if producer is None or producer["held"] is not False:
                raise PipelineRepositoryError("SHARED_CONTROLLED_EXPERIMENT_HELD")

    def _inputs(self, p: PreparedNativeRevisionRecheck, lease: JobLeaseV1, receipt_id: UUID, *,
                normal_facts_owner: SharedAdmissionFactsOwner | None = None,
                normal_facts: IssuedSharedAdmissionFactsV1 | None = None) -> CommittedNativeRevisionRecheckInputs:
        self._noncontrolled(p)
        self.require_schema()
        inputs = self.recheck.verified_readmission_inputs(p, lease=lease, recheck_receipt_id=receipt_id,
            normal_facts_owner=normal_facts_owner, normal_facts=normal_facts)
        # Explicit NEW permission is diagnosticV3 only; old policy hashes stay exact.
        if (type(policy_for_hash(inputs.review_prepared.binding.policy_hash)) is not AutonomousEvidencePolicyV3
                or inputs.review_result.blind is None or inputs.review_result.bundle is None):
            raise PipelineRepositoryError("NORMAL_READMISSION_DIAGNOSTIC_V3_COMPLETE_CHILD_REQUIRED")
        return inputs

    def prepare(self, *, recheck: PreparedNativeRevisionRecheck, lease: JobLeaseV1,
                recheck_receipt_id: UUID) -> PreparedNormalRevisionReadmission:
        lease = checked_model(lease, JobLeaseV1)
        inputs = self._inputs(recheck, lease, recheck_receipt_id)
        if any(p.recheck_receipt_id == recheck_receipt_id for p, _, _ in self._prepared.values()):
            raise PipelineRepositoryError("NORMAL_READMISSION_ONCE_ALREADY_PREPARED")
        now = server_clock(self.conn, datetime.now(UTC))
        until = min(recheck.revision.deadline_at, lease.expires_at, lease.parent_deadline,
            lease.profile.parent_deadline_at)
        if now >= until:
            raise PipelineRepositoryError("NORMAL_READMISSION_EXPIRED")
        p = PreparedNormalRevisionReadmission(uuid4(), recheck, recheck_receipt_id, inputs.recheck_hash, lease, now, until)
        self._prepared[p.receipt_id] = (p, canonical_hash(p.seal_payload()), self.recheck.review.settings.model_copy(deep=True))
        return p

    def verify_context(self, p: PreparedNormalRevisionReadmission, *, lease: JobLeaseV1) -> CommittedNativeRevisionRecheckInputs:
        if type(p) is not PreparedNormalRevisionReadmission:
            raise PipelineRepositoryError("NORMAL_READMISSION_PROCESS_ISSUER_REQUIRED")
        self._noncontrolled(p.recheck)
        entry = self._prepared.get(p.receipt_id)
        if (entry is None or entry[0] is not p or entry[1] != canonical_hash(p.seal_payload())
                or entry[2] != self.recheck.review.settings or lease != p.lease):
            raise PipelineRepositoryError("NORMAL_READMISSION_PROCESS_ISSUER_REQUIRED")
        frame = self._fact_frames.get(p.receipt_id)
        inputs = self._inputs(p.recheck, lease, p.recheck_receipt_id,
            normal_facts_owner=None if frame is None else frame[0], normal_facts=None if frame is None else frame[1])
        now = server_clock(self.conn, datetime.now(UTC))
        if inputs.recheck_hash != p.recheck_hash or not p.checked_at <= now < p.valid_until:
            raise PipelineRepositoryError("NORMAL_READMISSION_CURRENT_FENCE_CHANGED")
        return inputs

    def persist(self, p: PreparedNormalRevisionReadmission, *, facts_owner: SharedAdmissionFactsOwner,
                facts: IssuedSharedAdmissionFactsV1) -> None:
        from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner

        if (type(facts_owner) is not SharedAdmissionFactsOwner or facts_owner.conn is not self.conn
                or facts_owner.normal_readmission_owner is not self
                or facts_owner.validation_pipeline is not self.recheck.validation
                or facts_owner.review_pipeline is not self.recheck.review):
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_FACTS_OWNER_REQUIRED")
        pending = facts_owner._normal_pending.get(p.receipt_id)
        if pending is None or pending[0] is not facts or pending[1].normal_readmission is not p:
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_FULL_EVALUATION_REQUIRED")
        self.verify_context(p, lease=facts.lease)
        if (facts.receipt_id != p.receipt_id or facts.generation_artifact_id != p.recheck.artifact_id
                or not p.checked_at <= facts.checked_at < facts.valid_until <= p.valid_until):
            raise PipelineRepositoryError("NORMAL_READMISSION_FACTS_BINDING_MISMATCH")
        if p.receipt_id in self._started:
            raise PipelineRepositoryError("NORMAL_READMISSION_ONCE_ALREADY_CONSUMED")
        self._started.add(p.receipt_id)
        r = p.recheck
        payload = dict(schema_version=POLICY, receipt_id=str(p.receipt_id), root_id=str(facts.root_id),
            lineage_id=str(r.revision.preparation_id), lineage_hash=r.lineage_hash,
            recheck_receipt_id=str(p.recheck_receipt_id), recheck_hash=p.recheck_hash,
            artifact_id=str(facts.generation_artifact_id), artifact_hash=facts.artifact_hash,
            lease=facts.lease.model_dump(mode="json"), binding=facts.evidence.binding.model_dump(mode="json"),
            validation_preparation_id=str(facts.validation_preparation_id),
            validation_receipt_id=str(facts.validation_receipt_id), validation_hash=facts.validation_receipt_hash,
            blind_receipt_id=str(facts.blind_receipt_id), blind_hash=facts.blind_receipt_hash,
            review_receipt_id=str(facts.review_receipt_id), review_hash=facts.review_receipt_hash,
            policy_hash=facts.evidence.binding.policy_hash, facts_receipt_id=str(facts.receipt_id),
            facts_payload_hash=facts.receipt_hash, facts_payload=facts.model_dump(mode="json"),
            checked_at=facts.checked_at.isoformat(), valid_until=facts.valid_until.isoformat(),
            publication_enabled=False, historical_findings_discharged=False)
        if r.committed_child is not None:
            payload.update(schema_version="normal_revision_readmission_v2",
                committed_child=r.committed_child.payload)
        row = self.conn.execute(f"INSERT INTO {TABLE}(id,root_id,job_id,generation_artifact_id,lineage_id,recheck_receipt_id,"
            "validation_receipt_id,blind_receipt_id,review_receipt_id,facts_payload_hash,payload_json,valid_until) "
            "VALUES(" + ",".join(["%s"] * 12) + ") RETURNING payload_hash",
            (p.receipt_id, facts.root_id, facts.lease.job_id, facts.generation_artifact_id, r.revision.preparation_id,
             p.recheck_receipt_id, facts.validation_receipt_id, facts.blind_receipt_id, facts.review_receipt_id,
             facts.receipt_hash, Jsonb(payload), facts.valid_until)).fetchone()
        if row is None or row["payload_hash"] != canonical_hash(payload):
            raise PipelineRepositoryError("NORMAL_READMISSION_STORAGE_HASH_MISMATCH")
        self._persisted[p.receipt_id] = (payload, row["payload_hash"])
        # This is not usable until ORIGINAL facts issue has inserted and sealed
        # its exact row. Never reconstruct a frame from stored JSON.
        self._fact_frames[p.receipt_id] = (facts_owner, facts)

    def require_terminal_frame(self, *, facts_owner: SharedAdmissionFactsOwner,
                               facts: IssuedSharedAdmissionFactsV1, lease: JobLeaseV1) -> PreparedNormalRevisionReadmission:
        """Nonrecursive ORIGINAL process seal + side/facts readback, not verify().

        The caller original revision/recheck verifier still performs its complete
        current source/lease/lineage/new-evidence fences. This frame only identifies
        the ONE exact child terminal already issued by those original owners.
        """
        from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
        from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1

        if type(facts_owner) is not SharedAdmissionFactsOwner or type(facts) is not IssuedSharedAdmissionFactsV1:
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_FACTS_PROCESS_FRAME_REQUIRED")
        original = facts_owner._issued.get(facts.receipt_id)
        if original is None or original[0] != checked_model(facts, IssuedSharedAdmissionFactsV1):
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_FACTS_PROCESS_FRAME_REQUIRED")
        p = original[1].normal_readmission
        if type(p) is not PreparedNormalRevisionReadmission:
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_FACTS_PROCESS_FRAME_REQUIRED")
        self._noncontrolled(p.recheck)  # Controlled BEFORE permission comparisons.
        if (facts_owner.conn is not self.conn or facts_owner.normal_readmission_owner is not self
                or facts_owner.validation_pipeline is not self.recheck.validation
                or facts_owner.review_pipeline is not self.recheck.review):
            raise PipelineRepositoryError("NORMAL_READMISSION_ORIGINAL_FACTS_PROCESS_FRAME_REQUIRED")
        entry = self._prepared.get(p.receipt_id)
        frame = self._fact_frames.get(p.receipt_id)
        if (entry is None or entry[0] is not p or entry[1] != canonical_hash(p.seal_payload())
                or entry[2] != self.recheck.review.settings or frame is None
                or frame[0] is not facts_owner or frame[1] is not original[0]
                or facts.lease != lease or p.lease != lease or facts.receipt_id != p.receipt_id
                or facts.generation_artifact_id != p.recheck.artifact_id):
            raise PipelineRepositoryError("NORMAL_READMISSION_EXACT_PREPARED_PROCESS_FRAME_REQUIRED")
        facts_owner._transaction()  # Owner/settings gates only; NO recursive verify.
        self.require_schema()
        stored = self._persisted.get(p.receipt_id)
        side = self.conn.execute(f"SELECT * FROM {TABLE} WHERE id=%s FOR SHARE", (p.receipt_id,)).fetchone()
        actual = self.conn.execute("SELECT payload_json,payload_hash,generation_artifact_id,job_id,root_id "
            "FROM tutor_item_supply_shared_admission_facts WHERE id=%s FOR SHARE", (p.receipt_id,)).fetchone()
        if (stored is None or side is None or actual is None
                or (side["payload_json"], side["payload_hash"]) != stored
                or canonical_hash(side["payload_json"]) != side["payload_hash"]
                or side["payload_json"]["facts_payload"] != facts.model_dump(mode="json")
                or side["facts_payload_hash"] != facts.receipt_hash or actual["payload_hash"] != facts.receipt_hash
                or actual["payload_json"] != facts.model_dump(mode="json")
                or (side["root_id"], side["job_id"], side["generation_artifact_id"], side["lineage_id"],
                    side["recheck_receipt_id"], side["validation_receipt_id"], side["blind_receipt_id"], side["review_receipt_id"])
                != (facts.root_id, lease.job_id, facts.generation_artifact_id, p.recheck.revision.preparation_id,
                    p.recheck_receipt_id, facts.validation_receipt_id, facts.blind_receipt_id, facts.review_receipt_id)
                or (actual["root_id"], actual["job_id"], actual["generation_artifact_id"])
                != (facts.root_id, lease.job_id, facts.generation_artifact_id)):
            raise PipelineRepositoryError("NORMAL_READMISSION_CURRENT_EXACT_SIDE_AND_FACTS_REQUIRED")
        now = server_clock(self.conn, datetime.now(UTC))
        if not p.checked_at <= facts.checked_at <= now < min(p.valid_until, facts.valid_until, side["valid_until"]):
            raise PipelineRepositoryError("NORMAL_READMISSION_EXPIRED")
        return p

    def verify_persisted(self, p: PreparedNormalRevisionReadmission, *, facts: IssuedSharedAdmissionFactsV1) -> None:
        self.verify_context(p, lease=facts.lease)
        stored = self._persisted.get(p.receipt_id)
        row = self.conn.execute(f"SELECT payload_json,payload_hash FROM {TABLE} WHERE id=%s FOR SHARE", (p.receipt_id,)).fetchone()
        if (stored is None or row is None or (row["payload_json"], row["payload_hash"]) != stored
                or row["payload_json"]["facts_payload"] != facts.model_dump(mode="json")
                or row["payload_json"]["facts_payload_hash"] != facts.receipt_hash):
            raise PipelineRepositoryError("NORMAL_READMISSION_PERSISTED_EXACT_FACTS_REQUIRED")

    def persist_committed(self, frame: IssuedCommittedChildAdmission, *, facts_owner: SharedAdmissionFactsOwner,
                          facts: IssuedSharedAdmissionFactsV1) -> None:
        from app.services.learning.item_supply.persistent_pack_committed_admission import require
        if (frame is not self._committed_admission or facts_owner is not frame.facts_owner
                or facts_owner._committed_pending is not facts or not self.enabled):
            raise PipelineRepositoryError("COMMITTED_ADMISSION_NORMAL_FULL_EVALUATION_REQUIRED")
        require(frame)
        if facts.receipt_id in self._committed_payloads or facts.lease != frame.lease or facts.receipt_id != frame.admission_id:
            raise PipelineRepositoryError("COMMITTED_ADMISSION_NORMAL_ONCE_REQUIRED")
        q = frame.quality
        payload = dict(schema_version="normal_revision_readmission_v3",receipt_id=str(facts.receipt_id),root_id=str(facts.root_id),
            lineage_id=str(q.lineage["id"]),lineage_hash=q.lineage["snapshot_hash"],recheck_receipt_id=str(q.recheck["id"]),
            recheck_hash=q.recheck["snapshot_hash"],artifact_id=str(facts.generation_artifact_id),artifact_hash=facts.artifact_hash,
            lease=facts.lease.model_dump(mode="json"),binding=q.bundle.binding.model_dump(mode="json"),
            validation_preparation_id=str(facts.validation_preparation_id),validation_receipt_id=str(facts.validation_receipt_id),
            validation_hash=facts.validation_receipt_hash,blind_receipt_id=str(facts.blind_receipt_id),blind_hash=facts.blind_receipt_hash,
            review_receipt_id=str(facts.review_receipt_id),review_hash=facts.review_receipt_hash,policy_hash=q.bundle.binding.policy_hash,
            facts_receipt_id=str(facts.receipt_id),facts_payload_hash=facts.receipt_hash,facts_payload=facts.model_dump(mode="json"),
            checked_at=facts.checked_at.isoformat(),valid_until=facts.valid_until.isoformat(),publication_enabled=False,
            historical_findings_discharged=False,admission_action_id=str(frame.admission_id),admission_action_hash=canonical_hash(frame.payload))
        row = self.conn.execute(f"INSERT INTO {TABLE}(id,root_id,job_id,generation_artifact_id,lineage_id,recheck_receipt_id,"
            "validation_receipt_id,blind_receipt_id,review_receipt_id,facts_payload_hash,payload_json,valid_until) "
            "VALUES("+",".join(["%s"]*12)+") RETURNING payload_hash",(facts.receipt_id,facts.root_id,facts.lease.job_id,
            facts.generation_artifact_id,q.lineage["id"],q.recheck["id"],facts.validation_receipt_id,facts.blind_receipt_id,
            facts.review_receipt_id,facts.receipt_hash,Jsonb(payload),facts.valid_until)).fetchone()
        if row is None or row["payload_hash"] != canonical_hash(payload):
            raise PipelineRepositoryError("COMMITTED_ADMISSION_NORMAL_HASH_CHANGED")
        self._committed_payloads[facts.receipt_id] = payload

    def verify_committed(self, frame: IssuedCommittedChildAdmission, *, facts: IssuedSharedAdmissionFactsV1) -> None:
        from app.services.learning.item_supply.persistent_pack_committed_admission import require
        if frame is not self._committed_admission or facts.lease != frame.lease:
            raise PipelineRepositoryError("COMMITTED_ADMISSION_NORMAL_ISSUER_REQUIRED")
        require(frame)
        payload = self._committed_payloads.get(facts.receipt_id)
        row = self.conn.execute(f"SELECT payload_json,payload_hash FROM {TABLE} WHERE id=%s FOR SHARE",(facts.receipt_id,)).fetchone()
        if (payload is None or row is None or row["payload_json"] != payload or row["payload_hash"] != canonical_hash(payload)
                or payload["facts_payload"] != facts.model_dump(mode="json")):
            raise PipelineRepositoryError("COMMITTED_ADMISSION_NORMAL_PERSISTED_FACTS_REQUIRED")
