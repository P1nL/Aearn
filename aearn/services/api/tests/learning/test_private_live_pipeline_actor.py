"""C15 offline actor/lock/fence contracts; not PG or lost-output recovery proof."""
from pathlib import Path
import re

from app.db.schema import SCHEMA_FRAGMENT_NAMES


SCHEMA = Path(__file__).resolve().parents[2] / 'app/db/schema'
FRAGMENT = '559_learning_item_private_live_pipeline_actor_v1.sql'
TARGET = 'public.enforce_item_supply_pipeline_artifact()'


def _parts() -> tuple[str, str, str]:
    sql = (SCHEMA / FRAGMENT).read_text(encoding='utf-8')
    old = sql.split('old_body constant text := $old559$', 1)[1].split('$old559$;', 1)[0]
    new = sql.split('new_body constant text := $new559$', 1)[1].split('$new559$;', 1)[0]
    return old, new, sql.split('$new559$;', 1)[1]


def _between(body: str, start: str, end: str) -> str:
    return body[body.index(start):body.index(end, body.index(start))]


def test_559_exact_final524_body_and_only_reviewed_native_branch_additions() -> None:
    source = (SCHEMA / '524_learning_item_private_native_pack_authority_v1.sql').read_text(encoding='utf-8')
    match = re.search(
        r'CREATE OR REPLACE FUNCTION enforce_item_supply_pipeline_artifact\(\) RETURNS trigger\n'
        r'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS \$\$'
        r'(.*?)\$\$;', source, re.S,
    )
    assert match is not None
    old, new, _ = _parts()
    assert old == match.group(1)
    restored = new
    declarations = _between(restored, '\n  native_live boolean:=false;', '\nBEGIN')
    restored = restored.replace(declarations, '', 1)
    actor = _between(restored, '    -- Recognition only.', '\n  END IF;\n  SELECT * INTO control')
    restored = restored.replace(actor, "    RAISE check_violation USING MESSAGE='synthetic sandbox actor required';", 1)
    generation = _between(restored, '    IF native_live AND item_supply_internal.private_native_generation_goal_current(to_jsonb(NEW))', '  ELSE\n    SELECT source_hash,mode,candidate_id,version_id')
    restored = restored.replace(generation, '', 1)
    receipt = _between(restored, '    IF native_live THEN\n      -- Full JSON', '    expected_schema:=CASE')
    restored = restored.replace(receipt, '', 1)
    final = _between(restored, '  IF native_live THEN\n    -- Full goal/source locks can wait.', '  RETURN NEW;')
    restored = restored.replace(final, '', 1)
    assert restored == old


def test_559_new_actor_recognition_is_exact_and_is_not_authority() -> None:
    old, new, _ = _parts()
    original_gate = "IF current_database()='aearn_b1d_sandbox_20261001' AND NOT EXISTS(\n    SELECT 1 FROM users WHERE id=NEW.user_id AND display_name=('sandbox.p6.'||NEW.user_id::text) AND deleted_at IS NULL) THEN"
    assert original_gate in old and original_gate in new
    recognition = _between(new, '    -- Recognition only.', '    -- Canonical locks BEFORE')
    for required in (
        "NEW.mode='live'", "NEW.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid", 'NEW.epoch=1',
        "NEW.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'::uuid",
        "TG_TABLE_NAME IN('tutor_item_supply_private_generation_artifacts','tutor_item_supply_private_pipeline_receipts')",
        'FROM users WHERE id=NEW.user_id AND deleted_at IS NULL',
        "ph.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid",
        'ph.user_id=NEW.user_id AND ph.epoch=NEW.epoch AND ph.scope_id=NEW.scope_id',
        "ph.operation_key='private.phase.'||NEW.job_id::text",
        "ph.payload_json->>'schema_version'='private_native_phase_v1'",
        "ph.payload_json->>'job_id'=NEW.job_id::text",
        "ph.payload_json->'ref'->>'mapping_receipt_id'='d8e34e01-3514-41a3-9bbd-55ee3e627134'",
        "IF native_phase.id IS NULL THEN\n      RAISE check_violation USING MESSAGE='synthetic sandbox actor required';",
    ):
        assert required in recognition
    assert 'FOR SHARE' not in recognition and 'FOR UPDATE' not in recognition
    assert 'private_native_generation_goal_current' not in recognition
    assert 'RETURN NEW' not in recognition
    assert '80f8f576-166e-48ea-aaa7-f78809da38b8' not in new
    assert new.count('RETURN NEW;') == 1
    assert not re.search(r'NEW\.[a-z_]+\s*:=', new)


def test_559_canonical_namespace_scope_plan_task_root_locks_precede_control() -> None:
    _, new, _ = _parts()
    epoch = new.index('PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch)')
    scope = new.index('PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p')
    task = new.index('SELECT task.* INTO native_task')
    root = new.index('PERFORM 1 FROM tutor_item_supply_private_budget_roots root JOIN tutor_item_supply_private_jobs job')
    control = new.index('SELECT * INTO control FROM tutor_item_supply_private_job_controls')
    assert epoch < scope < task < root < control
    assert 'p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id' in new[scope:task]
    assert 's.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch' in new[scope:task]
    assert 'FOR SHARE OF s,p;' in new[scope:task]
    assert 'FOR SHARE;' in new[task:root]
    assert 'FOR SHARE OF root,job;' in new[root:control]
    assert 'private_native_generation_goal_current' not in new[:control]
    assert 'private_pack_slot_current' not in new[:control]
    epoch_source = (SCHEMA / '495_learning_item_native_exposure.sql').read_text(encoding='utf-8')
    original_lock = _between(epoch_source, 'FUNCTION item_supply_internal.native_exposure_lock(', 'END $$;')
    assert original_lock.index('FROM users') < original_lock.index('FROM tutor_item_supply_user_epochs')
    assert original_lock.count('FOR SHARE;') == 2


def test_559_phase_and_all_five_declared_slots_share_the_original_root_only() -> None:
    _, new, _ = _parts()
    phase = _between(new, '    SELECT task.* INTO native_task', '  SELECT * INTO control')
    for required in (
        "native_task.payload_json->>'enhancement' IS DISTINCT FROM 'prefer_private'",
        "native_task.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'",
        "native_ref->>'pack_task_id',native_ref->>'user_id',native_ref->>'epoch',native_ref->>'scope_id'",
        "native_phase.payload_json->'lease'->>'visibility'",
        "native_ref->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'",
        "jsonb_array_length(native_task.payload_json->'slots') IS DISTINCT FROM 5",
        "member->>'slot_id'=native_ref->>'slot_id' AND member->>'logical_item_id'=native_ref->>'business_item_id'",
        "IN('practice-1','practice-2')", "IN('assessment-1','assessment-2')", "='guided-remediation'",
        "job.root_id=root.id AND job.user_id=root.user_id AND job.epoch=root.epoch AND job.scope_id=root.scope_id",
        'job.id=NEW.job_id',
    ):
        assert required in phase
    # No one-slot or one-job allowlist replaces the original declared-slot membership.
    assert 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c' not in phase


def test_559_generation_and_receipt_each_require_full_current_goal_source() -> None:
    _, new, _ = _parts()
    control = new.index('SELECT * INTO control FROM tutor_item_supply_private_job_controls')
    generation = new.index('IF native_live AND item_supply_internal.private_native_generation_goal_current(to_jsonb(NEW)) IS DISTINCT FROM true')
    receipt = new.index('IF native_live THEN\n      -- Full JSON')
    assert control < generation < receipt
    assert new.index("MESSAGE='pipeline source identity mismatch'") < generation
    actual_generation = _between(new, '    IF native_live THEN\n      -- Full JSON', '    expected_schema:=CASE')
    for required in (
        'SELECT to_jsonb(generation) INTO native_generation FROM tutor_item_supply_private_generation_artifacts generation',
        'generation.id=NEW.generation_artifact_id', 'generation.user_id=NEW.user_id', 'generation.epoch=NEW.epoch',
        'generation.scope_id=NEW.scope_id', 'generation.job_id=NEW.job_id', 'generation.version_id=NEW.version_id',
        'generation.content_hash=NEW.content_hash', 'generation.mode=NEW.mode',
        'native_generation IS NULL OR item_supply_internal.private_native_generation_goal_current(native_generation) IS DISTINCT FROM true',
    ):
        assert required in actual_generation
    assert 'to_jsonb(NEW)' not in actual_generation
    assert 'NEW.payload_json' not in actual_generation


def test_559_source_wait_cannot_reuse_pre_wait_phase_or_control_time() -> None:
    _, new, _ = _parts()
    final = _between(new, '  IF native_live THEN\n    -- Full goal/source locks can wait.', '  RETURN NEW;')
    assert new.index(final) > new.index('private_native_generation_goal_current(native_generation)')
    assert new.index(final) > new.index("MESSAGE='pipeline receipt identity mismatch'")
    slot = final.index('private_pack_slot_current(native_phase.pack_task_id')
    control = final.index('SELECT * INTO control FROM tutor_item_supply_private_job_controls')
    clock = final.index('native_stamp:=clock_timestamp();')
    assert slot < control < clock
    for required in (
        "(native_ref->>'business_item_id')::uuid,(native_ref->>'root_id')::uuid",
        'NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id) IS DISTINCT FROM true',
        'control.lease_generation IS DISTINCT FROM NEW.lease_generation',
        'control.state_version IS DISTINCT FROM NEW.lease_state_version',
        'control.lease_expires_at<=native_stamp OR control.parent_deadline<=native_stamp',
        "(native_phase.payload_json->>'valid_until')::timestamptz<=native_stamp",
        "MESSAGE='559 postwait native generation/state-version or deadline stale'",
    ):
        assert required in final
    assert new.count('native_stamp:=') == 1
    assert 'now()' not in new


def test_559_single_target_exact_replay_and_full_nonbody_metadata_preservation() -> None:
    _, _, installer = _parts()
    replay = installer.index('IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;')
    replacement = installer.index('EXECUTE replace(definition,old_body,new_body);')
    for guard in (
        "actual.pronamespace IS DISTINCT FROM 'public'::regnamespace",
        "actual.proname IS DISTINCT FROM 'enforce_item_supply_pipeline_artifact'",
        "actual.lanname IS DISTINCT FROM 'plpgsql'", "actual.prokind<>'f'",
        'actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof',
        "actual.provolatile<>'v' OR actual.proparallel<>'u'",
        "actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype",
        "actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector OR actual.proargnames IS NOT NULL",
        'actual.proallargtypes IS NOT NULL', 'actual.proargmodes IS NOT NULL', 'actual.provariadic<>0',
        'actual.pronargdefaults<>0', 'actual.proargdefaults IS NOT NULL', 'actual.probin IS NOT NULL',
        'actual.prosqlbody IS NOT NULL', 'actual.protrftypes IS NOT NULL',
        'actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0',
        "actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole",
        "actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]",
        "actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']",
    ):
        assert installer.index(guard) < replay
    assert installer.count(f"to_regprocedure('{TARGET}')") == 1
    assert installer.count('EXECUTE ') == 1
    assert replay < installer.index('IF actual.prosrc IS DISTINCT FROM old_body') < replacement
    assert installer.index("length(definition)-length(replace(definition,old_body,''))<>length(old_body)") < replacement
    assert "WHERE p.oid=actual.oid" in installer[replacement:]
    assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in installer[replacement:]
    assert 'verified.prosrc IS DISTINCT FROM new_body' in installer[replacement:]
    assert not re.search(r'(?im)^\s*(?:UPDATE|DELETE|INSERT|COMMIT|GRANT|REVOKE|ALTER|DROP|CREATE)\b', installer)


def test_559_manifest_and_original_two_private_trigger_bindings_stay_narrow() -> None:
    index = SCHEMA_FRAGMENT_NAMES.index('558_learning_item_private_author_continuation_v1.sql')
    assert SCHEMA_FRAGMENT_NAMES[index+1] == FRAGMENT
    assert SCHEMA_FRAGMENT_NAMES.count(FRAGMENT) == 1
    sql = (SCHEMA / FRAGMENT).read_text(encoding='utf-8')
    assert 'CREATE TRIGGER' not in sql and 'DROP TRIGGER' not in sql
    assert 'enforce_item_supply_shared_pipeline_artifact' not in sql
    source = (SCHEMA / '460_learning_item_supply_pipeline.sql').read_text(encoding='utf-8')
    assert "ARRAY['tutor_item_supply_private_generation_artifacts','tutor_item_supply_private_pipeline_receipts'] LOOP" in source
    assert 'CREATE TRIGGER supply_stage_authority BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_pipeline_artifact()' in source
    old, new, _ = _parts()
    fixture = "IF NEW.mode='synthetic' AND current_database() NOT IN ('aearn_b1b_fixture_20260930','aearn_b1d_sandbox_20261001') THEN"
    assert fixture in old and fixture in new
    assert 'UPDATE users' not in new
    assert 'private_initial_author_continuation_' not in new
