-- C24: select an actual 551 job's bound phase window, not all overlapping root windows.
-- Frozen <=567 untouched. One exact prosrc patch; no new objects/API/readiness patches.
-- Ordinary unmapped phases retain exact-one; no old window/lease/usage is modified.
DO $patch568$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old568$
DECLARE t record;j record;c record;o record;prior record;s jsonb;r jsonb:=p->'ref';l jsonb:=p->'lease';m jsonb;
 frozen jsonb;retry jsonb;deadline timestamptz;stamp timestamptz;role text;windows integer;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','root_id','job_id','slot_id','business_item_id','goal_scope_id','ref','lease','valid_until']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(r,ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(l,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_phase_v1'
  OR jsonb_typeof(r) IS DISTINCT FROM 'object' OR jsonb_typeof(l) IS DISTINCT FROM 'object'
  OR (r->>'pack_task_id',r->>'user_id',r->>'epoch',r->>'scope_id') IS DISTINCT FROM (task::text,u::text,e::text,scope::text)
  OR (p->>'root_id',p->>'job_id',p->>'slot_id',p->>'business_item_id',p->>'goal_scope_id')
   IS DISTINCT FROM (r->>'root_id',l->>'job_id',r->>'slot_id',r->>'business_item_id',r->>'goal_scope_id')
  OR (l->>'visibility',l->>'owner_id',l->>'owner_epoch') IS DISTINCT FROM ('private',u::text,e::text) THEN
  RAISE check_violation USING MESSAGE='524 exact PRIVATE phase schema/frame/namespace required'; END IF;
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task
  AND record_kind='task' AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 SELECT value INTO s FROM jsonb_array_elements(t.payload_json->'slots') WHERE value->>'slot_id'=r->>'slot_id'
  AND value->>'logical_item_id'=r->>'business_item_id';
 role:=CASE WHEN s->>'slot' IN('practice-1','practice-2') THEN 'practice'
  WHEN s->>'slot' IN('assessment-1','assessment-2') THEN 'assessment'
  WHEN s->>'slot'='guided-remediation' THEN 'remediation' END;
 IF t.id IS NULL OR s IS NULL OR role IS NULL OR role IS DISTINCT FROM r->>'slot'
  OR item_supply_internal.private_native_task_enhancement(task,u,e,scope) IS DISTINCT FROM true
  OR t.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM r->>'mapping_receipt_id' THEN
  RAISE check_violation USING MESSAGE='524 actual fixed PRIVATE task/business role required'; END IF;
 m:=item_supply_internal.private_native_mapping_current((r->>'mapping_receipt_id')::uuid,u,e);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_finite_course_mappings x,
  LATERAL jsonb_array_elements(x.receipt_json->'pack_request'->'demands') d WHERE x.id=(r->>'mapping_receipt_id')::uuid
  AND x.user_id=u AND x.epoch=e AND x.assessment_scope_id=scope AND d->>'slot'=role
  AND d->>'storage_scope_id'=r->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 real goal_scope distinct from assessment storage required'; END IF;
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=(l->>'job_id')::uuid AND user_id=u AND epoch=e
  AND scope_id=scope AND root_id=(r->>'root_id')::uuid FOR SHARE;
 SELECT * INTO o FROM tutor_item_supply_private_obligations WHERE root_id=j.root_id AND user_id=u AND epoch=e AND scope_id=scope;
 SELECT * INTO c FROM tutor_item_supply_private_job_controls WHERE job_id=j.id AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 frozen:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 retry:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'retry_policy' ELSE 'null'::jsonb END;
 deadline:=LEAST(c.lease_expires_at,c.parent_deadline,(frozen->>'bound_at')::timestamptz+
  (frozen->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF j.id IS NULL OR o.root_id IS NULL OR c.state IS DISTINCT FROM 'leased'
  OR (l->>'lease_owner',l->>'generation',l->>'state_version')
   IS DISTINCT FROM (c.lease_owner,c.lease_generation::text,c.state_version::text)
  OR (l->>'expires_at')::timestamptz IS DISTINCT FROM c.lease_expires_at
  OR (l->>'parent_deadline')::timestamptz IS DISTINCT FROM c.parent_deadline
  OR l->'profile' IS DISTINCT FROM frozen OR l->'retry_policy' IS DISTINCT FROM retry
  OR (p->>'valid_until')::timestamptz IS DISTINCT FROM deadline THEN
  RAISE check_violation USING MESSAGE='524 original PRIVATE issuer control/profile/finite deadline required'; END IF;
 SELECT * INTO prior FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=task AND user_id=u AND epoch=e
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1;
 IF prior.id IS NOT NULL AND prior.payload_json->>'root_id' IS DISTINCT FROM r->>'root_id' THEN
  RAISE check_violation USING MESSAGE='524 fixed PRIVATE canonical root required'; END IF;
 stamp:=clock_timestamp();
 SELECT count(*) INTO windows FROM tutor_item_supply_private_budget_windows w WHERE w.root_id=j.root_id AND w.user_id=u AND w.epoch=e
  AND w.scope_id=scope AND w.pool_key=o.pool_class AND w.provider_key=o.provider_key AND w.window_start<=stamp AND w.window_end>=deadline;
 IF windows<>1 OR deadline IS NULL OR stamp>=deadline THEN
  RAISE check_violation USING MESSAGE='524 current original PRIVATE resource window required after locks'; END IF;
END $old568$;
 new_body constant text := $new568$
DECLARE t record;j record;c record;o record;prior record;s jsonb;r jsonb:=p->'ref';l jsonb:=p->'lease';m jsonb;
 frozen jsonb;retry jsonb;deadline timestamptz;stamp timestamptz;role text;windows integer;
 dev_job public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 dev_batch public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','root_id','job_id','slot_id','business_item_id','goal_scope_id','ref','lease','valid_until']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(r,ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(l,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_phase_v1'
  OR jsonb_typeof(r) IS DISTINCT FROM 'object' OR jsonb_typeof(l) IS DISTINCT FROM 'object'
  OR (r->>'pack_task_id',r->>'user_id',r->>'epoch',r->>'scope_id') IS DISTINCT FROM (task::text,u::text,e::text,scope::text)
  OR (p->>'root_id',p->>'job_id',p->>'slot_id',p->>'business_item_id',p->>'goal_scope_id')
   IS DISTINCT FROM (r->>'root_id',l->>'job_id',r->>'slot_id',r->>'business_item_id',r->>'goal_scope_id')
  OR (l->>'visibility',l->>'owner_id',l->>'owner_epoch') IS DISTINCT FROM ('private',u::text,e::text) THEN
  RAISE check_violation USING MESSAGE='524 exact PRIVATE phase schema/frame/namespace required'; END IF;
 -- A locator is not permission: only an actual immutable 551 mapping selects this branch.
 SELECT aj.* INTO dev_job FROM tutor_item_supply_private_development_model_accounting_jobs aj WHERE aj.job_id=(l->>'job_id')::uuid;
 IF dev_job.id IS NOT NULL THEN
  SELECT bd.* INTO dev_batch FROM tutor_item_supply_private_development_model_accounting_batches bd WHERE bd.id=dev_job.batch_id;
  IF dev_batch.id IS NULL OR (dev_job.job_id,dev_job.user_id,dev_job.epoch,dev_job.scope_id,dev_job.root_id,dev_job.window_id) IS DISTINCT FROM
   ((l->>'job_id')::uuid,u,e,scope,(r->>'root_id')::uuid,dev_batch.window_id)
   OR (dev_batch.user_id,dev_batch.epoch,dev_batch.scope_id,dev_batch.root_id) IS DISTINCT FROM (u,e,scope,(r->>'root_id')::uuid) THEN
   RAISE check_violation USING MESSAGE='568 exact current job-bound development accounting phase required'; END IF;
  -- Original 551 user/epoch/scope/active-plan locks precede original task/job/control locks.
  PERFORM item_supply_internal.private_development_accounting_batch_current(dev_batch);
 END IF;
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task
  AND record_kind='task' AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 SELECT value INTO s FROM jsonb_array_elements(t.payload_json->'slots') WHERE value->>'slot_id'=r->>'slot_id'
  AND value->>'logical_item_id'=r->>'business_item_id';
 role:=CASE WHEN s->>'slot' IN('practice-1','practice-2') THEN 'practice'
  WHEN s->>'slot' IN('assessment-1','assessment-2') THEN 'assessment'
  WHEN s->>'slot'='guided-remediation' THEN 'remediation' END;
 IF t.id IS NULL OR s IS NULL OR role IS NULL OR role IS DISTINCT FROM r->>'slot'
  OR item_supply_internal.private_native_task_enhancement(task,u,e,scope) IS DISTINCT FROM true
  OR t.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM r->>'mapping_receipt_id' THEN
  RAISE check_violation USING MESSAGE='524 actual fixed PRIVATE task/business role required'; END IF;
 m:=item_supply_internal.private_native_mapping_current((r->>'mapping_receipt_id')::uuid,u,e);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_finite_course_mappings x,
  LATERAL jsonb_array_elements(x.receipt_json->'pack_request'->'demands') d WHERE x.id=(r->>'mapping_receipt_id')::uuid
  AND x.user_id=u AND x.epoch=e AND x.assessment_scope_id=scope AND d->>'slot'=role
  AND d->>'storage_scope_id'=r->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 real goal_scope distinct from assessment storage required'; END IF;
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=(l->>'job_id')::uuid AND user_id=u AND epoch=e
  AND scope_id=scope AND root_id=(r->>'root_id')::uuid FOR SHARE;
 SELECT * INTO o FROM tutor_item_supply_private_obligations WHERE root_id=j.root_id AND user_id=u AND epoch=e AND scope_id=scope;
 SELECT * INTO c FROM tutor_item_supply_private_job_controls WHERE job_id=j.id AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 frozen:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 retry:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'retry_policy' ELSE 'null'::jsonb END;
 deadline:=LEAST(c.lease_expires_at,c.parent_deadline,(frozen->>'bound_at')::timestamptz+
  (frozen->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF j.id IS NULL OR o.root_id IS NULL OR c.state IS DISTINCT FROM 'leased'
  OR (l->>'lease_owner',l->>'generation',l->>'state_version')
   IS DISTINCT FROM (c.lease_owner,c.lease_generation::text,c.state_version::text)
  OR (l->>'expires_at')::timestamptz IS DISTINCT FROM c.lease_expires_at
  OR (l->>'parent_deadline')::timestamptz IS DISTINCT FROM c.parent_deadline
  OR l->'profile' IS DISTINCT FROM frozen OR l->'retry_policy' IS DISTINCT FROM retry
  OR (p->>'valid_until')::timestamptz IS DISTINCT FROM deadline THEN
  RAISE check_violation USING MESSAGE='524 original PRIVATE issuer control/profile/finite deadline required'; END IF;
 SELECT * INTO prior FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=task AND user_id=u AND epoch=e
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1;
 IF prior.id IS NOT NULL AND prior.payload_json->>'root_id' IS DISTINCT FROM r->>'root_id' THEN
  RAISE check_violation USING MESSAGE='524 fixed PRIVATE canonical root required'; END IF;
 IF dev_job.id IS NOT NULL THEN
  IF dev_job.parent_job_id IS DISTINCT FROM j.parent_job_id OR dev_job.lease_generation IS DISTINCT FROM c.lease_generation
   OR dev_job.lease_owner IS DISTINCT FROM c.lease_owner OR dev_job.profile_hash IS DISTINCT FROM frozen->>'profile_hash'
   OR dev_job.parent_deadline IS DISTINCT FROM c.parent_deadline OR c.parent_deadline>dev_batch.valid_until
   OR dev_job.lease_state_version<=0 OR dev_job.lease_state_version>c.state_version
   OR c.lease_generation<>1 OR c.attempt_count<>1 OR c.breaker_open IS DISTINCT FROM false THEN
   RAISE check_violation USING MESSAGE='568 exact current job-bound development accounting phase required'; END IF;
  PERFORM item_supply_internal.private_development_accounting_batch_current(dev_batch);
 END IF;
 stamp:=clock_timestamp();
 IF dev_job.id IS NOT NULL THEN
  SELECT count(*) INTO windows FROM tutor_item_supply_private_budget_windows w WHERE w.root_id=j.root_id AND w.user_id=u AND w.epoch=e
   AND w.scope_id=scope AND w.pool_key=o.pool_class AND w.provider_key=o.provider_key AND w.id=dev_job.window_id
   AND w.window_start<=stamp AND w.window_end>=deadline;
 ELSE
 SELECT count(*) INTO windows FROM tutor_item_supply_private_budget_windows w WHERE w.root_id=j.root_id AND w.user_id=u AND w.epoch=e
  AND w.scope_id=scope AND w.pool_key=o.pool_class AND w.provider_key=o.provider_key AND w.window_start<=stamp AND w.window_end>=deadline;
 END IF;
 IF windows<>1 OR deadline IS NULL OR stamp>=deadline THEN
  RAISE check_violation USING MESSAGE='524 current original PRIVATE resource window required after locks'; END IF;
END $new568$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='568 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.assert_private_native_phase(jsonb,uuid,bigint,uuid,uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'assert_private_native_phase' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype
  OR actual.pronargs<>5 OR actual.proargtypes IS DISTINCT FROM '3802 2950 20 2950 2950'::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['p','u','e','scope','task']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='568 original private phase identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='568 original private phase body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='568 original private phase definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='568 private phase metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch568$;
