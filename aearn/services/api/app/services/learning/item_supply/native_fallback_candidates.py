"""Explicit fallback advertisement delegates to the ORIGINAL native builder.

Only the selected original PUBLIC practice is advertised. The private union is
reissued in this transaction, never retained through the Primary network call.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg import Connection

from app.core.config import Settings
from app.services.learning.item_supply.native_fallback_delivery import NativeTeachingWholeBaseFallbackContext
from app.services.learning.teaching_candidates import (
    NativeTeachingArtifactCandidateBuilder, TeachingArtifactCandidateBuilder,
    TeachingArtifactCandidateBuildError, _PublishedCandidateRepository,
)
from app.services.learning.teaching_contracts import TeachingArtifactCandidateScope, TeachingArtifactCandidateSet


class NativeFallbackTeachingArtifactCandidateBuilder(NativeTeachingArtifactCandidateBuilder):
    def __init__(self, repository: _PublishedCandidateRepository, *,
                 conn: Connection[dict[str, Any]], settings: Settings) -> None:
        super().__init__(repository, conn=conn, settings=settings)
        self._fallback_runs: dict[str, NativeTeachingWholeBaseFallbackContext] = {}

    def register_fallback_delivery(self, *, run_id: str,
                                   context: NativeTeachingWholeBaseFallbackContext) -> None:
        if (type(context) is not NativeTeachingWholeBaseFallbackContext
                or context.private_service.conn is not self.conn or context.private_service.settings is not self.settings):
            raise TeachingArtifactCandidateBuildError('fallback candidate concrete same-connection context required')
        try:
            context._binding(run_id)
        except ValueError as exc:
            raise TeachingArtifactCandidateBuildError('fallback candidate exact run required') from exc
        existing = self._fallback_runs.get(run_id)
        if existing is not None and existing is not context:
            raise TeachingArtifactCandidateBuildError('fallback candidate run is already bound')
        self.register_delivery(run_id=run_id, context=context.native_context)
        self._fallback_runs[run_id] = context

    def for_run(self, run_id: str) -> TeachingArtifactCandidateBuilder:
        original = super().for_run(run_id)
        context = self._fallback_runs.get(run_id)
        if context is None:
            return original
        return _FallbackRunCandidates(original, parent=self, run_id=run_id, context=context)


class _FallbackRunCandidates(TeachingArtifactCandidateBuilder):
    def __init__(self, original: TeachingArtifactCandidateBuilder, *,
                 parent: NativeFallbackTeachingArtifactCandidateBuilder, run_id: str,
                 context: NativeTeachingWholeBaseFallbackContext) -> None:
        super().__init__(original._repository)
        self.original, self.parent, self.run_id, self.context = original, parent, run_id, context

    def build(self, *, scope: TeachingArtifactCandidateScope,
              available_capabilities: Sequence[str], learning_artifacts_enabled: bool,
              artifact_teaching_enabled: bool, required_handles: Sequence[str] = (),
              excluded_purposes: Sequence[str] = ('remediation', 'transfer_check'),
              catalog_knowledge_key: str | None = None) -> TeachingArtifactCandidateSet:
        if not learning_artifacts_enabled or not artifact_teaching_enabled:
            return TeachingArtifactCandidateSet(scope=scope, feature_enabled=False)
        try:
            self.parent.register_fallback_delivery(run_id=self.run_id, context=self.context)
            self.context.require_current(run_id=self.run_id, stage='advertise')
            result = self.original.build(scope=scope, available_capabilities=available_capabilities,
                learning_artifacts_enabled=learning_artifacts_enabled, artifact_teaching_enabled=artifact_teaching_enabled,
                required_handles=required_handles, excluded_purposes=excluded_purposes,
                catalog_knowledge_key=catalog_knowledge_key)
            self.context.require_current(run_id=self.run_id, stage='advertise')
        except ValueError as exc:
            raise TeachingArtifactCandidateBuildError('fallback candidate current whole-base union unavailable') from exc
        return result

