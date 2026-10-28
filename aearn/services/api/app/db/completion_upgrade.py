"""Finite installed-prefix upgrades; never arbitrary PARTIAL recovery or startup DDL.

The latest full purpose-specific catalog remains authoritative. The only old
catalogs admitted here differ by the six exact non-grantable runtime SELECTs
introduced in frozen SQL601/602. No SQL number or marker establishes readiness.
Cold imports do not read configuration, credentials or the database.
"""

from dataclasses import dataclass
from types import ModuleType

from psycopg import Connection

from app.db.completion_baseline import (
    CONTRACT_ID,
    CompletionBaselineError,
    CompletionTarget,
    _catalog_matches,
    _metadata,
    _metadata_for_target,
    _namespace_matches,
    _public_domain_matches,
    _same,
    capture_completion_catalog,
    connect,
    inspect_completion_target,
)

_INVENTORY_FRAGMENT = "601_completion_non_b1d_inventory_reads.sql"
_PLANNING_FRAGMENT = "602_completion_non_b1d_planning_catalog_reads.sql"
_RUNTIME_SELECT = ("aearn_cb_runtime_20261027", "SELECT", False)
_FRAGMENT_RELATIONS = {
    _INVENTORY_FRAGMENT: (
        "public.rag_source_reviews", "public.rag_source_admissions", "public.rag_source_claim_receipts",
    ),
    _PLANNING_FRAGMENT: (
        "public.language_courses", "public.language_course_intent_tags", "public.tutor_learning_intents",
    ),
}
_CATEGORY_EXPORTS = {
    "EXTENSIONS": "EXPECTED_EXTENSIONS",
    "RELATION_METADATA": "EXPECTED_RELATION_METADATA",
    "COLUMNS": "EXPECTED_COLUMNS",
    "CONSTRAINTS": "EXPECTED_CONSTRAINTS",
    "INDEXES": "EXPECTED_INDEXES",
    "TRIGGER_DEFINITIONS": "EXPECTED_TRIGGER_DEFINITIONS",
    "POLICIES": "EXPECTED_POLICIES",
    "TABLE_ACLS": "EXPECTED_TABLE_ACLS",
    "COLUMN_ACLS": "EXPECTED_COLUMN_ACLS",
    "FUNCTION_METADATA": "FUNCTION_METADATA",
    "SCHEMA_METADATA": "EXPECTED_SCHEMA_METADATA",
    "SEQUENCE_METADATA": "EXPECTED_SEQUENCE_METADATA",
    "ROLE_METADATA": "EXPECTED_ROLE_METADATA",
    "ROLE_MEMBERSHIPS": "EXPECTED_ROLE_MEMBERSHIPS",
    "DEFAULT_ACLS": "EXPECTED_DEFAULT_ACLS",
}


@dataclass(frozen=True)
class CompletionUpgradePlan:
    target: CompletionTarget
    predecessor: str
    fragment_names: tuple[str, ...]


def _upgrade_metadata(*, storage_check: bool) -> ModuleType:
    metadata = _metadata(storage_check=storage_check)
    runtime = ("599_completion_non_b1d_baseline.sql", _INVENTORY_FRAGMENT, _PLANNING_FRAGMENT)
    if (metadata.RUNTIME_FORWARD_FRAGMENT_NAMES != runtime
            or metadata.VALIDATION_FORWARD_FRAGMENT_NAMES != runtime + ("600_completion_non_b1d_validation.sql",)):
        raise CompletionBaselineError("COMPLETION_BASELINE_UPGRADE_METADATA_REJECTED")
    return metadata


def _predecessor_metadata(metadata: ModuleType, missing: tuple[str, ...]) -> ModuleType:
    """Subtract exact reviewed grants, preserving every other row and value."""
    relations = {relation for name in missing for relation in _FRAGMENT_RELATIONS[name]}
    seen: set[str] = set()
    updated = []
    for relation, grants in metadata.EXPECTED_TABLE_ACLS:
        if relation in relations:
            if relation in seen or grants.count(_RUNTIME_SELECT) != 1:
                raise CompletionBaselineError("COMPLETION_BASELINE_UPGRADE_METADATA_REJECTED")
            seen.add(relation)
            grants = tuple(grant for grant in grants if grant != _RUNTIME_SELECT)
        updated.append((relation, grants))
    if seen != relations:
        raise CompletionBaselineError("COMPLETION_BASELINE_UPGRADE_METADATA_REJECTED")
    predecessor = ModuleType("completion_known_predecessor")
    predecessor.__dict__.update(metadata.__dict__)
    setattr(predecessor, "EXPECTED_TABLE_ACLS", tuple(updated))
    return predecessor


def _inspect_completion_upgrade_on_connection(
    conn: Connection[dict[str, object]], *, target: CompletionTarget,
) -> CompletionUpgradePlan:
    """Private readonly inspection in the caller's transaction, no write authority."""
    storage_check = target.purpose == "storage-validation-purpose"
    actual_target = inspect_completion_target(
        conn, storage_check=storage_check, expected_database_oid=target.database_oid,
    )
    if actual_target != target:
        raise CompletionBaselineError("COMPLETION_BASELINE_TARGET_REJECTED")
    metadata = _metadata_for_target(_upgrade_metadata(storage_check=storage_check), target=target)
    # A validation overlay already contains its own complete BASE/post exports;
    # don't overlay it again or substitute the runtime-purpose inventories.
    actual = capture_completion_catalog(conn, metadata=metadata, base=False)
    if set(actual) != set(_CATEGORY_EXPORTS):
        raise CompletionBaselineError("COMPLETION_BASELINE_UPGRADE_METADATA_REJECTED")
    for predecessor, missing in (
        ("602", ()),
        ("601", (_PLANNING_FRAGMENT,)),
        ("599", (_INVENTORY_FRAGMENT, _PLANNING_FRAGMENT)),
    ):
        expected = _predecessor_metadata(metadata, missing)
        if not all(_same(actual[category], getattr(expected, export))
                   for category, export in _CATEGORY_EXPORTS.items()):
            continue
        # Reuse the existing live catalog safety checks, including disabled
        # internal triggers and unsafe functions, not only the 15 raw exports.
        if (not _catalog_matches(conn, expected, base=False)
                or not _namespace_matches(conn, expected)
                or not _public_domain_matches(conn, expected, base=False)):
            break
        identity = conn.execute("SELECT * FROM completion_baseline_internal.contract_identity()").fetchone()
        if identity != {
            "database_oid": target.database_oid, "database_name": target.database_name,
            "contract_id": CONTRACT_ID, "purpose": target.purpose,
        }:
            break
        return CompletionUpgradePlan(target, predecessor, missing)
    raise CompletionBaselineError("COMPLETION_BASELINE_UPGRADE_PREDECESSOR_REJECTED")


def inspect_completion_upgrade(*, storage_check: bool = False) -> CompletionUpgradePlan:
    """Owned readonly snapshot; a plan is advisory, never reused by installation."""
    try:
        _upgrade_metadata(storage_check=storage_check)
        with connect() as conn:
            try:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                target = inspect_completion_target(conn, storage_check=storage_check)
                return _inspect_completion_upgrade_on_connection(conn, target=target)
            finally:
                conn.rollback()
    except CompletionBaselineError:
        raise
    except Exception:
        raise CompletionBaselineError("COMPLETION_BASELINE_UPGRADE_INSPECTION_FAILED") from None
