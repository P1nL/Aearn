"""Same-connection KC teaching selection -> original actual-D preparation only.

compose_kc_teaching binds the existing C/source/budget owners to the exact KC
draft. PUBLIC assessment authority, qualification alone and booleans cannot
substitute for current teaching consumption.
No connections, files, keys, models, signatures, confirmation or mapping here.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection

from app.services.grounding.assessment_course_selection import AssessmentCourseSelectionProducer
from app.services.grounding.autonomous.assessment_receipt_repository import (
    AssessmentReceiptRepository, PostgresAssessmentConsumeAuthority,
)
from app.services.grounding.autonomous.access_policy import AccessRequest, AuthoritySnapshot, AutonomousGates
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, RagBudgetDelegation, SubjectScope
from app.services.grounding.autonomous.corpus_governance import CorpusGovernance, PostgresCorpusAuthority, PostgresQualificationAuthority
from app.services.grounding.autonomous.public_python_teaching_review import PublicPythonTeachingVerifier
from app.services.grounding.autonomous.source_assessment import assess_document
from app.services.grounding.autonomous.source_assessment_profiles import PreparedActualDSourceAssessment, SourceAssessmentDenied
from app.services.grounding.current_authorization import CurrentAuthorization, EvidenceDenied
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_binding_repository import (
    MaterialBindingConflict, MaterialBindingStale, PostgresMaterialBindingRepository,
    _authorize, _plan_nodes, _scope_from_draft, goal_hash_for_node,
)
from app.services.grounding.material_contracts_v2 import DraftScope, MaterialSelectionResult, NodeMaterialRequirement, digest
from app.services.learning.item_supply.finite_course_mapping import finite_node_description
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.material_planning_composition import _BoundMaterialAuthority
from app.services.learning.material_selection import PostgresMaterialPlanningConsumer
from app.services.learning.plan_drafting import draft_artifact_from_row

TARGET: Literal["python-kc-binding-v1"] = "python-kc-binding-v1"
TARGET_NODE = "python.bind"
REFRESHER_NODE = "python.basics"
POLICY = "actual-d-kc-teaching-requirements-20261007-v1"


class PreparationPending(ValueError):
    """Fixed local reason only; never captures SQL/source/provider text."""


@dataclass(frozen=True)
class KcActualDPreparation:
    status: Literal["disabled", "pending", "prepared"]
    reason: str
    selection: MaterialSelectionResult | None = field(default=None, repr=False)
    prepared: PreparedActualDSourceAssessment | None = field(default=None, repr=False)
    producer: AssessmentCourseSelectionProducer | None = field(default=None, repr=False)

    def safe_report(self) -> dict[str, object]:
        return {"status": self.status, "reason": self.reason,
            "selection_handle": None if self.selection is None else self.selection.handle,
            "node_count": 0 if self.selection is None else len(self.selection.requirements),
            "prepared_only": self.prepared is not None, "source_oracle_executed": False,
            "signed_proof_persisted": False, "confirmed": False, "mapping_created": False,
            "teaching_evidence_boundary": "current_main_teaching_facets_only_not_all_KC_clause_proof"}


class KcTeachingRequirements:
    """Closed server mapping from immutable goals, NOT source/use authorization."""

    def resolve(self, draft: DraftScope, profile: Mapping[str, object],
                nodes: Mapping[str, Mapping[str, object]]) -> tuple[NodeMaterialRequirement, ...]:
        target = get_finite_course_target(TARGET)
        if profile.get("language_id") != target.language_id or set(nodes) != {TARGET_NODE, REFRESHER_NODE}:
            raise PreparationPending("EXACT_KC_WHOLE_DRAFT_REQUIRED")
        core, refresher = nodes[TARGET_NODE], nodes[REFRESHER_NODE]
        if (core.get("description") != finite_node_description(TARGET)
                or core.get("required_capabilities") != list(target.required_capabilities)
                or core.get("is_core") is not True or core.get("prerequisite_keys") != []
                or refresher.get("is_core") is not False or refresher.get("prerequisite_keys") != []
                or refresher.get("required_capabilities") != ["python"]
                or refresher.get("description") != "Already-known names and integer literals."):
            raise PreparationPending("EXACT_KC_OR_REFRESHER_GOAL_REQUIRED")
        requirements = []
        for node_id, node in nodes.items():
            goal = goal_hash_for_node(node)
            # Both exact, distinct goals fall under the registered fundamentals
            # facet. This policy grants neither current teaching nor KC scoring.
            demand = LearningMaterialDemand(
                scope=SubjectScope(subject_id=target.subject_id, subject_version="1.0", facets=target.required_facets),
                demand_hash=digest({"policy": POLICY, "draft": draft.model_dump(mode="json"),
                    "node_id": node_id, "goal_hash": goal, "purpose": "main_teaching"}),
                plan_ref="draft." + draft.draft_id, node_ref="node." + node_id,
                draft_revision=draft.draft_version, purpose="main_teaching", reading_level="beginner", language="en")
            requirements.append(NodeMaterialRequirement(node_id=node_id, goal_hash=goal,
                prerequisites=(), demand=demand))
        return tuple(requirements)


class KcTeachingConsumptionOwner:
    """Read-only finite adaptation of the original D consumption actor.

    Full demand comes from the exact current DB draft, never request shape. C's
    original production verifier/admission and registered-source budget owner
    establish permission each time. No grant, reservation or policy is issued.
    """

    def __init__(self, conn: Connection[dict[str, Any]], *, draft: DraftScope,
                 governance: CorpusGovernance, verifier: PublicPythonTeachingVerifier) -> None:
        self.conn, self.draft, self.governance, self.verifier = conn, draft, governance, verifier
        self.current = CurrentAuthorization(conn, governance=governance,
            gates=AutonomousGates(evidence_consumer=True), enabled=True)

    def _requirements(self) -> tuple[NodeMaterialRequirement, ...]:
        self.current.require_transaction()
        row = _scope_from_draft(self.conn, self.draft, lock=False)
        if draft_artifact_from_row(row).content_hash != self.draft.content_hash:
            raise PreparationPending("ORIGINAL_DRAFT_HASH_MISMATCH")
        profile = row["profile_json"]
        if not isinstance(profile, Mapping):
            raise PreparationPending("EXACT_KC_WHOLE_DRAFT_REQUIRED")
        return KcTeachingRequirements().resolve(self.draft, profile, _plan_nodes(row))

    def _current_snapshot(self, requirement: NodeMaterialRequirement) -> AuthoritySnapshot:
        if requirement not in self._requirements():
            raise PreparationPending("EXACT_CURRENT_TEACHING_DEMAND_REQUIRED")
        demand = requirement.demand
        pinned = self.verifier.review.payload.prepared  # locator only, not an unverified approval
        snapshot = PostgresQualificationAuthority(self.governance).resolve(demand)
        if snapshot is None or snapshot.synthetic_fixture or snapshot.demand != demand:
            raise PreparationPending("CURRENT_MAIN_TEACHING_CORPUS_REQUIRED")
        matches = [d for d in snapshot.documents if
            d.assessment.source_handle == pinned.source_handle and d.assessment.document_hash == pinned.document_hash
            and d.assessment.scope == demand.scope and d.assessment.reading_level == demand.reading_level
            and demand.purpose in d.assessment.allowed_usages
            and set(demand.scope.facets) <= set(d.covered_facets)]
        if len(matches) != 1:
            raise PreparationPending("EXACT_PINNED_MAIN_TEACHING_DOCUMENT_REQUIRED")
        reviews = self.governance.source_reviews
        assert reviews is not None  # concrete same-connection composition below
        document = matches[0].assessment
        reviewed = reviews.resolve(document.source_handle, document.document_handle)
        if (reviewed is None or reviewed.facts.registered_capture_id != pinned.capture_id
                or (reviewed.facts.policy_id, reviewed.facts.policy_generation, reviewed.facts.root_id)
                != (pinned.policy_id, pinned.policy_generation, pinned.root_id)):
            raise PreparationPending("CURRENT_PINNED_TEACHING_REVIEW_REQUIRED")
        # This calls the original C current reviewer again, including signature,
        # provenance, retained storage grant and purpose; no shape-only approval.
        decision = assess_document(reviewed.facts, resolver=reviews, now=self.current._clock())
        if (not decision.allowed or decision.assessment is None or decision.authorization is None
                or decision.assessment.scope != demand.scope
                or demand.purpose not in decision.assessment.allowed_usages
                or demand.purpose not in decision.authorization.allowed_usages):
            raise PreparationPending("CURRENT_MAIN_TEACHING_USE_DENIED")
        root = self.conn.execute("SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR SHARE",
                                 (pinned.root_id,)).fetchone()
        now = self.current._clock()
        authority = self.governance.authority
        if type(authority) is not PostgresCorpusAuthority:
            raise PreparationPending("CURRENT_ORIGINAL_SOURCE_BUDGET_REQUIRED")
        authority.require_current(self.conn, policy_id=pinned.policy_id,
            generation=pinned.policy_generation, root_id=pinned.root_id,
            subject_id=demand.scope.subject_id, subject_version=demand.scope.subject_version, now=now)
        now = self.current._clock()  # fresh clock after the original owner's lock waits
        if root is None:
            raise PreparationPending("CURRENT_ORIGINAL_SOURCE_BUDGET_REQUIRED")
        active = (root["enabled"] is True and root["period_start"] <= now < root["period_end"]
                  and now < root["delegation_expires_at"])
        if not active:
            raise PreparationPending("CURRENT_ORIGINAL_SOURCE_BUDGET_REQUIRED")
        if (reviewed.grant is None or now >= reviewed.grant.retained_until
                or now >= self.verifier.review.payload.expires_at):
            raise PreparationPending("CURRENT_MAIN_TEACHING_USE_DENIED")
        return AuthoritySnapshot(demand=demand, demand_hash=demand.demand_hash, scope=demand.scope,
            purpose="main_teaching", actor_id="service.rag-d-live", allowed_actions=("consume",),
            policy_id=pinned.policy_id, policy_generation=pinned.policy_generation,
            budget=RagBudgetDelegation(root_id=pinned.root_id, delegation_id=root["delegation_id"],
                generation=root["delegation_generation"], expires_at=root["delegation_expires_at"]),
            budget_active=active, authorized=decision.allowed)

    def request_for(self, requirement: NodeMaterialRequirement) -> AccessRequest:
        snapshot = self._current_snapshot(requirement)
        return AccessRequest(demand_hash=snapshot.demand_hash, scope=snapshot.scope, purpose=snapshot.purpose,
            actor_id=snapshot.actor_id, action="consume", policy_id=snapshot.policy_id,
            policy_generation=snapshot.policy_generation, budget=snapshot.budget)

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot | None:
        try:
            matches = [r for r in self._requirements() if r.demand.demand_hash == request.demand_hash]
            if len(matches) != 1 or request.action != "consume" or request.purpose != "main_teaching":
                return None
            snapshot = self._current_snapshot(matches[0])
            expected = AccessRequest(demand_hash=snapshot.demand_hash, scope=snapshot.scope,
                purpose=snapshot.purpose, actor_id=snapshot.actor_id, action="consume",
                policy_id=snapshot.policy_id, policy_generation=snapshot.policy_generation, budget=snapshot.budget)
            return snapshot if request == expected else None
        except Exception:
            return None  # original A fail-closed resolver contract


def compose_kc_teaching(conn: Connection[dict[str, Any]], *, draft: DraftScope,
                        governance: CorpusGovernance, enabled: bool = False) -> EvidenceSelection:
    """Reuse main's PUBLIC C governance, not its assessment consume authority.

    The current PUBLIC helper exposes this as authority._current.governance.
    Caller still owns the same active transaction; no public/private key IO.
    """
    if not enabled or type(governance) is not CorpusGovernance or governance.conn is not conn:
        raise PreparationPending("PINNED_PRODUCTION_TEACHING_COMPOSITION_REQUIRED")
    reviews = governance.source_reviews
    verifier = None if reviews is None else reviews.teaching_verifier
    if (type(governance.authority) is not PostgresCorpusAuthority
            or reviews is None or reviews.conn is not conn
            or type(verifier) is not PublicPythonTeachingVerifier or verifier.conn is not conn or not verifier.enabled):
        raise PreparationPending("PINNED_PRODUCTION_TEACHING_COMPOSITION_REQUIRED")
    owner = KcTeachingConsumptionOwner(conn, draft=draft, governance=governance, verifier=verifier)
    return EvidenceSelection(conn, governance=governance, request_for=owner.request_for,
        selections=PostgresMaterialBindingRepository(conn), gates=AutonomousGates(evidence_consumer=True),
        authority_resolver=owner, enabled=True)


def _ports(conn: Connection[dict[str, Any]], teaching: EvidenceSelection | None,
           receipts: AssessmentReceiptRepository) -> PublicPythonTeachingVerifier:
    if type(teaching) is not EvidenceSelection:
        raise PreparationPending("TEACHING_CONSUMPTION_OWNER_REQUIRED")
    if (teaching.conn is not conn or teaching.governance.conn is not conn
            or teaching.selections is None or teaching.selections.conn is not conn
            or type(receipts) is not AssessmentReceiptRepository or receipts.conn is not conn):
        raise PreparationPending("SAME_CONNECTION_ORIGINAL_OWNERS_REQUIRED")
    if (type(teaching.authority_resolver) is not KcTeachingConsumptionOwner
            or isinstance(teaching.authority_resolver, PostgresAssessmentConsumeAuthority)):
        raise PreparationPending("TEACHING_CONSUMPTION_OWNER_REQUIRED")
    reviews = teaching.governance.source_reviews
    verifier = None if reviews is None else reviews.teaching_verifier
    if type(verifier) is not PublicPythonTeachingVerifier or verifier.conn is not conn or not verifier.enabled:
        raise PreparationPending("PINNED_CURRENT_TEACHING_VERIFIER_REQUIRED")
    if not receipts.actual_d_private_provenance_enabled:
        raise PreparationPending("EXPLICIT_ACTUAL_D_PRIVATE_PROVENANCE_REQUIRED")
    teaching.require_transaction()
    receipts.require_transaction()  # includes exact B1d DB/read-committed/write-transaction fence
    return verifier


def prepare_kc_actual_d(conn: Connection[dict[str, Any]], *, user_id: UUID, session_id: UUID,
                        draft_id: UUID, receipts: AssessmentReceiptRepository,
                        capture_id: UUID, document_handle: str,
                        teaching: EvidenceSelection | None = None,
                        enabled: bool = False) -> KcActualDPreparation:
    """Caller owns an active short transaction and its eventual commit/rollback.

    Missing teaching actor denies before IO. Successful preparation persists only
    the original whole-draft selection, not proof/bridge/binding. Main must end
    the transaction before running the independent real source oracle.
    """
    if not enabled:
        return KcActualDPreparation("disabled", "GATE_CLOSED")
    try:
        verifier = _ports(conn, teaching, receipts)
        assert teaching is not None  # established by exact concrete type, not authority
        producer = AssessmentCourseSelectionProducer(conn, receipts=receipts,
            teaching_authority=teaching, teaching_verifier=verifier, enabled=True)
        # Savepoint encloses original selection writes and every final fence.
        # Late source/epoch/selection failure cannot leave a half-prepared row.
        with conn.transaction():
            draft, row = producer._load(user_id=user_id, session_id=session_id, draft_id=draft_id)
            artifact = draft_artifact_from_row(row)
            if artifact.content_hash != draft.content_hash:
                raise PreparationPending("ORIGINAL_DRAFT_HASH_MISMATCH")
            modules = artifact.plan.modules
            if (len(modules) != 2 or any(len(m.nodes) != 1 for m in modules)
                    or modules[0].is_core or not modules[0].is_skippable
                    or not modules[1].is_core or modules[1].is_skippable):
                raise PreparationPending("EXACT_TWO_MODULE_KC_PLAN_REQUIRED")
            consumer = PostgresMaterialPlanningConsumer(conn,
                authority=_BoundMaterialAuthority(conn, teaching), requirements=KcTeachingRequirements())
            # Reuses the original canonical ordering, exact current scope,
            # draft idempotency, immutable selection and repository write owner.
            selection = consumer._select(row, draft.conversation_id)
            if (len(selection.requirements) != 2 or any(
                    e.purpose != "main_teaching" or e.status != "ready" or not e.evidence
                    for e in selection.entries)):
                raise PreparationPending("WHOLE_DRAFT_CURRENT_TEACHING_NOT_READY")
            _authorize(teaching.authorize_selection, conn, selection)
            prepared = receipts.prepare_actual_d(capture_id=capture_id, document_handle=document_handle,
                draft=draft, base_selection_handle=selection.handle, node_id=TARGET_NODE, target_id=TARGET)
            if not isinstance(prepared, PreparedActualDSourceAssessment):
                raise PreparationPending("KC_SOURCE_PREPARATION_TYPE_MISMATCH")
            _authorize(teaching.authorize_selection, conn, selection)
        return KcActualDPreparation("prepared", "ORIGINAL_TEACHING_SELECTION_AND_SOURCE_PREPARED",
            selection=selection, prepared=prepared, producer=producer)
    except PreparationPending as exc:
        return KcActualDPreparation("pending", str(exc))
    except MaterialBindingStale:
        return KcActualDPreparation("pending", "ORIGINAL_DRAFT_OR_SELECTION_STALE")
    except MaterialBindingConflict:
        return KcActualDPreparation("pending", "ORIGINAL_SELECTION_AUTHORIZATION_OR_STORAGE_DENIED")
    except EvidenceDenied:
        return KcActualDPreparation("pending", "CURRENT_TEACHING_AUTHORITY_DENIED")
    except SourceAssessmentDenied:
        return KcActualDPreparation("pending", "ORIGINAL_ACTUAL_D_SOURCE_PREPARATION_DENIED")
