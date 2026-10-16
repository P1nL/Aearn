"""Opt-in source-fence observations; DATA only, never grant/retry authority.

No DB operations, raw exception text, private identities or source contents.
Observer/logging failure must not change original success/None/deny semantics.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from app.core.safe_diagnostics import log_safe_event

SourceFenceStage = Literal["actual_d_epoch", "claim_resolver", "execution_resolver",
    "mapping_bind", "mapping_resolve", "rag_authorize", "rag_assert_current",
    "generation_pre_network", "generation_post_network"]
_CODES = frozenset({"epoch_scope_rejected", "epoch_lock_unavailable", "claim_resolution_denied",
    "execution_resolution_denied", "claim_missing_or_denied", "source_authorization_denied",
    "native_receipt_mode_invalid", "native_receipt_current_mismatch", "source_reason_unknown",
    "SOURCE_ACTUAL_D_SCOPE_STALE", "CLAIM_VERIFICATION_REQUIRED", "SOURCE_AUTHORIZATION_STALE",
    "SOURCE_CORPUS_STALE", "SOURCE_CAPTURE_STALE", "SOURCE_GRANT_STALE", "SOURCE_BINDING_STALE",
    "source_or_claim_stale", "mapping_missing_or_stale", "gate_closed", "confirmed_course_missing",
    "assessment_selection_pending", "frozen_node_mismatch", "assessment_binding_missing",
    "native_mapping_current_required", "source_fence_denied"})
_CLASSES = frozenset({"ValueError", "TypeError", "KeyError", "LockNotAvailable", "DeadlockDetected",
    "SerializationFailure", "EvidenceDenied", "SourceAssessmentDenied", "SourceEvidenceDenied",
    "NativeTypeEvidencePending", "ValidationError"})
_SQLSTATES = frozenset({"55P03", "40P01", "40001"})
_STAGES = frozenset({"actual_d_epoch", "claim_resolver", "execution_resolver", "mapping_bind",
    "mapping_resolve", "rag_authorize", "rag_assert_current", "generation_pre_network", "generation_post_network"})
_LOG = logging.getLogger(__name__)

@dataclass(frozen=True)
class SourceFenceObservation:
    stage: SourceFenceStage
    code: str
    exception_class: str | None
    sqlstate: str | None
    observed_at: datetime  # host observation, NOT DB clock/authorization evidence

@dataclass
class SourceFenceDiagnostics:
    _correlation_label: str = field(default_factory=lambda: uuid4().hex, init=False, repr=False)
    _observations: list[SourceFenceObservation] = field(default_factory=list, repr=False)
    diagnostic_unavailable: bool = False

    @property
    def correlation_label(self) -> str:
        return self._correlation_label

    @property
    def observations(self) -> tuple[SourceFenceObservation, ...]:
        return tuple(self._observations)

_ACTIVE: ContextVar[SourceFenceDiagnostics | None] = ContextVar("source_fence_observer", default=None)

@contextmanager
def collect_source_fence_diagnostics() -> Iterator[SourceFenceDiagnostics]:
    collector = SourceFenceDiagnostics()
    token = _ACTIVE.set(collector)
    try:
        yield collector
    finally:
        _ACTIVE.reset(token)

def observe_source_fence(stage: SourceFenceStage, code: str, exception: BaseException | None = None) -> None:
    """Consume already-observed closed DATA; no query/commit/rollback/re-authorize."""
    collector = _ACTIVE.get()
    if collector is None:
        return
    try:
        if stage not in _STAGES:
            collector.diagnostic_unavailable = True
            return
        if len(collector._observations) >= 64:
            return
        safe_code = code if code in _CODES else "source_reason_unknown"
        cls = None if exception is None else type(exception).__name__
        cls = cls if cls is None or cls in _CLASSES else "UnknownException"
        raw_state = None if exception is None else getattr(exception, "sqlstate", None)
        state = raw_state if isinstance(raw_state, str) and raw_state in _SQLSTATES else None
        collector._observations.append(SourceFenceObservation(stage, safe_code, cls, state, datetime.now(UTC)))
        # Caller whitelist intentionally excludes user/job/artifact/capture IDs and hashes.
        log_safe_event(_LOG, "source_fence_observed", stage=stage, code=safe_code,
            exception_class=cls, cause_class=None if state is None else "pg_" + state,
            run_id=collector.correlation_label)
    except Exception:
        collector.diagnostic_unavailable = True

