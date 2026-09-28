"""Caller-owned PostgreSQL transactions for D snapshots and frozen exact bindings.

This repository never creates a connection, commits, or treats persisted hashes as
current source authorization. Callers supply the same-connection authorization port.
"""
from __future__ import annotations

import json
from datetime import timedelta
from collections.abc import Callable, Mapping
from typing import Any

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.services.grounding.autonomous.contracts import revalidate
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceBindingV2,
    MaterialFeedbackRef, MaterialSelectionResult, digest,
)


class MaterialBindingConflict(ValueError):
    pass


class MaterialBindingStale(MaterialBindingConflict):
    pass


class MaterialTransactionRequired(MaterialBindingConflict):
    pass


SelectionAuthorization = Callable[[Connection[Any], MaterialSelectionResult], CurrentMaterialAuthorizationReceipt]
BindingAuthorization = Callable[[Connection[Any], EvidenceBindingV2], CurrentMaterialAuthorizationReceipt]


def goal_hash_for_node(node: Mapping[str, object]) -> str:
    """Hash only the immutable, learner-visible canonical node goal/dependencies."""
    return digest({key: node.get(key) for key in (
        "knowledge_key", "title", "description", "is_core", "prerequisite_keys",
        "required_capabilities", "catalog_knowledge_key",
    )})


def _require_transaction(conn: Connection[Any]) -> None:
    if conn.autocommit or conn.info.transaction_status != TransactionStatus.INTRANS:
        raise MaterialTransactionRequired("explicit caller-owned transaction required")
    isolation = conn.execute("SHOW transaction_isolation").fetchone()
    # A READ COMMITTED snapshot is required for current checks after lock waits.
    if isolation is None or str(next(iter(isolation.values()))).lower() != "read committed":
        raise MaterialTransactionRequired("READ COMMITTED transaction required")
    read_only = conn.execute("SHOW transaction_read_only").fetchone()
    if read_only is None or str(next(iter(read_only.values()))).lower() != "off":
        raise MaterialTransactionRequired("writable transaction required")


def _authorize(
    callback: Callable[..., object], conn: Connection[Any],
    value: MaterialSelectionResult | EvidenceBindingV2,
) -> CurrentMaterialAuthorizationReceipt:
    if not callable(callback):
        raise MaterialBindingConflict("current authorization callback required")
    result = callback(conn, value)
    if type(result) is not CurrentMaterialAuthorizationReceipt:
        raise MaterialBindingConflict("exact current authorization receipt required")
    try:
        receipt = revalidate(result, CurrentMaterialAuthorizationReceipt)
    except ValueError as exc:
        raise MaterialBindingConflict("invalid current authorization receipt") from exc
    expected_kind = "selection" if isinstance(value, MaterialSelectionResult) else "binding"
    expected_digest = (value.selection_digest if isinstance(value, MaterialSelectionResult)
                       else value.binding_digest)
    expected_purposes = (tuple(sorted({e.purpose for e in value.entries}))
                         if isinstance(value, MaterialSelectionResult) else (value.purpose,))
    now_row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
    if now_row is None:
        raise MaterialBindingConflict("authorization clock unavailable")
    now = now_row["now"]
    if (receipt.kind != expected_kind or receipt.object_digest != expected_digest
            or receipt.draft != value.draft or receipt.purposes != expected_purposes
            or receipt.checked_at > now or now - receipt.checked_at > timedelta(seconds=30)):
        raise MaterialBindingConflict("current authorization receipt is not bound to request")
    return receipt


def _decode(value: object, model: type[Any]) -> Any:
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))


def _scope_from_draft(conn: Connection[Any], scope: DraftScope, *, lock: bool) -> Mapping[str, object]:
    session = conn.execute(
        "SELECT id, user_id, conversation_id, current_draft_id, version, status "
        "FROM tutor_learning_plan_sessions WHERE id=%s AND user_id=%s"
        + (" FOR UPDATE" if lock else " FOR SHARE"),
        (scope.session_id, scope.user_id),
    ).fetchone()
    if (session is None or str(session["conversation_id"]) != scope.conversation_id
            or str(session["current_draft_id"]) != scope.draft_id
            or session["status"] != "draft_ready"):
        raise MaterialBindingStale("draft is not the current session draft")
    row = conn.execute(
        "SELECT d.*, r.conversation_id AS run_conversation_id "
        "FROM tutor_learning_plan_drafts d JOIN tutor_runs r ON r.id=d.source_run_id "
        "WHERE d.id=%s AND d.user_id=%s AND d.session_id=%s FOR SHARE OF d, r",
        (scope.draft_id, scope.user_id, scope.session_id),
    ).fetchone()
    if (row is None or int(row["draft_version"]) != scope.draft_version
            or row["content_hash"] != scope.content_hash
            or str(row["source_run_id"]) != scope.source_run_id
            or int(row["source_input_revision"]) != scope.source_input_revision
            or str(row["run_conversation_id"]) != scope.conversation_id):
        raise MaterialBindingStale("exact immutable draft scope changed")
    return row


def _plan_nodes(row: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    plan = row["plan_json"]
    if not isinstance(plan, dict) or not isinstance(plan.get("modules"), list):
        raise MaterialBindingStale("invalid immutable plan shape")
    nodes: dict[str, Mapping[str, object]] = {}
    for module in plan["modules"]:
        if not isinstance(module, dict) or not isinstance(module.get("nodes"), list):
            raise MaterialBindingStale("invalid immutable plan modules")
        for node in module["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("knowledge_key"), str):
                raise MaterialBindingStale("invalid immutable plan node")
            key = node["knowledge_key"]
            if key in nodes:
                raise MaterialBindingStale("duplicate plan node")
            nodes[key] = node
    return nodes


def _check_members(selection: MaterialSelectionResult, row: Mapping[str, object]) -> None:
    nodes = _plan_nodes(row)
    if {r.node_id for r in selection.requirements} != set(nodes):
        raise MaterialBindingStale("selection does not cover the whole draft")
    for requirement in selection.requirements:
        node = nodes[requirement.node_id]
        prerequisites = node.get("prerequisite_keys")
        if (not isinstance(prerequisites, list)
                or requirement.goal_hash != goal_hash_for_node(node)
                or tuple(prerequisites) != requirement.prerequisites):
            raise MaterialBindingStale("node goal or prerequisites changed")


def _check_pending_jobs(conn: Connection[Any], selection: MaterialSelectionResult) -> None:
    demands = {(r.node_id, r.goal_hash, r.demand.purpose): r.demand
               for r in selection.requirements}
    for entry in selection.entries:
        if entry.status != "pending":
            continue
        demand = demands[(entry.node_id, entry.goal_hash, entry.purpose)]
        job = conn.execute(
            "SELECT id FROM rag_discovery_jobs WHERE id=%s AND demand_hash=%s "
            "AND subject_id=%s AND subject_version=%s AND purpose=%s "
            "AND state IN ('pending','leased') FOR SHARE",
            (entry.preparation_job_id, demand.demand_hash, demand.scope.subject_id,
             demand.scope.subject_version, entry.purpose),
        ).fetchone()
        if job is None:
            raise MaterialBindingStale("pending selection has no current exact preparation job")


class PostgresMaterialBindingRepository:
    """No implicit transactions. Scope and authorization checked even on replay."""

    def __init__(self, conn: Connection[Any]) -> None:
        self._conn = conn

    @property
    def conn(self) -> Connection[Any]:
        return self._conn

    def record_selection(self, selection: MaterialSelectionResult, *, idempotency_key: str) -> MaterialSelectionResult:
        conn = self._conn
        _require_transaction(conn)
        selection = revalidate(selection, MaterialSelectionResult)
        row = _scope_from_draft(conn, selection.draft, lock=True)
        _check_members(selection, row)
        _check_pending_jobs(conn, selection)
        if not 3 <= len(idempotency_key) <= 160:
            raise MaterialBindingConflict("invalid idempotency key")
        existing = conn.execute(
            "SELECT snapshot_json, idempotency_key FROM rag_material_selections "
            "WHERE draft_id=%s AND (idempotency_key=%s OR selection_digest=%s OR handle=%s) FOR UPDATE",
            (selection.draft.draft_id, idempotency_key, selection.selection_digest, selection.handle),
        ).fetchall()
        if existing:
            if len(existing) != 1 or existing[0]["idempotency_key"] != idempotency_key:
                raise MaterialBindingConflict("selection retry conflicts with stored authority")
            stored = _decode(existing[0]["snapshot_json"], MaterialSelectionResult)
            if stored != selection:
                raise MaterialBindingConflict("selection retry payload differs")
            return stored
        conn.execute(
            "INSERT INTO rag_material_selections "
            "(handle,user_id,conversation_id,session_id,draft_id,draft_version,content_hash,"
            "source_run_id,source_input_revision,selection_digest,snapshot_json,idempotency_key) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
            (selection.handle, selection.draft.user_id, selection.draft.conversation_id,
             selection.draft.session_id, selection.draft.draft_id, selection.draft.draft_version,
             selection.draft.content_hash, selection.draft.source_run_id,
             selection.draft.source_input_revision, selection.selection_digest,
             json.dumps(selection.model_dump(mode="json")), idempotency_key),
        )
        return selection

    def get_selection(self, *, handle: str, draft: DraftScope) -> MaterialSelectionResult:
        _require_transaction(self._conn)
        draft = revalidate(draft, DraftScope)
        row = _scope_from_draft(self._conn, draft, lock=False)
        selection = self._read_selection(handle, draft)
        _check_members(selection, row)
        return selection

    def _read_selection(self, handle: str, draft: DraftScope) -> MaterialSelectionResult:
        row = self._conn.execute(
            "SELECT snapshot_json,selection_digest FROM rag_material_selections "
            "WHERE handle=%s AND user_id=%s AND conversation_id=%s AND session_id=%s "
            "AND draft_id=%s AND draft_version=%s AND content_hash=%s "
            "AND source_run_id=%s AND source_input_revision=%s FOR SHARE",
            (handle, draft.user_id, draft.conversation_id, draft.session_id, draft.draft_id,
             draft.draft_version, draft.content_hash, draft.source_run_id, draft.source_input_revision),
        ).fetchone()
        if row is None:
            raise MaterialBindingStale("selection is absent from exact draft scope")
        selection = _decode(row["snapshot_json"], MaterialSelectionResult)
        if selection.draft != draft or selection.handle != handle or selection.selection_digest != row["selection_digest"]:
            raise MaterialBindingStale("selection storage does not match digest")
        return selection

    def assign_feedback(
        self, *, handle: str, draft: DraftScope, target_run_id: str,
        target_input_revision: int, expected_session_version: int,
        current_authorization: SelectionAuthorization,
    ) -> MaterialFeedbackRef:
        conn = self._conn
        _require_transaction(conn)
        draft = revalidate(draft, DraftScope)
        parent = _scope_from_draft(conn, draft, lock=True)
        selection = self._read_selection(handle, draft)
        _check_members(selection, parent)
        _check_pending_jobs(conn, selection)
        session = conn.execute(
            "SELECT version FROM tutor_learning_plan_sessions WHERE id=%s AND user_id=%s",
            (draft.session_id, draft.user_id),
        ).fetchone()
        if session is None or session["version"] != expected_session_version:
            raise MaterialBindingStale("parent session CAS changed")
        run = conn.execute(
            "SELECT r.id FROM tutor_runs r JOIN tutor_run_learning_scopes s ON s.run_id=r.id "
            "WHERE r.id=%s AND r.user_id=%s AND r.conversation_id=%s "
            "AND r.origin='interactive' AND r.input_revision=%s "
            "AND r.status IN ('queued','leased','running','waiting_for_input',"
            "'waiting_for_capability','awaiting_effect_commit') "
            "AND r.terminal_outcome IS NULL AND r.cancelled_at IS NULL "
            "AND r.superseded_by_run_id IS NULL AND r.created_at >= %s "
            "AND NOT EXISTS (SELECT 1 FROM tutor_learning_plan_drafts existing "
            "WHERE existing.source_run_id=r.id AND existing.source_input_revision=r.input_revision) "
            "AND s.scope_kind='plan_drafting' "
            "AND s.task_kind='plan_drafting' AND s.user_id=%s AND s.conversation_id=%s "
            "FOR SHARE OF r,s",
            (target_run_id, draft.user_id, draft.conversation_id, target_input_revision,
             parent["created_at"], draft.user_id, draft.conversation_id),
        ).fetchone()
        if run is None or target_run_id == draft.source_run_id or target_input_revision < 1:
            raise MaterialBindingStale("target is not an active successor planning run")
        _authorize(current_authorization, conn, selection)
        data = dict(selection_handle=handle, selection_digest=selection.selection_digest,
                    draft=draft.model_dump(mode="json"), target_run_id=target_run_id,
                    target_input_revision=target_input_revision,
                    expected_session_version=expected_session_version)
        ref = MaterialFeedbackRef.model_validate({**data, "assignment_digest": digest(data)})
        assigned = conn.execute(
            "UPDATE rag_material_selections SET target_run_id=%s,target_input_revision=%s,"
            "expected_session_version=%s,assignment_digest=%s,assigned_at=clock_timestamp() "
            "WHERE handle=%s AND target_run_id IS NULL RETURNING handle",
            (target_run_id, target_input_revision, expected_session_version,
             ref.assignment_digest, handle),
        ).fetchone()
        if assigned is None:
            prior = conn.execute(
                "SELECT target_run_id,target_input_revision,expected_session_version,assignment_digest "
                "FROM rag_material_selections WHERE handle=%s", (handle,),
            ).fetchone()
            if (prior is None or str(prior["target_run_id"]) != target_run_id
                    or prior["target_input_revision"] != target_input_revision
                    or prior["expected_session_version"] != expected_session_version
                    or prior["assignment_digest"] != ref.assignment_digest):
                raise MaterialBindingConflict("feedback selection already assigned elsewhere")
        return ref

    def get_feedback_for_target(
        self, *, user_id: str, conversation_id: str, target_run_id: str,
        target_input_revision: int,
    ) -> MaterialFeedbackRef:
        _require_transaction(self._conn)
        row = self._conn.execute(
            "SELECT snapshot_json,assignment_digest,expected_session_version "
            "FROM rag_material_selections WHERE user_id=%s AND conversation_id=%s "
            "AND target_run_id=%s AND target_input_revision=%s FOR SHARE",
            (user_id, conversation_id, target_run_id, target_input_revision),
        ).fetchone()
        if row is None:
            raise MaterialBindingStale("no feedback assigned to exact target pair")
        selection = _decode(row["snapshot_json"], MaterialSelectionResult)
        parent = _scope_from_draft(self._conn, selection.draft, lock=False)
        _check_members(selection, parent)
        _check_pending_jobs(self._conn, selection)
        current = self._conn.execute(
            "SELECT version FROM tutor_learning_plan_sessions WHERE id=%s AND user_id=%s",
            (selection.draft.session_id, user_id),
        ).fetchone()
        target = self._conn.execute(
            "SELECT r.id FROM tutor_runs r JOIN tutor_run_learning_scopes s ON s.run_id=r.id "
            "WHERE r.id=%s AND r.user_id=%s AND r.conversation_id=%s "
            "AND r.origin='interactive' AND r.input_revision=%s "
            "AND r.status IN ('queued','leased','running','waiting_for_input',"
            "'waiting_for_capability','awaiting_effect_commit') "
            "AND r.terminal_outcome IS NULL AND r.cancelled_at IS NULL "
            "AND r.superseded_by_run_id IS NULL AND r.created_at >= %s "
            "AND NOT EXISTS (SELECT 1 FROM tutor_learning_plan_drafts existing "
            "WHERE existing.source_run_id=r.id AND existing.source_input_revision=r.input_revision) "
            "AND s.scope_kind='plan_drafting' "
            "AND s.task_kind='plan_drafting' FOR SHARE OF r,s",
            (target_run_id, user_id, conversation_id, target_input_revision,
             parent["created_at"]),
        ).fetchone()
        if (current is None or current["version"] != row["expected_session_version"]
                or target is None):
            raise MaterialBindingStale("feedback parent CAS or target run changed")
        ref_data = dict(selection_handle=selection.handle, selection_digest=selection.selection_digest,
                        draft=selection.draft.model_dump(mode="json"), target_run_id=target_run_id,
                        target_input_revision=target_input_revision,
                        expected_session_version=row["expected_session_version"],
                        assignment_digest=row["assignment_digest"])
        return MaterialFeedbackRef.model_validate(ref_data)

    def freeze_binding(
        self, *, binding: EvidenceBindingV2, idempotency_key: str,
        current_authorization: BindingAuthorization,
    ) -> EvidenceBindingV2:
        conn = self._conn
        _require_transaction(conn)
        binding = revalidate(binding, EvidenceBindingV2)
        parent = _scope_from_draft(conn, binding.draft, lock=True)
        selection = self._read_selection(binding.selection_handle, binding.draft)
        _check_members(selection, parent)
        entry = next((e for e in selection.entries if
                      (e.node_id, e.goal_hash, e.purpose) ==
                      (binding.node_id, binding.goal_hash, binding.purpose)), None)
        if (selection.selection_digest != binding.selection_digest or entry is None
                or entry.status != "ready" or entry.evidence != binding.evidence):
            raise MaterialBindingConflict("binding is not the exact ready selection member")
        if not 3 <= len(idempotency_key) <= 160:
            raise MaterialBindingConflict("invalid binding idempotency key")
        _authorize(current_authorization, conn, binding)
        existing = conn.execute(
            "SELECT binding_json,idempotency_key,node_id,goal_hash,purpose "
            "FROM rag_plan_material_bindings "
            "WHERE draft_id=%s AND ((node_id=%s AND goal_hash=%s AND purpose=%s) "
            "OR idempotency_key=%s) FOR UPDATE",
            (binding.draft.draft_id, binding.node_id, binding.goal_hash,
             binding.purpose, idempotency_key),
        ).fetchall()
        if existing:
            if (len(existing) != 1 or existing[0]["node_id"] != binding.node_id
                    or existing[0]["goal_hash"] != binding.goal_hash
                    or existing[0]["purpose"] != binding.purpose):
                raise MaterialBindingConflict("binding retry points to a different natural key")
            stored = _decode(existing[0]["binding_json"], EvidenceBindingV2)
            if stored != binding:
                raise MaterialBindingConflict("binding retry payload differs")
            return stored
        conn.execute(
            "INSERT INTO rag_plan_material_bindings "
            "(selection_handle,selection_digest,user_id,session_id,draft_id,node_id,goal_hash,"
            "purpose,binding_digest,binding_json,idempotency_key) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
            (binding.selection_handle, binding.selection_digest, binding.draft.user_id,
             binding.draft.session_id, binding.draft.draft_id, binding.node_id,
             binding.goal_hash, binding.purpose, binding.binding_digest,
             json.dumps(binding.model_dump(mode="json")), idempotency_key),
        )
        return binding
