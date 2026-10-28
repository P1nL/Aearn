"""Fixed non-B1d baseline selection and read-only catalog readiness.

Importing this module never opens a connection or reads settings. Installation is
owned exclusively by app.db.bootstrap, not by this module or process startup.
"""

import importlib
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
from types import ModuleType

from psycopg import Connection
from psycopg.pq import TransactionStatus

CONTRACT_ID = "completion_non_b1d_v1"
RUNTIME_DATABASE_NAMES = ("postgres", "aearn_completion_b_test_20261026")
VALIDATION_DATABASE_NAME = "aearn_completion_b_validation_20261027"
ROLE_NAMES = (
    "aearn_cb_schema_20261027",
    "aearn_cb_runtime_20261027",
    "aearn_cb_verifier_20261027",
)
CATALOG_SEARCH_PATH_SQL = "SET LOCAL search_path = pg_catalog, pg_temp"
Row = tuple[object, ...]
Rows = tuple[Row, ...]

# The only approved development/pg_dump-restore rendering differences. The
# actual two raw rows per identity belong to Main's sampled metadata, not here.
_DEVELOPMENT_CONSTRAINT_KEYS = (
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


class CompletionBaselineError(RuntimeError):
    """Only a fixed safe code crosses the startup/operator boundary."""


class BaselineState(str, Enum):
    ABSENT = "ABSENT"
    COMPLETE = "COMPLETE"
    PARTIAL_OR_UNKNOWN = "PARTIAL_OR_UNKNOWN"


@dataclass(frozen=True)
class CompletionTarget:
    database_oid: int
    database_name: str
    purpose: str
    session_user: str


def connect() -> AbstractContextManager[Connection[dict[str, object]]]:
    # Importing connection imports config, whose module loads dotenv. Defer that
    # dependency until an actual, metadata-admitted connection is requested.
    from app.db.connection import connect as connect_database

    return connect_database()


def selected_contract() -> str | None:
    value = os.environ.get("AEARN_DATABASE_CONTRACT")
    if value is None:
        return None
    if value != CONTRACT_ID:
        raise CompletionBaselineError("COMPLETION_BASELINE_CONTRACT_REJECTED")
    return value


_BASE_EXPORTS = (
    "BASE_EXTENSIONS", "BASE_TABLES", "BASE_RELATION_METADATA", "BASE_COLUMNS",
    "BASE_CONSTRAINTS", "BASE_INDEXES", "BASE_TRIGGER_DEFINITIONS", "BASE_POLICIES",
    "BASE_FUNCTIONS", "BASE_FUNCTION_METADATA", "BASE_SCHEMA_METADATA", "BASE_TABLE_ACLS",
    "BASE_COLUMN_ACLS", "BASE_SEQUENCES", "BASE_SEQUENCE_METADATA", "BASE_LOCK_RELATIONS",
)
_POSTINSTALL_EXPORTS = (
    "EXPECTED_EXTENSIONS", "EXPECTED_TABLES", "EXPECTED_RELATION_METADATA", "EXPECTED_COLUMNS",
    "EXPECTED_CONSTRAINTS", "EXPECTED_INDEXES", "EXPECTED_TRIGGERS",
    "EXPECTED_TRIGGER_DEFINITIONS", "EXPECTED_POLICIES", "EXPECTED_FUNCTIONS",
    "FUNCTION_METADATA", "EXPECTED_SCHEMA_METADATA", "EXPECTED_TABLE_ACLS", "EXPECTED_COLUMN_ACLS",
    "EXPECTED_ROLE_METADATA", "EXPECTED_ROLE_MEMBERSHIPS", "EXPECTED_DEFAULT_ACLS",
    "NEW_TABLES", "NEW_FUNCTIONS", "NEW_SCHEMAS",
    "EXPECTED_SEQUENCES", "EXPECTED_SEQUENCE_METADATA", "NEW_SEQUENCES",
)


def _development_constraint_overrides(metadata: ModuleType) -> dict[tuple[str, str], tuple[Row, Row]]:
    pairs = getattr(metadata, "DEVELOPMENT_CONSTRAINT_OVERRIDES", None)
    if not isinstance(pairs, tuple) or len(pairs) != len(_DEVELOPMENT_CONSTRAINT_KEYS):
        raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INCOMPLETE")
    replacements: dict[tuple[str, str], tuple[Row, Row]] = {}
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2 or any(
            not isinstance(row, tuple) or len(row) != 7
            or not isinstance(row[0], str) or not isinstance(row[1], str)
            or row[2] != "c" or not isinstance(row[3], str) or not row[3]
            or any(type(flag) is not bool for flag in row[4:])
            or row[4:] != (True, False, False)
            for row in pair
        ):
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
        clone, development = pair
        key = (clone[0], clone[1])
        if (key not in _DEVELOPMENT_CONSTRAINT_KEYS or key in replacements
                or clone[:3] + clone[4:] != development[:3] + development[4:]
                or clone[3] == development[3]):
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
        replacements[key] = (clone, development)
    return replacements


def _metadata_for_target(metadata: ModuleType, *, target: CompletionTarget) -> ModuleType:
    # This is one fixed target exception, not per-database registration or a
    # set of alternative definitions accepted on every database.
    if target.database_name != "postgres" or target.purpose != "runtime-purpose":
        return metadata
    replacements = _development_constraint_overrides(metadata)
    selected = ModuleType("completion_non_b1d_development_contract")
    selected.__dict__.update(metadata.__dict__)
    for name in ("BASE_CONSTRAINTS", "EXPECTED_CONSTRAINTS"):
        seen: set[tuple[str, str]] = set()
        updated: list[Row] = []
        for row in getattr(metadata, name):
            if not isinstance(row, tuple) or len(row) != 7:
                raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
            key = (row[0], row[1])
            if key in replacements:
                clone, development = replacements[key]
                if key in seen or row != clone:
                    raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
                seen.add(key)
                updated.append(development)
            else:
                updated.append(row)
        if seen != set(replacements):
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INCOMPLETE")
        setattr(selected, name, tuple(updated))
    return selected


def _metadata(*, storage_check: bool = False) -> ModuleType:
    module = importlib.import_module("app.db.completion_baseline_contract")
    if getattr(module, "CATALOG_CANONICALIZED", False) is not True:
        raise CompletionBaselineError("COMPLETION_BASELINE_CATALOG_NOT_CANONICAL")
    if storage_check:
        # A fixed second purpose, not arbitrary migrations or a best-effort
        # overlay: every BASE/postinstall category must have a complete literal map.
        selected = ModuleType("completion_non_b1d_storage_contract")
        selected.__dict__.update(module.__dict__)
        for name in (*_BASE_EXPORTS, *_POSTINSTALL_EXPORTS):
            if not hasattr(module, "VALIDATION_" + name):
                raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INCOMPLETE")
            selected.__dict__[name] = getattr(module, "VALIDATION_" + name)
        module = selected
    if (
        module.CONTRACT_ID != CONTRACT_ID
        or module.RUNTIME_DATABASE_NAMES != RUNTIME_DATABASE_NAMES
        or module.VALIDATION_DATABASE_NAME != VALIDATION_DATABASE_NAME
    ):
        raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
    from app.db.schema import (
        RUNTIME_FORWARD_FRAGMENT_NAMES,
        SCHEMA_FORWARD_FRAGMENT_NAMES,
        VALIDATION_FORWARD_FRAGMENT_NAMES,
    )

    if (
        module.FORWARD_FRAGMENT_NAMES != SCHEMA_FORWARD_FRAGMENT_NAMES
        or module.RUNTIME_FORWARD_FRAGMENT_NAMES != RUNTIME_FORWARD_FRAGMENT_NAMES
        or module.VALIDATION_FORWARD_FRAGMENT_NAMES != VALIDATION_FORWARD_FRAGMENT_NAMES
    ):
        raise CompletionBaselineError("COMPLETION_BASELINE_PLAN_REJECTED")
    if not storage_check:
        _development_constraint_overrides(module)
    # These are real finite catalog inventories, not marker/count substitutes.
    for name in (
        "EXPECTED_EXTENSIONS", "BASE_EXTENSIONS", "EXPECTED_TABLES", "EXPECTED_COLUMNS", "EXPECTED_CONSTRAINTS",
        "EXPECTED_INDEXES", "EXPECTED_FUNCTIONS", "FUNCTION_METADATA",
        "EXPECTED_RELATION_METADATA", "EXPECTED_SCHEMA_METADATA",
        "EXPECTED_TABLE_ACLS", "EXPECTED_ROLE_METADATA", "BASE_TABLES",
        "BASE_COLUMNS", "BASE_CONSTRAINTS", "BASE_INDEXES",
        "BASE_RELATION_METADATA", "BASE_FUNCTIONS", "BASE_FUNCTION_METADATA", "BASE_LOCK_RELATIONS",
    ):
        if not getattr(module, name, None):
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INCOMPLETE")
    for name in (
        "EXPECTED_TRIGGERS", "EXPECTED_TRIGGER_DEFINITIONS", "EXPECTED_POLICIES",
        "EXPECTED_DEFAULT_ACLS", "EXPECTED_ROLE_MEMBERSHIPS", "BASE_SCHEMA_METADATA",
        "BASE_TABLE_ACLS", "BASE_TRIGGER_DEFINITIONS", "BASE_POLICIES",
        "NEW_TABLES", "NEW_FUNCTIONS", "NEW_SCHEMAS",
        "MANAGED_PUBLIC_RELATION_PREFIXES", "MANAGED_PUBLIC_FUNCTION_PREFIXES",
        "EXPECTED_SEQUENCES", "EXPECTED_SEQUENCE_METADATA", "BASE_SEQUENCES",
        "BASE_SEQUENCE_METADATA", "NEW_SEQUENCES", "BASE_COLUMN_ACLS", "EXPECTED_COLUMN_ACLS",
    ):
        if not isinstance(getattr(module, name, None), tuple):
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INCOMPLETE")
    for name in ("BASE_FUNCTION_METADATA", "FUNCTION_METADATA"):
        rows = getattr(module, name)
        if not isinstance(rows, tuple) or any(
            not isinstance(row, tuple) or len(row) != 11
            or (row[5] is not None and (
                not isinstance(row[5], tuple) or any(
                    not isinstance(acl, tuple) or len(acl) != 2
                    or not isinstance(acl[0], str) or type(acl[1]) is not bool
                    for acl in row[5]
                )
            ))
            for row in rows
        ):
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
    if (
        set(module.EXPECTED_TABLES) != {row[0] for row in module.EXPECTED_RELATION_METADATA}
        or set(module.EXPECTED_TABLES) != {row[0] for row in module.EXPECTED_COLUMNS}
        or set(module.EXPECTED_TABLES) != {row[0] for row in module.EXPECTED_TABLE_ACLS}
        or set(module.EXPECTED_FUNCTIONS) != {row[0] for row in module.FUNCTION_METADATA}
        or set(module.BASE_TABLES) != {row[0] for row in module.BASE_RELATION_METADATA}
        or set(module.BASE_TABLES) != {row[0] for row in module.BASE_COLUMNS}
        or set(module.BASE_TABLES) != {row[0] for row in module.BASE_TABLE_ACLS}
        or set(module.BASE_FUNCTIONS) != {row[0] for row in module.BASE_FUNCTION_METADATA}
        or "public" not in {row[0] for row in module.BASE_SCHEMA_METADATA}
        or not {"public", *module.NEW_SCHEMAS}.issubset(row[0] for row in module.EXPECTED_SCHEMA_METADATA)
        or set(ROLE_NAMES) != {row[0] for row in module.EXPECTED_ROLE_METADATA}
        or not module.NEW_TABLES or not module.NEW_SCHEMAS or not module.NEW_FUNCTIONS
    ):
        raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INCOMPLETE")
    for prefix in ("BASE_", "EXPECTED_"):
        # Sparse raw attacl: NULL has no row; an explicit empty ACL has a row
        # whose third field is (). Do not infer column grants from table ACLs.
        columns = {(row[0], row[1]) for row in getattr(module, prefix + "COLUMNS")
                   if isinstance(row, tuple) and len(row) >= 2}
        seen: set[tuple[str, str]] = set()
        for row in getattr(module, prefix + "COLUMN_ACLS"):
            if (
                not isinstance(row, tuple) or len(row) != 3
                or not isinstance(row[0], str) or not isinstance(row[1], str)
                or (row[0], row[1]) not in columns or (row[0], row[1]) in seen
                or not isinstance(row[2], tuple)
                or any(not isinstance(grant, tuple) or len(grant) != 3
                       or not isinstance(grant[0], str) or not grant[0]
                       or not isinstance(grant[1], str) or not grant[1]
                       or not isinstance(grant[2], bool) for grant in row[2])
            ):
                raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
            seen.add((row[0], row[1]))
    for names_key, rows_key in (("EXPECTED_SEQUENCES", "EXPECTED_SEQUENCE_METADATA"),
                                ("BASE_SEQUENCES", "BASE_SEQUENCE_METADATA")):
        names, rows = getattr(module, names_key), getattr(module, rows_key)
        if (any(not isinstance(row, tuple) or len(row) != 14 for row in rows)
                or len(names) != len(set(names)) or len(rows) != len(names)
                or set(names) != {row[0] for row in rows}):
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
    if (set(module.NEW_FUNCTIONS) & set(module.BASE_FUNCTIONS)
            or not set(module.NEW_FUNCTIONS).issubset(module.EXPECTED_FUNCTIONS)):
        raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
    if not set(module.NEW_SEQUENCES).issubset(module.EXPECTED_SEQUENCES):
        raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
    roles = tuple(module.EXPECTED_ROLE_METADATA)
    if any(
        len(row) != 9 or row[5] is not (row[0] != ROLE_NAMES[0])
        or any(row[index] is not False for index in (1, 2, 3, 4, 6, 7))
        for row in roles
    ):
        raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
    return module


def inspect_completion_target(
    conn: Connection[dict[str, object]], *, storage_check: bool = False,
    expected_database_oid: int | None = None,
) -> CompletionTarget:
    """Inspect the actual server target, never infer it from a DSN or db prefix.

    Main owns maintenance quiescence. An advisory lock does not lock business DML.
    Install/candidate callers must also pin the independently inspected DB OID.
    """
    # A local Docker PostgreSQL server reports a bridge inet_server_addr(),
    # not loopback. Pin the actual client endpoint, not that container address.
    if conn.info.host not in ("localhost", "127.0.0.1", "::1"):
        raise CompletionBaselineError("COMPLETION_BASELINE_TARGET_REJECTED")
    row = conn.execute(
        "SELECT d.oid::bigint AS database_oid, current_database() AS database_name, "
        "session_user::text AS session_user, inet_server_addr()::text AS server_address, "
        "pg_is_in_recovery() AS in_recovery FROM pg_database d "
        "WHERE d.datname = current_database()"
    ).fetchone()
    if row is None:
        raise CompletionBaselineError("COMPLETION_BASELINE_TARGET_REJECTED")
    name = str(row["database_name"])
    allowed = (VALIDATION_DATABASE_NAME,) if storage_check else RUNTIME_DATABASE_NAMES
    if (
        name not in allowed
        or row["in_recovery"] is not False
        or (expected_database_oid is not None and row["database_oid"] != expected_database_oid)
    ):
        raise CompletionBaselineError("COMPLETION_BASELINE_TARGET_REJECTED")
    return CompletionTarget(
        int(str(row["database_oid"])), name,
        "storage-validation-purpose" if storage_check else "runtime-purpose", str(row["session_user"]),
    )


def _resolve_signature(signature: str) -> str:
    # The reviewed legacy identities use public composite arguments without a
    # namespace. Resolve only those fixed-domain types, never rewrite prosrc,
    # constraint expressions, casts, or a SQL fragment.
    name, arguments = signature.split("(", 1)
    types = arguments.removesuffix(")").split(",") if arguments != ")" else []
    qualified = ["public." + value.strip() if value.strip().startswith(("tutor_", "rag_"))
                 else value.strip() for value in types]
    return name + "(" + ",".join(qualified) + ")"


def set_catalog_search_path(conn: Connection[dict[str, object]]) -> None:
    """Use this exact path for Main's BASE/post capture and loader comparison.

    The caller owns the transaction. SET LOCAL in idle autocommit mode would be
    ignored by PostgreSQL, so do not silently produce ambient-path identities.
    This never changes rendered SQL, expression strings, or stored function paths.
    """
    if conn.autocommit and conn.info.transaction_status != TransactionStatus.INTRANS:
        raise CompletionBaselineError("COMPLETION_BASELINE_TRANSACTION_REQUIRED")
    conn.execute(CATALOG_SEARCH_PATH_SQL)


def _rows(conn: Connection[dict[str, object]], query: str, names: tuple[str, ...]) -> Rows:
    # Also covers independent catalog captures and callers after DDL changes the
    # ambient path. Names and expressions remain raw PostgreSQL output.
    set_catalog_search_path(conn)
    params = (list(names), [_resolve_signature(name) for name in names]) if query == _CATALOG_QUERIES["FUNCTION_METADATA"] else (list(names),)
    return tuple(
        tuple(row["item"])  # type: ignore[arg-type]
        for row in conn.execute(query, params).fetchall()
    )


# Each query returns complete rows in a single JSON value. Exact comparison is
# intentional: removing parentheses/casts can erase a real SQL semantic change.
_CATALOG_QUERIES = {
    "EXTENSIONS": """
        SELECT jsonb_build_array(e.extname,e.extversion,n.nspname,
          pg_get_userbyid(e.extowner)) AS item
        FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname=ANY(%s::text[])
    """,
    "RELATION_METADATA": """
        SELECT jsonb_build_array(c.oid::regclass::text, pg_get_userbyid(c.relowner),
          c.relkind::text, c.relrowsecurity, c.relforcerowsecurity) AS item
        FROM pg_class c WHERE c.oid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
    """,
    "COLUMNS": """
        SELECT jsonb_build_array(a.attrelid::regclass::text, a.attname,
          format_type(a.atttypid,a.atttypmod), a.attnotnull, a.attgenerated::text,
          pg_get_expr(d.adbin,d.adrelid,false)) AS item
        FROM pg_attribute a LEFT JOIN pg_attrdef d
          ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
          AND a.attnum>0 AND NOT a.attisdropped
    """,
    "CONSTRAINTS": """
        SELECT jsonb_build_array(c.conrelid::regclass::text,c.conname,c.contype::text,
          pg_get_constraintdef(c.oid,false),c.convalidated,c.condeferrable,c.condeferred) AS item
        FROM pg_constraint c
        WHERE c.conrelid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
    """,
    "INDEXES": """
        SELECT jsonb_build_array(i.indrelid::regclass::text,c.relname,
          pg_get_indexdef(i.indexrelid,0,false),i.indisvalid,i.indisready) AS item
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        WHERE i.indrelid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
    """,
    "TRIGGER_DEFINITIONS": """
        SELECT jsonb_build_array(t.tgrelid::regclass::text,t.tgname,
          pg_get_triggerdef(t.oid,false),t.tgenabled::text) AS item
        FROM pg_trigger t
        WHERE t.tgrelid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
          AND NOT t.tgisinternal
    """,
    "POLICIES": """
        SELECT jsonb_build_array(p.polrelid::regclass::text,p.polname,p.polcmd::text,
          p.polpermissive,ARRAY(SELECT CASE WHEN x=0 THEN 'PUBLIC'
            ELSE pg_get_userbyid(x) END FROM unnest(p.polroles) x ORDER BY 1),
          pg_get_expr(p.polqual,p.polrelid,false),
          pg_get_expr(p.polwithcheck,p.polrelid,false)) AS item
        FROM pg_policy p
        WHERE p.polrelid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
    """,
    "TABLE_ACLS": """
        SELECT jsonb_build_array(c.oid::regclass::text,
          (SELECT jsonb_agg(jsonb_build_array(CASE WHEN a.grantee=0 THEN 'PUBLIC'
             ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable)
             ORDER BY CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
             a.privilege_type,a.is_grantable)
           FROM aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a)) AS item
        FROM pg_class c
        WHERE c.oid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
    """,
    "COLUMN_ACLS": """
        SELECT jsonb_build_array(a.attrelid::regclass::text,a.attname,
          COALESCE((SELECT jsonb_agg(jsonb_build_array(
             CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
             acl.privilege_type,acl.is_grantable)
             ORDER BY CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
             acl.privilege_type,acl.is_grantable)
           FROM aclexplode(a.attacl) acl),'[]'::jsonb)) AS item
        FROM pg_attribute a
        WHERE a.attrelid=ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
          AND a.attnum>0 AND NOT a.attisdropped AND a.attacl IS NOT NULL
    """,
    "FUNCTION_METADATA": """
        SELECT jsonb_build_array(x.sig,pg_get_userbyid(p.proowner),p.prosecdef,
          p.provolatile::text,p.proconfig,
          (SELECT jsonb_agg(jsonb_build_array(CASE WHEN a.grantee=0 THEN 'PUBLIC'
             ELSE pg_get_userbyid(a.grantee) END,a.is_grantable)
             ORDER BY CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
             a.is_grantable)
           FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
           WHERE a.privilege_type='EXECUTE'),
          l.lanname,pg_get_function_result(p.oid),p.proisstrict,p.proparallel::text,p.prosrc) AS item
        FROM unnest(%s::text[],%s::text[]) x(sig,resolved_sig)
        JOIN pg_proc p ON p.oid=to_regprocedure(x.resolved_sig)
        JOIN pg_language l ON l.oid=p.prolang
    """,
    "SCHEMA_METADATA": """
        SELECT jsonb_build_array(n.nspname,pg_get_userbyid(n.nspowner),
          (SELECT jsonb_agg(jsonb_build_array(CASE WHEN a.grantee=0 THEN 'PUBLIC'
             ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable)
             ORDER BY CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
             a.privilege_type,a.is_grantable)
           FROM aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a)) AS item
        FROM pg_namespace n WHERE n.nspname=ANY(%s::text[])
    """,
    "SEQUENCE_METADATA": """
        SELECT jsonb_build_array(c.oid::regclass::text,pg_get_userbyid(c.relowner),
          format_type(s.seqtypid,NULL),s.seqstart,s.seqincrement,s.seqmin,s.seqmax,
          s.seqcache,s.seqcycle,parent.oid::regclass::text,a.attname,d.deptype::text,
          a.attidentity::text,
          (SELECT jsonb_agg(jsonb_build_array(CASE WHEN acl.grantee=0 THEN 'PUBLIC'
             ELSE pg_get_userbyid(acl.grantee) END,acl.privilege_type,acl.is_grantable)
             ORDER BY CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
             acl.privilege_type,acl.is_grantable)
           FROM aclexplode(COALESCE(c.relacl,acldefault('S',c.relowner))) acl)) AS item
        FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid
        LEFT JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=c.oid
          AND d.objsubid=0 AND d.refclassid='pg_class'::regclass
          AND d.refobjsubid>0 AND d.deptype IN ('a','i')
        LEFT JOIN pg_class parent ON parent.oid=d.refobjid
        LEFT JOIN pg_attribute a ON a.attrelid=parent.oid AND a.attnum=d.refobjsubid
        WHERE c.oid=ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) x)
          AND c.relkind='S'
    """,
    "ROLE_METADATA": """
        SELECT jsonb_build_array(rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,
          rolcanlogin,rolreplication,rolbypassrls,shobj_description(oid,'pg_authid')) AS item FROM pg_roles
        WHERE rolname=ANY(%s::text[])
    """,
    "ROLE_MEMBERSHIPS": """
        SELECT jsonb_build_array(pg_get_userbyid(m.roleid),pg_get_userbyid(m.member),
          m.admin_option) AS item FROM pg_auth_members m
        WHERE EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname=ANY(%s::text[])
          AND r.oid IN (m.roleid,m.member))
    """,
    "DEFAULT_ACLS": """
        SELECT jsonb_build_array(pg_get_userbyid(d.defaclrole),n.nspname,
          d.defaclobjtype::text,CASE WHEN a.grantee=0 THEN 'PUBLIC'
            ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable) AS item
        FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE pg_get_userbyid(d.defaclrole)=ANY(%s::text[])
          OR n.nspname IN ('item_supply_internal','completion_baseline_internal')
    """,
}


def _freeze(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _same(actual: Rows, expected: object) -> bool:
    if not isinstance(expected, tuple):
        return False
    return sorted((repr(_freeze(row)) for row in actual)) == sorted(
        repr(_freeze(row)) for row in expected
    )


def _catalog_scopes(
    metadata: ModuleType, *, base: bool, storage_check: bool = False,
) -> dict[str, tuple[str, ...]]:
    purpose = "VALIDATION_" if storage_check else ""
    prefix = purpose + ("BASE_" if base else "EXPECTED_")
    # Capture must not depend on empty post-canonical result placeholders.
    # These are the fixed reviewed identities, not rewritten SQL/rendered rows.
    schemas = {"public", *(str(row[0]) for row in getattr(metadata, purpose + "BASE_SCHEMA_METADATA"))}
    if not base:
        schemas.update(getattr(metadata, purpose + "NEW_SCHEMAS"))
    return {
        "TABLES": tuple(getattr(metadata, prefix + "TABLES")),
        "FUNCTION_METADATA": tuple(getattr(metadata, prefix + "FUNCTIONS")),
        "SCHEMA_METADATA": tuple(sorted(schemas)),
        "EXTENSIONS": tuple(str(row[0]) for row in getattr(metadata, prefix + "EXTENSIONS")),
        "SEQUENCE_METADATA": tuple(getattr(metadata, prefix + "SEQUENCES")),
        "ROLE_METADATA": ROLE_NAMES, "ROLE_MEMBERSHIPS": ROLE_NAMES, "DEFAULT_ACLS": ROLE_NAMES,
    }


def capture_completion_catalog(
    conn: Connection[dict[str, object]], *, metadata: ModuleType, base: bool,
    storage_check: bool = False,
) -> dict[str, Rows]:
    """Capture raw runtime/validation BASE or post via the comparison queries.

    Main supplies the authored metadata module and owns connection, target,
    transaction, DDL and final rollback/commit. Capture is deliberately available
    while CATALOG_CANONICALIZED is False so Main can collect the missing data;
    it neither changes that flag nor validates readiness/installation authority.
    Each query reasserts the same explicit path, including BASE and column ACLs.
    """
    scopes = _catalog_scopes(metadata, base=base, storage_check=storage_check)
    return {category: _rows(conn, query, scopes.get(category, scopes["TABLES"]))
            for category, query in _CATALOG_QUERIES.items()}


def _catalog_matches(conn: Connection[dict[str, object]], metadata: ModuleType, *, base: bool) -> bool:
    prefix = "BASE_" if base else "EXPECTED_"
    function_metadata = getattr(metadata, "BASE_FUNCTION_METADATA" if base else "FUNCTION_METADATA")
    scopes = _catalog_scopes(metadata, base=base)
    tables = scopes["TABLES"]
    functions = scopes["FUNCTION_METADATA"]
    categories = (
        "EXTENSIONS", "RELATION_METADATA", "COLUMNS", "CONSTRAINTS", "INDEXES",
        "TRIGGER_DEFINITIONS", "POLICIES", "TABLE_ACLS", "COLUMN_ACLS", "FUNCTION_METADATA", "SCHEMA_METADATA",
        "SEQUENCE_METADATA",
    )
    for category in categories:
        expected = function_metadata if category == "FUNCTION_METADATA" else getattr(metadata, prefix + category)
        actual = _rows(conn, _CATALOG_QUERIES[category], scopes.get(category, tables))
        if not _same(actual, expected):
            return False
    # Column ACLs above are exact: additional grants/columns are catalog drift.
    disabled_fk = conn.execute(
        "SELECT 1 FROM pg_trigger WHERE tgrelid=ANY(SELECT to_regclass(x) "
        "FROM unnest(%s::text[]) x) AND tgisinternal AND tgenabled NOT IN ('O','A') LIMIT 1",
        (list(tables),),
    ).fetchone()
    unsafe_function = conn.execute(
        "SELECT 1 FROM pg_proc WHERE oid=ANY(SELECT to_regprocedure(x) "
        "FROM unnest(%s::text[]) x) AND (proleakproof OR prokind <> 'f' OR prosupport <> 0) LIMIT 1",
        ([_resolve_signature(signature) for signature in functions],),
    ).fetchone()
    return disabled_fk is None and unsafe_function is None


def _public_domain_matches(
    conn: Connection[dict[str, object]], metadata: ModuleType, *, base: bool,
) -> bool:
    tables = (metadata.BASE_TABLES + metadata.BASE_SEQUENCES if base
              else metadata.EXPECTED_TABLES + metadata.EXPECTED_SEQUENCES)
    functions = metadata.BASE_FUNCTION_METADATA if base else metadata.FUNCTION_METADATA
    extra = conn.execute(
        "SELECT 1 WHERE EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind NOT IN ('i','I') "
        "AND EXISTS (SELECT 1 FROM unnest(%s::text[]) prefix "
        "WHERE left(c.relname,length(prefix))=prefix) "
        "AND c.oid NOT IN (SELECT to_regclass(x) FROM unnest(%s::text[]) x)) "
        "OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND EXISTS (SELECT 1 FROM unnest(%s::text[]) prefix "
        "WHERE left(p.proname,length(prefix))=prefix) AND p.oid NOT IN "
        "(SELECT to_regprocedure(x) FROM unnest(%s::text[]) x))",
        (list(metadata.MANAGED_PUBLIC_RELATION_PREFIXES), list(tables),
         list(metadata.MANAGED_PUBLIC_FUNCTION_PREFIXES), [_resolve_signature(row[0]) for row in functions]),
    ).fetchone()
    return extra is None


def _namespace_matches(conn: Connection[dict[str, object]], metadata: ModuleType) -> bool:
    """Reject unlisted helpers/relations in the newly owned private schemas."""
    extra = conn.execute(
        "SELECT 1 WHERE EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s::text[]) "
        "AND c.oid NOT IN (SELECT to_regclass(x) FROM unnest(%s::text[]) x)) "
        "OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname=ANY(%s::text[]) AND p.oid NOT IN "
        "(SELECT to_regprocedure(x) FROM unnest(%s::text[]) x))",
        (list(metadata.NEW_SCHEMAS), list(metadata.EXPECTED_TABLES) + list(metadata.EXPECTED_SEQUENCES) + [
            str(row[0]).rsplit(".", 1)[0] + "." + str(row[1]) for row in metadata.EXPECTED_INDEXES
        ], list(metadata.NEW_SCHEMAS), [_resolve_signature(s) for s in metadata.EXPECTED_FUNCTIONS]),
    ).fetchone()
    return extra is None


def classify_completion_baseline(
    conn: Connection[dict[str, object]], *, target: CompletionTarget,
) -> BaselineState:
    metadata = _metadata(storage_check=target.purpose == "storage-validation-purpose")
    metadata = _metadata_for_target(metadata, target=target)
    # Keep regclass output schema-qualified and function bodies/search paths
    # independent of the connection's ambient search_path.
    set_catalog_search_path(conn)
    present = conn.execute(
        "SELECT 1 WHERE EXISTS (SELECT 1 FROM unnest(%s::text[]) x "
        "WHERE to_regclass(x) IS NOT NULL) OR EXISTS (SELECT 1 FROM pg_namespace "
        "WHERE nspname=ANY(%s::text[])) OR EXISTS (SELECT 1 FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname || '.' || p.proname = ANY(%s::text[]))",
        (list(metadata.NEW_TABLES) + list(metadata.NEW_SEQUENCES), list(metadata.NEW_SCHEMAS),
         [signature.split("(", 1)[0] for signature in metadata.NEW_FUNCTIONS]),
    ).fetchone()
    if present is None:
        # Cluster roles may already exist because the other named target was
        # installed first, but any existing role must match the fixed attributes.
        roles = _rows(conn, _CATALOG_QUERIES["ROLE_METADATA"], ROLE_NAMES)
        role_names = {row[0] for row in roles}
        role_match = _same(roles, tuple(row for row in metadata.EXPECTED_ROLE_METADATA if row[0] in role_names))
        role_memberships = _rows(conn, _CATALOG_QUERIES["ROLE_MEMBERSHIPS"], ROLE_NAMES)
        if (
            role_match
            and _same(role_memberships, metadata.EXPECTED_ROLE_MEMBERSHIPS)
            and _same(_rows(conn, _CATALOG_QUERIES["DEFAULT_ACLS"], ROLE_NAMES), metadata.EXPECTED_DEFAULT_ACLS)
            and _catalog_matches(conn, metadata, base=True)
            and _public_domain_matches(conn, metadata, base=True)
        ):
            return BaselineState.ABSENT
        return BaselineState.PARTIAL_OR_UNKNOWN
    if (not _catalog_matches(conn, metadata, base=False)
            or not _namespace_matches(conn, metadata)
            or not _public_domain_matches(conn, metadata, base=False)):
        return BaselineState.PARTIAL_OR_UNKNOWN
    roles = _rows(conn, _CATALOG_QUERIES["ROLE_METADATA"], ROLE_NAMES)
    if not _same(roles, metadata.EXPECTED_ROLE_METADATA):
        return BaselineState.PARTIAL_OR_UNKNOWN
    for category in ("ROLE_MEMBERSHIPS", "DEFAULT_ACLS"):
        if not _same(_rows(conn, _CATALOG_QUERIES[category], ROLE_NAMES), getattr(metadata, "EXPECTED_" + category)):
            return BaselineState.PARTIAL_OR_UNKNOWN
    identity = conn.execute("SELECT * FROM completion_baseline_internal.contract_identity()").fetchone()
    if identity != {
        "database_oid": target.database_oid, "database_name": target.database_name,
        "contract_id": CONTRACT_ID, "purpose": target.purpose,
    }:
        return BaselineState.PARTIAL_OR_UNKNOWN
    return BaselineState.COMPLETE


def check_completion_baseline(*, storage_check: bool = False) -> None:
    try:
        _metadata(storage_check=storage_check)
        with connect() as conn:
            try:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                target = inspect_completion_target(conn, storage_check=storage_check)
                if classify_completion_baseline(conn, target=target) is not BaselineState.COMPLETE:
                    raise CompletionBaselineError("COMPLETION_BASELINE_NOT_READY")
            finally:
                conn.rollback()
    except CompletionBaselineError:
        raise
    except Exception:
        raise CompletionBaselineError("COMPLETION_BASELINE_CHECK_FAILED") from None


def _startup_connection_scope() -> tuple[str, str]:
    # Resolve the configuration actually used by connect(), including cached
    # Settings and dotenv precedence, only when startup is invoked. Parsing
    # conninfo is local: no libpq connection or service/credential file is opened.
    try:
        from app.core.config import get_settings
        from psycopg.conninfo import conninfo_to_dict

        options = conninfo_to_dict(get_settings().database_url)
        user = str(options.get("user") or os.environ.get("PGUSER", ""))
        database = str(options.get("dbname") or os.environ.get("PGDATABASE", ""))
        if (options.get("service") or os.environ.get("PGSERVICE")) and (
            not user or not database
        ):
            raise ValueError("unresolved service scope")
        return database or user, user
    except Exception:
        raise CompletionBaselineError("COMPLETION_BASELINE_CONFIGURATION_REJECTED") from None


def ensure_startup_contract(*, entrypoint: str) -> None:
    """Reject protected DSNs without the selector; genuine legacy makes no DB IO."""
    database, user = _startup_connection_scope()
    selected = selected_contract()  # config import may have loaded the selector
    if selected is None:
        if database == VALIDATION_DATABASE_NAME or user in ROLE_NAMES:
            raise CompletionBaselineError("COMPLETION_BASELINE_CONTRACT_REQUIRED")
        return
    if not entrypoint:
        raise CompletionBaselineError("COMPLETION_BASELINE_ENTRYPOINT_REJECTED")
    if database == VALIDATION_DATABASE_NAME:
        raise CompletionBaselineError("COMPLETION_BASELINE_TARGET_REJECTED")
    check_completion_baseline()
