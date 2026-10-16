"""C16 offline SQL contracts. No database, model, or old-output recovery proof."""
from pathlib import Path
import re


SCHEMA = Path(__file__).resolve().parents[2] / 'app/db/schema'
FRAGMENT = '560_learning_item_private_generation_durability_v1.sql'


def _sql() -> str:
    return (SCHEMA / FRAGMENT).read_text(encoding='utf-8')


def _definitions(source: str) -> dict[str, str]:
    return {signature: body for signature, _, _, body in re.findall(
        r" \('([^']+)',\s*'([^']+)',\s*'([^']+)', \$src\$([\s\S]*?)\$src\$\)", source,
    )}


def _body(name: str) -> str:
    return next(body for signature, body in _definitions(_sql()).items() if signature.split('(')[0] == name)


def _patch(tag: str) -> tuple[str, str, str]:
    patch = _sql().split(f'DO $patch{tag}560$', 1)[1].split(f'$patch{tag}560$;', 1)[0]
    old = patch.split(f'old_body constant text := $old{tag}560$', 1)[1].split(f'$old{tag}560$;', 1)[0]
    new = patch.split(f'new_body constant text := $new{tag}560$', 1)[1].split(f'$new{tag}560$;', 1)[0]
    return old, new, patch.split(f'$new{tag}560$;', 1)[1]


def test_560_wire_has_only_eight_new_functions_and_two_new_triggers() -> None:
    assert set(_definitions(_sql())) == {
        'private_generation_durability_attempt(uuid)',
        'private_initial_author_persistence_gap_issue(uuid,uuid,bigint,uuid,uuid)',
        'private_initial_author_persistence_gap_committed(uuid,uuid,uuid,bigint,uuid)',
        'private_generation_output_capture(uuid,jsonb)',
        'private_generation_output_committed(uuid,jsonb)',
        'enforce_private_generation_durability_insert()',
        'enforce_private_generation_durability_artifact()',
        'private_generation_durability_ready()',
    }
    installer = _sql().split(' ) AS definitions(signature,header,result_type,body) LOOP', 1)[1].split('$install560$;', 1)[0]
    assert installer.count("'CREATE TRIGGER ") == 2
    assert 'CREATE TRIGGER private_generation_durability_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal' in installer
    assert 'CREATE TRIGGER private_generation_durability_artifact BEFORE INSERT ON public.tutor_item_supply_private_generation_artifacts' in installer
    assert not re.search(r'(?im)^\s*(?:CREATE TABLE|ALTER TABLE|DROP |DELETE FROM|UPDATE |COMMIT|GRANT )', _sql())


def test_560_capture_and_gap_share_canonical_locks_before_absence_checks() -> None:
    attempt = _body('private_generation_durability_attempt')
    order = [attempt.index(text) for text in (
        'PERFORM item_supply_internal.private_native_epoch(',
        'FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p',
        'SELECT j.* INTO task_row',
        'FROM tutor_item_supply_private_budget_roots r',
        'SELECT j.* INTO aux', 'SELECT j.* INTO approval',
        'SELECT c.* INTO ctrl', 'SELECT s.* INTO settlement', 'stamp:=clock_timestamp()',
    )]
    assert order == sorted(order)
    assert 'FOR SHARE OF s,p;' in attempt
    for name in ('private_generation_output_capture', 'private_initial_author_persistence_gap_issue', 'enforce_private_generation_durability_insert'):
        body = _body(name)
        assert body.index('private_generation_durability_attempt(') < body.index('EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts')
    for forbidden in ('private_pack_auxiliary_committed(', 'private_initial_author_continuation_bound(',
                      'private_initial_author_recovery_source(', 'private_native_source_current('):
        assert forbidden not in attempt
    assert 'ctrl.parent_deadline IS DISTINCT FROM' in attempt
    assert 'ctrl.lease_expires_at>stamp' in attempt
    assert 'ctrl.parent_deadline>stamp' not in attempt
    assert 'ctrl.parent_deadline<=stamp' not in attempt


def test_560_fixed_gap_is_known_paid_expired_no_output_not_a_generation_failure() -> None:
    attempt = _body('private_generation_durability_attempt')
    issue = _body('private_initial_author_persistence_gap_issue')
    for fixed in (
        'af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6', 'b4866afd-d59f-4aef-bec3-1b1279fbaa14',
        'eeebd057-3e04-4a61-8979-201446e20221', '80f8f576-166e-48ea-aaa7-f78809da38b8',
        '55e11576-7b38-4f04-bee5-90ff5e6df51d', '4e0ec381-f9e4-4c11-b391-cedbc2480e04',
        '2026-10-16 03:05:23.278164+08', '2026-10-16 03:45:22.951952+08',
        '8c7ae3625382be3e25a2d4980e09ee3259b03463ba63b642d76cc85847dc468f',
    ):
        assert fixed in attempt
    assert "settlement.usage_state IS DISTINCT FROM 'known'" in attempt
    assert "settlement.cost_amount IS NOT NULL" in attempt
    assert '"requests":1,"candidates":1,"input_tokens":12916,"output_tokens":2082' in attempt
    assert "MESSAGE='560 fixed C14 gap binding required'" in issue
    assert issue.index("MESSAGE='560 fixed C14 gap binding required'") < issue.index('private_generation_durability_attempt(')
    for table in ('private_generation_artifacts', 'private_checkpoints', 'private_native_quality_evidence', 'private_native_publications'):
        assert table in issue
    assert "c.stage='generating' AND c.status='completed'" in issue
    assert "'.started','.result'" in issue
    assert 'private.generation.output.eeebd0573e044a618979201446e20221' in issue
    assert 'private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6' in issue
    assert 'expired_consumed_no_durable_output' in issue
    assert 'provider_failed' not in issue and 'unspent' not in issue


def test_560_new_commit_boundaries_use_validated_full_top_xid8_not_row_xmin() -> None:
    definitions = _definitions(_sql())
    for signature, body in definitions.items():
        if signature == 'private_generation_durability_ready()':
            continue  # Its expected literals contain unchanged frozen558 historical bodies.
        for forbidden in ('xmin', 'txid_current()', '4294967296', 'pg_xact_status', 'pg_visible_in_snapshot'):
            assert forbidden not in body
    trigger = _body('enforce_private_generation_durability_insert')
    assert "body->'captured_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)" in trigger
    assert "'issued_top_xid',pg_current_xact_id()::text" in trigger
    for name, marker, message in (
        ('private_generation_output_committed', 'captured_top_xid', '560 output requires a different committed TOP'),
        ('private_initial_author_persistence_gap_committed', 'issued_top_xid', '560 technical gap requires a different committed TOP'),
    ):
        body = _body(name)
        assert f"(body->>'{marker}')::xid8::text IS DISTINCT FROM body->>'{marker}'" in body
        assert f"IF body->>'{marker}'=pg_current_xact_id()::text THEN" in body
        assert f"RAISE check_violation USING MESSAGE='{message}';" in body
        assert body.index(f"IF body->>'{marker}'=pg_current_xact_id()::text THEN") > body.index('record required')
    # A savepoint release does not change this marker: no per-savepoint/subxid escape.
    assert 'captured_top_xid' in _body('private_generation_output_capture')
    assert 'issued_top_xid' in _body('private_initial_author_persistence_gap_issue')


def test_560_complete_capture_shape_source_hash_and_actual_known_unknown_accounting() -> None:
    body = _body('enforce_private_generation_durability_insert')
    for shape in (
        "ARRAY['schema_version','context','result']",
        "ARRAY['ref','lease','scope_id','request','reservation_id','sources','attempt_bound','mode','producer_binding']",
        "ARRAY['state','source','receipt','safe_reason']",
        "ARRAY['schema_version','blueprint','public','private']",
        "ARRAY['schema_version','candidate_id','scope_hash','source_hash','content_hash','provider','sources']",
    ):
        assert shape in body
    for check in (
        "result->>'state' IS DISTINCT FROM 'staged'", "result->>'safe_reason' IS DISTINCT FROM 'staged'",
        "receipt->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(source)",
        "receipt->>'content_hash' IS DISTINCT FROM expected_content",
        "ctx->'sources' IS DISTINCT FROM d->'binding'->'payload_json'->'sources'",
        "d->'settlement'->>'receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(provider)",
        "s.value->>'binding_digest' IS DISTINCT FROM m.value->'binding'->>'binding_digest'",
        "s.value->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash",
        "d->'settlement'->>'usage_state' IS DISTINCT FROM 'unknown'",
        "d->'settlement'->'receipt_hash' IS DISTINCT FROM 'null'::jsonb",
        "d->'amounts' IS DISTINCT FROM 'null'::jsonb",
    ):
        assert check in body
    assert "'requests',(provider->>'actual_requests')::bigint,'candidates',1" in body
    assert "COALESCE(d->'amounts'" not in body
    assert not re.search(r'COALESCE\([^\n]*,\s*0\)', body[body.index(' IF known THEN'):])
    assert 'settlement.xmin' not in body


def test_560_capture_is_unique_immutable_and_c14_backfill_is_denied_twice() -> None:
    capture = _body('private_generation_output_capture')
    insert = _body('enforce_private_generation_durability_insert')
    for body in (capture, insert):
        assert 'eeebd057-3e04-4a61-8979-201446e20221' in body
        assert "MESSAGE='560 historical author output cannot be backfilled'" in body
    assert "output_key:='private.generation.output.'||replace(p_preparation::text,'-','')" in capture
    assert "existing.payload_json->'capture' IS DISTINCT FROM p_capture" in capture
    assert 'RETURN existing.id;' in capture
    assert 'ON CONFLICT' not in capture and 'UPDATE ' not in capture
    assert '560 technical gap forbids output capture' in capture
    assert '560 output/gap exclusive immutable attempt already recorded' in insert


def test_560_artifact_gate_only_new_initial_private_generation_and_exact_committed_data() -> None:
    body = _body('enforce_private_generation_durability_artifact')
    assert "NEW.mode IS DISTINCT FROM 'live'" in body
    assert "phase.payload_json->'ref'->'parent_version_id'='null'::jsonb" in body
    assert 'tutor_item_supply_private_pipeline_receipts' not in body
    assert 'a.request_json,a.source_json,a.receipt_json' in body
    assert 'NEW.request_json,NEW.source_json,NEW.receipt_json' in body
    assert body.index('Inherited/idempotent staging') < body.index('private_generation_durability_attempt(')
    assert body.index('private_generation_durability_attempt(') < body.index('SELECT j.* INTO output_row')
    assert 'private_generation_output_committed(p_preparation,output_row.payload_json' in body
    assert "'result'->'source' IS DISTINCT FROM NEW.source_json" in body
    assert "'result'->'receipt' IS DISTINCT FROM NEW.receipt_json" in body


def test_560_two_old_patches_preserve_all_old_failure_and_terminal_semantics() -> None:
    frozen = _definitions((SCHEMA / '558_learning_item_private_author_continuation_v1.sql').read_text(encoding='utf-8'))
    old_pre, new_pre, _ = _patch('pre')
    old_term, new_term, _ = _patch('term')
    assert old_pre == frozen['private_initial_author_continuation_predecessor(uuid,uuid,uuid,bigint,uuid)']
    assert old_term == frozen['private_initial_author_continuation_terminal(uuid)']
    prefix = new_pre.index(' IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_receipt')
    end = new_pre.index(' PERFORM item_supply_internal.private_initial_author_recovery_anchor', prefix)
    assert new_pre[:prefix] + new_pre[end:] == old_pre
    assert 'private_initial_author_persistence_gap_committed(p_receipt,p_task,p_user,p_epoch,p_scope)' in new_pre[prefix:end]
    restored = new_term.replace(
        "   IF known_ancestor THEN\n    IF failure_row.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' THEN RETURN 'technical_gap'; END IF;\n    RETURN 'failure';\n   ELSE RETURN NULL; END IF;",
        "   IF known_ancestor THEN RETURN 'failure'; ELSE RETURN NULL; END IF;", 1)
    start = restored.index("  IF failure_row.id IS NULL AND binding_row.id='af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid THEN")
    end = restored.index('  IF failure_row.id IS NULL THEN RETURN NULL; END IF;', start)
    restored = restored[:start] + restored[end:]
    assert restored == old_term


def test_560_readiness_checks_exact_bodies_metadata_triggers_before_io() -> None:
    ready = _body('private_generation_durability_ready')
    expected = {signature: body for signature, _, _, body in re.findall(
        r" \('([^']+)','([^']+)','([^']+)',\$expected560\$([\s\S]*?)\$expected560\$\)", ready)}
    definitions = _definitions(_sql())
    for signature, body in definitions.items():
        if signature != 'private_generation_durability_ready()':
            assert expected[signature] == body
    assert expected['private_initial_author_continuation_predecessor(uuid,uuid,uuid,bigint,uuid)'] == _patch('pre')[1]
    assert expected['private_initial_author_continuation_terminal(uuid)'] == _patch('term')[1]
    assert len(expected) == 9
    for check in ('actual.prosrc IS DISTINCT FROM spec.body', 'actual.proowner', 'actual.proacl', 'actual.proconfig',
                  'actual.proargnames', 'actual.tgtype<>7', "actual.tgenabled<>'O'", 'actual.tgdeferrable', 'actual.tgfoid'):
        assert check in ready
    # Statements in expected body literals are DATA, not readiness writes.
    executable = re.sub(r'\$expected560\$.*?\$expected560\$', "''", ready, flags=re.S)
    assert not re.search(r'(?im)^\s*(?:INSERT|UPDATE|DELETE|EXECUTE)\b', executable)


def test_560_patch_metadata_and_replay_are_checked_without_owner_or_acl_changes() -> None:
    for tag in ('pre', 'term'):
        _, _, patch = _patch(tag)
        replay = patch.index('IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;')
        replacement = patch.index('EXECUTE replace(definition,old_body,new_body);')
        for required in ('actual.proowner', 'actual.proacl', 'actual.proconfig', 'actual.prorettype', 'actual.proargnames',
                         'actual.prokind', 'actual.prolang', 'actual.proretset', 'actual.proisstrict', 'actual.prosecdef',
                         'actual.proleakproof', 'actual.provolatile', 'actual.proparallel', 'actual.proallargtypes',
                         'actual.proargmodes', 'actual.provariadic', 'actual.pronargdefaults', 'actual.proargdefaults',
                         'actual.probin', 'actual.prosqlbody', 'actual.protrftypes', 'actual.procost', 'actual.prorows', 'actual.prosupport'):
            assert patch.index(required) < replay
        assert replay < patch.index('IF actual.prosrc IS DISTINCT FROM old_body') < replacement
        assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in patch[replacement:]
        assert 'WHERE p.oid=actual.oid' in patch[replacement:]
        assert patch.count('EXECUTE ') == 1
