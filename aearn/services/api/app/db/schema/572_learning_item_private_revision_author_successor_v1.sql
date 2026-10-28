-- C26: one original-owner technical author successor. No table/new writer/cross-phase recovery.
-- Six closed internal functions, one journal trigger, one exact570 attempt stage selector patch.
-- Frozen <=571 files and all old known/UNKNOWN/once/lease rows remain untouched.
DO $install572$
DECLARE spec record;actual record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001' THEN
  RAISE check_violation USING MESSAGE='572 original isolated writable transaction required'; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_native_revision_successor_basis_v1()','private_native_revision_successor_basis_v1()','jsonb','',ARRAY[]::text[],$basis572$
DECLARE d jsonb;
BEGIN
 d:=item_supply_internal.private_native_revision_durability_attempt_v1('4391fd7f-926e-4324-bb78-4815d081ec6e');
 IF d->'aux'->>'id' IS DISTINCT FROM '4391fd7f-926e-4324-bb78-4815d081ec6e'
  OR d->'aux'->>'payload_hash' IS DISTINCT FROM 'c1cc6e77116f86fed477de49051de17473a8f4d00eee3f1e941df0742e9e0eaa'
  OR d->'phase'->>'id' IS DISTINCT FROM '20dbfa43-279f-4408-8869-747833df9a68'
  OR d->'phase'->>'payload_hash' IS DISTINCT FROM 'f0cc734e6c04564f30bea569a9038d297b2c3d60807ef5f380216ed3f75f7b39'
  OR d->'started'->>'id' IS DISTINCT FROM '598eb68f-bf11-4f95-8b27-59b066ab45b8'
  OR d->'started'->>'payload_hash' IS DISTINCT FROM 'c27f8c13fbfc16b6c7c624861e2e9aa505a52450dad926f914ee52e2ed33f196'
  OR d->'control'->>'job_id' IS DISTINCT FROM '3c02e871-a33f-4c11-82ef-8421d818ae75'
  OR d->'reservation'->>'id' IS DISTINCT FROM '1bfb2476-5732-4182-a609-f5c21cc68037'
  OR d->>'generation_candidate_id' IS DISTINCT FROM '808e2e76-bc13-4955-b8ec-7a11ffa289a1'
  OR d->'settlement'->>'id' IS DISTINCT FROM 'e6ecb97c-6099-4d5a-8e8a-047f603ef9fc'
  OR d->'settlement'->'sequence' IS DISTINCT FROM '1'::jsonb
  OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'known' OR d->'settlement'->'cost_amount' IS DISTINCT FROM 'null'::jsonb
  OR d->'settlement'->>'receipt_hash' IS DISTINCT FROM '6cd0d92487844ffcde1de5a6368ab8bf0f6bcf327ecfc5ef0c094bd9bbc59aff'
  OR d->'amounts' IS DISTINCT FROM '{"requests":1,"input_tokens":14542,"output_tokens":2197,"candidates":0,"execution_seconds":0,"fetches":0,"revision_rounds":0,"investigation_rounds":0}'::jsonb THEN
  RAISE check_violation USING MESSAGE='572 fixed known-paid unstaged predecessor required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE
   j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
   AND (j.payload_json->>'schema_version'='private_native_revision_output_v1'
    AND (j.payload_json->>'revision_preparation_id'='4391fd7f-926e-4324-bb78-4815d081ec6e'
     OR j.payload_json->>'generation_candidate_id'='808e2e76-bc13-4955-b8ec-7a11ffa289a1')))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id='3c02e871-a33f-4c11-82ef-8421d818ae75')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id='3c02e871-a33f-4c11-82ef-8421d818ae75') THEN
  RAISE check_violation USING MESSAGE='572 old author has durable output or product'; END IF;
 RETURN jsonb_build_object('schema_version','private_native_revision_successor_basis_v1','cause_code','c25_not_staged_cause_unretained',
  'pack_task_id',d->'task'->'id','user_id',d->'task'->'user_id','epoch',d->'task'->'epoch','scope_id',d->'task'->'scope_id',
  'root_id',d->'aux'->'payload_json'->'request'->'ref'->'root_id','slot_id',d->'aux'->'payload_json'->'request'->'ref'->'slot_id',
  'business_item_id',d->'aux'->'payload_json'->'request'->'ref'->'business_item_id',
  'old_preparation_id',d->'aux'->'id','old_aux_hash',d->'aux'->'payload_hash','old_phase_id',d->'phase'->'id','old_phase_hash',d->'phase'->'payload_hash',
  'old_started_id',d->'started'->'id','old_started_hash',d->'started'->'payload_hash','old_job_id',d->'control'->'job_id',
  'old_reservation_id',d->'reservation'->'id','old_generation_candidate_id',d->'generation_candidate_id',
  'old_settlement_id',d->'settlement'->'id','old_receipt_hash',d->'settlement'->'receipt_hash','old_amounts',d->'amounts');
END;
$basis572$),
 ('private_native_revision_successor_preparation_v1(uuid,uuid)','private_native_revision_successor_preparation_v1(p_grant uuid,p_preparation uuid)','jsonb','2950 2950',ARRAY['p_grant','p_preparation']::text[],$preparation572$
DECLARE basis jsonb;grant_row record;old_aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 stage public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 reservation public.tutor_item_supply_private_reservations%ROWTYPE;profile public.tutor_item_supply_parameter_profiles%ROWTYPE;
 prep jsonb;ref jsonb;lease_json jsonb;request jsonb;old_prep jsonb;subject text;subject_hash text;stage_key text;issued_top text;
BEGIN
 basis:=item_supply_internal.private_native_revision_successor_basis_v1();
 SELECT j.* INTO grant_row FROM tutor_item_supply_private_persistent_pack_journal j
  WHERE j.id=p_grant AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=((basis->>'pack_task_id')::uuid,(basis->>'user_id')::uuid,(basis->>'epoch')::integer,(basis->>'scope_id')::uuid)
  AND j.record_kind='private_status' AND j.operation_key='private.revision.successor.grant.4391fd7f926e4324bb784815d081ec6e';
 issued_top:=grant_row.payload_json->>'issued_top_xid';
 IF grant_row.id IS NULL OR jsonb_typeof(grant_row.payload_json->'issued_top_xid') IS DISTINCT FROM 'string'
  OR grant_row.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(grant_row.payload_json)
  OR (grant_row.payload_json - 'issued_top_xid'::text) IS DISTINCT FROM jsonb_build_object('schema_version','private_native_revision_successor_grant_v1','approval_scope','c26_author_successor_20261017','basis',basis) THEN
  RAISE check_violation USING MESSAGE='572 prior committed exact successor grant required'; END IF;
 BEGIN
  IF issued_top::xid8::text IS DISTINCT FROM issued_top THEN
   RAISE check_violation USING MESSAGE='572 prior committed exact successor grant required'; END IF;
 EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
  RAISE check_violation USING MESSAGE='572 prior committed exact successor grant required';
 END;
 IF issued_top IS NOT DISTINCT FROM pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='572 prior committed exact successor grant required'; END IF;
 IF p_preparation IS NULL OR p_preparation='4391fd7f-926e-4324-bb78-4815d081ec6e'::uuid THEN
  RAISE check_violation USING MESSAGE='572 new original revision preparation required'; END IF;
 SELECT j.* INTO old_aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(basis->>'old_preparation_id')::uuid;
 old_prep:=old_aux.payload_json->'request';
 SELECT j.* INTO aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_preparation
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(grant_row.pack_task_id,grant_row.user_id,grant_row.epoch,grant_row.scope_id)
  AND j.record_kind='private_attachment' AND j.operation_key='private.aux.'||p_preparation::text;
 prep:=aux.payload_json->'request';ref:=prep->'ref';lease_json:=prep->'lease';request:=prep->'request';
 IF aux.id IS NULL OR aux.intent_hash IS DISTINCT FROM grant_row.intent_hash
  OR item_supply_internal.snapshot_keys(aux.payload_json,ARRAY['schema_version','job_id','reservation_id','request','valid_until']) IS DISTINCT FROM true
  OR aux.payload_json->>'schema_version' IS DISTINCT FROM 'private_native_auxiliary_v1'
  OR item_supply_internal.snapshot_keys(prep,ARRAY['schema_version','ref','lease','investigation_id','parent_version_id','request','directive_hash']) IS DISTINCT FROM true
  OR prep->>'schema_version' IS DISTINCT FROM 'private_native_revision_phase_v1'
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR ref IS DISTINCT FROM old_prep->'ref' OR prep->'investigation_id' IS DISTINCT FROM old_prep->'investigation_id'
  OR prep->'parent_version_id' IS DISTINCT FROM old_prep->'parent_version_id' OR prep->'directive_hash' IS DISTINCT FROM old_prep->'directive_hash'
  OR request->>'candidate_id' IS NULL OR request->>'candidate_id' IN(p_preparation::text,basis->>'old_generation_candidate_id')
  OR (request - ARRAY['candidate_id','profile']::text[]) IS DISTINCT FROM ((old_prep->'request') - ARRAY['candidate_id','profile']::text[])
  OR request->'profile' IS DISTINCT FROM lease_json->'profile'
  OR aux.payload_json->>'job_id' IS DISTINCT FROM lease_json->>'job_id'
  OR lease_json->>'job_id' IS NULL OR lease_json->>'job_id'=basis->>'old_job_id'
  OR (lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch') IS DISTINCT FROM ('private',basis->>'user_id',basis->>'epoch') THEN
  RAISE check_violation USING MESSAGE='572 exact new same-item R1 revision preparation required'; END IF;
 SELECT j.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(aux.pack_task_id,aux.user_id,aux.epoch,aux.scope_id)
  AND j.record_kind='phase' AND j.operation_key='private.phase.'||(lease_json->>'job_id')
  AND j.payload_json->>'schema_version'='private_native_phase_v1' AND j.payload_json->>'job_id'=lease_json->>'job_id';
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=(lease_json->>'job_id')::uuid
  AND c.user_id=aux.user_id AND c.epoch=aux.epoch AND c.scope_id=aux.scope_id;
 SELECT p.* INTO profile FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id;
 SELECT r.* INTO reservation FROM tutor_item_supply_private_reservations r WHERE r.id=(aux.payload_json->>'reservation_id')::uuid
  AND (r.user_id,r.epoch,r.scope_id,r.job_id,r.root_id)=(aux.user_id,aux.epoch,aux.scope_id,ctrl.job_id,(ref->>'root_id')::uuid)
  AND r.reservation_key='gen.'||replace(request->>'candidate_id','-','');
 subject:='v2.c26.'||replace(p_grant::text,'-','');subject_hash:=item_supply_internal.snapshot_hash(to_jsonb(subject));
 stage_key:='private.stage.'||replace(ref->>'business_item_id','-','')||'.revision.'||subject_hash||'.started';
 SELECT j.* INTO stage FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(aux.pack_task_id,aux.user_id,aux.epoch,aux.scope_id)
  AND j.record_kind='private_status' AND j.operation_key=stage_key;
 IF phase.id IS NULL OR ctrl.id IS NULL OR profile.id IS NULL OR reservation.id IS NULL OR stage.id IS NULL
  OR phase.payload_json->'ref' IS DISTINCT FROM ref
  OR ((phase.payload_json->'lease') - 'state_version'::text) IS DISTINCT FROM (lease_json - 'state_version'::text)
  OR stage.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_stage_v1','slot_id',ref->'slot_id',
   'stage','revision','subject_hash',subject_hash,'status','started','receipt_id',NULL,'job_id',lease_json->'job_id')
  OR stage.intent_hash IS DISTINCT FROM aux.intent_hash
  OR ctrl.lease_generation IS DISTINCT FROM (lease_json->>'generation')::integer OR reservation.lease_generation IS DISTINCT FROM ctrl.lease_generation
  OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR ctrl.profile_snapshot_json->'profile' IS DISTINCT FROM lease_json->'profile'
  OR ctrl.profile_snapshot_json->'retry_policy' IS DISTINCT FROM lease_json->'retry_policy'
  OR profile.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR (aux.payload_json->>'valid_until')::timestamptz IS NULL OR (phase.payload_json->>'valid_until')::timestamptz IS NULL
  OR (lease_json->>'expires_at')::timestamptz IS NULL OR (lease_json->>'parent_deadline')::timestamptz IS NULL
  OR (aux.payload_json->>'valid_until')::timestamptz>(phase.payload_json->>'valid_until')::timestamptz
  OR GREATEST(aux.created_at,stage.created_at)>=LEAST((aux.payload_json->>'valid_until')::timestamptz,
   (lease_json->>'expires_at')::timestamptz,(lease_json->>'parent_deadline')::timestamptz) THEN
  RAISE check_violation USING MESSAGE='572 exact lawful historical revision producer and dedicated stage required'; END IF;
 RETURN jsonb_build_object('schema_version','private_native_revision_successor_binding_v1','grant_id',p_grant,'grant_hash',grant_row.payload_hash,
  'preparation_id',p_preparation,'phase_id',phase.id,'phase_hash',phase.payload_hash,'job_id',lease_json->'job_id',
  'reservation_id',reservation.id,'generation_candidate_id',request->'candidate_id','request_hash',item_supply_internal.snapshot_hash(request),
  'ref',ref,'lease',lease_json,'stage_key',stage_key,'stage_id',stage.id,'stage_hash',stage.payload_hash,'subject_hash',subject_hash,
  'valid_until',aux.payload_json->'valid_until');
END;
$preparation572$),
 ('private_native_revision_successor_grant_v1()','private_native_revision_successor_grant_v1()','uuid','',ARRAY[]::text[],$grant572$
DECLARE basis jsonb;body jsonb;identity uuid:=gen_random_uuid();existing public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;intent text;issued_top text;
BEGIN
 basis:=item_supply_internal.private_native_revision_successor_basis_v1();
 SELECT j.intent_hash INTO intent FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(basis->>'pack_task_id')::uuid AND j.record_kind='task';
 body:=jsonb_build_object('schema_version','private_native_revision_successor_grant_v1','approval_scope','c26_author_successor_20261017','basis',basis);
 SELECT j.* INTO existing FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=((basis->>'pack_task_id')::uuid,(basis->>'user_id')::uuid,(basis->>'epoch')::integer,(basis->>'scope_id')::uuid)
  AND j.record_kind='private_status' AND j.operation_key='private.revision.successor.grant.4391fd7f926e4324bb784815d081ec6e';
 IF existing.id IS NOT NULL THEN
  issued_top:=existing.payload_json->>'issued_top_xid';
  IF jsonb_typeof(existing.payload_json->'issued_top_xid') IS DISTINCT FROM 'string'
   OR existing.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(existing.payload_json)
   OR (existing.payload_json - 'issued_top_xid'::text) IS DISTINCT FROM body OR existing.intent_hash IS DISTINCT FROM intent THEN
   RAISE check_violation USING MESSAGE='572 immutable successor grant conflict'; END IF;
 BEGIN
  IF issued_top::xid8::text IS DISTINCT FROM issued_top THEN
   RAISE check_violation USING MESSAGE='572 immutable successor grant conflict'; END IF;
 EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
  RAISE check_violation USING MESSAGE='572 immutable successor grant conflict';
 END;
  RETURN existing.id; -- DATA only; retain the original marker/time, never refresh.
 END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,(basis->>'pack_task_id')::uuid,(basis->>'user_id')::uuid,(basis->>'epoch')::integer,(basis->>'scope_id')::uuid,'private_status',
  'private.revision.successor.grant.4391fd7f926e4324bb784815d081ec6e',intent,body||jsonb_build_object('issued_top_xid',pg_current_xact_id()::text));
 RETURN identity;
END;
$grant572$),
 ('private_native_revision_successor_bind_v1(uuid,uuid)','private_native_revision_successor_bind_v1(p_grant uuid,p_preparation uuid)','uuid','2950 2950',ARRAY['p_grant','p_preparation']::text[],$bind572$
DECLARE aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 existing public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;expected jsonb;identity uuid:=gen_random_uuid();bank_candidate uuid;head integer;stamp timestamptz;issued_top text;
BEGIN
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 SELECT j.* INTO aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_preparation
  AND j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
  AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='private_attachment';
 SELECT j.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(aux.pack_task_id,aux.user_id,aux.epoch,aux.scope_id)
  AND j.record_kind='phase' AND j.payload_json->>'schema_version'='private_native_phase_v1'
  AND j.payload_json->>'job_id'=aux.payload_json->>'job_id';
 IF aux.id IS NULL OR phase.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',aux.payload_json->'request'->'ref','request',aux.payload_json->'request'->'request')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='572 current original child SOURCE required before binding'; END IF;
 PERFORM item_supply_internal.assert_private_native_phase(phase.payload_json,aux.user_id,aux.epoch,aux.scope_id,aux.pack_task_id);
 SELECT v.candidate_id INTO bank_candidate FROM tutor_item_supply_private_versions v WHERE v.id='a8e9af49-a9ae-4464-aea9-41239ab3a43d'
  AND v.user_id=aux.user_id AND v.epoch=aux.epoch AND v.scope_id=aux.scope_id FOR SHARE;
 SELECT max(v.version) INTO head FROM tutor_item_supply_private_versions v WHERE v.candidate_id=bank_candidate
  AND v.user_id=aux.user_id AND v.epoch=aux.epoch AND v.scope_id=aux.scope_id;
 IF bank_candidate IS NULL OR head IS DISTINCT FROM 1
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p WHERE p.pack_task_id=aux.pack_task_id
   AND p.user_id=aux.user_id AND p.epoch=aux.epoch AND p.slot_id='50df2afa-158c-586e-83c7-60bb99ea4307') THEN
  RAISE check_violation USING MESSAGE='572 unpublished original v1 head required at binding'; END IF;
 expected:=item_supply_internal.private_native_revision_successor_preparation_v1(p_grant,p_preparation);
 SELECT j.* INTO existing FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(aux.pack_task_id,aux.user_id,aux.epoch,aux.scope_id)
  AND j.record_kind='private_status' AND (j.operation_key='private.revision.successor.binding.'||replace(p_grant::text,'-','')
   OR (j.payload_json->>'schema_version'='private_native_revision_successor_binding_v1' AND j.payload_json->>'preparation_id'=p_preparation::text));
 IF existing.id IS NOT NULL THEN
  issued_top:=existing.payload_json->>'issued_top_xid';
  IF jsonb_typeof(existing.payload_json->'issued_top_xid') IS DISTINCT FROM 'string'
   OR existing.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(existing.payload_json)
   OR (existing.payload_json - 'issued_top_xid'::text) IS DISTINCT FROM expected THEN
   RAISE check_violation USING MESSAGE='572 successor grant already bound to another preparation'; END IF;
 BEGIN
  IF issued_top::xid8::text IS DISTINCT FROM issued_top THEN
   RAISE check_violation USING MESSAGE='572 successor grant already bound to another preparation'; END IF;
 EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
  RAISE check_violation USING MESSAGE='572 successor grant already bound to another preparation';
 END;
 END IF;
 -- A basis/control wait must not retain the earlier head or clock decision.
 SELECT max(v.version) INTO head FROM tutor_item_supply_private_versions v WHERE v.candidate_id=bank_candidate
  AND v.user_id=aux.user_id AND v.epoch=aux.epoch AND v.scope_id=aux.scope_id;
 stamp:=clock_timestamp();
 IF head IS DISTINCT FROM 1 OR stamp>=LEAST((expected->>'valid_until')::timestamptz,(phase.payload_json->>'valid_until')::timestamptz,
  (expected->'lease'->>'expires_at')::timestamptz,(expected->'lease'->>'parent_deadline')::timestamptz,
  (expected->'lease'->'profile'->>'parent_deadline_at')::timestamptz,
  (expected->'lease'->'profile'->>'bound_at')::timestamptz+(expected->'lease'->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond') THEN
  RAISE check_violation USING MESSAGE='572 successor child binding stale after waits'; END IF;
 IF existing.id IS NOT NULL THEN RETURN existing.id; END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,aux.pack_task_id,aux.user_id,aux.epoch,aux.scope_id,'private_status',
  'private.revision.successor.binding.'||replace(p_grant::text,'-',''),aux.intent_hash,expected||jsonb_build_object('issued_top_xid',pg_current_xact_id()::text));
 RETURN identity;
END;
$bind572$),
 ('private_native_revision_successor_bound_v1(uuid,uuid)','private_native_revision_successor_bound_v1(p_binding uuid,p_preparation uuid)','jsonb','2950 2950',ARRAY['p_binding','p_preparation']::text[],$bound572$
DECLARE binding record;expected jsonb;committed_rows integer;issued_top text;
BEGIN
 SELECT j.* INTO binding FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_binding
  AND j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
  AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='private_status'
  AND j.payload_json->>'schema_version'='private_native_revision_successor_binding_v1'
  AND j.payload_json->>'preparation_id'=p_preparation::text;
 issued_top:=binding.payload_json->>'issued_top_xid';
 IF binding.id IS NULL OR jsonb_typeof(binding.payload_json->'issued_top_xid') IS DISTINCT FROM 'string'
  OR item_supply_internal.snapshot_keys(binding.payload_json,ARRAY['schema_version','grant_id','grant_hash','preparation_id','phase_id','phase_hash','job_id','reservation_id','generation_candidate_id','request_hash','ref','lease','stage_key','stage_id','stage_hash','subject_hash','valid_until','issued_top_xid']) IS DISTINCT FROM true
  OR binding.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(binding.payload_json) THEN
  RAISE check_violation USING MESSAGE='572 committed revision successor binding required'; END IF;
 BEGIN
  IF issued_top::xid8::text IS DISTINCT FROM issued_top THEN
   RAISE check_violation USING MESSAGE='572 committed revision successor binding required'; END IF;
 EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
  RAISE check_violation USING MESSAGE='572 committed revision successor binding required';
 END;
 IF issued_top IS NOT DISTINCT FROM pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='572 committed revision successor binding required'; END IF;
 expected:=item_supply_internal.private_native_revision_successor_preparation_v1((binding.payload_json->>'grant_id')::uuid,p_preparation);
 IF binding.payload_json IS DISTINCT FROM expected||jsonb_build_object('issued_top_xid',issued_top)
  OR binding.operation_key IS DISTINCT FROM 'private.revision.successor.binding.'||replace(expected->>'grant_id','-','') THEN
  RAISE check_violation USING MESSAGE='572 exact committed historical successor binding required'; END IF;
 SELECT count(*) INTO committed_rows FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(binding.pack_task_id,binding.user_id,binding.epoch,binding.scope_id)
  AND j.id=ANY(ARRAY[p_preparation,(expected->>'phase_id')::uuid,(expected->>'stage_id')::uuid])
  AND pg_xact_status(j.xmin::text::xid8)='committed';
 IF committed_rows<>3 THEN RAISE check_violation USING MESSAGE='572 prior committed successor preparation phase and stage required'; END IF;
 RETURN expected; -- Historical DATA only: no head/current/SOURCE/expiry check and no sender restoration.
END;
$bound572$),
 ('enforce_private_native_revision_successor_insert_v1()','enforce_private_native_revision_successor_insert_v1()','trigger','',ARRAY[]::text[],$insert572$
DECLARE body jsonb:=NEW.payload_json;protocol text:=body->>'schema_version';basis jsonb;expected jsonb;p_grant uuid;p_preparation uuid;
 aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 bank_candidate uuid;head integer;stamp timestamptz;intent text;
BEGIN
 IF COALESCE(protocol NOT IN('private_native_revision_successor_grant_v1','private_native_revision_successor_binding_v1'),true)
  AND NEW.operation_key NOT LIKE 'private.revision.successor.%' THEN RETURN NEW; END IF;
 IF protocol NOT IN('private_native_revision_successor_grant_v1','private_native_revision_successor_binding_v1') OR protocol IS NULL THEN
  RAISE check_violation USING MESSAGE='572 closed successor journal schema required'; END IF;
 -- Equality to the server full-TOP xid8 text also excludes empty/noncanonical/caller-old markers.
 IF jsonb_typeof(body->'issued_top_xid') IS DISTINCT FROM 'string'
  OR body->>'issued_top_xid' IS DISTINCT FROM pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='572 current canonical successor TOP marker required'; END IF;
 IF (body->>'issued_top_xid')::xid8::text IS DISTINCT FROM body->>'issued_top_xid' THEN
  RAISE check_violation USING MESSAGE='572 current canonical successor TOP marker required'; END IF;
 IF protocol='private_native_revision_successor_grant_v1' THEN
  basis:=item_supply_internal.private_native_revision_successor_basis_v1();
  SELECT j.intent_hash INTO intent FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(basis->>'pack_task_id')::uuid AND j.record_kind='task';
  expected:=jsonb_build_object('schema_version','private_native_revision_successor_grant_v1','approval_scope','c26_author_successor_20261017','basis',basis);
  IF (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.record_kind,NEW.intent_hash) IS DISTINCT FROM
    ((basis->>'pack_task_id')::uuid,(basis->>'user_id')::uuid,(basis->>'epoch')::integer,(basis->>'scope_id')::uuid,'private_status',intent)
   OR NEW.operation_key IS DISTINCT FROM 'private.revision.successor.grant.4391fd7f926e4324bb784815d081ec6e'
   OR (body - 'issued_top_xid'::text) IS DISTINCT FROM expected THEN RAISE check_violation USING MESSAGE='572 exact immutable successor grant required'; END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE
   (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id)
   AND (j.operation_key=NEW.operation_key OR j.payload_json->>'schema_version'='private_native_revision_successor_grant_v1')) THEN
   RAISE check_violation USING MESSAGE='572 successor grant already recorded'; END IF;
  RETURN NEW;
 END IF;
 p_grant:=(body->>'grant_id')::uuid;p_preparation:=(body->>'preparation_id')::uuid;
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 SELECT j.* INTO aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_preparation
  AND j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
  AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='private_attachment';
 SELECT j.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(aux.pack_task_id,aux.user_id,aux.epoch,aux.scope_id)
  AND j.record_kind='phase' AND j.payload_json->>'schema_version'='private_native_phase_v1'
  AND j.payload_json->>'job_id'=aux.payload_json->>'job_id';
 IF aux.id IS NULL OR phase.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',aux.payload_json->'request'->'ref','request',aux.payload_json->'request'->'request')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='572 current original child SOURCE required before binding'; END IF;
 PERFORM item_supply_internal.assert_private_native_phase(phase.payload_json,aux.user_id,aux.epoch,aux.scope_id,aux.pack_task_id);
 SELECT v.candidate_id INTO bank_candidate FROM tutor_item_supply_private_versions v WHERE v.id='a8e9af49-a9ae-4464-aea9-41239ab3a43d'
  AND v.user_id=aux.user_id AND v.epoch=aux.epoch AND v.scope_id=aux.scope_id FOR SHARE;
 SELECT max(v.version) INTO head FROM tutor_item_supply_private_versions v WHERE v.candidate_id=bank_candidate
  AND v.user_id=aux.user_id AND v.epoch=aux.epoch AND v.scope_id=aux.scope_id;
 IF bank_candidate IS NULL OR head IS DISTINCT FROM 1
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p WHERE p.pack_task_id=aux.pack_task_id
   AND p.user_id=aux.user_id AND p.epoch=aux.epoch AND p.slot_id='50df2afa-158c-586e-83c7-60bb99ea4307') THEN
  RAISE check_violation USING MESSAGE='572 unpublished original v1 head required at binding'; END IF;
 expected:=item_supply_internal.private_native_revision_successor_preparation_v1(p_grant,p_preparation);
 IF (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.record_kind,NEW.intent_hash) IS DISTINCT FROM
   (aux.pack_task_id,aux.user_id,aux.epoch,aux.scope_id,'private_status',aux.intent_hash)
  OR NEW.operation_key IS DISTINCT FROM 'private.revision.successor.binding.'||replace(p_grant::text,'-','') OR (body - 'issued_top_xid'::text) IS DISTINCT FROM expected THEN
  RAISE check_violation USING MESSAGE='572 exact successor binding namespace and payload required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id)
  AND j.record_kind='private_status' AND (j.operation_key=NEW.operation_key
   OR (j.payload_json->>'schema_version'='private_native_revision_successor_binding_v1'
    AND (j.payload_json->>'grant_id'=p_grant::text OR j.payload_json->>'preparation_id'=p_preparation::text)))) THEN
  RAISE check_violation USING MESSAGE='572 successor binding already recorded'; END IF;
 -- A basis/control wait must not retain the earlier head or clock decision.
 SELECT max(v.version) INTO head FROM tutor_item_supply_private_versions v WHERE v.candidate_id=bank_candidate
  AND v.user_id=aux.user_id AND v.epoch=aux.epoch AND v.scope_id=aux.scope_id;
 stamp:=clock_timestamp();
 IF head IS DISTINCT FROM 1 OR stamp>=LEAST((expected->>'valid_until')::timestamptz,(phase.payload_json->>'valid_until')::timestamptz,
  (expected->'lease'->>'expires_at')::timestamptz,(expected->'lease'->>'parent_deadline')::timestamptz,
  (expected->'lease'->'profile'->>'parent_deadline_at')::timestamptz,
  (expected->'lease'->'profile'->>'bound_at')::timestamptz+(expected->'lease'->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond') THEN
  RAISE check_violation USING MESSAGE='572 successor child binding stale after waits'; END IF;
 RETURN NEW;
END;
$insert572$)
 ) AS definitions(signature,header,result_type,types,names,body) LOOP
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.'||spec.signature);
  IF FOUND THEN
   IF actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
   OR actual.proname IS DISTINCT FROM split_part(spec.signature,'(',1) OR actual.prokind<>'f'
   OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
   OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype IS DISTINCT FROM to_regtype(spec.result_type)
   OR actual.pronargs<>cardinality(spec.names) OR actual.proargtypes IS DISTINCT FROM spec.types::oidvector
   OR actual.proargnames IS DISTINCT FROM (CASE WHEN cardinality(spec.names)=0 THEN NULL::text[] ELSE spec.names END)
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
   OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
    OR actual.prosrc IS DISTINCT FROM spec.body THEN
    RAISE check_violation USING MESSAGE='572 unexpected existing successor receiver: '||spec.signature; END IF;
  ELSE
   EXECUTE 'CREATE FUNCTION item_supply_internal.'||spec.header||' RETURNS '||spec.result_type||
    ' LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS '||quote_literal(spec.body);
   EXECUTE 'REVOKE ALL ON FUNCTION item_supply_internal.'||spec.signature||' FROM PUBLIC';
  END IF;
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.'||spec.signature);
  IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
   OR actual.proname IS DISTINCT FROM split_part(spec.signature,'(',1) OR actual.prokind<>'f'
   OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
   OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype IS DISTINCT FROM to_regtype(spec.result_type)
   OR actual.pronargs<>cardinality(spec.names) OR actual.proargtypes IS DISTINCT FROM spec.types::oidvector
   OR actual.proargnames IS DISTINCT FROM (CASE WHEN cardinality(spec.names)=0 THEN NULL::text[] ELSE spec.names END)
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
   OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.prosrc IS DISTINCT FROM spec.body THEN
   RAISE check_violation USING MESSAGE='572 installed successor receiver attributes/body changed: '||spec.signature; END IF;
 END LOOP;
 SELECT t.* INTO actual FROM pg_catalog.pg_trigger t WHERE t.tgrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass
  AND t.tgname='private_native_revision_successor_insert';
 IF NOT FOUND THEN
  CREATE TRIGGER private_native_revision_successor_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal
   FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_revision_successor_insert_v1();
 END IF;
 SELECT t.* INTO actual FROM pg_catalog.pg_trigger t WHERE t.tgrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass
  AND t.tgname='private_native_revision_successor_insert';
 IF NOT FOUND OR actual.tgfoid IS DISTINCT FROM 'item_supply_internal.enforce_private_native_revision_successor_insert_v1()'::regprocedure
  OR actual.tgtype<>7 OR actual.tgenabled<>'O' OR actual.tgisinternal OR actual.tgdeferrable OR actual.tginitdeferred
  OR actual.tgnargs<>0 OR actual.tgqual IS NOT NULL OR actual.tgattr::text<>'' OR actual.tgargs<>''::bytea
  OR actual.tgparentid<>0 OR actual.tgconstrrelid<>0 OR actual.tgconstrindid<>0 OR actual.tgconstraint<>0
  OR actual.tgoldtable IS NOT NULL OR actual.tgnewtable IS NOT NULL
  OR pg_get_triggerdef(actual.oid) IS DISTINCT FROM 'CREATE TRIGGER private_native_revision_successor_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_revision_successor_insert_v1()' THEN
  RAISE check_violation USING MESSAGE='572 exact successor journal trigger required'; END IF;
END;
$install572$;

-- Only original570 stage selection changes; oldpid is excluded before invoking successor DATA.
DO $patch572$
DECLARE actual record;verified record;definition text;
 old_body constant text := $old572$
DECLARE task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 started public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 invest public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 parent_artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 reservation public.tutor_item_supply_private_reservations%ROWTYPE;
 settlement public.tutor_item_supply_private_runtime_settlements%ROWTYPE;
 profile public.tutor_item_supply_parameter_profiles%ROWTYPE;
 prep jsonb; ref jsonb; request jsonb; lease_json jsonb; expected jsonb; amounts jsonb; directive text; scope_hash text;
BEGIN
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 SELECT s.scope_hash INTO scope_hash FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='570 current original namespace and active plan required'; END IF;
 SELECT j.* INTO task_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  j.id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.pack_task_id=j.id AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
  AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='task' FOR SHARE;
 IF task_row.id IS NULL OR task_row.payload_json->>'enhancement' IS DISTINCT FROM 'prefer_private'
  OR task_row.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134' THEN
  RAISE check_violation USING MESSAGE='570 original PRIVATE task required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_budget_roots r WHERE r.id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  AND r.user_id=task_row.user_id AND r.epoch=task_row.epoch AND r.scope_id=task_row.scope_id FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='570 original canonical root required'; END IF;
 SELECT j.* INTO aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_preparation
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='private_attachment' AND j.operation_key='private.aux.'||p_preparation::text
  AND j.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND j.xmin::text::bigint<>(txid_current()%4294967296);
 prep:=aux.payload_json->'request';ref:=prep->'ref';request:=prep->'request';lease_json:=prep->'lease';
 IF aux.id IS NULL OR item_supply_internal.snapshot_keys(aux.payload_json,ARRAY['schema_version','job_id','reservation_id','request','valid_until']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(prep,ARRAY['schema_version','ref','lease','investigation_id','parent_version_id','request','directive_hash']) IS DISTINCT FROM true
  OR prep->>'schema_version' IS DISTINCT FROM 'private_native_revision_phase_v1'
  OR item_supply_internal.snapshot_keys(ref,ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(request,ARRAY['schema_version','candidate_id','scope_hash','demand_binding','item_key','version','blueprint','public_template','profile','limits','materials']) IS DISTINCT FROM true
  OR (ref->>'pack_task_id',ref->>'slot_id',ref->>'business_item_id',ref->>'root_id',ref->>'mapping_receipt_id',ref->>'user_id',ref->>'epoch',ref->>'scope_id',ref->>'goal_scope_id',ref->>'slot',ref->>'parent_version_id') IS DISTINCT FROM
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc','50df2afa-158c-586e-83c7-60bb99ea4307','2e1251b9-efd2-5624-930f-174f726c35ea','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','cef6af15-84c0-466a-b330-3dc3235aa587','cef6af15-84c0-466a-b330-3dc3235aa587','practice','a8e9af49-a9ae-4464-aea9-41239ab3a43d')
  OR prep->>'parent_version_id' IS DISTINCT FROM ref->>'parent_version_id'
  OR prep->>'investigation_id' IS DISTINCT FROM '8914dcd5-a275-480f-850c-c4563be6ebe5'
  OR aux.payload_json->>'job_id' IS DISTINCT FROM lease_json->>'job_id'
  OR (lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch') IS DISTINCT FROM ('private',ref->>'user_id','1')
  OR request->>'schema_version' IS DISTINCT FROM 'item_generation_request_v2'
  OR request->>'candidate_id' IS NULL OR request->>'candidate_id'=p_preparation::text
  OR request->>'item_key' IS DISTINCT FROM 'private-native.2e1251b9efd25624930f174f726c35ea'
  OR request->>'version' IS DISTINCT FROM 'v2' OR request->>'scope_hash' IS DISTINCT FROM scope_hash
  OR request->'profile' IS DISTINCT FROM lease_json->'profile'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(task_row.payload_json->'slots') s
   WHERE s->>'slot_id'=ref->>'slot_id' AND s->>'logical_item_id'=ref->>'business_item_id') THEN
  RAISE check_violation USING MESSAGE='570 exact C25 normal revision preparation required'; END IF;
 SELECT j.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='phase' AND j.operation_key='private.phase.'||(lease_json->>'job_id')
  AND j.payload_json->>'schema_version'='private_native_phase_v1'
  AND j.payload_json->>'job_id'=lease_json->>'job_id' AND j.xmin::text::bigint<>(txid_current()%4294967296);
 IF phase.id IS NULL OR phase.payload_json->'ref' IS DISTINCT FROM ref
  OR (aux.payload_json->>'valid_until')::timestamptz IS NULL OR (phase.payload_json->>'valid_until')::timestamptz IS NULL
  OR (lease_json->>'expires_at')::timestamptz IS NULL OR (lease_json->>'parent_deadline')::timestamptz IS NULL
  OR ((phase.payload_json->'lease') - 'state_version'::text) IS DISTINCT FROM (lease_json - 'state_version'::text)
  OR aux.created_at>=LEAST((aux.payload_json->>'valid_until')::timestamptz,(phase.payload_json->>'valid_until')::timestamptz,
    (lease_json->>'expires_at')::timestamptz,(lease_json->>'parent_deadline')::timestamptz) THEN
  RAISE check_violation USING MESSAGE='570 exact lawful prepared child phase required'; END IF;
 SELECT q.* INTO invest FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id='8914dcd5-a275-480f-850c-c4563be6ebe5'
  AND q.kind='investigation' AND q.version_id='a8e9af49-a9ae-4464-aea9-41239ab3a43d'
  AND (q.user_id,q.epoch,q.scope_id,q.pack_task_id,q.slot_id,q.root_id)=(task_row.user_id,task_row.epoch,task_row.scope_id,task_row.id,(ref->>'slot_id')::uuid,(ref->>'root_id')::uuid)
  AND q.xmin::text::bigint<>(txid_current()%4294967296);
 SELECT q.* INTO peer FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id='b90b09bd-cac4-4ed7-98d9-f58adb739d99'
  AND q.kind='review' AND q.version_id=invest.version_id
  AND (q.user_id,q.epoch,q.scope_id,q.pack_task_id,q.slot_id,q.root_id)=(invest.user_id,invest.epoch,invest.scope_id,invest.pack_task_id,invest.slot_id,invest.root_id)
  AND q.xmin::text::bigint<>(txid_current()%4294967296);
 SELECT a.* INTO parent_artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id='1d43ebb0-3ad2-4d25-a6ce-ca70960173a8'
  AND (a.user_id,a.epoch,a.scope_id,a.version_id)=(task_row.user_id,task_row.epoch,task_row.scope_id,invest.version_id)
  AND a.mode='live' AND a.xmin::text::bigint<>(txid_current()%4294967296);
 SELECT string_agg(x.value->>'proposed_revision',E'\n' ORDER BY x.n) INTO directive
  FROM jsonb_array_elements(invest.payload_json->'output'->'analyses') WITH ORDINALITY x(value,n)
  WHERE length(x.value->>'proposed_revision')>0;
 IF invest.id IS NULL OR peer.id IS NULL OR parent_artifact.id IS NULL
  OR invest.payload_hash IS DISTINCT FROM '132d0344345787adbcaf9587e56a31252017cc1f2f40b886e3b993d8fc539f8e'
  OR peer.payload_hash IS DISTINCT FROM 'af34b1bda02a58e1a1a500dba4be779bdde20cbbe090eae5415758d2c6557c28'
  OR parent_artifact.artifact_hash IS DISTINCT FROM 'f401a3fc9e42678079f7b0956db069d847120bd87ad4de1a172c43786bf0df84'
  OR invest.payload_json->>'parent_artifact_id' IS DISTINCT FROM parent_artifact.id::text
  OR invest.payload_json->>'parent_review_id' IS DISTINCT FROM peer.id::text
  OR invest.payload_json->>'parent_review_hash' IS DISTINCT FROM peer.payload_hash
  OR invest.payload_json->'request'->'review_input'->'source' IS DISTINCT FROM parent_artifact.source_json
  OR invest.payload_json->'request'->'review_input'->'binding' IS DISTINCT FROM peer.payload_json->'bundle'->'binding'
  OR ((invest.payload_json->'ref') - 'parent_version_id'::text) IS DISTINCT FROM (ref - 'parent_version_id'::text)
  OR invest.checked_at>=invest.valid_until OR invest.created_at>=invest.valid_until
  OR peer.checked_at>=peer.valid_until OR peer.created_at>=peer.valid_until
  OR prep->>'directive_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(to_jsonb(directive))
  OR prep->>'directive_hash' IS DISTINCT FROM '4a71086d8bf24fcfffd9c027b02cddcf27f77e3db7ce03c76df354580ae6f764'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(invest.payload_json->'output'->'analyses') a
   WHERE a->>'dispute_key'='0cfafd6e34c6d62c42fb87fc0ee677711a099154dd9761bb634ca1d3448b81e4' AND a->>'finding_status'='supported') THEN
  RAISE check_violation USING MESSAGE='570 exact committed C25 revision lineage required'; END IF;
 expected:=item_supply_internal.private_native_same_scene_d1_render_v1(peer.payload_json->'spec',parent_artifact.source_json);
 IF request->'blueprint' IS DISTINCT FROM expected->'blueprint' OR request->'public_template' IS DISTINCT FROM expected->'public_template'
  OR request->'materials' IS DISTINCT FROM parent_artifact.request_json->'materials' THEN
  RAISE check_violation USING MESSAGE='570 exact frozen R1 request and materials required'; END IF;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=(lease_json->>'job_id')::uuid
  AND c.user_id=task_row.user_id AND c.epoch=task_row.epoch AND c.scope_id=task_row.scope_id FOR UPDATE;
 SELECT p.* INTO profile FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id;
 SELECT r.* INTO reservation FROM tutor_item_supply_private_reservations r WHERE r.id=(aux.payload_json->>'reservation_id')::uuid
  AND r.job_id=ctrl.job_id AND r.user_id=task_row.user_id AND r.epoch=task_row.epoch AND r.scope_id=task_row.scope_id
  AND r.root_id=(ref->>'root_id')::uuid AND r.reservation_key='gen.'||replace(request->>'candidate_id','-','') FOR SHARE;
 SELECT s.* INTO settlement FROM tutor_item_supply_private_runtime_settlements s WHERE s.reservation_id=reservation.id
  AND s.user_id=task_row.user_id AND s.epoch=task_row.epoch AND s.scope_id=task_row.scope_id
  AND s.settlement_key='generation.'||replace(request->>'candidate_id','-','') AND s.sequence=1 FOR SHARE;
 SELECT j.* INTO started FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='private_status'
  AND j.operation_key='private.stage.'||replace(ref->>'business_item_id','-','')||'.revision.'||item_supply_internal.snapshot_hash('"v2"'::jsonb)||'.started'
  AND j.payload_json->>'schema_version'='private_native_stage_v1' AND j.payload_json->>'stage'='revision'
  AND j.payload_json->>'status'='started' AND j.payload_json->'receipt_id'='null'::jsonb
  AND j.payload_json->>'job_id'=ctrl.job_id::text AND j.payload_json->>'slot_id'=ref->>'slot_id'
  AND j.payload_json->>'subject_hash'=item_supply_internal.snapshot_hash('"v2"'::jsonb)
  AND j.xmin::text::bigint<>(txid_current()%4294967296);
 IF ctrl.id IS NULL OR profile.id IS NULL OR reservation.id IS NULL OR settlement.id IS NULL OR started.id IS NULL
  OR ctrl.lease_generation IS DISTINCT FROM (lease_json->>'generation')::integer
  OR reservation.lease_generation IS DISTINCT FROM ctrl.lease_generation
  OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR ctrl.profile_snapshot_json->'profile' IS DISTINCT FROM lease_json->'profile'
  OR ctrl.profile_snapshot_json->'retry_policy' IS DISTINCT FROM lease_json->'retry_policy'
  OR profile.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash' THEN
  RAISE check_violation USING MESSAGE='570 original revision producer profile reservation settlement and once required'; END IF;
 SELECT jsonb_object_agg(a.resource_kind,a.actual_amount) INTO amounts FROM tutor_item_supply_private_runtime_settlement_amounts a WHERE a.settlement_id=settlement.id;
 RETURN jsonb_build_object('task',to_jsonb(task_row),'aux',to_jsonb(aux),'phase',to_jsonb(phase),'started',to_jsonb(started),
  'investigation',to_jsonb(invest),'parent_review',to_jsonb(peer),'parent_artifact',to_jsonb(parent_artifact),'expected_spec',expected,
  'control',to_jsonb(ctrl),'reservation',to_jsonb(reservation),'settlement',to_jsonb(settlement),'amounts',amounts,
  'generation_candidate_id',request->>'candidate_id',
  'producer_binding',jsonb_build_array(profile.profile_json->'profile_key'->>'provider',profile.profile_json->'profile_key'->>'model_version'));
END;
$old572$;
 new_body constant text := $new572$
DECLARE task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 started public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 invest public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 parent_artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 reservation public.tutor_item_supply_private_reservations%ROWTYPE;
 settlement public.tutor_item_supply_private_runtime_settlements%ROWTYPE;
 profile public.tutor_item_supply_parameter_profiles%ROWTYPE;
 prep jsonb; ref jsonb; request jsonb; lease_json jsonb; expected jsonb; amounts jsonb; directive text; scope_hash text; successor jsonb; successor_binding uuid; successor_count bigint; successor_stage_key text; successor_subject_hash text;
BEGIN
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 SELECT s.scope_hash INTO scope_hash FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='570 current original namespace and active plan required'; END IF;
 SELECT j.* INTO task_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  j.id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.pack_task_id=j.id AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
  AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='task' FOR SHARE;
 IF task_row.id IS NULL OR task_row.payload_json->>'enhancement' IS DISTINCT FROM 'prefer_private'
  OR task_row.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134' THEN
  RAISE check_violation USING MESSAGE='570 original PRIVATE task required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_budget_roots r WHERE r.id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  AND r.user_id=task_row.user_id AND r.epoch=task_row.epoch AND r.scope_id=task_row.scope_id FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='570 original canonical root required'; END IF;
 SELECT j.* INTO aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_preparation
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='private_attachment' AND j.operation_key='private.aux.'||p_preparation::text
  AND j.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND j.xmin::text::bigint<>(txid_current()%4294967296);
 prep:=aux.payload_json->'request';ref:=prep->'ref';request:=prep->'request';lease_json:=prep->'lease';
 IF aux.id IS NULL OR item_supply_internal.snapshot_keys(aux.payload_json,ARRAY['schema_version','job_id','reservation_id','request','valid_until']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(prep,ARRAY['schema_version','ref','lease','investigation_id','parent_version_id','request','directive_hash']) IS DISTINCT FROM true
  OR prep->>'schema_version' IS DISTINCT FROM 'private_native_revision_phase_v1'
  OR item_supply_internal.snapshot_keys(ref,ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(request,ARRAY['schema_version','candidate_id','scope_hash','demand_binding','item_key','version','blueprint','public_template','profile','limits','materials']) IS DISTINCT FROM true
  OR (ref->>'pack_task_id',ref->>'slot_id',ref->>'business_item_id',ref->>'root_id',ref->>'mapping_receipt_id',ref->>'user_id',ref->>'epoch',ref->>'scope_id',ref->>'goal_scope_id',ref->>'slot',ref->>'parent_version_id') IS DISTINCT FROM
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc','50df2afa-158c-586e-83c7-60bb99ea4307','2e1251b9-efd2-5624-930f-174f726c35ea','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','cef6af15-84c0-466a-b330-3dc3235aa587','cef6af15-84c0-466a-b330-3dc3235aa587','practice','a8e9af49-a9ae-4464-aea9-41239ab3a43d')
  OR prep->>'parent_version_id' IS DISTINCT FROM ref->>'parent_version_id'
  OR prep->>'investigation_id' IS DISTINCT FROM '8914dcd5-a275-480f-850c-c4563be6ebe5'
  OR aux.payload_json->>'job_id' IS DISTINCT FROM lease_json->>'job_id'
  OR (lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch') IS DISTINCT FROM ('private',ref->>'user_id','1')
  OR request->>'schema_version' IS DISTINCT FROM 'item_generation_request_v2'
  OR request->>'candidate_id' IS NULL OR request->>'candidate_id'=p_preparation::text
  OR request->>'item_key' IS DISTINCT FROM 'private-native.2e1251b9efd25624930f174f726c35ea'
  OR request->>'version' IS DISTINCT FROM 'v2' OR request->>'scope_hash' IS DISTINCT FROM scope_hash
  OR request->'profile' IS DISTINCT FROM lease_json->'profile'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(task_row.payload_json->'slots') s
   WHERE s->>'slot_id'=ref->>'slot_id' AND s->>'logical_item_id'=ref->>'business_item_id') THEN
  RAISE check_violation USING MESSAGE='570 exact C25 normal revision preparation required'; END IF;
 SELECT j.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='phase' AND j.operation_key='private.phase.'||(lease_json->>'job_id')
  AND j.payload_json->>'schema_version'='private_native_phase_v1'
  AND j.payload_json->>'job_id'=lease_json->>'job_id' AND j.xmin::text::bigint<>(txid_current()%4294967296);
 IF phase.id IS NULL OR phase.payload_json->'ref' IS DISTINCT FROM ref
  OR (aux.payload_json->>'valid_until')::timestamptz IS NULL OR (phase.payload_json->>'valid_until')::timestamptz IS NULL
  OR (lease_json->>'expires_at')::timestamptz IS NULL OR (lease_json->>'parent_deadline')::timestamptz IS NULL
  OR ((phase.payload_json->'lease') - 'state_version'::text) IS DISTINCT FROM (lease_json - 'state_version'::text)
  OR aux.created_at>=LEAST((aux.payload_json->>'valid_until')::timestamptz,(phase.payload_json->>'valid_until')::timestamptz,
    (lease_json->>'expires_at')::timestamptz,(lease_json->>'parent_deadline')::timestamptz) THEN
  RAISE check_violation USING MESSAGE='570 exact lawful prepared child phase required'; END IF;
 SELECT q.* INTO invest FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id='8914dcd5-a275-480f-850c-c4563be6ebe5'
  AND q.kind='investigation' AND q.version_id='a8e9af49-a9ae-4464-aea9-41239ab3a43d'
  AND (q.user_id,q.epoch,q.scope_id,q.pack_task_id,q.slot_id,q.root_id)=(task_row.user_id,task_row.epoch,task_row.scope_id,task_row.id,(ref->>'slot_id')::uuid,(ref->>'root_id')::uuid)
  AND q.xmin::text::bigint<>(txid_current()%4294967296);
 SELECT q.* INTO peer FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id='b90b09bd-cac4-4ed7-98d9-f58adb739d99'
  AND q.kind='review' AND q.version_id=invest.version_id
  AND (q.user_id,q.epoch,q.scope_id,q.pack_task_id,q.slot_id,q.root_id)=(invest.user_id,invest.epoch,invest.scope_id,invest.pack_task_id,invest.slot_id,invest.root_id)
  AND q.xmin::text::bigint<>(txid_current()%4294967296);
 SELECT a.* INTO parent_artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id='1d43ebb0-3ad2-4d25-a6ce-ca70960173a8'
  AND (a.user_id,a.epoch,a.scope_id,a.version_id)=(task_row.user_id,task_row.epoch,task_row.scope_id,invest.version_id)
  AND a.mode='live' AND a.xmin::text::bigint<>(txid_current()%4294967296);
 SELECT string_agg(x.value->>'proposed_revision',E'\n' ORDER BY x.n) INTO directive
  FROM jsonb_array_elements(invest.payload_json->'output'->'analyses') WITH ORDINALITY x(value,n)
  WHERE length(x.value->>'proposed_revision')>0;
 IF invest.id IS NULL OR peer.id IS NULL OR parent_artifact.id IS NULL
  OR invest.payload_hash IS DISTINCT FROM '132d0344345787adbcaf9587e56a31252017cc1f2f40b886e3b993d8fc539f8e'
  OR peer.payload_hash IS DISTINCT FROM 'af34b1bda02a58e1a1a500dba4be779bdde20cbbe090eae5415758d2c6557c28'
  OR parent_artifact.artifact_hash IS DISTINCT FROM 'f401a3fc9e42678079f7b0956db069d847120bd87ad4de1a172c43786bf0df84'
  OR invest.payload_json->>'parent_artifact_id' IS DISTINCT FROM parent_artifact.id::text
  OR invest.payload_json->>'parent_review_id' IS DISTINCT FROM peer.id::text
  OR invest.payload_json->>'parent_review_hash' IS DISTINCT FROM peer.payload_hash
  OR invest.payload_json->'request'->'review_input'->'source' IS DISTINCT FROM parent_artifact.source_json
  OR invest.payload_json->'request'->'review_input'->'binding' IS DISTINCT FROM peer.payload_json->'bundle'->'binding'
  OR ((invest.payload_json->'ref') - 'parent_version_id'::text) IS DISTINCT FROM (ref - 'parent_version_id'::text)
  OR invest.checked_at>=invest.valid_until OR invest.created_at>=invest.valid_until
  OR peer.checked_at>=peer.valid_until OR peer.created_at>=peer.valid_until
  OR prep->>'directive_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(to_jsonb(directive))
  OR prep->>'directive_hash' IS DISTINCT FROM '4a71086d8bf24fcfffd9c027b02cddcf27f77e3db7ce03c76df354580ae6f764'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(invest.payload_json->'output'->'analyses') a
   WHERE a->>'dispute_key'='0cfafd6e34c6d62c42fb87fc0ee677711a099154dd9761bb634ca1d3448b81e4' AND a->>'finding_status'='supported') THEN
  RAISE check_violation USING MESSAGE='570 exact committed C25 revision lineage required'; END IF;
 expected:=item_supply_internal.private_native_same_scene_d1_render_v1(peer.payload_json->'spec',parent_artifact.source_json);
 IF request->'blueprint' IS DISTINCT FROM expected->'blueprint' OR request->'public_template' IS DISTINCT FROM expected->'public_template'
  OR request->'materials' IS DISTINCT FROM parent_artifact.request_json->'materials' THEN
  RAISE check_violation USING MESSAGE='570 exact frozen R1 request and materials required'; END IF;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=(lease_json->>'job_id')::uuid
  AND c.user_id=task_row.user_id AND c.epoch=task_row.epoch AND c.scope_id=task_row.scope_id FOR UPDATE;
 SELECT p.* INTO profile FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id;
 SELECT r.* INTO reservation FROM tutor_item_supply_private_reservations r WHERE r.id=(aux.payload_json->>'reservation_id')::uuid
  AND r.job_id=ctrl.job_id AND r.user_id=task_row.user_id AND r.epoch=task_row.epoch AND r.scope_id=task_row.scope_id
  AND r.root_id=(ref->>'root_id')::uuid AND r.reservation_key='gen.'||replace(request->>'candidate_id','-','') FOR SHARE;
 SELECT s.* INTO settlement FROM tutor_item_supply_private_runtime_settlements s WHERE s.reservation_id=reservation.id
  AND s.user_id=task_row.user_id AND s.epoch=task_row.epoch AND s.scope_id=task_row.scope_id
  AND s.settlement_key='generation.'||replace(request->>'candidate_id','-','') AND s.sequence=1 FOR SHARE;
 successor_subject_hash:=item_supply_internal.snapshot_hash('"v2"'::jsonb);
 successor_stage_key:='private.stage.'||replace(ref->>'business_item_id','-','')||'.revision.'||successor_subject_hash||'.started';
 -- Fixed oldpid cannot enter this branch: basis -> attempt(oldpid) must not recurse.
 IF p_preparation IS DISTINCT FROM '4391fd7f-926e-4324-bb78-4815d081ec6e'::uuid THEN
  SELECT count(*),(array_agg(j.id ORDER BY j.id))[1] INTO successor_count,successor_binding FROM tutor_item_supply_private_persistent_pack_journal j WHERE
   (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
   AND j.record_kind='private_status' AND j.payload_json->>'schema_version'='private_native_revision_successor_binding_v1'
   AND j.payload_json->>'preparation_id'=p_preparation::text;
  IF successor_count>1 THEN RAISE check_violation USING MESSAGE='572 one exact successor binding required'; END IF;
  IF successor_count=1 THEN
   successor:=item_supply_internal.private_native_revision_successor_bound_v1(successor_binding,p_preparation);
   successor_stage_key:=successor->>'stage_key';successor_subject_hash:=successor->>'subject_hash';
  END IF;
 END IF;
 SELECT j.* INTO started FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='private_status'
  AND j.operation_key=successor_stage_key
  AND j.payload_json->>'schema_version'='private_native_stage_v1' AND j.payload_json->>'stage'='revision'
  AND j.payload_json->>'status'='started' AND j.payload_json->'receipt_id'='null'::jsonb
  AND j.payload_json->>'job_id'=ctrl.job_id::text AND j.payload_json->>'slot_id'=ref->>'slot_id'
  AND j.payload_json->>'subject_hash'=successor_subject_hash
  AND j.xmin::text::bigint<>(txid_current()%4294967296);
 IF ctrl.id IS NULL OR profile.id IS NULL OR reservation.id IS NULL OR settlement.id IS NULL OR started.id IS NULL
  OR ctrl.lease_generation IS DISTINCT FROM (lease_json->>'generation')::integer
  OR reservation.lease_generation IS DISTINCT FROM ctrl.lease_generation
  OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR ctrl.profile_snapshot_json->'profile' IS DISTINCT FROM lease_json->'profile'
  OR ctrl.profile_snapshot_json->'retry_policy' IS DISTINCT FROM lease_json->'retry_policy'
  OR profile.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash' THEN
  RAISE check_violation USING MESSAGE='570 original revision producer profile reservation settlement and once required'; END IF;
 SELECT jsonb_object_agg(a.resource_kind,a.actual_amount) INTO amounts FROM tutor_item_supply_private_runtime_settlement_amounts a WHERE a.settlement_id=settlement.id;
 RETURN jsonb_build_object('task',to_jsonb(task_row),'aux',to_jsonb(aux),'phase',to_jsonb(phase),'started',to_jsonb(started),
  'investigation',to_jsonb(invest),'parent_review',to_jsonb(peer),'parent_artifact',to_jsonb(parent_artifact),'expected_spec',expected,
  'control',to_jsonb(ctrl),'reservation',to_jsonb(reservation),'settlement',to_jsonb(settlement),'amounts',amounts,
  'generation_candidate_id',request->>'candidate_id',
  'producer_binding',jsonb_build_array(profile.profile_json->'profile_key'->>'provider',profile.profile_json->'profile_key'->>'model_version'));
END;
$new572$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='572 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_native_revision_durability_attempt_v1(uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_native_revision_durability_attempt_v1' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.jsonb'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM '2950'::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['p_preparation']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='572 original revision attempt identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='572 original revision attempt body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='572 original revision attempt definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='572 revision attempt metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch572$;
