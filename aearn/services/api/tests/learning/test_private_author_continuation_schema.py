"""C14 SQL shape/exact delta checks only; no PostgreSQL or provider acceptance."""
import ast
from pathlib import Path
import re

from app.db.schema import SCHEMA_FRAGMENT_NAMES


SCHEMA = Path(__file__).resolve().parents[2] / 'app/db/schema'
FRAGMENT = '558_learning_item_private_author_continuation_v1.sql'
PREFIX = 'p7.private.initial-author.continuation.20261016'
FIRST_FAILURE = 'df0a6e8c-287a-4814-98f1-5deeb59347a3'


def _sql() -> str:
    return (SCHEMA / FRAGMENT).read_text(encoding='utf-8')


def _definitions(source: str) -> dict[str, str]:
    return dict((signature, body) for signature, _, _, body in re.findall(
        r" \('([^']+)',\s*'([^']+)',\s*'([^']+)', \$src\$([\s\S]*?)\$src\$\)", source,
    ))


def _body(name: str) -> str:
    return next(body for signature, body in _definitions(_sql()).items() if signature.split('(')[0] == name)


def _aux_parts() -> tuple[str, str, str]:
    sql = _sql()
    old = sql.split('old_body constant text := $oldaux558$', 1)[1].split('$oldaux558$;', 1)[0]
    new = sql.split('new_body constant text := $newaux558$', 1)[1].split('$newaux558$;', 1)[0]
    return old, new, sql.split('$newaux558$;', 1)[1]


def test_558_manifest_is_one_append_after_557() -> None:
    index = SCHEMA_FRAGMENT_NAMES.index('557_learning_item_native_consumer_public_contract.sql')
    assert SCHEMA_FRAGMENT_NAMES[index+1] == FRAGMENT
    assert SCHEMA_FRAGMENT_NAMES.count(FRAGMENT) == 1


def test_558_ten_signatures_and_two_triggers_match_live_caller_abi() -> None:
    service = SCHEMA.parent.parent / 'services/learning/item_supply/private_enhancement_service.py'
    tree = ast.parse(service.read_text(encoding='utf-8'))
    receiver = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_continuation_receivers')
    assigned = next(node for node in receiver.body if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == 'signatures' for target in node.targets))
    signatures = ast.literal_eval(assigned.value)
    definitions = _definitions(_sql())
    assert len(definitions) == 10
    assert set(definitions) == set(signatures)
    installer = _sql().split(' ) AS definitions(signature,header,result_type,body) LOOP', 1)[1].split('$install558$;', 1)[0]
    assert installer.count("'CREATE TRIGGER ") == 2
    assert "'CREATE CONSTRAINT TRIGGER " not in installer
    for name in ('private_initial_author_continuation_insert', 'private_initial_author_continuation_control'):
        assert f'CREATE TRIGGER {name} ' in installer


def test_558_sole_old_body_delta_is_complete_continuation_auxiliary_dispatch() -> None:
    original = _definitions((SCHEMA / '555_learning_item_private_initial_author_recovery_v1.sql').read_text(encoding='utf-8'))
    old, new, _ = _aux_parts()
    assert old == original['enforce_private_initial_author_recovery_auxiliary()']
    # Remove ONLY the explicit early dispatch: the entire 555 body is unchanged.
    start = new.index(' -- Only real continuation binding/candidate rows enter the new full receiver.\n')
    end = new.index(" IF NEW.payload_json->>'schema_version'='private_initial_author_recovery_binding_v1' THEN", start)
    dispatch = new[start:end]
    assert new[:start] + new[end:] == old
    assert "WHERE journal.id=NEW.id AND journal.pack_task_id=NEW.pack_task_id" in dispatch
    assert "journal.payload_json->>'candidate_id'=NEW.id::text" in dispatch
    assert "journal.payload_json->>'preparation_id'=NEW.id::text" in dispatch
    assert dispatch.count('private_initial_author_continuation_auxiliary(binding_row.id) IS DISTINCT FROM true') == 2
    assert 'IF binding_row.id IS NOT NULL THEN' in dispatch
    assert 'RETURN NEW;' in dispatch
    assert 'initial_author_recovery_bound' not in dispatch


def test_558_old_auxiliary_patch_preserves_every_nonbody_attribute_before_replay() -> None:
    _, _, patch = _aux_parts()
    replay = patch.index('IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;')
    replacement = patch.index('EXECUTE replace(definition,old_body,new_body);')
    for guard in (
        "actual.proname IS DISTINCT FROM 'enforce_private_initial_author_recovery_auxiliary'",
        "actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype",
        "actual.lanname IS DISTINCT FROM 'plpgsql'", "actual.prokind<>'f'",
        'actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof',
        "actual.provolatile<>'v' OR actual.proparallel<>'u'", 'actual.pronargs<>0',
        "actual.proargtypes IS DISTINCT FROM ''::oidvector", 'actual.proargnames IS NOT NULL',
        'actual.proallargtypes IS NOT NULL', 'actual.proargmodes IS NOT NULL', 'actual.provariadic<>0',
        'actual.pronargdefaults<>0', 'actual.proargdefaults IS NOT NULL', 'actual.probin IS NOT NULL',
        'actual.prosqlbody IS NOT NULL', 'actual.protrftypes IS NOT NULL',
        'actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0',
        "actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole",
        "actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]",
        "actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']",
    ):
        assert patch.index(guard) < replay
    assert replay < patch.index('IF actual.prosrc IS DISTINCT FROM old_body') < replacement
    assert patch.index("length(definition)-length(replace(definition,old_body,''))<>length(old_body)") < replacement
    assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in patch[replacement:]
    assert 'verified.prosrc IS DISTINCT FROM new_body' in patch[replacement:]
    assert patch.count('EXECUTE ') == 1


def test_558_historical_failure_and_predecessor_never_require_old_current_permission() -> None:
    failure = _body('private_initial_author_continuation_failure_committed')
    predecessor = _body('private_initial_author_continuation_predecessor')
    approval = _body('private_initial_author_continuation_approval')
    for historical in (failure, predecessor, approval):
        assert 'private_initial_author_continuation_bound(' not in historical
        assert 'private_initial_author_recovery_source(' not in historical
        assert 'private_development_accounting_batch_current(' not in historical
        assert 'lease_expires_at' not in historical
    assert f"IF p_receipt='{FIRST_FAILURE}' THEN" in predecessor
    assert 'private_initial_author_failure_committed(p_receipt,p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM true' in predecessor
    assert 'private_initial_author_continuation_failure_committed(p_receipt,p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM true' in predecessor
    assert 'FOR UPDATE;' in predecessor
    assert "claim.payload_json->>'approval_id'=approval_row.id::text" in failure
    assert "aux.payload_json->'request'->'request'=binding_row.payload_json->'request'" in failure
    for name in ('consumed', 'started', 'claim', 'aux', 'settlement'):
        assert f'{name}.xmin::text::bigint<>(txid_current()%4294967296)' in failure
    assert 'settlement.reservation_id=reservation.id AND settlement.sequence=1' in failure
    assert "settlement.settlement_key='generation.'||replace(binding_row.payload_json->>'candidate_id','-','')" in failure
    assert 'tutor_item_supply_private_generation_artifacts' in failure and ".author.result'" in failure


def test_558_deterministic_keys_closed_schemas_and_original_fixed_scope() -> None:
    insert = _body('enforce_private_initial_author_continuation_insert')
    approval = _body('private_initial_author_continuation_approval')
    for field in ('authorization_key', 'predecessor_failure_id', 'old_started_id', 'old_job_id', 'old_candidate_id',
                  'slot_id', 'business_item_id', 'root_id', 'mapping_receipt_id', 'candidate_key', 'storage_version'):
        assert f"'{field}'" in approval
    assert f"approval_row.operation_key IS DISTINCT FROM '{PREFIX}.'||replace(body->>'predecessor_failure_id','-','')||'.approval'" in approval
    assert f"attempt_key:='{PREFIX}.'||replace(predecessor_row.id::text,'-','');" in insert
    assert "NEW.operation_key IS DISTINCT FROM attempt_key||'.'||suffix" in insert
    for kind in ('approval', 'claim', 'binding', 'consumed', 'failure'):
        assert f'private_initial_author_continuation_{kind}_v1' in insert
    assert insert.count('snapshot_keys(body,ARRAY[') == 6
    assert "body->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb" in insert
    assert "body->'ref'->>'pack_task_id' IS DISTINCT FROM NEW.pack_task_id::text" in insert
    assert "body->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'" in insert


def test_558_new_attempt_requires_fresh_preparation_prior_top_and_unique_dispatch() -> None:
    bound = _body('private_initial_author_continuation_bound')
    claim = _body('private_initial_author_continuation_first_claim')
    consume = _body('private_initial_author_continuation_consume')
    insert = _body('enforce_private_initial_author_continuation_insert')
    assert 'private_initial_author_recovery_source(p_origin)' in bound
    assert 'private_development_accounting_batch_current(batch_row)' in bound
    assert 'private_pack_auxiliary_committed(binding_row.pack_task_id,aux_row.id) IS DISTINCT FROM true' in bound
    assert "MESSAGE='558 prior-TOP committed original preparation required'" in bound
    assert 'clock_timestamp()' in bound and 'postwait current bound expired' in bound
    assert 'lease_generation=1,attempt_count=1' in claim
    assert "'private.initial.author.continuation.'||replace(p_approval::text,'-','')" in claim
    assert 'private_initial_author_continuation_bound(p_binding,p_origin,true)' in consume
    assert "MESSAGE='558 once-only committed original author dispatch required'" in consume
    for suffix in ('consumed', 'failure', 'author.result'):
        assert f"attempt_key||'.{suffix}'" in consume
    assert 'started_row.id IS NULL OR EXISTS' in consume
    assert 'started' in consume and 'xmin::text::bigint<>(txid_current()%4294967296)' in consume
    for receiver in (claim, consume, insert):
        assert 'initial artifact already exists, use original quality/revision' in receiver
        assert "artifact.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51'" in receiver


def test_558_terminal_resolves_only_the_known_chain_by_real_committed_head_artifact() -> None:
    terminal = _body('private_initial_author_continuation_terminal')
    assert "requested.id='5ad70ab7-0441-456b-ae5e-156755a80911'" in terminal
    assert "requested.id::text=failure_row.payload_json->>'started_id'" in terminal
    assert 'known_ancestor:=known_ancestor OR requested.id=started_row.id' in terminal
    assert 'known_ancestor THEN RETURN' in terminal
    assert "attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(failure_row.id::text,'-','')" in terminal
    assert "artifact.request_json=binding_row.payload_json->'request'" in terminal
    assert 'version.version=1' in terminal and "artifact.mode='live'" in terminal
    assert 'settlement.sequence=1' in terminal
    for name in ('done', 'artifact', 'consumed', 'settlement'):
        assert f'{name}.xmin::text::bigint<>(txid_current()%4294967296)' in terminal
    assert not re.search(r'ORDER BY\s+(?:\w+\.)?(?:created_at|id)\b', terminal)
    assert "IF NOT known_ancestor THEN RETURN NULL; END IF;" in terminal
    assert 'private_initial_author_continuation_bound(' not in terminal
    assert 'private_initial_author_recovery_source(' not in terminal
    assert 'lease_expires_at' not in terminal


def test_558_exact_replay_metadata_and_immutable_control_no_ddl_or_history_broadening() -> None:
    sql = _sql()
    installer = sql.split(' ) AS definitions(signature,header,result_type,body) LOOP', 1)[1].split('$install558$;', 1)[0]
    for guard in ('prior.prosrc IS DISTINCT FROM spec.body', 'prior.prosecdef IS DISTINCT FROM true',
                  'prior.proacl IS DISTINCT FROM', 'prior.proargnames IS DISTINCT FROM expected_names',
                  'prior.proallargtypes IS NOT NULL', 'prior.proargmodes IS NOT NULL',
                  'prior.probin IS NOT NULL', 'prior.prosqlbody IS NOT NULL', 'prior.protrftypes IS NOT NULL',
                  'prior.prorows<>0', 'prior.prosupport<>0', 'prior.prolang<>',
                  'prior.tgargs', 'prior.tgparentid', 'prior.tgconstraint', 'prior.tgoldtable', 'prior.tgnewtable'):
        assert guard in installer
    control = _body('enforce_private_initial_author_continuation_control')
    assert 'NEW.lease_generation<>1 OR NEW.attempt_count<>1' in control
    assert 'NEW.lease_expires_at>NEW.parent_deadline' in control
    assert 'cannot be reclaimed/reprofiled/extended' in control
    assert not re.search(r'(?im)^\s*(CREATE TABLE|ALTER TABLE|DROP |COMMIT|DELETE FROM)\b', sql)
    assert 'TO PUBLIC' not in sql
    assert 'private_initial_author_recovery_anchor' not in _definitions(sql)


def test_558_review_failed_requires_committed_bound_full_review_not_a_veto_boolean() -> None:
    terminal = _body('private_initial_author_continuation_terminal')
    assert "review.payload_json->>'artifact_id'=head_artifact.id::text" in terminal
    assert "review.payload_json->'ref'=binding_row.payload_json->'ref'" in terminal
    assert "review.payload_json->'spec'->'public_template'=head_artifact.request_json->'public_template'" in terminal
    assert "validation.payload_json->>'state'='machine_verified'" in terminal
    assert "blind.payload_json=review.payload_json->'bundle'->'blind_solve'" in terminal
    assert "review_done.payload_json->>'receipt_id'=review.id::text" in terminal
    for name in ('review', 'validation', 'blind', 'review_done'):
        assert f'{name}.xmin::text::bigint<>(txid_current()%4294967296)' in terminal
    assert 'PERFORM item_supply_internal.assert_private_native_review_stage(peer)' in terminal
    assert "THEN RETURN 'review_failed'; END IF;" in terminal
    assert "report->>'verdict'<>'approved'" in terminal
    assert "finding->>'blocking'='true'" in terminal
    assert "finding->>'severity' IN('major','critical')" in terminal
    assert 'private_enhancement_review_veto_v1' not in terminal
    # This reused original receiver is historical identity/settlement verification,
    # not a fresh source/lease assertion after the original review has completed.
    source = (SCHEMA / '524_learning_item_private_native_pack_authority_v1.sql').read_text(encoding='utf-8')
    stage = source.split('FUNCTION item_supply_internal.assert_private_native_review_stage(', 1)[1].split('END $$;', 1)[0]
    assert 'r.requests<>7' in stage and "settlement_key='private.native.review.'" in stage
    assert 'private_native_source_current' not in stage and 'clock_timestamp()' not in stage


def test_558_published_requires_real_admission_publication_version_and_materialization() -> None:
    terminal = _body('private_initial_author_continuation_terminal')
    for required in (
        "quality.kind='admission'", "quality.payload_json->>'generation_artifact_id'=head_artifact.id::text",
        "quality.payload_json->>'review_receipt_id'=peer.id::text",
        "quality.payload_json->'bundle'=peer.payload_json->'bundle'",
        "quality.payload_json->'request'=head_artifact.request_json",
        "quality.payload_json->'source'=head_artifact.source_json",
        "admitted_validation.payload_json=quality.payload_json->'validation'",
        "admitted_blind.payload_json=peer.payload_json->'bundle'->'blind_solve'",
        "publication.state='published'", "publication.payload_json->>'quality_hash'=quality.payload_hash",
        'version.public_json=head_artifact.source_json', 'version.private_json=head_artifact.source_json',
        "exercise.source_kind='registered_author'", "rubric.rubric_hash=publication.payload_json->>'rubric_hash'",
        'successor.state_version>publication.state_version', "THEN RETURN 'published'; END IF;",
    ):
        assert required in terminal
    for name in ('quality', 'publication', 'admitted_validation', 'admitted_blind'):
        assert f'{name}.xmin::text::bigint<>(txid_current()%4294967296)' in terminal
    assert terminal.index("THEN RETURN 'published'") < terminal.index("THEN RETURN 'review_failed'") < terminal.index("RETURN 'artifact'")
