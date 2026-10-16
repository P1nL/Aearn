"""C19 exact selected-prosrc deltas; offline only, no database or provider."""
from pathlib import Path
import re

import pytest


SCHEMA = Path(__file__).resolve().parents[2] / "app/db/schema"
FRAGMENT = "563_learning_item_private_native_handle_identity_v1.sql"
TARGETS = {
    "quality": "item_supply_internal.enforce_private_native_quality_insert()",
    "pub": "item_supply_internal.enforce_private_native_publication_insert()",
    "current": "item_supply_internal.private_native_publication_current(uuid,uuid,bigint)",
    "term": "item_supply_internal.private_initial_author_continuation_terminal(uuid)",
    "ready": "item_supply_internal.private_generation_durability_ready()",
}


def _sql() -> str:
    return (SCHEMA / FRAGMENT).read_text(encoding="utf-8")


def _patch(tag: str) -> tuple[str, str, str]:
    block = _sql().split(f"DO $patch{tag}563$", 1)[1].split(f"$patch{tag}563$;", 1)[0]
    old = block.split(f"old_body constant text := $old{tag}563$", 1)[1].split(f"$old{tag}563$;", 1)[0]
    new = block.split(f"new_body constant text := $new{tag}563$", 1)[1].split(f"$new{tag}563$;", 1)[0]
    tail = block.split(f"$new{tag}563$;", 1)[1]
    return old, new, tail


def _old524(name: str) -> str:
    source = (SCHEMA / "524_learning_item_private_native_pack_authority_v1.sql").read_text(encoding="utf-8")
    tail = source.split(f"CREATE OR REPLACE FUNCTION item_supply_internal.{name}(", 1)[1]
    return tail.split("AS $$", 1)[1].split("$$;", 1)[0]


def _final562(tag: str) -> str:
    source = (SCHEMA / "562_learning_item_private_generation_persistence_phase_v1.sql").read_text(encoding="utf-8")
    return source.split(f"new_body constant text := $new{tag}562$", 1)[1].split(f"$new{tag}562$;", 1)[0]


def test_only_five_selected_existing_function_patches_no_new_objects_or_writes() -> None:
    assert re.findall(r"(?m)^DO \$patch([a-z]+)563\$", _sql()) == list(TARGETS)
    tails = "\n".join(_patch(tag)[2] for tag in TARGETS)
    assert re.findall(r"to_regprocedure\('([^']+)'\)", tails) == list(TARGETS.values())
    assert not re.search(r"(?im)^\s*(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|GRANT|REVOKE|COMMIT)\b", tails)
    assert tails.count("EXECUTE replace(definition,old_body,new_body);") == 5
    assert "private_generation_persistence_phase_ready" not in tails
    assert "IS DISTINCT FROM CASE WHEN" not in tails


@pytest.mark.parametrize("tag", TARGETS)
def test_old_bodies_match_verified_frozen_candidates(tag: str) -> None:
    old, _, _ = _patch(tag)
    if tag in {"term", "ready"}:
        assert old == _final562(tag)
    else:
        name = TARGETS[tag].split(".", 1)[1].split("(", 1)[0]
        assert old == _old524(name)
    assert "\r" not in old  # Main's catalog is LF; the earlier standalone dump used CRLF.


@pytest.mark.parametrize("tag", TARGETS)
def test_metadata_before_replay_and_exact_unique_body_only_replacement(tag: str) -> None:
    _, _, tail = _patch(tag)
    for fragment in (
        "current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'",
        "current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'",
        "current_setting('transaction_read_only') IS DISTINCT FROM 'off'",
        "actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace",
        "actual.prokind<>'f'", "actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')",
        "actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof",
        "actual.provolatile<>'v' OR actual.proparallel<>'u'", "actual.proargtypes IS DISTINCT FROM",
        "actual.proargnames IS DISTINCT FROM", "actual.proallargtypes IS NOT NULL",
        "actual.proargmodes IS NOT NULL OR actual.provariadic<>0", "actual.pronargdefaults<>0",
        "actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL",
        "actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL",
        "actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0",
        "actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole",
        "actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]",
        "actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']",
    ):
        assert fragment in tail
    metadata = tail.index(f"563 original {tag} receiver identity/attributes changed")
    replay = tail.index("IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;")
    old_check = tail.index("IF actual.prosrc IS DISTINCT FROM old_body")
    execute = tail.index("EXECUTE replace(definition,old_body,new_body);")
    assert metadata < replay < old_check < execute
    assert "length(definition)-length(replace(definition,old_body,''))<>length(old_body)" in tail
    assert "WHERE p.oid=actual.oid;" in tail
    assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in tail
    assert "verified.prosrc IS DISTINCT FROM new_body" in tail


def test_exact_return_and_argument_metadata() -> None:
    for tag in ("quality", "pub"):
        tail = _patch(tag)[2]
        assert "actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype" in tail
        assert "actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector" in tail
        assert "actual.proargnames IS DISTINCT FROM NULL::text[]" in tail
    current = _patch("current")[2]
    assert "actual.prorettype IS DISTINCT FROM 'pg_catalog.jsonb'::regtype" in current
    assert "actual.pronargs<>3" in current
    assert "ARRAY['v','u','e']::text[]" in current
    assert "'pg_catalog.int8'::regtype::oid::text" in current
    terminal = _patch("term")[2]
    assert "actual.prorettype IS DISTINCT FROM 'pg_catalog.text'::regtype" in terminal
    assert "actual.pronargs<>1" in terminal and "ARRAY['p_started']::text[]" in terminal
    assert "actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype" in _patch("ready")[2]


def test_quality_delta_is_actual_version_candidate_identity_not_storage_handle_regex() -> None:
    old, new, _ = _patch("quality")
    original = "v.handle IS DISTINCT FROM 'lip:v2:'||NEW.version_id::text"
    corrected = "a.version_id IS DISTINCT FROM v.id OR a.candidate_id IS DISTINCT FROM v.candidate_id"
    assert old.count(original) == 1
    assert new == old.replace(original, corrected)
    assert "v.handle" not in new
    for unchanged in (
        "WHERE g.version_id=NEW.version_id AND g.user_id=NEW.user_id AND g.epoch=NEW.epoch",
        "AND g.scope_id=NEW.scope_id AND j.root_id=NEW.root_id",
        "WHERE id=NEW.version_id AND user_id=NEW.user_id",
        "AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR SHARE",
        "a.mode IS DISTINCT FROM 'live'", "a.source_json->'public' IS DISTINCT FROM v.public_json",
        "a.source_json->'private' IS DISTINCT FROM v.private_json",
    ):
        assert unchanged in new
    assert new.index("524 quality current source before bank required") < new.index("SELECT * INTO v")
    assert "private_native_semantic_normal_readmission_v1" not in new
    assert "IF NEW.kind='normal' THEN PERFORM item_supply_internal.assert_private_native_normal(NEW); END IF;" in new
    assert "assert_private_native_review_stage(NEW)" in new
    assert "524 quality stale after lock wait" in new


def test_publication_two_handle_checks_use_actual_locked_version_canonical_id() -> None:
    old, new, _ = _patch("pub")
    expected = old
    for field in ("p->>'item_handle'", "NEW.content_json->>'item_handle'"):
        fragment = field + " IS DISTINCT FROM v.handle"
        assert old.count(fragment) == 1
        expected = expected.replace(fragment, field + " IS DISTINCT FROM ('lip:v2:'||v.id::text)")
    assert new == expected
    assert "v.handle" not in new
    for unchanged in (
        "WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR UPDATE",
        "p->>'version_id' IS DISTINCT FROM NEW.version_id::text",
        "NEW.content_json->>'version_id' IS DISTINCT FROM NEW.version_id::text",
        "p->>'quality_hash' IS DISTINCT FROM q.payload_hash", "actual original private materialization required",
        "v.public_json IS DISTINCT FROM q.payload_json->'source'->'public'",
        "v.private_json IS DISTINCT FROM q.payload_json->'source'->'private'",
        "private_pack_slot_current(", "524 private publication stale after wait",
        "524 immutable private publication terminal CAS required",
    ):
        assert unchanged in new


def test_publication_current_single_delta_preserves_retirement_source_and_materialization() -> None:
    old, new, _ = _patch("current")
    original = "version.handle IS DISTINCT FROM pub.payload_json->>'item_handle'"
    replacement = "('lip:v2:'||version.id::text) IS DISTINCT FROM pub.payload_json->>'item_handle'"
    assert old.count(original) == 1 and new == old.replace(original, replacement)
    assert "WHERE id=v AND user_id=u AND epoch=e FOR SHARE" in new
    assert "latest.state IS DISTINCT FROM 'published' OR latest.id IS DISTINCT FROM pub.id" in new
    assert "524 actual original exercise/rubric missing" in new
    assert "524 source stale after bank wait" in new
    assert "private_native_mapping_current(" in new
    assert "private_generation_persistence_phase_bound(" not in new


def test_terminal_two_handle_deltas_leave_ancestry_completed_data_and_full_quality_intact() -> None:
    old, new, _ = _patch("term")
    expected = old
    for field in ("publication.payload_json", "publication.content_json"):
        original = field + "->>'item_handle'=version.handle"
        assert old.count(original) == 1
        expected = expected.replace(original, field + "->>'item_handle'=('lip:v2:'||version.id::text)")
    assert new == expected
    for unchanged in (
        "private_generation_persistence_phase_completed_data(bridge_row.id)",
        "bound_top_xid'=pg_current_xact_id()::text", "completed_top_xid'=pg_current_xact_id()::text",
        "IF NOT known_ancestor", "assert_private_native_review_stage(peer)",
        "jsonb_array_length(review.payload_json->'bundle'->'reports')=6",
        "version.id=publication.version_id AND version.user_id=publication.user_id AND version.epoch=publication.epoch",
        "version.public_json=head_artifact.source_json->'public' AND version.private_json=head_artifact.source_json->'private'",
        "tutor_exercise_private_rubrics", "RETURN 'published'", "RETURN 'review_failed'", "RETURN 'artifact'",
    ):
        assert unchanged in new
    assert "private_generation_persistence_phase_bound(" not in new
    assert "private_generation_persistence_phase_committed(" not in new


def test_readiness_changes_only_exact_terminal_expected_body_no_new_readiness_layer() -> None:
    old, new, _ = _patch("ready")
    old_terminal, new_terminal, _ = _patch("term")
    assert old.count(old_terminal) == 1
    assert new == old.replace(old_terminal, new_terminal)
    assert new.count(new_terminal) == 1
    assert "private_generation_persistence_phase_ready(" not in new
    frozen = (SCHEMA / "562_learning_item_private_generation_persistence_phase_v1.sql").read_text(encoding="utf-8")
    phase_ready = frozen.split("('private_generation_persistence_phase_ready()', 'private_generation_persistence_phase_ready()', 'boolean', false, $src$", 1)[1].split("$src$)", 1)[0]
    assert "private_generation_durability_ready() IS DISTINCT FROM true" in phase_ready
    assert old not in phase_ready and new not in phase_ready


def test_raw_storage_handle_stays_an_independent_opaque_locator() -> None:
    storage = (SCHEMA / "440_learning_item_supply_sandbox.sql").read_text(encoding="utf-8")
    version_table = storage.split("CREATE TABLE IF NOT EXISTS tutor_item_supply_private_versions (", 1)[1].split(");", 1)[0]
    assert "id uuid PRIMARY KEY DEFAULT gen_random_uuid()" in version_table
    assert "handle text NOT NULL UNIQUE DEFAULT ('lip:v2:'||gen_random_uuid()::text)" in version_table
    # No special-case acceptance of the observed raw locator; native checks derive only real version.id.
    for tag in ("quality", "pub", "current", "term"):
        _, new, _ = _patch(tag)
        assert "b012d828-03e0-4da9-9aaf-3009a070390e" not in new
        assert "LIKE 'lip:v2:%'" not in new
