"""Offline immutable migration projections and stale/replay checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

import pytest
from psycopg import Connection

from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.plan_coverage import PlanCoveragePreflightService, PlanPreflightConflict
from app.services.learning.plan_migration import ExistingTrackMigrationPlanner
from tests.learning.test_rag_plan_preflight import FakeFacts, plan, requirement

USER_ID = str(UUID("00000000-0000-0000-0000-000000000021"))
TRACK_ID = str(UUID("00000000-0000-0000-0000-000000000022"))
REVISION_ID = str(UUID("00000000-0000-0000-0000-000000000023"))


@dataclass
class ReadOnlyConnection:
    row: dict[str, object]
    statements: list[str] = field(default_factory=list)

    def execute(self, sql: str, args: object) -> ReadOnlyConnection:
        self.statements.append(sql)
        assert args == (TRACK_ID, USER_ID)
        assert sql.lstrip().startswith("SELECT")
        assert "FOR UPDATE" not in sql.upper()
        return self

    def fetchone(self) -> dict[str, object]:
        return self.row


def _conn() -> ReadOnlyConnection:
    draft = plan(key="lc-overview")
    return ReadOnlyConnection({
        "id": REVISION_ID, "content_hash": draft.content_hash,
        "title": draft.title, "target_level": draft.target_level,
        "generator_version": draft.generator_version,
        "policy_version": draft.policy_version,
        "change_reason": draft.change_reason,
        "plan_json": canonical_plan_payload(draft),
    })


def test_existing_langchain_track_waits_and_replays_without_mutation() -> None:
    conn = _conn()
    planner = ExistingTrackMigrationPlanner(
        cast(Connection[dict[str, object]], conn),
        PlanCoveragePreflightService(FakeFacts(status="insufficient", synthetic=True)),
    )
    kwargs = {
        "user_id": USER_ID, "track_id": TRACK_ID,
        "expected_revision_id": REVISION_ID,
        "expected_plan_hash": conn.row["content_hash"],
        "requirements": (requirement(
            key="lc-overview", subject="python.ai-applications", facets=("langchain-core",),
        ),),
    }
    first = planner.propose(**kwargs)  # type: ignore[arg-type]
    second = planner.propose(**kwargs)  # type: ignore[arg-type]
    assert first == second
    assert first.predecessor_revision_id == REVISION_ID
    assert first.state == "blocked" and first.activation_allowed is False
    assert first.node_diffs[0].action == "wait_for_release"
    assert first.node_diffs[0].before_subject_id == "python.ai-applications"
    assert len(conn.statements) == 2  # no progress, assignment, Lesson, or pointer write
    assert all(sql.lstrip().startswith("SELECT") for sql in conn.statements)


def test_stale_plan_and_base_language_rebinding_fail_closed() -> None:
    conn = _conn()
    planner = ExistingTrackMigrationPlanner(
        cast(Connection[dict[str, object]], conn), PlanCoveragePreflightService(FakeFacts()),
    )
    with pytest.raises(PlanPreflightConflict, match="active plan revision changed"):
        planner.propose(
            user_id=USER_ID, track_id=TRACK_ID, expected_revision_id=REVISION_ID,
            expected_plan_hash="0" * 64,
            requirements=(requirement(key="lc-overview", subject="python.ai-applications",
                                      facets=("langchain-core",)),),
        )
    with pytest.raises(PlanPreflightConflict, match="legacy ecosystem mapping"):
        planner.propose(
            user_id=USER_ID, track_id=TRACK_ID, expected_revision_id=REVISION_ID,
            expected_plan_hash=cast(str, conn.row["content_hash"]),
            requirements=(requirement(key="lc-overview", subject="route.python"),),
        )
