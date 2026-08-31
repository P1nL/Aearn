"""共享的外部依赖与持久化常量。"""
# ruff: noqa: F401
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, cast
from uuid import uuid4

from psycopg import Connection
from pydantic import ValidationError

from app.agents.harness.capabilities import EffectDescriptor, default_effect_descriptors, is_exact_semver
from app.agents.harness.contracts import (
    MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH,
    MAX_TUTOR_PUBLIC_THINKING_STEPS,
    MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH,
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorCheckpoint,
    TutorCompactionRequest,
    TutorCompactionTrigger,
    TutorContextBudgetMode,
    TutorContextBudgetPolicy,
    TutorContinuationKind,
    TutorDecision,
    TutorEffectProposal,
    TutorEffectResult,
    TutorEffectStatus,
    TutorLease,
    TutorPolicySnapshot,
    TutorProviderAttemptOutcome,
    TutorProviderAttemptReceipt,
    TutorProviderContextCapability,
    TutorRunResult,
    TutorRunOrigin,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
    TutorTurnCompletionReason,
    normalize_tutor_conversation_title,
    payload_mapping_from_fields,
)
from app.agents.harness.skill_catalog import CatalogSkillReference, SkillCatalogSnapshot
from app.core.config import get_settings
from app.core.teaching_safety import check_teaching_output, sanitize_summary_text
from app.services.learning.artifacts.contracts import TutorPublicArtifactItem
from app.services.learning.teaching_contracts import (
    TeachingAuthoritySnapshot,
    TeachingCheckpointState,
    TeachingSessionMode,
    canonical_hash as teaching_canonical_hash,
)
from app.services.learning.teaching_loop import reduce_teaching_checkpoint
from app.services.llm.contracts import LLMUsage
from app.services.tutor.conversation_contracts import (
    TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION,
    TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION,
    TUTOR_CONVERSATION_SNAPSHOT_V4_VERSION,
    TUTOR_CONVERSATION_SNAPSHOT_VERSION,
    TUTOR_CONVERSATION_STREAM_CURSOR_VERSION,
    TUTOR_PUBLIC_THINKING_STREAM_VERSION,
    TUTOR_RUNTIME_OUTPUT_VERSION,
    TutorConversationEventKind,
    TutorDispatchJobState,
    TutorInteractionProtocolVersion,
    TutorPublicTurn,
    validate_public_item,
    public_turn_status,
    validate_conversation_event_payload,
)
from app.services.learning.planning_questions import (
    PLANNING_QUESTION_CATALOG_VERSION,
    build_planning_question_presentation,
    format_planning_question_value,
    validate_planning_question_value,
)
from app.services.learning.planning_intent import PlanningIntentResolver
from app.services.tutor.interaction_requests import (
    TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION,
    TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION,
    TutorInteractionRequestActor,
    TutorInteractionRequestKind,
    TutorInteractionRequestState,
    actor_for_request,
    canonical_payload_hash,
    completion_reason_for_request,
    public_item_kind,
)
from app.services.tutor.ports import TutorLifecycleConflict, TutorLifecyclePersistence, TutorRunStore
from app.services.tutor.public_thinking_stream import (
    PUBLIC_THINKING_CHUNK_MAX_LENGTH,
    TutorPublicThinkingSink,
)
from app.services.tutor.safe_projection import TutorSafeProjection
from app.services.tutor.skill_selection import TutorSkillSelection


_DEFAULT_MEMORY_SETTING_VERSION: Final[str] = "memory_settings_v1"
_DEFAULT_RETENTION_DAYS: Final[int] = 30
_DEFAULT_STALE_DAYS: Final[int] = 7
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATUSES = frozenset(outcome.value for outcome in TutorTerminalOutcome)
_PROPOSAL_KINDS = frozenset({"context_summary", "memory_entry"})
_PROPOSAL_STATES = frozenset({"pending", "no_action", "stale", "failed"})
# Replay/export treats persisted discriminator columns as untrusted historical data.
# Keep the Child 02 vocabulary closed until a later child extends persistence and
# its safe-projection contract together.
_DURABLE_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "input_accepted",
        "skill_selected",
        "capability_invoked",
        "compaction_requested",
        "waiting_for_input",
        "interaction_request",
        "curation_proposal_recorded",
        "effect_result",
        "checkpoint_saved",
        "terminal_result",
    }
)
_TRACE_KINDS: Final[frozenset[str]] = frozenset(
    {"checkpoint", "terminal_checkpoint", "compaction_request", "waiting_result"}
)
_PUBLIC_PROCESS_VERSION: Final[str] = "tutor_public_process_v1"
_PUBLIC_PROCESS_STATES: Final[frozenset[str]] = frozenset(
    {
        "thinking",
        "waiting_input",
        "waiting_approval",
        "waiting_authority",
        "completed",
        "interrupted",
        "superseded",
        "unavailable",
        "failed",
    }
)
_PUBLIC_PROCESS_STEP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "input_received",
        "context_prepared",
        "authorized_resource_checked",
        "runtime_started",
        "domain_tool_running",
        "domain_tool_completed",
        "learning_reply_generated",
        "replaced_by_newer_input",
    }
)
_PUBLIC_PROCESS_STEP_STATES: Final[frozenset[str]] = frozenset({"completed", "current"})
_PUBLIC_PROCESS_STEP_LABELS: Final[dict[str, str]] = {
    "input_received": "已接收你的问题",
    "context_prepared": "已整理最近的对话与学习目标",
    "authorized_resource_checked": "已查阅已授权的学习资料",
    "runtime_started": "已启动受控 Agent Runtime",
    "domain_tool_running": "正在执行受控学习工具",
    "domain_tool_completed": "已完成受控学习工具",
    "learning_reply_generated": "已完成一次受控学习建议生成",
    "replaced_by_newer_input": "已根据你的新消息更新本轮处理",
}
_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS: Final[int] = 3_600
_CURSOR_VERSION: Final[int] = 1
_CONVERSATION_EVENT_CURSOR_KIND: Final[str] = "conversation-events"
_DISPATCH_JOB_LEASE_SECONDS: Final[int] = 420
_DISPATCH_JOB_MAX_ATTEMPTS: Final[int] = 5
_QUEUE_MAX_PENDING: Final[int] = 10

__all__ = (
    'annotations',
    'base64',
    'hashlib',
    'hmac',
    'json',
    're',
    'Callable',
    'Mapping',
    'Sequence',
    'dataclass',
    'UTC',
    'datetime',
    'timedelta',
    'Final',
    'Literal',
    'cast',
    'uuid4',
    'Connection',
    'ValidationError',
    'EffectDescriptor',
    'default_effect_descriptors',
    'is_exact_semver',
    'MAX_TUTOR_PUBLIC_THINKING_STEP_LENGTH',
    'MAX_TUTOR_PUBLIC_THINKING_STEPS',
    'MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH',
    'TutorCapabilityRequest',
    'TutorCapabilityResult',
    'TutorCapabilityStatus',
    'TutorCheckpoint',
    'TutorCompactionRequest',
    'TutorCompactionTrigger',
    'TutorContextBudgetMode',
    'TutorContextBudgetPolicy',
    'TutorContinuationKind',
    'TutorDecision',
    'TutorEffectProposal',
    'TutorEffectResult',
    'TutorEffectStatus',
    'TutorLease',
    'TutorPolicySnapshot',
    'TutorProviderAttemptOutcome',
    'TutorProviderAttemptReceipt',
    'TutorProviderContextCapability',
    'TutorRunResult',
    'TutorRunOrigin',
    'TutorRunSnapshot',
    'TutorRunStatus',
    'TutorTerminalOutcome',
    'TutorTurnCompletionReason',
    'normalize_tutor_conversation_title',
    'payload_mapping_from_fields',
    'CatalogSkillReference',
    'SkillCatalogSnapshot',
    'get_settings',
    'check_teaching_output',
    'sanitize_summary_text',
    'TutorPublicArtifactItem',
    'TeachingAuthoritySnapshot',
    'TeachingCheckpointState',
    'TeachingSessionMode',
    'teaching_canonical_hash',
    'reduce_teaching_checkpoint',
    'LLMUsage',
    'TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION',
    'TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION',
    'TUTOR_CONVERSATION_SNAPSHOT_V4_VERSION',
    'TUTOR_CONVERSATION_SNAPSHOT_VERSION',
    'TUTOR_CONVERSATION_STREAM_CURSOR_VERSION',
    'TUTOR_PUBLIC_THINKING_STREAM_VERSION',
    'TUTOR_RUNTIME_OUTPUT_VERSION',
    'TutorConversationEventKind',
    'TutorDispatchJobState',
    'TutorInteractionProtocolVersion',
    'TutorPublicTurn',
    'validate_public_item',
    'public_turn_status',
    'validate_conversation_event_payload',
    'PLANNING_QUESTION_CATALOG_VERSION',
    'build_planning_question_presentation',
    'format_planning_question_value',
    'validate_planning_question_value',
    'PlanningIntentResolver',
    'TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION',
    'TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION',
    'TutorInteractionRequestActor',
    'TutorInteractionRequestKind',
    'TutorInteractionRequestState',
    'actor_for_request',
    'canonical_payload_hash',
    'completion_reason_for_request',
    'public_item_kind',
    'TutorLifecycleConflict',
    'TutorLifecyclePersistence',
    'TutorRunStore',
    'PUBLIC_THINKING_CHUNK_MAX_LENGTH',
    'TutorPublicThinkingSink',
    'TutorSafeProjection',
    'TutorSkillSelection',
    '_DEFAULT_MEMORY_SETTING_VERSION',
    '_DEFAULT_RETENTION_DAYS',
    '_DEFAULT_STALE_DAYS',
    '_SAFE_KEY',
    '_SHA256',
    '_TERMINAL_STATUSES',
    '_PROPOSAL_KINDS',
    '_PROPOSAL_STATES',
    '_DURABLE_EVENT_KINDS',
    '_TRACE_KINDS',
    '_PUBLIC_PROCESS_VERSION',
    '_PUBLIC_PROCESS_STATES',
    '_PUBLIC_PROCESS_STEP_KEYS',
    '_PUBLIC_PROCESS_STEP_STATES',
    '_PUBLIC_PROCESS_STEP_LABELS',
    '_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS',
    '_CURSOR_VERSION',
    '_CONVERSATION_EVENT_CURSOR_KIND',
    '_DISPATCH_JOB_LEASE_SECONDS',
    '_DISPATCH_JOB_MAX_ATTEMPTS',
    '_QUEUE_MAX_PENDING',
)
