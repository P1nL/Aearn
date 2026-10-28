"""Explicit non-B1d validation DB consumer tests; Main installs 599/600 first.

No import-time IO, bootstrap, DDL, source/provider/runner calls or teardown.
ADMIN is observation-only. Runtime/verifier use distinct real login identities.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Literal, TypedDict, cast
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app.models.onboarding import UserCreateRequest
from app.services.learning.item_supply.storage_tables import PRIVATE_TABLES
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.repositories.local_user_data_repository import delete_user_data, export_user_data, reset_user_data
from app.services.repositories.user_repository import create_user
from app.services.tutor.cutover import CutoverError, HarnessCutoverService
from tests.support.learning_track_support import sample_plan


_DATABASE = "aearn_completion_b_validation_20261027"
_RUNTIME = "aearn_cb_runtime_20261027"
_VERIFIER = "aearn_cb_verifier_20261027"
_ENV_PREFIX = "AEARN_COMPLETION_BASELINE_"
_PREINSTALL_USER = "98a28406-8f80-4f44-b532-f6acf110963b"
_BIRTHS = "tutor_item_supply_native_exposure_births"
_INBOX = "tutor_item_supply_native_exposure_inbox"
Role = Literal["ADMIN", "RUNTIME", "VERIFIER"]


@dataclass(frozen=True)
class BaselineConnection:
    role: Role
    options: dict[str, str] = field(repr=False)

    @classmethod
    def parse(cls, role: Role, raw: str) -> BaselineConnection:
        try:
            parsed = urlsplit(raw)
            port = parsed.port if parsed.port is not None else 5432
            username = unquote(parsed.username or "")
            if (parsed.scheme not in {"postgres", "postgresql"}
                    or parsed.hostname not in {"localhost", "127.0.0.1"}
                    or unquote(parsed.path) != "/" + _DATABASE
                    or parsed.query or parsed.fragment or not username or not 1 <= port <= 65535
                    or (role == "RUNTIME" and username != _RUNTIME)
                    or (role == "VERIFIER" and username != _VERIFIER)
                    or (role == "ADMIN" and username in {_RUNTIME, _VERIFIER})):
                raise ValueError
        except ValueError:
            raise ValueError(f"Unsafe {_ENV_PREFIX}{role}_URL: require the exact local validation DB and its distinct login role") from None
        options = "-c search_path=public -c statement_timeout=15000 -c lock_timeout=3000"
        if role == "ADMIN":
            options += " -c default_transaction_read_only=on"
        return cls(role, {
            "host": cast(str, parsed.hostname), "hostaddr": "127.0.0.1", "port": str(port),
            "dbname": _DATABASE, "user": username, "password": unquote(parsed.password or ""),
            "passfile": os.devnull, "connect_timeout": "3", "options": options,
            "application_name": f"completion-baseline-validation-{role.lower()}",
        })

    @contextmanager
    def connect(self, *, autocommit: bool = False) -> Iterator[Connection[dict[str, object]]]:
        with psycopg.connect(make_conninfo(**self.options), autocommit=autocommit, row_factory=dict_row) as conn:
            identity = conn.execute("""SELECT current_database() AS database_name,
                session_user::text AS login, current_user::text AS effective""").fetchone()
            assert identity is not None and identity["database_name"] == _DATABASE
            assert identity["login"] == identity["effective"] == self.options["user"]
            if not autocommit:
                conn.commit()  # Identity read must not turn the owner TOP into a savepoint.
            yield conn


@dataclass(frozen=True)
class BaselineCredentials:
    admin: BaselineConnection = field(repr=False)
    runtime: BaselineConnection = field(repr=False)
    verifier: BaselineConnection = field(repr=False)
    preinstall_user_id: str


def _credentials() -> BaselineCredentials | None:
    names = tuple(_ENV_PREFIX + role + "_URL" for role in ("ADMIN", "RUNTIME", "VERIFIER"))
    values = tuple(os.environ.get(name) for name in names)
    if all(value is None for value in values):
        return None
    if any(not value for value in values):
        raise ValueError("All three explicit baseline validation URLs are required; no DATABASE_URL fallback")
    preinstall = os.environ.get(_ENV_PREFIX + "PREINSTALL_USER_ID")
    if preinstall != _PREINSTALL_USER:
        raise ValueError("Explicit preinstallation synthetic user identity must match Main's committed report")
    connections = tuple(BaselineConnection.parse(cast(Role, role), cast(str, value))
        for role, value in zip(("ADMIN", "RUNTIME", "VERIFIER"), values, strict=True))
    if len({connection.options["port"] for connection in connections}) != 1:
        raise ValueError("Baseline validation roles must address the same local server")
    return BaselineCredentials(connections[0], connections[1], connections[2], preinstall)


def test_missing_env_is_safe_without_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("ADMIN", "RUNTIME", "VERIFIER"):
        monkeypatch.delenv(_ENV_PREFIX + role + "_URL", raising=False)
    monkeypatch.delenv(_ENV_PREFIX + "PREINSTALL_USER_ID", raising=False)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Missing-env check must never connect")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    assert _credentials() is None
    with pytest.raises(pytest.fail.Exception, match="PG acceptance cannot skip"):
        getattr(baseline_pg, "__wrapped__")()
    monkeypatch.setenv(_ENV_PREFIX + "RUNTIME_URL", "postgresql://not-read@127.0.0.1/postgres")
    with pytest.raises(ValueError, match="All three"):
        _credentials()


@dataclass
class BaselinePG:
    credentials: BaselineCredentials = field(repr=False)
    created_users: set[str] = field(default_factory=set)

    def new_user(self, *, legacy: bool = False) -> str:
        payload = UserCreateRequest(display_name=f"completion-baseline-validation:{uuid4().hex}",
            profession="synthetic legacy profile" if legacy else None)
        with self.credentials.runtime.connect() as conn, conn.transaction():
            user = create_user(conn, payload)
            user_id = str(user["id"])
        with self.credentials.admin.connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)).fetchone()
            assert row is not None
        self.created_users.add(user_id)
        print(f"baseline synthetic user retained: {user_id}")
        return user_id

    def verify_new_user(self, user_id: str) -> None:
        assert user_id in self.created_users
        with self.credentials.admin.connect() as conn:
            assert conn.execute("SELECT user_id FROM harness_cutovers WHERE user_id = %s", (user_id,)).fetchone() is None
        with self.credentials.runtime.connect() as conn:
            assert HarnessCutoverService(conn).get_decision(user_id=user_id)["state"] == "verified"
        with self.credentials.admin.connect() as conn:
            row = conn.execute("SELECT state, verified_at FROM harness_cutovers WHERE user_id = %s", (user_id,)).fetchone()
            assert row is not None and row["state"] == "verified" and row["verified_at"] is not None


@pytest.fixture
def baseline_pg() -> BaselinePG:
    credentials = _credentials()
    if credentials is None:
        pytest.fail("All three isolated baseline validation role URLs are required; PG acceptance cannot skip", pytrace=False)
    from app.db.completion_baseline import BaselineState, classify_completion_baseline, inspect_completion_target

    with credentials.admin.connect() as conn, conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        target = inspect_completion_target(conn, storage_check=True)
        assert classify_completion_baseline(conn, target=target) is BaselineState.COMPLETE, "Main must install and independently validate the complete 599/600 contract first"
    return BaselinePG(credentials)


def _epoch(case: BaselinePG, user_id: str) -> dict[str, object] | None:
    with case.credentials.admin.connect() as conn:
        return conn.execute("SELECT epoch, enabled FROM tutor_item_supply_user_epochs WHERE user_id = %s", (user_id,)).fetchone()


def _private_snapshot(case: BaselinePG, user_id: str) -> dict[str, list[dict[str, object]]]:
    assert user_id in case.created_users
    with case.credentials.admin.connect() as conn:
        return {table: conn.execute(sql.SQL("SELECT * FROM {} AS owned WHERE user_id = %s ORDER BY created_at, to_jsonb(owned)::text").format(sql.Identifier(table)),
            (user_id,)).fetchall() for table in PRIVATE_TABLES}


def _assert_no_permit(case: BaselinePG, user_id: str) -> None:
    with case.credentials.admin.connect() as conn:
        assert not conn.execute("SELECT transaction_id FROM item_supply_internal.reset_permits WHERE user_id = %s", (user_id,)).fetchall()
        assert not conn.execute("SELECT transaction_id FROM completion_baseline_internal.validation_permits WHERE user_id = %s", (user_id,)).fetchall()


@dataclass(frozen=True)
class ValidationGraph:
    user_id: str
    track_id: str
    revision_id: str
    ids: dict[str, object]
    journal: dict[str, object]


def _graph(case: BaselinePG, user_id: str, teaching: OrdinaryTeachingGraph | None = None) -> ValidationGraph:
    assert user_id in case.created_users
    knowledge_key = "python.width" if teaching else "python.variables"
    with case.credentials.runtime.connect() as conn, conn.transaction():
        repository = PostgresLearningTrackRepository(conn)
        if teaching is None:
            plan = sample_plan()
            plan = replace(plan, modules=(replace(plan.modules[0], nodes=(plan.modules[0].nodes[0],)),))
            track_id = repository.create_track(user_id=user_id, language_id="python",
                goal_text="Non-B1d storage lifecycle validation", target_level="beginner", plan=plan)
        else:
            assert teaching.user_id == user_id
            track_id = teaching.track_id
        revision_id, _ = repository.read_active_plan(user_id=user_id, track_id=track_id)
    with case.credentials.verifier.connect() as conn, conn.transaction():
        ids = conn.execute("SELECT * FROM completion_baseline_internal.issue_private_graph(%s,%s,%s,%s)",
            (user_id, track_id, revision_id, knowledge_key)).fetchone()
        assert ids is not None and set(ids) == {"scope_id", "material_id", "parent_candidate_id", "child_candidate_id", "version_id", "shared_matrix_id"}
        journal = conn.execute("SELECT * FROM completion_baseline_internal.issue_journal_graph(%s)", (ids["scope_id"],)).fetchone()
        assert journal is not None and set(journal) == {"task_id", "attachment_id"}
    with case.credentials.admin.connect() as conn:
        for table, key in (("tutor_item_supply_private_scopes", "scope_id"), ("tutor_item_supply_private_materials", "material_id"),
                           ("tutor_item_supply_private_candidates", "child_candidate_id"), ("tutor_item_supply_private_versions", "version_id")):
            assert conn.execute(sql.SQL("SELECT id FROM {} WHERE id = %s AND user_id = %s").format(sql.Identifier(table)),
                (ids[key], user_id)).fetchone() is not None
    _assert_no_permit(case, user_id)
    return ValidationGraph(user_id, track_id, revision_id, ids, journal)


class ConfirmationArguments(TypedDict):
    user_id: str
    cutover_version: str
    summary_version: int
    preview_nonce: str
    summary_hash: str
    client_action_id: str
    confirm: bool


def _confirm_arguments(user_id: str, preview: Mapping[str, object]) -> ConfirmationArguments:
    return {"user_id": user_id, "cutover_version": str(preview["cutover_version"]),
        "summary_version": int(str(preview["summary_version"])), "preview_nonce": str(preview["preview_nonce"]),
        "summary_hash": str(preview["summary_hash"]), "client_action_id": f"baseline-confirm-{uuid4().hex}", "confirm": True}


def test_scenario_01_new_user_birth_and_real_preinstallation_user(baseline_pg: BaselinePG) -> None:
    case = baseline_pg
    old_user = case.credentials.preinstall_user_id
    with case.credentials.admin.connect() as conn:
        assert conn.execute("SELECT id FROM users WHERE id = %s AND deleted_at IS NULL", (old_user,)).fetchone() is not None
        assert not conn.execute(f"SELECT id FROM {_BIRTHS} WHERE user_id = %s", (old_user,)).fetchall(), "Installation must not fabricate birth for Main's preinstallation user"
    old_epoch = _epoch(case, old_user)
    with case.credentials.runtime.connect() as conn:
        assert HarnessCutoverService(conn).get_decision(user_id=old_user)["state"] == "verified"
    assert _epoch(case, old_user) == old_epoch  # Reading cutover is not a birth/epoch mint.
    user_id = case.new_user()
    assert _epoch(case, user_id) == {"epoch": 1, "enabled": True}
    with case.credentials.admin.connect() as conn:
        births = conn.execute(f"SELECT id, epoch FROM {_BIRTHS} WHERE user_id = %s", (user_id,)).fetchall()
        assert len(births) == 1 and births[0]["epoch"] == 1
    case.verify_new_user(user_id)
    with case.credentials.runtime.connect() as conn, conn.transaction():
        reset_user_data(conn, user_id)
    assert _epoch(case, user_id) == {"epoch": 2, "enabled": True}
    with case.credentials.admin.connect() as conn:
        assert not conn.execute(f"SELECT id FROM {_BIRTHS} WHERE user_id IN (%s,%s)", (user_id, old_user)).fetchall()
    _assert_no_permit(case, user_id)


def test_scenario_02_first_cutover_blocks_payload_and_confirms_real_legacy_profile(baseline_pg: BaselinePG) -> None:
    case = baseline_pg
    contaminated = case.new_user()
    graph = _graph(case, contaminated)
    before = _private_snapshot(case, contaminated)
    with case.credentials.admin.connect() as conn:
        assert conn.execute("SELECT user_id FROM harness_cutovers WHERE user_id = %s", (contaminated,)).fetchone() is None
    with case.credentials.runtime.connect() as conn:
        decision = HarnessCutoverService(conn).get_decision(user_id=contaminated)
        assert decision["state"] == "blocked_target_state" and decision["code"] == "CUTOVER_TARGET_STATE_PRESENT"
    assert _private_snapshot(case, contaminated) == before and graph.ids["scope_id"] is not None
    legacy = case.new_user(legacy=True)
    with case.credentials.runtime.connect() as conn:
        preview = HarnessCutoverService(conn).get_decision(user_id=legacy)
        assert preview["state"] == "summary_ready"
        args = _confirm_arguments(legacy, preview)

        def failure(_stage: str) -> None:
            raise RuntimeError("Synthetic original-owner rollback point")

        with pytest.raises(CutoverError) as stopped:
            HarnessCutoverService(conn, failure_injector=failure).confirm(**args)
        assert stopped.value.code == "CUTOVER_VERIFICATION_FAILED"
    with case.credentials.admin.connect() as conn:
        row = conn.execute("SELECT profession FROM users WHERE id = %s", (legacy,)).fetchone()
        assert row is not None and row["profession"] == "synthetic legacy profile"
    with case.credentials.runtime.connect() as conn:
        owner = HarnessCutoverService(conn)
        refreshed = owner.get_decision(user_id=legacy)
        assert refreshed["state"] == "summary_ready"
        assert owner.confirm(**_confirm_arguments(legacy, refreshed))["state"] == "verified"
    with case.credentials.admin.connect() as conn:
        row = conn.execute("SELECT profession FROM users WHERE id = %s", (legacy,)).fetchone()
        assert row is not None and row["profession"] is None


def test_scenario_03_nonempty_private_export_is_safe_and_user_scoped(baseline_pg: BaselinePG, monkeypatch: pytest.MonkeyPatch) -> None:
    case = baseline_pg
    user_id, other_id = case.new_user(), case.new_user()
    first, native = _native_graph(case, user_id, monkeypatch)
    other = _graph(case, other_id)
    other_before = _private_snapshot(case, other_id)
    with case.credentials.runtime.connect() as conn, conn.transaction():
        exported = export_user_data(conn, user_id)
    summaries = cast(dict[str, dict[str, object]], exported["item_supply_private_summaries"])
    assert set(PRIVATE_TABLES) <= set(summaries)
    for table in PRIVATE_TABLES:
        summary = summaries[table]
        records = cast(list[dict[str, object]], summary["records"])
        assert type(summary["truncated"]) is bool and len(records) <= 1000
        assert all(set(record) == {"id", "scope_id", "created_at"} for record in records)
    for table, expected_id in (("tutor_item_supply_private_materials", first.ids["material_id"]),
                               ("tutor_item_supply_private_versions", first.ids["version_id"])):
        records = cast(list[dict[str, object]], summaries[table]["records"])
        assert len(records) == 1 and records[0]["id"] == str(expected_id)
        assert records[0]["scope_id"] == str(first.ids["scope_id"])
    births = cast(list[dict[str, object]], summaries[_BIRTHS]["records"])
    assert len(births) == 1 and births[0]["scope_id"] is None
    text = json.dumps(summaries, default=str)
    assert str(other.ids["material_id"]) not in text and str(other.ids["scope_id"]) not in text
    completion = cast(dict[str, object], exported["completion_execution_summary"])
    assert set(completion) == {"schema_version", "counts", "private_requests_results_and_source_units"}
    assert completion["private_requests_results_and_source_units"] == "omitted"
    bindings = cast(list[dict[str, object]], summaries["tutor_item_supply_native_artifact_bindings"]["records"])
    assert len(bindings) == 1 and bindings[0]["id"] == str(native["binding_artifact_id"])
    assert bindings[0]["scope_id"] is None  # Real artifact_id PK; no fabricated scope column.
    with case.credentials.runtime.connect() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT * FROM completion_baseline_internal.issue_native_binding_graph(%s,%s,%s)",
                (first.ids["scope_id"], native["binding_artifact_id"], uuid4()))
        with conn.transaction():
            reset_user_data(conn, user_id)
    assert not any(_private_snapshot(case, user_id).values())
    assert _private_snapshot(case, other_id) == other_before
    _assert_no_permit(case, user_id)


def test_scenario_05_reset_epoch_permit_and_stale_receiver_are_atomic(baseline_pg: BaselinePG, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routes import users as routes
    from app.services.tutor import cutover
    from starlette.requests import Request

    case = baseline_pg
    user_id = case.new_user()
    case.verify_new_user(user_id)
    graph = _graph(case, user_id)
    before = _private_snapshot(case, user_id)
    assert before["tutor_item_supply_private_candidates"] and before["tutor_item_supply_private_persistent_pack_journal"]

    @contextmanager
    def owner_connection() -> Iterator[Connection[dict[str, object]]]:
        with case.credentials.runtime.connect(autocommit=False) as conn:
            yield conn

    monkeypatch.setattr(routes, "connect", owner_connection)
    monkeypatch.setattr(cutover, "connect", owner_connection)

    def request(confirm: bool) -> Request:
        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": json.dumps({"confirm": confirm}).encode(), "more_body": False}
        return Request({"type": "http", "method": "POST", "path": f"/api/users/{user_id}/reset-data", "headers": []}, receive)

    refusal = asyncio.run(routes.reset_user_learning_data(user_id, request(False)))
    assert getattr(refusal, "status_code", None) == 400
    assert _private_snapshot(case, user_id) == before
    with case.credentials.runtime.connect() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("SELECT * FROM completion_baseline_internal.issue_private_graph(%s,%s,%s,%s)",
                    (user_id, graph.track_id, graph.revision_id, "python.variables"))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("SELECT set_config('aearn.item_supply_purge_user_id',%s,true)", (user_id,))
                conn.execute("DELETE FROM tutor_item_supply_private_materials WHERE id=%s AND user_id=%s", (graph.ids["material_id"], user_id))
    # Hold a real second connection/transaction with the old scope across the
    # original route's COMMIT; the verifier cannot revive it after reset.
    with case.credentials.verifier.connect() as stale, stale.transaction():
        assert stale.execute("SELECT txid_current() AS id").fetchone() is not None
        result = asyncio.run(routes.reset_user_learning_data(user_id, request(True)))
        assert getattr(result, "status_code", None) == 200
        with pytest.raises(psycopg.errors.CheckViolation):
            with stale.transaction():
                stale.execute("SELECT * FROM completion_baseline_internal.issue_journal_graph(%s)", (graph.ids["scope_id"],)).fetchone()
    assert _epoch(case, user_id) == {"epoch": 2, "enabled": True}
    assert not any(_private_snapshot(case, user_id).values())
    _assert_no_permit(case, user_id)


def test_scenario_06_delete_rolls_back_then_preserves_other_user_and_shared_matrix(baseline_pg: BaselinePG) -> None:
    case = baseline_pg
    user_id, other_id = case.new_user(), case.new_user()
    case.verify_new_user(user_id)
    first, other = _graph(case, user_id), _graph(case, other_id)
    with case.credentials.verifier.connect() as conn, conn.transaction():
        shared = conn.execute("SELECT * FROM completion_baseline_internal.issue_shared_subscription_graph(%s,%s)",
            (first.ids["scope_id"], other.ids["scope_id"])).fetchone()
        assert shared is not None and set(shared) == {"shared_job_id", "first_subscription_id", "second_subscription_id",
            "known_usage_id", "unknown_usage_id", "reservation_id"}
    with case.credentials.admin.connect() as conn:
        job_before = conn.execute("SELECT * FROM tutor_item_supply_shared_jobs WHERE id=%s", (shared["shared_job_id"],)).fetchone()
        usage_before = conn.execute("SELECT * FROM tutor_item_supply_shared_usage_events WHERE job_id=%s ORDER BY usage_state",
            (shared["shared_job_id"],)).fetchall()
        subscriptions = conn.execute("SELECT id,user_id,shared_job_id,state FROM tutor_item_supply_private_subscriptions WHERE shared_job_id=%s",
            (shared["shared_job_id"],)).fetchall()
        assert job_before is not None and job_before["state"] == "cancelled" and len(subscriptions) == 2
        assert {row["id"] for row in subscriptions} == {shared["first_subscription_id"], shared["second_subscription_id"]}
        assert {str(row["user_id"]) for row in subscriptions} == {user_id, other_id}
        assert len(usage_before) == 2 and usage_before[0]["id"] == shared["known_usage_id"]
        assert usage_before[0]["usage_state"] == "known" and usage_before[0]["input_tokens"] == 7 and usage_before[0]["output_tokens"] == 3
        assert usage_before[1]["id"] == shared["unknown_usage_id"] and usage_before[1]["usage_state"] == "unknown"
        assert all(usage_before[1][key] is None for key in ("input_tokens", "output_tokens", "resource_units", "cost_amount"))
        assert all(row["cost_amount"] is None for row in usage_before)  # No paid billing assertion, including known counters.
    before, other_before = _private_snapshot(case, user_id), _private_snapshot(case, other_id)
    with case.credentials.admin.connect() as conn:
        shared_before = conn.execute("SELECT * FROM tutor_item_supply_shared_matrices WHERE id IN (%s,%s) ORDER BY id",
            (first.ids["shared_matrix_id"], other.ids["shared_matrix_id"])).fetchall()
        assert shared_before
    with case.credentials.runtime.connect() as conn:
        with pytest.raises(RuntimeError, match="rollback"):
            with conn.transaction():
                delete_user_data(conn, user_id)
                raise RuntimeError("Original owner completed; rollback enclosing TOP")
    assert _private_snapshot(case, user_id) == before and _epoch(case, user_id) == {"epoch": 1, "enabled": True}
    _assert_no_permit(case, user_id)
    with case.credentials.runtime.connect() as conn, conn.transaction():
        assert delete_user_data(conn, user_id)["deleted_user_id"] == user_id
    assert _epoch(case, user_id) == {"epoch": 2, "enabled": False}
    assert not any(_private_snapshot(case, user_id).values())
    assert _private_snapshot(case, other_id) == other_before
    with case.credentials.admin.connect() as conn:
        deleted_user = conn.execute("SELECT deleted_at FROM users WHERE id=%s", (user_id,)).fetchone()
        assert deleted_user is not None and deleted_user["deleted_at"] is not None
        shared_after = conn.execute("SELECT * FROM tutor_item_supply_shared_matrices WHERE id IN (%s,%s) ORDER BY id",
            (first.ids["shared_matrix_id"], other.ids["shared_matrix_id"])).fetchall()
        assert shared_after == shared_before
        assert conn.execute("SELECT * FROM tutor_item_supply_shared_jobs WHERE id=%s", (shared["shared_job_id"],)).fetchone() == job_before
        assert conn.execute("SELECT * FROM tutor_item_supply_shared_usage_events WHERE job_id=%s ORDER BY usage_state",
            (shared["shared_job_id"],)).fetchall() == usage_before
        remaining = conn.execute("SELECT id,user_id,state FROM tutor_item_supply_private_subscriptions WHERE shared_job_id=%s",
            (shared["shared_job_id"],)).fetchall()
        assert len(remaining) == 1 and remaining[0]["id"] == shared["second_subscription_id"]
        assert str(remaining[0]["user_id"]) == other_id and remaining[0]["state"] == "active"
    _assert_no_permit(case, user_id)
    _assert_no_permit(case, other_id)


@dataclass(frozen=True)
class OrdinaryTeachingGraph:
    user_id: str
    track_id: str
    conversation_id: str
    lesson_run_id: str
    session: dict[str, object]


def _ordinary_teaching_graph(case: BaselinePG, user_id: str, monkeypatch: pytest.MonkeyPatch) -> OrdinaryTeachingGraph:
    """Original owners with retained genuine docs; no synthetic source receipt."""
    from datetime import datetime

    from app.core.config import Settings
    from app.services.learning import lesson_authoring, lesson_completion_stages, lesson_service
    from app.services.learning.contracts import LearningScope, LearningScopeKind, LearningTaskKind
    from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
    from app.services.learning.teaching_contracts import TeachingSessionMode
    from app.services.learning.teaching_sessions import TeachingSessionService
    from app.services.tutor.persistence import PostgresTutorRepository
    from tests.support.lesson_document_support import author_candidate_payload

    settings = Settings(llm_type="disabled", openai_api_key=None, deepseek_api_key=None,
        tutor_completion_driven_enabled=True, tutor_default_context_window_tokens=64_000,
        tutor_default_output_reserve_tokens=16_384, codex_runtime_enabled=False)

    def clock() -> datetime:
        with case.credentials.runtime.connect() as conn:
            row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
            assert row is not None and isinstance(row["now"], datetime)
            return row["now"]

    with case.credentials.runtime.connect() as conn:
        try:
            snapshots = lesson_authoring._load_evidence_snapshots(conn, "python", "python.width", "Width assignment",
                clock(), completion_driven=True, required_topics=("python.width",))
        except lesson_authoring.LessonAuthoringFailure:
            pytest.fail("Main must import only the retained 2026-10-26 python-tutorial introduction capture via the original cleaning/index owner into validation DB; no new GET or fake provenance", pytrace=False)
        assert snapshots and all(s.source_id == "python-tutorial" and s.canonical_url == "https://docs.python.org/3/tutorial/introduction.html" for s in snapshots)
        assert PostgresLessonDocumentRepository(conn).evidence_is_current(snapshots)
    with case.credentials.runtime.connect() as conn, conn.transaction():
        plan = sample_plan()
        node = replace(plan.modules[0].nodes[0], knowledge_key="python.width", title="Width assignment")
        plan = replace(plan, modules=(replace(plan.modules[0], nodes=(node,)),))
        tracks = PostgresLearningTrackRepository(conn)
        track_id = tracks.create_track(user_id=user_id, language_id="python", goal_text="Understand width and height assignment", target_level="beginner", plan=plan)
        conversation_id = PostgresTutorRepository(conn, settings=settings).create_conversation(user_id=user_id)
        tracks.bind_conversation_scope(user_id=user_id, conversation_id=conversation_id,
            scope=LearningScope(scope_kind=LearningScopeKind.LEARNING_TRACK, learning_track_id=track_id, task_kind=LearningTaskKind.LESSON_TEACHING))
        scope = PostgresLessonDocumentRepository(conn).read_scope(user_id=user_id, track_id=track_id, knowledge_key=node.knowledge_key)
    monkeypatch.setattr(lesson_authoring, "connect", case.credentials.runtime.connect)
    monkeypatch.setattr(lesson_completion_stages, "connect", case.credentials.runtime.connect)
    monkeypatch.setattr(lesson_completion_stages, "get_settings", lambda: settings)
    monkeypatch.setattr(lesson_service, "get_settings", lambda: settings)

    class FixedAuthor:
        def author(self, request: lesson_authoring.LessonAuthoringRequest) -> lesson_authoring.LessonAuthoringResponse:
            candidate = author_candidate_payload(personalized=request.document_kind == "personalized", title=request.title)
            candidate["knowledge_key"], candidate["coverage_keys"] = request.knowledge_key, [request.knowledge_key]
            for block in cast(list[dict[str, object]], candidate["blocks"]):
                if "coverage_keys" in block:
                    block["coverage_keys"] = [request.knowledge_key]
                if block.get("citation_ids"):
                    block["citation_ids"] = [request.evidence[0].handle]
                if block["type"] == "exercise_gate":
                    block["gate_key"], block["required_capabilities"] = "python.width.basic", [request.knowledge_key]
                elif block["type"] == "code_example":
                    block["code"] = "width = 20\nheight = 5 * 9\narea = width * height"
                elif block["type"] == "comparison":
                    block["rows"] = [["width", "20"], ["height", "45"]]
            return lesson_authoring.LessonAuthoringResponse(candidate, "synthetic", "fixed-owner-fixture", "fixture")

    with case.credentials.runtime.connect() as conn:
        prepared = lesson_service.LessonDocumentService(conn).prepare(user_id=user_id, track_id=track_id,
            knowledge_key=node.knowledge_key, expected_track_version=scope.track_version, expected_progress_version=scope.progress_version,
            idempotency_key=f"baseline-lesson-{uuid4().hex}", completion_driven=True)
        run_id = str(cast(dict[str, object], prepared["authoring_run"])["run_id"])
    lesson_authoring.dispatch_lesson_authoring_run(run_id, author=FixedAuthor(), now=clock)
    with case.credentials.runtime.connect() as conn, conn.transaction():
        lesson = PostgresLessonDocumentRepository(conn).read_authoring_run(run_id=run_id)
        assert lesson.state == "completed", f"Original Lesson owner failed: {lesson.failure_code}"
        opened = TeachingSessionService(conn, settings=settings).open(user_id=user_id, track_id=track_id,
            knowledge_key=node.knowledge_key, conversation_id=conversation_id, expected_track_version=1,
            expected_progress_version=1, expected_assignment_version=1, mode=TeachingSessionMode.FREE_READING,
            idempotency_key=f"baseline-teaching-{uuid4().hex}")
        assert opened["pending_run"] is None
        session = cast(dict[str, object], opened["teaching_session"])
    return OrdinaryTeachingGraph(user_id, track_id, conversation_id, run_id, session)


def _teaching_artifact(case: BaselinePG, graph: OrdinaryTeachingGraph) -> str:
    from app.services.learning.artifacts.contracts import (
        TutorArtifactActionKind, TutorArtifactCreate, TutorArtifactKind, TutorArtifactKnowledgeCheckPresentationV1,
        TutorArtifactOwnerKind, TutorArtifactPurpose, TutorArtifactState,
    )
    from app.services.learning.artifacts.conversation_events import PostgresTutorArtifactConversationEventSink
    from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository

    user_id = graph.user_id
    session = graph.session
    with case.credentials.runtime.connect() as conn, conn.transaction():
        repository = PostgresLearningArtifactRepository(conn, conversation_events=PostgresTutorArtifactConversationEventSink(conn))
        result = repository.create_artifact(TutorArtifactCreate(
            user_id=user_id, conversation_id=graph.conversation_id, learning_track_id=graph.track_id,
            knowledge_key="python.width", teaching_session_id=str(session["session_id"]), checkpoint_id=str(session["checkpoint_id"]),
            track_version=1, progress_version=1, assignment_version=1, owner_kind=TutorArtifactOwnerKind.TEACHING_PRACTICE,
            owner_id=str(session["checkpoint_id"]), owner_version=int(str(session["session_version"])),
            owner_context_version=int(str(session["session_version"])), artifact_kind=TutorArtifactKind.KNOWLEDGE_CHECK,
            purpose=TutorArtifactPurpose.KNOWLEDGE_CHECK, state=TutorArtifactState.ACTIVE, blocking=False,
            title="Assignment check", instruction_markdown="Explain the role of width.",
            presentation=TutorArtifactKnowledgeCheckPresentationV1(response_kind="short_text", prompt_markdown="What does width represent?", maximum_text_length=200),
            allowed_actions=(TutorArtifactActionKind.RESPOND, TutorArtifactActionKind.CANCEL)), creation_key=f"baseline-origin:{uuid4().hex}")
        artifact_id = result.artifact.id
    return str(artifact_id)


def test_scenario_04_ordinary_teaching_owner_captures_unmapped_origin(baseline_pg: BaselinePG, monkeypatch: pytest.MonkeyPatch) -> None:
    case = baseline_pg
    user_id = case.new_user()
    graph = _ordinary_teaching_graph(case, user_id, monkeypatch)
    artifact_id = _teaching_artifact(case, graph)
    with case.credentials.admin.connect() as conn:
        origins = conn.execute(f"""SELECT i.* FROM {_INBOX} i JOIN tutor_learning_artifact_events e
            ON e.id=i.origin_id AND e.user_id=i.user_id WHERE i.user_id=%s AND e.artifact_id=%s""", (user_id, artifact_id)).fetchall()
        assert origins and all(row["version_id"] is None and row["kind"] in {"shown", "untracked"} for row in origins)
        assert not conn.execute("SELECT id FROM tutor_item_supply_native_exposure_watermarks WHERE user_id=%s", (user_id,)).fetchall()
        assert not conn.execute("SELECT id FROM tutor_item_supply_native_exposure_events WHERE user_id=%s", (user_id,)).fetchall()


def _native_graph(case: BaselinePG, user_id: str, monkeypatch: pytest.MonkeyPatch) -> tuple[ValidationGraph, dict[str, object]]:
    from datetime import datetime, timedelta

    from app.agents.harness.contracts import TutorPolicySnapshot
    from app.agents.harness.skill_catalog import compile_published_skill_catalog
    from app.core.config import Settings
    from app.services.tutor.conversation_contracts import TutorInteractionProtocolVersion
    from app.services.tutor.persistence import PostgresTutorRepository

    teaching = _ordinary_teaching_graph(case, user_id, monkeypatch)
    graph = _graph(case, user_id, teaching)
    artifact_id = _teaching_artifact(case, teaching)
    with case.credentials.runtime.connect() as conn, conn.transaction():
        repository = PostgresTutorRepository(conn, settings=Settings(llm_type="disabled", codex_runtime_enabled=False))
        catalog = compile_published_skill_catalog()
        repository.record_catalog_snapshot(catalog)
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()
        assert now is not None and isinstance(now["now"], datetime)
        created = repository.create_run(user_id=user_id, conversation_id=teaching.conversation_id,
            catalog_digest=catalog.digest, policy=TutorPolicySnapshot(deadline=now["now"] + timedelta(minutes=5),
                max_capability_calls=1, max_effects=1, context_token_budget=64, lease_duration_seconds=60),
            origin="interactive", runtime_kind="codex_sidecar_v1",
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2)
        repository.accept_input(user_id=user_id, run_id=created.run_id, idempotency_key=f"validation-native-{uuid4().hex}",
            content="Synthetic storage only; no model dispatch.", ensure_dispatch=False)
    with case.credentials.verifier.connect() as conn, conn.transaction():
        ids = conn.execute("SELECT * FROM completion_baseline_internal.issue_native_binding_graph(%s,%s,%s)",
            (graph.ids["scope_id"], artifact_id, created.run_id)).fetchone()
        assert ids is not None and set(ids) == {"binding_artifact_id", "mapping_id", "consumer_receipt_id", "item_version_id",
            "plan_session_id", "plan_draft_id", "selection_handle", "assessment_binding_id"}
    with case.credentials.admin.connect() as conn:
        row = conn.execute("""SELECT b.artifact_id,b.user_id,b.epoch,r.mode,r.delivery_id,r.payload_json,
            r.valid_until < clock_timestamp() AS expired FROM tutor_item_supply_native_artifact_bindings b
            JOIN tutor_item_supply_native_consumer_receipts r ON r.id=b.creation_receipt_id AND r.user_id=b.user_id
            WHERE b.artifact_id=%s AND b.mapping_id=%s AND b.version_id=%s""",
            (ids["binding_artifact_id"], ids["mapping_id"], ids["item_version_id"])).fetchone()
        assert row is not None and str(row["user_id"]) == user_id and row["epoch"] == 1
        assert row["mode"] == "completion_storage_validation" and row["delivery_id"] is None and row["expired"] is True
        assert cast(dict[str, object], row["payload_json"])["not_business_eligible"] is True
        assert conn.execute("SELECT id FROM tutor_learning_item_publication_events WHERE version_id=%s", (ids["item_version_id"],)).fetchone() is None
    _assert_no_permit(case, user_id)
    return graph, ids


def test_scenario_07_actual_d_tail_requires_nonempty_legally_issued_graph(baseline_pg: BaselinePG, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.grounding.autonomous.actual_d_lifecycle import actual_d_private_counts
    from app.services.learning.item_supply.storage import purge_private_supply

    case = baseline_pg
    user_id = case.new_user()
    case.verify_new_user(user_id)
    graph, native = _native_graph(case, user_id, monkeypatch)
    with case.credentials.verifier.connect() as conn, conn.transaction():
        source = conn.execute("SELECT * FROM completion_baseline_internal.issue_actual_d_tail_graph(%s)", (graph.ids["scope_id"],)).fetchone()
        assert source is not None and set(source) == {"private_evidence_id", "review_id", "admission_id", "claim_id", "public_evidence_id", "corpus_id", "capture_id"}
    with case.credentials.admin.connect() as conn:
        for table, key in (("rag_assessment_source_evidence", "private_evidence_id"), ("rag_source_reviews", "review_id"),
                           ("rag_source_admissions", "admission_id"), ("rag_source_claim_receipts", "claim_id")):
            assert conn.execute(sql.SQL("SELECT id FROM {} WHERE id=%s").format(sql.Identifier(table)), (source[key],)).fetchone() is not None
        evidence = conn.execute("SELECT * FROM rag_assessment_source_evidence WHERE id=%s", (source["private_evidence_id"],)).fetchone()
        assert evidence is not None and str(evidence["private_user_id"]) == user_id and evidence["private_epoch"] == 1
        proof = cast(dict[str, object], evidence["signed_proof"])
        assert proof["signature_status"] == "unsigned" and proof["not_business_eligible"] is True and "signature" not in proof
        assert evidence["revoked_at"] is not None
        provenance = conn.execute("SELECT draft_id,private_evidence_id FROM rag_actual_d_private_provenance WHERE user_id=%s", (user_id,)).fetchone()
        assert provenance == {"draft_id": native["plan_draft_id"], "private_evidence_id": source["private_evidence_id"]}
        public_before = conn.execute("SELECT * FROM rag_assessment_source_evidence WHERE id=%s", (source["public_evidence_id"],)).fetchone()
        corpus_before = conn.execute("SELECT * FROM grounding_corpus_versions WHERE id=%s", (source["corpus_id"],)).fetchone()
        assert public_before is not None and public_before["private_user_id"] is None and public_before["revoked_at"] is not None
        assert corpus_before is not None and corpus_before["state"] == "failed" and corpus_before["published_at"] is None
        assert conn.execute("SELECT evidence_level FROM rag_registered_source_captures WHERE id=%s", (source["capture_id"],)).fetchone() == {"evidence_level": "completion_storage_validation"}
    with case.credentials.runtime.connect() as conn, conn.transaction():
        before = actual_d_private_counts(conn, UUID(user_id))
    assert before and set(before.values()) == {1}, "All five real tail relations must be nonempty; empty success is not acceptance"
    _assert_no_permit(case, user_id)
    assert _epoch(case, user_id) == {"epoch": 1, "enabled": True}
    reached_tail = False
    with case.credentials.runtime.connect() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                purge_private_supply(conn, UUID(user_id))
                reached_tail = True
        assert reached_tail, "Require deferred tail failure at COMMIT, not an unrelated earlier error"
        with conn.transaction():
            assert actual_d_private_counts(conn, UUID(user_id)) == before
    assert _epoch(case, user_id) == {"epoch": 1, "enabled": True}
    with case.credentials.runtime.connect() as conn, conn.transaction():
        reset_user_data(conn, user_id)
    with case.credentials.runtime.connect() as conn, conn.transaction():
        assert not any(actual_d_private_counts(conn, UUID(user_id)).values())
    with case.credentials.admin.connect() as conn:
        assert conn.execute("SELECT * FROM rag_assessment_source_evidence WHERE id=%s", (source["public_evidence_id"],)).fetchone() == public_before
        assert conn.execute("SELECT * FROM grounding_corpus_versions WHERE id=%s", (source["corpus_id"],)).fetchone() == corpus_before
    assert _epoch(case, user_id) == {"epoch": 2, "enabled": True}
    _assert_no_permit(case, user_id)


def test_scenario_08_reset_retains_completion_audit_but_purges_lesson_stages(baseline_pg: BaselinePG, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime

    from app.agents.harness.contracts import TutorPolicySnapshot
    from app.agents.harness.skill_catalog import compile_published_skill_catalog
    from app.agents.runtime.contracts import RuntimePlanningStepResult, RuntimeTerminalStatus, RuntimeThreadHandle, RuntimeTurnResult
    from app.core.config import Settings
    from app.services.tutor.completion_execution import CompletionExecutionOwner, completion_admission_policy
    from app.services.tutor.conversation_contracts import TutorInteractionProtocolVersion
    from app.services.tutor.persistence import PostgresTutorRepository
    from app.services.tutor.runtime_projection import PostgresTutorRuntimeProjectionRepository, TutorRuntimeProjectionFence

    case = baseline_pg
    user_id = case.new_user()
    case.verify_new_user(user_id)
    _graph(case, user_id)
    teaching = _ordinary_teaching_graph(case, user_id, monkeypatch)
    settings = Settings(llm_type="disabled", openai_api_key=None, deepseek_api_key=None, codex_runtime_enabled=False)
    # The real CompletionExecutionOwner demands an idle autocommit connection
    # between preparation, dispatch, result and acceptance boundaries.
    with case.credentials.runtime.connect(autocommit=True) as conn:
        repository = PostgresTutorRepository(conn, settings=settings)
        with conn.transaction():
            # Real immutable repository catalog, not a forged verified receipt.
            catalog = compile_published_skill_catalog()
            repository.record_catalog_snapshot(catalog)
            row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
            assert row is not None and isinstance(row["now"], datetime)
            now = row["now"]
            policy = completion_admission_policy(TutorPolicySnapshot(deadline=now, max_capability_calls=2,
                max_effects=2, context_token_budget=64, lease_duration_seconds=600), now=now)
            created = repository.create_run(user_id=user_id, conversation_id=teaching.conversation_id,
                catalog_digest=catalog.digest, policy=policy, origin="interactive", runtime_kind="codex_sidecar_v1",
                interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2)
            repository.accept_input(user_id=user_id, run_id=created.run_id, idempotency_key=f"audit-input-{uuid4().hex}",
                content="Synthetic audit only; do not dispatch.", ensure_dispatch=False)
            lease = repository.acquire_lease(user_id=user_id, run_id=created.run_id, owner_id="baseline-audit", now=now, duration_seconds=600)
            run = repository.load_snapshot(user_id=user_id, run_id=created.run_id)
            assert lease is not None and run is not None
        owner = CompletionExecutionOwner(conn)
        batch = owner.ensure_batch(run=run, lease=lease)
        step = owner.prepare_step(run=run, lease=lease, batch=batch, step_key="synthetic-audit", kind="sidecar_turn",
            request={"synthetic": True, "private_marker": "BASELINE_PRIVATE_COMPLETION_SENTINEL"}, dependencies={"revision": run.input_revision})
        binding = PostgresTutorRuntimeProjectionRepository(conn).bind_run(user_id=user_id, run_id=run.run_id,
            fence=TutorRuntimeProjectionFence(input_revision=run.input_revision, lease_owner_id=lease.owner_id,
                lease_generation=lease.generation, connection_generation=1), runtime_version="synthetic-validation-only",
            protocol_version="synthetic-validation-only", external_thread_id=f"synthetic-{run.conversation_id}", occurred_at=now, step_attempt_id=step.id)
        step = owner.mark_dispatched(run=run, lease=lease, step=step)
        owner.record_result(run=run, lease=lease, step=step, result=RuntimePlanningStepResult(
            runtime=RuntimeTurnResult(thread=RuntimeThreadHandle(thread_id=f"synthetic-{run.conversation_id}", generation=1),
                turn_id=f"synthetic-{uuid4()}", terminal_status=RuntimeTerminalStatus.COMPLETED, events=()),
            planning_state={"synthetic": True, "private_marker": "BASELINE_PRIVATE_COMPLETION_SENTINEL"},
            tool_results=(), tool_call_count=0, tool_repair_count=0))
    retained = ("tutor_run_execution_batches", "tutor_run_step_attempts", "tutor_run_runtime_bindings")
    with case.credentials.admin.connect() as conn:
        before = {table: conn.execute(sql.SQL("SELECT * FROM {} WHERE run_id=%s ORDER BY id").format(sql.Identifier(table)), (run.run_id,)).fetchall() for table in retained}
        assert all(before.values()) and before["tutor_run_runtime_bindings"][0]["id"] == UUID(binding.binding_id)
        assert len(conn.execute("SELECT id FROM tutor_lesson_authoring_stage_attempts WHERE user_id=%s", (user_id,)).fetchall()) == 2
    with case.credentials.runtime.connect() as conn, conn.transaction():
        exported = export_user_data(conn, user_id)
        assert "BASELINE_PRIVATE_COMPLETION_SENTINEL" not in json.dumps(exported, default=str)
        reset_user_data(conn, user_id)
    with case.credentials.admin.connect() as conn:
        after = {table: conn.execute(sql.SQL("SELECT * FROM {} WHERE run_id=%s ORDER BY id").format(sql.Identifier(table)), (run.run_id,)).fetchall() for table in retained}
        assert after == before
        for table in ("tutor_lesson_authoring_stage_attempts", "tutor_lesson_authoring_runs", "tutor_lesson_assignments"):
            assert not conn.execute(sql.SQL("SELECT id FROM {} WHERE user_id=%s").format(sql.Identifier(table)), (user_id,)).fetchall()
        retained_run = conn.execute("SELECT cancelled_at FROM tutor_runs WHERE id=%s AND user_id=%s", (run.run_id, user_id)).fetchone()
        assert retained_run is not None and retained_run["cancelled_at"] is not None
        assert conn.execute("SELECT id FROM tutor_conversations WHERE id=%s", (teaching.conversation_id,)).fetchone() is not None
    _assert_no_permit(case, user_id)
