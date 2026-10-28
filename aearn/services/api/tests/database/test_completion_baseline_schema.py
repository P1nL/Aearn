"""Offline checks for the independently authored completion baseline contract."""

import ast
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "app" / "db" / "schema"
CONTRACT_PATH = ROOT / "app" / "db" / "completion_baseline_contract.py"
spec = importlib.util.spec_from_file_location("baseline_contract_offline", CONTRACT_PATH)
assert spec is not None and spec.loader is not None
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
BASELINE = (SCHEMA / "599_completion_non_b1d_baseline.sql").read_text(encoding="utf-8")
VALIDATION = (SCHEMA / "600_completion_non_b1d_validation.sql").read_text(encoding="utf-8")
INVENTORY_READS = (SCHEMA / "601_completion_non_b1d_inventory_reads.sql").read_text(encoding="utf-8")
PLANNING_CATALOG_READS = (SCHEMA / "602_completion_non_b1d_planning_catalog_reads.sql").read_text(encoding="utf-8")


def test_static_contract_has_no_import_or_io() -> None:
    tree = ast.parse(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom, ast.Call)) for node in ast.walk(tree))
    assert contract.CONTRACT_ID == "completion_non_b1d_v1"
    assert contract.RUNTIME_DATABASE_NAMES == ("postgres", "aearn_completion_b_test_20261026")
    assert contract.VALIDATION_DATABASE_NAME == "aearn_completion_b_validation_20261027"
    assert contract.CATALOG_CANONICALIZED is True
    # True means Main captured the complete catalog, not installed/business PASS.
    # The loader suite independently retains the False -> fail-closed regression.


def test_fragment_plans_are_fixed_and_purpose_separated() -> None:
    assert contract.RUNTIME_FORWARD_FRAGMENT_NAMES == (
        "599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
        "602_completion_non_b1d_planning_catalog_reads.sql",
    )
    assert contract.VALIDATION_FORWARD_FRAGMENT_NAMES == contract.FORWARD_FRAGMENT_NAMES
    assert contract.FORWARD_FRAGMENT_NAMES == (
        "599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
        "602_completion_non_b1d_planning_catalog_reads.sql",
        "600_completion_non_b1d_validation.sql",
    )
    assert "current_database()<>'aearn_completion_b_validation_20261027'" in VALIDATION
    assert "i.purpose='storage-validation-purpose'" in VALIDATION
    assert "d.oid=i.database_oid AND d.datname=i.database_name" in VALIDATION


def test_mandatory_inventory_and_explicit_fk_closure() -> None:
    storage_path = ROOT / "app/services/learning/item_supply/storage_tables.py"
    namespace: dict[str, object] = {}
    exec(compile(storage_path.read_text(encoding="utf-8"), str(storage_path), "exec"), namespace)
    private_tables = namespace["PRIVATE_TABLES"]
    epoch_table = namespace["EPOCH_TABLE"]
    assert isinstance(private_tables, tuple) and isinstance(epoch_table, str)
    mandatory = set(private_tables) | {epoch_table}
    assert len(mandatory) == 66
    assert {"public." + name for name in mandatory} <= set(contract.NEW_TABLES)
    available = set(contract.EXPECTED_TABLES)
    for table, ddl in contract.AUTHORED_RELATION_DEFINITIONS:
        assert table in contract.NEW_TABLES
        for target in re.findall(r"\bREFERENCES\s+(?:public\.)?(\w+)", ddl, re.I):
            assert "public." + target in available, (table, target)
    assert set(contract.NEW_TABLES).isdisjoint(contract.BASE_TABLES)
    assert len(contract.BASE_TABLES) < 205


def test_roles_are_fixed_without_password_or_role_membership() -> None:
    rows = {row[0]: row for row in contract.EXPECTED_ROLE_METADATA}
    for name, row in rows.items():
        assert row[1:5] == (False, False, False, False)
        assert row[6:8] == (False, False)
        assert row[5] is (name != contract.SCHEMA_ROLE)
    assert contract.EXPECTED_ROLE_MEMBERSHIPS == ()
    assert "PASSWORD" not in BASELINE.upper()
    assert "PASSWORD" not in VALIDATION.upper()
    assert "shobj_description(p.oid,'pg_authid')" in BASELINE
    for role in rows:
        assert not re.search(rf"GRANT\s+{role}\s+TO", BASELINE, re.I)


def test_identity_is_protected_but_not_the_only_catalog_expectation() -> None:
    assert "completion_baseline_internal.installation_identity" in contract.NEW_TABLES
    assert "completion_baseline_internal.contract_identity()" in contract.NEW_FUNCTIONS
    assert len(contract.AUTHORED_RELATION_DEFINITIONS) >= 82
    assert len(contract.EXPECTED_TRIGGERS) > 200
    assert len(contract.EXPECTED_FUNCTION_POLICIES) == len(contract.AUTHORED_FUNCTION_SIGNATURES)
    assert "i.database_oid AND d.datname=i.database_name" in BASELINE
    assert "installation identity immutable" in BASELINE


def test_business_denials_are_executable_policy_not_success_stubs() -> None:
    functions = {row[0]: row for row in contract.FUNCTION_METADATA}
    policies = dict(contract.EXPECTED_FUNCTION_POLICIES)
    denied = [sig for sig, policy in policies.items() if policy == "explicit_business_denial"]
    assert denied
    for sig in denied:
        body = functions[sig][-1]
        assert "RAISE EXCEPTION" in body and "ERRCODE='42501'" in body
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|RETURN\s+true)\b", body, re.I)
    assert "P2/P7 business storage denied" in BASELINE
    assert "P2/P7 original consumer denied" in BASELINE


def test_normal_origin_hooks_and_unassigned_record_regression() -> None:
    triggers = {(row[0], row[1], row[2]) for row in contract.EXPECTED_TRIGGERS}
    assert ("public.users", "native_exposure_birth_capture", "public.capture_native_exposure_birth()") in triggers
    for table in (
        "tutor_learning_artifact_events", "tutor_knowledge_check_assistance_receipts",
        "tutor_exercise_attempts", "tutor_exercise_hint_receipts", "tutor_lesson_gate_bindings",
    ):
        assert ("public." + table, "native_exposure_origin_capture", "public.capture_native_exposure_origin()") in triggers
    functions = {row[0]: row for row in contract.FUNCTION_METADATA}
    origin = functions["public.capture_native_exposure_origin()"][-1]
    assert "artifact_uuid uuid" in origin
    assert "artifact_uuid:=a.id" in origin
    assert "WHERE artifact_id=artifact_uuid" in origin
    assert "WHERE artifact_id=a.id" not in origin
    assert "ON CONFLICT DO NOTHING" in origin
    assert "snapshot_hash(raw)" in origin


def test_formal_purge_is_shared_by_runtime_and_validation_and_retains_audit() -> None:
    functions = {row[0]: row for row in contract.FUNCTION_METADATA}
    purge = functions["public.purge_item_supply_private(uuid,boolean)"][-1]
    assert "FOR UPDATE" in purge
    assert "INSERT INTO item_supply_internal.reset_permits" in purge
    assert "epoch=epoch+1,enabled=NOT deleting" in purge
    assert "IF NOT EXISTS(SELECT 1 FROM rag_assessment_source_evidence" in purge
    assert "RETURN new_epoch" in purge
    assert "parent_candidate_id" in purge and "parent_job_id" in purge
    tail = functions["public.rag_actual_d_private_purge(uuid)"][-1]
    assert "e.private_epoch<active_epoch" in tail
    assert "original D children first" in tail
    assert "DELETE FROM item_supply_internal.reset_permits" in tail
    deferred = functions["item_supply_internal.assert_actual_d_private_reset_complete()"][-1]
    assert "original reset tail incomplete" in deferred
    assert "DEFERRABLE INITIALLY DEFERRED" in BASELINE
    for table in ("tutor_runs", "tutor_run_execution_batches", "tutor_run_step_attempts", "tutor_run_runtime_bindings"):
        assert not re.search(rf"DELETE FROM\s+(?:public\.)?{table}\b", purge)
    assert not re.search(
        r"^CREATE(?: OR REPLACE)? FUNCTION (?:public\.)?purge_item_supply_private\(",
        VALIDATION, re.M | re.I,
    )


def test_validation_receivers_are_finite_and_caller_bound() -> None:
    assert "current_setting('role') NOT IN('none','aearn_cb_verifier_20261027')" in VALIDATION
    assert "session_user<>'aearn_cb_verifier_20261027'" in VALIDATION
    assert "completion_baseline_internal.contract_identity()" in VALIDATION
    assert "RETURNS TABLE(scope_id uuid,material_id uuid,parent_candidate_id uuid,child_candidate_id uuid,version_id uuid,shared_matrix_id uuid)" in VALIDATION
    assert "RETURNS TABLE(task_id uuid,attachment_id uuid)" in VALIDATION
    # 600 now owns additional explicitly authorized validation-only guards and
    # non-success graphs. Keep the original two receiver regressions scoped to
    # their bodies, rather than rejecting every legitimate new trigger/source row.
    for name in ("issue_private_graph", "issue_journal_graph"):
        definition = re.search(
            r"CREATE FUNCTION completion_baseline_internal\." + name
            + r"\(.*?AS \$\$(.*?)\$\$;", VALIDATION, re.S,
        )
        assert definition is not None
        body = definition[1]
        assert "assert_validation_caller()" in body
        assert "jsonb_populate_record" not in body and "EXECUTE format" not in body
        assert "not_business_eligible" in body
        assert "DELETE FROM completion_baseline_internal.validation_permits" in body
        for table in (
            "tutor_item_supply_private_native_quality_evidence", "rag_assessment_source_evidence",
            "tutor_item_supply_private_usage_events", "tutor_learning_item_native_publication_proofs",
        ):
            assert not re.search(rf"INSERT INTO\s+(?:public\.)?{table}\b", body)
        assert "GRANT EXECUTE ON FUNCTION completion_baseline_internal." + name in VALIDATION
    assert "'source_readiness','not_evaluated'" in VALIDATION


def test_current_constraints_and_generated_identities_remain_present() -> None:
    assert "GENERATED ALWAYS AS" in BASELINE
    assert "supply_runtime_allocation_owner_resource" in BASELINE
    assert "private_native_epoch>=1" in BASELINE
    assert "not_asserted_for_mvp" in BASELINE
    assert "'00:10:00'::interval" in BASELINE
    assert "'blind_data'" in BASELINE
    assert "SET LOCAL search_path=public,pg_catalog" in BASELINE
    assert "session_replication_role" not in BASELINE
    assert not re.search(r"DISABLE\s+TRIGGER|DROP\s+TABLE|TRUNCATE\s+TABLE", BASELINE, re.I)


def test_function_acl_rows_have_independent_grantee_pairs() -> None:
    for rows in (contract.BASE_FUNCTION_METADATA, contract.FUNCTION_METADATA,
                 contract.VALIDATION_FUNCTION_METADATA):
        for row in rows:
            assert isinstance(row[5], tuple)
            assert all(isinstance(acl, tuple) and len(acl) == 2
                       and isinstance(acl[0], str) and isinstance(acl[1], bool)
                       for acl in row[5]), row[0]
            assert (row[1], False) in row[5], row[0]


def test_sequences_are_finite_owned_schema_objects_not_ignored_extras() -> None:
    assert len(contract.NEW_SEQUENCES) == 2
    assert set(contract.NEW_SEQUENCES).isdisjoint(contract.NEW_TABLES)
    assert contract.BASE_SEQUENCES == contract.BASE_SEQUENCE_METADATA == ()
    assert contract.VALIDATION_NEW_SEQUENCES == contract.NEW_SEQUENCES
    assert {row[0] for row in contract.EXPECTED_SEQUENCE_METADATA} == set(contract.NEW_SEQUENCES)
    for row in contract.EXPECTED_SEQUENCE_METADATA:
        assert row[1] == contract.SCHEMA_ROLE
        assert row[2:9] == ('bigint', 1, 1, 1, 9223372036854775807, 1, False)
        assert row[9] in contract.NEW_TABLES and row[10] == 'sequence'
        assert (row[11], row[12]) in (('i', 'a'), ('a', ''))
        assert {acl[0] for acl in row[13]} == {contract.SCHEMA_ROLE}
        assert f'ALTER SEQUENCE {row[0]} OWNER TO {contract.SCHEMA_ROLE}' in BASELINE
        assert f'REVOKE ALL ON SEQUENCE {row[0]} FROM PUBLIC,{contract.RUNTIME_ROLE},{contract.VERIFIER_ROLE}' in BASELINE


def _base_table_grants(role: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for privileges, tables, grantee in re.findall(
        r"GRANT\s+([A-Z, ]+)\s+ON TABLE\s+([\w.,\s]+?)\s+TO\s+(\w+);", BASELINE, re.I,
    ):
        if grantee != role:
            continue
        for table in tables.replace("\n", "").split(","):
            table = table.strip()
            if table in contract.BASE_TABLES:
                result.setdefault(table, set()).update(p.strip() for p in privileges.split(","))
    order = ("SELECT", "INSERT", "UPDATE", "DELETE")
    return {table: tuple(p for p in order if p in rights) for table, rights in result.items()}


def test_runtime_and_definer_grants_match_audited_consumer_matrices() -> None:
    for role, rows, evidence in (
        (contract.RUNTIME_ROLE, contract.RUNTIME_BASE_TABLE_PRIVILEGES, contract.RUNTIME_TABLE_PERMISSION_SOURCES),
        (contract.SCHEMA_ROLE, contract.SCHEMA_DEFINER_BASE_TABLE_PRIVILEGES, contract.SCHEMA_DEFINER_PERMISSION_SOURCES),
    ):
        assert _base_table_grants(role) == dict(rows)
        required = {(table, privilege) for table, privileges in rows for privilege in privileges}
        assert required == {(table, privilege) for table, privilege, sources in evidence if sources}
        assert all(table in contract.BASE_TABLES for table, _privileges in rows)
    runtime = dict(contract.RUNTIME_BASE_TABLE_PRIVILEGES)
    assert runtime["public.harness_cutovers"] == ("SELECT", "INSERT", "UPDATE")
    assert runtime["public.learner_profiles"] == ("SELECT", "DELETE")
    assert {"SELECT", "INSERT", "DELETE"} <= set(runtime["public.tutor_track_plan_modules"])
    assert runtime["public.grounding_chunks"] == ("SELECT",)
    assert runtime["public.tutor_catalog_snapshots"] == ("SELECT", "INSERT")
    assert "INSERT" in runtime["public.tutor_run_skill_selections"]
    assert "public.tutor_skill_versions" not in runtime
    assert "public.rag_registered_source_policies" not in runtime
    assert "ALL TABLES IN SCHEMA" not in BASELINE.upper()
    assert "GRANT ALL" not in BASELINE.upper()


def test_protected_reference_row_lock_is_not_runtime_update_authority() -> None:
    functions = {row[0]: row for row in contract.FUNCTION_METADATA}
    ref = functions["public.rag_actual_d_private_reference_guard()"]
    assert ref[1] == contract.SCHEMA_ROLE and ref[2] is True
    assert ref[4] == ("search_path=pg_catalog, public, item_supply_internal, pg_temp",)
    assert "FOR SHARE" in ref[-1]
    assert "public.rag_assessment_source_evidence" not in dict(contract.RUNTIME_BASE_TABLE_PRIVILEGES)
    assert "GRANT SELECT ON TABLE public.rag_assessment_source_evidence TO " + contract.RUNTIME_ROLE in BASELINE
    definer = dict(contract.SCHEMA_DEFINER_BASE_TABLE_PRIVILEGES)
    assert definer["public.users"] == ("SELECT", "UPDATE")
    assert definer["public.tutor_track_active_plans"] == ("SELECT", "UPDATE")
    assert all("INSERT" not in rights for _table, rights in contract.SCHEMA_DEFINER_BASE_TABLE_PRIVILEGES)


def test_public_maintenance_checks_identity_before_empty_or_lock_paths() -> None:
    functions = {row[0]: row for row in contract.FUNCTION_METADATA}
    for sig, first_effect in (
        ("public.purge_item_supply_private(uuid,boolean)", "PERFORM 1 FROM users"),
        ("public.rag_actual_d_private_purge(uuid)", "IF target_user IS NULL"),
        ("public.rag_actual_d_private_epoch(uuid,bigint,boolean)", "IF target_user IS NULL"),
    ):
        body = functions[sig][-1]
        assert body.index("PERFORM * FROM completion_baseline_internal.contract_identity();") < body.index(first_effect)


def test_source_ddl_statement_boundaries_preserve_exact_predecessor_locks() -> None:
    old = {row[0]: row[-1] for row in contract.BASE_FUNCTION_METADATA}
    locks = re.findall(r"\$expected\$(.*?)\$expected\$", BASELINE, re.S)
    assert len(locks) == 3
    for definition in locks:
        name = re.search(r"FUNCTION (public\.rag_source_\w+)\(\)", definition)
        assert name is not None
        body = definition.split("AS $function$", 1)[1].split("$function$", 1)[0]
        assert old[name[1] + "()"] == body
        actual = re.search(
            r"^CREATE OR REPLACE FUNCTION " + re.escape(name[1])
            + r"\(\).*?AS \$function\$(.*?)\$function\$;", BASELINE, re.M | re.S,
        )
        assert actual is not None
        assert "Independent forward503 maintenance branch" in actual[1]
    assert "item_supply_internal.check_execution_intent(uuid)" in contract.NEW_FUNCTIONS
    assert not re.search(r"AS \$\s*$|^END \$;", BASELINE, re.M)


def _sql_lexemes(sql: str) -> list[tuple[str, str, int, int]]:
    """Recognize protected SQL spans before inspecting punctuation (offline only)."""
    result: list[tuple[str, str, int, int]] = []
    i = 0
    while i < len(sql):
        start = i
        if sql.startswith("--", i):
            end = sql.find("\n", i + 2)
            i = len(sql) if end < 0 else end
            kind = "comment"
        elif sql.startswith("/*", i):
            depth = 1
            i += 2
            while i < len(sql) and depth:
                if sql.startswith("/*", i):
                    depth += 1
                    i += 2
                elif sql.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            assert depth == 0, "unterminated SQL block comment"
            kind = "comment"
        elif sql[i] in "'\"" or (
            sql[i:i + 2].lower() == "e'"
            and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_"))
        ):
            escape = sql[i:i + 2].lower() == "e'"
            quote = "'" if escape else sql[i]
            i += 2 if escape else 1
            closed = False
            while i < len(sql):
                if escape and sql[i] == "\\":
                    i += 2
                elif sql[i] == quote:
                    i += 1
                    if i < len(sql) and sql[i] == quote:
                        i += 1
                    else:
                        closed = True
                        break
                else:
                    i += 1
            assert closed, "unterminated SQL quoted span"
            kind = "identifier" if quote == '"' else "literal"
        elif sql[i] == "$" and (
            tag := re.match(r"\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$", sql[i:])
        ):
            marker = tag[0]
            end = sql.find(marker, i + len(marker))
            assert end >= 0, "unterminated SQL dollar quote"
            i = end + len(marker)
            kind = "literal"
        else:
            i += 1
            kind = "code"
        result.append((kind, sql[start:i], start, i))
    return result


def _sql_comma_parts(sql: str) -> list[str]:
    depth = 0
    start = 0
    parts: list[str] = []
    for kind, text, begin, end in _sql_lexemes(sql):
        if kind != "code":
            continue
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
        elif text == "," and depth == 0:
            parts.append(sql[start:begin].strip())
            start = end
        assert depth >= 0, "unbalanced SQL parentheses"
    assert depth == 0, "unbalanced SQL parentheses"
    parts.append(sql[start:].strip())
    return parts


def _table_body(ddl: str) -> str:
    depth = 0
    start: int | None = None
    for kind, text, begin, end in _sql_lexemes(ddl):
        if kind != "code":
            continue
        if text == "(":
            if start is None:
                start = end
            depth += 1
        elif text == ")":
            depth -= 1
            if depth == 0:
                assert start is not None
                return ddl[start:begin]
    raise AssertionError("missing complete CREATE TABLE body")


def test_sql_comma_boundaries_preserve_comments_and_quoted_spans() -> None:
    # The C0 failure split a comment into one comment and one executable line.
    # Include every protected comma form, not just that particular English text.
    parts = [
        "id uuid PRIMARY KEY",
        "-- Expected proof, not an FK: event -> proof.\nproof_id uuid NOT NULL",
        "payload text DEFAULT 'a,b(''c,d'')'",
        '"column,with,commas" text',
        r"escaped text DEFAULT E'a\',b'",
        "body text DEFAULT $body$a,b,(--literal)$$$body$",
        "/* outer, ( /* nested, ) */ still, comment */ count integer CHECK(count IN (1,2))",
    ]
    assert _sql_comma_parts(",\n".join(parts)) == parts
    for original, emitted in zip(parts, _sql_comma_parts(",\n".join(parts)), strict=True):
        assert [(k, s) for k, s, _, _ in _sql_lexemes(original) if k != "code"] == [
            (k, s) for k, s, _, _ in _sql_lexemes(emitted) if k != "code"
        ]


def test_all_authored_table_clauses_have_lexical_boundaries_and_match_sql() -> None:
    count = 0
    column_type = (
        r"uuid|bigint|bigserial|integer|int|text|jsonb|boolean|timestamptz|"
        r"timestamp|numeric|smallint|bytea|double|real|date|interval"
    )
    for table, ddl in contract.AUTHORED_RELATION_DEFINITIONS:
        if not ddl.startswith("-- Structural identity source "):
            continue
        count += 1
        # read_text normalizes physical CRLF, while the literal metadata retains it.
        assert BASELINE.count(ddl.replace("\r\n", "\n")) == 1, table
        for part in _sql_comma_parts(_table_body(ddl)):
            visible = "".join(s for kind, s, _, _ in _sql_lexemes(part) if kind != "comment").strip()
            assert re.match(
                rf"(?:[a-z_][a-z0-9_]*\s+(?:{column_type})\b|"
                r"(?:CONSTRAINT\s+\w+\s+)?(?:CHECK|UNIQUE|PRIMARY\s+KEY|FOREIGN\s+KEY)\s*\()",
                visible, re.I,
            ), (table, visible)
    assert count == 82


def test_frozen_structural_comments_and_comma_literals_survive_authorship() -> None:
    count = 0
    comments = 0
    for table, ddl in contract.AUTHORED_RELATION_DEFINITIONS:
        source = re.match(r"-- Structural identity source (\d+_[\w.]+\.sql);", ddl)
        if source is None:
            continue
        count += 1
        original = (SCHEMA / source[1]).read_text(encoding="utf-8")
        name = table.removeprefix("public.")
        declaration = re.search(
            r"\bCREATE TABLE(?: IF NOT EXISTS)? (?:public\.)?" + re.escape(name) + r"\s*\(",
            original, re.I,
        )
        assert declaration is not None, table
        before = _sql_lexemes(_table_body(original[declaration.start():]))
        after = _sql_lexemes(_table_body(ddl))
        before_comments = [s for kind, s, _, _ in before if kind == "comment"]
        after_comments = [s for kind, s, _, _ in after if kind == "comment"]
        assert before_comments == after_comments, table
        comments += len(before_comments)
        # Exact protected tokens catch commas/newlines accidentally inserted into
        # strings too. Intentional forward CHECK changes do not alter these tokens.
        after_literals = {s for kind, s, _, _ in after if kind == "literal"}
        for kind, text, _, _ in before:
            if kind == "literal" and "," in text:
                assert text in after_literals, (table, text)
    assert count == 82 and comments == 3


def _visible_sql(sql: str) -> str:
    return "".join(text for kind, text, _, _ in _sql_lexemes(sql) if kind != "comment").strip()


def _column_identity(part: str) -> str | None:
    match = re.match(r'("(?:[^"]|"")+"|[a-z_][a-z_0-9]*)\s+', _visible_sql(part), re.I)
    if match is None or match[1].upper() in {"CHECK", "CONSTRAINT", "UNIQUE", "PRIMARY", "FOREIGN"}:
        return None
    name = match[1]
    return name[1:-1].replace('""', '"') if name.startswith('"') else name.lower()


def _add_column(parts: list[str], declaration: str, *, if_not_exists: bool) -> list[str]:
    """ADD IF NOT EXISTS skips an existing identity; it never replaces its body."""
    name = _column_identity(declaration)
    assert name is not None
    found = [part for part in parts if _column_identity(part) == name]
    assert len(found) <= 1, f"already ambiguous column: {name}"
    if found:
        if if_not_exists:
            return list(parts)
        raise ValueError(f"duplicate column: {name}")
    return [*parts, declaration]


def _structure_key(sql: str) -> str:
    # Ignore code whitespace only. Never normalize comments/strings by regex.
    return "".join(
        re.sub(r"\s", "", text).lower() if kind == "code" else text
        for kind, text, _, _ in _sql_lexemes(sql) if kind != "comment"
    )


def _assert_distinct_table_parts(parts: list[str]) -> None:
    columns: set[str] = set()
    named_constraints: set[str] = set()
    anonymous_constraints: set[str] = set()
    for part in parts:
        name = _column_identity(part)
        if name is not None:
            assert name not in columns, f"duplicate column: {name}"
            columns.add(name)
            continue
        visible = _visible_sql(part)
        named = re.match(r"CONSTRAINT\s+(\w+)\b", visible, re.I)
        if named is not None:
            assert named[1] not in named_constraints, f"duplicate constraint name: {named[1]}"
            named_constraints.add(named[1])
        else:
            key = _structure_key(part)
            assert key not in anonymous_constraints, f"duplicate anonymous constraint: {visible}"
            anonymous_constraints.add(key)


def _sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    start = 0
    for kind, text, _, end in _sql_lexemes(sql):
        if kind == "code" and text == ";":
            statements.append(sql[start:end])
            start = end
    if sql[start:].strip():
        statements.append(sql[start:])
    return statements


def test_add_if_not_exists_reproduces_and_prevents_original_duplicate_column() -> None:
    original = "request_json jsonb NOT NULL CHECK(jsonb_typeof(request_json)='object')"
    repeated_add = "request_json jsonb NOT NULL"
    parts = ["id uuid PRIMARY KEY", original]
    # The old author-time append reproduces the actual C0-2 failure, without PG.
    with pytest.raises(AssertionError, match="duplicate column: request_json"):
        _assert_distinct_table_parts([*parts, repeated_add])
    assert _add_column(parts, repeated_add, if_not_exists=True) == parts
    # IF NOT EXISTS is not TYPE/CHECK reconciliation: even a different declaration
    # is skipped, retaining the existing stronger definition. Explicit later
    # TYPE/constraint edits remain separate operations, not this skip decision.
    assert _add_column(parts, "request_json text", if_not_exists=True) == parts
    with pytest.raises(ValueError, match="duplicate column: request_json"):
        _add_column(parts, repeated_add, if_not_exists=False)
    assert _add_column(parts, "new_column bigint CHECK(new_column>=0)", if_not_exists=True)[-1].startswith("new_column bigint")
    with pytest.raises(AssertionError, match="duplicate anonymous constraint"):
        _assert_distinct_table_parts(["id uuid", "UNIQUE (id)", "UNIQUE(id)"])
    _assert_distinct_table_parts(["id uuid", "user_id uuid", "UNIQUE(id)", "UNIQUE(id,user_id)"])


def test_all_82_declarations_have_distinct_columns_and_constraint_identities() -> None:
    count = 0
    for table, ddl in contract.AUTHORED_RELATION_DEFINITIONS:
        if not ddl.startswith("-- Structural identity source "):
            continue
        count += 1
        try:
            _assert_distinct_table_parts(_sql_comma_parts(_table_body(ddl)))
        except AssertionError as exc:
            raise AssertionError(f"{table}: {exc}") from exc
    assert count == 82
    indexes: set[str] = set()
    for statement in _sql_statements(BASELINE):
        match = re.match(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?([\w.]+)",
            _visible_sql(statement), re.I,
        )
        if match:
            assert match[1] not in indexes, match[1]
            indexes.add(match[1])


def test_all_selected_idempotent_column_actions_have_exactly_one_result() -> None:
    authored = {table.removeprefix("public."): ddl for table, ddl in contract.AUTHORED_RELATION_DEFINITIONS}
    count = 0
    for filename in (
        "460_learning_item_supply_pipeline.sql", "491_learning_item_shared_continuation.sql",
        "503_rag_actual_d_private_lifecycle.sql",
    ):
        original = (SCHEMA / filename).read_text(encoding="utf-8")
        for statement in _sql_statements(original):
            action = re.match(
                r"ALTER TABLE\s+(?:public\.)?(\w+)\s+ADD\s+(?:COLUMN\s+)?IF NOT EXISTS\s+([\s\S]+?);$",
                _visible_sql(statement), re.I,
            )
            if action is None or action[1] not in authored:
                continue
            count += 1
            table, declaration = action[1], action[2]
            name = _column_identity(declaration)
            current_parts = _sql_comma_parts(_table_body(authored[table]))
            assert sum(_column_identity(part) == name for part in current_parts) == 1, (table, name)
            source_create = re.search(
                r"CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?" + re.escape(table) + r"\s*\(",
                original, re.I,
            )
            if source_create is not None:
                source_parts = _sql_comma_parts(_table_body(original[source_create.start():]))
                source_column = next((part for part in source_parts if _column_identity(part) == name), None)
                if source_column is not None:
                    retained = next(part for part in current_parts if _column_identity(part) == name)
                    assert _structure_key(source_column) == _structure_key(retained), (table, name)
    assert count == 5
    generation = authored["tutor_item_supply_private_generation_artifacts"]
    assert "item_generation_request_v2" in generation
    assert "octet_length(request_json::text)<=1048576" in generation


def _canonical_rows(prefix: str, category: str) -> tuple[tuple[object, ...], ...]:
    name = prefix + category
    if category == "FUNCTION_METADATA" and prefix.endswith("EXPECTED_"):
        name = prefix.removesuffix("EXPECTED_") + "FUNCTION_METADATA"
    rows = getattr(contract, name)
    assert isinstance(rows, tuple) and all(isinstance(row, tuple) for row in rows), name
    return rows


def test_final_canonical_catalogs_are_complete_and_purpose_partitioned() -> None:
    assert contract.CATALOG_CANONICALIZED is True
    # C0-6 supplies the original scopes. C1 post-2 changes only three ACL entries;
    # C2 added-base-2 adds existing planning catalogs and two guards to each scope
    # (set_updated_at is already included). 601/602 do not create these objects.
    # The test does not require ignored .runtime artifacts at execution time:
    # exact rows are checked against authored scopes/ACLs and finite phase deltas.
    categories = (
        ("RELATION_METADATA", 5), ("COLUMNS", 6), ("CONSTRAINTS", 7), ("INDEXES", 5),
        ("TRIGGER_DEFINITIONS", 4), ("TABLE_ACLS", 2), ("COLUMN_ACLS", 3),
        ("FUNCTION_METADATA", 11), ("SCHEMA_METADATA", 3), ("SEQUENCE_METADATA", 14),
    )
    c0_counts = {
        "BASE_": (183, 2794, 2521, 713, 208, 183, 0, 84, 1, 0),
        "EXPECTED_": (268, 3825, 3506, 1001, 454, 268, 1, 268, 3, 2),
        "VALIDATION_BASE_": (184, 2798, 2526, 716, 209, 184, 0, 86, 1, 0),
        "VALIDATION_EXPECTED_": (270, 3839, 3522, 1006, 457, 270, 8, 278, 3, 2),
    }
    c2_added_scope = (3, 24, 18, 7, 6, 3, 0, 2, 0, 0)
    counts = {
        prefix: tuple(before + added for before, added in zip(values, c2_added_scope, strict=True))
        for prefix, values in c0_counts.items()
    }
    two_part_keys = {"COLUMNS", "CONSTRAINTS", "INDEXES", "TRIGGER_DEFINITIONS", "COLUMN_ACLS"}
    for prefix, expected_counts in counts.items():
        tables = set(getattr(contract, prefix + "TABLES"))
        functions = set(getattr(contract, prefix + "FUNCTIONS"))
        for (category, width), count in zip(categories, expected_counts, strict=True):
            rows = _canonical_rows(prefix, category)
            assert len(rows) == count, (prefix, category)
            assert all(len(row) == width for row in rows), (prefix, category)
            key_width = 2 if category in two_part_keys else 1
            assert len({row[:key_width] for row in rows}) == len(rows), (prefix, category)
            if category not in {"FUNCTION_METADATA", "SCHEMA_METADATA", "SEQUENCE_METADATA"}:
                assert {row[0] for row in rows} <= tables, (prefix, category)
            if category in {"RELATION_METADATA", "COLUMNS", "TABLE_ACLS"}:
                assert {row[0] for row in rows} == tables, (prefix, category)
        assert {row[0] for row in _canonical_rows(prefix, "FUNCTION_METADATA")} == functions
        assert {row[0] for row in _canonical_rows(prefix, "SEQUENCE_METADATA")} == set(
            getattr(contract, prefix + "SEQUENCES")
        )
        assert _canonical_rows(prefix, "EXTENSIONS") == (("pgcrypto", "1.3", "public", "postgres"),)
        assert _canonical_rows(prefix, "POLICIES") == ()
        schemas = {"public"}
        if prefix.endswith("EXPECTED_"):
            purpose = prefix.removesuffix("EXPECTED_")
            schemas.update(getattr(contract, purpose + "NEW_SCHEMAS"))
            assert len(_canonical_rows(prefix, "ROLE_METADATA")) == 3
            assert _canonical_rows(prefix, "ROLE_MEMBERSHIPS") == ()
            assert _canonical_rows(prefix, "DEFAULT_ACLS") == ()
        assert {row[0] for row in _canonical_rows(prefix, "SCHEMA_METADATA")} == schemas
        for row in _canonical_rows(prefix, "CONSTRAINTS"):
            assert isinstance(row[3], str) and row[3], (prefix, row[:2])
            assert all(type(flag) is bool for flag in row[4:]), (prefix, row[:2])
        for row in _canonical_rows(prefix, "TRIGGER_DEFINITIONS"):
            assert isinstance(row[2], str) and row[2].startswith("CREATE ") and row[3] == "O"
        for row in _canonical_rows(prefix, "FUNCTION_METADATA"):
            assert isinstance(row[-1], str) and row[-1], (prefix, row[0])

    # Compare whole canonical rows, including definitions/flags, not just counts.
    for category in ("RELATION_METADATA", "CONSTRAINTS", "INDEXES", "TRIGGER_DEFINITIONS"):
        assert set(_canonical_rows("BASE_", category)) <= set(_canonical_rows("EXPECTED_", category)), category
    for category, _ in categories:
        assert set(_canonical_rows("BASE_", category)) <= set(_canonical_rows("VALIDATION_BASE_", category)), category
    for category in ("RELATION_METADATA", "COLUMNS", "INDEXES", "TRIGGER_DEFINITIONS", "SEQUENCE_METADATA", "SCHEMA_METADATA"):
        assert set(_canonical_rows("EXPECTED_", category)) <= set(_canonical_rows("VALIDATION_EXPECTED_", category)), category

    runtime_constraints = {row[:2]: row for row in contract.EXPECTED_CONSTRAINTS}
    validation_constraints = {row[:2]: row for row in contract.VALIDATION_EXPECTED_CONSTRAINTS}
    assert runtime_constraints.keys() <= validation_constraints.keys()
    patched: set[tuple[object, ...]] = set()
    for relation, predecessor, _synthetic_branch in contract.VALIDATION_AUTHORED_CONSTRAINT_PATCHES:
        matches = [key for key, row in runtime_constraints.items() if row[0] == relation and row[3] == predecessor]
        assert len(matches) == 1, (relation, predecessor)
        patched.add(matches[0])
    assert len(patched) == 7
    assert {key for key, row in runtime_constraints.items() if validation_constraints[key] != row} == patched
    for key in patched:
        before, after = runtime_constraints[key], validation_constraints[key]
        assert before[:3] + before[4:] == after[:3] + after[4:], key
        assert "IS TRUE" in after[3], key

    for prefix in ("", "VALIDATION_"):
        base_functions = {row[0]: row for row in getattr(contract, prefix + "BASE_FUNCTION_METADATA")}
        post_functions = {row[0]: row for row in getattr(contract, prefix + "FUNCTION_METADATA")}
        replaced = set(getattr(contract, prefix + "REPLACED_BASE_FUNCTIONS"))
        assert {key for key, row in base_functions.items() if post_functions[key] != row} == replaced
        assert set(getattr(contract, prefix + "EXPECTED_TABLE_ACLS")) == _table_acls_with_forward_read_deltas(
            getattr(contract, prefix + "AUTHORED_EXPECTED_TABLE_ACLS")
        )
        new_tables = set(getattr(contract, prefix + "NEW_TABLES"))
        base_relations = {row[0]: row for row in getattr(contract, prefix + "BASE_RELATION_METADATA")}
        for row in getattr(contract, prefix + "EXPECTED_RELATION_METADATA"):
            if row[0] in new_tables:
                assert row[1:] == (contract.SCHEMA_ROLE, "r", False, False), row[0]
            else:
                assert row == base_relations[row[0]], row[0]
    assert contract.VALIDATION_EXPECTED_ROLE_METADATA == contract.EXPECTED_ROLE_METADATA
    assert contract.VALIDATION_EXPECTED_SEQUENCE_METADATA == contract.EXPECTED_SEQUENCE_METADATA


def test_development_constraint_overlay_is_exactly_thirteen_full_check_pairs() -> None:
    # The loader owns the fixed target routing and False -> fail-closed tests.
    # Read its literal allowlist without importing connection/config modules.
    tree = ast.parse((ROOT / "app/db/completion_baseline.py").read_text(encoding="utf-8"))
    keys = next(
        ast.literal_eval(node.value)
        for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_DEVELOPMENT_CONSTRAINT_KEYS" for target in node.targets)
    )
    pairs = contract.DEVELOPMENT_CONSTRAINT_OVERRIDES
    assert isinstance(pairs, tuple) and len(pairs) == len(keys) == 13
    assert {clone[:2] for clone, _development in pairs} == set(keys)
    runtime_base = {row[:2]: row for row in contract.BASE_CONSTRAINTS}
    runtime_post = {row[:2]: row for row in contract.EXPECTED_CONSTRAINTS}
    validation_base = {row[:2]: row for row in contract.VALIDATION_BASE_CONSTRAINTS}
    for clone, development in pairs:
        assert len(clone) == len(development) == 7
        assert clone[:3] + clone[4:] == development[:3] + development[4:]
        assert clone[2] == "c" and clone[4:] == (True, False, False)
        assert isinstance(clone[3], str) and isinstance(development[3], str)
        assert clone[3] and development[3] and clone[3] != development[3]
        key = clone[:2]
        assert runtime_base[key] == runtime_post[key] == validation_base[key] == clone


def _created_functions(sql: str) -> dict[str, tuple[int, str, str, str]]:
    """Top-level CREATE statements only; dollar-quoted DO/expected text is data."""
    result: dict[str, tuple[int, str, str, str]] = {}
    cursor = 0
    for statement in _sql_statements(sql):
        offset = sql.index(statement, cursor)
        cursor = offset + len(statement)
        visible = _visible_sql(statement)
        create = re.match(r"CREATE(?: OR REPLACE)? FUNCTION\s+([\w.]+)\s*\(", visible, re.I)
        if create is None:
            continue
        name = create[1] if "." in create[1] else "public." + create[1]
        name = name.lower()
        assert name not in result, f"unexpected overload/redefinition in selected scope: {name}"
        body_token = next(
            text for kind, text, _, _ in _sql_lexemes(statement)
            if kind == "literal" and text.startswith("$")
        )
        marker = re.match(r"\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$", body_token)
        assert marker is not None
        body = body_token[len(marker[0]):-len(marker[0])]
        header = statement[:statement.index(body_token)]
        language = re.search(r"\bLANGUAGE\s+(\w+)", header, re.I)
        assert language is not None, name
        result[name] = (offset, language[1].lower(), body, statement)
    return result


def _assert_sql_creation_order(sql: str) -> set[str]:
    definitions = _created_functions(sql)
    base_functions = {signature.split("(", 1)[0] for signature in contract.BASE_FUNCTIONS}
    relations = {table: -1 for table in contract.BASE_TABLES}
    cursor = 0
    for statement in _sql_statements(sql):
        offset = sql.index(statement, cursor)
        cursor = offset + len(statement)
        create = re.match(r"CREATE TABLE\s+([\w.]+)\s*\(", _visible_sql(statement), re.I)
        if create:
            name = create[1] if "." in create[1] else "public." + create[1]
            relations[name] = offset
    # Finite pg_catalog calls and the declared pgcrypto dependency; no fallback
    # that silently accepts arbitrary unresolved or future user-defined callees.
    builtins = {
        "encode", "convert_to", "jsonb_typeof", "jsonb_object_keys", "jsonb_each",
        "jsonb_array_elements", "jsonb_build_object", "txid_current", "count", "current_setting",
    }
    syntax = {"and", "or", "not", "in", "any", "all", "exists", "array", "row"}
    assert ("pgcrypto", "1.3", "public", "postgres") in contract.BASE_EXTENSIONS

    def function_available(name: str, offset: int, caller: str) -> None:
        qualified = name if "." in name else "public." + name
        assert qualified in definitions or qualified in base_functions, (caller, "unknown callee", qualified)
        assert qualified in base_functions or definitions[qualified][0] < offset, (
            caller, "callee must exist at CREATE", qualified,
        )

    def relation_available(name: str, offset: int, caller: str) -> None:
        qualified = name if "." in name else "public." + name
        assert qualified in relations and relations[qualified] < offset, (
            caller, "relation must exist at CREATE", qualified,
        )

    checked: set[str] = set()
    for caller, (offset, language, body, _) in definitions.items():
        if language != "sql":
            continue
        checked.add(caller)
        lexemes = _sql_lexemes(body)
        code = "".join(
            text if kind in {"code", "identifier"} else " " * len(text)
            for kind, text, _, _ in lexemes
        )
        for call in re.finditer(r"\b([a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*)?)\s*\(", code, re.I):
            name = call[1].lower()
            if name in syntax or name.removeprefix("pg_catalog.") in builtins:
                continue
            if name in {"digest", "public.digest"}:
                continue  # pgcrypto is an explicit, already-installed BASE extension.
            function_available(name, offset, caller)
        for relation in re.finditer(r"\b(?:FROM|JOIN)\s+([\w.]+)", code, re.I):
            if code[relation.end():].lstrip().startswith("("):
                continue  # Set-returning function, checked in the call loop above.
            if relation[1] in {"pg_trigger", "pg_catalog.pg_trigger"}:
                continue
            relation_available(relation[1], offset, caller)
        for kind, text, _, end in lexemes:
            if kind != "literal" or not text.startswith("'"):
                continue
            cast = re.match(r"\s*::\s*(?:pg_catalog\.)?(regprocedure|regclass)\b", body[end:], re.I)
            if cast is None:
                continue
            constant = text[1:-1].replace("''", "'")
            if cast[1].lower() == "regprocedure":
                signature = constant if "." in constant else "public." + constant
                assert signature in contract.EXPECTED_FUNCTIONS, (caller, "unknown signature", signature)
                function_available(signature.split("(", 1)[0], offset, caller)
            else:
                relation_available(constant, offset, caller)
    return checked


def test_all_selected_sql_functions_resolve_creation_time_dependencies() -> None:
    assert _assert_sql_creation_order(BASELINE) == {
        "item_supply_internal.snapshot_hash", "item_supply_internal.snapshot_keys",
        "item_supply_internal.snapshot_scalars", "item_supply_internal.snapshot_strings",
        "item_supply_internal.pipeline_generation_hash", "item_supply_internal.shared_generation_hash",
        "public.rag_actual_d_finite_storage_profile", "item_supply_internal.permitted",
        "item_supply_internal.native_exposure_hooks_current", "public.rag_actual_d_private_delete_allowed",
        "completion_baseline_internal.validation_allowed",
    }
    definitions = _created_functions(BASELINE)
    assert len(definitions) == 187
    hooks = definitions["item_supply_internal.native_exposure_hooks_current"][2]
    assert "'capture_native_exposure_origin()'::regprocedure" in hooks
    assert "'capture_native_exposure_birth()'::regprocedure" in hooks
    assert "to_regprocedure" not in hooks
    assert "check_function_bodies" not in BASELINE.lower()
    expected_bodies = {row[0].split("(", 1)[0]: row[-1] for row in contract.FUNCTION_METADATA}
    for name, (_, _, body, _) in definitions.items():
        assert body == expected_bodies[name], name


def test_creation_time_order_rejects_forward_regprocedure_and_sql_callee() -> None:
    definitions = _created_functions(BASELINE)
    for name in ("public.capture_native_exposure_origin", "item_supply_internal.canonical_snapshot"):
        statement = definitions[name][3]
        assert BASELINE.count(statement) == 1
        # Only move an intact definition: final callee set, body and attributes
        # still match, but SQL validation must reject the CREATE-time order.
        broken = BASELINE.replace(statement, "", 1) + statement
        assert set(_created_functions(broken)) == set(definitions)
        with pytest.raises(AssertionError, match="callee must exist at CREATE"):
            _assert_sql_creation_order(broken)


def _relation_grants(sql: str) -> tuple[dict[tuple[str, str], set[str]], dict[tuple[str, str, str], set[str]]]:
    tables: dict[tuple[str, str], set[str]] = {}
    columns: dict[tuple[str, str, str], set[str]] = {}
    for statement in _sql_statements(sql):
        visible = _visible_sql(statement)
        if not re.match(r"GRANT\s+(?:SELECT|INSERT|UPDATE|DELETE)\b", visible, re.I):
            continue
        grant = re.match(r"GRANT\s+([\s\S]+?)\s+ON\s+(?:TABLE\s+)?([\s\S]+?)\s+TO\s+(\w+);$", visible, re.I)
        assert grant is not None, visible
        for privilege in _sql_comma_parts(grant[1]):
            item = re.fullmatch(r"(SELECT|INSERT|UPDATE|DELETE)(?:\(([^)]+)\))?", privilege, re.I)
            assert item is not None, privilege
            for table in _sql_comma_parts(grant[2]):
                if item[2] is None:
                    tables.setdefault((table, grant[3]), set()).add(item[1])
                else:
                    for column in _sql_comma_parts(item[2]):
                        columns.setdefault((table, column, grant[3]), set()).add(item[1])
    return tables, columns


def test_formal_native_purge_deletes_fk_children_before_every_receipt_mode() -> None:
    rows = {row[0]: row for row in contract.FUNCTION_METADATA}
    body = rows["item_supply_internal.purge_native_consumer_private(uuid)"][-1]
    binding = "DELETE FROM tutor_item_supply_native_artifact_bindings WHERE user_id=target_user;"
    receipt = "DELETE FROM tutor_item_supply_native_consumer_receipts WHERE user_id=target_user;"
    assert body.index("item_supply_internal.permitted(target_user)") < body.index(binding) < body.index(receipt)
    assert body.count("DELETE FROM tutor_item_supply_native_consumer_receipts") == 1
    assert "mode<>" not in body
    ddl = dict(contract.AUTHORED_RELATION_DEFINITIONS)["public.tutor_item_supply_native_artifact_bindings"]
    assert "FOREIGN KEY(creation_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_native_consumer_receipts(id,user_id,epoch) ON DELETE RESTRICT" in ddl
    assert "completion_storage_validation" in VALIDATION
    assert "CREATE FUNCTION item_supply_internal.purge_native_consumer_private" not in VALIDATION


def test_every_authored_function_has_explicit_protected_owner_and_acl() -> None:
    rows = {row[0]: row for row in contract.FUNCTION_METADATA}
    assert len(contract.AUTHORED_FUNCTION_SIGNATURES) == 187
    for signature in contract.AUTHORED_FUNCTION_SIGNATURES:
        assert rows[signature][1] == contract.SCHEMA_ROLE, signature
        assert f"ALTER FUNCTION {signature} OWNER TO {contract.SCHEMA_ROLE};" in BASELINE, signature
        assert f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,{contract.RUNTIME_ROLE},{contract.VERIFIER_ROLE};" in BASELINE, signature
    signature = "item_supply_internal.check_execution_intent(uuid)"
    assert (contract.RUNTIME_ROLE, False) in rows[signature][5]
    assert "USING ERRCODE='42501'" in rows[signature][-1]


def test_ordinary_terminal_material_planning_and_thread_acl_is_exact() -> None:
    runtime = dict(contract.RUNTIME_BASE_TABLE_PRIVILEGES)
    for table in ("tutor_run_checkpoints", "tutor_memory_curation_outbox", "tutor_learning_plan_drafts",
                  "tutor_learning_plan_sessions", "tutor_planning_intake_facts", "tutor_planning_question_events"):
        assert "INSERT" in runtime["public." + table], table
    assert {"SELECT", "INSERT", "UPDATE"} <= set(runtime["public.rag_material_semantic_reviews"])
    assert runtime["public.tutor_thread_turn_cutovers"] == ("SELECT",)
    assert contract.RUNTIME_COLUMN_PRIVILEGES == (("public.tutor_thread_turn_cutovers", "cutover_version", ("INSERT",)),)
    assert len(contract.RUNTIME_BASE_TABLE_PRIVILEGES) == 155
    assert len(contract.SCHEMA_DEFINER_BASE_TABLE_PRIVILEGES) == 25
    assert set(contract.BASE_TABLES) == {row[0] for row in contract.AUTHORED_BASE_RELATION_METADATA}
    assert len(contract.BASE_TABLES) == 183 + 3  # C0-6 scope + C2 added-base-2.
    scoped = dict(contract.BASE_PERMISSION_SCOPED_HELPERS)
    assert scoped["app/services/tutor/persistence/curation.py"] == (
        "_persist_checkpoint_and_outbox_locked", "_upsert_outbox_locked",
    )
    assert scoped["app/services/tutor/thread_turn_cutover.py"] == ("_ensure_record",)


def test_sparse_column_acl_contract_matches_every_literal_grant() -> None:
    runtime_tables, runtime_columns = _relation_grants(BASELINE)
    validation_tables, validation_columns = _relation_grants(VALIDATION)
    assert contract.BASE_COLUMN_ACLS == contract.VALIDATION_BASE_COLUMN_ACLS == ()
    for actual, expected in (
        (runtime_columns, contract.EXPECTED_COLUMN_ACLS),
        ({**runtime_columns, **validation_columns}, contract.VALIDATION_EXPECTED_COLUMN_ACLS),
    ):
        flattened = {(table, column, grantee): {privilege for g, privilege, grantable in acl if g == grantee and not grantable}
                     for table, column, acl in expected for grantee, _, _ in acl}
        assert actual == flattened
        assert len({(table, column) for table, column, _ in expected}) == len(expected)
    assert len(contract.EXPECTED_COLUMN_ACLS) == 1
    assert len(contract.VALIDATION_EXPECTED_COLUMN_ACLS) == 8
    for rows in (contract.AUTHORED_EXPECTED_TABLE_ACLS, contract.VALIDATION_AUTHORED_EXPECTED_TABLE_ACLS):
        assert len({row[0] for row in rows}) == len(rows)
        assert all(grantee != contract.VERIFIER_ROLE for _, acl in rows for grantee, _, _ in acl)
    assert set(runtime_tables).isdisjoint({("public.tutor_thread_turn_cutovers", contract.SCHEMA_ROLE)})
    assert ("public.tutor_item_supply_shared_usage_events", contract.RUNTIME_ROLE) in validation_tables


def test_purpose_inventories_distinguish_new_objects_from_replaced_base_guards() -> None:
    assert set(contract.NEW_FUNCTIONS).isdisjoint(contract.BASE_FUNCTIONS)
    assert set(contract.VALIDATION_NEW_FUNCTIONS).isdisjoint(contract.VALIDATION_BASE_FUNCTIONS)
    assert len(contract.NEW_FUNCTIONS) == 184 and len(contract.REPLACED_BASE_FUNCTIONS) == 3
    assert len(contract.VALIDATION_NEW_FUNCTIONS) == 192 and len(contract.VALIDATION_REPLACED_BASE_FUNCTIONS) == 4
    assert set(contract.EXPECTED_FUNCTIONS) == set(contract.BASE_FUNCTIONS) | set(contract.AUTHORED_FUNCTION_SIGNATURES)
    assert set(contract.VALIDATION_EXPECTED_FUNCTIONS) == set(contract.VALIDATION_BASE_FUNCTIONS) | set(contract.VALIDATION_AUTHORED_FUNCTION_SIGNATURES)
    assert set(contract.EXPECTED_TABLES) == set(contract.BASE_TABLES) | set(contract.NEW_TABLES)
    assert set(contract.VALIDATION_EXPECTED_TABLES) == set(contract.VALIDATION_BASE_TABLES) | set(contract.VALIDATION_NEW_TABLES)
    assert len(contract.VALIDATION_BASE_TABLES) == 184 + 3
    assert len(contract.VALIDATION_BASE_FUNCTION_METADATA) == 86 + 2
    assert len(contract.VALIDATION_FUNCTION_METADATA) == 278 + 2
    assert len(contract.EXPECTED_TRIGGERS) == 454 + 6 and len(contract.VALIDATION_EXPECTED_TRIGGERS) == 457 + 6
    for suffix in (
        "TABLES", "FUNCTIONS", "FUNCTION_METADATA", "LOCK_RELATIONS", "EXTENSIONS", "RELATION_METADATA",
        "COLUMNS", "CONSTRAINTS", "INDEXES", "TRIGGER_DEFINITIONS", "POLICIES", "SCHEMA_METADATA",
        "TABLE_ACLS", "COLUMN_ACLS", "SEQUENCES", "SEQUENCE_METADATA",
    ):
        assert isinstance(getattr(contract, "VALIDATION_BASE_" + suffix), tuple), suffix
    assert contract.CATALOG_CANONICALIZED is True


def test_validation_final_function_bodies_predecessors_and_finite_objects_are_complete() -> None:
    definitions = _created_functions(VALIDATION)
    assert len(definitions) == 15
    rows = {row[0].split("(", 1)[0]: row for row in contract.VALIDATION_FUNCTION_METADATA}
    for name, (_, _, body, _) in definitions.items():
        row = rows[name]
        assert row[-1] == body, name
        assert row[1] == contract.SCHEMA_ROLE
        expected_acl = {(contract.SCHEMA_ROLE, False)}
        if name.startswith("completion_baseline_internal.issue_"):
            expected_acl.add((contract.VERIFIER_ROLE, False))
        assert set(row[5]) == expected_acl, name
        assert row[4] is not None and row[4][0].startswith("search_path=pg_catalog, public,")
    previous = {row[0]: row[-1] for row in contract.VALIDATION_BASE_FUNCTION_METADATA + contract.FUNCTION_METADATA}
    predecessors = re.findall(r"oid='([^']+)'::regprocedure\) IS DISTINCT FROM \$prior\$(.*?)\$prior\$", VALIDATION, re.S)
    assert len(predecessors) == 7
    for signature, body in predecessors:
        assert previous[signature] == body, signature
    scope = rows["completion_baseline_internal.validation_scope"][-1]
    assert "FROM tutor_track_active_plans" in scope and "revision_id=s.revision_id FOR SHARE" in scope
    capture = rows["public.rag_registered_capture_guard"][-1]
    assert "provider_attempt_id" not in capture and "provider_row" not in capture
    assert len(contract.VALIDATION_AUTHORED_CONSTRAINT_PATCHES) == 7
    assert len(contract.VALIDATION_AUTHORED_RELATION_DEFINITIONS) == 83
    new_shared = dict(contract.VALIDATION_AUTHORED_RELATION_DEFINITIONS)["public.tutor_item_supply_shared_usage_events"]
    assert "CHECK(cost_amount IS NULL)" in new_shared
    assert "FOREIGN KEY(reservation_id,job_id)" in new_shared


def _table_acls_with_forward_read_deltas(
    frozen_rows: tuple[tuple[str, tuple[tuple[str, str, bool], ...]], ...],
) -> set[tuple[str, tuple[tuple[str, str, bool], ...]]]:
    """Compose C1 and C2 SELECT deltas without backfilling frozen 599 grants."""
    inventory_reads = set(contract.INVENTORY_READ_TABLES)
    assert inventory_reads == {
        "public.rag_source_reviews", "public.rag_source_admissions", "public.rag_source_claim_receipts",
    }
    planning_reads = set(contract.PLANNING_CATALOG_READ_TABLES)
    assert planning_reads == {
        "public.language_courses", "public.language_course_intent_tags", "public.tutor_learning_intents",
    }
    assert inventory_reads.isdisjoint(planning_reads)
    rows = dict(frozen_rows)
    for reads in (inventory_reads, planning_reads):
        assert reads <= rows.keys()
        before = dict(rows)
        for table in reads:
            acl = rows[table]
            assert all(grantee != contract.RUNTIME_ROLE for grantee, _privilege, _grantable in acl), table
            rows[table] = tuple(sorted((*acl, (contract.RUNTIME_ROLE, "SELECT", False))))
        assert {table for table in rows if rows[table] != before[table]} == reads
    return set(rows.items())


def test_601_covers_the_actual_fixed_fstring_inventory_joins_with_select_only() -> None:
    path = ROOT / "app/services/grounding/autonomous/actual_d_lifecycle.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "actual_d_private_counts")
    assignments = {target.id: node.value for node in function.body if isinstance(node, ast.Assign)
                   for target in node.targets if isinstance(target, ast.Name)}
    joins = ast.literal_eval(assignments["joins"])
    owner = ast.literal_eval(assignments["owner"])
    assert set(joins) == {
        "rag_assessment_source_evidence", "rag_source_reviews", "rag_source_admissions", "rag_source_claim_receipts",
    }
    assert owner == (
        "e.signed_proof->'payload'->>'format'=%s AND "
        "e.signed_proof->'payload'->'prepared'->'actual_d'->'draft'->>'user_id'=%s"
    )
    executions = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"
                  and node.args and isinstance(node.args[0], ast.JoinedStr)]
    assert len(executions) == 1
    query = executions[0].args[0]
    assert isinstance(query, ast.JoinedStr)
    assert [value.value for value in query.values if isinstance(value, ast.Constant)] == [
        "SELECT count(*) AS count FROM ", " WHERE ",
    ]
    assert [ast.unparse(value.value) for value in query.values if isinstance(value, ast.FormattedValue)] == ["source", "owner"]
    assert ast.unparse(executions[0].args[1]) == "(ACTUAL_D_FORMAT, str(user_id))"
    loop = next(node for node in function.body if isinstance(node, ast.For) and ast.unparse(node.iter) == "joins.items()")
    assert ast.unparse(loop.target) == "(name, source)"
    assert any(isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "row" for t in node.targets)
               and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
               and node.value.func.attr == "fetchone" and node.value.func.value is executions[0]
               for node in loop.body)
    assert any(isinstance(node, ast.Assign) and any(ast.unparse(t) == "result[name]" for t in node.targets)
               and ast.dump(node.value) == ast.dump(ast.parse('int(row["count"])', mode="eval").body)
               for node in loop.body)
    # Read the real production caller, without importing services/config or
    # replacing actual_d_private_counts with a mock/verified outcome.
    cutover = ast.parse((ROOT / "app/services/tutor/cutover.py").read_text(encoding="utf-8"))
    inventory = next(node for node in ast.walk(cutover) if isinstance(node, ast.FunctionDef) and node.name == "_inventory")
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "actual_d_private_counts" for node in ast.walk(inventory))

    required: set[str] = set()
    for source in joins.values():
        assert isinstance(source, str)
        sql = f"SELECT count(*) AS count FROM {source} WHERE {owner}"
        required.update("public." + name for name in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql))
    frozen_grants, _ = _relation_grants(BASELINE)
    missing = {table for table in required if "SELECT" not in frozen_grants.get((table, contract.RUNTIME_ROLE), set())}
    assert missing == set(contract.INVENTORY_READ_TABLES)
    delta_grants, delta_columns = _relation_grants(INVENTORY_READS)
    assert delta_grants == {(table, contract.RUNTIME_ROLE): {"SELECT"} for table in missing}
    assert delta_columns == {}
    assert {(table, privilege) for table, privilege, _source in contract.INVENTORY_READ_PERMISSION_SOURCES} == {
        (table, "SELECT") for table in missing
    }
    assert len(contract.INVENTORY_READ_PERMISSION_SOURCES) == 3
    assert all(source.startswith("app/services/grounding/autonomous/actual_d_lifecycle.py:")
               and "actual_d_private_counts" in source
               for _table, _privilege, source in contract.INVENTORY_READ_PERMISSION_SOURCES)
    # These remain the frozen single-fragment 599 declarations, not a merged
    # grant history pretending that the three SELECTs were installed by 599.
    assert all(table not in dict(contract.RUNTIME_BASE_TABLE_PRIVILEGES) for table in missing)
    assert _base_table_grants(contract.RUNTIME_ROLE) == dict(contract.RUNTIME_BASE_TABLE_PRIVILEGES)
    statements = [_visible_sql(statement) for statement in _sql_statements(INVENTORY_READS)]
    assert len(statements) == 5
    assert statements[0].startswith("SET LOCAL search_path=")
    assert statements[1].startswith("DO $inventory_scope$")
    assert all(statement.startswith("GRANT SELECT ON TABLE ") for statement in statements[2:])
    assert "completion_baseline_internal.contract_identity()" in statements[1]
    assert "identity_row.database_oid" in statements[1] and "identity_row.purpose" in statements[1]
    assert "predecessor runtime ACL changed" in statements[1]


def test_602_covers_only_the_current_planning_resolver_catalog_selects() -> None:
    path = ROOT / "app/services/learning/planning_intent.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    resolver = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PlanningIntentResolver")
    tables = set(contract.PLANNING_CATALOG_READ_TABLES)
    assert tables == {"public.language_courses", "public.language_course_intent_tags", "public.tutor_learning_intents"}
    for name, required in (("_active_courses", {"public.language_courses"}), ("_intent_course_ids", tables)):
        method = next(node for node in resolver.body if isinstance(node, ast.FunctionDef) and node.name == name)
        executions = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"]
        assert len(executions) == 1
        query = ast.literal_eval(executions[0].args[0])
        assert isinstance(query, str) and query.strip().startswith("SELECT ")
        assert {"public." + table for table in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", query)} == required
        assert "archived_at IS NULL" in query
        if name == "_intent_course_ids":
            assert "intents.state = 'active'" in query and "tags.intent_key = ANY(%s)" in query
            assert ast.unparse(executions[0].args[1]) == "(list(intent_tags),)"

    prior_grants, _ = _relation_grants(BASELINE + "\n" + INVENTORY_READS)
    assert all((table, contract.RUNTIME_ROLE) not in prior_grants for table in tables)
    grants, columns = _relation_grants(PLANNING_CATALOG_READS)
    assert grants == {(table, contract.RUNTIME_ROLE): {"SELECT"} for table in tables}
    assert columns == {}
    sources = contract.PLANNING_CATALOG_READ_PERMISSION_SOURCES
    assert len(sources) == 3 and {(table, privilege) for table, privilege, _source in sources} == {
        (table, "SELECT") for table in tables
    }
    assert all(source.startswith("app/services/learning/planning_intent.py:")
               and "PlanningIntentResolver._intent_course_ids" in source for _table, _privilege, source in sources)
    assert "PlanningIntentResolver._active_courses" in next(source for table, _privilege, source in sources if table == "public.language_courses")
    assert tables.isdisjoint(dict(contract.RUNTIME_BASE_TABLE_PRIVILEGES))
    assert tables.isdisjoint(contract.INVENTORY_READ_TABLES)
    statements = [_visible_sql(statement) for statement in _sql_statements(PLANNING_CATALOG_READS)]
    assert len(statements) == 5 and statements[0].startswith("SET LOCAL search_path=")
    assert statements[1].startswith("DO $planning_catalog_scope$")
    assert all(statement.startswith("GRANT SELECT ON TABLE ") for statement in statements[2:])
    assert "completion_baseline_internal.contract_identity()" in statements[1]
    assert "identity_row.database_oid" in statements[1] and "identity_row.purpose" in statements[1]
    assert "rolname=session_user" in statements[1] and "predecessor runtime ACL changed" in statements[1]


def test_c2_planning_scope_is_existing_catalog_and_guard_closure_not_new_objects() -> None:
    tables = set(contract.PLANNING_CATALOG_READ_TABLES)
    functions = {"public.enforce_language_course_intent_coverage()", "public.assert_language_course_intent_coverage()", "public.set_updated_at()"}
    owner_acl = tuple(("postgres", privilege, False) for privilege in (
        "DELETE", "INSERT", "REFERENCES", "SELECT", "TRIGGER", "TRUNCATE", "UPDATE",
    ))
    # added-base-2, not the incomplete added-base-1: six triggers need all three
    # existing functions, of which set_updated_at must occur only once per scope.
    for category, count in (("RELATION_METADATA", 3), ("COLUMNS", 24), ("CONSTRAINTS", 18), ("INDEXES", 7), ("TRIGGER_DEFINITIONS", 6)):
        expected = {row for row in _canonical_rows("BASE_", category) if row[0] in tables}
        assert len(expected) == count, category
        for prefix in ("EXPECTED_", "VALIDATION_BASE_", "VALIDATION_EXPECTED_"):
            assert {row for row in _canonical_rows(prefix, category) if row[0] in tables} == expected, (prefix, category)
    assert {row for row in contract.BASE_RELATION_METADATA if row[0] in tables} == {
        (table, "postgres", "r", False, False) for table in tables
    }
    assert tables.isdisjoint(clone[0] for clone, _development in contract.DEVELOPMENT_CONSTRAINT_OVERRIDES)
    for purpose in ("", "VALIDATION_"):
        assert tables <= set(getattr(contract, purpose + "BASE_LOCK_RELATIONS"))
        assert tables.isdisjoint(getattr(contract, purpose + "NEW_TABLES"))
        assert functions <= set(getattr(contract, purpose + "BASE_FUNCTIONS"))
        assert functions.isdisjoint(getattr(contract, purpose + "NEW_FUNCTIONS"))
        assert functions.isdisjoint(getattr(contract, purpose + "AUTHORED_FUNCTION_SIGNATURES"))
        for name in ("BASE_TABLE_ACLS", "AUTHORED_EXPECTED_TABLE_ACLS"):
            assert {row for row in getattr(contract, purpose + name) if row[0] in tables} == {
                (table, owner_acl) for table in tables
            }
        assert not any(row[0] in tables for row in getattr(contract, purpose + "EXPECTED_COLUMN_ACLS"))
    base_functions = {row[0]: row for row in contract.BASE_FUNCTION_METADATA if row[0] in functions}
    for prefix in ("BASE_", "EXPECTED_", "VALIDATION_BASE_", "VALIDATION_EXPECTED_"):
        rows = [row for row in _canonical_rows(prefix, "FUNCTION_METADATA") if row[0] in functions]
        assert len(rows) == 3 and {row[0]: row for row in rows} == base_functions
    for signature, row in base_functions.items():
        result = "void" if signature == "public.assert_language_course_intent_coverage()" else "trigger"
        assert row[1:10] == ("postgres", False, "v", None, (("PUBLIC", False), ("postgres", False)), "plpgsql", result, False, "u")
    assert " ".join(base_functions["public.enforce_language_course_intent_coverage()"][-1].split()) == (
        "BEGIN PERFORM assert_language_course_intent_coverage(); RETURN NULL; END;"
    )
    assertion = base_functions["public.assert_language_course_intent_coverage()"][-1]
    assert {"public." + table for table in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", assertion)} == tables
    assert assertion.count("RAISE EXCEPTION 'language_course_intent_coverage_missing:") == 2
    assert not re.search(r"\b(?:PERFORM|INSERT|UPDATE|DELETE)\b", assertion)
