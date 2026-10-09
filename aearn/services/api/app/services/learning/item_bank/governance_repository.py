"""PostgreSQL authority for Learning Item review, pilot, and publication."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection

from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1,
    LearningItemValidationReceiptV1,
    canonical_hash,
    canonical_json,
    learning_item_uuid,
    stable_key,
)
from app.services.learning.item_bank.practice_adapter import (
    LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
    build_exercise_authority,
)
from app.services.learning.item_bank.repository import (
    LearningItemPublicationResult,
    PostgresLearningItemBankRepository,
)
from app.services.learning.item_bank.review import (
    LearningItemReviewSubject,
    adjudicate_learning_item_reviews,
)
from app.services.learning.item_bank.review_contracts import (
    LEARNING_ITEM_HUMAN_APPROVAL_POLICY_VERSION,
    LEARNING_ITEM_REVIEW_POLICY_VERSION,
    LearningItemHumanApprovalV1,
    LearningItemPilotDecision,
    LearningItemPilotReceiptV1,
    LearningItemPilotTelemetryV1,
    LearningItemReviewAdjudicationV1,
    LearningItemReviewReportV1,
    evaluate_pilot,
)
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.practice.quality import require_exercise_quality
from app.services.learning.practice.repository import PostgresExerciseGateRepository


_HANDLE = re.compile(r"^li:[0-9a-f]{64}$")


class LearningItemGovernanceError(ValueError):
    """Base learner-safe governance error."""


class LearningItemGovernanceConflict(LearningItemGovernanceError):
    """Stored immutable authority conflicts with the requested replay."""


@dataclass(frozen=True, slots=True)
class LearningItemReviewGovernanceResult:
    adjudication_id: str
    adjudication: LearningItemReviewAdjudicationV1
    publication: LearningItemPublicationResult | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class LearningItemPilotGovernanceResult:
    receipt_id: str
    pilot_sequence: int
    receipt: LearningItemPilotReceiptV1
    publication: LearningItemPublicationResult | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class LearningItemHumanApprovalResult:
    approval_id: str
    approval: LearningItemHumanApprovalV1
    publication: LearningItemPublicationResult
    replayed: bool


@dataclass(frozen=True, slots=True)
class LearningItemPracticeMaterializationResult:
    materialization_id: str
    exercise_version_id: str
    receipt_hash: str
    replayed: bool


class PostgresLearningItemGovernanceRepository:
    """Caller-transaction-owned governance writes over shared immutable rows."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._items = PostgresLearningItemBankRepository(conn)

    def _deny_native(self, handle: str) -> None:
        # V2 native versions have a different concrete current-facts publisher.
        # Never feed their SQL/Python into the legacy V1 validator, fabricate V1
        # review/pilot authority, or reach automatic materialization/promotion.
        row = self._conn.execute(
            "SELECT 1 FROM tutor_learning_item_validation_receipts r "
            "JOIN tutor_learning_item_versions v ON v.id=r.version_id "
            "WHERE v.handle=%s AND r.schema_version='candidate_validation_v2' LIMIT 1", (handle,),
        ).fetchone()
        if row is not None:
            raise LearningItemGovernanceError("Native Learning Item requires current native publication authority")

    def load_review_subject(self, *, handle: str) -> LearningItemReviewSubject:
        item_handle = _handle(handle)
        self._deny_native(item_handle)
        row = self._conn.execute(
            """
            SELECT versions.id,versions.creator_identity,versions.handle,versions.content_hash,
                   blueprints.blueprint_json,public.public_json,private.private_json,
                   validations.receipt_json
            FROM tutor_learning_item_versions AS versions
            JOIN tutor_learning_item_blueprints AS blueprints ON blueprints.id=versions.blueprint_id
            JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
            JOIN tutor_learning_item_private_contents AS private ON private.version_id=versions.id
            JOIN tutor_learning_item_validation_receipts AS validations ON validations.version_id=versions.id
            WHERE versions.handle=%s AND validations.passed
            """,
            (item_handle,),
        ).fetchone()
        if row is None:
            raise LearningItemGovernanceError("Learning Item review subject was not found")
        source = LearningItemSourceV1.model_validate(
            {
                "schema_version": "learning_item_source_v1",
                "blueprint": _mapping(row["blueprint_json"]),
                "public": _mapping(row["public_json"]),
                "private": _mapping(row["private_json"]),
            }
        )
        validation = LearningItemValidationReceiptV1.model_validate(_mapping(row["receipt_json"]))
        expected_validation = validate_learning_item(source)
        if (
            source.content_hash != str(row["content_hash"])
            or validation.item_handle != item_handle
            or validation != expected_validation
        ):
            raise LearningItemGovernanceConflict("Stored Learning Item review subject is stale")
        return LearningItemReviewSubject(
            version_id=str(row["id"]),
            creator_identity=str(row["creator_identity"]),
            source=source,
            validation_receipt=validation,
        )

    def record_review_bundle(
        self,
        *,
        subject: LearningItemReviewSubject,
        reports: tuple[LearningItemReviewReportV1, ...],
        bundle_key: str,
        occurred_at: datetime,
    ) -> LearningItemReviewGovernanceResult:
        key = stable_key(bundle_key, label="Learning Item review bundle key")
        self._lock_subject(subject)
        current_state, _current_version = self._current_state(subject.version_id)
        adjudication = adjudicate_learning_item_reviews(subject, reports)
        report_replayed = True
        for report in reports:
            review_key = f"review:{canonical_hash({'bundle_key': key, 'role': report.role.value})}"
            request_hash = canonical_hash(
                {"review_key": review_key, "report": report.model_dump(mode="json")}
            )
            report_id = str(
                learning_item_uuid(
                    "review",
                    f"{subject.version_id}:{report.role.value}:{report.policy_version}",
                )
            )
            stored = self._conn.execute(
                """SELECT report_hash FROM tutor_learning_item_review_reports
                   WHERE version_id=%s AND role=%s AND policy_version=%s""",
                (subject.version_id, report.role.value, report.policy_version),
            ).fetchone()
            if stored is not None:
                if str(stored["report_hash"]) != report.report_hash:
                    raise LearningItemGovernanceConflict(
                        "Learning Item review role already has different evidence"
                    )
                continue
            if current_state != "machine_verified":
                raise LearningItemGovernanceConflict(
                    "New Learning Item review evidence requires machine-verified state"
                )
            inserted = self._conn.execute(
                """
                INSERT INTO tutor_learning_item_review_reports (
                  id,version_id,item_handle,content_hash,role,reviewer_identity,
                  review_key,request_hash,review_input_hash,schema_version,policy_version,
                  verdict,highest_severity,blocker_count,blocker_kinds_json,findings_json,
                  report_hash,created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
                ON CONFLICT (version_id,role,policy_version) DO NOTHING RETURNING id
                """,
                (
                    report_id,
                    subject.version_id,
                    report.item_handle,
                    report.content_hash,
                    report.role.value,
                    report.reviewer_identity,
                    review_key,
                    request_hash,
                    report.review_input_hash,
                    report.schema_version,
                    report.policy_version,
                    report.verdict.value,
                    report.highest_severity.value,
                    sum(1 for item in report.findings if item.blocking),
                    canonical_json([item.value for item in report.blocker_kinds]),
                    canonical_json([item.model_dump(mode="json") for item in report.findings]),
                    report.report_hash,
                    occurred_at,
                ),
            ).fetchone()
            if inserted is not None:
                report_replayed = False
                continue
            stored = self._conn.execute(
                """SELECT report_hash FROM tutor_learning_item_review_reports
                   WHERE version_id=%s AND role=%s AND policy_version=%s""",
                (subject.version_id, report.role.value, report.policy_version),
            ).fetchone()
            if stored is None or str(stored["report_hash"]) != report.report_hash:
                raise LearningItemGovernanceConflict("Learning Item review role already has different evidence")

        adjudication_key = f"adjudication:{canonical_hash({'bundle_key': key})}"
        request_hash = canonical_hash(
            {
                "adjudication_key": adjudication_key,
                "adjudication": adjudication.model_dump(mode="json"),
            }
        )
        adjudication_id = str(
            learning_item_uuid(
                "adjudication",
                f"{subject.version_id}:{LEARNING_ITEM_REVIEW_POLICY_VERSION}",
            )
        )
        stored_adjudication = self._conn.execute(
            """SELECT id,adjudication_hash FROM tutor_learning_item_review_adjudications
               WHERE version_id=%s AND policy_version=%s""",
            (subject.version_id, adjudication.policy_version),
        ).fetchone()
        if stored_adjudication is not None:
            if str(stored_adjudication["adjudication_hash"]) != adjudication.adjudication_hash:
                raise LearningItemGovernanceConflict(
                    "Learning Item adjudication conflicts with stored evidence"
                )
            adjudication_id = str(stored_adjudication["id"])
            inserted = None
        else:
            if current_state != "machine_verified":
                raise LearningItemGovernanceConflict(
                    "New Learning Item adjudication requires machine-verified state"
                )
            inserted = self._conn.execute(
            """
            INSERT INTO tutor_learning_item_review_adjudications (
              id,version_id,item_handle,content_hash,adjudication_key,request_hash,
              schema_version,policy_version,risk_tier,required_roles_json,report_hashes_json,
              verdict,highest_severity,blocker_kinds_json,machine_execution_verified,
              adjudication_hash,created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s::jsonb,%s,%s,%s)
            ON CONFLICT (version_id,policy_version) DO NOTHING RETURNING id
            """,
            (
                adjudication_id,
                subject.version_id,
                adjudication.item_handle,
                adjudication.content_hash,
                adjudication_key,
                request_hash,
                adjudication.schema_version,
                adjudication.policy_version,
                adjudication.risk_tier.value,
                canonical_json([item.value for item in adjudication.required_roles]),
                canonical_json(
                    {role.value: value for role, value in adjudication.report_hashes.items()}
                ),
                adjudication.verdict,
                adjudication.highest_severity.value,
                canonical_json([item.value for item in adjudication.blocker_kinds]),
                adjudication.machine_execution_verified,
                adjudication.adjudication_hash,
                occurred_at,
            ),
            ).fetchone()
        replayed = report_replayed and inserted is None
        if inserted is None:
            stored = self._conn.execute(
                """SELECT id,adjudication_hash FROM tutor_learning_item_review_adjudications
                   WHERE version_id=%s AND policy_version=%s""",
                (subject.version_id, adjudication.policy_version),
            ).fetchone()
            if stored is None or str(stored["adjudication_hash"]) != adjudication.adjudication_hash:
                raise LearningItemGovernanceConflict("Learning Item adjudication conflicts with stored evidence")
            adjudication_id = str(stored["id"])

        publication = None
        if adjudication.verdict == "approved":
            transition_key = f"reviewed:{adjudication.adjudication_hash[:64]}"
            publication = self._items.append_publication_state(
                handle=subject.item_handle,
                expected_state_version=1,
                next_state="agent_reviewed",
                transition_key=transition_key,
                authority_kind="agent_review",
                authority_hash=adjudication.adjudication_hash,
                authority_reference_id=adjudication_id,
                policy_version=adjudication.policy_version,
                occurred_at=occurred_at,
            )
            replayed = replayed and publication.replayed
        return LearningItemReviewGovernanceResult(
            adjudication_id=adjudication_id,
            adjudication=adjudication,
            publication=publication,
            replayed=replayed,
        )

    def start_pilot(
        self,
        *,
        handle: str,
        transition_key: str,
        occurred_at: datetime,
    ) -> LearningItemPublicationResult:
        item_handle = _handle(handle)
        self._deny_native(item_handle)
        key = stable_key(transition_key, label="Learning Item pilot transition key")
        row = self._conn.execute(
            """SELECT id,adjudication_hash FROM tutor_learning_item_review_adjudications
               WHERE version_id=(SELECT id FROM tutor_learning_item_versions WHERE handle=%s)
                 AND policy_version=%s AND verdict='approved'""",
            (item_handle, LEARNING_ITEM_REVIEW_POLICY_VERSION),
        ).fetchone()
        if row is None:
            raise LearningItemGovernanceConflict("Learning Item pilot requires approved adjudication")
        return self._items.append_publication_state(
            handle=item_handle,
            expected_state_version=2,
            next_state="pilot",
            transition_key=key,
            authority_kind="agent_review",
            authority_hash=str(row["adjudication_hash"]),
            authority_reference_id=str(row["id"]),
            policy_version=LEARNING_ITEM_REVIEW_POLICY_VERSION,
            occurred_at=occurred_at,
        )

    def record_pilot_telemetry(
        self,
        *,
        handle: str,
        telemetry: LearningItemPilotTelemetryV1,
        expected_pilot_sequence: int,
        telemetry_key: str,
        occurred_at: datetime,
    ) -> LearningItemPilotGovernanceResult:
        item_handle = _handle(handle)
        key = stable_key(telemetry_key, label="Learning Item pilot telemetry key")
        if expected_pilot_sequence < 0:
            raise ValueError("expected Learning Item pilot sequence cannot be negative")
        version = self._version_row(item_handle, for_update=True)
        if telemetry.item_handle != item_handle or telemetry.content_hash != str(version["content_hash"]):
            raise LearningItemGovernanceConflict("Learning Item pilot telemetry is stale")
        receipt = evaluate_pilot(
            risk_tier=telemetry_risk(version),
            telemetry=telemetry,
        )
        request_hash = canonical_hash(
            {
                "telemetry_key": key,
                "expected_pilot_sequence": expected_pilot_sequence,
                "receipt": receipt.model_dump(mode="json"),
            }
        )
        replay = self._conn.execute(
            """SELECT * FROM tutor_learning_item_pilot_receipts
               WHERE version_id=%s AND telemetry_key=%s""",
            (version["id"], key),
        ).fetchone()
        if replay is not None:
            if str(replay["request_hash"]) != request_hash:
                raise LearningItemGovernanceConflict("Learning Item pilot telemetry key conflicts")
            return LearningItemPilotGovernanceResult(
                receipt_id=str(replay["id"]),
                pilot_sequence=_int(replay["pilot_sequence"]),
                receipt=_pilot_receipt(replay),
                publication=self._publication_by_authority(str(replay["id"])),
                replayed=True,
            )

        current_state, current_state_version = self._current_state(str(version["id"]))
        if current_state != "pilot" or current_state_version != 3:
            raise LearningItemGovernanceConflict(
                "Learning Item pilot telemetry requires current pilot state"
            )
        current = self._conn.execute(
            """SELECT id,pilot_sequence FROM tutor_learning_item_pilot_receipts
               WHERE version_id=%s ORDER BY pilot_sequence DESC LIMIT 1 FOR UPDATE""",
            (version["id"],),
        ).fetchone()
        current_sequence = _int(current["pilot_sequence"]) if current is not None else 0
        if current_sequence != expected_pilot_sequence:
            raise LearningItemGovernanceConflict("Learning Item pilot sequence is stale")
        pilot_sequence = current_sequence + 1
        receipt_id = str(
            learning_item_uuid(
                "pilot",
                f"{version['id']}:{pilot_sequence}:{receipt.receipt_hash}",
            )
        )
        self._conn.execute(
            """
            INSERT INTO tutor_learning_item_pilot_receipts (
              id,version_id,item_handle,content_hash,predecessor_receipt_id,pilot_sequence,
              telemetry_key,request_hash,schema_version,policy_version,risk_tier,
              observation_window_hash,sample_count,completed_count,ambiguity_count,
              rubric_mismatch_count,technical_failure_count,difficulty_mismatch_count,
              unexpected_outcome_count,security_incident_count,leakage_incident_count,
              cohort_complete,decision,telemetry_hash,receipt_hash,occurred_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                receipt_id,
                version["id"],
                item_handle,
                version["content_hash"],
                current["id"] if current is not None else None,
                pilot_sequence,
                key,
                request_hash,
                receipt.schema_version,
                receipt.policy_version,
                receipt.risk_tier.value,
                telemetry.observation_window_hash,
                telemetry.sample_count,
                telemetry.completed_count,
                telemetry.ambiguity_count,
                telemetry.rubric_mismatch_count,
                telemetry.technical_failure_count,
                telemetry.difficulty_mismatch_count,
                telemetry.unexpected_outcome_count,
                telemetry.security_incident_count,
                telemetry.leakage_incident_count,
                telemetry.cohort_complete,
                receipt.decision.value,
                telemetry.telemetry_hash,
                receipt.receipt_hash,
                occurred_at,
            ),
        )
        publication = self._apply_pilot_decision(
            version=version,
            receipt_id=receipt_id,
            receipt=receipt,
            occurred_at=occurred_at,
        )
        return LearningItemPilotGovernanceResult(
            receipt_id=receipt_id,
            pilot_sequence=pilot_sequence,
            receipt=receipt,
            publication=publication,
            replayed=False,
        )

    def approve_high_risk(
        self,
        *,
        handle: str,
        approver_identity: str,
        approval_key: str,
        occurred_at: datetime,
        approval_code: str = "approved",
    ) -> LearningItemHumanApprovalResult:
        item_handle = _handle(handle)
        approver = stable_key(approver_identity, label="Learning Item human approver")
        key = stable_key(approval_key, label="Learning Item human approval key")
        code = stable_key(approval_code, label="Learning Item human approval code")
        version = self._version_row(item_handle, for_update=True)
        existing = self._conn.execute(
            """SELECT approvals.*,pilots.receipt_hash AS pilot_receipt_hash
               FROM tutor_learning_item_human_approvals AS approvals
               JOIN tutor_learning_item_pilot_receipts AS pilots ON pilots.id=approvals.pilot_receipt_id
               WHERE approvals.version_id=%s AND approvals.approval_key=%s""",
            (version["id"], key),
        ).fetchone()
        if existing is not None:
            approval = _human_approval(existing)
            request_hash = canonical_hash(
                {"approval_key": key, "approval": approval.model_dump(mode="json")}
            )
            if (
                str(existing["request_hash"]) != request_hash
                or approval.approver_identity != approver
                or approval.approval_code != code
            ):
                raise LearningItemGovernanceConflict("Learning Item human approval key conflicts")
            publication = self._publication_by_authority(str(existing["id"]))
            if publication is None:
                raise LearningItemGovernanceConflict("Learning Item human approval lacks publication")
            return LearningItemHumanApprovalResult(
                approval_id=str(existing["id"]),
                approval=approval,
                publication=publication,
                replayed=True,
            )

        current_state, current_state_version = self._current_state(str(version["id"]))
        if current_state != "pilot" or current_state_version != 3:
            raise LearningItemGovernanceConflict(
                "High-risk Learning Item is not in current pilot state"
            )
        pilot = self._conn.execute(
            """SELECT * FROM tutor_learning_item_pilot_receipts
               WHERE version_id=%s ORDER BY pilot_sequence DESC LIMIT 1 FOR UPDATE""",
            (version["id"],),
        ).fetchone()
        if pilot is None or str(pilot["decision"]) != LearningItemPilotDecision.AWAITING_HUMAN_APPROVAL.value:
            raise LearningItemGovernanceConflict("High-risk Learning Item is not awaiting human approval")
        approval = LearningItemHumanApprovalV1(
            item_handle=item_handle,
            content_hash=str(version["content_hash"]),
            pilot_receipt_hash=str(pilot["receipt_hash"]),
            approver_identity=approver,
            approval_code=code,
        )
        request_hash = canonical_hash(
            {"approval_key": key, "approval": approval.model_dump(mode="json")}
        )
        approval_id = str(
            learning_item_uuid(
                "approval",
                f"{version['id']}:{LEARNING_ITEM_HUMAN_APPROVAL_POLICY_VERSION}",
            )
        )
        self._conn.execute(
            """
            INSERT INTO tutor_learning_item_human_approvals (
              id,version_id,item_handle,content_hash,pilot_receipt_id,approval_key,
              request_hash,schema_version,policy_version,approver_identity,approval_code,
              approved,approval_hash,approved_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s)
            """,
            (
                approval_id,
                version["id"],
                item_handle,
                version["content_hash"],
                pilot["id"],
                key,
                request_hash,
                approval.schema_version,
                approval.policy_version,
                approval.approver_identity,
                approval.approval_code,
                approval.approval_hash,
                occurred_at,
            ),
        )
        subject = self.load_review_subject(handle=item_handle)
        self._materialize_practice_authority(subject, occurred_at=occurred_at)
        publication = self._items.append_publication_state(
            handle=item_handle,
            expected_state_version=3,
            next_state="published",
            transition_key=f"human-publish:{approval.approval_hash[:64]}",
            authority_kind="human_approval",
            authority_hash=approval.approval_hash,
            authority_reference_id=approval_id,
            policy_version=approval.policy_version,
            occurred_at=occurred_at,
        )
        return LearningItemHumanApprovalResult(
            approval_id=approval_id,
            approval=approval,
            publication=publication,
            replayed=False,
        )

    def _apply_pilot_decision(
        self,
        *,
        version: Mapping[str, object],
        receipt_id: str,
        receipt: LearningItemPilotReceiptV1,
        occurred_at: datetime,
    ) -> LearningItemPublicationResult | None:
        if receipt.decision in {
            LearningItemPilotDecision.COLLECTING,
            LearningItemPilotDecision.AWAITING_HUMAN_APPROVAL,
        }:
            return None
        item_handle = str(version["handle"])
        if receipt.decision is LearningItemPilotDecision.PROMOTE:
            subject = self.load_review_subject(handle=item_handle)
            self._materialize_practice_authority(subject, occurred_at=occurred_at)
            state = "published"
            reason = None
        elif receipt.decision is LearningItemPilotDecision.QUARANTINE:
            state = "quarantined"
            reason = "pilot.anomaly"
        else:
            state = "retired"
            reason = "pilot.safety"
        return self._items.append_publication_state(
            handle=item_handle,
            expected_state_version=3,
            next_state=state,  # type: ignore[arg-type]
            transition_key=f"pilot-{state}:{receipt.receipt_hash[:64]}",
            authority_kind="pilot",
            authority_hash=receipt.receipt_hash,
            authority_reference_id=receipt_id,
            policy_version=receipt.policy_version,
            reason_code=reason,
            occurred_at=occurred_at,
        )

    def _materialize_practice_authority(
        self,
        subject: LearningItemReviewSubject,
        *,
        occurred_at: datetime,
    ) -> LearningItemPracticeMaterializationResult | None:
        self._deny_native(subject.item_handle)
        material = build_exercise_authority(subject.source)
        if material is None:
            return None
        require_exercise_quality(
            material.exercise,
            material.rubric,
            model_review_validation=material.model_review_validation,
        )
        exercise_version_id = PostgresExerciseGateRepository(
            self._conn
        ).ensure_exercise_authority(
            material.exercise,
            material.rubric,
            now=occurred_at,
        )
        receipt_hash = canonical_hash(
            {
                "adapter_version": LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
                "learning_item_version_id": subject.version_id,
                "learning_item_handle": subject.item_handle,
                "learning_item_content_hash": subject.source.content_hash,
                "exercise_version_id": exercise_version_id,
                "exercise_content_hash": material.exercise.content_hash,
                "rubric_hash": material.rubric.rubric_hash,
            }
        )
        materialization_id = str(
            learning_item_uuid("materialization", f"{subject.version_id}:{receipt_hash}")
        )
        inserted = self._conn.execute(
            """
            INSERT INTO tutor_learning_item_practice_materializations (
              id,version_id,item_handle,content_hash,exercise_version_id,exercise_key,
              exercise_version,exercise_content_hash,rubric_hash,adapter_version,
              receipt_hash,materialized_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (version_id) DO NOTHING RETURNING id
            """,
            (
                materialization_id,
                subject.version_id,
                subject.item_handle,
                subject.source.content_hash,
                exercise_version_id,
                material.exercise.exercise_key,
                material.exercise.version,
                material.exercise.content_hash,
                material.rubric.rubric_hash,
                LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
                receipt_hash,
                occurred_at,
            ),
        ).fetchone()
        if inserted is None:
            stored = self._conn.execute(
                """SELECT id,exercise_version_id,receipt_hash
                   FROM tutor_learning_item_practice_materializations WHERE version_id=%s""",
                (subject.version_id,),
            ).fetchone()
            if stored is None or str(stored["receipt_hash"]) != receipt_hash:
                raise LearningItemGovernanceConflict("Learning Item Practice materialization conflicts")
            return LearningItemPracticeMaterializationResult(
                materialization_id=str(stored["id"]),
                exercise_version_id=str(stored["exercise_version_id"]),
                receipt_hash=receipt_hash,
                replayed=True,
            )
        return LearningItemPracticeMaterializationResult(
            materialization_id=materialization_id,
            exercise_version_id=exercise_version_id,
            receipt_hash=receipt_hash,
            replayed=False,
        )

    def _lock_subject(
        self,
        subject: LearningItemReviewSubject,
        *,
        expected_state: str | None = None,
    ) -> Mapping[str, object]:
        self._deny_native(subject.item_handle)
        row = self._conn.execute(
            """SELECT id,handle,content_hash,creator_identity FROM tutor_learning_item_versions
               WHERE id=%s FOR UPDATE""",
            (subject.version_id,),
        ).fetchone()
        if (
            row is None
            or str(row["handle"]) != subject.item_handle
            or str(row["content_hash"]) != subject.source.content_hash
            or str(row["creator_identity"]) != subject.creator_identity
        ):
            raise LearningItemGovernanceConflict("Learning Item review subject changed")
        if expected_state is not None:
            current = self._current_state(subject.version_id)
            if current[0] != expected_state:
                raise LearningItemGovernanceConflict("Learning Item publication state is stale")
        return row

    def _version_row(self, handle: str, *, for_update: bool) -> Mapping[str, object]:
        self._deny_native(handle)
        lock = " FOR UPDATE" if for_update else ""
        row = self._conn.execute(
            """SELECT id,handle,content_hash,risk_tier,item_kind,item_key,version
               FROM tutor_learning_item_versions WHERE handle=%s""" + lock,
            (handle,),
        ).fetchone()
        if row is None:
            raise LearningItemGovernanceError("Learning Item version was not found")
        return row

    def _current_state(self, version_id: str) -> tuple[str, int]:
        row = self._conn.execute(
            """SELECT state,state_version FROM tutor_learning_item_publication_events
               WHERE version_id=%s ORDER BY state_version DESC LIMIT 1""",
            (version_id,),
        ).fetchone()
        if row is None:
            raise LearningItemGovernanceConflict("Learning Item publication state is missing")
        return str(row["state"]), _int(row["state_version"])

    def _publication_by_authority(
        self,
        authority_reference_id: str,
    ) -> LearningItemPublicationResult | None:
        row = self._conn.execute(
            """SELECT version_id,id,item_handle,state,state_version
               FROM tutor_learning_item_publication_events
               WHERE authority_reference_id=%s ORDER BY state_version DESC LIMIT 1""",
            (authority_reference_id,),
        ).fetchone()
        if row is None:
            return None
        return LearningItemPublicationResult(
            version_id=str(row["version_id"]),
            event_id=str(row["id"]),
            handle=str(row["item_handle"]),
            state=str(row["state"]),  # type: ignore[arg-type]
            state_version=_int(row["state_version"]),
            replayed=True,
        )


def _handle(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _HANDLE.fullmatch(normalized):
        raise ValueError("Learning Item handle is invalid")
    return normalized


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise LearningItemGovernanceConflict("Stored Learning Item JSON is invalid")
    return dict(value)


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise LearningItemGovernanceConflict("Stored Learning Item integer is invalid")
    return int(value)


def telemetry_risk(row: Mapping[str, object]):  # type: ignore[no-untyped-def]
    from app.services.learning.item_bank.contracts import LearningItemRiskTier

    return LearningItemRiskTier(str(row["risk_tier"]))


def _pilot_receipt(row: Mapping[str, object]) -> LearningItemPilotReceiptV1:
    return LearningItemPilotReceiptV1(
        risk_tier=str(row["risk_tier"]),  # type: ignore[arg-type]
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=str(row["item_handle"]),
            content_hash=str(row["content_hash"]),
            observation_window_hash=str(row["observation_window_hash"]),
            sample_count=_int(row["sample_count"]),
            completed_count=_int(row["completed_count"]),
            ambiguity_count=_int(row["ambiguity_count"]),
            rubric_mismatch_count=_int(row["rubric_mismatch_count"]),
            technical_failure_count=_int(row["technical_failure_count"]),
            difficulty_mismatch_count=_int(row["difficulty_mismatch_count"]),
            unexpected_outcome_count=_int(row["unexpected_outcome_count"]),
            security_incident_count=_int(row["security_incident_count"]),
            leakage_incident_count=_int(row["leakage_incident_count"]),
            cohort_complete=bool(row["cohort_complete"]),
        ),
        decision=str(row["decision"]),  # type: ignore[arg-type]
    )


def _human_approval(row: Mapping[str, object]) -> LearningItemHumanApprovalV1:
    return LearningItemHumanApprovalV1(
        item_handle=str(row["item_handle"]),
        content_hash=str(row["content_hash"]),
        pilot_receipt_hash=str(row["pilot_receipt_hash"]),
        approver_identity=str(row["approver_identity"]),
        approval_code=str(row["approval_code"]),
    )


__all__ = (
    "LearningItemGovernanceConflict",
    "LearningItemGovernanceError",
    "LearningItemHumanApprovalResult",
    "LearningItemPilotGovernanceResult",
    "LearningItemPracticeMaterializationResult",
    "LearningItemReviewGovernanceResult",
    "PostgresLearningItemGovernanceRepository",
)
