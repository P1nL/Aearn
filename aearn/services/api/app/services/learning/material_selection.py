"""Internal, default-off material feedback for an explicit successor planning run."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator, Protocol

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput, plan_draft_input_model
from app.agents.harness.contracts import (
    TutorContextSection, TutorContextSource, TutorDecision, TutorRunSnapshot, payload_mapping_from_fields,
)
from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.services.grounding.material_binding_repository import (
    MaterialBindingStale, PostgresMaterialBindingRepository, goal_hash_for_node,
)
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceBindingV2, MaterialFeedbackRef, MaterialSelectionEntry,
    MaterialSelectionResult, NodeMaterialRequirement, apply_material_dependencies, digest,
)
from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.material_semantics import (
    MaterialReviewReceipt, MaterialReviewRequest, MaterialSemanticReviewer, ReviewReason,
    StrictReviewVerdict,
    ReviewVerdict, candidate_digest_for_input, material_review_authority,
)
from app.services.learning.plan_drafting import LearningPlanDraftArtifact
from app.services.learning.plan_repository import PostgresLearningPlanSessionRepository


logger = logging.getLogger(__name__)


def _review_issue(verdict: str, reason: str) -> str | None:
    if verdict == ReviewVerdict.CONSISTENT.value and reason == ReviewReason.SUPPORTED.value:
        return None
    if verdict == ReviewVerdict.INCONSISTENT.value:
        return "material_" + reason
    return "material_review_uncertain_" + reason


class RequirementResolver(Protocol):
    """Server-only approved node/version/facet/purpose policy; no model or pointer inference."""

    def resolve(self, draft: DraftScope, profile: Mapping[str, object],
                nodes: Mapping[str, Mapping[str, object]]) -> tuple[NodeMaterialRequirement, ...]: ...


class MaterialScopeUnsupported(MaterialBindingStale):
    """A truthful unsupported/gap result: no fabricated canonical demand is persisted."""

    def __init__(self, nodes: tuple[str, ...]) -> None:
        super().__init__("material scope unsupported for nodes: " + ",".join(nodes))
        self.nodes = nodes


class MaterialPlanningAuthority(Protocol):
    """Bound same-connection C/current service, returning typed current receipts."""

    def resolve_evidence(self, draft: DraftScope,
                         requirements: tuple[NodeMaterialRequirement, ...]) -> MaterialSelectionResult: ...

    def authorize_selection(self, conn: Connection[Any], selection: MaterialSelectionResult) -> CurrentMaterialAuthorizationReceipt: ...

    def authorize_binding(self, conn: Connection[Any], binding: EvidenceBindingV2) -> CurrentMaterialAuthorizationReceipt: ...


def parent_snapshot_sources(parent: Mapping[str, object], draft_id: str) -> tuple[TutorContextSource, ...]:
    """Exact bounded parent facts; never rely on optional SYSTEM summaries."""
    plan = parent.get("plan_json")
    profile = parent.get("profile_json")
    if not isinstance(plan, dict) or not isinstance(profile, dict):
        raise MaterialBindingStale("parent snapshot unavailable")
    _nodes(plan)  # Validate the complete node set before constructing any part.
    units: list[dict[str, object]] = [
        {"profile": profile, "plan_title": plan.get("title"), "target_level": plan.get("target_level")},
    ]
    for module in plan["modules"]:
        units.append({"module": {key: value for key, value in module.items() if key != "nodes"}})
        for node in module["nodes"]:
            units.append({"module_key": module["module_key"], "node": node,
                          "goal_hash": goal_hash_for_node(node)})
    config = TutorContextBuilderConfig()
    builder = TutorContextBuilder(config=config)
    sources: list[TutorContextSource] = []
    pending: list[dict[str, object]] = []

    def source(items: list[dict[str, object]]) -> TutorContextSource:
        return TutorContextSource(
            source_id=f"material-parent:{draft_id}:{len(sources)}",
            content={"kind": "material_parent_snapshot", "draft_id": draft_id,
                     "part": len(sources), "items": items},
        )

    def length(items: list[dict[str, object]]) -> int:
        return len(json.dumps(source(items).content, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False))

    def append(items: list[dict[str, object]]) -> None:
        value = source(items)
        serialized, truncated = builder._serialize_source(TutorContextSection.REQUIRED_FACTS, value)
        if truncated or json.loads(serialized) != value.content:
            raise MaterialBindingStale("parent snapshot cannot be represented exactly")
        sources.append(value)

    # A v1.1.0 profile fits by itself, but duplicating its title/level in the
    # same unit can exceed 1200. Split whole objects, never their text or goals.
    if length([units[0]]) > config.max_source_characters:
        units[:1] = [{"profile": profile},
                     {"plan_title": plan.get("title"), "target_level": plan.get("target_level")}]
    for unit in units:
        candidate = [*pending, unit]
        if pending and (len(candidate) > 12 or length(candidate) > config.max_source_characters):
            append(pending)
            pending = []
        if length([unit]) > config.max_source_characters:
            raise MaterialBindingStale("parent snapshot exceeds source bound")
        pending.append(unit)
    if pending:
        append(pending)
    return tuple(sources)


@contextmanager
def material_transaction(conn: Connection[Any]) -> Iterator[None]:
    """Bridge a short D transaction from the dispatcher's provider-safe autocommit."""
    prior = conn.autocommit
    if prior:
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise MaterialBindingStale("material transaction needs idle connection")
        conn.autocommit = False
    try:
        with conn.transaction():
            yield
    finally:
        if prior:
            if conn.info.transaction_status != TransactionStatus.IDLE:
                conn.rollback()
            conn.autocommit = True


def _nodes(plan: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(plan, dict) or not isinstance(plan.get("modules"), list):
        raise MaterialBindingStale("invalid immutable plan")
    result: dict[str, Mapping[str, object]] = {}
    for module in plan["modules"]:
        if not isinstance(module, dict) or not isinstance(module.get("nodes"), list):
            raise MaterialBindingStale("invalid plan module")
        for node in module["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("knowledge_key"), str):
                raise MaterialBindingStale("invalid plan node")
            key = node["knowledge_key"]
            if key in result:
                raise MaterialBindingStale("duplicate plan node")
            result[key] = node
    if not result or len(result) > 128:
        raise MaterialBindingStale("plan outside bounded selection")
    return result


def _scope(row: Mapping[str, object], conversation_id: str) -> DraftScope:
    return DraftScope(
        user_id=str(row["user_id"]), conversation_id=conversation_id,
        session_id=str(row["session_id"]), draft_id=str(row["id"]),
        draft_version=int(str(row["draft_version"])), content_hash=str(row["content_hash"]),
        source_run_id=str(row["source_run_id"]),
        source_input_revision=int(str(row["source_input_revision"])),
    )


def _prerequisites(node: Mapping[str, object]) -> tuple[str, ...]:
    value = node.get("prerequisite_keys", ())
    if not isinstance(value, (tuple, list)) or any(not isinstance(x, str) for x in value):
        raise MaterialBindingStale("invalid immutable prerequisites")
    return tuple(value)


def _requirements(row: Mapping[str, object], scope: DraftScope,
                  resolver: RequirementResolver) -> tuple[NodeMaterialRequirement, ...]:
    nodes = _nodes(row["plan_json"])
    profile = row["profile_json"]
    if not isinstance(profile, dict):
        raise MaterialBindingStale("invalid immutable profile")
    # D's approved pilot is Python core / SQLite SQL. A trusted mapping can
    # choose versions, facets and usage, but cannot replace the course language.
    expected_subject = {"python": "route.python", "sql": "route.sql"}.get(str(profile.get("language_id")))
    if expected_subject is None:
        raise MaterialScopeUnsupported(tuple(nodes))
    requirements = resolver.resolve(scope, profile, nodes)
    if not requirements or len(requirements) > 128:
        raise MaterialScopeUnsupported(tuple(nodes))
    missing = set(nodes) - {r.node_id for r in requirements}
    if missing:
        raise MaterialScopeUnsupported(tuple(sorted(missing)))
    if len({(r.node_id, r.goal_hash, r.demand.purpose) for r in requirements}) != len(requirements):
        raise MaterialBindingStale("duplicate node/purpose requirement")
    for req in requirements:
        node = nodes.get(req.node_id)
        if (node is None or req.demand.scope.subject_id != expected_subject
                or req.goal_hash != goal_hash_for_node(node)
                or req.prerequisites != _prerequisites(node)
                or req.demand.plan_ref != f"draft.{scope.draft_id}"
                or req.demand.draft_revision != scope.draft_version
                or req.demand.node_ref != f"node.{req.node_id}"):
            raise MaterialBindingStale("requirement does not match immutable plan")
    return requirements


def _dependency_entries(requirements: tuple[NodeMaterialRequirement, ...],
                        entries: tuple[MaterialSelectionEntry, ...]) -> tuple[MaterialSelectionEntry, ...]:
    """Compatibility seam for tests; the strict V2 contract owns DAG normalization."""
    return apply_material_dependencies(requirements, entries)


class PostgresMaterialPlanningConsumer:
    """One persisted feedback assignment and one re-selection per explicit successor."""

    def __init__(self, conn: Connection[Any], *, authority: MaterialPlanningAuthority,
                 requirements: RequirementResolver,
                 semantic_reviewer: MaterialSemanticReviewer | None = None) -> None:
        self._semantic_reviewer = semantic_reviewer
        self._conn = conn
        self._repo = PostgresMaterialBindingRepository(conn)
        self._plans = PostgresLearningPlanSessionRepository(conn)
        self._authority = authority
        self._requirements = requirements

    def _select(self, row: Mapping[str, object], conversation_id: str, *,
                feedback_target: tuple[str, int] | None = None) -> MaterialSelectionResult:
        scope = _scope(row, conversation_id)
        requirements = _requirements(row, scope, self._requirements)
        idempotency_key = f"draft:{scope.draft_id}:{scope.content_hash}"
        if feedback_target is not None:
            # An abandoned target keeps its immutable assignment. A new run must
            # reselect current material rather than steal that old assignment.
            idempotency_key = f"feedback:{scope.draft_id}:{digest(feedback_target)}"
        prior = self._conn.execute(
            "SELECT handle FROM rag_material_selections WHERE user_id=%s AND session_id=%s "
            "AND draft_id=%s AND idempotency_key=%s FOR SHARE",
            (scope.user_id, scope.session_id, scope.draft_id, idempotency_key),
        ).fetchone()
        if prior is not None:
            saved = self._repo.get_selection(handle=str(prior["handle"]), draft=scope)
            if saved.requirements != requirements:
                raise MaterialBindingStale("approved material requirement policy changed")
            return saved
        resolved = self._authority.resolve_evidence(scope, requirements)
        if resolved.draft != scope or resolved.requirements != requirements:
            raise MaterialBindingStale("grounding selection changed demand scope")
        canonical = tuple(
            MaterialSelectionEntry.model_validate(entry.model_copy(update={
                "evidence": tuple(sorted(entry.evidence,
                    key=lambda item: digest(item.model_dump(mode="json")))),
            }).model_dump(mode="python"))
            for entry in resolved.entries
        )
        entries = _dependency_entries(requirements, canonical)
        if entries != resolved.entries:
            raw = resolved.model_dump(mode="json", exclude={"selection_digest"})
            raw["entries"] = [entry.model_dump(mode="json") for entry in entries]
            resolved = MaterialSelectionResult.model_validate_json(
                json.dumps({**raw, "selection_digest": digest(raw)}))
        return self._repo.record_selection(
            resolved, idempotency_key=idempotency_key,
        )

    def assign_parent_feedback(self, *, parent: DraftScope, target_run_id: str,
                               target_input_revision: int,
                               expected_session_version: int) -> MaterialFeedbackRef:
        """Call after a new persisted run is admitted, before its provider begins."""
        with material_transaction(self._conn):
            row = self._plans.draft_for_session(user_id=parent.user_id,
                                                session_id=parent.session_id,
                                                draft_id=parent.draft_id)
            if _scope(row, parent.conversation_id) != parent:
                raise MaterialBindingStale("parent scope changed")
            selection = self._select(row, parent.conversation_id,
                                     feedback_target=(target_run_id, target_input_revision))
            return self._repo.assign_feedback(
                handle=selection.handle, draft=parent, target_run_id=target_run_id,
                target_input_revision=target_input_revision,
                expected_session_version=expected_session_version,
                current_authorization=self._authority.authorize_selection,
            )

    def _feedback(self, run: TutorRunSnapshot,
                  session: Mapping[str, object]) -> tuple[MaterialFeedbackRef, MaterialSelectionResult] | None:
        try:
            ref = self._repo.get_feedback_for_target(
                user_id=run.user_id, conversation_id=run.conversation_id,
                target_run_id=run.run_id, target_input_revision=run.input_revision,
            )
        except MaterialBindingStale as exc:
            if "no feedback assigned" in str(exc):
                return None
            raise
        if (str(session["id"]) != ref.draft.session_id
                or str(session["current_draft_id"]) != ref.draft.draft_id
                or int(str(session["version"])) != ref.expected_session_version
                or int(str(session["draft_version"])) != ref.draft.draft_version):
            raise MaterialBindingStale("feedback parent/session CAS stale")
        selection = self._repo.get_selection(handle=ref.selection_handle, draft=ref.draft)
        if selection.selection_digest != ref.selection_digest:
            raise MaterialBindingStale("feedback selection digest changed")
        self._authority.authorize_selection(self._conn, selection)
        return ref, selection

    def context_for_run(self, run: TutorRunSnapshot, session: Mapping[str, object]) -> tuple[
        dict[str, object] | None, tuple[TutorContextSource, ...],
    ]:
        # Nested helpers retain their locks until this outer transaction ends.
        # A parent and its material feedback must never be collected separately.
        with material_transaction(self._conn):
            feedback = self.feedback_for_context(run, session)
            if feedback is None:
                if (session.get("current_draft_id") is not None
                        and self._plans.draft_for_source(user_id=run.user_id, run_id=run.run_id,
                                                         input_revision=run.input_revision) is None):
                    raise MaterialBindingStale("D revision requires assigned material feedback")
                return None, ()
            parents = self.parent_facts_for_context(run, session)
            if not parents:
                raise MaterialBindingStale("material feedback has no exact parent snapshot")
            source = TutorContextSource(
                source_id=f"material-feedback:{run.run_id}:{run.input_revision}", content=feedback,
            )
            builder = TutorContextBuilder(config=TutorContextBuilderConfig())
            serialized, truncated = builder._serialize_source(TutorContextSection.REQUIRED_FACTS, source)
            if not truncated and json.loads(serialized) == source.content:
                return feedback, parents
            # Keep each exact entry intact, but do not force all ready/gap entries
            # into one 1200-character source. The header points to required parts.
            entries = feedback.get("entries")
            if not isinstance(entries, list):
                raise MaterialBindingStale("material feedback cannot be represented exactly")
            parts: list[TutorContextSource] = []
            pending: list[object] = []

            def part(items: list[object]) -> TutorContextSource:
                return TutorContextSource(
                    source_id=f"material-feedback:{run.run_id}:{run.input_revision}:part:{len(parts)}",
                    content={"kind": "material_planning_feedback_part", "part": len(parts),
                             "parent_draft_version": feedback["parent_draft_version"], "entries": items},
                )

            def exact(candidate: TutorContextSource) -> bool:
                text, cut = builder._serialize_source(TutorContextSection.REQUIRED_FACTS, candidate)
                return not cut and json.loads(text) == candidate.content

            for entry in entries:
                if pending and not exact(part([*pending, entry])):
                    parts.append(part(pending))
                    pending = []
                if not exact(part([entry])):
                    raise MaterialBindingStale("material feedback entry cannot be represented exactly")
                pending.append(entry)
            if pending:
                parts.append(part(pending))
            header = {**feedback, "entries": [], "entry_parts": len(parts),
                      "instruction": str(feedback["instruction"]) + " Read all material_planning_feedback_part entries."}
            if not exact(TutorContextSource(source_id=source.source_id, content=header)):
                raise MaterialBindingStale("material feedback header cannot be represented exactly")
            return header, (*parents, *parts)

    def feedback_for_context(self, run: TutorRunSnapshot,
                             session: Mapping[str, object]) -> dict[str, object] | None:
        with material_transaction(self._conn):
            # A capability continuation of this same run must not re-inject an
            # already consumed parent or try to run a second feedback round.
            if self._plans.draft_for_source(user_id=run.user_id, run_id=run.run_id,
                                            input_revision=run.input_revision) is not None:
                return None
            feedback = self._feedback(run, session)
            if feedback is None:
                return None
            _, selection = feedback
            return {
                "kind": "material_planning_feedback", "schema_version": selection.contract_version,
                "parent_draft_version": selection.draft.draft_version,
                "entries": [{"node_id": e.node_id, "purpose": e.purpose, "status": e.status,
                             "covered_facets": list(e.covered_facets), "gaps": list(e.gaps),
                             "evidence_count": len(e.evidence),
                             "recommended": [{
                                 "source_handle": c.binding.source_handle,
                                 "document_handle": c.binding.document_handle,
                                 "document_revision": c.binding.document_revision,
                                 "purpose": c.binding.purpose,
                             } for c in e.evidence[:2]]} for e in selection.entries[:8]],
                "omitted_entry_count": max(0, len(selection.entries) - 8),
                "instruction": "Preserve every goal and prerequisite; never invent source coverage.",
            }

    def parent_facts_for_context(self, run: TutorRunSnapshot,
                                 session: Mapping[str, object]) -> tuple[TutorContextSource, ...]:
        with material_transaction(self._conn):
            feedback = self._feedback(run, session)
            if feedback is None:
                return ()
            ref, _selection = feedback
            parent = self._plans.draft_for_session(
                user_id=run.user_id, session_id=ref.draft.session_id,
                draft_id=ref.draft.draft_id,
            )
            return parent_snapshot_sources(parent, ref.draft.draft_id)

    def validate_successor_before_append(self, run: TutorRunSnapshot,
                                         session: Mapping[str, object],
                                         artifact: LearningPlanDraftArtifact,
                                         candidate: LearningPlanDraftCapabilityInput) -> MaterialFeedbackRef | None:
        feedback = self._feedback(run, session)
        if feedback is None:
            if session.get("current_draft_id") is not None:
                raise MaterialBindingStale("D revision requires assigned material feedback")
            return None
        ref, selection = feedback
        parent = self._plans.draft_for_session(user_id=run.user_id,
                                               session_id=ref.draft.session_id,
                                               draft_id=ref.draft.draft_id)
        if (_scope(parent, run.conversation_id) != ref.draft
                or parent["goal_text"] != artifact.profile.goal_text
                or parent["language_id"] != artifact.profile.language_id):
            raise MaterialBindingStale("successor changed core goal or parent")
        before = _nodes(parent["plan_json"])
        after = _nodes(canonical_plan_payload(artifact.plan))
        if set(before) != set(after) or any(
            goal_hash_for_node(before[key]) != goal_hash_for_node(after[key]) for key in before
        ):
            raise MaterialBindingStale("successor changed node goal or prerequisite map")
        self.assert_review_before_append(run, candidate, parent, selection)
        return ref

    def review_decision(self, run: TutorRunSnapshot, decision: TutorDecision,
                        attempt_index: int) -> str | None:
        """One D review per draft candidate, outside provider/DB write transactions."""
        requests = [item for item in decision.capability_requests
                    if item.capability_id == "learning.plan.draft"]
        if not requests:
            return None  # Skill selection and terminal messages are not draft candidates.
        if len(requests) != 1 or not 1 <= attempt_index <= 2:
            return "material_candidate_invalid"
        values = payload_mapping_from_fields(requests[0].arguments)
        if values is None:
            return "material_candidate_invalid"
        try:
            candidate = plan_draft_input_model(requests[0].capability_version).model_validate(values)
        except ValueError:
            return "material_candidate_invalid"
        if self._semantic_reviewer is None:
            return "material_review_uncertain_unavailable"
        with material_transaction(self._conn):
            session = self._plans.active_session_for_run(
                user_id=run.user_id, run_id=run.run_id, input_revision=run.input_revision)
            feedback = self._feedback(run, session)
            if feedback is None:
                if session.get("current_draft_id") is not None:
                    raise MaterialBindingStale("D revision requires assigned material feedback")
                return None
            ref, selection = feedback
            parent = self._plans.draft_for_session(
                user_id=run.user_id, session_id=ref.draft.session_id,
                draft_id=ref.draft.draft_id)
            authority = material_review_authority(selection, parent)
            try:
                request = MaterialReviewRequest.build(
                    run_id=run.run_id, input_revision=run.input_revision,
                    selection_digest=selection.selection_digest,
                    parent_content_hash=selection.draft.content_hash,
                    candidate_digest=candidate_digest_for_input(candidate), authority=authority,
                    candidate={"capability_input": candidate.model_dump(mode="json"),
                               "public_message": decision.public_message,
                               "public_thinking_text": decision.public_thinking_text},
                )
            except ValueError:
                return "material_review_uncertain_context"
        # Reserve the exact attempt before network IO. A crash keeps an unknown-usage
        # dispatch record; replay never sends a second billed request for this key.
        with material_transaction(self._conn):
            self._assert_review_run_current(run)
            session = self._plans.active_session_for_run(
                user_id=run.user_id, run_id=run.run_id, input_revision=run.input_revision)
            current = self._feedback(run, session)
            if current is None or current[0] != ref or current[1].selection_digest != selection.selection_digest:
                raise MaterialBindingStale("semantic review selection changed")
            prior = self._conn.execute(
                "SELECT * FROM rag_material_semantic_reviews WHERE run_id=%s AND input_revision=%s "
                "AND decision_iteration=%s AND attempt_index=%s FOR SHARE",
                (run.run_id,run.input_revision,run.model_call_count + 1,attempt_index),
            ).fetchone()
            if prior is not None:
                if (prior["request_binding_hash"] != request.binding_hash
                        or prior["selection_handle"] != selection.handle
                        or prior["candidate_digest"] != request.candidate_digest):
                    raise MaterialBindingStale("semantic review attempt conflicts with different candidate")
                if prior["review_status"] == "dispatched":
                    return "material_review_uncertain_incomplete_dispatch"
                return _review_issue(prior["verdict"], prior["reason_code"])
            self._conn.execute(
                "INSERT INTO rag_material_semantic_reviews (user_id,conversation_id,run_id,"
                "input_revision,decision_iteration,attempt_index,selection_handle,selection_digest,"
                "parent_content_hash,candidate_digest,authority_hash,candidate_hash,"
                "request_binding_hash,review_status,verdict,reason_code) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'dispatched','uncertain','insufficient_context')",
                (run.user_id,run.conversation_id,run.run_id,run.input_revision,
                 run.model_call_count + 1,attempt_index,selection.handle,selection.selection_digest,
                 selection.draft.content_hash,request.candidate_digest,digest(authority),
                 digest(json.loads(request.candidate_json)),request.binding_hash),
            )
        try:
            receipt = self._semantic_reviewer.review(request)
        except Exception:
            receipt = MaterialReviewReceipt(
                request.binding_hash,
                StrictReviewVerdict(verdict=ReviewVerdict.UNCERTAIN,
                                    reason_code=ReviewReason.PROVIDER_UNAVAILABLE), None, None)
        if receipt.request_binding_hash != request.binding_hash:
            receipt = MaterialReviewReceipt(
                request.binding_hash,
                StrictReviewVerdict(verdict=ReviewVerdict.UNCERTAIN,
                                    reason_code=ReviewReason.REQUEST_BINDING_INVALID),
                receipt.model, receipt.usage)
        usage = asdict(receipt.usage) if receipt.usage is not None else None
        # Settle usage separately from eligibility. Lost lease or withdrawn C
        # authority must never roll back a completed provider usage audit.
        try:
            with material_transaction(self._conn):
                settled = self._conn.execute(
                    "UPDATE rag_material_semantic_reviews SET review_status='settled',"
                    "verdict=%s,reason_code=%s,reviewer_model=%s,usage_json=%s "
                    "WHERE run_id=%s AND input_revision=%s AND decision_iteration=%s "
                    "AND attempt_index=%s AND request_binding_hash=%s "
                    "AND review_status='dispatched' RETURNING id",
                    (receipt.verdict.verdict.value,receipt.verdict.reason_code.value,
                     receipt.model,Jsonb(usage) if usage is not None else None,
                     run.run_id,run.input_revision,run.model_call_count + 1,attempt_index,
                     request.binding_hash),
                ).fetchone()
                if settled is None:
                    raise MaterialBindingStale("semantic review settlement conflict")
        except Exception:
            logger.warning("D semantic review audit settlement unavailable: usage_known=%s",
                           usage is not None)
            return "material_review_uncertain_audit"
        with material_transaction(self._conn):
            self._assert_review_run_current(run)
            session = self._plans.active_session_for_run(
                user_id=run.user_id, run_id=run.run_id, input_revision=run.input_revision)
            current = self._feedback(run, session)
            if current is None or current[0] != ref or current[1].selection_digest != selection.selection_digest:
                raise MaterialBindingStale("semantic review selection changed")
        return _review_issue(receipt.verdict.verdict.value, receipt.verdict.reason_code.value)

    def _assert_review_run_current(self, run: TutorRunSnapshot) -> None:
        row = self._conn.execute(
            "SELECT input_revision,status,active_lease_owner_id,active_lease_generation,"
            "active_lease_expires_at,cancelled_at,terminal_outcome,"
            "clock_timestamp() AS checked_at FROM tutor_runs "
            "WHERE id=%s AND user_id=%s AND conversation_id=%s FOR SHARE",
            (run.run_id,run.user_id,run.conversation_id),
        ).fetchone()
        lease = run.lease
        if (row is None or lease is None or int(row["input_revision"]) != run.input_revision
                or row["status"] not in {"leased", "running"}
                or row["cancelled_at"] is not None or row["terminal_outcome"] is not None
                or row["active_lease_owner_id"] != lease.owner_id
                or int(row["active_lease_generation"]) != lease.generation
                or row["active_lease_expires_at"] <= row["checked_at"]):
            raise MaterialBindingStale("semantic review lost run lease or revision")
    def assert_review_before_append(self, run: TutorRunSnapshot,
                                    candidate: LearningPlanDraftCapabilityInput,
                                    parent: Mapping[str, object],
                                    selection: MaterialSelectionResult) -> None:
        """Independent same-transaction exact receipt check; no model IO."""
        row = self._conn.execute(
            "SELECT review.* FROM rag_material_semantic_reviews AS review "
            "JOIN tutor_provider_attempt_receipts AS provider ON "
            "provider.run_id=review.run_id AND provider.input_revision=review.input_revision "
            "AND provider.decision_iteration=review.decision_iteration "
            "AND provider.attempt_index=review.attempt_index "
            "AND provider.outcome='accepted' "
            "WHERE review.run_id=%s AND review.user_id=%s AND review.conversation_id=%s "
            "AND review.input_revision=%s AND review.selection_handle=%s "
            "AND review.selection_digest=%s AND review.parent_content_hash=%s "
            "AND review.candidate_digest=%s AND review.verdict='consistent' "
            "AND review.review_status='settled' AND review.decision_iteration=%s FOR SHARE OF review",
            (run.run_id, run.user_id, run.conversation_id, run.input_revision,
             selection.handle, selection.selection_digest, selection.draft.content_hash,
             candidate_digest_for_input(candidate), run.model_call_count),
        ).fetchone()
        if row is None or row["reason_code"] != ReviewReason.SUPPORTED.value:
            raise MaterialBindingStale("exact material semantic review receipt required")
        authority_hash = digest(material_review_authority(selection, parent))
        identity = dict(run_id=run.run_id,input_revision=run.input_revision,
                        selection_digest=selection.selection_digest,
                        parent_content_hash=selection.draft.content_hash,
                        candidate_digest=candidate_digest_for_input(candidate),
                        authority_hash=authority_hash,candidate_hash=row["candidate_hash"])
        if (row["authority_hash"] != authority_hash
                or row["request_binding_hash"] != digest(identity)):
            raise MaterialBindingStale("semantic review receipt binding changed")
    def after_successor_append(self, *, run: TutorRunSnapshot,
                               row: Mapping[str, object],
                               feedback: MaterialFeedbackRef) -> MaterialSelectionResult:
        if (str(row["predecessor_draft_id"]) != feedback.draft.draft_id
                or str(row["source_run_id"]) != run.run_id
                or int(str(row["source_input_revision"])) != run.input_revision
                or int(str(row["draft_version"])) != feedback.draft.draft_version + 1):
            raise MaterialBindingStale("successor predecessor/source mismatch")
        selection = self._select(row, run.conversation_id)
        for entry in selection.entries:
            if entry.status != "ready":
                continue
            raw: dict[str, object] = {
                "contract_version": "rag_d_binding_v2",
                "selection_handle": selection.handle,
                "selection_digest": selection.selection_digest,
                "draft": selection.draft.model_dump(mode="json"),
                "node_id": entry.node_id, "goal_hash": entry.goal_hash,
                "purpose": entry.purpose,
                "evidence": [item.model_dump(mode="json") for item in entry.evidence],
            }
            binding = EvidenceBindingV2.model_validate_json(
                json.dumps({**raw, "binding_digest": digest(raw)}))
            self._repo.freeze_binding(
                binding=binding,
                idempotency_key=f"draft:{selection.draft.draft_id}:{entry.node_id}:{entry.purpose}",
                current_authorization=self._authority.authorize_binding,
            )
        return selection
