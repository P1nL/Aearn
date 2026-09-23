"""Immutable, predecessor-linked repair projections; never activates a plan."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from psycopg import Connection
from pydantic import Field

from app.services.grounding.retrieval_contracts import stable_hash
from app.services.grounding.subject_contracts import SubjectAssessment
from app.services.learning.contracts import LearningPlan
from app.services.learning.plan_coverage import (
    LEGACY_ECOSYSTEM_BINDINGS, POLICY_VERSION, NodeSourceRequirement, PlanCoveragePreflightService,
    PlanPreflightConflict, PlanPreflightReport, RepairAction, _Frozen, required_node_keys,
)
from app.services.learning.track_repository import LearningPlanActivationInvalid, _plan_from_row


class NodeRepairDiff(_Frozen):
    knowledge_key: str
    action: RepairAction
    before_subject_id: str
    before_subject_version: str
    after_subject_id: str | None
    after_subject_version: str | None
    target_handle: str | None
    reason_codes: tuple[str, ...]
    missing_facets: tuple[str, ...]
    missing_capabilities: tuple[SubjectAssessment, ...]
    before_required_assessments: tuple[SubjectAssessment, ...]
    after_required_assessments: tuple[SubjectAssessment, ...] | None
    source_generation: int
    source_summary_hash: str | None
    capability_hash: str


class PlanRepairProposal(_Frozen):
    """Non-persisted, unconfirmed; no successor revision id exists yet."""

    track_id: str | None
    predecessor_revision_id: str | None
    predecessor_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["blocked", "awaiting_confirmation"]
    activation_allowed: Literal[False] = False
    node_diffs: tuple[NodeRepairDiff, ...]
    preflight_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlanRepairProposalBuilder:
    """Only registry-verified input facts; no provider-selected targets."""

    def build(self, plan: LearningPlan, report: PlanPreflightReport, *,
              track_id: str | None = None,
              predecessor_revision_id: str | None = None) -> PlanRepairProposal:
        if (report.plan_hash != plan.content_hash or report.policy_version != POLICY_VERSION
                or {node.knowledge_key for node in report.nodes} != {node.knowledge_key for node in plan.nodes}
                or len(report.nodes) != len(plan.nodes)):
            raise PlanPreflightConflict("preflight does not match exact plan")
        # Defensive against model_copy(update=...) and internally injected readers:
        # a caller cannot turn a blocked report into an actionable one by flipping flags.
        if report.report_hash != stable_hash(report.model_dump(mode="json", exclude={"report_hash"})):
            raise PlanPreflightConflict("preflight report hash changed")
        actual_blocked = any(node.required_for_activation and node.status != "supported"
                             for node in report.nodes)
        actual_status = ("unavailable" if any(node.status == "unavailable" for node in report.nodes)
                         else "insufficient" if any(node.status == "insufficient" for node in report.nodes)
                         else "partial" if any(node.status == "partial" for node in report.nodes)
                         else "supported")
        if report.activation_blocked != actual_blocked or report.status != actual_status:
            raise PlanPreflightConflict("preflight status changed")
        depended_on = {key for node in plan.nodes for key in node.prerequisite_keys}
        required_keys = required_node_keys(plan)
        module_for_node = {node.knowledge_key: module.module_key
                           for module in plan.modules for node in module.nodes}
        remaining_by_module = {module.module_key: len(module.nodes) for module in plan.modules}
        diffs: list[NodeRepairDiff] = []
        deletions_remaining = len(plan.nodes) - 1
        for node, result in zip(plan.nodes, report.nodes, strict=True):
            if (node.knowledge_key != result.knowledge_key
                    or node.is_core != result.is_core
                    or (node.knowledge_key in required_keys) != result.required_for_activation):
                raise PlanPreflightConflict("preflight node order changed")
            if (set(result.missing_capabilities) - set(result.required_capabilities)
                    or (result.required_for_activation and result.allowed_actions != (("wait_for_release",)
                        if result.status != "supported" else ()))
                    or (result.status == "supported" and (
                        result.corpus_status != "satisfied" or result.missing_facets
                        or result.missing_capabilities or result.allowed_actions
                        or "PUBLIC_RELEASE_UNAVAILABLE" in result.reason_codes
                        or "SYNTHETIC_FIXTURE_ONLY" in result.reason_codes))):
                raise PlanPreflightConflict("preflight node facts contradict status")
            if result.status == "supported":
                continue
            if result.required_for_activation:
                action: RepairAction = "wait_for_release"
                target_handle = None
                target_subject_id = result.subject_id
                target_version = result.subject_version
            elif ("downgrade_assessment" in result.allowed_actions
                  and "lesson" in result.required_capabilities
                  and "lesson" not in result.missing_capabilities
                  and result.missing_capabilities
                  and "PUBLIC_RELEASE_UNAVAILABLE" not in result.reason_codes
                  and "SYNTHETIC_FIXTURE_ONLY" not in result.reason_codes
                  and result.corpus_status == "satisfied"
                  and not result.missing_facets):
                action = "downgrade_assessment"
                target_handle = "lesson"
                target_subject_id = result.subject_id
                target_version = result.subject_version
            elif ("delete_optional_node" in result.allowed_actions
                  and node.knowledge_key not in depended_on and deletions_remaining > 0
                  and remaining_by_module[module_for_node[node.knowledge_key]] > 1):
                deletions_remaining -= 1
                remaining_by_module[module_for_node[node.knowledge_key]] -= 1
                action = "delete_optional_node"
                target_handle = None
                target_subject_id = None
                target_version = None
            else:
                action = "defer_subject"
                target_handle = None
                target_subject_id = result.subject_id
                target_version = result.subject_version
            if action not in result.allowed_actions:
                raise PlanPreflightConflict("repair action not authorized by preflight")
            after_assessments = (None if action == "delete_optional_node" else
                                 ("lesson",) if action == "downgrade_assessment" else
                                 result.required_capabilities)
            diffs.append(NodeRepairDiff(
                knowledge_key=node.knowledge_key, action=action,
                before_subject_id=result.subject_id, before_subject_version=result.subject_version,
                after_subject_id=target_subject_id, after_subject_version=target_version,
                target_handle=target_handle, reason_codes=result.reason_codes,
                missing_facets=result.missing_facets,
                missing_capabilities=result.missing_capabilities,
                before_required_assessments=result.required_capabilities,
                after_required_assessments=after_assessments,
                source_generation=result.source_generation,
                source_summary_hash=result.source_summary_hash,
                capability_hash=result.capability_hash,
            ))
        payload: dict[str, object] = {
            "track_id": track_id, "predecessor_revision_id": predecessor_revision_id,
            "predecessor_plan_hash": plan.content_hash,
            "state": "blocked" if report.activation_blocked else "awaiting_confirmation",
            "activation_allowed": False,
            "node_diffs": tuple(diffs),
            "preflight_report_hash": report.report_hash, "policy_version": POLICY_VERSION,
        }
        hash_payload = {**payload, "node_diffs": tuple(diff.model_dump(mode="json") for diff in diffs)}
        return PlanRepairProposal.model_validate({**payload, "proposal_hash": stable_hash(hash_payload)})


class ExistingTrackMigrationPlanner:
    """Selects the immutable active revision; no repository mutation methods."""

    def __init__(self, conn: Connection[dict[str, object]],
                 preflight: PlanCoveragePreflightService) -> None:
        self._conn = conn
        self._preflight = preflight
        self._builder = PlanRepairProposalBuilder()

    def propose(self, *, user_id: str, track_id: str, expected_revision_id: str,
                expected_plan_hash: str,
                requirements: tuple[NodeSourceRequirement, ...]) -> PlanRepairProposal:
        # No FOR UPDATE: usable inside PostgreSQL read-only, repeatable-read transactions.
        row = self._conn.execute(
            """SELECT revisions.* FROM tutor_track_active_plans AS active
               JOIN tutor_track_plan_revisions AS revisions
                 ON (revisions.id,revisions.track_id,revisions.user_id) =
                    (active.revision_id,active.track_id,active.user_id)
               WHERE active.track_id=%s AND active.user_id=%s""",
            (str(UUID(track_id)), str(UUID(user_id))),
        ).fetchone()
        if row is None:
            raise LearningPlanActivationInvalid("active learning plan is missing")
        if str(row["id"]) != str(UUID(expected_revision_id)) or row["content_hash"] != expected_plan_hash:
            raise PlanPreflightConflict("active plan revision changed")
        plan = _plan_from_row(row)
        if plan.content_hash != expected_plan_hash:
            raise PlanPreflightConflict("stored plan hash changed")
        # A legacy core ecosystem goal cannot be caller-rebound to its base language.
        for requirement in requirements:
            binding = LEGACY_ECOSYSTEM_BINDINGS.get(requirement.knowledge_key)
            if binding is not None and (requirement.subject_id, requirement.required_facets) != binding:
                raise PlanPreflightConflict("legacy ecosystem mapping changed")
        report = self._preflight.evaluate(
            plan, requirements, expected_plan_hash=expected_plan_hash,
        )
        return self._builder.build(
            plan, report, track_id=str(UUID(track_id)),
            predecessor_revision_id=str(UUID(expected_revision_id)),
        )
