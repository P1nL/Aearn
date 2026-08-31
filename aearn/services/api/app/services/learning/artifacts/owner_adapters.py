"""Owner-delegation contracts for server-authoritative Learning Artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from psycopg import Connection
from pydantic import TypeAdapter

from .contracts import (
    TutorArtifactActionKind,
    TutorArtifactActionRequest,
    TutorArtifactAttemptSummaryV1,
    TutorArtifactOwnerKind,
    TutorArtifactPresentationV1,
    TutorArtifactState,
    TutorPublicArtifactItem,
    assert_public_artifact_safe,
)


_PRESENTATION_ADAPTER: TypeAdapter[TutorArtifactPresentationV1] = TypeAdapter(
    TutorArtifactPresentationV1
)


class ArtifactOwnerAdapterError(ValueError):
    """Base class for safe failures reported by an owner adapter."""


class ArtifactOwnerActionInvalid(ArtifactOwnerAdapterError):
    pass


class ArtifactOwnerScopeConflict(ArtifactOwnerAdapterError):
    pass


class ArtifactOwnerVersionConflict(ArtifactOwnerAdapterError):
    pass


class ArtifactOwnerUnavailable(ArtifactOwnerAdapterError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactMutation:
    """Complete learner-safe artifact state returned by one domain owner.

    Adapters delegate to the existing Gate, Review, or Teaching authority using the
    supplied caller-owned connection. They return only the facade state that the
    artifact repository is allowed to persist; they never return private submissions,
    rubrics, tests, provider payloads, commands, paths, or execution internals.
    """

    state: TutorArtifactState
    owner_version: int
    presentation: TutorArtifactPresentationV1
    allowed_actions: tuple[TutorArtifactActionKind, ...] = ()
    owner_context_version: int | None = None
    active_attempt: TutorArtifactAttemptSummaryV1 | None = None
    safe_event_payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            state = TutorArtifactState(str(self.state))
            presentation = _PRESENTATION_ADAPTER.validate_python(self.presentation)
            actions = tuple(
                TutorArtifactActionKind(str(item)) for item in self.allowed_actions
            )
            active_attempt = (
                TutorArtifactAttemptSummaryV1.model_validate(self.active_attempt)
                if self.active_attempt is not None
                else None
            )
        except (TypeError, ValueError) as exc:
            raise ArtifactOwnerActionInvalid(
                "artifact owner returned an invalid public mutation"
            ) from exc
        if self.owner_version < 1:
            raise ArtifactOwnerActionInvalid("artifact owner version must be positive")
        if self.owner_context_version is not None and self.owner_context_version < 1:
            raise ArtifactOwnerActionInvalid(
                "artifact owner context version must be positive"
            )
        if len(actions) != len(set(actions)):
            raise ArtifactOwnerActionInvalid("artifact owner actions must be unique")
        if state.terminal and actions:
            raise ArtifactOwnerActionInvalid(
                "terminal artifact mutations cannot expose actions"
            )
        if (
            state.terminal
            and active_attempt is not None
            and active_attempt.status != "terminal"
        ):
            raise ArtifactOwnerActionInvalid(
                "terminal artifact mutations cannot retain a pending Attempt"
            )
        if not isinstance(self.safe_event_payload, Mapping):
            raise ArtifactOwnerActionInvalid(
                "artifact owner safe event payload must be an object"
            )
        safe_event_payload = dict(self.safe_event_payload)
        try:
            assert_public_artifact_safe(safe_event_payload)
        except ValueError as exc:
            raise ArtifactOwnerActionInvalid(
                "artifact owner safe event payload is protected"
            ) from exc
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "presentation", presentation)
        object.__setattr__(self, "allowed_actions", actions)
        object.__setattr__(self, "active_attempt", active_attempt)
        object.__setattr__(self, "safe_event_payload", safe_event_payload)


class ArtifactOwnerAdapter(Protocol):
    """Short, in-transaction delegation to an existing domain authority.

    Implementations must use the supplied connection and must not call a provider,
    runner, subprocess, or other unbounded external dependency while the artifact is
    locked. Long-running work must be admitted by the owner and represented as a
    pending/running authoritative receipt instead.
    """

    @property
    def owner_kind(self) -> TutorArtifactOwnerKind: ...

    def apply_action(
        self,
        *,
        conn: Connection[dict[str, object]],
        artifact: TutorPublicArtifactItem,
        request: TutorArtifactActionRequest,
    ) -> ArtifactMutation: ...


class ArtifactOwnerAdapterRegistry:
    """Closed exact owner-kind registry with no fallback or text inference."""

    def __init__(self, adapters: Iterable[ArtifactOwnerAdapter] = ()) -> None:
        registered: dict[TutorArtifactOwnerKind, ArtifactOwnerAdapter] = {}
        for adapter in adapters:
            try:
                owner_kind = TutorArtifactOwnerKind(str(adapter.owner_kind))
            except (AttributeError, ValueError) as exc:
                raise ValueError(
                    "artifact owner adapter has an invalid owner kind"
                ) from exc
            if owner_kind in registered:
                raise ValueError(
                    f"duplicate artifact owner adapter: {owner_kind.value}"
                )
            registered[owner_kind] = adapter
        self._adapters = registered

    @property
    def owner_kinds(self) -> tuple[TutorArtifactOwnerKind, ...]:
        return tuple(sorted(self._adapters, key=lambda item: item.value))

    def require(self, owner_kind: TutorArtifactOwnerKind) -> ArtifactOwnerAdapter:
        normalized = TutorArtifactOwnerKind(str(owner_kind))
        adapter = self._adapters.get(normalized)
        if adapter is None:
            raise ArtifactOwnerUnavailable(
                f"artifact owner adapter is unavailable: {normalized.value}"
            )
        return adapter


__all__ = (
    "ArtifactMutation",
    "ArtifactOwnerActionInvalid",
    "ArtifactOwnerAdapter",
    "ArtifactOwnerAdapterError",
    "ArtifactOwnerAdapterRegistry",
    "ArtifactOwnerScopeConflict",
    "ArtifactOwnerUnavailable",
    "ArtifactOwnerVersionConflict",
)
