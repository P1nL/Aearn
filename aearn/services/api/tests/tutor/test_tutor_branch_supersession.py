"""Serial, provider-free PostgreSQL regressions for branch authority retirement.

Run only through output/teaching-fullflow-20260913-repairs/run-isolated-tests.py.
Legacy helpers probe PostgreSQL on import: defer that import until BOTH the
explicit and effective DSNs are verified. No dispatcher or context builder runs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository
from app.services.learning.artifacts.contracts import TutorArtifactState
from app.services.learning.artifacts.owner_adapters import ArtifactMutation
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import (
    TeachingAuthority,
    TeachingSessionConflict,
    TeachingSessionRepository,
)
from app.services.tutor.branching import (
    PostgresTutorBranchRepository,
    TutorBranchConflict,
    TutorBranchError,
    TutorBranchRecord,
)
from app.services.tutor.continuation import (
    ContinuationIntentRecord,
    ContinuationIntentState,
    ContinuationSourceKind,
    PostgresTutorContinuationIntentRepository,
)
from app.services.tutor.persistence import PostgresTutorRepository

if TYPE_CHECKING:
    from tests.tutor.test_tutor_branch_continuation import _ArtifactScope


def _require_isolated_database() -> str:
    """Fail before any probe/bootstrap/connection; never print DSNs or settings."""
    explicit = os.environ.get("DATABASE_URL")
    expected = os.environ.get("AEARN_TEST_DATABASE_NAME")
    if not expected:
        pytest.skip("Set AEARN_TEST_DATABASE_NAME to a dedicated isolated database.")
    if expected in {"postgres", "template0", "template1"}:
        pytest.fail("Refusing a non-isolated database target.")
    if not explicit or os.environ.get("LLM_TYPE") != "disabled":
        pytest.fail("Use the serial isolated-test runner; database/provider isolation is missing.")
    try:
        explicit_name = conninfo_to_dict(explicit).get("dbname")
        effective = get_settings().database_url
        effective_name = conninfo_to_dict(effective).get("dbname")
    except (ValueError, psycopg.Error):
        pytest.fail("Invalid isolated database configuration.", pytrace=False)
    if explicit_name != expected or effective_name != expected:
        pytest.fail("Refusing database work outside the exact approved repair database.")
    return effective


@pytest.fixture(scope="module")
def helpers() -> ModuleType:
    _require_isolated_database()
    # Never move this probe-on-import legacy module to collection/module scope.
    module = import_module("tests.tutor.test_tutor_branch_continuation")
    _require_isolated_database()
    module.bootstrap_database()
    return module


@dataclass
class _Case:
    conn: Connection[dict[str, object]]
    helpers: ModuleType
    scope: _ArtifactScope
    run_id: str
    message_id: str
    branch_id: str
    cleanup_user_ids: list[str]

    def branch(self) -> dict[str, object]:
        row = self.conn.execute(
            "SELECT * FROM tutor_conversation_branches WHERE id=%s AND user_id=%s",
            (self.branch_id, self.scope.user_id),
        ).fetchone()
        assert row is not None
        return row

    def session(self, session_id: str) -> dict[str, object]:
        row = self.conn.execute(
            "SELECT * FROM tutor_teaching_sessions WHERE id=%s AND user_id=%s",
            (session_id, self.scope.user_id),
        ).fetchone()
        assert row is not None
        return row

    def cancel_open_turn(self) -> None:
        PostgresTutorRepository(self.conn).request_cancellation(
            user_id=self.scope.user_id, run_id=self.run_id, now=datetime.now(UTC),
            diagnostic_code="supersession_fixture_cancelled",
        )
        self.conn.commit()

    def effects(self) -> dict[str, object]:
        return {
            "runs": self.conn.execute(
                "SELECT id,status,terminal_outcome FROM tutor_runs WHERE user_id=%s ORDER BY id",
                (self.scope.user_id,),
            ).fetchall(),
            "messages": self.conn.execute(
                "SELECT id,role FROM tutor_messages WHERE conversation_id=%s ORDER BY id",
                (self.scope.conversation_id,),
            ).fetchall(),
            "artifacts": self.conn.execute(
                "SELECT id,state,version FROM tutor_learning_artifacts WHERE user_id=%s ORDER BY id",
                (self.scope.user_id,),
            ).fetchall(),
            "intents": self.conn.execute(
                "SELECT id,state,version FROM tutor_continuation_intents WHERE user_id=%s ORDER BY id",
                (self.scope.user_id,),
            ).fetchall(),
            "progress": self.conn.execute(
                "SELECT knowledge_key,status,version FROM tutor_track_node_progress "
                "WHERE track_id=%s ORDER BY knowledge_key",
                (self.scope.track_id,),
            ).fetchall(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "branch": self.branch(),
            "events": self.conn.execute(
                "SELECT * FROM tutor_conversation_branch_events WHERE branch_id=%s ORDER BY branch_version",
                (self.branch_id,),
            ).fetchall(),
            "items": self.conn.execute(
                "SELECT * FROM tutor_conversation_branch_items WHERE branch_id=%s ORDER BY item_sequence",
                (self.branch_id,),
            ).fetchall(),
            "sessions": self.conn.execute(
                "SELECT * FROM tutor_teaching_sessions WHERE user_id=%s ORDER BY id",
                (self.scope.user_id,),
            ).fetchall(),
            "checkpoints": self.conn.execute(
                "SELECT id,teaching_session_id,session_version,predecessor_checkpoint_id "
                "FROM tutor_teaching_session_checkpoints WHERE user_id=%s ORDER BY id",
                (self.scope.user_id,),
            ).fetchall(),
            "effects": self.effects(),
        }


@pytest.fixture
def case(helpers: ModuleType) -> Iterator[_Case]:
    dsn = _require_isolated_database()
    cleanup_user_ids: list[str] = []
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
        if conn.info.dbname != os.environ["AEARN_TEST_DATABASE_NAME"]:
            pytest.fail("Connected database does not match the approved isolated target.")
        try:
            scope = helpers._prepare_artifact(conn)
            cleanup_user_ids.append(scope.user_id)
            run_id, message_id, _revision, branch_id = helpers._create_branch_turn(
                conn, scope, use_service=True,
            )
            yield _Case(conn, helpers, scope, run_id, message_id, branch_id, cleanup_user_ids)
        finally:
            conn.rollback()
            _require_isolated_database()
            # Existing exact user-scoped cleanup, without another bootstrap.
            for user_id in reversed(cleanup_user_ids):
                helpers.reset_user_data(conn, user_id)
                # Purge authorization is transaction-local and belongs to one user.
                conn.commit()


def _advance_authority(case: _Case) -> TeachingAuthority:
    """Update real fixture authority, not just a detached dataclass snapshot."""
    repository = TeachingSessionRepository(case.conn)
    current = repository.resolve_authority(
        user_id=case.scope.user_id, track_id=case.scope.track_id,
        knowledge_key=case.scope.knowledge_key, conversation_id=case.scope.conversation_id,
        for_update=True,
    )
    row = case.conn.execute(
        "UPDATE tutor_track_node_progress SET version=version+1 "
        "WHERE user_id=%s AND track_id=%s AND knowledge_key=%s AND version=%s RETURNING version",
        (case.scope.user_id, case.scope.track_id, case.scope.knowledge_key, current.progress_version),
    ).fetchone()
    assert row is not None
    changed = replace(current, progress_version=int(str(row["version"])))
    actual = repository.resolve_authority(
        user_id=case.scope.user_id, track_id=case.scope.track_id,
        knowledge_key=case.scope.knowledge_key, conversation_id=case.scope.conversation_id,
        for_update=True,
    )
    assert actual == changed
    # Commit the external fact before testing replacement's own rollback boundary.
    case.conn.commit()
    return changed


def _replace_session(case: _Case, authority: TeachingAuthority) -> dict[str, object]:
    successor, created = TeachingSessionRepository(case.conn).open_or_resume(
        authority=authority, mode=TeachingSessionMode.GUIDED,
    )
    assert created is True
    case.conn.commit()
    return dict(successor)


def _historical_successor(case: _Case, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Recreate the pre-210 orphan using real session/checkpoint owners.

    Suppress ONLY the new auto-retirement hook while arranging this historical
    fixture. Restore the real owner before testing CAS/replay/SQL fencing/claim.
    No session identity, checkpoint lineage or runtime receipt is forged.
    """
    case.cancel_open_turn()
    authority = _advance_authority(case)
    calls: list[str] = []

    def preserve_legacy_branch(
        repository: PostgresTutorBranchRepository, **kwargs: Any,
    ) -> TutorBranchRecord:
        calls.append(str(kwargs["branch_id"]))
        record = repository.read_for_artifact(
            user_id=case.scope.user_id, conversation_id=case.scope.conversation_id,
            artifact_id=case.scope.artifact_id,
        )
        assert record is not None and record.branch_id == case.branch_id
        return record

    with monkeypatch.context() as patch:
        patch.setattr(PostgresTutorBranchRepository, "supersede_authority", preserve_legacy_branch)
        successor = _replace_session(case, authority)
    assert calls == [case.branch_id]
    assert case.branch()["state"] == "active"
    assert case.session(case.scope.session_id)["status"] == "blocked"
    assert str(successor["predecessor_session_id"]) == case.scope.session_id
    assert successor["progress_version"] != case.session(case.scope.session_id)["progress_version"]
    return successor


@dataclass(frozen=True)
class _Request:
    branch_id: str
    user_id: str
    conversation_id: str
    learning_track_id: str
    knowledge_key: str
    teaching_session_id: str
    successor_session_id: str
    expected_version: int
    expected_event_id: str
    expected_session_version: int
    expected_successor_version: int

    def submit(self, case: _Case) -> TutorBranchRecord:
        return PostgresTutorBranchRepository(case.conn).supersede_authority(**asdict(self))


def _request(case: _Case, successor: Mapping[str, object]) -> _Request:
    branch = case.branch()
    old = case.session(case.scope.session_id)
    return _Request(
        branch_id=case.branch_id, user_id=case.scope.user_id,
        conversation_id=case.scope.conversation_id, learning_track_id=case.scope.track_id,
        knowledge_key=case.scope.knowledge_key, teaching_session_id=case.scope.session_id,
        successor_session_id=str(successor["id"]), expected_version=int(str(branch["version"])),
        # TutorBranchRecord deliberately has no current_event_id.
        expected_event_id=str(branch["current_event_id"]),
        expected_session_version=int(str(old["version"])),
        expected_successor_version=int(str(successor["version"])),
    )


def _assert_retirement(
    case: _Case, before: Mapping[str, object], successor_id: str,
) -> dict[str, object]:
    after = case.branch()
    assert after["state"] == "superseded"
    assert after["version"] == int(str(before["version"])) + 1
    assert str(after["superseded_by_session_id"]) == successor_id
    assert after["superseded_at"] is not None
    assert after["resolved_at"] is None and after["resolved_turn_id"] is None
    for key in (
        "user_id", "conversation_id", "learning_track_id", "knowledge_key",
        "teaching_session_id", "checkpoint_id", "artifact_id", "opened_turn_id",
        "opened_message_id", "opened_input_revision", "predecessor_branch_id",
        "round_count", "latest_disposition", "created_at",
    ):
        assert after[key] == before[key], key
    events = case.conn.execute(
        "SELECT * FROM tutor_conversation_branch_events "
        "WHERE branch_id=%s AND event_kind='authority_superseded'",
        (case.branch_id,),
    ).fetchall()
    assert len(events) == 1
    event = events[0]
    assert event["id"] == after["current_event_id"]
    assert event["predecessor_event_id"] == before["current_event_id"]
    assert event["branch_version"] == after["version"]
    assert str(event["superseding_session_id"]) == successor_id
    assert event["created_at"] == after["superseded_at"]
    assert all(event[key] is None for key in (
        "source_turn_id", "source_message_id", "source_input_revision",
        "response_message_id", "disposition", "assistance_receipt_id",
    ))
    assert event["assistance_kind"] == "none"
    return event


def test_authority_refresh_retires_once_without_answer_items_rounds_or_progress(case: _Case) -> None:
    case.cancel_open_turn()
    authority = _advance_authority(case)
    before = case.snapshot()
    successor = _replace_session(case, authority)
    _assert_retirement(case, before["branch"], str(successor["id"]))
    after = case.snapshot()
    assert after["items"] == before["items"]
    # Refresh retires the old session's Artifact as well as its branch; it
    # must not create answer, score, mastery, or progress effects.
    assert after["effects"] == {
        **before["effects"],
        "artifacts": [
            {**artifact, "state": "superseded", "version": artifact["version"] + 1}
            for artifact in before["effects"]["artifacts"]
        ],
    }
    assert len(after["events"]) == len(before["events"]) + 1
    assert case.session(case.scope.session_id)["status"] == "blocked"
    assert str(successor["predecessor_session_id"]) == case.scope.session_id
    same, created = TeachingSessionRepository(case.conn).open_or_resume(
        authority=authority, mode=TeachingSessionMode.GUIDED,
    )
    assert created is False and same["id"] == successor["id"]
    assert case.snapshot() == after


def test_same_authority_open_keeps_valid_active_branch(case: _Case) -> None:
    case.cancel_open_turn()
    repository = TeachingSessionRepository(case.conn)
    authority = repository.resolve_authority(
        user_id=case.scope.user_id, track_id=case.scope.track_id,
        knowledge_key=case.scope.knowledge_key, conversation_id=case.scope.conversation_id,
    )
    before = case.snapshot()
    same, created = repository.open_or_resume(authority=authority, mode=TeachingSessionMode.GUIDED)
    assert created is False and str(same["id"]) == case.scope.session_id
    assert case.snapshot() == before
    # A valid current session is not a replacement for itself, even with exact CAS.
    with pytest.raises(TutorBranchError):
        _request(case, same).submit(case)
    assert case.snapshot() == before


def test_active_old_run_blocks_entire_session_replacement(case: _Case) -> None:
    authority = _advance_authority(case)
    before = case.snapshot()
    with pytest.raises(TeachingSessionConflict):
        TeachingSessionRepository(case.conn).open_or_resume(
            authority=authority, mode=TeachingSessionMode.GUIDED,
        )
    # Do not rollback here: that would hide partial writes leaked by the owner.
    assert case.snapshot() == before
    assert case.branch()["state"] == "active"


def test_owner_failure_after_retirement_rolls_back_checkpoint_successor_and_event(
    case: _Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case.cancel_open_turn()
    authority = _advance_authority(case)
    before = case.snapshot()
    original = PostgresTutorBranchRepository.supersede_authority
    retired_inside: list[str] = []

    def retire_then_fail(repository: PostgresTutorBranchRepository, **kwargs: Any) -> TutorBranchRecord:
        result = original(repository, **kwargs)
        retired_inside.append(result.state)
        raise TutorBranchConflict("injected failure after retirement, before replacement returns")

    with monkeypatch.context() as patch:
        patch.setattr(PostgresTutorBranchRepository, "supersede_authority", retire_then_fail)
        with pytest.raises((TeachingSessionConflict, TutorBranchError)):
            TeachingSessionRepository(case.conn).open_or_resume(
                authority=authority, mode=TeachingSessionMode.GUIDED,
            )
    assert retired_inside == ["superseded"]
    assert case.snapshot() == before


def test_original_expected_request_replays_same_event(
    case: _Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _historical_successor(case, monkeypatch)
    request = _request(case, successor)
    before = case.branch()
    first = request.submit(case)
    event = _assert_retirement(case, before, str(successor["id"]))
    case.conn.commit()
    persisted = case.snapshot()
    second = request.submit(case)
    assert second == first
    assert second.superseded_by_session_id == str(successor["id"])
    assert second.superseded_at == first.superseded_at
    assert case.branch()["current_event_id"] == event["id"]
    assert case.snapshot() == persisted


def _invalid_request(request: _Request, field: str) -> _Request:
    assert field in _Request.__dataclass_fields__
    new_id = str(uuid4())
    return replace(request,
        branch_id=new_id if field == "branch_id" else request.branch_id,
        user_id=new_id if field == "user_id" else request.user_id,
        conversation_id=new_id if field == "conversation_id" else request.conversation_id,
        learning_track_id=new_id if field == "learning_track_id" else request.learning_track_id,
        knowledge_key="python.other" if field == "knowledge_key" else request.knowledge_key,
        teaching_session_id=new_id if field == "teaching_session_id" else request.teaching_session_id,
        successor_session_id=new_id if field == "successor_session_id" else request.successor_session_id,
        expected_version=request.expected_version + (field == "expected_version"),
        expected_event_id=new_id if field == "expected_event_id" else request.expected_event_id,
        expected_session_version=request.expected_session_version + (field == "expected_session_version"),
        expected_successor_version=request.expected_successor_version + (field == "expected_successor_version"),
    )


@pytest.mark.parametrize("field", [
    "branch_id", "user_id", "conversation_id", "learning_track_id", "knowledge_key",
    "teaching_session_id", "successor_session_id", "expected_version", "expected_event_id",
    "expected_session_version", "expected_successor_version",
])
def test_wrong_scope_or_expected_authority_leaves_no_orphan(
    case: _Case, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    successor = _historical_successor(case, monkeypatch)
    request = _request(case, successor)
    invalid = _invalid_request(request, field)
    before = case.snapshot()
    with pytest.raises(TutorBranchError):
        invalid.submit(case)
    assert case.snapshot() == before


@pytest.mark.parametrize("field", [
    "expected_version", "expected_event_id", "expected_session_version", "expected_successor_version",
])
def test_modified_expected_fields_are_not_an_idempotent_replay(
    case: _Case, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    successor = _historical_successor(case, monkeypatch)
    request = _request(case, successor)
    request.submit(case)
    before = case.snapshot()
    with pytest.raises(TutorBranchError):
        _invalid_request(request, field).submit(case)
    assert case.snapshot() == before


def test_foreign_existing_successor_cannot_retire_branch(
    case: _Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _historical_successor(case, monkeypatch)
    foreign = case.helpers._prepare_artifact(case.conn)
    case.cleanup_user_ids.append(foreign.user_id)
    request = replace(
        _request(case, successor), successor_session_id=foreign.session_id,
        expected_successor_version=foreign.session_version,
    )
    before = case.snapshot()
    with pytest.raises(TutorBranchError):
        request.submit(case)
    assert case.snapshot() == before


def test_blocked_direct_successor_is_valid_but_grandchild_is_not(
    case: _Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct = _historical_successor(case, monkeypatch)
    grandchild = _replace_session(case, _advance_authority(case))
    direct = case.session(str(direct["id"]))
    assert direct["status"] == "blocked"
    assert str(grandchild["predecessor_session_id"]) == str(direct["id"])
    before = case.snapshot()
    with pytest.raises(TutorBranchError):
        _request(case, grandchild).submit(case)
    assert case.snapshot() == before
    result = _request(case, direct).submit(case)
    assert result.state == "superseded"
    _assert_retirement(case, before["branch"], str(direct["id"]))


def _pending_intent(case: _Case, artifact_id: str) -> ContinuationIntentRecord:
    return PostgresTutorContinuationIntentRepository(case.conn).create_pending(
        user_id=case.scope.user_id, conversation_id=case.scope.conversation_id,
        artifact_id=artifact_id, source_kind=ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION,
        source_id=f"supersession-fixture:{uuid4().hex}", source_version=1,
        idempotency_key=f"supersession-fixture:{uuid4().hex}",
    )


def _successor_artifact(case: _Case, successor: Mapping[str, object]) -> str:
    teaching = TeachingSessionRepository(case.conn)
    session = teaching.project_session(successor)
    request = case.helpers._artifact_request(
        scope={
            "user_id": case.scope.user_id, "conversation_id": case.scope.conversation_id,
            "track_id": case.scope.track_id, "knowledge_key": case.scope.knowledge_key,
            "track_version": int(str(successor["track_version"])),
            "progress_version": int(str(successor["progress_version"])),
            "assignment_version": int(str(successor["assignment_version"])),
        },
        session=session, owner_kind="teaching_practice",
        owner_id=str(successor["current_checkpoint_id"]), owner_version=int(str(successor["version"])),
    )
    artifacts = PostgresLearningArtifactRepository(
        case.conn, conversation_events=PostgresTutorArtifactConversationEventSink(case.conn),
    )
    created = artifacts.create_artifact(
        request, creation_key=f"supersession-current-artifact:{uuid4().hex}", occurred_at=datetime.now(UTC),
    )
    assert created.artifact.teaching_session_id == str(successor["id"])
    return created.artifact.id


def test_valid_active_branch_still_blocks_current_intent_without_foreground(case: _Case) -> None:
    case.cancel_open_turn()
    intent = _pending_intent(case, case.scope.artifact_id)
    before = case.snapshot()
    claimed = PostgresTutorContinuationIntentRepository(case.conn).claim_next(
        user_id=case.scope.user_id, conversation_id=case.scope.conversation_id, claimant_id="guard-check",
    )
    assert claimed is None
    assert case.session(case.scope.session_id)["status"] == "active"
    assert intent.teaching_session_id == case.scope.session_id
    assert case.snapshot() == before


def test_only_new_authority_intent_is_claimable_after_legal_retirement(
    case: _Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case.cancel_open_turn()
    old_intent = _pending_intent(case, case.scope.artifact_id)
    # Match a legitimate historical terminal Artifact; never bypass the one
    # blocking-Artifact guard merely to arrange a successor-intent fixture.
    artifacts = PostgresLearningArtifactRepository(
        case.conn, conversation_events=PostgresTutorArtifactConversationEventSink(case.conn),
    )
    old_artifact = artifacts.read_artifact(
        artifact_id=case.scope.artifact_id, user_id=case.scope.user_id,
        conversation_id=case.scope.conversation_id,
    )
    artifacts.apply_owner_update(
        artifact_id=old_artifact.id, user_id=case.scope.user_id,
        conversation_id=case.scope.conversation_id, learning_track_id=case.scope.track_id,
        teaching_session_id=case.scope.session_id, expected_artifact_version=old_artifact.version,
        event_key="supersession-fixture-terminal", event_kind="terminal",
        mutation=ArtifactMutation(state=TutorArtifactState.CANCELLED,
            owner_version=old_artifact.owner_version, owner_context_version=old_artifact.owner_version,
            presentation=old_artifact.presentation),
    )
    case.conn.commit()
    successor = _historical_successor(case, monkeypatch)
    current_artifact_id = _successor_artifact(case, successor)
    current_intent = _pending_intent(case, current_artifact_id)
    assert current_intent.teaching_session_id == str(successor["id"])
    assert current_intent.session_version == int(str(successor["version"]))
    assert current_intent.progress_version == int(str(successor["progress_version"]))
    repository = PostgresTutorContinuationIntentRepository(case.conn)
    assert repository.claim_next(
        user_id=case.scope.user_id, conversation_id=case.scope.conversation_id, claimant_id="first-claimant",
    ) is None
    run_ids = case.effects()["runs"]
    _request(case, successor).submit(case)
    now = datetime.now(UTC)
    claimed = repository.claim_next(
        user_id=case.scope.user_id, conversation_id=case.scope.conversation_id,
        claimant_id="first-claimant", now=now,
    )
    assert claimed is not None and claimed.intent_id == current_intent.intent_id
    assert claimed.state is ContinuationIntentState.CLAIMED and claimed.claim_generation == 1
    assert repository.claim_next(
        user_id=case.scope.user_id, conversation_id=case.scope.conversation_id,
        claimant_id="competing-claimant", now=now,
    ) is None
    old = case.conn.execute(
        "SELECT state,terminal_reason,consumed_run_id FROM tutor_continuation_intents WHERE id=%s",
        (old_intent.intent_id,),
    ).fetchone()
    assert old == {"state": "cancelled", "terminal_reason": "authority_stale", "consumed_run_id": None}
    assert case.effects()["runs"] == run_ids
    assert case.conn.execute(
        "SELECT count(*)::int AS n FROM tutor_continuation_intent_events "
        "WHERE intent_id=%s AND event_kind='claimed'", (current_intent.intent_id,),
    ).fetchone() == {"n": 1}


def test_terminal_data_survives_bootstrap_twice_and_is_immutable(case: _Case) -> None:
    case.cancel_open_turn()
    _replace_session(case, _advance_authority(case))
    before = case.snapshot()
    case.conn.commit()
    case.helpers.bootstrap_database()
    case.helpers.bootstrap_database()
    assert case.snapshot() == before
    with pytest.raises(psycopg.errors.CheckViolation), case.conn.transaction():
        case.conn.execute("UPDATE tutor_conversation_branches SET state='active' WHERE id=%s", (case.branch_id,))
    with pytest.raises(psycopg.errors.CheckViolation), case.conn.transaction():
        case.conn.execute("UPDATE tutor_conversation_branch_events SET event_key='rewrite' WHERE branch_id=%s", (case.branch_id,))
    assert case.snapshot() == before


def test_sql_cannot_invent_authority_retirement_for_valid_session(case: _Case) -> None:
    case.cancel_open_turn()
    branch = case.branch()
    before = case.snapshot()
    with pytest.raises(psycopg.errors.CheckViolation), case.conn.transaction():
        case.conn.execute("""INSERT INTO tutor_conversation_branch_events (
            id,branch_id,user_id,conversation_id,artifact_id,predecessor_event_id,
            branch_version,event_key,event_kind,message_classification,superseding_session_id,request_hash
          ) VALUES (%s,%s,%s,%s,%s,%s,%s,'forged-retirement','authority_superseded','normal',%s,%s)""",
          (uuid4(),case.branch_id,case.scope.user_id,case.scope.conversation_id,case.scope.artifact_id,
           branch['current_event_id'],int(str(branch['version']))+1,case.scope.session_id,'0'*64))
    assert case.snapshot() == before


def test_public_retirement_uses_v2_without_reinterpreting_v1(case: _Case) -> None:
    from pydantic import ValidationError
    from app.services.tutor.branch_contracts import TutorPublicBranchGroupV1, TutorPublicBranchGroupV2
    from app.services.learning.artifacts.contracts import TutorArtifactBranchSummaryV1, TutorArtifactBranchSummaryV2

    branches = PostgresTutorBranchRepository(case.conn)
    artifacts = PostgresLearningArtifactRepository(case.conn)
    def group():
        return branches.list_snapshot_groups(user_id=case.scope.user_id,conversation_id=case.scope.conversation_id)[0]
    def summary():
        result = artifacts.read_artifact(user_id=case.scope.user_id,conversation_id=case.scope.conversation_id,
                                         artifact_id=case.scope.artifact_id).branch_summary
        assert result is not None
        return result
    active = group().model_dump(mode='json')
    assert active['schema_version'] == 'tutor_conversation_branch_v1'
    assert 'superseded_at' not in active and 'schema_version' not in summary().model_dump()
    case.cancel_open_turn()
    _replace_session(case, _advance_authority(case))
    retired = group().model_dump(mode='json')
    assert retired['schema_version'] == 'tutor_conversation_branch_v2'
    assert retired['state'] == 'superseded' and retired['resolved_at'] is None and retired['collapsed'] is True
    assert retired['superseded_at'] and retired['items'] == active['items']
    retired_summary = summary().model_dump(mode='json')
    assert retired_summary['schema_version'] == 'tutor_artifact_branch_summary_v2'
    assert retired_summary['state'] == 'superseded' and retired_summary['disposition'] is None
    for model, payload in ((TutorPublicBranchGroupV1, retired),(TutorPublicBranchGroupV2,active),
                            (TutorArtifactBranchSummaryV1,retired_summary),
                            (TutorArtifactBranchSummaryV2,{**retired_summary,'state':'resolved'}),
                            (TutorPublicBranchGroupV2,{**retired,'superseded_at':None}),
                            (TutorPublicBranchGroupV2,{**retired,'resolved_at':retired['superseded_at']}),
                            (TutorPublicBranchGroupV2,{**retired,'unexpected':'field'})):
        with pytest.raises(ValidationError):
            model.model_validate(payload)
