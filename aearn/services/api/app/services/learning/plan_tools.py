"""Server-authoritative typed learning-plan tools for the Codex runtime."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.harness.contracts import TutorRunSnapshot
from app.services.learning.contracts import stable_key
from app.services.learning.plan_capability import (
    LearningPlanDraftCapabilityError,
    build_validated_learning_plan_artifact,
)
from app.services.learning.plan_drafting import (
    CompactPlanModule,
    CompactPlanNode,
    CompactPlanProfile,
    LearningPlanExperienceLevel,
)
from app.services.learning.plan_repository import (
    LearningPlanDraftConflict,
    LearningPlanSessionConflict,
    LearningPlanSessionNotFound,
    PostgresLearningPlanSessionRepository,
)
from app.services.learning.planning_facts import (
    PlanningFactField,
    PostgresPlanningFactRepository,
)
from app.services.learning.planning_questions import (
    PLANNING_QUESTION_CATALOG_VERSION,
    build_planning_question_model_descriptor,
)

PLANNING_CONTEXT_TOOL_NAME = "aearn_planning_context_read"
LEARNING_PLAN_DRAFT_TOOL_NAME = "aearn_learning_plan_draft"
LEARNING_PLAN_TOOL_SCHEMA_VERSION = "aearn-learning-plan-tools-v1"


class LearningPlanToolStatus(StrEnum):
    COMPLETED = "completed"
    REPAIRABLE_INVALID = "repairable_invalid"
    AWAITING_USER = "awaiting_user"
    CONFLICT = "conflict"
    POLICY_BLOCKED = "policy_blocked"
    UNAVAILABLE = "unavailable"
    FATAL = "fatal"


class _ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PlanningContextReadInput(_ToolModel):
    schema_version: Literal["aearn-learning-plan-tools-v1"] = "aearn-learning-plan-tools-v1"


class LearningPlanDraftNodeInput(_ToolModel):
    stable_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    is_core: bool = True
    prerequisites: tuple[str, ...] = Field(default=(), max_length=8)
    required_capabilities: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("stable_key")
    @classmethod
    def _normalize_stable_key(cls, value: str) -> str:
        return stable_key(value, label="node stable_key")

    @field_validator("prerequisites", "required_capabilities")
    @classmethod
    def _normalize_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(stable_key(value, label="stable key") for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate_stable_key")
        return normalized


class LearningPlanDraftModuleInput(_ToolModel):
    stable_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    is_core: bool = True
    is_skippable: bool = False
    nodes: tuple[LearningPlanDraftNodeInput, ...] = Field(min_length=1, max_length=8)

    @field_validator("stable_key")
    @classmethod
    def _normalize_stable_key(cls, value: str) -> str:
        return stable_key(value, label="module stable_key")


class LearningPlanDraftToolInput(_ToolModel):
    schema_version: Literal["aearn-learning-plan-tools-v1"] = "aearn-learning-plan-tools-v1"
    modules: tuple[LearningPlanDraftModuleInput, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _validate_graph(self) -> "LearningPlanDraftToolInput":
        module_keys = tuple(module.stable_key for module in self.modules)
        if len(module_keys) != len(set(module_keys)):
            raise ValueError("duplicate_module_key")
        node_keys = tuple(node.stable_key for module in self.modules for node in module.nodes)
        if len(node_keys) != len(set(node_keys)):
            raise ValueError("duplicate_node_key")
        available = set(node_keys)
        prerequisites = {
            node.stable_key: node.prerequisites
            for module in self.modules
            for node in module.nodes
        }
        if any(node_key in values for node_key, values in prerequisites.items()):
            raise ValueError("self_prerequisite")
        if any(value not in available for values in prerequisites.values() for value in values):
            raise ValueError("unknown_prerequisite")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visited:
                return
            if key in visiting:
                raise ValueError("prerequisite_cycle")
            visiting.add(key)
            for prerequisite in prerequisites[key]:
                visit(prerequisite)
            visiting.remove(key)
            visited.add(key)

        for key in sorted(available):
            visit(key)
        return self


class LearningPlanToolIssue(_ToolModel):
    path: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    hint: str = Field(min_length=1, max_length=200)


class LearningPlanAgentToolResult(_ToolModel):
    status: LearningPlanToolStatus
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    issues: tuple[LearningPlanToolIssue, ...] = Field(default=(), max_length=12)
    data: Mapping[str, object] = Field(default_factory=dict)
    retry_allowed: bool = False
    replayed: bool = False
    remaining_repair_attempts: int = Field(default=0, ge=0, le=8)

    def content(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class LearningPlanToolFenceSnapshot:
    run_id: str
    conversation_id: str
    user_id: str
    input_revision: int
    lease_owner_id: str
    lease_generation: int
    runtime_generation: int
    facts_fingerprint: str
    facts_revision: int
    active: bool = True
    lease_current: bool = True
    policy_allowed: bool = True


class LearningPlanToolFence(Protocol):
    def snapshot(self) -> LearningPlanToolFenceSnapshot: ...


class PostgresLearningPlanToolFence:
    """Refresh existing Tutor run/lease/facts authority without adding new schema."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        expected: LearningPlanToolFenceSnapshot,
        runtime_generation: Callable[[], int],
        policy_allowed: Callable[[], bool] = lambda: True,
    ) -> None:
        self._conn = conn
        self._expected = expected
        self._runtime_generation = runtime_generation
        self._policy_allowed = policy_allowed
        self._sessions = PostgresLearningPlanSessionRepository(conn)
        self._facts = PostgresPlanningFactRepository(conn)

    def snapshot(self) -> LearningPlanToolFenceSnapshot:
        row = self._conn.execute(
            """
            SELECT id, user_id, conversation_id, input_revision, terminal_outcome,
                   cancelled_at, superseded_by_run_id, active_lease_owner_id,
                   active_lease_generation, active_lease_expires_at
            FROM tutor_runs
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            """,
            (self._expected.run_id, self._expected.user_id, self._expected.conversation_id),
        ).fetchone()
        if row is None:
            return replace(self._expected, active=False, lease_current=False)
        active = (
            row.get("terminal_outcome") is None
            and row.get("cancelled_at") is None
            and row.get("superseded_by_run_id") is None
        )
        expires_at = row.get("active_lease_expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        lease_current = (
            str(row.get("active_lease_owner_id") or "") == self._expected.lease_owner_id
            and _integer(row.get("active_lease_generation")) == self._expected.lease_generation
            and isinstance(expires_at, datetime)
            and (expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC))
            > datetime.now(UTC)
        )
        fingerprint = ""
        facts_revision = 0
        try:
            session = self._sessions.active_session_for_run(
                user_id=self._expected.user_id,
                run_id=self._expected.run_id,
                input_revision=_integer(row.get("input_revision")),
            )
            _, fingerprint, facts_revision, _ = self._facts.profile_fact_state(
                user_id=self._expected.user_id,
                session_id=str(session["id"]),
            )
        except LearningPlanSessionNotFound:
            active = False
        return LearningPlanToolFenceSnapshot(
            run_id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            user_id=str(row["user_id"]),
            input_revision=_integer(row.get("input_revision")),
            lease_owner_id=str(row.get("active_lease_owner_id") or ""),
            lease_generation=_integer(row.get("active_lease_generation")),
            runtime_generation=self._runtime_generation(),
            facts_fingerprint=fingerprint,
            facts_revision=facts_revision,
            active=active,
            lease_current=lease_current,
            policy_allowed=self._policy_allowed(),
        )


class LearningPlanToolService:
    """Read bounded planning authority and append one typed LearningPlan draft."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        run: TutorRunSnapshot,
        expected_fence: LearningPlanToolFenceSnapshot,
        fence: LearningPlanToolFence,
    ) -> None:
        self._conn = conn
        self._run = run
        self._expected = expected_fence
        self._fence = fence
        self._sessions = PostgresLearningPlanSessionRepository(conn)
        self._facts = PostgresPlanningFactRepository(conn)

    def read_context(self) -> LearningPlanAgentToolResult:
        fenced = self._fence_result()
        if fenced is not None:
            return fenced
        try:
            session = self._sessions.active_session_for_run(
                user_id=self._run.user_id,
                run_id=self._run.run_id,
                input_revision=self._run.input_revision,
            )
            values, fingerprint, revision, missing = self._facts.profile_fact_state(
                user_id=self._run.user_id,
                session_id=str(session["id"]),
            )
        except LearningPlanSessionNotFound:
            return _result(LearningPlanToolStatus.UNAVAILABLE, "planning_session_unavailable")
        context: dict[str, object] = {
            "schema_version": LEARNING_PLAN_TOOL_SCHEMA_VERSION,
            "confirmed_facts": [
                {"field_key": field.value, "value": values[field]}
                for field in sorted(values, key=lambda item: item.value)
            ],
            "missing_facts": [field.value for field in missing],
            "facts_revision": revision,
            "facts_fingerprint": fingerprint,
            "question_catalog_version": PLANNING_QUESTION_CATALOG_VERSION,
            "current_draft": _current_draft_summary(session),
            "constraints": {
                "scope_kind": "plan_drafting",
                "preferred_language_id": str(session.get("preferred_language_id") or "") or None,
                "module_count": {"minimum": 2, "maximum": 8},
                "nodes_per_module": {"minimum": 1, "maximum": 8},
            },
        }
        if missing:
            context["next_missing_fact"] = build_planning_question_model_descriptor(missing[0])
            return _result(
                LearningPlanToolStatus.AWAITING_USER,
                "planning_facts_missing",
                issues=tuple(
                    LearningPlanToolIssue(
                        path=f"confirmed_facts.{field.value}",
                        code="missing_fact",
                        hint="Ask the learner for this planning fact through the typed planning request.",
                    )
                    for field in missing
                ),
                data=context,
            )
        return _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready", data=context)

    def draft(self, tool_input: LearningPlanDraftToolInput) -> LearningPlanAgentToolResult:
        fenced = self._fence_result()
        if fenced is not None:
            return fenced
        try:
            with self._conn.transaction():
                session = self._sessions.active_session_for_run(
                    user_id=self._run.user_id,
                    run_id=self._run.run_id,
                    input_revision=self._run.input_revision,
                    for_update=True,
                )
                values, fingerprint, revision, missing = self._facts.profile_fact_state(
                    user_id=self._run.user_id,
                    session_id=str(session["id"]),
                )
                if missing:
                    return _result(
                        LearningPlanToolStatus.AWAITING_USER,
                        "planning_facts_missing",
                        issues=tuple(
                            LearningPlanToolIssue(
                                path=f"confirmed_facts.{field.value}",
                                code="missing_fact",
                                hint="Ask the learner for this planning fact before drafting.",
                            )
                            for field in missing
                        ),
                    )
                if (
                    fingerprint != self._expected.facts_fingerprint
                    or revision != self._expected.facts_revision
                ):
                    return _result(LearningPlanToolStatus.CONFLICT, "planning_facts_stale")
                try:
                    profile = _profile_from_facts(values)
                except (KeyError, TypeError, ValueError):
                    return _result(
                        LearningPlanToolStatus.FATAL,
                        "planning_facts_invalid",
                    )
                modules = tuple(_domain_module(module) for module in tool_input.modules)
                prior_receipt = self._sessions.draft_for_source(
                    user_id=self._run.user_id,
                    run_id=self._run.run_id,
                    input_revision=self._run.input_revision,
                )
                artifact = build_validated_learning_plan_artifact(
                    session=session,
                    profile=profile,
                    modules=modules,
                    change_reason=(
                        str(prior_receipt.get("change_reason"))
                        if prior_receipt is not None
                        else None
                    ),
                )
                fenced = self._fence_result()
                if fenced is not None:
                    return fenced
                row, replayed = self._sessions.append_draft(
                    user_id=self._run.user_id,
                    run_id=self._run.run_id,
                    input_revision=self._run.input_revision,
                    artifact=artifact,
                    facts_fingerprint=fingerprint,
                    facts_revision=revision,
                )
                receipt = hashlib.sha256(
                    f"{self._run.run_id}:{self._run.input_revision}:{row['content_hash']}".encode("utf-8")
                ).hexdigest()
                return _result(
                    LearningPlanToolStatus.COMPLETED,
                    "learning_plan_draft_completed",
                    data={
                        "draft_id": str(row["id"]),
                        "draft_version": _integer(row.get("draft_version")),
                        "content_hash": str(row["content_hash"]),
                        "module_count": len(artifact.plan.modules),
                        "node_count": len(artifact.plan.nodes),
                        "receipt": receipt,
                    },
                    replayed=replayed,
                )
        except LearningPlanDraftCapabilityError as exc:
            if exc.diagnostic_code == "learning_plan_draft_quality_blocked":
                return _repairable("modules", "plan_quality_invalid", "Use only selectable language capabilities and include core teaching coverage.")
            if exc.diagnostic_code == "learning_language_not_selectable":
                return _result(LearningPlanToolStatus.POLICY_BLOCKED, "learning_language_not_selectable")
            if exc.diagnostic_code == "learning_plan_source_quality_blocked":
                return _result(LearningPlanToolStatus.UNAVAILABLE, "learning_plan_sources_unavailable")
            if exc.diagnostic_code == "learning_plan_draft_invalid":
                return _result(LearningPlanToolStatus.CONFLICT, "planning_profile_conflict")
            return _result(LearningPlanToolStatus.FATAL, "learning_plan_tool_failed")
        except (LearningPlanDraftConflict, LearningPlanSessionConflict):
            return _result(LearningPlanToolStatus.CONFLICT, "learning_plan_draft_conflict")
        except LearningPlanSessionNotFound:
            return _result(LearningPlanToolStatus.UNAVAILABLE, "planning_session_unavailable")
        except ValueError as exc:
            return _domain_repair_result(exc)
        except Exception:
            return _result(LearningPlanToolStatus.FATAL, "learning_plan_tool_failed")

    def _fence_result(self) -> LearningPlanAgentToolResult | None:
        current = self._fence.snapshot()
        if not current.policy_allowed:
            return _result(LearningPlanToolStatus.POLICY_BLOCKED, "learning_plan_tool_policy_blocked")
        if not current.active:
            return _result(LearningPlanToolStatus.CONFLICT, "tool_run_inactive")
        if current.input_revision != self._expected.input_revision:
            return _result(LearningPlanToolStatus.CONFLICT, "tool_input_revision_stale")
        if (
            not current.lease_current
            or current.lease_owner_id != self._expected.lease_owner_id
            or current.lease_generation != self._expected.lease_generation
        ):
            return _result(LearningPlanToolStatus.CONFLICT, "tool_lease_stale")
        if current.runtime_generation != self._expected.runtime_generation:
            return _result(LearningPlanToolStatus.CONFLICT, "tool_runtime_generation_stale")
        if (
            current.facts_fingerprint != self._expected.facts_fingerprint
            or current.facts_revision != self._expected.facts_revision
        ):
            return _result(LearningPlanToolStatus.CONFLICT, "planning_facts_stale")
        return None


def build_expected_learning_plan_tool_fence(
    conn: Connection[dict[str, object]],
    *,
    run: TutorRunSnapshot,
    runtime_generation: int,
) -> LearningPlanToolFenceSnapshot:
    if run.lease is None:
        raise ValueError("learning plan tools require a current Tutor lease")
    sessions = PostgresLearningPlanSessionRepository(conn)
    facts = PostgresPlanningFactRepository(conn)
    session = sessions.active_session_for_run(
        user_id=run.user_id,
        run_id=run.run_id,
        input_revision=run.input_revision,
    )
    _, fingerprint, revision, _ = facts.profile_fact_state(
        user_id=run.user_id,
        session_id=str(session["id"]),
    )
    return LearningPlanToolFenceSnapshot(
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        user_id=run.user_id,
        input_revision=run.input_revision,
        lease_owner_id=run.lease.owner_id,
        lease_generation=run.lease.generation,
        runtime_generation=runtime_generation,
        facts_fingerprint=fingerprint,
        facts_revision=revision,
    )


def _profile_from_facts(values: Mapping[PlanningFactField, object]) -> CompactPlanProfile:
    language_id = str(values[PlanningFactField.LANGUAGE_ID])
    target_level = str(values[PlanningFactField.TARGET_LEVEL])
    return CompactPlanProfile(
        language_id=language_id,
        goal_text=str(values[PlanningFactField.GOAL_TEXT]),
        target_level=target_level,
        weekly_minutes=_integer(values[PlanningFactField.WEEKLY_MINUTES]),
        experience_level=LearningPlanExperienceLevel(
            str(values[PlanningFactField.EXPERIENCE_LEVEL])
        ),
        teaching_preferences=list(_string_sequence(values[PlanningFactField.TEACHING_PREFERENCES])),
        pace_summary=str(values[PlanningFactField.PACE_CONSTRAINTS]),
        title=f"{language_id} {target_level} 学习计划"[:240],
    )


def _domain_module(module: LearningPlanDraftModuleInput) -> CompactPlanModule:
    return CompactPlanModule(
        module_key=module.stable_key,
        title=module.title,
        description=module.description,
        is_core=module.is_core,
        is_skippable=module.is_skippable,
        nodes=[
            CompactPlanNode(
                knowledge_key=node.stable_key,
                title=node.title,
                description=node.description,
                is_core=node.is_core,
                prerequisite_keys=list(node.prerequisites),
                required_capabilities=list(node.required_capabilities),
            )
            for node in module.nodes
        ],
    )


def _current_draft_summary(session: Mapping[str, object]) -> Mapping[str, object] | None:
    if session.get("current_draft_id") is None:
        return None
    plan = session.get("plan_json")
    modules = plan.get("modules") if isinstance(plan, Mapping) else None
    module_summaries: list[dict[str, object]] = []
    if isinstance(modules, list):
        for raw in modules[:8]:
            if not isinstance(raw, Mapping):
                continue
            nodes = raw.get("nodes")
            module_summaries.append(
                {
                    "stable_key": str(raw.get("module_key") or ""),
                    "title": str(raw.get("title") or "")[:120],
                    "node_count": len(nodes) if isinstance(nodes, list) else 0,
                }
            )
    return {
        "draft_id": str(session["current_draft_id"]),
        "draft_version": _integer(session.get("draft_version")),
        "content_hash": str(session.get("content_hash") or ""),
        "modules": module_summaries,
    }


def _domain_repair_result(exc: ValueError) -> LearningPlanAgentToolResult:
    text = str(exc)
    code = "plan_structure_invalid"
    if "duplicate" in text or "unique" in text:
        code = "duplicate_stable_key"
    elif "prerequisite" in text and ("unknown" in text or "missing" in text):
        code = "unknown_prerequisite"
    elif "acyclic" in text or "cycle" in text:
        code = "prerequisite_cycle"
    elif "2..8" in text:
        code = "module_count_invalid"
    return _repairable("modules", code, "Correct the typed module graph and call the tool again.")


def _repairable(path: str, code: str, hint: str) -> LearningPlanAgentToolResult:
    return _result(
        LearningPlanToolStatus.REPAIRABLE_INVALID,
        "learning_plan_draft_invalid",
        issues=(LearningPlanToolIssue(path=path, code=code, hint=hint),),
        retry_allowed=True,
    )


def _result(
    status: LearningPlanToolStatus,
    code: str,
    *,
    issues: tuple[LearningPlanToolIssue, ...] = (),
    data: Mapping[str, object] | None = None,
    retry_allowed: bool = False,
    replayed: bool = False,
) -> LearningPlanAgentToolResult:
    return LearningPlanAgentToolResult(
        status=status,
        code=code,
        issues=issues,
        data=data or {},
        retry_allowed=retry_allowed,
        replayed=replayed,
    )


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("teaching preferences are invalid")
    return tuple(str(item) for item in value)


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
