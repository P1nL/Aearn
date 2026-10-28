"""Offline exact-catalog upgrade tests, not PostgreSQL installation evidence."""

import json
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Iterator, TypedDict, cast

import pytest
from psycopg import Connection

from app.db import bootstrap, completion_baseline as baseline, completion_upgrade as upgrade
from app.db.schema import SchemaFragment
from tests.database import test_completion_baseline as fixtures
from tests.database.test_completion_baseline import no_external_io as no_external_io

catalog_metadata = fixtures.metadata
TableACL = tuple[str, tuple[tuple[str, str, bool], ...]]


class InstallOptions(TypedDict):
    expected_database_oid: int
    maintenance_confirmed: bool
    storage_check: bool
    upgrade: bool

_F601 = "601_completion_non_b1d_inventory_reads.sql"
_F602 = "602_completion_non_b1d_planning_catalog_reads.sql"
_TABLES_601 = ("public.rag_source_reviews", "public.rag_source_admissions", "public.rag_source_claim_receipts")
_TABLES_602 = ("public.language_courses", "public.language_course_intent_tags", "public.tutor_learning_intents")
_RUNTIME = ("aearn_cb_runtime_20261027", "SELECT", False)
_OWNER = ("postgres", "SELECT", False)
_VERIFIER = ("aearn_cb_verifier_20261027", "SELECT", False)
_VALIDATION_TABLE = "completion_baseline_internal.validation_fixture"
_TARGETS = ("aearn_completion_b_test_20261026", "postgres", "aearn_completion_b_validation_20261027")


@pytest.fixture
def upgrade_metadata(catalog_metadata: ModuleType) -> ModuleType:
    metadata = catalog_metadata
    tables = _TABLES_601 + _TABLES_602
    additions: dict[str, tuple[object, ...]] = {
        "EXPECTED_TABLES": tables,
        "EXPECTED_RELATION_METADATA": tuple((t, "postgres", "r", False, False) for t in tables),
        "EXPECTED_COLUMNS": tuple((t, "id", "uuid", True, "", None) for t in tables),
        "EXPECTED_TABLE_ACLS": tuple((t, (_RUNTIME, _VERIFIER, _OWNER)) for t in tables),
        "EXPECTED_CONSTRAINTS": tuple(pair[0] for pair in fixtures._CONSTRAINT_VARIANTS),
        "BASE_CONSTRAINTS": tuple(pair[0] for pair in fixtures._CONSTRAINT_VARIANTS),
    }
    for name, rows in additions.items():
        setattr(metadata, name, getattr(metadata, name) + rows)
    for name in (*baseline._BASE_EXPORTS, *baseline._POSTINSTALL_EXPORTS):
        setattr(metadata, "VALIDATION_" + name, getattr(metadata, name))
    validation_additions: dict[str, tuple[object, ...]] = {
        "EXPECTED_TABLES": (_VALIDATION_TABLE,), "NEW_TABLES": (_VALIDATION_TABLE,),
        "EXPECTED_RELATION_METADATA": ((_VALIDATION_TABLE, "postgres", "r", False, False),),
        "EXPECTED_COLUMNS": ((_VALIDATION_TABLE, "id", "uuid", True, "", None),),
        "EXPECTED_TABLE_ACLS": ((_VALIDATION_TABLE, (_OWNER,)),),
        "BASE_TABLES": ("public.tutor_learning_items",),
        "BASE_RELATION_METADATA": (("public.tutor_learning_items", "postgres", "r", False, False),),
        "BASE_COLUMNS": (("public.tutor_learning_items", "id", "uuid", True, "", None),),
        "BASE_TABLE_ACLS": (("public.tutor_learning_items", (_OWNER,)),),
        "BASE_LOCK_RELATIONS": ("public.tutor_learning_items",),
    }
    for name, rows in validation_additions.items():
        setattr(metadata, "VALIDATION_" + name, getattr(metadata, "VALIDATION_" + name) + rows)
    return metadata


class UpgradeConnection(fixtures.CatalogConnection):
    def __init__(self, predecessor: str = "599", database: str = _TARGETS[0]) -> None:
        super().__init__(database=database)
        self.catalog = deepcopy(fixtures._ACTUAL)
        self.catalog["RELATION_METADATA"] += tuple((t, "postgres", "r", False, False) for t in _TABLES_601 + _TABLES_602)
        self.catalog["COLUMNS"] += tuple((t, "id", "uuid", True, "", None) for t in _TABLES_601 + _TABLES_602)
        self.catalog["CONSTRAINTS"] += tuple(pair[1 if database == "postgres" else 0] for pair in fixtures._CONSTRAINT_VARIANTS)
        self.catalog["TABLE_ACLS"] += tuple(
            (t, ((_RUNTIME,) if predecessor == "602" or predecessor == "601" and t in _TABLES_601 else ())
             + (_VERIFIER, _OWNER)) for t in _TABLES_601 + _TABLES_602
        )
        if database == _TARGETS[2]:
            self.catalog["RELATION_METADATA"] += ((_VALIDATION_TABLE, "postgres", "r", False, False),)
            self.catalog["COLUMNS"] += ((_VALIDATION_TABLE, "id", "uuid", True, "", None),)
            self.catalog["TABLE_ACLS"] += ((_VALIDATION_TABLE, (_OWNER,)),)
        self.initial_catalog = deepcopy(self.catalog)
        self.empty_base = False
        self.fail_fragment: str | None = None
        self.lock_drift = False
        self.lock_oid_drift = False
        self.postinstall_drift = False

    def execute(self, statement: object, params: object = None) -> fixtures.Cursor:
        text = str(statement)
        cursor = super().execute(statement, params)
        if text.startswith("SELECT 1 WHERE NOT EXISTS"):
            return fixtures.Cursor([{"empty": True}] if self.empty_base else [])
        if "LOCK TABLE" in text:
            if self.lock_drift:
                self.drift = "COLUMNS"
            if self.lock_oid_drift:
                self.database = "renamed_after_lock"
        for category, query in baseline._CATALOG_QUERIES.items():
            if text == query:
                rows = (("catalog drift",),) if self.drift == category else self.catalog[category]
                return fixtures.Cursor([{"item": list(row)} for row in rows])
        if text.startswith("FIXTURE "):
            if text == self.fail_fragment:
                raise OSError("password=must-not-be-printed")
            tables = _TABLES_601 if text == "FIXTURE 601" else _TABLES_602
            assert text in ("FIXTURE 601", "FIXTURE 602"), "upgrade replayed 599/600"
            self.catalog["TABLE_ACLS"] = tuple(
                (t, (_RUNTIME,) + grants if t in tables else grants)
                for t, grants in cast(tuple[TableACL, ...], self.catalog["TABLE_ACLS"])
            )
            if self.postinstall_drift:
                self.drift = "COLUMNS"
        return cursor

    def rollback(self) -> None:
        super().rollback()
        self.catalog = deepcopy(self.initial_catalog)

    def commit(self) -> None:
        super().commit()
        self.initial_catalog = deepcopy(self.catalog)


def _attach(monkeypatch: pytest.MonkeyPatch, conn: UpgradeConnection) -> None:
    fixtures.attach(monkeypatch, conn)

    @contextmanager
    def fake_connect() -> Iterator[Connection[dict[str, object]]]:
        yield fixtures.connection(conn)

    monkeypatch.setattr(upgrade, "connect", fake_connect)


@pytest.fixture
def fragments(monkeypatch: pytest.MonkeyPatch) -> None:
    def load(*, contract: str, storage_check: bool = False) -> tuple[SchemaFragment, ...]:
        assert contract == "completion_non_b1d_v1"
        plan = (
            SchemaFragment("599_completion_non_b1d_baseline.sql", Path("599.sql"), "FIXTURE 599"),
            SchemaFragment(_F601, Path("601.sql"), "FIXTURE 601"),
            SchemaFragment(_F602, Path("602.sql"), "FIXTURE 602"),
        )
        return plan + ((SchemaFragment("600_completion_non_b1d_validation.sql", Path("600.sql"), "FIXTURE 600"),)
                       if storage_check else ())

    monkeypatch.setattr(bootstrap, "load_schema_fragments", load)


@pytest.mark.parametrize("database", _TARGETS)
@pytest.mark.parametrize("predecessor,expected", [("599", (_F601, _F602)), ("601", (_F602,)), ("602", ())])
def test_readonly_plan_exact_catalog(
    upgrade_metadata: ModuleType, monkeypatch: pytest.MonkeyPatch,
    database: str, predecessor: str, expected: tuple[str, ...],
) -> None:
    conn = UpgradeConnection(predecessor, database)
    _attach(monkeypatch, conn)
    plan = upgrade.inspect_completion_upgrade(storage_check=database == _TARGETS[2])
    assert (plan.predecessor, plan.fragment_names) == (predecessor, expected)
    assert plan.target.database_name == database
    assert conn.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert conn.commits == 0 and conn.rollbacks == 1
    assert not any("FIXTURE " in text or "LOCK TABLE" in text for text in conn.statements)
    assert set(upgrade._CATEGORY_EXPORTS) == set(baseline._CATALOG_QUERIES)


@pytest.mark.parametrize("database", _TARGETS)
@pytest.mark.parametrize("predecessor,expected", [("599", ["FIXTURE 601", "FIXTURE 602"]), ("601", ["FIXTURE 602"])])
def test_candidate_then_install_only_remaining_grants(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
    database: str, predecessor: str, expected: list[str],
) -> None:
    conn = UpgradeConnection(predecessor, database)
    _attach(monkeypatch, conn)
    original = deepcopy(conn.catalog)
    options: InstallOptions = {"expected_database_oid": 901, "maintenance_confirmed": True,
               "storage_check": database == _TARGETS[2], "upgrade": True}
    assert bootstrap.candidate_completion_baseline(**options) is baseline.BaselineState.COMPLETE
    assert conn.catalog == original and conn.commits == 0 and conn.rollbacks == 1
    assert bootstrap.install_completion_baseline(**options) is baseline.BaselineState.COMPLETE
    assert conn.commits == 1
    assert [s for s in conn.statements if s.startswith("FIXTURE ")] == expected * 2
    assert upgrade.inspect_completion_upgrade(storage_check=database == _TARGETS[2]).predecessor == "602"
    advisory = next(i for i, s in enumerate(conn.statements) if "pg_advisory_xact_lock" in s)
    lock = next(i for i, s in enumerate(conn.statements) if "LOCK TABLE" in s)
    capture = next(i for i, s in enumerate(conn.statements) if s == baseline._CATALOG_QUERIES["TABLE_ACLS"])
    ddl = conn.statements.index(expected[0])
    assert advisory < lock < capture < ddl
    if database == _TARGETS[2]:
        assert any("tutor_learning_items" in s and "LOCK TABLE" in s for s in conn.statements)


@pytest.mark.parametrize("category", tuple(baseline._CATALOG_QUERIES))
def test_all_fifteen_categories_are_exact_not_subsets(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch, category: str,
) -> None:
    conn = UpgradeConnection()
    conn.drift = category
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError, match="UPGRADE_PREDECESSOR_REJECTED"):
        bootstrap.candidate_completion_baseline(expected_database_oid=901, maintenance_confirmed=True, upgrade=True)
    assert conn.commits == 0 and not any(s.startswith("FIXTURE ") for s in conn.statements)


@pytest.mark.parametrize("drift", [
    "partial601", "partial602", "602without601", "extra_table_grant", "grantable_select",
    "missing_verifier", "column_grant", "empty_column_acl", "missing_validation600",
])
def test_unknown_acl_and_missing_validation_purpose_rejected(
    upgrade_metadata: ModuleType, monkeypatch: pytest.MonkeyPatch, drift: str,
) -> None:
    conn = UpgradeConnection(database=_TARGETS[2])
    if drift == "missing_validation600":
        conn.catalog["RELATION_METADATA"] = tuple(r for r in conn.catalog["RELATION_METADATA"] if r[0] != _VALIDATION_TABLE)
    elif drift in ("column_grant", "empty_column_acl"):
        conn.catalog["COLUMN_ACLS"] = ((_TABLES_601[0], "id", (_RUNTIME,) if drift == "column_grant" else ()),)
    else:
        updated = []
        for table, grants in cast(tuple[TableACL, ...], conn.catalog["TABLE_ACLS"]):
            if ((drift == "partial601" and table == _TABLES_601[0])
                    or (drift == "partial602" and table == _TABLES_602[0])
                    or (drift == "602without601" and table in _TABLES_602)):
                grants = (_RUNTIME,) + grants
            if table == _TABLES_601[0]:
                if drift == "extra_table_grant":
                    grants += (("PUBLIC", "UPDATE", False),)
                elif drift == "grantable_select":
                    grants += (("aearn_cb_runtime_20261027", "SELECT", True),)
                elif drift == "missing_verifier":
                    grants = tuple(g for g in grants if g != _VERIFIER)
            updated.append((table, grants))
        conn.catalog["TABLE_ACLS"] = tuple(updated)
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError, match="UPGRADE_PREDECESSOR_REJECTED"):
        upgrade.inspect_completion_upgrade(storage_check=True)
    assert conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize("failure", ["extra", "identity_bad", "disabled_fk", "unsafe_function"])
def test_existing_identity_domain_and_runtime_safety_guards_remain_fresh(
    upgrade_metadata: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    conn = UpgradeConnection()
    setattr(conn, failure, True)
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError, match="UPGRADE_PREDECESSOR_REJECTED"):
        upgrade.inspect_completion_upgrade()


@pytest.mark.parametrize("drift", ["lock_drift", "lock_oid_drift"])
def test_upgrade_reinspects_after_schema_and_base_locks(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch, drift: str,
) -> None:
    conn = UpgradeConnection()
    setattr(conn, drift, True)
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError):
        bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True, upgrade=True)
    assert not any(s.startswith("FIXTURE ") for s in conn.statements)
    assert conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize("failure", ["FIXTURE 602", "postinstall"])
def test_failed_second_delta_or_postcheck_rolls_back_whole_transition(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    conn = UpgradeConnection()
    original = deepcopy(conn.catalog)
    conn.fail_fragment = failure
    conn.postinstall_drift = failure == "postinstall"
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError, match="INSTALL_FAILED|POSTINSTALL_REJECTED"):
        bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True, upgrade=True)
    assert conn.catalog == original and conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_upgrade_commit_unknown_never_retries_or_issues_rollback(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
    cleanup_failure: bool,
) -> None:
    conn = UpgradeConnection()
    conn.commit_error = True
    _attach(monkeypatch, conn)
    opens: list[UpgradeConnection] = []

    @contextmanager
    def fake_connect() -> Iterator[Connection[dict[str, object]]]:
        opens.append(conn)
        assert len(opens) == 1, "unknown COMMIT retried or started readback"
        try:
            yield fixtures.connection(conn)
        finally:
            if cleanup_failure:
                raise OSError("password=cleanup-must-not-be-printed")

    monkeypatch.setattr(bootstrap, "connect", fake_connect)
    with pytest.raises(baseline.CompletionBaselineError, match="^COMPLETION_BASELINE_COMMIT_UNKNOWN$"):
        bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True, upgrade=True)
    assert opens == [conn]
    assert conn.commits == 1 and conn.rollbacks == 0
    assert [s for s in conn.statements if s.startswith("FIXTURE ")] == ["FIXTURE 601", "FIXTURE 602"]


@pytest.mark.parametrize("candidate", [False, True])
def test_complete_upgrade_no_ddl_no_commit(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch, candidate: bool,
) -> None:
    conn = UpgradeConnection("602")
    _attach(monkeypatch, conn)
    runner = bootstrap.candidate_completion_baseline if candidate else bootstrap.install_completion_baseline
    assert runner(expected_database_oid=901, maintenance_confirmed=True, upgrade=True) is baseline.BaselineState.COMPLETE
    assert conn.commits == 0 and conn.rollbacks == 1
    assert not any(s.startswith("FIXTURE ") for s in conn.statements)


@pytest.mark.parametrize("failure", [
    None, "writer-close", "readback-open", "readback-catalog", "readback-oid",
    "readback-purpose", "readback-close",
])
def test_acknowledged_upgrade_uses_fresh_readback_and_preserves_committed_error_codes(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    writer = UpgradeConnection("601", database=_TARGETS[2])
    reader = UpgradeConnection("602", database=_TARGETS[2])
    opens: list[UpgradeConnection] = []
    events: list[str] = []
    if failure == "readback-catalog":
        reader.drift = "COLUMNS"
    elif failure == "readback-purpose":
        reader.database = _TARGETS[0]
    elif failure == "readback-oid":
        original_execute = reader.execute

        def wrong_oid(statement: object, params: object = None) -> fixtures.Cursor:
            cursor = original_execute(statement, params)
            if "FROM pg_database d" in str(statement):
                row = cursor.fetchone()
                assert row is not None
                return fixtures.Cursor([row | {"database_oid": 902}])
            return cursor

        monkeypatch.setattr(reader, "execute", wrong_oid)

    @contextmanager
    def fake_connect() -> Iterator[Connection[dict[str, object]]]:
        conn = writer if not opens else reader
        opens.append(conn)
        assert len(opens) <= 2, "acknowledged installation retried"
        label = "writer" if conn is writer else "readback"
        events.append(label + "-open")
        if label == "readback":
            assert writer.commits == 1 and events[-2] == "writer-close"
            if failure == "readback-open":
                raise OSError("password=readback-open-must-not-be-printed")
        try:
            yield fixtures.connection(conn)
        finally:
            events.append(label + "-close")
            if failure == label + "-close":
                raise OSError("password=close-must-not-be-printed")

    monkeypatch.setattr(bootstrap, "connect", fake_connect)
    if failure is None:
        assert bootstrap.install_completion_baseline(
            expected_database_oid=901, maintenance_confirmed=True, storage_check=True, upgrade=True,
        ) is baseline.BaselineState.COMPLETE
    else:
        code = ("COMPLETION_BASELINE_COMMITTED_CLEANUP_FAILED" if failure == "writer-close"
                else "COMPLETION_BASELINE_COMMITTED_READBACK_FAILED")
        with pytest.raises(baseline.CompletionBaselineError, match="^" + code + "$"):
            bootstrap.install_completion_baseline(
                expected_database_oid=901, maintenance_confirmed=True, storage_check=True, upgrade=True,
            )
    assert writer.commits == 1 and writer.rollbacks == 0
    assert [s for s in writer.statements if s.startswith("FIXTURE ")] == ["FIXTURE 602"]
    assert reader.commits == 0
    assert not any("LOCK TABLE" in s or s.startswith("FIXTURE ") for s in reader.statements)
    if failure == "writer-close":
        assert opens == [writer] and reader.rollbacks == 0
    else:
        assert opens == [writer, reader] and writer is not reader
        if failure == "readback-open":
            assert reader.statements == [] and reader.rollbacks == 0
        else:
            assert reader.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            assert reader.rollbacks == 1


def test_acknowledged_first_install_also_requires_independent_complete_readback(
    catalog_metadata: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = fixtures.CatalogConnection(present=False)
    reader = fixtures.CatalogConnection(present=True)
    opens: list[fixtures.CatalogConnection] = []
    plan = tuple(SchemaFragment(name, Path(name), text) for name, text in (
        ("599_completion_non_b1d_baseline.sql", "FORWARD FIXTURE DDL"),
        (_F601, "INVENTORY READS FIXTURE DDL"), (_F602, "PLANNING CATALOG READS FIXTURE DDL"),
    ))
    monkeypatch.setattr(bootstrap, "load_schema_fragments", lambda **kw: plan)

    @contextmanager
    def fake_connect() -> Iterator[Connection[dict[str, object]]]:
        conn = writer if not opens else reader
        opens.append(conn)
        assert len(opens) <= 2
        if conn is reader:
            assert writer.commits == 1
        yield fixtures.connection(conn)

    monkeypatch.setattr(bootstrap, "connect", fake_connect)
    assert bootstrap.install_completion_baseline(
        expected_database_oid=901, maintenance_confirmed=True,
    ) is baseline.BaselineState.COMPLETE
    assert opens == [writer, reader] and writer is not reader
    assert writer.commits == 1 and writer.rollbacks == 0
    assert reader.commits == 0 and reader.rollbacks == 1
    assert reader.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert not any("LOCK TABLE" in s or s.endswith("FIXTURE DDL") for s in reader.statements)


@pytest.mark.parametrize("predecessor,candidate", [("599", True), ("602", False), ("602", True)])
def test_candidate_or_noop_never_opens_postcommit_readback(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
    predecessor: str, candidate: bool,
) -> None:
    conn = UpgradeConnection(predecessor)
    opens = 0

    @contextmanager
    def fake_connect() -> Iterator[Connection[dict[str, object]]]:
        nonlocal opens
        opens += 1
        assert opens == 1, "candidate/noop unexpectedly opened readback"
        yield fixtures.connection(conn)

    monkeypatch.setattr(bootstrap, "connect", fake_connect)
    runner = bootstrap.candidate_completion_baseline if candidate else bootstrap.install_completion_baseline
    assert runner(expected_database_oid=901, maintenance_confirmed=True, upgrade=True) is baseline.BaselineState.COMPLETE
    assert opens == 1 and conn.commits == 0 and conn.rollbacks == 1


def test_private_transition_is_same_real_branch_but_never_ends_outer_top(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = UpgradeConnection(database=_TARGETS[2])
    _attach(monkeypatch, conn)
    original = deepcopy(conn.catalog)
    assert bootstrap._apply_completion_transition(
        fixtures.connection(conn), expected_database_oid=901, storage_check=True, upgrade=True,
    ) is True
    assert conn.commits == 0 and conn.rollbacks == 0
    conn.rollback()
    assert conn.catalog == original


@pytest.mark.parametrize("upgrade_requested", [False, True])
def test_empty_named_database_needs_existing_base_never_legacy_replay(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch, upgrade_requested: bool,
) -> None:
    conn = UpgradeConnection()
    conn.empty_base = True
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError, match="EXISTING_BASE_REQUIRED"):
        bootstrap.install_completion_baseline(
            expected_database_oid=901, maintenance_confirmed=True, upgrade=upgrade_requested,
        )
    assert not any("LOCK TABLE" in s or s.startswith("FIXTURE ") for s in conn.statements)


def test_upgrade_never_installs_absent_or_repairs_during_check(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = UpgradeConnection()
    conn.present = False
    conn.catalog = {category: fixtures._BASE_ACTUAL.get(category, ()) for category in baseline._CATALOG_QUERIES}
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError, match="UPGRADE_PREDECESSOR_REJECTED"):
        bootstrap.candidate_completion_baseline(expected_database_oid=901, maintenance_confirmed=True, upgrade=True)
    with pytest.raises(baseline.CompletionBaselineError, match="NOT_READY"):
        baseline.check_completion_baseline()
    assert not any(s.startswith("FIXTURE ") for s in conn.statements)


def test_known_prefix_still_needs_explicit_upgrade_selector(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = UpgradeConnection("601")
    _attach(monkeypatch, conn)
    with pytest.raises(baseline.CompletionBaselineError, match="PARTIAL_OR_UNKNOWN"):
        bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True)
    with pytest.raises(baseline.CompletionBaselineError, match="NOT_READY"):
        baseline.check_completion_baseline()
    assert not any(s.startswith("FIXTURE ") for s in conn.statements)


@pytest.mark.parametrize("confirmed,oid", [(False, 901), (True, 0), (True, -1)])
def test_upgrade_public_maintenance_gate_before_connection(
    monkeypatch: pytest.MonkeyPatch, confirmed: bool, oid: int,
) -> None:
    monkeypatch.setattr(bootstrap, "connect", lambda: pytest.fail("unadmitted connection"))
    with pytest.raises(baseline.CompletionBaselineError, match="MAINTENANCE_REQUIRED"):
        bootstrap.install_completion_baseline(expected_database_oid=oid, maintenance_confirmed=confirmed, upgrade=True)


@pytest.mark.parametrize("freeze_commitment", [False, None, True])
def test_candidate_rehearsal_does_not_freeze_but_real_install_requires_freeze(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch,
    freeze_commitment: bool | None,
) -> None:
    from app.db.schema import governance

    conn = UpgradeConnection("601")
    _attach(monkeypatch, conn)
    facts = governance.CandidateEditFacts(
        installed_anywhere=False, external_pin=False, freeze_commitment=freeze_commitment,
    )
    monkeypatch.setattr(governance, "SCHEMA_FROZEN_FILE_NAMES", governance.SCHEMA_FROZEN_FILE_NAMES - {_F602})
    monkeypatch.setitem(governance.SCHEMA_CANDIDATE_FACTS, _F602, facts)
    assert bootstrap.candidate_completion_baseline(
        expected_database_oid=901, maintenance_confirmed=True, upgrade=True,
    ) is baseline.BaselineState.COMPLETE
    assert governance.SCHEMA_CANDIDATE_FACTS[_F602] is facts
    conn.statements.clear()
    if freeze_commitment is True:
        assert bootstrap.install_completion_baseline(
            expected_database_oid=901, maintenance_confirmed=True, upgrade=True,
        ) is baseline.BaselineState.COMPLETE
        assert conn.commits == 1
        assert governance.candidate_edit_blockers(facts) == ["freeze_commitment_confirmed"]
    else:
        with pytest.raises(baseline.CompletionBaselineError, match="INSTALL_FREEZE_REQUIRED"):
            bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True, upgrade=True)
        assert conn.commits == 0 and not any(s.startswith("FIXTURE ") for s in conn.statements)


@pytest.mark.parametrize("argv", [[], ["--check"], ["--candidate"], ["--install"], ["--upgrade-plan"]])
def test_cli_no_selector_never_legacy_replay(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(bootstrap, "import_module", lambda _: None)
    monkeypatch.setattr(bootstrap, "bootstrap_database", lambda: pytest.fail("CLI replayed legacy DDL"))
    assert bootstrap.main(argv) == 1


@pytest.mark.parametrize("argv", [["--upgrade"], ["--check", "--upgrade"], ["--upgrade-plan", "--upgrade"]])
def test_upgrade_modifier_requires_explicit_candidate_or_install(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(bootstrap, "import_module", lambda _: None)
    assert bootstrap.main(["--contract", "completion_non_b1d_v1", *argv]) == 1


def test_cli_explicit_upgrade_and_readonly_plan(
    upgrade_metadata: ModuleType, fragments: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    conn = UpgradeConnection()
    _attach(monkeypatch, conn)
    monkeypatch.setattr(bootstrap, "import_module", lambda _: None)
    assert bootstrap.main(["--contract", "completion_non_b1d_v1", "--upgrade-plan"]) == 0
    assert json.loads(capsys.readouterr().out)["fragments"] == [_F601, _F602]
    assert bootstrap.main(["--contract", "completion_non_b1d_v1", "--candidate", "--upgrade",
                           "--database-oid", "901", "--maintenance-confirmed"]) == 0
    assert conn.commits == 0


@pytest.mark.parametrize("argv", [
    ["--inventory"], ["--inventory", "--contract", "completion_non_b1d_v1"],
    ["--inventory", "--contract", "completion_non_b1d_v1", "--storage-check"], ["--help"],
])
def test_offline_cli_inventory_and_help_never_load_config_or_connect(argv: list[str]) -> None:
    script = """
import sys
import dotenv
import psycopg
def forbidden(*args, **kwargs):
    raise AssertionError('offline CLI performed credential/DB IO')
dotenv.load_dotenv = forbidden
psycopg.connect = forbidden
psycopg.Connection.connect = forbidden
from app.db import bootstrap
try:
    assert bootstrap.main(sys.argv[1:]) == 0
except SystemExit as result:
    assert result.code == 0
assert 'app.core.config' not in sys.modules
assert 'app.db.connection' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, *argv], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("argv", [
    ["--check"], ["--candidate"], ["--install"], ["--upgrade-plan"], ["--upgrade"],
    ["--database-oid", "901"], ["--maintenance-confirmed"], ["--storage-check"],
])
def test_invalid_inventory_combinations_reject_before_configuration(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(bootstrap, "import_module", lambda _: pytest.fail("invalid inventory loaded config"))
    assert bootstrap.main(["--inventory", *argv]) == 1
