import argparse
import json
from importlib import import_module
from time import sleep
from typing import NoReturn

from psycopg import Connection, sql
from psycopg.errors import DeadlockDetected, SerializationFailure

from app.db.completion_baseline import (
    connect,
    CONTRACT_ID,
    BaselineState,
    CompletionBaselineError,
    _metadata,
    check_completion_baseline,
    classify_completion_baseline,
    ensure_startup_contract,
    inspect_completion_target,
    selected_contract,
)
from app.db.schema import load_schema_fragments
from app.db.completion_upgrade import (
    _inspect_completion_upgrade_on_connection,
    inspect_completion_upgrade,
)
from app.db.seeds import (
    ARCHIVED_LANGUAGE_COURSE_SLUGS,
    LANGUAGE_COURSE_INTENT_TAG_SEEDS,
    LANGUAGE_COURSE_SEEDS,
    LEARNING_INTENT_SEEDS,
    PLANNING_INTENT_POLICY_VERSION,
    RUNTIME_PROFILE_SEEDS,
)


_BOOTSTRAP_ADVISORY_LOCK_KEY = 0x414541524E534348
_BOOTSTRAP_MAX_ATTEMPTS = 3
_BOOTSTRAP_RETRY_DELAY_SECONDS = 0.05
_RETRIABLE_BOOTSTRAP_ERRORS = (DeadlockDetected, SerializationFailure)


def import_curated_learning_item_sources(conn: Connection[dict[str, object]]) -> None:
    # The legacy importer pulls in runtime configuration. Keep it out of cold
    # imports and the named read-only / candidate / install paths.
    from app.services.learning.item_bank.importer import import_curated_learning_item_sources as import_sources

    import_sources(conn)


def bootstrap_database() -> None:
    """Explicit historical maintenance/test API, never the normal CLI path.

    Completion selection is check-only. Without a selector, existing explicit
    maintenance/test callers retain legacy replay/seed behavior. That replay is
    not a supported empty-database completion installer.
    """
    # Preserve legacy dotenv selection at execution, never at module import.
    import_module("app.core.config")
    # The opt-in contract never reaches the historical DDL/seed/import branch.
    if selected_contract() is not None:
        check_completion_baseline()
        return
    # An omitted selector must not send a dedicated new-domain DSN through the
    # historical 163-fragment/seed path either.
    ensure_startup_contract(entrypoint="legacy-bootstrap")
    for attempt in range(_BOOTSTRAP_MAX_ATTEMPTS):
        try:
            with connect() as conn:
                # Serialize bootstrap owners across API, tests, and worker processes.
                # Business DML does not take this lock, so deadlocks still retry the
                # complete transaction instead of committing partial fragments.
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_BOOTSTRAP_ADVISORY_LOCK_KEY,))
                apply_schema(conn)
                seed_runtime_profiles(conn)
                seed_language_courses(conn)
                archive_language_courses(conn)
                seed_learning_intents(conn)
                seed_language_course_intent_tags(conn)
                require_language_course_intent_coverage(conn)
                import_curated_learning_item_sources(conn)
                conn.commit()
            return
        except _RETRIABLE_BOOTSTRAP_ERRORS:
            if attempt + 1 >= _BOOTSTRAP_MAX_ATTEMPTS:
                raise
            sleep(_BOOTSTRAP_RETRY_DELAY_SECONDS * (attempt + 1))


def apply_schema(conn: Connection[dict[str, object]]) -> None:
    for fragment in load_schema_fragments():
        conn.execute(fragment.sql)


def seed_runtime_profiles(conn: Connection[dict[str, object]]) -> None:
    for seed in RUNTIME_PROFILE_SEEDS:
        conn.execute(
            """
            INSERT INTO runtime_profiles (
              slug, runtime_tier, language, runner, supports_realtime_preview,
              supports_stdout, supports_tests, compile_required, timeout_ms,
              memory_limit_mb, sandbox_policy
            )
            VALUES (
              %(slug)s, %(runtime_tier)s, %(language)s, %(runner)s,
              %(supports_realtime_preview)s, %(supports_stdout)s, %(supports_tests)s,
              %(compile_required)s, %(timeout_ms)s, %(memory_limit_mb)s,
              %(sandbox_policy)s::jsonb
            )
            ON CONFLICT (slug) DO UPDATE SET
              runtime_tier = EXCLUDED.runtime_tier,
              language = EXCLUDED.language,
              runner = EXCLUDED.runner,
              supports_realtime_preview = EXCLUDED.supports_realtime_preview,
              supports_stdout = EXCLUDED.supports_stdout,
              supports_tests = EXCLUDED.supports_tests,
              compile_required = EXCLUDED.compile_required,
              timeout_ms = EXCLUDED.timeout_ms,
              memory_limit_mb = EXCLUDED.memory_limit_mb,
              sandbox_policy = EXCLUDED.sandbox_policy,
              archived_at = NULL
            """,
            seed | {"sandbox_policy": json.dumps(seed["sandbox_policy"])},
        )


def seed_language_courses(conn: Connection[dict[str, object]]) -> None:
    for seed in LANGUAGE_COURSE_SEEDS:
        conn.execute(
            """
            INSERT INTO language_courses (
              slug, language, title, description, level, runtime_profile_id,
              supported_exercise_types_json
            )
            SELECT
              %(slug)s, %(language)s, %(title)s, %(description)s, %(level)s,
              runtime_profiles.id, %(supported_exercise_types_json)s::jsonb
            FROM runtime_profiles
            WHERE runtime_profiles.slug = %(runtime_profile_slug)s
            ON CONFLICT (slug) DO UPDATE SET
              language = EXCLUDED.language,
              title = EXCLUDED.title,
              description = EXCLUDED.description,
              level = EXCLUDED.level,
              runtime_profile_id = EXCLUDED.runtime_profile_id,
              supported_exercise_types_json = EXCLUDED.supported_exercise_types_json,
              archived_at = NULL
            """,
            seed
            | {
                "supported_exercise_types_json": json.dumps(
                    seed["supported_exercise_types_json"],
                ),
            },
        )


def seed_learning_intents(conn: Connection[dict[str, object]]) -> None:
    for seed in LEARNING_INTENT_SEEDS:
        conn.execute(
            """
            INSERT INTO tutor_learning_intents (
              intent_key, display_name, state, policy_version
            ) VALUES (%(intent_key)s, %(display_name)s, %(state)s, %(policy_version)s)
            ON CONFLICT (intent_key) DO UPDATE SET
              display_name = EXCLUDED.display_name,
              state = EXCLUDED.state,
              policy_version = EXCLUDED.policy_version
            """,
            seed | {"policy_version": PLANNING_INTENT_POLICY_VERSION},
        )


def seed_language_course_intent_tags(conn: Connection[dict[str, object]]) -> None:
    for seed in LANGUAGE_COURSE_INTENT_TAG_SEEDS:
        row = conn.execute(
            """
            INSERT INTO language_course_intent_tags (
              course_id, intent_key, relevance_rank, is_primary, policy_version
            )
            SELECT courses.id, %(intent_key)s, %(relevance_rank)s, %(is_primary)s, %(policy_version)s
            FROM language_courses AS courses
            WHERE courses.slug = %(course_slug)s
            ON CONFLICT (course_id, intent_key) DO UPDATE SET
              relevance_rank = EXCLUDED.relevance_rank,
              is_primary = EXCLUDED.is_primary,
              policy_version = EXCLUDED.policy_version
            RETURNING course_id
            """,
            seed | {"policy_version": PLANNING_INTENT_POLICY_VERSION},
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"language course intent backfill course is missing: {seed['course_slug']}"
            )


def language_course_intent_coverage(conn: Connection[dict[str, object]]) -> dict[str, list[str]]:
    missing_courses = conn.execute(
        """
        SELECT courses.id::text AS course_id, courses.slug
        FROM language_courses AS courses
        WHERE courses.archived_at IS NULL
          AND NOT EXISTS (
            SELECT 1
            FROM language_course_intent_tags AS tags
            JOIN tutor_learning_intents AS intents
              ON intents.intent_key = tags.intent_key AND intents.state = 'active'
            WHERE tags.course_id = courses.id
          )
        ORDER BY courses.slug
        """
    ).fetchall()
    missing_intents = conn.execute(
        """
        SELECT intents.intent_key
        FROM tutor_learning_intents AS intents
        WHERE intents.state = 'active'
          AND NOT EXISTS (
            SELECT 1
            FROM language_course_intent_tags AS tags
            JOIN language_courses AS courses
              ON courses.id = tags.course_id AND courses.archived_at IS NULL
            WHERE tags.intent_key = intents.intent_key
          )
        ORDER BY intents.intent_key
        """
    ).fetchall()
    return {
        "missing_course_ids": [str(row["course_id"]) for row in missing_courses],
        "missing_course_slugs": [str(row["slug"]) for row in missing_courses],
        "missing_intent_keys": [str(row["intent_key"]) for row in missing_intents],
    }


def require_language_course_intent_coverage(conn: Connection[dict[str, object]]) -> None:
    coverage = language_course_intent_coverage(conn)
    if any(coverage.values()):
        raise RuntimeError(f"language course intent coverage is incomplete: {coverage}")
    conn.execute("SELECT assert_language_course_intent_coverage()")


def archive_language_courses(conn: Connection[dict[str, object]]) -> None:
    if not ARCHIVED_LANGUAGE_COURSE_SLUGS:
        return
    conn.execute(
        """
        UPDATE language_courses
        SET archived_at = COALESCE(archived_at, now())
        WHERE slug = ANY(%s)
          AND archived_at IS NULL
        """,
        (list(ARCHIVED_LANGUAGE_COURSE_SLUGS),),
    )


def _run_completion_baseline(
    *, candidate: bool, expected_database_oid: int,
    maintenance_confirmed: bool, storage_check: bool, upgrade: bool = False,
) -> BaselineState:
    """One caller-owned transaction, one fixed plan, no uncertain-COMMIT retry.

    Main must establish maintenance quiescence separately; neither the advisory
    lock nor this acknowledgement is a lock on all business DML.
    """
    if not maintenance_confirmed or expected_database_oid <= 0:
        raise CompletionBaselineError("COMPLETION_BASELINE_MAINTENANCE_REQUIRED")
    committing = False
    commit_acknowledged = False
    readback_started = False
    try:
        _metadata(storage_check=storage_check)
        with connect() as conn:
            try:
                changed = _apply_completion_transition(
                    conn, expected_database_oid=expected_database_oid,
                    storage_check=storage_check, upgrade=upgrade, candidate=candidate,
                )
                if not changed or candidate:
                    conn.rollback()
                    return BaselineState.COMPLETE
                committed_target = inspect_completion_target(
                    conn, storage_check=storage_check, expected_database_oid=expected_database_oid,
                )
                committing = True
                conn.commit()
                commit_acknowledged = True
                committing = False
            except Exception:
                if not committing and not commit_acknowledged:
                    conn.rollback()
                raise
        # Only an acknowledged changed install reaches this point. The writer
        # has closed; neither its transaction nor its post-DDL snapshot is reused.
        readback_started = True
        with connect() as readback:
            try:
                readback.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                actual_target = inspect_completion_target(
                    readback, storage_check=storage_check, expected_database_oid=expected_database_oid,
                )
                if (actual_target != committed_target
                        or classify_completion_baseline(readback, target=actual_target) is not BaselineState.COMPLETE):
                    raise CompletionBaselineError("COMPLETION_BASELINE_COMMITTED_READBACK_FAILED")
            finally:
                readback.rollback()
        return BaselineState.COMPLETE
    except Exception as error:
        if commit_acknowledged:
            code = ("COMPLETION_BASELINE_COMMITTED_READBACK_FAILED" if readback_started
                    else "COMPLETION_BASELINE_COMMITTED_CLEANUP_FAILED")
            raise CompletionBaselineError(code) from None
        if committing:
            raise CompletionBaselineError("COMPLETION_BASELINE_COMMIT_UNKNOWN") from None
        if isinstance(error, CompletionBaselineError):
            raise
        raise CompletionBaselineError("COMPLETION_BASELINE_INSTALL_FAILED") from None


def _apply_completion_transition(
    conn: Connection[dict[str, object]], *, expected_database_oid: int,
    storage_check: bool = False, upgrade: bool = False, candidate: bool = False,
) -> bool:
    """Private exact-plan seam; caller owns maintenance, TOP and final rollback.

    It never commits, accepts caller SQL, or installs a missing legacy BASE.
    False means an already-COMPLETE no-DDL transition.
    """
    if expected_database_oid <= 0 or conn.autocommit:
        raise CompletionBaselineError("COMPLETION_BASELINE_TRANSACTION_REQUIRED")
    metadata = _metadata(storage_check=storage_check)
    fragments = load_schema_fragments(contract=CONTRACT_ID, storage_check=storage_check)
    expected_plan = metadata.VALIDATION_FORWARD_FRAGMENT_NAMES if storage_check else metadata.RUNTIME_FORWARD_FRAGMENT_NAMES
    if tuple(fragment.name for fragment in fragments) != expected_plan:
        raise CompletionBaselineError("COMPLETION_BASELINE_PLAN_REJECTED")
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_BOOTSTRAP_ADVISORY_LOCK_KEY,))
    inspect_completion_target(conn, storage_check=storage_check, expected_database_oid=expected_database_oid)
    # This contract requires an existing purpose-specific BASE, not an empty DB.
    empty_base = conn.execute(
        "SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM unnest(%s::text[]) relation "
        "WHERE to_regclass(relation) IS NOT NULL)", (list(metadata.BASE_TABLES),),
    ).fetchone()
    if empty_base is not None:
        raise CompletionBaselineError("COMPLETION_BASELINE_EXISTING_BASE_REQUIRED")
    for relation in metadata.BASE_LOCK_RELATIONS:
        parts = relation.split(".") if isinstance(relation, str) else relation
        if len(parts) != 2:
            raise CompletionBaselineError("COMPLETION_BASELINE_METADATA_INVALID")
        conn.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(sql.Identifier(*parts)))
    # Fresh lock-internal checks: never reuse a pre-queue target/catalog snapshot.
    target = inspect_completion_target(conn, storage_check=storage_check, expected_database_oid=expected_database_oid)
    if upgrade:
        plan = _inspect_completion_upgrade_on_connection(conn, target=target)
        if not plan.fragment_names:
            return False
        fragments = tuple(fragment for fragment in fragments if fragment.name in plan.fragment_names)
        if tuple(fragment.name for fragment in fragments) != plan.fragment_names:
            raise CompletionBaselineError("COMPLETION_BASELINE_PLAN_REJECTED")
    else:
        state = classify_completion_baseline(conn, target=target)
        if state is BaselineState.COMPLETE:
            return False
        if state is not BaselineState.ABSENT:
            raise CompletionBaselineError("COMPLETION_BASELINE_PARTIAL_OR_UNKNOWN")
    if not candidate:
        # A rollback rehearsal is not installation and need not freeze a draft
        # candidate. A real install must not leave newly installed SQL editable.
        from app.db.schema.governance import SCHEMA_CANDIDATE_FACTS, SCHEMA_FROZEN_FILE_NAMES

        for fragment in fragments:
            facts = SCHEMA_CANDIDATE_FACTS.get(fragment.name)
            if fragment.name not in SCHEMA_FROZEN_FILE_NAMES and (facts is None or facts.freeze_commitment is not True):
                raise CompletionBaselineError("COMPLETION_BASELINE_INSTALL_FREEZE_REQUIRED")
    for fragment in fragments:
        conn.execute(fragment.sql)
    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
    target = inspect_completion_target(conn, storage_check=storage_check, expected_database_oid=expected_database_oid)
    if classify_completion_baseline(conn, target=target) is not BaselineState.COMPLETE:
        raise CompletionBaselineError("COMPLETION_BASELINE_POSTINSTALL_REJECTED")
    return True


def candidate_completion_baseline(
    *, expected_database_oid: int, maintenance_confirmed: bool,
    storage_check: bool = False, upgrade: bool = False,
) -> BaselineState:
    """Validate the fixed install in an outer transaction, then always rollback."""
    return _run_completion_baseline(
        candidate=True, expected_database_oid=expected_database_oid,
        maintenance_confirmed=maintenance_confirmed, storage_check=storage_check,
        upgrade=upgrade,
    )


def install_completion_baseline(
    *, expected_database_oid: int, maintenance_confirmed: bool,
    storage_check: bool = False, upgrade: bool = False,
) -> BaselineState:
    """Explicit installation COMMIT; never called from normal process startup."""
    return _run_completion_baseline(
        candidate=False, expected_database_oid=expected_database_oid,
        maintenance_confirmed=maintenance_confirmed, storage_check=storage_check,
        upgrade=upgrade,
    )


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CompletionBaselineError("COMPLETION_BASELINE_ARGUMENTS_REJECTED")


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(description="Aearn database bootstrap")
    parser.add_argument("--contract", choices=(CONTRACT_ID,))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--candidate", action="store_true")
    action.add_argument("--install", action="store_true")
    action.add_argument("--upgrade-plan", action="store_true", help="Read the finite known-predecessor upgrade plan")
    action.add_argument("--inventory", action="store_true", help="Offline migration lifecycle and selected-plan inventory")
    parser.add_argument("--upgrade", action="store_true", help="Use a finite upgrade with --candidate or --install")
    parser.add_argument("--storage-check", action="store_true")
    parser.add_argument("--database-oid", type=int)
    parser.add_argument("--maintenance-confirmed", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.inventory:
            if args.upgrade or args.database_oid is not None or args.maintenance_confirmed:
                raise CompletionBaselineError("COMPLETION_BASELINE_ACTION_REJECTED")
            if args.storage_check and args.contract is None:
                raise CompletionBaselineError("COMPLETION_BASELINE_CONTRACT_REQUIRED")
            from app.db.schema import schema_migration_inventory

            try:
                inventory = schema_migration_inventory(contract=args.contract, storage_check=args.storage_check)
            except RuntimeError:
                raise CompletionBaselineError("COMPLETION_BASELINE_INVENTORY_REJECTED") from None
            print(json.dumps(inventory))
            return 0
        # CLI selection still observes the ordinary config/.env precedence.
        # Parsing --help and importing this module never load credentials.
        import_module("app.core.config")
        selected = selected_contract()
        if args.contract is not None and selected not in (None, args.contract):
            raise CompletionBaselineError("COMPLETION_BASELINE_CONTRACT_REJECTED")
        if args.contract is None and selected is None:
            raise CompletionBaselineError("COMPLETION_BASELINE_CONTRACT_REQUIRED")
        if args.upgrade and not (args.candidate or args.install):
            raise CompletionBaselineError("COMPLETION_BASELINE_ACTION_REJECTED")
        if args.storage_check and not (args.check or args.candidate or args.install or args.upgrade_plan):
            raise CompletionBaselineError("COMPLETION_BASELINE_STORAGE_ACTION_REQUIRED")
        if args.candidate or args.install:
            if args.database_oid is None:
                raise CompletionBaselineError("COMPLETION_BASELINE_TARGET_OID_REQUIRED")
            runner = candidate_completion_baseline if args.candidate else install_completion_baseline
            state = runner(
                expected_database_oid=args.database_oid,
                maintenance_confirmed=args.maintenance_confirmed, storage_check=args.storage_check,
                upgrade=args.upgrade,
            )
            print("COMPLETION_BASELINE_CANDIDATE_ROLLED_BACK" if args.candidate else "COMPLETION_BASELINE_INSTALL_COMPLETE")
            return 0 if state is BaselineState.COMPLETE else 1
        if args.database_oid is not None or args.maintenance_confirmed:
            raise CompletionBaselineError("COMPLETION_BASELINE_ACTION_REJECTED")
        if args.upgrade_plan:
            plan = inspect_completion_upgrade(storage_check=args.storage_check)
            print(json.dumps({"contract": CONTRACT_ID, "predecessor": plan.predecessor,
                              "purpose": plan.target.purpose, "fragments": plan.fragment_names}))
            return 0
        check_completion_baseline(storage_check=args.storage_check)
        print("COMPLETION_BASELINE_CHECK_COMPLETE")
        return 0
    except CompletionBaselineError as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
