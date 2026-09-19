from __future__ import annotations

import pytest

from app.services.learning.teaching_contracts import (
    TeachingFocusResolution,
    teaching_focus_resolution_error,
)


@pytest.mark.parametrize(
    ("resolution", "focus_id", "parents", "expected"),
    [
        ("push_child", "candidate", (), None),
        ("push_child", "objective", (), "teaching_child_focus_invalid"),
        ("stay", "active", (), None),
        ("stay", "candidate", (), None),
        ("stay", "unknown", (), "teaching_active_focus_invalid"),
        ("resolve_and_resume_parent", "active", (), "teaching_parent_focus_invalid"),
        ("resolve_and_resume_parent", "parent", ("parent",), None),
        ("resolve_and_resume_parent", "other", ("parent",), "teaching_parent_focus_invalid"),
        ("replace_objective", "objective", (), None),
        ("replace_objective", "candidate", (), None),
        ("replace_objective", "unknown", (), "teaching_replacement_focus_invalid"),
        ("wait", "active", (), None),
        ("wait", "candidate", (), None),
        ("wait", "unknown", (), "teaching_wait_focus_invalid"),
        ("abandon_branch", "active", ("parent",), None),
        ("abandon_branch", "parent", ("parent",), "teaching_abandoned_focus_invalid"),
    ],
)
def test_focus_authority_preserves_final_gate_matrix(
    resolution: str, focus_id: str, parents: tuple[str, ...], expected: str | None,
) -> None:
    assert teaching_focus_resolution_error(
        resolution=TeachingFocusResolution(resolution), focus_id=focus_id,
        objective_id="objective", active_focus_id="active", candidate_focus_id="candidate",
        suspended_focus_ids=parents,
    ) == expected
