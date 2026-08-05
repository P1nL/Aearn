"""Read-only LearningTrack context seam for the Tutor Harness."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from psycopg import Connection

from app.agents.harness.contracts import TutorContextSource
from app.services.learning.contracts import LearningScopeKind
from app.services.learning.track_repository import PostgresLearningTrackRepository, ScopeSnapshot


@dataclass(frozen=True, slots=True)
class TutorLearningContext:
    scope: ScopeSnapshot
    sources: tuple[TutorContextSource, ...]


class TutorLearningContextAdapter:
    """Build bounded authoritative context without changing prompt priority or provider behavior."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._repository = PostgresLearningTrackRepository(conn)

    def load(self, *, user_id: str, run_id: str) -> TutorLearningContext:
        scope = self._repository.read_run_scope(user_id=user_id, run_id=run_id)
        scope_source = TutorContextSource(
            source_id=f"learning-scope:{run_id}",
            content={
                "scope_kind": scope.scope_kind.value,
                "task_kind": scope.task_kind.value,
                "learning_track_id": scope.learning_track_id,
                "knowledge_key": scope.knowledge_key,
                "scope_version": scope.scope_version,
            },
        )
        if scope.scope_kind is not LearningScopeKind.LEARNING_TRACK or scope.learning_track_id is None:
            return TutorLearningContext(scope=scope, sources=(scope_source,))

        track = self._repository.read_track(user_id=user_id, track_id=scope.learning_track_id)
        roadmap = self._repository.read_roadmap(user_id=user_id, track_id=scope.learning_track_id)
        current_key = scope.knowledge_key or (
            str(track["current_knowledge_key"]) if track.get("current_knowledge_key") is not None else None
        )
        current_node: Mapping[str, object] | None = None
        modules = roadmap.get("modules")
        if not isinstance(modules, list | tuple):
            modules = ()
        for module in modules:
            if not isinstance(module, Mapping):
                continue
            nodes = module.get("nodes")
            if not isinstance(nodes, list | tuple):
                continue
            for node in nodes:
                if isinstance(node, Mapping) and node.get("knowledge_key") == current_key:
                    current_node = node
                    break
            if current_node is not None:
                break
        track_source = TutorContextSource(
            source_id=f"learning-track:{scope.learning_track_id}",
            content={
                "language_id": str(track["language_id"]),
                "goal_text": str(track["goal_text"]),
                "target_level": str(track["target_level"]),
                "track_version": _int(track["version"]),
                "active_revision_id": str(track["active_revision_id"]),
                "active_plan_title": str(track["active_plan_title"]),
                "current_knowledge_key": current_key,
            },
        )
        sources: list[TutorContextSource] = [scope_source, track_source]
        if current_node is not None:
            sources.append(
                TutorContextSource(
                    source_id=f"learning-node:{current_key}",
                    content={
                        "knowledge_key": current_node["knowledge_key"],
                        "title": current_node["title"],
                        "progress_status": current_node["progress_status"],
                        "mastery_level": current_node["mastery_level"],
                        "mastery_confidence": current_node["mastery_confidence"],
                        "prerequisite_keys": current_node["prerequisite_keys"],
                    },
                )
            )
        return TutorLearningContext(scope=scope, sources=tuple(sources))


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0
