"""C18 selected SQL boundary contracts only; never connects to PostgreSQL."""
from hashlib import sha256
from pathlib import Path
import re

import pytest


SCHEMA = Path(__file__).resolve().parents[2] / "app/db/schema"
FRAGMENT = "562_learning_item_private_generation_persistence_phase_v1.sql"


def _sql() -> str:
    return (SCHEMA / FRAGMENT).read_text(encoding="utf-8")


def _definitions(source: str | None = None) -> dict[str, tuple[str, bool, str]]:
    return {
        signature: (result, is_set == "true", body)
        for signature, _header, result, is_set, body in re.findall(
            r" \('([^']+)', '([^']+)', '([^']+)', (true|false), \$src\$([\s\S]*?)\$src\$\)",
            _sql() if source is None else source,
        )
    }


def _body(name: str) -> str:
    return next(body for signature, (_, _, body) in _definitions().items() if signature.split("(")[0] == name)


def _patch(tag: str) -> tuple[str, str, str]:
    source = _sql().split(f"DO $patch{tag}562$", 1)[1].split(f"$patch{tag}562$;", 1)[0]
    old = source.split(f"old_body constant text := $old{tag}562$", 1)[1].split(f"$old{tag}562$;", 1)[0]
    new = source.split(f"new_body constant text := $new{tag}562$", 1)[1].split(f"$new{tag}562$;", 1)[0]
    tail = source.split(f"$new{tag}562$;", 1)[1]
    return old, new, tail


def test_exact_eight_functions_five_wire_receivers_and_three_triggers() -> None:
    journal = "public.tutor_item_supply_private_persistent_pack_journal"
    expected = {
        "private_generation_persistence_phase_ready()": ("boolean", False),
        "private_generation_persistence_phase_first_claim(uuid,uuid,uuid,uuid)": ("public.tutor_item_supply_private_job_controls", True),
        "private_generation_persistence_phase_bound(uuid,uuid)": (journal, True),
        "private_generation_persistence_phase_complete(uuid,uuid,uuid)": ("uuid", False),
        "private_generation_persistence_phase_committed(uuid,uuid)": (journal, True),
        "private_generation_persistence_phase_completed_data(uuid)": (journal, True),
        "enforce_private_generation_persistence_phase_insert()": ("trigger", False),
        "enforce_private_generation_persistence_phase_atomic()": ("trigger", False),
    }
    assert {name: value[:2] for name, value in _definitions().items()} == expected
    installer = _sql().split(" ) AS definitions(signature,header,result_type,is_set,body) LOOP", 1)[1].split("$install562$;", 1)[0]
    assert installer.count("'CREATE TRIGGER ") == 1
    assert installer.count("'CREATE CONSTRAINT TRIGGER ") == 2
    assert "a000_private_generation_persistence_phase_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal" in installer
    assert "private_generation_persistence_phase_atomic AFTER INSERT ON public.tutor_item_supply_private_persistent_pack_journal DEFERRABLE INITIALLY DEFERRED" in installer
    assert "private_generation_persistence_artifact_atomic AFTER INSERT ON public.tutor_item_supply_private_generation_artifacts DEFERRABLE INITIALLY DEFERRED" in installer
    assert not re.search(r"(?im)^\s*(CREATE TABLE|ALTER TABLE|DROP |DELETE FROM|COMMIT|GRANT )", _sql())


def test_replay_checks_full_metadata_setof_arity_owner_acl_and_constraint_shape() -> None:
    source = _sql()
    # IF reads THEN as its delimiter unless the nested CASE operand is parenthesized.
    assert "IS DISTINCT FROM CASE WHEN" not in source
    assert len(re.findall(
        r"prorows IS DISTINCT FROM \(CASE WHEN (?:spec\.is_set|false) THEN 1000::real ELSE 0::real END\)",
        source,
    )) == 5
    for text in (
        "prior.prosrc IS DISTINCT FROM spec.body", "prior.proretset IS DISTINCT FROM spec.is_set",
        "prior.prorows IS DISTINCT FROM (CASE WHEN spec.is_set THEN 1000::real ELSE 0::real END)",
        "prior.proargnames IS DISTINCT FROM expected_names", "prior.pronargs IS DISTINCT FROM COALESCE(cardinality(expected_names),0)",
        "prior.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole", "prior.proacl IS DISTINCT FROM ARRAY[",
        "prior.proconfig IS DISTINCT FROM ARRAY[", "prior.proargdefaults IS NOT NULL", "prior.prosqlbody IS NOT NULL",
        "prior.tgdeferrable IS DISTINCT FROM tr.deferred", "prior.tginitdeferred IS DISTINCT FROM tr.deferred",
        "k.contype='t'", "k.condeferrable AND k.condeferred AND k.convalidated",
    ):
        assert text in source
    for tag in ("art", "term", "ready"):
        _, _, tail = _patch(tag)
        assert "IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;" in tail
        assert "IF actual.prosrc IS DISTINCT FROM old_body THEN RAISE" in tail
        assert "definition:=pg_get_functiondef(actual.oid);" in tail
        assert "EXECUTE replace(definition,old_body,new_body);" in tail
        assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in tail


def test_old_bodies_match_frozen_560_final_definitions_exactly() -> None:
    source = (SCHEMA / "560_learning_item_private_generation_durability_v1.sql").read_text(encoding="utf-8")
    definitions = {signature: body for signature, _, _, body in re.findall(
        r" \('([^']+)',\s*'([^']+)',\s*'([^']+)', \$src\$([\s\S]*?)\$src\$\)", source,
    )}
    assert _patch("art")[0] == definitions["enforce_private_generation_durability_artifact()"]
    assert _patch("ready")[0] == definitions["private_generation_durability_ready()"]
    assert _patch("term")[0] == source.split("new_body constant text := $newterm560$", 1)[1].split("$newterm560$;", 1)[0]


def test_artifact_patch_preserves_every_ordinary_line_and_exact_initial_scope() -> None:
    old, new, _ = _patch("art")
    bridge = new.split(" -- C18: this one separately committed output", 1)[1].split(" p_preparation:=", 1)[0]
    stripped = new.replace(" -- C18: this one separately committed output" + bridge, "")
    stripped = stripped.replace("\n bridge_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; origin_id uuid; origin_count bigint;", "")
    assert stripped == old
    assert new.index("Inherited/idempotent staging") < new.index("-- C18:")
    assert new.index("phase.payload_json->'ref'->'parent_version_id'='null'::jsonb") < new.index("-- C18:")
    for text in ("private_generation_persistence_phase_bound(bridge_row.id,origin_id)", "origin_count<>1",
                 "NEW.lease_state_version<>2", "NEW.artifact_key IS DISTINCT FROM 'generation.d55f63a980434d748a1c0862660aed30'",
                 "'request' IS DISTINCT FROM NEW.request_json", "'source' IS DISTINCT FROM NEW.source_json",
                 "'receipt' IS DISTINCT FROM NEW.receipt_json"):
        assert text in bridge
    assert new.index("private_generation_durability_attempt('d55f63a9") < new.index("SELECT count(*)")


def test_terminal_patch_keeps_true_original_quality_suffix_and_prior_ancestry() -> None:
    old, new, _ = _patch("term")
    marker = "   -- Durable terminal quality is DATA, not a restored live work capability."
    assert new.split(marker, 1)[1] == old.split(marker, 1)[1]
    bridge = new.split("  -- C18 completion", 1)[1].split("  IF bridge_head OR (EXISTS", 1)[0]
    assert "original_binding_id'=binding_row.id::text" in bridge
    assert "original_started_id'=started_row.id::text" in bridge
    assert "IF NOT known_ancestor" in bridge
    assert "bound_top_xid'=pg_current_xact_id()::text" in bridge
    assert "completed_top_xid'=pg_current_xact_id()::text" in bridge
    assert "private_generation_persistence_phase_completed_data(bridge_row.id)" in bridge
    assert "private_generation_persistence_phase_bound(" not in new
    assert "private_generation_persistence_phase_committed(" not in new
    assert "current_pack_source_origin_current(" not in new
    assert "IF NOT bridge_head THEN" in new
    assert "RETURN 'published'" in new and "RETURN 'review_failed'" in new and "RETURN 'artifact'" in new
    assert "assert_private_native_review_stage(peer)" in new


def test_readiness_changes_only_two_old_body_pins_and_covers_seven_new_bodies() -> None:
    old, new, _ = _patch("ready")
    for tag in ("art", "term"):
        old_body, new_body, _ = _patch(tag)
        assert new.count(new_body) == 1
        new = new.replace(new_body, old_body)
    assert new == old
    ready = _body("private_generation_persistence_phase_ready")
    for signature, (_, _, body) in _definitions().items():
        if signature == "private_generation_persistence_phase_ready()":
            continue
        assert sha256(body.encode()).hexdigest() in ready
    assert "private_generation_durability_ready() IS DISTINCT FROM true" in ready
    assert "'private_generation_persistence_phase_ready()','private_generation_persistence_phase_ready()','boolean',false,NULL::text" in ready
    assert "private_generation_persistence_phase_ready(" not in _patch("ready")[1]


def test_new_records_use_only_server_full_top_markers_not_xmin_or_savepoints() -> None:
    for _, _, body in _definitions().values():
        for forbidden in ("xmin", "4294967296", "txid_current()", "pg_xact_status", "SAVEPOINT", "allow_same_top"):
            assert forbidden not in body
    trigger = _body("enforce_private_generation_persistence_phase_insert")
    assert "NEW.payload_json->'bound_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)" in trigger
    assert "complete_body->'completed_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)" in trigger
    assert "'bound_top_xid',pg_current_xact_id()::text" in _body("private_generation_persistence_phase_first_claim")
    assert "'completed_top_xid',pg_current_xact_id()::text" in _body("private_generation_persistence_phase_complete")


def test_same_top_denials_precede_missing_phase_and_current_writer_checks() -> None:
    bound = _body("private_generation_persistence_phase_bound")
    committed = _body("private_generation_persistence_phase_committed")
    assert bound.index("562 prior-TOP persistence binding required") < bound.index("private_generation_durability_attempt(")
    assert bound.index("562 prior-TOP persistence binding required") < bound.index("mapping_row.id IS NULL")
    assert committed.index("562 prior-TOP persistence binding required") < committed.index("562 prior-TOP persistence completion required")
    assert committed.index("562 prior-TOP persistence completion required") < committed.index("private_generation_persistence_phase_completed_data(")
    assert committed.index("private_generation_persistence_phase_completed_data(") < committed.index("private_generation_persistence_phase_bound(")


def test_first_claim_only_designated_unused_job_with_canonical_lock_order() -> None:
    body = _body("private_generation_persistence_phase_first_claim")
    anchors = [body.index(s) for s in (
        "private_native_epoch(", "JOIN tutor_track_active_plans", "private_generation_durability_attempt(",
        "IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal", "WHERE c.job_id=p_job FOR UPDATE",
        "private_native_source_current(", "stamp:=clock_timestamp();", "UPDATE tutor_item_supply_private_job_controls",
    )]
    assert anchors == sorted(anchors)
    for text in ("((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true", "job_row.parent_job_id IS NOT NULL", "ctrl.state IS DISTINCT FROM 'queued'",
                 "ctrl.state_version<>1", "ctrl.lease_generation<>0", "ctrl.attempt_count<>0", "ctrl.lease_owner IS NOT NULL",
                 "chr(31)", "WHERE c.id=ctrl.id AND c.state='queued'", "lease_generation=1,attempt_count=1",
                 "private_generation_persistence_phase_ready() IS DISTINCT FROM true"):
        assert text in body
    assert "SKIP LOCKED" not in body and "ORDER BY c.priority" not in body
    assert body.count("UPDATE tutor_item_supply_private_job_controls") == 1
    assert "INSERT INTO tutor_item_supply_private_development_model_accounting_jobs" not in body
    assert "'private_status','private.persistence.phase." in body
    assert "INSERT INTO tutor_item_supply_private_persistent_pack_journal" in body


def test_phase_order_compares_frozen_db_clock_not_job_top_start_timestamp() -> None:
    predicate = "((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true"
    bodies = {signature: body for signature, (_, _, body) in _definitions().items()}
    assert {name: body.count(predicate) for name, body in bodies.items() if predicate in body} == {
        "private_generation_persistence_phase_completed_data(uuid)": 1,
        "private_generation_persistence_phase_bound(uuid,uuid)": 1,
        "private_generation_persistence_phase_first_claim(uuid,uuid,uuid,uuid)": 1,
        "private_generation_persistence_phase_complete(uuid,uuid,uuid)": 1,
        "enforce_private_generation_persistence_phase_insert()": 2,
        "enforce_private_generation_persistence_phase_atomic()": 1,
    }
    # NULL/earlier frozen times fail closed; no job creation timestamp or xmin substitute.
    assert all("job_row.created_at" not in body for body in bodies.values())
    assert all("xmin" not in body for body in bodies.values())
    assert "lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'" in bodies[
        "private_generation_persistence_phase_bound(uuid,uuid)"
    ]


def test_binding_time_is_guard_stamped_after_validation_not_control_updated_at() -> None:
    trigger = _body("enforce_private_generation_persistence_phase_insert")
    binding = trigger.split(" IF protocol='private_generation_persistence_phase_v1' THEN", 1)[1].split(
        " ELSE\n  complete_body:=NEW.payload_json;", 1
    )[0]
    assert "IS DISTINCT FROM ctrl.updated_at" not in trigger
    assert "((body->>'bound_at')::timestamptz>=(lease_json->'profile'->>'bound_at')::timestamptz) IS DISTINCT FROM true" in binding
    assert "(body->>'bound_at')::timestamptz IS NULL OR (body->>'bound_at')::timestamptz>clock_timestamp()" in binding
    assert "origin_row.payload_json->>'issued_at')::timestamptz>(body->>'bound_at')::timestamptz" in binding
    tail = binding.split("  stamp:=clock_timestamp();", 1)[1]
    assert "(body->>'bound_at')::timestamptz>stamp" in tail
    assert "stamp>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,source_end,batch_row.valid_until," in tail
    assert "(body->>'valid_until')::timestamptz,(origin_row.payload_json->>'valid_until')::timestamptz)" in tail
    write = "NEW.payload_json:=jsonb_set(NEW.payload_json,'{bound_at}',to_jsonb(stamp));"
    assert tail.index("562 current persistence writer and source required") < tail.index(write)
    assert "'bound_at',stamp" in _body("private_generation_persistence_phase_first_claim")
    assert "NEW.payload_json->'bound_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)" in binding


def test_binding_payload_domains_and_immutable_original_request_are_exact() -> None:
    body = _body("enforce_private_generation_persistence_phase_insert")
    expected = {
        "schema_version", "output_id", "preparation_id", "output_hash", "original_binding_id", "original_started_id", "original_consumed_id",
        "original_settlement_id", "generation_job_id", "generation_request_hash", "generation_profile_hash", "ref", "writer_job_id", "batch_id",
        "lease", "source_origin_id", "bound_top_xid", "bound_at", "valid_until",
    }
    keys = re.search(r"snapshot_keys\(body,ARRAY\[([^]]+)\]\)", body)
    assert keys is not None and set(re.findall(r"'([^']+)'", keys[1])) == expected
    assert "body->>'output_hash' IS DISTINCT FROM output_row.payload_hash" in body
    assert "body->>'generation_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')" in body
    assert "body->'generation_profile_hash' IS DISTINCT FROM ctx->'request'->'profile'->'profile_hash'" in body
    assert "lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'" in body
    assert "ctx->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb" in body
    assert "snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy'])" in body


def test_deferred_a_requires_real_accounting_phase_before_any_work() -> None:
    body = _body("enforce_private_generation_persistence_phase_atomic")
    a = body.split(" IF is_binding THEN", 1)[1].split(" ELSE\n  IF body->>'bound_top_xid'", 1)[0]
    for text in ("mapping_row.id IS NULL OR phase_row.id IS NULL", "mapping_row.lease_state_version<>2",
                 "mapping_row.parent_job_id IS NOT NULL", "phase_row.payload_json IS DISTINCT FROM jsonb_build_object",
                 "562 complete accounting and slot phase required before commit", "ctrl.state_version<>2",
                 "tutor_item_supply_private_reservations", "tutor_item_supply_private_checkpoints", "tutor_item_supply_private_generation_artifacts",
                 "tutor_item_supply_private_candidates", "assert_private_native_phase(", "private_native_generation_goal_current("):
        assert text in a
    assert a.index("private_native_generation_goal_current(") < a.index("stamp:=clock_timestamp();")


def test_deferred_b_cannot_commit_direct_artifact_without_same_top_completion() -> None:
    body = _body("enforce_private_generation_persistence_phase_atomic")
    assert "ELSIF TG_TABLE_NAME='tutor_item_supply_private_generation_artifacts'" in body
    assert "j.payload_json->>'writer_job_id'=NEW.job_id::text" in body
    assert "completion_row.payload_json->>'artifact_id' IS DISTINCT FROM event_id::text" in body
    assert "completion_row.payload_json->>'completed_top_xid' IS DISTINCT FROM pg_current_xact_id()::text" in body
    assert "562 same-TOP artifact checkpoint completion required before commit" in body
    assert "private_generation_persistence_phase_completed_data(binding_row.id)" in body
    for text in ("ctrl.state_version<>3", "tutor_item_supply_private_pipeline_receipts", "k.id<>checkpoint.id", "'private_native_auxiliary_v1','private_native_stage_v1'"):
        assert text in body


def test_historical_completion_never_requires_fresh_old_or_new_writer() -> None:
    body = _body("private_generation_persistence_phase_completed_data")
    for forbidden in ("private_generation_persistence_phase_bound(", "current_pack_source_origin_current(", "private_native_source_current(",
                      "private_development_accounting_batch_current(", "private_pack_slot_current(", "ctrl.state IS DISTINCT FROM 'leased'",
                      "stamp>=", "clock_timestamp()>=(body->>'valid_until')"):
        assert forbidden not in body
    for text in ("private_generation_output_committed(", "d->'settlement'->>'usage_state' IS DISTINCT FROM 'known'",
                 "artifact.request_json IS DISTINCT FROM ctx->'request'", "artifact.source_json IS DISTINCT FROM capture->'result'->'source'",
                 "artifact.receipt_json IS DISTINCT FROM capture->'result'->'receipt'", "'generating',1,'completed',1,artifact.artifact_hash,'candidate_staged'",
                 "v.version=1", "complete_body->>'completed_top_xid'=body->>'bound_top_xid'", "origin_row.payload_json->>'capture_txid' IS DISTINCT FROM complete_body->>'completed_top_xid'"):
        assert text in body


def test_current_bound_refreshes_only_assertion_version_and_uses_new_top_source() -> None:
    body = _body("private_generation_persistence_phase_bound")
    assert "jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version))" in body
    assert "origin_id:=p_origin;" in body
    assert "ctrl.lease_expires_at IS DISTINCT FROM (lease_json->>'expires_at')::timestamptz" in body
    assert "ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz" in body
    assert body.index("private_native_generation_goal_current(") < body.index("stamp:=clock_timestamp();")
    claim = _body("private_generation_persistence_phase_first_claim")
    deadline = claim.split("deadline:=LEAST(", 1)[1].split(";", 1)[0]
    assert "source_end" in deadline and "origin_row" not in deadline
    assert "interval '3600 seconds'" in deadline


@pytest.mark.parametrize("receiver,message", [
    ("private_generation_persistence_phase_first_claim", "562 fixed durable output required"),
    ("private_generation_persistence_phase_first_claim", "562 exact unclaimed persistence job required"),
    ("private_generation_persistence_phase_first_claim", "562 persistence phase already bound"),
    ("private_generation_persistence_phase_bound", "562 prior-TOP persistence binding required"),
    ("private_generation_persistence_phase_committed", "562 prior-TOP persistence completion required"),
    ("enforce_private_generation_persistence_phase_atomic", "562 complete accounting and slot phase required before commit"),
    ("enforce_private_generation_persistence_phase_atomic", "562 same-TOP artifact checkpoint completion required before commit"),
])
def test_exact_probe_errors_are_check_violation(receiver: str, message: str) -> None:
    assert f"RAISE check_violation USING MESSAGE='{message}';" in _body(receiver)
