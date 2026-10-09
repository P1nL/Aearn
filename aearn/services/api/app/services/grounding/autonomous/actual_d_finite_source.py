"""Exact actual-D finite source scope, read through the original D repository.

This does not create a draft, select materials, confirm a course, or grant source
permission. Public oracle declarations are reused as semantics, never as proofs.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from pydantic import Field, model_validator

from app.services.grounding.material_binding_repository import (
    PostgresMaterialBindingRepository, _check_members, _plan_nodes, _require_transaction, _scope_from_draft, goal_hash_for_node,
)
from app.services.grounding.material_contracts_v2 import DraftScope, digest
from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.plan_drafting import draft_artifact_from_row
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_targets.contracts import TargetId

from .contracts import FrozenContract, HASH, LearningMaterialDemand, revalidate
from .actual_d_lifecycle import current_actual_d_epoch

ActualDProfileId = Literal["python-state-actual-d-source-v1", "python-binding-actual-d-source-v1", "sqlite-predicate-actual-d-source-v1"]
ACTUAL_D_PROFILE_TARGET: dict[str, TargetId] = {
    "python-state-actual-d-source-v1": "python-state-update-v1",
    "python-binding-actual-d-source-v1": "python-kc-binding-v1",
    "sqlite-predicate-actual-d-source-v1": "sqlite-predicate-order-v1",
}
ACTUAL_D_STORAGE_PROFILE = {
    "python-state-actual-d-source-v1": "python-state-source-v1",
    "python-binding-actual-d-source-v1": "python-binding-source-v1",
    "sqlite-predicate-actual-d-source-v1": "sqlite-predicate-source-v1",
}


class ActualDFiniteSourceScope(FrozenContract):
    contract_version: Literal["rag_actual_d_finite_source_scope_v1"] = "rag_actual_d_finite_source_scope_v1"
    draft: DraftScope
    user_epoch: int = Field(ge=1)
    base_selection_handle: str = Field(pattern=r"^selection\.[0-9a-f]{32}$")
    base_selection_digest: str = Field(pattern=HASH)
    node_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    goal_hash: str = Field(pattern=HASH)
    target_id: TargetId
    target_definition_hash: str = Field(pattern=HASH)
    oracle_run_id: UUID

    @model_validator(mode="after")
    def exact_target(self) -> ActualDFiniteSourceScope:
        revalidate(self.draft, DraftScope)
        if self.target_definition_hash != get_finite_course_target(self.target_id).definition_hash:
            raise ValueError("actual D target definition changed")
        return self


def _draft_row(conn: Connection[dict[str, Any]], draft: DraftScope, *, allow_confirmed: bool) -> Mapping[str, object]:
    # Keep the original session-before-draft/run ordering. Confirmed reads are a
    # separate exact frozen-plan path; never pretend confirmed is draft_ready.
    # Consumption can arrive after C's version lock. Never wait on a D writer
    # that holds the session while waiting for C: fail closed in its savepoint.
    owner = conn.execute("SELECT id FROM users WHERE id=%s AND deleted_at IS NULL FOR SHARE"
                         + (" NOWAIT" if allow_confirmed else ""), (draft.user_id,)).fetchone()
    if owner is None:
        raise ValueError("actual D active owner missing")
    session = conn.execute("SELECT * FROM tutor_learning_plan_sessions WHERE id=%s AND user_id=%s FOR SHARE"
                           + (" NOWAIT" if allow_confirmed else ""),
                           (draft.session_id, draft.user_id)).fetchone()
    if (session is None or str(session["current_draft_id"]) != draft.draft_id
            or str(session["conversation_id"]) != draft.conversation_id):
        raise ValueError("actual D current draft missing")
    if session["status"] == "draft_ready":
        row = _scope_from_draft(conn, draft, lock=False)
    elif allow_confirmed and session["status"] == "confirmed":
        confirmed_row = conn.execute("SELECT * FROM tutor_learning_plan_drafts WHERE id=%s AND user_id=%s AND session_id=%s FOR SHARE",
                           (draft.draft_id, draft.user_id, draft.session_id)).fetchone()
        if confirmed_row is None:
            raise ValueError("actual D confirmed draft missing")
        row = confirmed_row
        active = conn.execute(
            "SELECT r.plan_json,r.content_hash,t.language_id FROM tutor_track_active_plans p "
            "JOIN tutor_track_plan_revisions r ON (r.id,r.track_id,r.user_id)=(p.revision_id,p.track_id,p.user_id) "
            "JOIN tutor_learning_tracks t ON (t.id,t.user_id)=(p.track_id,p.user_id) "
            "WHERE p.track_id=%s AND p.user_id=%s AND r.status='active' AND t.status='active' FOR SHARE OF p,r,t",
            (session["confirmed_track_id"], draft.user_id),
        ).fetchone()
        artifact = draft_artifact_from_row(row)
        if (active is None or artifact.plan.content_hash != active["content_hash"]
                or canonical_plan_payload(artifact.plan) != active["plan_json"]
                or artifact.profile.language_id != active["language_id"]):
            raise ValueError("actual D confirmed plan changed")
    else:
        raise ValueError("actual D draft is not eligible")
    if (row["draft_version"] != draft.draft_version or row["content_hash"] != draft.content_hash
            or str(row["source_run_id"]) != draft.source_run_id
            or row["source_input_revision"] != draft.source_input_revision):
        raise ValueError("actual D immutable draft changed")
    run = conn.execute("SELECT user_id,conversation_id,input_revision FROM tutor_runs WHERE id=%s FOR SHARE",
                       (draft.source_run_id,)).fetchone()
    if (run is None or str(run["user_id"]) != draft.user_id or str(run["conversation_id"]) != draft.conversation_id
            or run["input_revision"] != draft.source_input_revision):
        raise ValueError("actual D source input revision changed")
    if draft_artifact_from_row(row).content_hash != draft.content_hash:
        raise ValueError("actual D content hash changed")
    return row


def read_actual_d_finite_scope(conn: Connection[dict[str, Any]], *, draft: DraftScope,
                              base_selection_handle: str, node_id: str, target_id: TargetId,
                              oracle_run_id: UUID, allow_confirmed: bool = False
                              ) -> tuple[ActualDFiniteSourceScope, LearningMaterialDemand]:
    """Reconstruct exact draft/node/goal and a NEW D-scoped assessment demand."""
    from app.services.learning.item_supply.finite_course_mapping import finite_node_description

    _require_transaction(conn)
    draft = revalidate(draft, DraftScope)
    user_epoch = current_actual_d_epoch(conn, user_id=UUID(draft.user_id), nowait=allow_confirmed)
    parent = _draft_row(conn, draft, allow_confirmed=allow_confirmed)
    repo = PostgresMaterialBindingRepository(conn)
    # The original stored-selection decoder binds all scope columns and digest.
    # _scope_from_draft's draft_ready-only rule is not silently relaxed.
    selection = repo._read_selection(base_selection_handle, draft)
    _check_members(selection, parent)
    target = get_finite_course_target(target_id)
    node = _plan_nodes(parent).get(node_id)
    profile = parent["profile_json"]
    if (node is None or not isinstance(profile, dict) or profile.get("language_id") != target.language_id
            or node.get("description") != finite_node_description(target_id)
            or node.get("required_capabilities") != list(target.required_capabilities)):
        raise ValueError("actual D finite node semantics mismatch")
    main = [r for r in selection.requirements if (r.node_id, r.demand.purpose) == (node_id, "main_teaching")]
    goal = goal_hash_for_node(node)
    if (len(main) != 1 or main[0].goal_hash != goal
            or main[0].demand.scope.subject_id != target.subject_id
            or main[0].demand.scope.subject_version != "1.0"
            or main[0].demand.scope.facets != target.required_facets):
        raise ValueError("actual D main requirement mismatch")
    scope = ActualDFiniteSourceScope(draft=draft, user_epoch=user_epoch, base_selection_handle=base_selection_handle,
        base_selection_digest=selection.selection_digest, node_id=node_id, goal_hash=goal,
        target_id=target_id, target_definition_hash=target.definition_hash, oracle_run_id=oracle_run_id)
    # Execution nonce is NOT demand identity: preparation retries cannot create
    # additional capture/demand publication identities or reset accounting.
    demand_hash = digest({"contract": "rag_actual_d_finite_demand_v1",
        "actual_d": scope.model_dump(mode="json", exclude={"oracle_run_id"}),
        "main_demand": main[0].demand.model_dump(mode="json")})
    return scope, LearningMaterialDemand(demand_hash=demand_hash, scope=main[0].demand.scope,
        plan_ref="draft." + draft.draft_id, node_ref="node." + node_id, draft_revision=draft.draft_version,
        purpose="assessment_evidence", reading_level=main[0].demand.reading_level, language=main[0].demand.language)
