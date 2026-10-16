-- Persistent ONE user demand / PUBLIC work. Default-off B1d receiver, append-only.
-- Old508-522 bytes are untouched. Caller owns TOP transaction; no provider/ledger IO.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
 RAISE check_violation USING MESSAGE='523 B1d only'; END IF; END $$;
DO $guard523$
DECLARE expected record; actual record;
BEGIN
 FOR expected IN SELECT * FROM (VALUES
 ('item_supply_internal.assert_persistent_pack_phase(jsonb)','6c26c1c3fb4fac05b84dcd8dc4a7f112d375167039e8df14f3a06f7a73d896d2','void',ARRAY['p']::text[]),
 ('item_supply_internal.enforce_persistent_pack_journal_insert()','30456f50482feed7c23d119752287d3559fced4a33d9bc98d01c5d0ac80cd0dd','trigger',NULL::text[]),
 ('item_supply_internal.purge_persistent_pack_on_epoch_advance()','dc85dee1aee0741f1b2b68a015d2e1547ad549eb6e7d07d70fb21677e2a9745e','trigger',NULL::text[]),
 ('item_supply_internal.persistent_relation_anchor_matches(jsonb,uuid,uuid,uuid)','80517e523d0ef7f6ebc218f3b46561b9f51f9a61eb8b5a9f8e76bba00edc71bf','bool',ARRAY['p','anchor','exact_root','exact_job']::text[])
 ) AS f(signature,sha,returntype,argnames) LOOP
  SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(expected.signature);
  IF FOUND AND (encode(sha256(convert_to(replace(actual.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM expected.sha
   OR actual.prokind<>'f' OR actual.lanname<>'plpgsql' OR actual.proretset OR actual.proisstrict
   OR NOT actual.prosecdef OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
   OR actual.prorettype IS DISTINCT FROM to_regtype('pg_catalog.'||expected.returntype)
   OR actual.pronargs IS DISTINCT FROM COALESCE(cardinality(expected.argnames),0)
   OR actual.proargnames IS DISTINCT FROM expected.argnames OR actual.proallargtypes IS NOT NULL
   OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
  THEN RAISE check_violation USING MESSAGE='523 unknown helper body or attributes'; END IF;
 END LOOP;
END $guard523$;
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_persistent_pack_journal (
 id uuid PRIMARY KEY, public_task_id uuid NOT NULL, record_kind text NOT NULL
 CHECK(record_kind IN('task','version','qualified','phase','dispatch_started','stage_started','stage_result','phase_result')),
 operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 3 AND 200),
 root_id uuid REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid, phase_id uuid,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
 payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(operation_key,record_kind), UNIQUE(id,public_task_id),
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS persistent_public_intent_once ON tutor_item_supply_shared_persistent_pack_journal
 ((payload_json->>'intent_hash')) WHERE record_kind='task';
CREATE INDEX IF NOT EXISTS persistent_public_work_events ON tutor_item_supply_shared_persistent_pack_journal(public_task_id,created_at,id);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_persistent_pack_journal (
 id uuid PRIMARY KEY, pack_task_id uuid NOT NULL, user_id uuid NOT NULL, epoch integer NOT NULL CHECK(epoch>0),
 scope_id uuid NOT NULL, record_kind text NOT NULL CHECK(record_kind IN('task','phase','pause','stop','private_attachment','private_status')),
 operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 3 AND 200),
 intent_hash text NOT NULL CHECK(intent_hash ~ '^[0-9a-f]{64}$'),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
 payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(id,user_id,epoch,scope_id), UNIQUE(user_id,epoch,operation_key,record_kind),
 FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS persistent_private_intent_once ON tutor_item_supply_private_persistent_pack_journal
 (user_id,epoch,scope_id,intent_hash) WHERE record_kind='task';
COMMENT ON TABLE tutor_item_supply_shared_persistent_pack_journal IS 'shared-confidential public task/work/phase DATA; no private identity/hash; not quality authority';
COMMENT ON TABLE tutor_item_supply_private_persistent_pack_journal IS 'PRIVATE demand task/phase/shared attachment; exact user epoch scope; no restored capabilities';

CREATE OR REPLACE FUNCTION item_supply_internal.assert_persistent_pack_phase(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE c record; b record; phase record; stamp timestamptz;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_task_id','public_slot_id','phase_id','revision_id','kind','operation_key','job_id','root_id','batch_id','lease','valid_until','frame_hash','anchor_version_id','candidate_version_ids']) IS DISTINCT FROM true
  OR p->>'frame_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p-'frame_hash')
 THEN RAISE check_violation USING MESSAGE='523 exact phase schema/frame required'; END IF;
 IF p->>'schema_version' IS DISTINCT FROM 'persistent_public_phase_v1'
  OR COALESCE(p->>'kind' IN('candidate','relation_pack'),false) IS DISTINCT FROM true OR p->'lease'->>'visibility' IS DISTINCT FROM 'public'
  OR p->'lease'->>'owner_id' IS NOT NULL OR p->'lease'->>'owner_epoch' IS NOT NULL
  OR COALESCE(p->>'frame_hash' ~ '^[0-9a-f]{64}$',false) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(p->'lease',ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
  OR p->>'job_id' IS DISTINCT FROM p->'lease'->>'job_id'
  OR COALESCE(p->>'operation_key' ~ '^[a-z0-9][a-z0-9._:-]{2,159}$',false) IS DISTINCT FROM true
  OR COALESCE(p->>'valid_until' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
  OR jsonb_typeof(p->'candidate_version_ids') IS DISTINCT FROM 'array'
  THEN RAISE check_violation USING MESSAGE='523 closed public phase required'; END IF;
 IF p->>'kind'='relation_pack' THEN
  IF p->'public_slot_id' IS DISTINCT FROM 'null'::jsonb OR p->'revision_id' IS DISTINCT FROM 'null'::jsonb
   OR jsonb_array_length(p->'candidate_version_ids') IS DISTINCT FROM 5
   OR (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p->'candidate_version_ids'))<>5
   OR COALESCE(p->'candidate_version_ids' @> jsonb_build_array(p->>'anchor_version_id'),false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='523 exact five relation versions required'; END IF;
 ELSE
  IF p->'anchor_version_id' IS DISTINCT FROM 'null'::jsonb OR p->'candidate_version_ids' IS DISTINCT FROM '[]'::jsonb
   OR COALESCE(p->>'public_slot_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
   OR COALESCE(p->>'revision_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='523 exact candidate slot revision required'; END IF;
 END IF;
 SELECT j.root_id,ctrl.* INTO c FROM tutor_item_supply_shared_jobs j
 JOIN tutor_item_supply_shared_job_controls ctrl ON ctrl.job_id=j.id WHERE j.id=(p->>'job_id')::uuid FOR SHARE OF j,ctrl;
 IF NOT FOUND OR c.root_id IS DISTINCT FROM (p->>'root_id')::uuid OR c.state<>'leased'
  OR c.lease_owner IS DISTINCT FROM p->'lease'->>'lease_owner'
  OR c.lease_generation::text IS DISTINCT FROM p->'lease'->>'generation'
  OR c.state_version<(p->'lease'->>'state_version')::integer
  OR c.parent_deadline IS DISTINCT FROM (p->'lease'->>'parent_deadline')::timestamptz
  OR (p->'lease'->>'expires_at')::timestamptz>c.lease_expires_at
  OR jsonb_typeof(p->'lease'->'generation') IS DISTINCT FROM 'number'
  OR jsonb_typeof(p->'lease'->'state_version') IS DISTINCT FROM 'number'
  OR (CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END) IS DISTINCT FROM p->'lease'->'profile'
  OR item_supply_internal.controlled_counterexample_held(c.job_id) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='523 original current public lease required'; END IF;
 SELECT batches.* INTO b FROM tutor_item_supply_development_model_accounting_batches batches
 JOIN tutor_item_supply_development_model_accounting_jobs bindings ON bindings.batch_id=batches.id
 WHERE batches.id=(p->>'batch_id')::uuid AND batches.root_id=(p->>'root_id')::uuid
 AND bindings.job_id=(p->>'job_id')::uuid AND bindings.lease_generation=c.lease_generation
 AND bindings.lease_owner=c.lease_owner AND bindings.parent_deadline=c.parent_deadline FOR SHARE OF batches,bindings;
 IF NOT FOUND OR b.authorization_key<>'development-unlimited-model-calls-20261010'
  OR c.parent_deadline>b.valid_until OR b.valid_until>b.started_at+interval '7200 seconds'
 THEN RAISE check_violation USING MESSAGE='523 original517 accounting binding required'; END IF;
 stamp:=clock_timestamp();
 IF c.lease_expires_at<=stamp OR c.parent_deadline<=stamp OR b.valid_until<=stamp
  OR (p->>'valid_until')::timestamptz<=stamp
  OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,(p->'lease'->>'expires_at')::timestamptz,c.parent_deadline,b.valid_until,
   (p->'lease'->'profile'->>'bound_at')::timestamptz+
   (p->'lease'->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='523 phase deadline expired or extended'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_pack_phase(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_persistent_pack_journal_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=NEW.payload_json; parent record; proof record; phase record; header record; artifact record;
 private_header record;private_job record;private_control record;private_ref jsonb;private_lease jsonb;private_profile jsonb;fixed_slot jsonb;stamp timestamptz;
 slots text[]:=ARRAY['practice-1','practice-2','assessment-1','assessment-2','guided-remediation']; slot_index integer;
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_private_persistent_pack_journal' THEN
  PERFORM user_id FROM tutor_item_supply_user_epochs WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private epoch stale'; END IF;
  PERFORM id FROM tutor_item_supply_private_scopes WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private scope stale'; END IF;
  IF NEW.record_kind='task' THEN
   IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','slots','enhancement']) IS DISTINCT FROM true
    OR item_supply_internal.snapshot_keys(p->'ref',ARRAY['schema_version','pack_task_id','user_id','epoch','scope_id','mapping_receipt_id','demand_id','intent_hash','public_task_id']) IS DISTINCT FROM true
    OR p->>'schema_version' IS DISTINCT FROM 'persistent_pack_task_record_v1'
    OR p->'ref'->>'schema_version' IS DISTINCT FROM 'persistent_pack_task_ref_v1'
    OR NEW.id IS DISTINCT FROM NEW.pack_task_id OR (p->'ref'->>'pack_task_id')::uuid IS DISTINCT FROM NEW.id
    OR (p->'ref'->>'user_id')::uuid IS DISTINCT FROM NEW.user_id OR (p->'ref'->>'epoch')::integer IS DISTINCT FROM NEW.epoch
    OR (p->'ref'->>'scope_id')::uuid IS DISTINCT FROM NEW.scope_id OR p->'ref'->>'intent_hash' IS DISTINCT FROM NEW.intent_hash
    OR COALESCE(p->>'enhancement' IN('base_only','prefer_private'),false) IS DISTINCT FROM true
    OR jsonb_typeof(p->'slots') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'slots') IS DISTINCT FROM 5
   THEN RAISE check_violation USING MESSAGE='523 exact ONE private task five stable slots required'; END IF;
   SELECT * INTO header FROM tutor_item_supply_shared_persistent_pack_journal
    WHERE public_task_id=(p->'ref'->>'public_task_id')::uuid AND record_kind='task' FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private task public attachment missing'; END IF;
   FOR slot_index IN 0..4 LOOP
    IF item_supply_internal.snapshot_keys(p->'slots'->slot_index,ARRAY['schema_version','slot_id','logical_item_id','slot','public_slot_id']) IS DISTINCT FROM true
     OR p->'slots'->slot_index->>'schema_version' IS DISTINCT FROM 'persistent_pack_slot_ref_v1'
     OR p->'slots'->slot_index->>'slot' IS DISTINCT FROM slots[slot_index+1]
     OR p->'slots'->slot_index->'public_slot_id' IS DISTINCT FROM header.payload_json->'public_slots'->slot_index
     OR COALESCE(p->'slots'->slot_index->>'slot_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
     OR COALESCE(p->'slots'->slot_index->>'logical_item_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='523 exact private slot attachment required'; END IF;
   END LOOP;
   IF (SELECT count(DISTINCT s->>'slot_id') FROM jsonb_array_elements(p->'slots') s)<>5
    OR (SELECT count(DISTINCT s->>'logical_item_id') FROM jsonb_array_elements(p->'slots') s)<>5
   THEN RAISE check_violation USING MESSAGE='523 private slots must be unique'; END IF;
   PERFORM id FROM tutor_item_supply_finite_course_mappings m WHERE m.id=(p->'ref'->>'mapping_receipt_id')::uuid
    AND m.user_id=NEW.user_id AND m.epoch=NEW.epoch AND m.assessment_scope_id=NEW.scope_id
    AND (p->'ref'->>'demand_id')::uuid IN(m.practice_demand_id,m.assessment_demand_id,m.remediation_demand_id) FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 original confirmed mapping demand required'; END IF;
  ELSE
   PERFORM id FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id
    AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND intent_hash=NEW.intent_hash AND record_kind='task' FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private original task required'; END IF;
   IF NEW.record_kind='phase' THEN
    IF p->>'schema_version'='persistent_private_phase_attachment_v1' THEN
     IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','public_task_id']) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 private PUBLIC attachment schema required'; END IF;
     PERFORM id FROM tutor_item_supply_shared_persistent_pack_journal WHERE record_kind='phase'
      AND phase_id=(p->>'phase_id')::uuid AND public_task_id=(p->>'public_task_id')::uuid FOR SHARE;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private original PUBLIC phase required'; END IF;
    ELSIF p->>'schema_version'='private_native_phase_v1' THEN
     -- Exact A524 native PRIVATE phase DATA. Never a SHARED lease/attachment.
     IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','root_id','job_id','slot_id','business_item_id','goal_scope_id','ref','lease','valid_until']) IS DISTINCT FROM true
      OR item_supply_internal.snapshot_keys(p->'ref',ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
      OR item_supply_internal.snapshot_keys(p->'lease',ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 exact native PRIVATE phase schema required'; END IF;
     private_ref:=p->'ref';private_lease:=p->'lease';
     SELECT * INTO private_header FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id
      AND pack_task_id=id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND record_kind='task' FOR SHARE;
     IF NOT FOUND OR (private_ref->>'pack_task_id')::uuid IS DISTINCT FROM NEW.pack_task_id
      OR (private_ref->>'user_id')::uuid IS DISTINCT FROM NEW.user_id OR (private_ref->>'epoch')::bigint IS DISTINCT FROM NEW.epoch
      OR (private_ref->>'scope_id')::uuid IS DISTINCT FROM NEW.scope_id
      OR private_ref->>'mapping_receipt_id' IS DISTINCT FROM private_header.payload_json->'ref'->>'mapping_receipt_id'
      OR private_lease->>'visibility' IS DISTINCT FROM 'private' OR private_lease->>'owner_id' IS DISTINCT FROM private_ref->>'user_id'
      OR private_lease->'owner_epoch' IS DISTINCT FROM private_ref->'epoch' OR jsonb_typeof(private_ref->'epoch') IS DISTINCT FROM 'number'
      OR private_lease->>'job_id' IS DISTINCT FROM p->>'job_id' OR private_ref->>'root_id' IS DISTINCT FROM p->>'root_id'
      OR private_ref->>'slot_id' IS DISTINCT FROM p->>'slot_id' OR private_ref->>'business_item_id' IS DISTINCT FROM p->>'business_item_id'
      OR private_ref->>'goal_scope_id' IS DISTINCT FROM p->>'goal_scope_id'
      OR NEW.operation_key IS DISTINCT FROM ('private.phase.'||(p->>'job_id'))
      OR (private_ref->'parent_version_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(private_ref->'parent_version_id') IS DISTINCT FROM 'string'
       OR COALESCE(private_ref->>'parent_version_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true))
     THEN RAISE check_violation USING MESSAGE='523 exact native PRIVATE task owner/phase required'; END IF;
     SELECT s INTO fixed_slot FROM jsonb_array_elements(private_header.payload_json->'slots') s
      WHERE s->>'slot_id'=private_ref->>'slot_id' AND s->>'logical_item_id'=private_ref->>'business_item_id';
     IF fixed_slot IS NULL OR private_ref->>'slot' IS DISTINCT FROM
      (CASE WHEN fixed_slot->>'slot' IN('practice-1','practice-2') THEN 'practice'
       WHEN fixed_slot->>'slot' IN('assessment-1','assessment-2') THEN 'assessment' ELSE 'remediation' END)
     THEN RAISE check_violation USING MESSAGE='523 native PRIVATE fixed business slot/role required'; END IF;
     SELECT j.* INTO private_job FROM tutor_item_supply_private_jobs j WHERE j.id=(p->>'job_id')::uuid
      AND j.root_id=(p->>'root_id')::uuid AND j.user_id=NEW.user_id AND j.epoch=NEW.epoch AND j.scope_id=NEW.scope_id FOR SHARE;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 original native PRIVATE job required'; END IF;
     SELECT c.* INTO private_control FROM tutor_item_supply_private_job_controls c WHERE c.job_id=private_job.id
      AND c.user_id=NEW.user_id AND c.epoch=NEW.epoch AND c.scope_id=NEW.scope_id FOR SHARE;
     IF NOT FOUND OR private_control.state IS DISTINCT FROM 'leased'
      OR private_control.lease_owner IS DISTINCT FROM private_lease->>'lease_owner'
      OR private_control.lease_generation::text IS DISTINCT FROM private_lease->>'generation'
      OR COALESCE(private_control.state_version>=(private_lease->>'state_version')::bigint,false) IS DISTINCT FROM true
      OR private_control.parent_deadline IS DISTINCT FROM (private_lease->>'parent_deadline')::timestamptz
      OR (private_lease->>'expires_at')::timestamptz>private_control.lease_expires_at
      OR jsonb_typeof(private_lease->'generation') IS DISTINCT FROM 'number' OR jsonb_typeof(private_lease->'state_version') IS DISTINCT FROM 'number'
      OR COALESCE(private_lease->>'expires_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
      OR COALESCE(private_lease->>'parent_deadline' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
      OR COALESCE(p->>'valid_until' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 original current PRIVATE lease identity required'; END IF;
     private_profile:=CASE WHEN private_control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
      THEN private_control.profile_snapshot_json->'profile' ELSE private_control.profile_snapshot_json END;
     IF private_profile IS DISTINCT FROM private_lease->'profile'
      OR (CASE WHEN private_control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
        THEN private_control.profile_snapshot_json->'retry_policy' ELSE 'null'::jsonb END) IS DISTINCT FROM private_lease->'retry_policy'
     THEN RAISE check_violation USING MESSAGE='523 exact original PRIVATE profile/retry frame required'; END IF;
     PERFORM id FROM tutor_item_supply_private_budget_roots WHERE id=private_job.root_id AND user_id=NEW.user_id
      AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR SHARE;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 exact original PRIVATE root required'; END IF;
     SELECT * INTO parent FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=NEW.pack_task_id
      AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1 FOR SHARE;
     IF FOUND AND parent.payload_json->>'root_id' IS DISTINCT FROM p->>'root_id'
     THEN RAISE check_violation USING MESSAGE='523 native PRIVATE task canonical root fixed'; END IF;
     -- This is a real installed native mapping/source receiver, not storage existence.
     PERFORM item_supply_internal.private_native_mapping_current((private_ref->>'mapping_receipt_id')::uuid,NEW.user_id,NEW.epoch::bigint);
     PERFORM m.id FROM tutor_item_supply_finite_course_mappings m,
      LATERAL jsonb_array_elements(m.receipt_json->'pack_request'->'demands') d WHERE m.id=(private_ref->>'mapping_receipt_id')::uuid
      AND m.user_id=NEW.user_id AND m.epoch=NEW.epoch AND d->>'slot'=private_ref->>'slot'
      AND d->>'storage_scope_id'=private_ref->>'goal_scope_id' FOR SHARE OF m;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 native PRIVATE exact current role goal scope required'; END IF;
     stamp:=clock_timestamp();
     IF (p->>'valid_until')::timestamptz>LEAST(private_control.lease_expires_at,private_control.parent_deadline,
        (private_lease->>'expires_at')::timestamptz,(private_lease->>'parent_deadline')::timestamptz)
      OR (p->>'valid_until')::timestamptz>private_control.parent_deadline
      OR (p->>'valid_until')::timestamptz>(private_profile->>'bound_at')::timestamptz+
        (private_profile->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'
      OR COALESCE((p->>'valid_until')::timestamptz>stamp,false) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 native PRIVATE deadline/frame expired or extended'; END IF;
    ELSE
     RAISE check_violation USING MESSAGE='523 native PRIVATE phase protocol unsupported';
    END IF;
   ELSIF NEW.record_kind IN('pause','stop') THEN
    IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','reason']) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM 'persistent_private_stop_v1' OR p->>'reason' IS DISTINCT FROM 'user_stop'
    THEN RAISE check_violation USING MESSAGE='523 closed private stop required'; END IF;
   END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.record_kind='task' THEN
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_task_id','intent_hash','target_id','target_definition_hash','public_slots']) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM 'persistent_public_task_v1' OR (p->>'public_task_id')::uuid IS DISTINCT FROM NEW.public_task_id
   OR COALESCE(p->>'target_id' IN('python-kc-binding-v1','python-state-update-v1','sqlite-predicate-order-v1'),false) IS DISTINCT FROM true
   OR jsonb_typeof(p->'public_slots') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'public_slots') IS DISTINCT FROM 5
   OR COALESCE(p->>'intent_hash' ~ '^[0-9a-f]{64}$',false) IS DISTINCT FROM true
   OR COALESCE(p->>'target_definition_hash' ~ '^[0-9a-f]{64}$',false) IS DISTINCT FROM true
   OR NEW.root_id IS NOT NULL OR NEW.job_id IS NOT NULL OR NEW.phase_id IS NOT NULL
  THEN RAISE check_violation USING MESSAGE='523 closed public finite task required'; END IF;
  IF (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p->'public_slots'))<>5
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'public_slots') v WHERE jsonb_typeof(v) IS DISTINCT FROM 'string'
    OR COALESCE((v#>>'{}') ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true)
  THEN RAISE check_violation USING MESSAGE='523 five unique public slots required'; END IF;
 ELSE
  SELECT * INTO header FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=NEW.public_task_id AND record_kind='task' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 public original task required'; END IF;
  IF NEW.record_kind IN('version','qualified') THEN
   IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_task_id','public_slot_id','slot','revision_id','revision_seq','parent_revision_id','candidate_id','specification','root_id','artifact_id','published_version_id']) IS DISTINCT FROM true
    OR p->>'schema_version' IS DISTINCT FROM 'persistent_public_version_v1' OR (p->>'public_task_id')::uuid IS DISTINCT FROM NEW.public_task_id
    OR (p->>'root_id')::uuid IS DISTINCT FROM NEW.root_id OR NEW.root_id IS NULL OR NEW.job_id IS NOT NULL OR NEW.phase_id IS NOT NULL
    OR COALESCE(p->>'slot'=ANY(slots),false) IS DISTINCT FROM true
    OR COALESCE((p->>'revision_seq')::integer>=1,false) IS DISTINCT FROM true
    OR COALESCE(p->>'revision_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
    OR jsonb_typeof(p->'revision_seq') IS DISTINCT FROM 'number'
    OR item_supply_internal.snapshot_keys(p->'specification',ARRAY['schema_version','target_id','target_definition_hash','family_definition_hash','allocation','seed','blueprint','public_template','coverage_blueprint','python_goal','sql_target']) IS DISTINCT FROM true
   THEN RAISE check_violation USING MESSAGE='523 closed public version required'; END IF;
   slot_index:=array_position(slots,p->>'slot')-1;
   IF p->'public_slot_id' IS DISTINCT FROM header.payload_json->'public_slots'->slot_index
    OR p->'specification'->>'schema_version' IS DISTINCT FROM 'finite_candidate_spec_v1'
    OR p->'specification'->>'target_id' IS DISTINCT FROM header.payload_json->>'target_id'
    OR p->'specification'->>'target_definition_hash' IS DISTINCT FROM header.payload_json->>'target_definition_hash'
    -- A stable pack position is not a historical factory variant identity.
    -- Adopt an unchanged current member of the same original purpose role.
    OR p->'specification'->'allocation'->>'slot' IS DISTINCT FROM
      (CASE WHEN p->>'slot' IN('practice-1','practice-2') THEN 'practice'
       WHEN p->>'slot' IN('assessment-1','assessment-2') THEN 'assessment' ELSE 'remediation' END)
    OR p->'specification'->'coverage_blueprint'->'scope'->>'visibility' IS DISTINCT FROM 'public'
    OR p->'specification'->'coverage_blueprint'->'scope'->>'owner_ref' IS NOT NULL
   THEN RAISE check_violation USING MESSAGE='523 slot original public specification mismatch'; END IF;
   SELECT a.* INTO artifact FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=(p->>'artifact_id')::uuid
    AND a.root_id=NEW.root_id AND a.candidate_id=(p->>'candidate_id')::uuid FOR SHARE;
   IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(artifact.job_id) IS DISTINCT FROM false
    OR artifact.target_id IS DISTINCT FROM p->'specification'->>'target_id'
    OR artifact.target_definition_hash IS DISTINCT FROM p->'specification'->>'target_definition_hash'
    OR artifact.request_json->'blueprint' IS DISTINCT FROM p->'specification'->'blueprint'
    OR artifact.request_json->'public_template' IS DISTINCT FROM p->'specification'->'public_template'
    OR artifact.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'specification'->'coverage_blueprint'->'scope')
   THEN RAISE check_violation USING MESSAGE='523 genuine original candidate artifact specification required'; END IF;
   -- Entire nested specification must equal the original issued validation DATA,
   -- or (qualified adoption) its immutable publication's exact full-spec hash.
   IF NEW.record_kind='qualified' THEN
    SELECT n.* INTO proof FROM tutor_learning_item_native_publication_proofs n WHERE n.version_id=(p->>'published_version_id')::uuid
     AND n.generation_artifact_id=artifact.id AND n.proof_json->>'specification_hash'=item_supply_internal.snapshot_hash(p->'specification') FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 genuine full-spec original publication required'; END IF;
   ELSE
    IF p->>'published_version_id' IS NOT NULL THEN RAISE check_violation USING MESSAGE='523 unqualified version cannot declare publication'; END IF;
    PERFORM id FROM tutor_item_supply_shared_validation_preparations WHERE generation_artifact_id=artifact.id
     AND payload_json->'spec' IS NOT DISTINCT FROM p->'specification' FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 original full-spec validation preparation required'; END IF;
   END IF;
   IF (p->>'revision_seq')::integer>1 THEN
    SELECT payload_json INTO parent FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=NEW.public_task_id
     AND record_kind IN('version','qualified') AND payload_json->>'revision_id'=p->>'parent_revision_id' ORDER BY created_at DESC LIMIT 1 FOR SHARE;
    IF NOT FOUND OR parent.payload_json->>'public_slot_id' IS DISTINCT FROM p->>'public_slot_id'
     OR parent.payload_json->>'root_id' IS DISTINCT FROM p->>'root_id'
     OR (parent.payload_json->>'revision_seq')::integer+1 IS DISTINCT FROM (p->>'revision_seq')::integer
     OR parent.payload_json->'specification'->>'seed' IS DISTINCT FROM p->'specification'->>'seed'
     OR parent.payload_json->'specification'->'allocation' IS DISTINCT FROM p->'specification'->'allocation'
    THEN RAISE check_violation USING MESSAGE='523 immutable same-slot root lineage required'; END IF;
    PERFORM id FROM tutor_item_supply_shared_revision_preparations rp WHERE rp.candidate_id=artifact.candidate_id
     AND rp.child_job_id=artifact.job_id AND rp.parent_artifact_id=(parent.payload_json->>'artifact_id')::uuid FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 original same-item substantive revision required'; END IF;
   ELSIF p->>'parent_revision_id' IS NOT NULL OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal
    WHERE public_task_id=NEW.public_task_id AND record_kind IN('version','qualified') AND payload_json->>'public_slot_id'=p->>'public_slot_id'
     AND payload_json->>'revision_id' IS DISTINCT FROM p->>'revision_id') THEN
    RAISE check_violation USING MESSAGE='523 initial slot cannot be replaced';
   END IF;
  ELSIF NEW.record_kind='phase' THEN
   IF NEW.public_task_id IS DISTINCT FROM (p->>'public_task_id')::uuid OR NEW.phase_id IS DISTINCT FROM (p->>'phase_id')::uuid
    OR NEW.job_id IS DISTINCT FROM (p->>'job_id')::uuid OR NEW.root_id IS DISTINCT FROM (p->>'root_id')::uuid
    OR NEW.operation_key IS DISTINCT FROM p->>'operation_key'
   THEN RAISE check_violation USING MESSAGE='523 exact phase journal binding required'; END IF;
   PERFORM item_supply_internal.assert_persistent_pack_phase(p);
  ELSE
   SELECT * INTO phase FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=NEW.phase_id AND record_kind='phase' FOR SHARE;
   IF NOT FOUND OR phase.public_task_id IS DISTINCT FROM NEW.public_task_id OR phase.root_id IS DISTINCT FROM NEW.root_id OR phase.job_id IS DISTINCT FROM NEW.job_id
    THEN RAISE check_violation USING MESSAGE='523 stage original phase required'; END IF;
   IF NEW.record_kind='dispatch_started' THEN
    IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id']) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM 'persistent_dispatch_started_v1' OR (p->>'phase_id')::uuid IS DISTINCT FROM NEW.phase_id
     OR NEW.operation_key IS DISTINCT FROM phase.operation_key
    THEN RAISE check_violation USING MESSAGE='523 exact dispatch schema required'; END IF;
   ELSIF NEW.record_kind IN('stage_started','stage_result') THEN
    IF (CASE WHEN NEW.record_kind='stage_started' THEN item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','stage','operation_key'])
      ELSE item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','stage','operation_key','outcome','receipt_id','safe_reason']) END) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM (CASE WHEN NEW.record_kind='stage_started' THEN 'persistent_stage_started_v1' ELSE 'persistent_stage_result_v1' END)
     OR (p->>'phase_id')::uuid IS DISTINCT FROM NEW.phase_id OR p->>'operation_key' IS DISTINCT FROM NEW.operation_key
     OR COALESCE(p->>'stage' IN('author','validation','review','investigation','revision','recheck','facts','publication','relation'),false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='523 closed original stage required'; END IF;
    IF NEW.record_kind='stage_result' AND (
     COALESCE(p->>'outcome' IN('completed','qualified','failed','blocked','outcome_unknown'),false) IS DISTINCT FROM true
     OR COALESCE(p->>'safe_reason' ~ '^[a-z0-9_]{1,160}$',false) IS DISTINCT FROM true
     OR (p->'receipt_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(p->'receipt_id') IS DISTINCT FROM 'string'
      OR COALESCE(p->>'receipt_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true)))
    THEN RAISE check_violation USING MESSAGE='523 closed stage result scalar DATA required'; END IF;
   ELSIF NEW.record_kind='phase_result' THEN
    IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','status','safe_reason','artifact_id','published_version_id','relation_receipt_id','usage_state']) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM 'persistent_phase_outcome_v1' OR (p->>'phase_id')::uuid IS DISTINCT FROM NEW.phase_id
     OR NEW.operation_key IS DISTINCT FROM phase.operation_key
     OR COALESCE(p->>'status' IN('qualified','quality_failed','blocked','outcome_unknown','relation_ready'),false) IS DISTINCT FROM true
     OR COALESCE(p->>'safe_reason' ~ '^[a-z0-9_]{1,160}$',false) IS DISTINCT FROM true
     OR COALESCE(p->>'usage_state' IN('known','unknown'),false) IS DISTINCT FROM true
     OR p->'relation_receipt_id' IS DISTINCT FROM 'null'::jsonb
     OR (p->'artifact_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(p->'artifact_id') IS DISTINCT FROM 'string'
      OR COALESCE(p->>'artifact_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true))
     OR (p->'published_version_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(p->'published_version_id') IS DISTINCT FROM 'string'
      OR COALESCE(p->>'published_version_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true))
    THEN RAISE check_violation USING MESSAGE='523 closed original outcome required'; END IF;
   END IF;
   IF NEW.record_kind IN('dispatch_started','stage_started') THEN
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase.payload_json);
    IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=NEW.phase_id AND record_kind='phase_result')
    THEN RAISE check_violation USING MESSAGE='523 terminal phase cannot dispatch'; END IF;
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_persistent_pack_journal_insert() FROM PUBLIC;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tutor_item_supply_shared_persistent_pack_journal','tutor_item_supply_private_persistent_pack_journal'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS persistent_journal_insert ON %I',t);
 EXECUTE format('DROP TRIGGER IF EXISTS persistent_journal_immutable ON %I',t);
 EXECUTE format('CREATE TRIGGER persistent_journal_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_persistent_pack_journal_insert()',t);
 EXECUTE format('CREATE TRIGGER persistent_journal_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(%L)',t,CASE WHEN t LIKE '%_private_%' THEN 'private' ELSE 'shared' END);
 END LOOP; END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.purge_persistent_pack_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch<>OLD.epoch+1
  OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='523 original permitted epoch advance required'; END IF;
 -- SQL524 PRIVATE evidence/attachments must purge BEFORE this header trigger.
 DELETE FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=NEW.user_id AND record_kind<>'task';
 DELETE FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=NEW.user_id AND record_kind='task';
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_persistent_pack_on_epoch_advance() FROM PUBLIC;
DROP TRIGGER IF EXISTS a00z_persistent_pack_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a00z_persistent_pack_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN(NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION item_supply_internal.purge_persistent_pack_on_epoch_advance();

CREATE OR REPLACE FUNCTION item_supply_internal.persistent_relation_anchor_matches(p jsonb, anchor uuid, exact_root uuid, exact_job uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE phase record; candidate jsonb;
BEGIN
 IF p->>'kind' IS DISTINCT FROM 'relation_pack' OR (p->>'anchor_version_id')::uuid IS DISTINCT FROM anchor
  OR (p->>'root_id')::uuid IS DISTINCT FROM exact_root OR (p->>'job_id')::uuid IS DISTINCT FROM exact_job
  OR jsonb_array_length(p->'candidate_version_ids')<>5
 THEN RETURN false; END IF;
 SELECT * INTO phase FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=(p->>'phase_id')::uuid
  AND record_kind='phase' AND public_task_id=(p->>'public_task_id')::uuid FOR SHARE;
 IF NOT FOUND OR phase.payload_json IS DISTINCT FROM p THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_persistent_pack_phase(p);
 FOR candidate IN SELECT value FROM jsonb_array_elements(p->'candidate_version_ids') LOOP
  PERFORM 1 FROM tutor_item_supply_shared_persistent_pack_journal q
   JOIN tutor_learning_item_native_publication_proofs n ON n.version_id=(q.payload_json->>'published_version_id')::uuid
   JOIN tutor_item_supply_shared_generation_artifacts a ON a.id=n.generation_artifact_id
   WHERE q.record_kind='qualified' AND q.public_task_id=phase.public_task_id
    AND q.payload_json->>'published_version_id'=candidate#>>'{}'
    AND item_supply_internal.controlled_counterexample_held(a.job_id)=false
    AND EXISTS(SELECT 1 FROM tutor_learning_item_publication_events e WHERE e.version_id=n.version_id
     AND e.state='published' AND NOT EXISTS(SELECT 1 FROM tutor_learning_item_publication_events later
       WHERE later.version_id=e.version_id AND later.state_version>e.state_version));
  IF NOT FOUND THEN RETURN false; END IF;
 END LOOP;
 PERFORM 1 FROM tutor_learning_item_native_publication_proofs n
  JOIN tutor_item_supply_shared_generation_artifacts a ON a.id=n.generation_artifact_id
  WHERE n.version_id=anchor AND a.root_id=exact_root AND item_supply_internal.controlled_counterexample_held(a.job_id)=false;
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.persistent_relation_anchor_matches(jsonb,uuid,uuid,uuid) FROM PUBLIC;

-- Minimal closed original501/520 anchor branch. All old guards/attributes retained.
DO $anchor523$
DECLARE actual record; verified record; source text; revised text; definition text;
 old_sha constant text:='204c682ae3e58565e25f9f8099500f7a96f67ddc59b5fc08229bb404f1b0927b';
 new_sha constant text:='55c745fb1cfef2ff22dd9db4b95252a58771f3d942901f04549e654ba735c2af';
 old_anchor constant text:=$old_anchor$     WHERE n.version_id=NEW.anchor_version_id AND n.proof_json->'lease'=p->'lease'
       AND (n.proof_json->'lease'->>'job_id')::uuid=NEW.job_id;$old_anchor$;
 new_anchor constant text:=$new_anchor$     WHERE n.version_id=NEW.anchor_version_id AND (
       (n.proof_json->'lease'=p->'lease' AND (n.proof_json->'lease'->>'job_id')::uuid=NEW.job_id)
       OR (p ? 'persistent_phase' AND p->'persistent_phase'->'lease'=p->'lease'
         AND item_supply_internal.persistent_relation_anchor_matches(p->'persistent_phase',NEW.anchor_version_id,NEW.root_id,NEW.job_id)));$new_anchor$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('public.enforce_native_type_evidence_insert()');
 IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql' OR actual.pronargs<>0
  OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset OR actual.proisstrict
  OR NOT actual.prosecdef OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
 THEN RAISE check_violation USING MESSAGE='523 original native receiver attributes changed'; END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR (length(source)-length(replace(source,old_anchor,'')))/length(old_anchor)<>1
 THEN RAISE check_violation USING MESSAGE='523 unknown original relation receiver source'; END IF;
 revised:=replace(source,old_anchor,new_anchor);
 IF encode(sha256(convert_to(revised,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='523 unexpected native anchor source'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1
 THEN RAISE check_violation USING MESSAGE='523 native receiver framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,revised);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='523 native receiver attributes not preserved'; END IF;
END $anchor523$;
