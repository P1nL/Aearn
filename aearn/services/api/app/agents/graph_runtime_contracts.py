"""Shared graph runtime contracts for LangGraph orchestration.

Defines state, intent, result, and fallback types shared across
learning, onboarding, and review graph modules. Graph nodes produce
intents; service layers execute them against repositories.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum


MAX_USER_TEXT_LENGTH = 4000
MAX_SUMMARY_LENGTH = 2000
MAX_ID_LENGTH = 80
MAX_ERROR_LENGTH = 160
MAX_INTENT_PAYLOAD_KEYS = 20
MAX_INTENTS_PER_RUN = 10
MAX_ERRORS_PER_RUN = 5
MAX_DIAGNOSTICS_LENGTH = 500
MAX_THREAD_ID_LENGTH = 120
MAX_CHECKPOINT_NS_LENGTH = 80
MAX_THREAD_METADATA_KEYS = 20
MAX_PROFILE_SUMMARY_LENGTH = 2000
MAX_MEMORY_SOURCE_LENGTH = 80
MAX_RAG_QUERY_LENGTH = 500
MAX_RAG_CHUNKS = 4
MAX_RAG_CHUNK_TITLE_LENGTH = 160
MAX_RAG_CHUNK_CONTENT_LENGTH = 1200
MAX_RAG_CHUNK_TYPE_LENGTH = 40
MAX_RAG_SOURCE_URL_LENGTH = 300
MAX_RAG_STATUS_LENGTH = 40

REDACTED_FIELDS = frozenset({
    "solution_reference",
    "hidden_tests",
    "hidden_test_source",
    "raw_prompt",
    "system_prompt",
    "provider_payload",
    "api_key",
    "secret",
    "auth_token",
    "stack_trace",
    "traceback",
})

REDACTED_CONTENT_MARKERS = (
    "solution_reference",
    "solution reference",
    "hidden_test",
    "hidden test",
    "raw_prompt",
    "raw prompt",
    "system prompt",
    "api_key",
    "api key",
    "secret_key",
    "secret key",
    "auth_token",
    "auth token",
    "provider payload",
    "provider error",
)


class IntentType(str, Enum):
    STAGE_UPDATE = "stage_update"
    TOOL_CALL = "tool_call"
    FEEDBACK_REQUEST = "feedback_request"
    PERSISTENCE = "persistence"
    PROFILE_UPDATE = "profile_update"
    SIDE_EFFECT = "side_effect"


class GraphRuntimeLayer(str, Enum):
    GRAPH = "graph"
    SERVICE = "service"
    REPOSITORY = "repository"
    API = "api"
    SSE = "sse"


@dataclass(frozen=True)
class GraphIntent:
    intent_type: IntentType
    target: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_type": self.intent_type.value,
            "target": self.target,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class GraphRuntimeState:
    session_id: str
    user_id: str
    session_type: str
    current_stage: str
    user_text: str
    context_summary: str = ""
    scoped_ids: Mapping[str, str] = field(default_factory=dict)
    session_facts: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "session_type": self.session_type,
            "current_stage": self.current_stage,
            "user_text": self.user_text,
            "context_summary": self.context_summary,
            "scoped_ids": dict(self.scoped_ids),
            "session_facts": dict(self.session_facts),
        }


@dataclass(frozen=True)
class GraphMemorySnapshot:
    profile_summary: str = ""
    source: str = "learner_profile"
    available: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_summary": self.profile_summary,
            "source": self.source,
            "available": self.available,
        }


@dataclass(frozen=True)
class GraphRagChunk:
    chunk_id: str
    chunk_type: str
    title: str
    content: str
    source_url: str | None = None
    relevance_rank: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "chunk_type": self.chunk_type,
            "title": self.title,
            "content": self.content,
            "source_url": self.source_url,
            "relevance_rank": self.relevance_rank,
        }


@dataclass(frozen=True)
class GraphRagContext:
    knowledge_point_id: str
    query: str
    retrieval_status: str
    source_scope: str = "knowledge_point"
    chunks: tuple[GraphRagChunk, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "knowledge_point_id": self.knowledge_point_id,
            "query": self.query,
            "retrieval_status": self.retrieval_status,
            "source_scope": self.source_scope,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }


@dataclass(frozen=True)
class GraphCheckpointThreadState:
    thread_id: str
    checkpoint_ns: str
    checkpoint_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_config(self) -> dict[str, object]:
        configurable: dict[str, object] = {
            "thread_id": self.thread_id,
            "checkpoint_ns": self.checkpoint_ns,
        }
        if self.checkpoint_id:
            configurable["checkpoint_id"] = self.checkpoint_id
        config: dict[str, object] = {"configurable": configurable}
        if self.metadata:
            config["metadata"] = dict(self.metadata)
        return config

    def to_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "checkpoint_ns": self.checkpoint_ns,
            "checkpoint_id": self.checkpoint_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphRunResult:
    next_stage: str
    intents: tuple[GraphIntent, ...] = ()
    diagnostics: str = ""
    safe_context: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "next_stage": self.next_stage,
            "intents": [intent.to_dict() for intent in self.intents],
            "diagnostics": self.diagnostics,
            "safe_context": dict(self.safe_context),
        }


@dataclass(frozen=True)
class GraphFallback:
    reason: str
    fallback_stage: str
    safe_message: str = ""
    recoverable: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "fallback_stage": self.fallback_stage,
            "safe_message": self.safe_message,
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True)
class GraphLayerResponsibility:
    layer: GraphRuntimeLayer
    owns: tuple[str, ...]
    does_not_own: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "layer": self.layer.value,
            "owns": list(self.owns),
            "does_not_own": list(self.does_not_own),
        }


@dataclass(frozen=True)
class GraphIntentBoundaryRule:
    intent_type: IntentType
    produced_by: GraphRuntimeLayer
    consumed_by: GraphRuntimeLayer
    durable_write_request: bool = False
    public_api_visible: bool = False
    sse_visible: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_type": self.intent_type.value,
            "produced_by": self.produced_by.value,
            "consumed_by": self.consumed_by.value,
            "durable_write_request": self.durable_write_request,
            "public_api_visible": self.public_api_visible,
            "sse_visible": self.sse_visible,
        }


@dataclass(frozen=True)
class GraphRuntimeBoundaryContract:
    responsibilities: tuple[GraphLayerResponsibility, ...]
    intent_rules: tuple[GraphIntentBoundaryRule, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "responsibilities": [item.to_dict() for item in self.responsibilities],
            "intent_rules": [item.to_dict() for item in self.intent_rules],
        }


GRAPH_RUNTIME_BOUNDARY_CONTRACT = GraphRuntimeBoundaryContract(
    responsibilities=(
        GraphLayerResponsibility(
            layer=GraphRuntimeLayer.GRAPH,
            owns=(
                "routing_decisions",
                "stage_transitions",
                "next_action_selection",
                "typed_intent_production",
            ),
            does_not_own=(
                "database_connections",
                "repository_writes",
                "idempotency_records",
                "public_api_envelopes",
                "sse_frame_order",
            ),
        ),
        GraphLayerResponsibility(
            layer=GraphRuntimeLayer.SERVICE,
            owns=(
                "graph_invocation",
                "boundary_validation",
                "intent_execution",
                "durable_write_orchestration",
                "idempotency_replay",
                "stable_fallback",
            ),
            does_not_own=("sql_invariants", "raw_sse_frames"),
        ),
        GraphLayerResponsibility(
            layer=GraphRuntimeLayer.REPOSITORY,
            owns=("sql", "transactions", "persistence_invariants"),
            does_not_own=("graph_routing", "public_response_rendering"),
        ),
        GraphLayerResponsibility(
            layer=GraphRuntimeLayer.API,
            owns=("request_validation", "response_envelopes", "http_mode_selection"),
            does_not_own=("graph_internals", "repository_writes"),
        ),
        GraphLayerResponsibility(
            layer=GraphRuntimeLayer.SSE,
            owns=("event_names", "frame_order", "bounded_public_payloads"),
            does_not_own=("graph_diagnostics", "raw_provider_errors"),
        ),
    ),
    intent_rules=(
        GraphIntentBoundaryRule(
            intent_type=IntentType.STAGE_UPDATE,
            produced_by=GraphRuntimeLayer.GRAPH,
            consumed_by=GraphRuntimeLayer.SERVICE,
            durable_write_request=True,
            public_api_visible=True,
        ),
        GraphIntentBoundaryRule(
            intent_type=IntentType.TOOL_CALL,
            produced_by=GraphRuntimeLayer.GRAPH,
            consumed_by=GraphRuntimeLayer.SERVICE,
            public_api_visible=True,
            sse_visible=True,
        ),
        GraphIntentBoundaryRule(
            intent_type=IntentType.FEEDBACK_REQUEST,
            produced_by=GraphRuntimeLayer.GRAPH,
            consumed_by=GraphRuntimeLayer.SERVICE,
            public_api_visible=True,
            sse_visible=True,
        ),
        GraphIntentBoundaryRule(
            intent_type=IntentType.PERSISTENCE,
            produced_by=GraphRuntimeLayer.GRAPH,
            consumed_by=GraphRuntimeLayer.SERVICE,
            durable_write_request=True,
        ),
        GraphIntentBoundaryRule(
            intent_type=IntentType.PROFILE_UPDATE,
            produced_by=GraphRuntimeLayer.GRAPH,
            consumed_by=GraphRuntimeLayer.SERVICE,
            durable_write_request=True,
        ),
        GraphIntentBoundaryRule(
            intent_type=IntentType.SIDE_EFFECT,
            produced_by=GraphRuntimeLayer.GRAPH,
            consumed_by=GraphRuntimeLayer.SERVICE,
            durable_write_request=True,
        ),
    ),
)


def graph_runtime_boundary_contract() -> GraphRuntimeBoundaryContract:
    return GRAPH_RUNTIME_BOUNDARY_CONTRACT


def boundary_rule_for_intent_type(intent_type: IntentType) -> GraphIntentBoundaryRule | None:
    for rule in GRAPH_RUNTIME_BOUNDARY_CONTRACT.intent_rules:
        if rule.intent_type == intent_type:
            return rule
    return None


# --- State construction ---


def build_runtime_state(
    *,
    session_id: str,
    user_id: str,
    session_type: str,
    current_stage: str,
    user_text: str,
    context_summary: str = "",
    scoped_ids: Mapping[str, str] | None = None,
    session_facts: Mapping[str, object] | None = None,
) -> GraphRuntimeState:
    return GraphRuntimeState(
        session_id=_bound_id(session_id),
        user_id=_bound_id(user_id),
        session_type=_bound_id(session_type),
        current_stage=_bound_id(current_stage),
        user_text=_bound_text(user_text, MAX_USER_TEXT_LENGTH),
        context_summary=_bound_text(context_summary, MAX_SUMMARY_LENGTH),
        scoped_ids=_bound_id_mapping(scoped_ids or {}),
        session_facts=_redact_mapping(session_facts or {}),
    )


def build_graph_memory_snapshot(
    *,
    profile_summary: str = "",
    source: str = "learner_profile",
) -> GraphMemorySnapshot:
    safe_summary = _bound_text(str(redact_value(profile_summary)), MAX_PROFILE_SUMMARY_LENGTH)
    return GraphMemorySnapshot(
        profile_summary=safe_summary,
        source=_bound_text(source, MAX_MEMORY_SOURCE_LENGTH),
        available=bool(safe_summary),
    )


def build_graph_rag_context(
    *,
    knowledge_point_id: str,
    query: str,
    chunks: Sequence[Mapping[str, object]] = (),
    retrieval_status: str | None = None,
    source_scope: str = "knowledge_point",
) -> GraphRagContext:
    safe_chunks = tuple(_build_graph_rag_chunk(chunk) for chunk in chunks[:MAX_RAG_CHUNKS])
    status = retrieval_status or ("available" if safe_chunks else "empty")
    return GraphRagContext(
        knowledge_point_id=_bound_id(knowledge_point_id),
        query=_bound_text(str(redact_value(query)), MAX_RAG_QUERY_LENGTH),
        retrieval_status=_bound_text(status, MAX_RAG_STATUS_LENGTH),
        source_scope=_bound_text(source_scope, MAX_RAG_STATUS_LENGTH),
        chunks=safe_chunks,
    )


def build_checkpoint_thread_state(
    *,
    session_id: str,
    user_id: str,
    session_type: str,
    checkpoint_ns: str = "learning",
    checkpoint_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> GraphCheckpointThreadState:
    safe_session_id = _bound_id(session_id)
    safe_user_id = _bound_id(user_id)
    safe_session_type = _bound_id(session_type)
    safe_metadata = _redact_mapping(metadata or {}, max_keys=MAX_THREAD_METADATA_KEYS)
    safe_metadata.update({
        "session_id": safe_session_id,
        "session_type": safe_session_type,
        "user_id": safe_user_id,
        "durable_state_owner": GraphRuntimeLayer.SERVICE.value,
    })
    return GraphCheckpointThreadState(
        thread_id=_stable_thread_id(session_type=safe_session_type, session_id=safe_session_id),
        checkpoint_ns=_bound_text(checkpoint_ns, MAX_CHECKPOINT_NS_LENGTH),
        checkpoint_id=_bound_text(checkpoint_id, MAX_ID_LENGTH) if checkpoint_id else None,
        metadata=safe_metadata,
    )


def _build_graph_rag_chunk(chunk: Mapping[str, object]) -> GraphRagChunk:
    source_url = chunk.get("source_url")
    return GraphRagChunk(
        chunk_id=_bound_id(str(chunk.get("chunk_id") or "")),
        chunk_type=_bound_text(str(chunk.get("chunk_type") or ""), MAX_RAG_CHUNK_TYPE_LENGTH),
        title=_bound_text(str(redact_value(str(chunk.get("title") or ""))), MAX_RAG_CHUNK_TITLE_LENGTH),
        content=_bound_text(str(redact_value(str(chunk.get("content") or ""))), MAX_RAG_CHUNK_CONTENT_LENGTH),
        source_url=_bound_text(str(source_url), MAX_RAG_SOURCE_URL_LENGTH) if source_url else None,
        relevance_rank=_as_float(chunk.get("relevance_rank"), 0.0),
    )


# --- Intent construction ---


def make_intent(
    intent_type: IntentType,
    target: str,
    payload: Mapping[str, object] | None = None,
) -> GraphIntent:
    safe_payload = _redact_mapping(payload or {}, max_keys=MAX_INTENT_PAYLOAD_KEYS)
    return GraphIntent(
        intent_type=intent_type,
        target=_bound_text(target, MAX_ID_LENGTH),
        payload=safe_payload,
    )


# --- Result construction ---


def build_run_result(
    *,
    next_stage: str,
    intents: Sequence[GraphIntent] = (),
    diagnostics: str = "",
    safe_context: Mapping[str, object] | None = None,
) -> GraphRunResult:
    bounded_intents = tuple(intents[:MAX_INTENTS_PER_RUN])
    return GraphRunResult(
        next_stage=_bound_text(next_stage, MAX_ID_LENGTH),
        intents=bounded_intents,
        diagnostics=_bound_text(diagnostics, MAX_DIAGNOSTICS_LENGTH),
        safe_context=_redact_mapping(safe_context or {}),
    )


# --- Fallback construction ---


def build_fallback(
    *,
    reason: str,
    fallback_stage: str,
    safe_message: str = "",
    recoverable: bool = True,
) -> GraphFallback:
    return GraphFallback(
        reason=_redact_error(reason),
        fallback_stage=_bound_text(fallback_stage, MAX_ID_LENGTH),
        safe_message=_bound_text(safe_message, MAX_ERROR_LENGTH),
        recoverable=recoverable,
    )


# --- Validation ---


def validate_intents(intents: Sequence[GraphIntent]) -> list[str]:
    errors: list[str] = []
    if len(intents) > MAX_INTENTS_PER_RUN:
        errors.append(f"too many intents: {len(intents)} > {MAX_INTENTS_PER_RUN}")
    for i, intent in enumerate(intents):
        if not intent.target:
            errors.append(f"intent[{i}] has empty target")
        if intent.intent_type not in IntentType:
            errors.append(f"intent[{i}] has invalid type")
    return errors


def validate_run_result(result: GraphRunResult) -> list[str]:
    errors: list[str] = []
    if not result.next_stage:
        errors.append("run result has empty next_stage")
    errors.extend(validate_intents(result.intents))
    return errors


def validate_run_result_for_boundary(
    result: GraphRunResult,
    *,
    allowed_intent_targets: Mapping[IntentType, Sequence[str]] | None = None,
) -> list[str]:
    errors = validate_run_result(result)
    errors.extend(validate_boundary_intents(result.intents, allowed_intent_targets=allowed_intent_targets))
    return errors


def validate_boundary_intents(
    intents: Sequence[GraphIntent],
    *,
    allowed_intent_targets: Mapping[IntentType, Sequence[str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    allowed_targets = allowed_intent_targets or {}
    for i, intent in enumerate(intents):
        rule = boundary_rule_for_intent_type(intent.intent_type)
        if rule is None:
            errors.append(f"intent[{i}] has no boundary rule for {intent.intent_type}")
            continue
        if rule.produced_by != GraphRuntimeLayer.GRAPH:
            errors.append(f"intent[{i}] is not graph-produced")
        if rule.consumed_by != GraphRuntimeLayer.SERVICE:
            errors.append(f"intent[{i}] is not service-consumed")
        if allowed_intent_targets is not None and intent.intent_type not in allowed_targets:
            errors.append(f"intent[{i}] type {intent.intent_type.value} is not allowed in this service scope")
            continue
        targets = allowed_targets.get(intent.intent_type)
        if targets is not None and intent.target not in set(targets):
            errors.append(
                f"intent[{i}] target {intent.target!r} is not allowed for {intent.intent_type.value}",
            )
    return errors


# --- Redaction and sanitization ---


def redact_value(value: object) -> object:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [redact_value(item) for item in value[:20]]
    return value


def _redact_mapping(
    mapping: Mapping[str, object],
    *,
    max_keys: int = 50,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for i, (key, value) in enumerate(mapping.items()):
        if i >= max_keys:
            break
        if key.lower() in REDACTED_FIELDS:
            result[key] = "[REDACTED]"
            continue
        result[key] = redact_value(value)
    return result


def _redact_string(value: str) -> str:
    lowered = value.lower()
    for marker in REDACTED_CONTENT_MARKERS:
        if marker in lowered:
            return "[REDACTED: contains sensitive content]"
    return value


def _redact_error(error: str) -> str:
    bounded = _bound_text(error, MAX_ERROR_LENGTH)
    lowered = bounded.lower()
    if any(marker in lowered for marker in ("traceback", "stack_trace", "api_key", "secret")):
        return "internal error (details redacted)"
    return bounded


# --- Bounding helpers ---


def _bound_text(value: str, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[:max_length]


def _bound_id(value: str) -> str:
    return _bound_text(value, MAX_ID_LENGTH)


def _stable_thread_id(*, session_type: str, session_id: str) -> str:
    raw_thread_id = f"aearn:{session_type}:{session_id}"
    if len(raw_thread_id) <= MAX_THREAD_ID_LENGTH:
        return raw_thread_id
    digest = hashlib.sha256(raw_thread_id.encode("utf-8")).hexdigest()[:20]
    prefix = _bound_text(f"aearn:{session_type}", MAX_THREAD_ID_LENGTH - len(digest) - 1)
    return f"{prefix}:{digest}"


def _bound_id_mapping(mapping: Mapping[str, str]) -> dict[str, str]:
    return {
        _bound_id(key): _bound_id(str(value))
        for key, value in list(mapping.items())[:20]
    }


def _as_float(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default
