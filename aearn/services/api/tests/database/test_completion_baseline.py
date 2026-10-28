"""CPU-only literal catalog boundary fixtures; these do NOT attest real SQL readiness."""

import subprocess
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import cast

import dotenv
import psycopg
import pytest
from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.db import bootstrap, completion_baseline as baseline
from app.db.schema import SchemaFragment


# Independent fixed identity list; these small raw expressions test the protocol,
# not the real CHECK semantics or PostgreSQL parsing. Never load runtime JSON here.
_DEVELOPMENT_IDENTITIES = (
    ("public.tutor_conversations", "chk_tutor_conversations_title"),
    ("public.rag_registered_source_policies", "rag_registered_source_policies_canonical_url_check"),
    ("public.grounding_corpus_documents", "grounding_corpus_documents_canonical_url_check"),
    ("public.grounding_corpus_documents", "grounding_corpus_documents_final_url_check"),
    ("public.rag_registered_source_policies", "rag_registered_source_policies_allowed_usages_check"),
    ("public.rag_registered_source_captures", "rag_registered_source_captures_final_url_check"),
    ("public.rag_source_reviews", "rag_source_reviews_check"),
    ("public.rag_registered_supplemental_authorizations", "rag_registered_supplemental_authorizations_approval_ref_check"),
    ("public.rag_source_admissions", "rag_source_admissions_allowed_usages_check"),
    ("public.rag_candidate_use_grants", "rag_candidate_use_grants_allowed_usages_check"),
    ("public.rag_candidate_use_grants", "rag_candidate_use_grants_approval_ref_check"),
    ("public.rag_registered_supplemental_revocations", "rag_registered_supplemental_revocations_approval_ref_check"),
    ("public.rag_registered_final_followup_allowances", "rag_registered_final_followup_allowances_approval_ref_check"),
)
_CLONE_CHECK = "CHECK (((a >= 0) AND (a <= 1) AND b))"
_DEVELOPMENT_CHECK = "CHECK ((((a >= 0) AND (a <= 1)) AND b))"
_CONSTRAINT_VARIANTS = tuple(
    ((*key, "c", _CLONE_CHECK, True, False, False),
     (*key, "c", _DEVELOPMENT_CHECK, True, False, False))
    for key in _DEVELOPMENT_IDENTITIES
)


# Independent literal metadata: no production SQL parsing or derivation from the
# module under review. SQL author's complete real inventory is a separate gate.
@pytest.fixture
def metadata(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = ModuleType("literal_contract_fixture")
    values = {
        "CATALOG_CANONICALIZED": True,
        "DEVELOPMENT_CONSTRAINT_OVERRIDES": _CONSTRAINT_VARIANTS,
        "CONTRACT_ID": "completion_non_b1d_v1",
        "RUNTIME_DATABASE_NAMES": ("postgres", "aearn_completion_b_test_20261026"),
        "VALIDATION_DATABASE_NAME": "aearn_completion_b_validation_20261027",
        "FORWARD_FRAGMENT_NAMES": (
            "599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
            "602_completion_non_b1d_planning_catalog_reads.sql",
            "600_completion_non_b1d_validation.sql",
        ),
        "RUNTIME_FORWARD_FRAGMENT_NAMES": (
            "599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
            "602_completion_non_b1d_planning_catalog_reads.sql",
        ),
        "VALIDATION_FORWARD_FRAGMENT_NAMES": (
            "599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
            "602_completion_non_b1d_planning_catalog_reads.sql",
            "600_completion_non_b1d_validation.sql",
        ),
        "MANAGED_PUBLIC_RELATION_PREFIXES": ("tutor_item_supply_",),
        "MANAGED_PUBLIC_FUNCTION_PREFIXES": ("purge_item_supply_",),
        "NEW_TABLES": ("completion_baseline_internal.identity",),
        "NEW_SCHEMAS": ("completion_baseline_internal",),
        "NEW_FUNCTIONS": ("completion_baseline_internal.contract_identity()",),
        "EXPECTED_SEQUENCES": (), "EXPECTED_SEQUENCE_METADATA": (), "NEW_SEQUENCES": (),
        "BASE_SEQUENCES": (), "BASE_SEQUENCE_METADATA": (),
        "EXPECTED_EXTENSIONS": (("pgcrypto", "1.3", "public", "postgres"),),
        "BASE_EXTENSIONS": (("pgcrypto", "1.3", "public", "postgres"),),
        "EXPECTED_TABLES": ("completion_baseline_internal.identity",),
        "EXPECTED_RELATION_METADATA": (("completion_baseline_internal.identity", "aearn_cb_schema_20261027", "r", False, False),),
        "EXPECTED_COLUMNS": (("completion_baseline_internal.identity", "id", "boolean", True, "", None),),
        "EXPECTED_CONSTRAINTS": (("completion_baseline_internal.identity", "identity_pkey", "p", "PRIMARY KEY (id)", True, False, False),),
        "EXPECTED_INDEXES": (("completion_baseline_internal.identity", "identity_pkey", "CREATE UNIQUE INDEX identity_pkey ON completion_baseline_internal.identity USING btree (id)", True, True),),
        "EXPECTED_TRIGGERS": (),
        "EXPECTED_TRIGGER_DEFINITIONS": (),
        "EXPECTED_POLICIES": (),
        "EXPECTED_FUNCTIONS": ("completion_baseline_internal.contract_identity()",),
        "FUNCTION_METADATA": (("completion_baseline_internal.contract_identity()", "aearn_cb_schema_20261027", True, "s", ("search_path=pg_catalog",), (("aearn_cb_schema_20261027", False),), "sql", "integer", False, "u", "SELECT 1"),),
        "EXPECTED_SCHEMA_METADATA": (("completion_baseline_internal", "aearn_cb_schema_20261027", (("aearn_cb_schema_20261027", "CREATE", False), ("aearn_cb_schema_20261027", "USAGE", False))), ("public", "postgres", (("postgres", "USAGE", False),))),
        "EXPECTED_TABLE_ACLS": (("completion_baseline_internal.identity", (("aearn_cb_schema_20261027", "SELECT", False),)),),
        "EXPECTED_COLUMN_ACLS": (),
        "EXPECTED_ROLE_METADATA": (
            ("aearn_cb_schema_20261027", False, False, False, False, False, False, False, "completion_non_b1d_v1"),
            ("aearn_cb_runtime_20261027", False, False, False, False, True, False, False, "completion_non_b1d_v1"),
            ("aearn_cb_verifier_20261027", False, False, False, False, True, False, False, "completion_non_b1d_v1"),
        ),
        "EXPECTED_ROLE_MEMBERSHIPS": (),
        "EXPECTED_DEFAULT_ACLS": (),
        "BASE_TABLES": ("public.users",),
        "BASE_COLUMNS": (("public.users", "id", "uuid", True, "", None),),
        "BASE_CONSTRAINTS": (("public.users", "users_pkey", "p", "PRIMARY KEY (id)", True, False, False),),
        "BASE_INDEXES": (("public.users", "users_pkey", "CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)", True, True),),
        "BASE_RELATION_METADATA": (("public.users", "postgres", "r", False, False),),
        "BASE_FUNCTIONS": ("public.old_guard()",),
        "BASE_FUNCTION_METADATA": (("public.old_guard()", "postgres", False, "v", None, (("PUBLIC", False), ("postgres", False)), "plpgsql", "trigger", False, "u", "BEGIN RETURN NEW; END"),),
        "BASE_SCHEMA_METADATA": (("public", "postgres", (("postgres", "USAGE", False),)),),
        "BASE_TABLE_ACLS": (("public.users", (("postgres", "SELECT", False),)),),
        "BASE_TRIGGER_DEFINITIONS": (),
        "BASE_POLICIES": (),
        "BASE_COLUMN_ACLS": (),
        "BASE_LOCK_RELATIONS": ("public.users",),
    }
    module.__dict__.update(values)
    module.__dict__.update({"VALIDATION_" + key: value for key, value in values.items()
                            if key in (*baseline._BASE_EXPORTS, *baseline._POSTINSTALL_EXPORTS)})
    monkeypatch.setattr(baseline.importlib, "import_module", lambda _: module)
    return module


# Deliberately repeated literals, not copied from EXPECTED_* metadata.
_ACTUAL: dict[str, baseline.Rows] = {
    "EXTENSIONS": (("pgcrypto", "1.3", "public", "postgres"),),
    "RELATION_METADATA": (("completion_baseline_internal.identity", "aearn_cb_schema_20261027", "r", False, False),),
    "COLUMNS": (("completion_baseline_internal.identity", "id", "boolean", True, "", None),),
    "CONSTRAINTS": (("completion_baseline_internal.identity", "identity_pkey", "p", "PRIMARY KEY (id)", True, False, False),),
    "INDEXES": (("completion_baseline_internal.identity", "identity_pkey", "CREATE UNIQUE INDEX identity_pkey ON completion_baseline_internal.identity USING btree (id)", True, True),),
    "TRIGGER_DEFINITIONS": (), "POLICIES": (),
    "FUNCTION_METADATA": (("completion_baseline_internal.contract_identity()", "aearn_cb_schema_20261027", True, "s", ("search_path=pg_catalog",), (("aearn_cb_schema_20261027", False),), "sql", "integer", False, "u", "SELECT 1"),),
    "SCHEMA_METADATA": (("completion_baseline_internal", "aearn_cb_schema_20261027", (("aearn_cb_schema_20261027", "CREATE", False), ("aearn_cb_schema_20261027", "USAGE", False))), ("public", "postgres", (("postgres", "USAGE", False),))),
    "TABLE_ACLS": (("completion_baseline_internal.identity", (("aearn_cb_schema_20261027", "SELECT", False),)),),
    "COLUMN_ACLS": (),
    "ROLE_METADATA": (
        ("aearn_cb_schema_20261027", False, False, False, False, False, False, False, "completion_non_b1d_v1"),
        ("aearn_cb_runtime_20261027", False, False, False, False, True, False, False, "completion_non_b1d_v1"),
        ("aearn_cb_verifier_20261027", False, False, False, False, True, False, False, "completion_non_b1d_v1"),
    ),
    "ROLE_MEMBERSHIPS": (), "DEFAULT_ACLS": (), "SEQUENCE_METADATA": (),
}
_BASE_ACTUAL: dict[str, baseline.Rows] = {
    "EXTENSIONS": (("pgcrypto", "1.3", "public", "postgres"),),
    "RELATION_METADATA": (("public.users", "postgres", "r", False, False),),
    "COLUMNS": (("public.users", "id", "uuid", True, "", None),),
    "CONSTRAINTS": (("public.users", "users_pkey", "p", "PRIMARY KEY (id)", True, False, False),),
    "INDEXES": (("public.users", "users_pkey", "CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)", True, True),),
    "TRIGGER_DEFINITIONS": (), "POLICIES": (),
    "FUNCTION_METADATA": (("public.old_guard()", "postgres", False, "v", None, (("PUBLIC", False), ("postgres", False)), "plpgsql", "trigger", False, "u", "BEGIN RETURN NEW; END"),),
    "SCHEMA_METADATA": (("public", "postgres", (("postgres", "USAGE", False),)),),
    "TABLE_ACLS": (("public.users", (("postgres", "SELECT", False),)),),
    "SEQUENCE_METADATA": (), "COLUMN_ACLS": (),
}


class Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class CatalogConnection:
    def __init__(self, *, present: bool = True, database: str = "aearn_completion_b_test_20261026") -> None:
        self.info = SimpleNamespace(host="127.0.0.1")
        self.autocommit = False
        self.search_path = "public"
        self.column_acl_rows: tuple[tuple[object, ...], ...] | None = None
        self.present = present
        self.initial_present = present
        self.database = database
        self.statements: list[str] = []
        self.parameters: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = False
        self.drift: str | None = None
        self.extra = False
        self.column_grant = False
        self.identity_bad = False
        self.disabled_fk = False
        self.unsafe_function = False
        self.base_bad = False

    def execute(self, statement: object, params: object = None) -> Cursor:
        text = str(statement)
        self.statements.append(text)
        self.parameters.append(params)
        if text == baseline.CATALOG_SEARCH_PATH_SQL:
            self.search_path = "pg_catalog, pg_temp"
        if "FROM pg_database d" in text:
            return Cursor([{"database_oid": 901, "database_name": self.database,
                            "session_user": "postgres", "server_address": "127.0.0.1",
                            "in_recovery": False}])
        for category, query in baseline._CATALOG_QUERIES.items():
            if text == query:
                assert self.search_path == "pg_catalog, pg_temp", "ambient catalog rendering path"
                names = cast(tuple[list[str]], params)[0]
                base = (not names or names[0] in ("public.users", "public.old_guard()")
                        or (category == "SCHEMA_METADATA" and not self.present))
                actual = _BASE_ACTUAL if base else _ACTUAL
                rows: list[tuple[object, ...]] = list(actual.get(category, ()))
                if category == "COLUMN_ACLS":
                    if self.column_acl_rows is not None:
                        rows = list(self.column_acl_rows)
                    elif self.column_grant:
                        table = "public.users" if base else "completion_baseline_internal.identity"
                        rows = [(table, "id", (("PUBLIC", "UPDATE", False),))]
                if self.drift == category or (base and self.base_bad):
                    rows = [("wrong actual catalog value",)]
                return Cursor([{"item": list(row)} for row in rows])
        if "SELECT * FROM completion_baseline_internal.contract_identity()" in text:
            return Cursor([{"database_oid": 902 if self.identity_bad else 901,
                            "database_name": self.database, "contract_id": "completion_non_b1d_v1",
                            "purpose": "storage-validation-purpose" if self.database == "aearn_completion_b_validation_20261027" else "runtime-purpose"}])
        if "SELECT 1 WHERE EXISTS (SELECT 1 FROM pg_class c JOIN" in text:
            return Cursor([{"extra": True}] if self.extra else [])
        if text.startswith("SELECT 1 WHERE EXISTS"):
            return Cursor([{"present": True}] if self.present else [])
        if "AND tgisinternal AND tgenabled NOT IN" in text:
            return Cursor([{"disabled": True}] if self.disabled_fk else [])
        if "proleakproof OR prokind" in text:
            return Cursor([{"unsafe": True}] if self.unsafe_function else [])
        if text == "FORWARD FIXTURE DDL":
            self.present = True
            self.search_path = "public"  # Mirrors the forward SQL tail.
        return Cursor([])

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error:
            raise OSError("password=must-not-be-printed DSN")
        self.initial_present = self.present

    def rollback(self) -> None:
        self.rollbacks += 1
        self.present = self.initial_present


def connection(conn: CatalogConnection) -> Connection[dict[str, object]]:
    return cast(Connection[dict[str, object]], conn)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEARN_DATABASE_CONTRACT", raising=False)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("CPU test attempted database/settings IO")

    # Resolving the lazy connection/config module must not read the local .env.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr("app.db.connection.get_settings", forbidden)


def attach(monkeypatch: pytest.MonkeyPatch, conn: CatalogConnection) -> None:
    @contextmanager
    def fake_connect():  # type: ignore[no-untyped-def]
        yield connection(conn)

    monkeypatch.setattr(baseline, "connect", fake_connect)
    monkeypatch.setattr(bootstrap, "connect", fake_connect)


@pytest.mark.parametrize("module", ["app.db.completion_baseline", "app.db.bootstrap"])
def test_module_import_has_no_database_or_settings_io(module: str) -> None:
    script = """
import importlib
import sys
import dotenv
import psycopg

def forbidden(*args, **kwargs):
    raise AssertionError('cold import attempted dotenv/DB IO')

dotenv.load_dotenv = forbidden
psycopg.connect = forbidden
psycopg.Connection.connect = forbidden
importlib.import_module(sys.argv[1])
assert 'app.core.config' not in sys.modules
assert 'app.db.connection' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, module], capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entry", ["cli", "direct"])
def test_bootstrap_loads_environment_at_execution_before_contract_selection(
    monkeypatch: pytest.MonkeyPatch, entry: str,
) -> None:
    events: list[str] = []

    def load_config(name: str) -> None:
        assert name == "app.core.config"
        events.append("config")
        monkeypatch.setenv("AEARN_DATABASE_CONTRACT", "completion_non_b1d_v1")

    monkeypatch.setattr(bootstrap, "import_module", load_config)
    monkeypatch.setattr(bootstrap, "check_completion_baseline", lambda **kw: events.append("readonly-check"))
    if entry == "cli":
        assert bootstrap.main([]) == 0
    else:
        bootstrap.bootstrap_database()
    assert events == ["config", "readonly-check"]


def test_legacy_startup_is_a_noop_and_unknown_environment_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline.ensure_startup_contract(entrypoint="asgi")
    for value in ("", "legacy", "completion_non_b1d_v1 ", "other"):
        monkeypatch.setenv("AEARN_DATABASE_CONTRACT", value)
        with pytest.raises(baseline.CompletionBaselineError, match="CONTRACT_REJECTED"):
            baseline.ensure_startup_contract(entrypoint="worker")


@pytest.mark.parametrize("database", ["aearn_completion_b_validation_20261027", "aearn_b1d_sandbox_20261001", "prefix_postgres"])
def test_live_startup_rejects_validation_and_unnamed_domains(
    metadata: ModuleType, monkeypatch: pytest.MonkeyPatch, database: str,
) -> None:
    conn = CatalogConnection(database=database)
    attach(monkeypatch, conn)
    monkeypatch.setenv("AEARN_DATABASE_CONTRACT", "completion_non_b1d_v1")
    with pytest.raises(baseline.CompletionBaselineError, match="TARGET_REJECTED"):
        baseline.ensure_startup_contract(entrypoint="asgi")
    assert conn.commits == 0 and conn.rollbacks == 1


def test_readonly_startup_checks_full_catalog(metadata: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConnection()
    attach(monkeypatch, conn)
    monkeypatch.setenv("AEARN_DATABASE_CONTRACT", "completion_non_b1d_v1")
    baseline.ensure_startup_contract(entrypoint="worker")
    assert conn.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert conn.commits == 0 and conn.rollbacks == 1
    assert not any("FORWARD FIXTURE" in s for s in conn.statements)


@pytest.mark.parametrize("category", list(_ACTUAL))
def test_catalog_drift_is_not_ready_even_with_valid_identity(metadata: ModuleType, category: str) -> None:
    conn = CatalogConnection()
    conn.drift = category
    target = baseline.inspect_completion_target(connection(conn))
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.PARTIAL_OR_UNKNOWN


@pytest.mark.parametrize("failure", ["extra", "column_grant", "identity_bad", "disabled_fk", "unsafe_function"])
def test_unknown_objects_acl_or_wrong_identity_are_rejected(metadata: ModuleType, failure: str) -> None:
    conn = CatalogConnection()
    setattr(conn, failure, True)
    target = baseline.inspect_completion_target(connection(conn))
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.PARTIAL_OR_UNKNOWN


def test_absent_requires_exact_base_contract(metadata: ModuleType) -> None:
    conn = CatalogConnection(present=False)
    target = baseline.inspect_completion_target(connection(conn))
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.ABSENT
    conn.base_bad = True
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.PARTIAL_OR_UNKNOWN


def test_empty_metadata_is_not_a_ready_stub(metadata: ModuleType) -> None:
    setattr(metadata, "EXPECTED_COLUMNS", ())
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INCOMPLETE"):
        baseline._metadata()


@pytest.fixture
def install_fixture(metadata: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path):  # type: ignore[no-untyped-def]
    fragments = (
        SchemaFragment("599_completion_non_b1d_baseline.sql", tmp_path / "599.sql", "FORWARD FIXTURE DDL"),
        SchemaFragment("601_completion_non_b1d_inventory_reads.sql", tmp_path / "601.sql", "INVENTORY READS FIXTURE DDL"),
        SchemaFragment("602_completion_non_b1d_planning_catalog_reads.sql", tmp_path / "602.sql", "PLANNING CATALOG READS FIXTURE DDL"),
    )
    monkeypatch.setattr(bootstrap, "load_schema_fragments", lambda *, contract, storage_check=False: fragments)
    conn = CatalogConnection(present=False)
    attach(monkeypatch, conn)
    return conn


def test_fixed_candidate_rolls_back_and_install_commits_separately(install_fixture: CatalogConnection) -> None:
    conn = install_fixture
    assert bootstrap.candidate_completion_baseline(expected_database_oid=901, maintenance_confirmed=True) is baseline.BaselineState.COMPLETE
    assert conn.commits == 0 and not conn.present and conn.rollbacks == 1
    assert bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True) is baseline.BaselineState.COMPLETE
    assert conn.commits == 1 and conn.present
    assert conn.statements.count("FORWARD FIXTURE DDL") == 2
    assert [statement for statement in conn.statements if statement.endswith("FIXTURE DDL")] == [
        "FORWARD FIXTURE DDL", "INVENTORY READS FIXTURE DDL", "PLANNING CATALOG READS FIXTURE DDL",
        "FORWARD FIXTURE DDL", "INVENTORY READS FIXTURE DDL", "PLANNING CATALOG READS FIXTURE DDL",
    ]
    assert not any("523_" in s or "524_" in s or "INSERT INTO runtime_profiles" in s for s in conn.statements)
    advisory = next(i for i, text in enumerate(conn.statements) if "pg_advisory_xact_lock" in text)
    lock = next(i for i, text in enumerate(conn.statements) if "LOCK TABLE" in text)
    preflight = next(i for i, text in enumerate(conn.statements) if "SELECT 1 WHERE EXISTS" in text)
    assert advisory < lock < preflight


def test_complete_install_is_readonly_noop(install_fixture: CatalogConnection) -> None:
    conn = install_fixture
    conn.present = conn.initial_present = True
    bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True)
    assert conn.commits == 0 and "FORWARD FIXTURE DDL" not in conn.statements


def test_partial_install_rejects_before_ddl(install_fixture: CatalogConnection) -> None:
    conn = install_fixture
    conn.present = conn.initial_present = True
    conn.drift = "COLUMNS"
    with pytest.raises(baseline.CompletionBaselineError, match="PARTIAL_OR_UNKNOWN"):
        bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True)
    assert conn.commits == 0 and "FORWARD FIXTURE DDL" not in conn.statements


def test_unknown_commit_is_never_replayed_and_dsn_is_not_exposed(install_fixture: CatalogConnection) -> None:
    conn = install_fixture
    conn.commit_error = True
    with pytest.raises(baseline.CompletionBaselineError, match="^COMPLETION_BASELINE_COMMIT_UNKNOWN$"):
        bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True)
    assert conn.statements.count("FORWARD FIXTURE DDL") == 1
    assert conn.statements.count("INVENTORY READS FIXTURE DDL") == 1
    assert conn.statements.count("PLANNING CATALOG READS FIXTURE DDL") == 1
    assert conn.commits == 1 and conn.rollbacks == 0


def test_target_oid_is_rechecked_inside_lock_before_ddl(install_fixture: CatalogConnection) -> None:
    with pytest.raises(baseline.CompletionBaselineError, match="TARGET_REJECTED"):
        bootstrap.install_completion_baseline(expected_database_oid=902, maintenance_confirmed=True)
    assert "FORWARD FIXTURE DDL" not in install_fixture.statements


def test_validation_only_explicit_storage_check(metadata: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConnection(database="aearn_completion_b_validation_20261027")
    attach(monkeypatch, conn)
    assert bootstrap.main(["--contract", "completion_non_b1d_v1", "--check", "--storage-check"]) == 0
    assert bootstrap.main(["--contract", "completion_non_b1d_v1", "--check"]) == 1


def test_named_bootstrap_never_enters_legacy_seed_path(metadata: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConnection()
    attach(monkeypatch, conn)
    monkeypatch.setenv("AEARN_DATABASE_CONTRACT", "completion_non_b1d_v1")
    bootstrap.bootstrap_database()
    assert conn.commits == 0 and conn.rollbacks == 1
    assert not any("INSERT" in statement for statement in conn.statements)


def test_cli_does_not_install_implicitly(monkeypatch: pytest.MonkeyPatch, metadata: ModuleType) -> None:
    conn = CatalogConnection()
    attach(monkeypatch, conn)
    assert bootstrap.main(["--contract", "completion_non_b1d_v1", "--check"]) == 0
    assert bootstrap.main(["--contract", "completion_non_b1d_v1", "--install"]) == 1
    assert conn.commits == 0


def test_client_endpoint_not_container_bridge_address_is_local_boundary() -> None:
    conn = CatalogConnection()
    conn.info.host = "untrusted.example"
    with pytest.raises(baseline.CompletionBaselineError, match="TARGET_REJECTED"):
        baseline.inspect_completion_target(connection(conn))
    assert conn.statements == []


def test_cli_rejects_unknown_values_with_only_safe_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert bootstrap.main(["--contract", "password=hidden-dsn"]) == 1
    assert capsys.readouterr().out.strip() == "COMPLETION_BASELINE_ARGUMENTS_REJECTED"


def test_uncanonicalized_sql_metadata_refuses_before_connection(metadata: ModuleType) -> None:
    setattr(metadata, "CATALOG_CANONICALIZED", False)
    with pytest.raises(baseline.CompletionBaselineError, match="CATALOG_NOT_CANONICAL"):
        baseline.check_completion_baseline()
    with pytest.raises(baseline.CompletionBaselineError, match="CATALOG_NOT_CANONICAL"):
        bootstrap.install_completion_baseline(expected_database_oid=901, maintenance_confirmed=True)


def test_public_composite_function_identity_is_resolved_without_sql_rewriting() -> None:
    signature = "item_supply_internal.check(tutor_item_supply_private_candidates,uuid,timestamptz)"
    assert baseline._resolve_signature(signature) == (
        "item_supply_internal.check(public.tutor_item_supply_private_candidates,uuid,timestamptz)"
    )
    assert baseline._resolve_signature("public.f(public.users,uuid)") == "public.f(public.users,uuid)"


def test_actual_authored_metadata_is_fail_closed_without_canonical_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import completion_baseline_contract as authored

    monkeypatch.setattr(authored, "CATALOG_CANONICALIZED", False)
    with pytest.raises(baseline.CompletionBaselineError, match="CATALOG_NOT_CANONICAL"):
        baseline.check_completion_baseline()


@pytest.mark.parametrize("name", ["BASE_FUNCTION_METADATA", "FUNCTION_METADATA"])
@pytest.mark.parametrize("bad_arity", [False, True])
def test_function_acl_and_row_shape_refuse_before_connection(metadata: ModuleType, name: str, bad_arity: bool) -> None:
    rows = list(getattr(metadata, name))
    row = list(rows[0])
    if bad_arity:
        row.pop()
    else:
        row[5] = (("PUBLIC", False), False)
    rows[0] = tuple(row)
    setattr(metadata, name, tuple(rows))
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INVALID"):
        baseline.check_completion_baseline()


@pytest.mark.parametrize("drift", [None, 1, 4, 9, 11, 13])
def test_exact_sequences_are_checked_not_ignored(metadata: ModuleType, drift: int | None) -> None:
    name = "public.tutor_item_supply_fixture_sequence_seq"
    expected = (name, "aearn_cb_schema_20261027", "bigint", 1, 1, 1,
                9223372036854775807, 1, False, "public.tutor_item_supply_fixture",
                "sequence", "i", "a", (("aearn_cb_schema_20261027", "USAGE", False),))
    setattr(metadata, "EXPECTED_SEQUENCES", (name,))
    setattr(metadata, "EXPECTED_SEQUENCE_METADATA", (expected,))
    setattr(metadata, "NEW_SEQUENCES", (name,))
    actual: list[object] = ["public.tutor_item_supply_fixture_sequence_seq", "aearn_cb_schema_20261027",
        "bigint", 1, 1, 1, 9223372036854775807, 1, False, "public.tutor_item_supply_fixture",
        "sequence", "i", "a", [["aearn_cb_schema_20261027", "USAGE", False]]]
    if drift is not None:
        actual[drift] = "drift"

    class SequenceConnection(CatalogConnection):
        def execute(self, statement: object, params: object = None) -> Cursor:
            if statement == baseline._CATALOG_QUERIES["SEQUENCE_METADATA"] and params == ([name],):
                self.statements.append(str(statement))
                self.parameters.append(params)
                return Cursor([{"item": actual}])
            return super().execute(statement, params)

    conn = SequenceConnection()
    target = baseline.inspect_completion_target(connection(conn))
    state = baseline.classify_completion_baseline(connection(conn), target=target)
    assert state is (baseline.BaselineState.COMPLETE if drift is None else baseline.BaselineState.PARTIAL_OR_UNKNOWN)
    presence = next(params for statement, params in zip(conn.statements, conn.parameters, strict=True)
                    if statement.startswith("SELECT 1 WHERE EXISTS (SELECT 1 FROM unnest"))
    assert name in cast(tuple[list[str], ...], presence)[0]
    if drift is None:
        for statement, params in zip(conn.statements, conn.parameters, strict=True):
            if statement.startswith("SELECT 1 WHERE EXISTS (SELECT 1 FROM pg_class"):
                assert name in cast(tuple[list[str], ...], params)[1]
    query = baseline._CATALOG_QUERIES["SEQUENCE_METADATA"]
    assert "pg_sequence" in query and "pg_depend" in query and "acldefault('S'" in query
    assert "last_value" not in query and "is_called" not in query


@pytest.mark.parametrize("dsn", [
    "postgresql://postgres:private@127.0.0.1/aearn_completion_b_validation_20261027",
    "host=127.0.0.1 dbname=postgres user=aearn_cb_runtime_20261027 password=private",
    "postgresql://aearn_cb_verifier_20261027:private@localhost/postgres",
    "postgresql://%61earn_cb_runtime_20261027:private@localhost/postgres",
])
def test_protected_effective_dsn_requires_selector(monkeypatch: pytest.MonkeyPatch, dsn: str) -> None:
    from app.core import config
    # The cached Settings value, not a subsequently changed DATABASE_URL env,
    # is the actual configuration used by the connection owner.
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:old@localhost/postgres")
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(database_url=dsn))
    with pytest.raises(baseline.CompletionBaselineError, match="^COMPLETION_BASELINE_CONTRACT_REQUIRED$"):
        baseline.ensure_startup_contract(entrypoint="asgi")
    with pytest.raises(baseline.CompletionBaselineError, match="^COMPLETION_BASELINE_CONTRACT_REQUIRED$"):
        bootstrap.bootstrap_database()


def test_genuine_legacy_dsn_is_no_db_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(database_url="postgresql://postgres:old@localhost/postgres"))
    baseline.ensure_startup_contract(entrypoint="worker")


def test_settings_loading_can_supply_selector_without_legacy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config
    events: list[str] = []

    def settings() -> SimpleNamespace:
        monkeypatch.setenv("AEARN_DATABASE_CONTRACT", "completion_non_b1d_v1")
        return SimpleNamespace(database_url="postgresql://aearn_cb_runtime_20261027:private@localhost/postgres")

    monkeypatch.setattr(config, "get_settings", settings)
    monkeypatch.setattr(baseline, "check_completion_baseline", lambda: events.append("strict-check"))
    baseline.ensure_startup_contract(entrypoint="asgi")
    assert events == ["strict-check"]


@pytest.mark.parametrize("dsn", ["password=secret invalid-option=value", "service=private_service"])
def test_unresolved_or_invalid_dsn_refuses_without_secret_disclosure(monkeypatch: pytest.MonkeyPatch, dsn: str) -> None:
    from app.core import config
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGDATABASE", raising=False)
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(database_url=dsn))
    with pytest.raises(baseline.CompletionBaselineError, match="^COMPLETION_BASELINE_CONFIGURATION_REJECTED$"):
        baseline.ensure_startup_contract(entrypoint="worker")


@pytest.mark.parametrize("field", ["BASE_TABLE_ACLS", "BASE_SCHEMA_METADATA"])
def test_missing_base_scope_is_rejected_before_connection(metadata: ModuleType, field: str) -> None:
    setattr(metadata, field, ())
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INCOMPLETE"):
        baseline.check_completion_baseline()


def test_catalog_capture_reasserts_path_and_preserves_raw_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_sql = "CREATE INDEX raw_idx ON public.users USING btree (((id)::text || 'public.keep_me'::text))"
    monkeypatch.setitem(_BASE_ACTUAL, "INDEXES", (("public.users", "raw_idx", raw_sql, True, True),))
    conn = CatalogConnection(present=False)
    query = baseline._CATALOG_QUERIES["INDEXES"]
    for ambient in ("public", "untrusted, public"):
        conn.search_path = ambient
        rows = baseline._rows(connection(conn), query, ("public.users",))
        assert rows == (("public.users", "raw_idx", raw_sql, True, True),)
    assert conn.statements == [
        "SET LOCAL search_path = pg_catalog, pg_temp", query,
        "SET LOCAL search_path = pg_catalog, pg_temp", query,
    ]
    assert conn.commits == conn.rollbacks == 0


@pytest.mark.parametrize("active", [False, True])
def test_catalog_capture_requires_effective_local_transaction(active: bool) -> None:
    conn = CatalogConnection(present=False)
    conn.autocommit = True
    conn.info.transaction_status = TransactionStatus.INTRANS if active else TransactionStatus.IDLE
    if active:
        baseline._rows(connection(conn), baseline._CATALOG_QUERIES["COLUMNS"], ("public.users",))
        assert conn.statements[0] == "SET LOCAL search_path = pg_catalog, pg_temp"
    else:
        with pytest.raises(baseline.CompletionBaselineError, match="TRANSACTION_REQUIRED"):
            baseline._rows(connection(conn), baseline._CATALOG_QUERIES["COLUMNS"], ("public.users",))
        assert conn.statements == []
    assert conn.commits == conn.rollbacks == 0


def test_ambient_bare_relation_metadata_is_not_normalized_into_acceptance(metadata: ModuleType) -> None:
    row = metadata.EXPECTED_RELATION_METADATA[0]
    setattr(metadata, "EXPECTED_RELATION_METADATA", (("identity", *row[1:]),))
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INCOMPLETE"):
        baseline.check_completion_baseline()


@pytest.mark.parametrize("drift", [None, "missing", "grantee", "privilege", "grantable", "extra-column"])
def test_column_acl_exact_grants_not_table_acl_equivalence(metadata: ModuleType, drift: str | None) -> None:
    setattr(metadata, "EXPECTED_COLUMN_ACLS", (("completion_baseline_internal.identity", "id",
                                             (("aearn_cb_runtime_20261027", "INSERT", False),)),))
    grant: list[object] = ["aearn_cb_runtime_20261027", "INSERT", False]
    if drift == "grantee":
        grant[0] = "PUBLIC"
    elif drift == "privilege":
        grant[1] = "UPDATE"
    elif drift == "grantable":
        grant[2] = True
    actual: tuple[tuple[object, ...], ...] = (
        ("completion_baseline_internal.identity", "id", (tuple(grant),)),
    )
    if drift == "missing":
        actual = ()
    elif drift == "extra-column":
        actual += (("completion_baseline_internal.identity", "unexpected", (("PUBLIC", "UPDATE", False),)),)
    conn = CatalogConnection()
    conn.column_acl_rows = actual
    target = baseline.inspect_completion_target(connection(conn))
    expected = baseline.BaselineState.COMPLETE if drift is None else baseline.BaselineState.PARTIAL_OR_UNKNOWN
    assert baseline.classify_completion_baseline(connection(conn), target=target) is expected
    query = baseline._CATALOG_QUERIES["COLUMN_ACLS"]
    assert "aclexplode(a.attacl)" in query and "a.attacl IS NOT NULL" in query
    assert "NOT a.attisdropped" in query and "a.attnum>0" in query
    assert "acldefault" not in query and "relacl" not in query


@pytest.mark.parametrize("expected_empty", [False, True])
def test_sparse_column_acl_distinguishes_null_from_explicit_empty(
    metadata: ModuleType, expected_empty: bool,
) -> None:
    empty = (("completion_baseline_internal.identity", "id", ()),)
    setattr(metadata, "EXPECTED_COLUMN_ACLS", empty if expected_empty else ())
    conn = CatalogConnection()
    target = baseline.inspect_completion_target(connection(conn))
    conn.column_acl_rows = empty if expected_empty else ()
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.COMPLETE
    conn.column_acl_rows = () if expected_empty else empty
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.PARTIAL_OR_UNKNOWN


def test_base_column_acl_must_match_before_absent_can_install(metadata: ModuleType) -> None:
    setattr(metadata, "BASE_COLUMN_ACLS", (("public.users", "id", (("postgres", "UPDATE", False),)),))
    conn = CatalogConnection(present=False)
    conn.column_acl_rows = (("public.users", "id", (("postgres", "UPDATE", False),)),)
    target = baseline.inspect_completion_target(connection(conn))
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.ABSENT
    conn.column_acl_rows = ()
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.PARTIAL_OR_UNKNOWN


@pytest.mark.parametrize("rows", [
    (("completion_baseline_internal.identity", "id", None),),
    (("completion_baseline_internal.identity", "id", (("PUBLIC", "UPDATE", "false"),)),),
    (("completion_baseline_internal.identity", "missing", ()),),
    (("completion_baseline_internal.identity", "id", ()), ("completion_baseline_internal.identity", "id", ())),
])
def test_malformed_or_duplicate_column_acl_metadata_is_fail_closed(metadata: ModuleType, rows: object) -> None:
    setattr(metadata, "EXPECTED_COLUMN_ACLS", rows)
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INVALID"):
        baseline.check_completion_baseline()


@pytest.fixture
def validation_metadata(metadata: ModuleType) -> ModuleType:
    # Independent purpose-only additions: neither belongs to runtime BASE.
    additions = {
        "BASE_TABLES": ("public.tutor_learning_items",),
        "BASE_COLUMNS": (("public.tutor_learning_items", "id", "uuid", True, "", None),),
        "BASE_RELATION_METADATA": (("public.tutor_learning_items", "postgres", "r", False, False),),
        "BASE_TABLE_ACLS": (("public.tutor_learning_items", (("postgres", "SELECT", False),)),),
        "BASE_FUNCTIONS": ("public.rag_registered_capture_guard()",),
        "BASE_FUNCTION_METADATA": (("public.rag_registered_capture_guard()", "postgres", False, "v",
                                    None, (("postgres", False),), "plpgsql", "trigger", False, "u",
                                    "BEGIN RETURN NEW; END"),),
        "BASE_LOCK_RELATIONS": ("public.tutor_learning_items",),
        "BASE_COLUMN_ACLS": (("public.tutor_learning_items", "id", (("postgres", "UPDATE", False),)),),
    }
    for name, extra in additions.items():
        setattr(metadata, "VALIDATION_" + name, getattr(metadata, name) + extra)
    return metadata


def test_validation_base_overlay_is_complete_and_keeps_runtime_scope(validation_metadata: ModuleType) -> None:
    runtime = baseline._metadata()
    validation = baseline._metadata(storage_check=True)
    assert runtime.BASE_TABLES == ("public.users",)
    assert validation.BASE_TABLES == ("public.users", "public.tutor_learning_items")
    assert runtime.BASE_FUNCTIONS == ("public.old_guard()",)
    assert validation.BASE_FUNCTIONS == ("public.old_guard()", "public.rag_registered_capture_guard()")
    assert runtime.BASE_COLUMN_ACLS == ()
    assert validation.BASE_COLUMN_ACLS == (
        ("public.tutor_learning_items", "id", (("postgres", "UPDATE", False),)),
    )
    for name in baseline._BASE_EXPORTS:
        assert getattr(validation, name) == getattr(validation_metadata, "VALIDATION_" + name)
    # No missing validation BASE category may silently inherit runtime values.
    for name in baseline._BASE_EXPORTS:
        key = "VALIDATION_" + name
        value = getattr(validation_metadata, key)
        delattr(validation_metadata, key)
        with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INCOMPLETE"):
            baseline._metadata(storage_check=True)
        setattr(validation_metadata, key, value)


def test_validation_installer_locks_actual_purpose_parents(
    validation_metadata: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    fragments = (
        SchemaFragment("599_completion_non_b1d_baseline.sql", tmp_path / "599.sql", "FORWARD FIXTURE DDL"),
        SchemaFragment("601_completion_non_b1d_inventory_reads.sql", tmp_path / "601.sql", "INVENTORY READS FIXTURE DDL"),
        SchemaFragment("602_completion_non_b1d_planning_catalog_reads.sql", tmp_path / "602.sql", "PLANNING CATALOG READS FIXTURE DDL"),
        SchemaFragment("600_completion_non_b1d_validation.sql", tmp_path / "600.sql", "VALIDATION FIXTURE DDL"),
    )
    monkeypatch.setattr(bootstrap, "load_schema_fragments", lambda **kwargs: fragments)
    states = iter((baseline.BaselineState.ABSENT, baseline.BaselineState.COMPLETE))
    monkeypatch.setattr(bootstrap, "classify_completion_baseline", lambda *args, **kwargs: next(states))
    conn = CatalogConnection(present=False, database="aearn_completion_b_validation_20261027")
    attach(monkeypatch, conn)
    bootstrap.candidate_completion_baseline(expected_database_oid=901, maintenance_confirmed=True, storage_check=True)
    locks = [statement for statement in conn.statements if "LOCK TABLE" in statement]
    assert len(locks) == 2
    assert "users" in locks[0] and "tutor_learning_items" in locks[1]
    assert conn.statements.index(locks[1]) < conn.statements.index("FORWARD FIXTURE DDL")
    assert [statement for statement in conn.statements if statement.endswith("FIXTURE DDL")] == [
        "FORWARD FIXTURE DDL", "INVENTORY READS FIXTURE DDL",
        "PLANNING CATALOG READS FIXTURE DDL", "VALIDATION FIXTURE DDL",
    ]
    assert validation_metadata.BASE_LOCK_RELATIONS == ("public.users",)
    assert conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize("new_function", ["public.old_guard()", "public.unexpected()"])
def test_new_function_presence_scope_cannot_include_replaced_or_undeclared_functions(
    metadata: ModuleType, new_function: str,
) -> None:
    setattr(metadata, "NEW_FUNCTIONS", (new_function,))
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INVALID"):
        baseline.check_completion_baseline()


@pytest.mark.parametrize("base", [False, True])
@pytest.mark.parametrize("storage_check", [False, True])
def test_public_capture_uses_same_explicit_path_for_every_purpose_and_phase(
    validation_metadata: ModuleType, base: bool, storage_check: bool,
) -> None:
    # Raw capture must be possible before canonicalization, but must not grant
    # readiness. A deliberately distinct validation post scope catches fallback.
    setattr(validation_metadata, "CATALOG_CANONICALIZED", False)
    setattr(validation_metadata, "VALIDATION_EXPECTED_TABLES", ("completion_baseline_internal.validation_post",))
    # Actual authored metadata deliberately has empty post-canonical outputs.
    for name in ("EXPECTED_SCHEMA_METADATA", "VALIDATION_EXPECTED_SCHEMA_METADATA",
                 "FUNCTION_METADATA", "VALIDATION_FUNCTION_METADATA"):
        setattr(validation_metadata, name, ())
    conn = CatalogConnection(present=not base)
    captured = baseline.capture_completion_catalog(
        connection(conn), metadata=validation_metadata, base=base, storage_check=storage_check,
    )
    assert set(captured) == set(baseline._CATALOG_QUERIES)
    assert "COLUMN_ACLS" in captured
    if base:
        tables = ["public.users", "public.tutor_learning_items"] if storage_check else ["public.users"]
        functions = (["public.old_guard()", "public.rag_registered_capture_guard()"]
                     if storage_check else ["public.old_guard()"])
    else:
        tables = (["completion_baseline_internal.validation_post"] if storage_check
                  else ["completion_baseline_internal.identity"])
        functions = ["completion_baseline_internal.contract_identity()"]
    for index in range(0, len(conn.statements), 2):
        assert conn.statements[index] == "SET LOCAL search_path = pg_catalog, pg_temp"
    for category in ("RELATION_METADATA", "COLUMNS", "COLUMN_ACLS", "TABLE_ACLS"):
        index = conn.statements.index(baseline._CATALOG_QUERIES[category])
        assert conn.parameters[index] == (tables,)
    index = conn.statements.index(baseline._CATALOG_QUERIES["FUNCTION_METADATA"])
    assert conn.parameters[index] == (functions, functions)
    index = conn.statements.index(baseline._CATALOG_QUERIES["SCHEMA_METADATA"])
    schemas = ["public"] if base else ["completion_baseline_internal", "public"]
    assert conn.parameters[index] == (schemas,)
    assert validation_metadata.CATALOG_CANONICALIZED is False
    assert conn.commits == conn.rollbacks == 0
    with pytest.raises(baseline.CompletionBaselineError, match="CATALOG_NOT_CANONICAL"):
        baseline.check_completion_baseline(storage_check=storage_check)


@pytest.fixture
def constraint_variants(metadata: ModuleType, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # Extend the tiny catalog with the exact approved identities, but synthetic
    # CHECK bodies. This tests dispatch/comparison, not the actual PG constraint.
    tables = tuple(sorted({table for table, _ in _DEVELOPMENT_IDENTITIES}))
    columns = tuple(row for table in tables for row in (
        (table, "a", "integer", True, "", None),
        (table, "b", "boolean", True, "", None),
    ))
    additions = {
        "RELATION_METADATA": tuple((table, "postgres", "r", False, False) for table in tables),
        "COLUMNS": columns,
        "TABLE_ACLS": tuple((table, (("postgres", "SELECT", False),)) for table in tables),
        "CONSTRAINTS": tuple(pair[0] for pair in _CONSTRAINT_VARIANTS),
    }
    for prefix, actual in (("BASE_", _BASE_ACTUAL), ("EXPECTED_", _ACTUAL)):
        setattr(metadata, prefix + "TABLES", getattr(metadata, prefix + "TABLES") + tables)
        for category, extra in additions.items():
            setattr(metadata, prefix + category, getattr(metadata, prefix + category) + extra)
            monkeypatch.setitem(actual, category, actual[category] + extra)
    for name in (*baseline._BASE_EXPORTS, *baseline._POSTINSTALL_EXPORTS):
        setattr(metadata, "VALIDATION_" + name, getattr(metadata, name))
    return metadata


@pytest.mark.parametrize("base", [False, True])
@pytest.mark.parametrize("database", ["postgres", "aearn_completion_b_test_20261026", "aearn_completion_b_validation_20261027"])
@pytest.mark.parametrize("development_rows", [False, True])
def test_fixed_development_constraint_variant_is_bound_to_actual_target(
    constraint_variants: ModuleType, monkeypatch: pytest.MonkeyPatch,
    base: bool, database: str, development_rows: bool,
) -> None:
    actual = _BASE_ACTUAL if base else _ACTUAL
    if development_rows:
        # The first unrelated pkey remains unchanged; only these 13 raw rows vary.
        monkeypatch.setitem(actual, "CONSTRAINTS", (actual["CONSTRAINTS"][0],) +
                            tuple(pair[1] for pair in _CONSTRAINT_VARIANTS))
    conn = CatalogConnection(present=not base, database=database)
    target = baseline.inspect_completion_target(
        connection(conn), storage_check=database == "aearn_completion_b_validation_20261027",
    )
    state = baseline.classify_completion_baseline(connection(conn), target=target)
    accepted = development_rows == (database == "postgres")
    expected = baseline.BaselineState.ABSENT if base else baseline.BaselineState.COMPLETE
    assert state is (expected if accepted else baseline.BaselineState.PARTIAL_OR_UNKNOWN)
    assert constraint_variants.BASE_CONSTRAINTS[-1][3] == _CLONE_CHECK
    assert constraint_variants.EXPECTED_CONSTRAINTS[-1][3] == _CLONE_CHECK
    assert conn.commits == conn.rollbacks == 0


@pytest.mark.parametrize("base", [False, True])
def test_validation_keeps_its_own_complete_constraint_overlay(
    constraint_variants: ModuleType, monkeypatch: pytest.MonkeyPatch, base: bool,
) -> None:
    raw_validation = "CHECK ((b AND (a >= 0) AND (a <= 1)))"
    rows = tuple((*key, "c", raw_validation, True, False, False) for key in _DEVELOPMENT_IDENTITIES)
    actual = _BASE_ACTUAL if base else _ACTUAL
    expected = (actual["CONSTRAINTS"][0],) + rows
    monkeypatch.setitem(actual, "CONSTRAINTS", expected)
    field = "VALIDATION_BASE_CONSTRAINTS" if base else "VALIDATION_EXPECTED_CONSTRAINTS"
    setattr(constraint_variants, field, expected)
    conn = CatalogConnection(present=not base, database="aearn_completion_b_validation_20261027")
    target = baseline.inspect_completion_target(connection(conn), storage_check=True)
    assert baseline.classify_completion_baseline(connection(conn), target=target) is (
        baseline.BaselineState.ABSENT if base else baseline.BaselineState.COMPLETE
    )
    # Even a mismatched database name alone cannot activate the development patch.
    guarded_target = baseline.CompletionTarget(901, "postgres", "storage-validation-purpose", "postgres")
    validation = baseline._metadata(storage_check=True)
    assert baseline._metadata_for_target(validation, target=guarded_target) is validation


@pytest.mark.parametrize("drift", ["known-definition", "unrelated-definition", "extra-constraint"])
def test_development_constraint_overlay_does_not_accept_unknown_drift(
    constraint_variants: ModuleType, monkeypatch: pytest.MonkeyPatch, drift: str,
) -> None:
    rows = [_ACTUAL["CONSTRAINTS"][0], *(pair[1] for pair in _CONSTRAINT_VARIANTS)]
    if drift == "extra-constraint":
        rows.append(("public.tutor_conversations", "unreviewed_check", "c", "CHECK (true)", True, False, False))
    else:
        index = 1 if drift == "known-definition" else 0
        row = rows[index]
        rows[index] = (*row[:3], "CHECK ((a > 999))", *row[4:])
    monkeypatch.setitem(_ACTUAL, "CONSTRAINTS", tuple(rows))
    conn = CatalogConnection(database="postgres")
    target = baseline.inspect_completion_target(connection(conn))
    assert baseline.classify_completion_baseline(connection(conn), target=target) is baseline.BaselineState.PARTIAL_OR_UNKNOWN


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown-key", "changed-flag", "changed-identity"])
def test_development_constraint_pair_abi_is_exact_and_fail_closed(
    metadata: ModuleType, fault: str,
) -> None:
    pairs = list(_CONSTRAINT_VARIANTS)
    if fault == "missing":
        pairs.pop()
    elif fault == "duplicate":
        pairs[-1] = pairs[0]
    elif fault == "unknown-key":
        source, development = pairs[-1]
        pairs[-1] = (("public.unapproved", *source[1:]), ("public.unapproved", *development[1:]))
    else:
        source, development = pairs[-1]
        if fault == "changed-flag":
            development = (*development[:4], False, *development[5:])
        else:
            development = ("public.unapproved", *development[1:])
        pairs[-1] = (source, development)
    setattr(metadata, "DEVELOPMENT_CONSTRAINT_OVERRIDES", tuple(pairs))
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_(INCOMPLETE|INVALID)"):
        baseline.check_completion_baseline()


@pytest.mark.parametrize("phase", ["BASE_CONSTRAINTS", "EXPECTED_CONSTRAINTS"])
def test_development_patch_requires_original_clone_row_in_both_phases(
    constraint_variants: ModuleType, phase: str,
) -> None:
    rows = list(getattr(constraint_variants, phase))
    row = rows[-1]
    rows[-1] = (*row[:3], "CHECK ((a > 999))", *row[4:])
    setattr(constraint_variants, phase, tuple(rows))
    target = baseline.CompletionTarget(901, "postgres", "runtime-purpose", "postgres")
    with pytest.raises(baseline.CompletionBaselineError, match="METADATA_INVALID"):
        baseline._metadata_for_target(constraint_variants, target=target)
