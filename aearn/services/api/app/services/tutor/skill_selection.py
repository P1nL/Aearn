"""Run-local, non-durable Skill selection evidence for the Harness seam."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agents.harness.skill_catalog import CatalogSkillReference


@dataclass(frozen=True)
class TutorSkillSelection:
    reference: CatalogSkillReference
    manifest_hash: str
    instruction_hash: str

    def __post_init__(self) -> None:
        for value in (self.manifest_hash, self.instruction_hash):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("Skill selection hashes must be SHA-256 hex values")


class TutorSkillSelectionStore(Protocol):
    def get(self, *, run_id: str, input_revision: int) -> TutorSkillSelection | None: ...

    def record(
        self,
        *,
        run_id: str,
        input_revision: int,
        selection: TutorSkillSelection,
    ) -> None: ...


class InMemoryTutorSkillSelectionStore:
    """A deterministic Child 01 fake; later work replaces it with replay storage."""

    def __init__(self) -> None:
        self._selections: dict[tuple[str, int], TutorSkillSelection] = {}
        self.records: list[tuple[str, int, TutorSkillSelection]] = []

    def get(self, *, run_id: str, input_revision: int) -> TutorSkillSelection | None:
        return self._selections.get((run_id, input_revision))

    def record(
        self,
        *,
        run_id: str,
        input_revision: int,
        selection: TutorSkillSelection,
    ) -> None:
        key = (run_id, input_revision)
        self._selections[key] = selection
        self.records.append((run_id, input_revision, selection))