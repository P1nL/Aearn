-- Fixed synthetic storage graph only. Never install this fragment in runtime databases.
SET LOCAL search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp;
DO $validation_scope$
BEGIN
 IF current_database()<>'aearn_completion_b_validation_20261027' OR NOT(SELECT rolsuper FROM pg_roles WHERE rolname=session_user)
  OR NOT EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() i JOIN pg_database d
   ON d.oid=i.database_oid AND d.datname=i.database_name
   WHERE d.datname=current_database() AND i.contract_id='completion_non_b1d_v1' AND i.purpose='storage-validation-purpose')
 THEN RAISE EXCEPTION 'completion baseline: validation installation scope denied' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='completion_baseline_internal' AND p.proname IN('assert_validation_caller','issue_private_graph','issue_journal_graph','validation_scope','validation_source_allowed','issue_native_binding_graph','issue_shared_subscription_graph','issue_actual_d_tail_graph'))
 THEN RAISE EXCEPTION 'completion baseline: unknown partial validation receiver' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aearn_cb_verifier_20261027' AND rolcanlogin AND NOT rolsuper
   AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit
   AND shobj_description(oid,'pg_authid')='completion_non_b1d_v1 managed role')
  OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='aearn_cb_verifier_20261027')
   OR member=(SELECT oid FROM pg_roles WHERE rolname='aearn_cb_verifier_20261027'))
 THEN RAISE EXCEPTION 'completion baseline: protected verifier role changed' USING ERRCODE='42501'; END IF;
END $validation_scope$;
CREATE FUNCTION completion_baseline_internal.assert_validation_caller() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,completion_baseline_internal,pg_temp AS $$
BEGIN
 IF session_user<>'aearn_cb_verifier_20261027' OR current_setting('role') NOT IN('none','aearn_cb_verifier_20261027')
  OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=session_user AND rolcanlogin AND NOT rolsuper
   AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit)
  OR NOT EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() WHERE purpose='storage-validation-purpose'
   AND database_name='aearn_completion_b_validation_20261027')
 THEN RAISE EXCEPTION 'completion baseline: real verifier login in the bound validation database required' USING ERRCODE='42501'; END IF;
END $$;
CREATE FUNCTION completion_baseline_internal.issue_private_graph(
 user_id uuid,track_id uuid,revision_id uuid,knowledge_key text)
RETURNS TABLE(scope_id uuid,material_id uuid,parent_candidate_id uuid,child_candidate_id uuid,version_id uuid,shared_matrix_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE u alias for $1; tr alias for $2; rev alias for $3; kc alias for $4;
 e bigint; facts jsonb; contract jsonb; matrix jsonb; scope_hash_value text; matrix_hash_value text;
 sid uuid:=gen_random_uuid(); mid uuid:=gen_random_uuid(); parent uuid:=gen_random_uuid(); child uuid:=gen_random_uuid(); v uuid:=gen_random_uuid(); matrix_id uuid;
BEGIN
 PERFORM completion_baseline_internal.assert_validation_caller();
 PERFORM 1 FROM users x WHERE x.id=u AND x.deleted_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'completion validation: active original user required' USING ERRCODE='23514'; END IF;
 SELECT x.epoch INTO e FROM tutor_item_supply_user_epochs x WHERE x.user_id=u AND x.enabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'completion validation: real current user epoch required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM tutor_track_active_plans p WHERE p.track_id=tr AND p.user_id=u AND p.revision_id=rev FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'completion validation: original active plan required' USING ERRCODE='23514'; END IF;
 SELECT jsonb_build_object('id',n.id::text,'title',n.title,'description',n.description,
   'required_capabilities_json',n.required_capabilities_json,'prerequisite_keys_json',n.prerequisite_keys_json,'language_id',t.language_id)
 INTO facts FROM tutor_track_plan_nodes n JOIN tutor_learning_tracks t ON t.id=n.track_id AND t.user_id=n.user_id
 WHERE n.user_id=u AND n.track_id=tr AND n.revision_id=rev AND n.knowledge_key=kc FOR SHARE OF n,t;
 IF facts IS NULL OR EXISTS(SELECT 1 FROM tutor_item_supply_private_scopes s WHERE s.user_id=u AND s.epoch=e) THEN
  RAISE EXCEPTION 'completion validation: exact original node and unused fixed graph namespace required' USING ERRCODE='23514'; END IF;
 contract:=jsonb_build_object('schema_version','supply_scope_v1','course_family','completion-storage-validation',
  'course_version','1','knowledge_key',kc,'language_id',facts->>'language_id','subject_id','storage-validation-only',
  'subject_version','1','required_facets','[]'::jsonb,'dialect',NULL,'runtime_profile_id','storage-validation-only',
  'runtime_profile_hash',repeat('0',64),'item_kind','code','purpose','exercise','interaction','edit',
  'required_capabilities','[]'::jsonb,'assessment_contract_version','storage-validation-only',
  'scorer_version','storage-validation-only','assistance_policy_hash',repeat('0',64),'visibility','private','owner_ref','user:'||u::text);
 scope_hash_value:=item_supply_internal.snapshot_hash(jsonb_build_object('contract',contract,'track_id',tr::text,'revision_id',rev::text,'node_id',facts->>'id'));
 INSERT INTO completion_baseline_internal.validation_permits(transaction_id,user_id,scope_id) VALUES(txid_current(),u,sid);
 INSERT INTO tutor_item_supply_private_scopes(id,user_id,epoch,track_id,revision_id,knowledge_key,scope_hash,objective_hash,snapshot_json)
  VALUES(sid,u,e,tr,rev,kc,scope_hash_value,item_supply_internal.snapshot_hash(facts),contract);
 INSERT INTO tutor_item_supply_private_materials(id,user_id,epoch,scope_id,material_key,content_text)
  VALUES(mid,u,e,sid,'completion.validation.material','Synthetic storage only. No source, quality, usage, admission, publication or consumer authority.');
 INSERT INTO tutor_item_supply_private_candidates(id,user_id,epoch,scope_id,material_id,candidate_key)
  VALUES(parent,u,e,sid,mid,'completion.validation.parent');
 INSERT INTO tutor_item_supply_private_candidates(id,user_id,epoch,scope_id,material_id,candidate_key,parent_candidate_id)
  VALUES(child,u,e,sid,mid,'completion.validation.child',parent);
 INSERT INTO tutor_item_supply_private_versions(id,user_id,epoch,scope_id,candidate_id,version,public_json,private_json)
  VALUES(v,u,e,sid,child,1,
   jsonb_build_object('schema_version','learning_item_public_v1','storage_validation',true,'not_business_eligible',true),
   jsonb_build_object('schema_version','learning_item_private_v1','storage_validation',true,'not_business_eligible',true));
 matrix:=jsonb_build_object('version','item_supply_support_matrix_v1','authority','declaration_only',
  'gate_metadata_status','separate_p0_snapshot','runtime_readiness','not_evaluated','source_readiness','not_evaluated',
  'inventory_readiness','not_evaluated','languages','[]'::jsonb,'public_course_languages','[]'::jsonb,
  'item_kinds','[]'::jsonb,'item_purposes','[]'::jsonb,'interactions','[]'::jsonb,'first_batch_slices','[]'::jsonb);
 matrix_hash_value:=item_supply_internal.snapshot_hash(matrix);
 INSERT INTO tutor_item_supply_shared_matrices(matrix_hash,snapshot_json) VALUES(matrix_hash_value,matrix) ON CONFLICT(matrix_hash) DO NOTHING;
 SELECT m.id INTO matrix_id FROM tutor_item_supply_shared_matrices m WHERE m.matrix_hash=matrix_hash_value;
 DELETE FROM completion_baseline_internal.validation_permits p WHERE p.transaction_id=txid_current() AND p.user_id=u AND p.scope_id=sid;
 RETURN QUERY SELECT sid,mid,parent,child,v,matrix_id;
END $$;
CREATE FUNCTION completion_baseline_internal.issue_journal_graph(scope_id uuid)
RETURNS TABLE(task_id uuid,attachment_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE sid alias for $1; s public.tutor_item_supply_private_scopes%ROWTYPE; task uuid:=gen_random_uuid(); child uuid:=gen_random_uuid(); p jsonb; h text;
BEGIN
 PERFORM completion_baseline_internal.assert_validation_caller();
 SELECT x.* INTO s FROM tutor_item_supply_private_scopes x WHERE x.id=sid FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_materials m WHERE m.scope_id=s.id AND m.user_id=s.user_id AND m.epoch=s.epoch
  AND m.material_key='completion.validation.material' AND m.content_text='Synthetic storage only. No source, quality, usage, admission, publication or consumer authority.')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.scope_id=s.id AND j.user_id=s.user_id AND j.epoch=s.epoch) THEN
  RAISE EXCEPTION 'completion validation: fixed private graph and unused journal namespace required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM users WHERE id=s.user_id AND deleted_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'completion validation: active original owner required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM tutor_item_supply_user_epochs WHERE user_id=s.user_id AND epoch=s.epoch AND enabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'completion validation: stale graph epoch' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM tutor_track_active_plans WHERE track_id=s.track_id AND user_id=s.user_id AND revision_id=s.revision_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'completion validation: stale graph plan' USING ERRCODE='23514'; END IF;
 p:=jsonb_build_object('schema_version','completion_storage_validation_v1','storage_validation',true,'not_business_eligible',true);
 h:=item_supply_internal.snapshot_hash(p);
 INSERT INTO completion_baseline_internal.validation_permits(transaction_id,user_id,scope_id) VALUES(txid_current(),s.user_id,s.id);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
  VALUES(task,task,s.user_id,s.epoch,s.id,'task','completion.validation.task',h,p);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
  VALUES(child,task,s.user_id,s.epoch,s.id,'private_attachment','completion.validation.attachment',h,p);
 DELETE FROM completion_baseline_internal.validation_permits x WHERE x.transaction_id=txid_current() AND x.user_id=s.user_id AND x.scope_id=s.id;
 RETURN QUERY SELECT task,child;
END $$;

ALTER FUNCTION completion_baseline_internal.assert_validation_caller() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.assert_validation_caller() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION completion_baseline_internal.issue_private_graph(uuid,uuid,uuid,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.issue_private_graph(uuid,uuid,uuid,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
GRANT EXECUTE ON FUNCTION completion_baseline_internal.issue_private_graph(uuid,uuid,uuid,text) TO aearn_cb_verifier_20261027;

ALTER FUNCTION completion_baseline_internal.issue_journal_graph(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.issue_journal_graph(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
GRANT EXECUTE ON FUNCTION completion_baseline_internal.issue_journal_graph(uuid) TO aearn_cb_verifier_20261027;

CREATE FUNCTION completion_baseline_internal.issue_shared_subscription_graph(first_scope_id uuid,second_scope_id uuid)
RETURNS TABLE(shared_job_id uuid,first_subscription_id uuid,second_subscription_id uuid,known_usage_id uuid,unknown_usage_id uuid,reservation_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE a public.tutor_item_supply_private_scopes%ROWTYPE; b public.tutor_item_supply_private_scopes%ROWTYPE;
 x public.tutor_item_supply_private_scopes%ROWTYPE; blueprint uuid:=gen_random_uuid(); root uuid:=gen_random_uuid();
 win uuid:=gen_random_uuid(); job uuid:=gen_random_uuid(); reservation uuid:=gen_random_uuid();
 known_id uuid:=gen_random_uuid(); unknown_id uuid:=gen_random_uuid(); d uuid; sub uuid; scope uuid;
 first_sub uuid; second_sub uuid; p jsonb; h text; matrix text;
BEGIN
 IF $1 IS NULL OR $2 IS NULL OR $1=$2 THEN RAISE EXCEPTION '600: two distinct scopes required' USING ERRCODE='23514'; END IF;
 IF $1<$2 THEN a:=completion_baseline_internal.validation_scope($1); b:=completion_baseline_internal.validation_scope($2);
 ELSE b:=completion_baseline_internal.validation_scope($2); a:=completion_baseline_internal.validation_scope($1); END IF;
 IF a.user_id=b.user_id THEN RAISE EXCEPTION '600: two distinct active owners required' USING ERRCODE='23514'; END IF;
 INSERT INTO completion_baseline_internal.validation_permits VALUES(txid_current(),a.user_id,a.id);
 p:=jsonb_build_object('schema_version','autonomous_evidence_policy_v2','policy_version','autonomous_evidence_policy_v2',
  'publication_enabled',false,'required_review_roles',jsonb_build_array('curriculum','difficulty','technical','ambiguity','security','adversarial'),
  'risk_adapter_required',true,'independent_second_bundle_required',true);
 h:=item_supply_internal.snapshot_hash(p);
 INSERT INTO tutor_item_supply_shared_policies(policy_version,policy_hash,policy_json)
  VALUES('autonomous_evidence_policy_v2',h,p) ON CONFLICT(policy_version) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_policies WHERE policy_version='autonomous_evidence_policy_v2'
  AND policy_hash=h AND policy_json=p) THEN RAISE EXCEPTION '600: synthetic policy namespace occupied' USING ERRCODE='23514'; END IF;
 SELECT matrix_hash INTO matrix FROM tutor_item_supply_shared_matrices WHERE snapshot_json->>'authority'='declaration_only'
  AND snapshot_json->'languages'='[]'::jsonb ORDER BY id LIMIT 1;
 IF matrix IS NULL THEN RAISE EXCEPTION '600: original validation matrix required' USING ERRCODE='23514'; END IF;
 h:=item_supply_internal.snapshot_hash(jsonb_build_object('synthetic_blueprint',blueprint));
 p:=jsonb_build_object('schema_version','coverage_blueprint_v1',
  'scope',a.snapshot_json||jsonb_build_object('visibility','public','owner_ref',NULL,'course_family','completion-storage-validation','course_version',blueprint::text),
  'objective_hash',h,'matrix_hash',matrix,'policy_version','autonomous_evidence_policy_v2','clauses','[]'::jsonb,
  'minimum',jsonb_build_object('policy_version','autonomous_evidence_policy_v2','practice',0,'assessment',0,'remediation',0));
 INSERT INTO tutor_item_supply_shared_blueprints(id,blueprint_hash,objective_hash,matrix_hash,policy_version,snapshot_json)
  VALUES(blueprint,item_supply_internal.snapshot_hash(p),h,matrix,'autonomous_evidence_policy_v2',p);
 INSERT INTO tutor_item_supply_shared_budget_roots(id,blueprint_id,canonical_key,policy_class)
  VALUES(root,blueprint,h,'completion.validation.synthetic');
 INSERT INTO tutor_item_supply_shared_budget_windows(id,root_id,pool_key,provider_key,window_start,window_end,request_cap,token_cap,resource_cap)
  VALUES(win,root,'completion.validation.synthetic','disabled.synthetic','2000-01-01T00:00:00Z','2000-01-02T00:00:00Z',1,1,1);
 INSERT INTO tutor_item_supply_shared_jobs(id,root_id,job_key,state,terminal_at)
  VALUES(job,root,'completion.validation.synthetic','cancelled','2000-01-01T00:00:00Z');
 INSERT INTO tutor_item_supply_shared_reservations(id,root_id,window_id,job_id,lease_generation,reservation_key,requests,tokens,resources)
  VALUES(reservation,root,win,job,1,'completion.validation.synthetic',0,0,0);
 INSERT INTO tutor_item_supply_shared_usage_events(id,reservation_id,job_id,settlement_key,usage_state,input_tokens,output_tokens,resource_units,cost_amount)
  VALUES(known_id,reservation,job,'completion.validation.synthetic.known','known',7,3,0,NULL),
        (unknown_id,reservation,job,'completion.validation.synthetic.unknown','unknown',NULL,NULL,NULL,NULL);
 DELETE FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current();
 FOREACH scope IN ARRAY ARRAY[$1,$2] LOOP
  IF scope=$1 THEN x:=a; ELSE x:=b; END IF;
  INSERT INTO completion_baseline_internal.validation_permits VALUES(txid_current(),x.user_id,x.id);
  d:=gen_random_uuid(); sub:=gen_random_uuid();
  p:=jsonb_build_object('schema_version','assessment_supply_demand_v1','storage_validation',true,'not_business_eligible',true,
   'fixture_id',d,'scope',x.snapshot_json,'objective_hash',x.objective_hash,'learner_ref','user:'||x.user_id::text);
  INSERT INTO tutor_item_supply_private_demands(id,user_id,epoch,scope_id,request_key,demand_hash,snapshot_json)
   VALUES(d,x.user_id,x.epoch,x.id,'completion.validation.subscription',item_supply_internal.snapshot_hash(p),p);
  INSERT INTO tutor_item_supply_private_subscriptions(id,user_id,epoch,scope_id,demand_id,shared_job_id,subscription_key)
   VALUES(sub,x.user_id,x.epoch,x.id,d,job,'completion.validation.synthetic');
  IF x.id=$1 THEN first_sub:=sub; ELSE second_sub:=sub; END IF;
  DELETE FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current();
 END LOOP;
 RETURN QUERY SELECT job,first_sub,second_sub,known_id,unknown_id,reservation;
END $$;

-- Finite validation extension: no runtime-purpose install, arbitrary JSON input,
-- real provider, live source/quality/publication authority or paid settlement.
DO $finite_scope$ BEGIN
 IF current_database()<>'aearn_completion_b_validation_20261027'
 OR NOT EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() WHERE purpose='storage-validation-purpose')
 OR to_regclass('public.tutor_item_supply_shared_usage_events') IS NOT NULL
 THEN
 RAISE EXCEPTION '600: exact unused validation extension required' USING ERRCODE='23514'; END IF;
END $finite_scope$;

-- CHECK extensions are exact predecessor matches in this one validation DB.
-- PK/FK/UNIQUE/NOT NULL and immutable/owner/epoch triggers are not relaxed.
-- These distinct labels prevent a fixture from looking like live attestation,
-- successful native consumption, independent verification or paid accounting.
DO $synthetic_shapes$
DECLARE r record; c oid; n name; count_found integer;
BEGIN
 FOR r IN SELECT * FROM (VALUES
 ('public.tutor_item_supply_native_consumer_receipts',
  $old$CHECK ((mode = ANY (ARRAY['create'::text, 'consume'::text, 'cancel'::text])))$old$,
  $new$mode='completion_storage_validation'$new$),
 ('public.tutor_item_supply_native_consumer_receipts',
  $old$CHECK ((((mode = 'create'::text) AND (run_id IS NOT NULL) AND (artifact_id IS NULL) AND (artifact_version IS NULL) AND (delivery_id IS NOT NULL)) OR ((mode = ANY (ARRAY['consume'::text, 'cancel'::text])) AND (run_id IS NULL) AND (artifact_id IS NOT NULL) AND (artifact_version IS NOT NULL) AND (delivery_id IS NULL))))$old$,
  $new$mode='completion_storage_validation' AND run_id IS NOT NULL AND artifact_id IS NOT NULL AND artifact_version IS NOT NULL AND delivery_id IS NULL AND payload_json->>'storage_validation'='true' AND payload_json->>'not_business_eligible'='true' AND checked_at='2000-01-01T00:00:00Z'::timestamptz AND valid_until='2000-01-01T00:00:01Z'::timestamptz$new$),
 ('public.rag_registered_source_captures',
  $old$CHECK ((evidence_level = 'live_egress_attested'::text))$old$,
  $new$evidence_level='completion_storage_validation' AND fetch_attempt_id IS NOT NULL AND transport_proof IS NULL AND transport_proof_sha256 IS NULL AND attestor_key_sha256 IS NULL AND worker_image_sha256 IS NULL$new$),
 ('public.rag_source_admissions',
  $old$CHECK (((cardinality(allowed_usages) >= 1) AND (cardinality(allowed_usages) <= 3) AND (allowed_usages <@ ARRAY['main_teaching'::text, 'supplementary_explanation'::text, 'assessment_evidence'::text])))$old$,
  $new$cardinality(allowed_usages)=0 AND NOT active AND revoked_at IS NOT NULL AND receipt_handle LIKE 'completion.validation.%'$new$),
 ('public.rag_source_claim_receipts',
  $old$CHECK ((method = ANY (ARRAY['independent_source'::text, 'isolated_execution'::text])))$old$,
  $new$method='completion_storage_validation'$new$),
 ('public.rag_source_claim_receipts',
  $old$CHECK ((((method = 'independent_source'::text) AND (independent_admission_id IS NOT NULL) AND (execution_receipt_handle IS NULL) AND (independent_admission_id <> admission_id) AND (independent_document_hash IS NOT NULL)) OR ((method = 'isolated_execution'::text) AND (independent_admission_id IS NULL) AND (independent_document_hash IS NULL) AND (execution_receipt_handle IS NOT NULL))))$old$,
  $new$method='completion_storage_validation' AND independent_admission_id IS NULL AND independent_document_hash IS NULL AND execution_receipt_handle IS NULL AND revoked_at IS NOT NULL$new$)
,
 ('public.rag_source_claim_receipts',
  $old$CHECK ((((method = 'independent_source'::text) AND (independent_document_hash IS NOT NULL)) OR ((method = 'isolated_execution'::text) AND (independent_document_hash IS NULL))))$old$,
  $new$method='completion_storage_validation' AND independent_document_hash IS NULL AND revoked_at IS NOT NULL$new$)
 ) AS definitions(relation,predecessor,synthetic_branch) LOOP
  SELECT count(*),(array_agg(oid))[1] INTO count_found,c FROM pg_constraint
   WHERE conrelid=r.relation::regclass AND contype='c' AND convalidated AND conislocal
    AND pg_get_constraintdef(oid)=r.predecessor;
  IF count_found<>1 THEN RAISE EXCEPTION '600: exact CHECK predecessor mismatch for %: %',r.relation,r.predecessor USING ERRCODE='23514'; END IF;
  SELECT conname INTO n FROM pg_constraint WHERE oid=c;
  EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',r.relation,n);
  EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I CHECK ((%s) OR ((%s) IS TRUE))',r.relation,n,
   substring(r.predecessor FROM 8 FOR length(r.predecessor)-8),r.synthetic_branch);
 END LOOP;
END $synthetic_shapes$;

CREATE FUNCTION completion_baseline_internal.issue_native_binding_graph(scope_id uuid,artifact_id uuid,source_run_id uuid)
RETURNS TABLE(binding_artifact_id uuid,mapping_id uuid,consumer_receipt_id uuid,item_version_id uuid,plan_session_id uuid,plan_draft_id uuid,selection_handle text,assessment_binding_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE s public.tutor_item_supply_private_scopes%ROWTYPE; a public.tutor_learning_artifacts%ROWTYPE;
 run public.tutor_runs%ROWTYPE; node uuid; ps uuid:=gen_random_uuid(); draft uuid:=gen_random_uuid();
 selection text:='selection.'||replace(gen_random_uuid()::text,'-',''); binding uuid:=gen_random_uuid();
 mapping uuid:=gen_random_uuid(); receipt uuid:=gen_random_uuid(); item uuid:=gen_random_uuid();
 blueprint uuid:=gen_random_uuid(); version_id_value uuid:=gen_random_uuid(); demand uuid:=gen_random_uuid();
 p jsonb; h text; demand_payload jsonb; item_payload jsonb; item_hash_value text;
 item_key_value text:='completion.validation.'||replace(item::text,'-','');
BEGIN
 s:=completion_baseline_internal.validation_scope($1);
 SELECT * INTO a FROM tutor_learning_artifacts WHERE id=$2 AND user_id=s.user_id
  AND learning_track_id=s.track_id AND knowledge_key=s.knowledge_key AND owner_kind='teaching_practice' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION '600: same-owner original teaching artifact required' USING ERRCODE='23514'; END IF;
 SELECT * INTO run FROM tutor_runs WHERE id=$3 AND user_id=s.user_id AND conversation_id=a.conversation_id
  AND input_revision>=1 AND model_call_count=0 AND capability_call_count=0 AND effect_count=0 FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION '600: same-owner non-dispatched original run required' USING ERRCODE='23514'; END IF;
 SELECT id INTO node FROM tutor_track_plan_nodes WHERE revision_id=s.revision_id AND track_id=s.track_id
  AND user_id=s.user_id AND knowledge_key=s.knowledge_key;
 p:=jsonb_build_object('schema_version','completion_storage_validation_v1','storage_validation',true,'not_business_eligible',true,'fixture_id',mapping);
 h:=item_supply_internal.snapshot_hash(p);
 INSERT INTO completion_baseline_internal.validation_permits VALUES(txid_current(),s.user_id,s.id);
 INSERT INTO tutor_learning_plan_sessions(id,user_id,conversation_id,status,cancelled_at)
  VALUES(ps,s.user_id,a.conversation_id,'cancelled',clock_timestamp());
 INSERT INTO tutor_learning_plan_drafts(id,session_id,user_id,draft_version,language_id,goal_text,target_level,weekly_minutes,
  experience_level,pace_summary,profile_json,plan_json,source_summary_json,content_hash,generator_version,policy_version,
  change_reason,source_run_id,source_input_revision)
 VALUES(draft,ps,s.user_id,1,'python','Synthetic storage validation only','beginner',15,'new','Not a learning plan',p,p,
  jsonb_build_array(p),h,'completion-storage-validation','completion-storage-validation','No model or source authority',run.id,run.input_revision);
 INSERT INTO rag_material_selections(handle,user_id,conversation_id,session_id,draft_id,draft_version,content_hash,
  source_run_id,source_input_revision,selection_digest,snapshot_json,idempotency_key)
 VALUES(selection,s.user_id,a.conversation_id,ps,draft,1,h,run.id,run.input_revision,h,p,'completion.validation.selection');
 INSERT INTO rag_plan_material_bindings(id,selection_handle,selection_digest,user_id,session_id,draft_id,node_id,
  goal_hash,purpose,binding_digest,binding_json,idempotency_key)
 VALUES(binding,selection,h,s.user_id,ps,draft,s.knowledge_key,h,'assessment_evidence',h,p,'completion.validation.binding');
 demand_payload:=p||jsonb_build_object('schema_version','assessment_supply_demand_v1',
  'scope',s.snapshot_json,'objective_hash',s.objective_hash,'learner_ref','user:'||s.user_id::text);
 INSERT INTO tutor_item_supply_private_demands(id,user_id,epoch,scope_id,request_key,demand_hash,snapshot_json)
 VALUES(demand,s.user_id,s.epoch,s.id,'completion.validation.native',item_supply_internal.snapshot_hash(demand_payload),demand_payload);
 INSERT INTO tutor_item_supply_finite_course_mappings(id,user_id,epoch,track_id,revision_id,node_id,knowledge_key,
  session_id,draft_id,selection_handle,selection_digest,assessment_binding_id,binding_digest,goal_hash,mapping_hash,
  practice_scope_id,practice_demand_id,assessment_scope_id,assessment_demand_id,remediation_scope_id,remediation_demand_id,receipt_json)
 VALUES(mapping,s.user_id,s.epoch,s.track_id,s.revision_id,node,s.knowledge_key,ps,draft,selection,h,binding,h,h,h,
  s.id,demand,s.id,demand,s.id,demand,p||jsonb_build_object('schema_version','finite_course_mapping_v1'));
 -- Retained shared item bytes contain only their own shared identity, never a
 -- private mapping/user/draft identifier or the private mapping fingerprint.
 item_payload:=jsonb_build_object('schema_version','completion_storage_validation_v1','storage_validation',true,
  'not_business_eligible',true,'fixture_id',item);
 item_hash_value:=item_supply_internal.snapshot_hash(item_payload);
 INSERT INTO tutor_learning_item_blueprints(id,blueprint_key,version,knowledge_key,item_kind,purpose,language_id,difficulty,
  risk_tier,required_capabilities_json,blueprint_json,blueprint_hash)
 VALUES(blueprint,item_key_value,'storage-validation-v1',s.knowledge_key,'knowledge_check','knowledge_check','python','D1','low',
  jsonb_build_array(s.knowledge_key),item_payload,item_hash_value);
 INSERT INTO tutor_learning_items(id,item_key,item_kind) VALUES(item,item_key_value,'knowledge_check');
 INSERT INTO tutor_learning_item_versions(id,item_id,blueprint_id,item_key,version,item_kind,purpose,knowledge_key,language_id,
  difficulty,risk_tier,required_capabilities_json,source_schema_version,compiler_version,source_hash,blueprint_hash,
  public_hash,private_hash,content_hash,handle,creator_identity)
 VALUES(version_id_value,item,blueprint,item_key_value,'storage-validation-v1','knowledge_check','knowledge_check',s.knowledge_key,
  'python','D1','low',jsonb_build_array(s.knowledge_key),'learning_item_source_v1','learning_item_compiler_v1',
  item_hash_value,item_hash_value,item_hash_value,item_hash_value,item_hash_value,'li:'||item_hash_value,'completion.storage-validation');
 -- No public/private contents, delivery, exposure completeness or publication.
 INSERT INTO tutor_item_supply_native_consumer_receipts(id,user_id,epoch,mode,run_id,artifact_id,artifact_version,
  mapping_id,version_id,payload_json,checked_at,valid_until)
 VALUES(receipt,s.user_id,s.epoch,'completion_storage_validation',run.id,a.id,a.version,mapping,version_id_value,p,
  '2000-01-01T00:00:00Z','2000-01-01T00:00:01Z');
 INSERT INTO tutor_item_supply_native_artifact_bindings(artifact_id,user_id,epoch,version_id,mapping_id,creation_receipt_id)
 VALUES(a.id,s.user_id,s.epoch,version_id_value,mapping,receipt);
 DELETE FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current();
 RETURN QUERY SELECT a.id,mapping,receipt,version_id_value,ps,draft,selection,binding;
END $$;
CREATE FUNCTION completion_baseline_internal.validation_scope(scope_id uuid)
RETURNS public.tutor_item_supply_private_scopes
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE s public.tutor_item_supply_private_scopes%ROWTYPE;
BEGIN
 PERFORM completion_baseline_internal.assert_validation_caller();
 SELECT * INTO s FROM tutor_item_supply_private_scopes WHERE id=$1 FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_materials m WHERE m.scope_id=s.id
  AND m.user_id=s.user_id AND m.epoch=s.epoch AND m.material_key='completion.validation.material'
  AND m.content_text='Synthetic storage only. No source, quality, usage, admission, publication or consumer authority.') THEN
 RAISE EXCEPTION '600: original fixed validation graph required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM users WHERE id=s.user_id AND deleted_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION '600: active owner required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM tutor_item_supply_user_epochs WHERE user_id=s.user_id AND epoch=s.epoch AND enabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION '600: current enabled epoch required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM tutor_track_active_plans WHERE track_id=s.track_id AND user_id=s.user_id AND revision_id=s.revision_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION '600: active plan required' USING ERRCODE='23514'; END IF;
 RETURN s;
END $$;
-- Original 440 composite FK and UNKNOWN NULL shape; validation-only retention table.
CREATE TABLE public.tutor_item_supply_shared_usage_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), reservation_id uuid NOT NULL, job_id uuid NOT NULL,
 settlement_key text NOT NULL CHECK(settlement_key IN('completion.validation.synthetic.known','completion.validation.synthetic.unknown')),
 usage_state text NOT NULL CHECK(usage_state IN('known','unknown')),
 input_tokens bigint CHECK(input_tokens>=0),output_tokens bigint CHECK(output_tokens>=0),
 resource_units bigint CHECK(resource_units>=0),cost_amount numeric CHECK(cost_amount>=0),
 CHECK((usage_state='unknown' AND input_tokens IS NULL AND output_tokens IS NULL AND resource_units IS NULL AND cost_amount IS NULL)
 OR (usage_state='known' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND resource_units IS NOT NULL)),
 CHECK(cost_amount IS NULL), UNIQUE(reservation_id,settlement_key),created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);
CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_usage_events
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();
CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_usage_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');
ALTER TABLE public.tutor_item_supply_shared_usage_events OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_usage_events FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
GRANT SELECT ON TABLE public.tutor_item_supply_shared_usage_events TO aearn_cb_runtime_20261027;
DO $exact_predecessor$ BEGIN
 IF (SELECT prosrc FROM pg_proc WHERE oid='completion_baseline_internal.enforce_closed_storage()'::regprocedure) IS DISTINCT FROM $prior$
DECLARE r jsonb; u uuid; s uuid;
BEGIN
 PERFORM * FROM completion_baseline_internal.contract_identity();
 IF TG_TABLE_NAME='installation_identity' THEN
  RAISE EXCEPTION 'completion baseline: installation identity immutable' USING ERRCODE='42501';
 END IF;
 r:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 u:=(r->>'user_id')::uuid; s:=CASE WHEN TG_TABLE_NAME='tutor_item_supply_private_scopes' THEN (r->>'id')::uuid ELSE (r->>'scope_id')::uuid END;
 -- Maintenance permits authorize only UPDATE/DELETE within the original user TOP.
 IF TG_OP IN('UPDATE','DELETE') AND u IS NOT NULL AND item_supply_internal.permitted(u) THEN
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
 IF TG_OP='INSERT' AND TG_TABLE_NAME IN('tutor_item_supply_private_scopes','tutor_item_supply_private_materials',
    'tutor_item_supply_private_candidates','tutor_item_supply_private_versions','tutor_item_supply_private_persistent_pack_journal')
  AND completion_baseline_internal.validation_allowed(u,s) THEN RETURN NEW; END IF;
 -- The fixed validation receiver may retain only its one non-business SHARED matrix.
 IF TG_OP='INSERT' AND TG_TABLE_NAME='tutor_item_supply_shared_matrices'
  AND session_user='aearn_cb_verifier_20261027' AND current_setting('role') IN('none','aearn_cb_verifier_20261027')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() WHERE purpose='storage-validation-purpose')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current()) THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'completion baseline: P2/P7 business storage denied: % %',TG_TABLE_NAME,TG_OP USING ERRCODE='42501';
END $prior$ THEN RAISE EXCEPTION '600: exact 599 storage predecessor changed' USING ERRCODE='23514'; END IF;
END $exact_predecessor$;
CREATE OR REPLACE FUNCTION completion_baseline_internal.enforce_closed_storage() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE r jsonb; u uuid; s uuid;
BEGIN
 PERFORM * FROM completion_baseline_internal.contract_identity();
 IF TG_TABLE_NAME='installation_identity' THEN
  RAISE EXCEPTION 'completion baseline: installation identity immutable' USING ERRCODE='42501';
 END IF;
 r:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 u:=(r->>'user_id')::uuid; s:=CASE WHEN TG_TABLE_NAME='tutor_item_supply_private_scopes' THEN (r->>'id')::uuid ELSE (r->>'scope_id')::uuid END;
 -- Maintenance permits authorize only UPDATE/DELETE within the original user TOP.
 IF TG_OP IN('UPDATE','DELETE') AND u IS NOT NULL AND item_supply_internal.permitted(u) THEN
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
 IF TG_OP='INSERT' AND TG_TABLE_NAME IN('tutor_item_supply_private_scopes','tutor_item_supply_private_materials',
    'tutor_item_supply_private_candidates','tutor_item_supply_private_versions','tutor_item_supply_private_persistent_pack_journal')
  AND completion_baseline_internal.validation_allowed(u,s) THEN RETURN NEW; END IF;

 -- Finite protected extensions only, never runtime business writes.
 IF TG_OP='INSERT' AND TG_TABLE_NAME IN('tutor_item_supply_private_demands','tutor_item_supply_private_subscriptions')
 AND completion_baseline_internal.validation_allowed(u,s) THEN RETURN NEW; END IF;
 IF TG_OP='INSERT' AND TG_TABLE_NAME IN('tutor_item_supply_finite_course_mappings','tutor_item_supply_native_consumer_receipts','tutor_item_supply_native_artifact_bindings') THEN
  IF TG_TABLE_NAME='tutor_item_supply_finite_course_mappings' THEN
   s:=(r->>'practice_scope_id')::uuid;
   IF s IS DISTINCT FROM (r->>'assessment_scope_id')::uuid OR s IS DISTINCT FROM (r->>'remediation_scope_id')::uuid
   OR r->'receipt_json'->>'storage_validation' IS DISTINCT FROM 'true'
   OR r->'receipt_json'->>'not_business_eligible' IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION '600: synthetic mapping shape required' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT practice_scope_id INTO s FROM tutor_item_supply_finite_course_mappings WHERE id=(r->>'mapping_id')::uuid
    AND user_id=u AND epoch=(r->>'epoch')::bigint AND receipt_json->>'storage_validation'='true';
  END IF;
  IF completion_baseline_internal.validation_allowed(u,s) AND EXISTS(SELECT 1 FROM tutor_item_supply_private_scopes p
   JOIN tutor_item_supply_user_epochs e ON e.user_id=p.user_id AND e.epoch=p.epoch AND e.enabled
   JOIN users a ON a.id=e.user_id AND a.deleted_at IS NULL
   WHERE p.id=s AND p.user_id=u AND p.epoch=(r->>'epoch')::bigint) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='INSERT' AND session_user='aearn_cb_verifier_20261027' AND current_setting('role') IN('none','aearn_cb_verifier_20261027')
 AND EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() WHERE purpose='storage-validation-purpose')
 AND EXISTS(SELECT 1 FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current())
 AND ((TG_TABLE_NAME='tutor_item_supply_shared_policies' AND r->'policy_json'->>'publication_enabled'='false' AND r->>'policy_version'='autonomous_evidence_policy_v2')
 OR (TG_TABLE_NAME='tutor_item_supply_shared_blueprints' AND r->'snapshot_json'->'scope'->>'course_family'='completion-storage-validation')
 OR (TG_TABLE_NAME='tutor_item_supply_shared_budget_roots' AND r->>'policy_class'='completion.validation.synthetic')
 OR (TG_TABLE_NAME='tutor_item_supply_shared_budget_windows' AND r->>'provider_key'='disabled.synthetic')
 OR (TG_TABLE_NAME='tutor_item_supply_shared_jobs' AND r->>'job_key'='completion.validation.synthetic' AND r->>'state'='cancelled')
 OR (TG_TABLE_NAME='tutor_item_supply_shared_reservations' AND r->>'reservation_key'='completion.validation.synthetic')
 OR (TG_TABLE_NAME='tutor_item_supply_shared_usage_events' AND r->>'settlement_key' IN('completion.validation.synthetic.known','completion.validation.synthetic.unknown'))) THEN RETURN NEW; END IF;
 -- The fixed validation receiver may retain only its one non-business SHARED matrix.
 IF TG_OP='INSERT' AND TG_TABLE_NAME='tutor_item_supply_shared_matrices'
  AND session_user='aearn_cb_verifier_20261027' AND current_setting('role') IN('none','aearn_cb_verifier_20261027')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() WHERE purpose='storage-validation-purpose')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current()) THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'completion baseline: P2/P7 business storage denied: % %',TG_TABLE_NAME,TG_OP USING ERRCODE='42501';
END $$;


CREATE FUNCTION completion_baseline_internal.validation_source_allowed(evidence_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM rag_assessment_source_evidence e
 JOIN tutor_item_supply_private_scopes s ON s.id=(e.signed_proof->'payload'->'prepared'->>'validation_scope_id')::uuid
  AND s.user_id=e.private_user_id AND s.epoch=e.private_epoch
 JOIN tutor_item_supply_user_epochs current_epoch ON current_epoch.user_id=s.user_id AND current_epoch.epoch=s.epoch AND current_epoch.enabled
 JOIN users u ON u.id=s.user_id AND u.deleted_at IS NULL
 WHERE e.id=$1 AND e.signed_proof->>'storage_validation'='true' AND e.signed_proof->>'not_business_eligible'='true'
  AND e.signed_proof->>'signature_status'='unsigned' AND e.revoked_at IS NOT NULL
  AND e.expires_at='2000-01-01T00:01:00Z'::timestamptz
  AND completion_baseline_internal.validation_allowed(s.user_id,s.id))
$$;

CREATE FUNCTION completion_baseline_internal.issue_actual_d_tail_graph(scope_id uuid)
RETURNS TABLE(private_evidence_id uuid,review_id uuid,admission_id uuid,claim_id uuid,public_evidence_id uuid,corpus_id uuid,capture_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE s public.tutor_item_supply_private_scopes%ROWTYPE; mapping public.tutor_item_supply_finite_course_mappings%ROWTYPE;
 private_id uuid:=gen_random_uuid(); public_id uuid:=gen_random_uuid(); review uuid:=gen_random_uuid();
 admission uuid:=gen_random_uuid(); claim uuid:=gen_random_uuid(); capture uuid:=gen_random_uuid();
 attempt uuid:=gen_random_uuid(); corpus uuid:=gen_random_uuid(); evidence_id uuid; proof jsonb;
 private_proof jsonb; public_proof jsonb; marker jsonb; h text; private_hash text; public_hash text;
 key text:='completion.validation.'||replace(capture::text,'-',''); url text; document_key text;
 body bytea:=convert_to('SYNTHETIC STORAGE ONLY. NO FETCH, SIGNATURE, QUALITY, EXECUTION OR SOURCE AUTHORITY.','UTF8');
 issued timestamptz:='2000-01-01T00:00:00Z'; expiry timestamptz:='2000-01-01T00:01:00Z';
BEGIN
 s:=completion_baseline_internal.validation_scope($1);
 SELECT * INTO mapping FROM tutor_item_supply_finite_course_mappings WHERE user_id=s.user_id AND epoch=s.epoch
  AND practice_scope_id=s.id AND receipt_json->>'storage_validation'='true' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION '600: fixed native graph with real D child FKs required first' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=s.user_id) THEN
  RAISE EXCEPTION '600: unused synthetic source namespace required' USING ERRCODE='23514'; END IF;
 INSERT INTO completion_baseline_internal.validation_permits VALUES(txid_current(),s.user_id,s.id);
 h:=encode(digest(body,'sha256'),'hex'); url:='https://completion-storage.invalid/'||replace(capture::text,'-','');
 document_key:=key||'.document';
 marker:=jsonb_build_object('storage_validation',true,'not_business_eligible',true,'signature_status','unsigned');
 INSERT INTO rag_budget_authority_roots(root_id,delegation_id,delegation_generation,delegation_expires_at,
  policy_id,policy_generation,period_key,period_start,period_end,cap_units,enabled)
 VALUES(key,key,1,expiry,key,1,'storage-validation',issued,expiry,1,false);
 INSERT INTO rag_registered_source_policies(policy_id,generation,source_handle,subject_id,subject_version,facets,origin,
  reading_level,canonical_url,canonical_url_sha256,host,path,license_id,allowed_usages,max_captured_bytes,
  retention_until,expires_at,root_id,enabled,revoked_at)
 VALUES(key,1,key,'completion-storage-validation','synthetic-v1',ARRAY['storage-validation'],'tutorial','beginner',url,
  encode(digest(url,'sha256'),'hex'),'completion-storage.invalid','/'||replace(capture::text,'-',''),'LicenseRef-Synthetic',
  ARRAY['assessment_evidence'],octet_length(body),expiry,expiry,key,false,issued);
 INSERT INTO rag_registered_fetch_attempts(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,
  state,error_code,dispatched_at)
 VALUES(attempt,key,1,encode(digest(url,'sha256'),'hex'),key,key,h,'unknown','STORAGE_VALIDATION_NO_FETCH',issued);
 INSERT INTO rag_registered_source_captures(id,fetch_attempt_id,policy_id,generation,request_chain,final_url,content_type,
  fetched_sha256,captured_bytes,captured_body,license_id,retention_until,evidence_level,fetched_at)
 VALUES(capture,attempt,key,1,jsonb_build_array(url),url,'text/plain',h,octet_length(body),body,'LicenseRef-Synthetic',
  expiry,'completion_storage_validation',issued);
 -- v3 is retained solely as the formal lifecycle classification key, not a
 -- signed/oracle receipt: top-level unsigned marker and absent terminal/signature.
 private_proof:=marker||jsonb_build_object('payload',jsonb_build_object('format','aearn.rag.actual-d-finite-source.v3',
  'prepared',jsonb_build_object('validation_scope_id',s.id,'actual_d',jsonb_build_object(
    'contract_version','completion_storage_validation_v1','user_epoch',s.epoch,'draft',jsonb_build_object('user_id',s.user_id,'id',mapping.draft_id)))));
 public_proof:=marker||jsonb_build_object('payload',jsonb_build_object('format','aearn.rag.fresh-assessment-source.v1'));
 private_hash:=item_supply_internal.snapshot_hash(private_proof); public_hash:=item_supply_internal.snapshot_hash(public_proof);
 FOREACH evidence_id IN ARRAY ARRAY[public_id,private_id] LOOP
  IF evidence_id=private_id THEN proof:=private_proof; ELSE proof:=public_proof; END IF;
  INSERT INTO rag_assessment_source_evidence(id,capture_id,source_handle,document_handle,document_hash,policy_id,
   policy_generation,root_id,profile_id,demand_hash,claim_hash,execution_handle,claim_handle,service_key_id,signed_proof,
   proof_hash,terminal_hash,issued_at,expires_at,revoked_at,private_user_id,private_epoch)
  VALUES(evidence_id,capture,key,'completion.validation.evidence.'||replace(evidence_id::text,'-',''),h,key,1,key,
   'python-state-source-v1',item_supply_internal.snapshot_hash(jsonb_build_object('synthetic_id',evidence_id)),h,
   'source-execution.'||replace(evidence_id::text,'-',''),'source-claim.'||replace(evidence_id::text,'-',''),
   'completion.storage-validation.unsigned',proof,item_supply_internal.snapshot_hash(proof),h,issued,expiry,issued,
   CASE WHEN evidence_id=private_id THEN s.user_id ELSE NULL END,CASE WHEN evidence_id=private_id THEN s.epoch ELSE NULL END);
 END LOOP;
 INSERT INTO rag_source_reviews(id,registered_capture_id,source_handle,document_handle,subject_id,subject_version,facets,
  document_revision,document_hash,lineage_family,origin,reading_level,status,quality_code,reading_fit,version_fit,
  technical_status,conflict_status,known_error,covered_facets,quality_evidence_hash,storage_receipt_id,license_id,
  allowed_usages,immutable_history_allowed,policy_id,policy_generation,root_id,review_receipt_hash,reviewed_at,assessment_evidence_id)
 VALUES(review,capture,key,document_key,'completion-storage-validation','synthetic-v1',ARRAY['storage-validation'],
  'synthetic-v1',h,key,'tutorial','beginner','quarantined','STORAGE_VALIDATION_ONLY','unknown','unknown','unknown','unknown',
  'unknown',ARRAY[]::text[],h,key,'LicenseRef-Synthetic',ARRAY[]::text[],false,key,1,key,h,issued,private_id);
 INSERT INTO rag_source_admissions(id,review_id,receipt_handle,allowed_usages,policy_generation,receipt_hash,active,revoked_at,admitted_at)
 VALUES(admission,review,key,ARRAY[]::text[],1,h,false,issued,issued);
 INSERT INTO rag_source_claim_receipts(id,admission_id,claim_hash,demand_hash,subject_id,subject_version,source_document_hash,
  applicability_hash,method,verification_receipt_hash,verified_at,revoked_at,assessment_evidence_id)
 VALUES(claim,admission,h,h,'completion-storage-validation','synthetic-v1',h,h,'completion_storage_validation',h,issued,issued,private_id);
 -- A failed synthetic corpus, never validated/published/active, supplies the real
 -- provenance FK. No private evidence identifier enters these shared rows.
 INSERT INTO grounding_corpus_versions(id,subject_id,subject_version,registry_digest,retrieval_policy_version,coverage_policy_version)
 VALUES(corpus,'completion-storage-validation','synthetic-v1',h,'storage-validation','storage-validation');
 INSERT INTO grounding_corpus_source_snapshots(corpus_version_id,subject_id,subject_version,source_id,source_hash,trust_tier,
  source_kind,source_version,allowed_domains_json,seed_urls_json,facets_json)
 VALUES(corpus,'completion-storage-validation','synthetic-v1',key,h,'trusted_de_facto','storage-validation','synthetic-v1',
  '["completion-storage.invalid"]'::jsonb,'[]'::jsonb,'["storage-validation"]'::jsonb);
 INSERT INTO grounding_corpus_documents(corpus_version_id,document_id,source_id,subject_id,subject_version,source_hash,trust_tier,
  canonical_url,final_url,content_type,document_version,fetched_at,document_hash,parse_status,diagnostic_code)
 VALUES(corpus,document_key,key,'completion-storage-validation','synthetic-v1',h,'trusted_de_facto',url,url,'text/plain',
  'synthetic-v1',issued,h,'failed','STORAGE_VALIDATION_ONLY');
 UPDATE grounding_corpus_versions SET state='failed',generation=1,
  validation_summary_json='{"storage_validation":true,"not_business_eligible":true}'::jsonb WHERE id=corpus;
 INSERT INTO rag_actual_d_private_provenance(private_evidence_id,user_id,epoch,draft_id,node_id,goal_hash,target_id,
  public_evidence_id,corpus_id,generation,document_id,document_hash,private_proof_hash,public_proof_hash,chunks_json)
 VALUES(private_id,s.user_id,s.epoch,mapping.draft_id,s.knowledge_key,mapping.goal_hash,'python-state-update-v1',public_id,
  corpus,1,document_key,h,private_hash,public_hash,jsonb_build_array(marker));
 DELETE FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current();
 RETURN QUERY SELECT private_id,review,admission,claim,public_id,corpus,capture;
END $$;

DO $exact_predecessor$ BEGIN
 IF (SELECT prosrc FROM pg_proc WHERE oid='public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz)'::regprocedure) IS DISTINCT FROM $prior$
DECLARE p jsonb := signed_proof->'payload';
DECLARE q jsonb := p->'prepared';
DECLARE a jsonb := q->'actual_d';
DECLARE prepared_at timestamptz;
DECLARE authority_until timestamptz;
DECLARE companion jsonb;
BEGIN
  IF (p->>'format') IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3' OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS NULL OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS DISTINCT FROM profile_id OR
     (a->>'contract_version') IS DISTINCT FROM 'rag_actual_d_finite_source_scope_v1' OR
     (a->>'oracle_run_id') IS NULL OR
     (p->'terminal'->>'run_id') IS DISTINCT FROM a->>'oracle_run_id' OR
     (p->'terminal'->>'probe_name') IS DISTINCT FROM 'actual_d_finite_source_oracle' OR
     issued_at IS NULL OR expires_at IS NULL OR issued_at>=expires_at OR
     expires_at>issued_at+interval '168 hours' OR
     (p->>'issued_at') IS NULL OR (p->>'expires_at') IS NULL OR
     (p->>'issued_at')::timestamptz IS DISTINCT FROM issued_at OR
     (p->>'expires_at')::timestamptz IS DISTINCT FROM expires_at THEN RETURN false; END IF;
  PERFORM (a->>'oracle_run_id')::uuid;
  prepared_at := (q->>'prepared_at')::timestamptz;
  authority_until := (q->>'authority_expires_at')::timestamptz;
  IF prepared_at IS NULL OR authority_until IS NULL OR prepared_at>issued_at OR
     authority_until<expires_at OR authority_until>prepared_at+interval '168 hours' OR
     (q->'budget'->>'expires_at') IS NULL OR
     authority_until>(q->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
  IF profile_id='sqlite-predicate-source-v1' THEN
    IF jsonb_typeof(q->'companions') IS DISTINCT FROM 'array' OR
       jsonb_array_length(q->'companions')<>2 THEN RETURN false; END IF;
    FOR companion IN SELECT value FROM jsonb_array_elements(q->'companions') LOOP
      IF (companion->>'authority_expires_at') IS NULL OR
         (companion->'budget'->>'expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz<authority_until OR
         (companion->>'authority_expires_at')::timestamptz>prepared_at+interval '168 hours' OR
         (companion->>'authority_expires_at')::timestamptz IS DISTINCT FROM
           (companion->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
    END LOOP;
  ELSIF q ? 'companions' THEN RETURN false;
  END IF;
  RETURN true;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_parameter_value OR invalid_text_representation THEN
  RETURN false;
END $prior$ THEN RAISE EXCEPTION '600: exact predecessor changed: public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz)' USING ERRCODE='23514'; END IF;
END $exact_predecessor$;
CREATE OR REPLACE FUNCTION public.rag_actual_d_finite_lifetime_allowed(
  signed_proof jsonb, profile_id text, issued_at timestamptz, expires_at timestamptz
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE p jsonb := signed_proof->'payload';
DECLARE q jsonb := p->'prepared';
DECLARE a jsonb := q->'actual_d';
DECLARE prepared_at timestamptz;
DECLARE authority_until timestamptz;
DECLARE companion jsonb;
BEGIN

  -- Classification format remains v3 for the unmodified formal 503 owner;
  -- explicitly unsigned, revoked storage fixtures have NO oracle/terminal proof.
  IF signed_proof->>'storage_validation'='true' THEN
    RETURN (signed_proof->>'not_business_eligible'='true' AND signed_proof->>'signature_status'='unsigned'
      AND NOT signed_proof ? 'signature' AND NOT p ? 'terminal'
      AND p->>'format'='aearn.rag.actual-d-finite-source.v3'
      AND profile_id='python-state-source-v1' AND q->>'validation_scope_id' IS NOT NULL
      AND a->>'oracle_run_id' IS NULL AND a->>'contract_version'='completion_storage_validation_v1'
      AND issued_at='2000-01-01T00:00:00Z'::timestamptz AND expires_at='2000-01-01T00:01:00Z'::timestamptz) IS TRUE;
  END IF;
  IF (p->>'format') IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3' OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS NULL OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS DISTINCT FROM profile_id OR
     (a->>'contract_version') IS DISTINCT FROM 'rag_actual_d_finite_source_scope_v1' OR
     (a->>'oracle_run_id') IS NULL OR
     (p->'terminal'->>'run_id') IS DISTINCT FROM a->>'oracle_run_id' OR
     (p->'terminal'->>'probe_name') IS DISTINCT FROM 'actual_d_finite_source_oracle' OR
     issued_at IS NULL OR expires_at IS NULL OR issued_at>=expires_at OR
     expires_at>issued_at+interval '168 hours' OR
     (p->>'issued_at') IS NULL OR (p->>'expires_at') IS NULL OR
     (p->>'issued_at')::timestamptz IS DISTINCT FROM issued_at OR
     (p->>'expires_at')::timestamptz IS DISTINCT FROM expires_at THEN RETURN false; END IF;
  PERFORM (a->>'oracle_run_id')::uuid;
  prepared_at := (q->>'prepared_at')::timestamptz;
  authority_until := (q->>'authority_expires_at')::timestamptz;
  IF prepared_at IS NULL OR authority_until IS NULL OR prepared_at>issued_at OR
     authority_until<expires_at OR authority_until>prepared_at+interval '168 hours' OR
     (q->'budget'->>'expires_at') IS NULL OR
     authority_until>(q->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
  IF profile_id='sqlite-predicate-source-v1' THEN
    IF jsonb_typeof(q->'companions') IS DISTINCT FROM 'array' OR
       jsonb_array_length(q->'companions')<>2 THEN RETURN false; END IF;
    FOR companion IN SELECT value FROM jsonb_array_elements(q->'companions') LOOP
      IF (companion->>'authority_expires_at') IS NULL OR
         (companion->'budget'->>'expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz<authority_until OR
         (companion->>'authority_expires_at')::timestamptz>prepared_at+interval '168 hours' OR
         (companion->>'authority_expires_at')::timestamptz IS DISTINCT FROM
           (companion->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
    END LOOP;
  ELSIF q ? 'companions' THEN RETURN false;
  END IF;
  RETURN true;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_parameter_value OR invalid_text_representation THEN
  RETURN false;
END $$;

DO $exact_predecessor$ BEGIN
 IF (SELECT prosrc FROM pg_proc WHERE oid='completion_baseline_internal.enforce_source_evidence_closed()'::regprocedure) IS DISTINCT FROM $prior$
BEGIN
 IF TG_OP='DELETE' THEN
  IF TG_TABLE_NAME='rag_assessment_source_evidence' AND rag_actual_d_private_delete_allowed((to_jsonb(OLD)->>'id')::uuid) THEN RETURN OLD; END IF;
  IF TG_TABLE_NAME='rag_actual_d_private_provenance' AND item_supply_internal.permitted((to_jsonb(OLD)->>'user_id')::uuid)
    AND EXISTS(SELECT 1 FROM tutor_item_supply_user_epochs WHERE user_id=(to_jsonb(OLD)->>'user_id')::uuid AND epoch>(to_jsonb(OLD)->>'epoch')::bigint) THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'completion baseline: source facts cannot be issued or modified' USING ERRCODE='42501';
END $prior$ THEN RAISE EXCEPTION '600: exact predecessor changed: completion_baseline_internal.enforce_source_evidence_closed()' USING ERRCODE='23514'; END IF;
END $exact_predecessor$;
CREATE OR REPLACE FUNCTION completion_baseline_internal.enforce_source_evidence_closed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
BEGIN

 IF TG_OP='INSERT' THEN
  PERFORM completion_baseline_internal.assert_validation_caller();
  IF TG_TABLE_NAME='rag_assessment_source_evidence' THEN
   IF NEW.signed_proof->>'storage_validation'='true' AND NEW.signed_proof->>'not_business_eligible'='true'
    AND NEW.signed_proof->>'signature_status'='unsigned' AND NOT NEW.signed_proof ? 'signature'
    AND NEW.service_key_id='completion.storage-validation.unsigned'
    AND NEW.issued_at='2000-01-01T00:00:00Z'::timestamptz
    AND NEW.expires_at='2000-01-01T00:01:00Z'::timestamptz AND NEW.revoked_at=NEW.issued_at
    AND EXISTS(SELECT 1 FROM rag_registered_source_captures WHERE id=NEW.capture_id AND evidence_level='completion_storage_validation')
    AND EXISTS(SELECT 1 FROM completion_baseline_internal.validation_permits p
       JOIN tutor_item_supply_private_scopes s ON s.id=p.scope_id AND s.user_id=p.user_id
       JOIN tutor_item_supply_user_epochs e ON e.user_id=s.user_id AND e.epoch=s.epoch AND e.enabled
       WHERE p.transaction_id=txid_current() AND
        ((NEW.private_user_id=s.user_id AND NEW.private_epoch=s.epoch
          AND NEW.signed_proof->'payload'->'prepared'->>'validation_scope_id'=s.id::text)
         OR (NEW.private_user_id IS NULL AND NEW.private_epoch IS NULL
          AND NEW.signed_proof->'payload'->>'format'='aearn.rag.fresh-assessment-source.v1'))) THEN RETURN NEW; END IF;
  ELSIF TG_TABLE_NAME='rag_actual_d_private_provenance' AND completion_baseline_internal.validation_source_allowed(NEW.private_evidence_id)
    AND EXISTS(SELECT 1 FROM rag_assessment_source_evidence e WHERE e.id=NEW.private_evidence_id
      AND e.private_user_id=NEW.user_id AND e.private_epoch=NEW.epoch AND e.proof_hash=NEW.private_proof_hash)
    AND EXISTS(SELECT 1 FROM rag_assessment_source_evidence e WHERE e.id=NEW.public_evidence_id
      AND e.private_user_id IS NULL AND e.signed_proof->>'storage_validation'='true' AND e.revoked_at IS NOT NULL
      AND e.proof_hash=NEW.public_proof_hash) THEN RETURN NEW;
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN
  IF TG_TABLE_NAME='rag_assessment_source_evidence' AND rag_actual_d_private_delete_allowed((to_jsonb(OLD)->>'id')::uuid) THEN RETURN OLD; END IF;
  IF TG_TABLE_NAME='rag_actual_d_private_provenance' AND item_supply_internal.permitted((to_jsonb(OLD)->>'user_id')::uuid)
    AND EXISTS(SELECT 1 FROM tutor_item_supply_user_epochs WHERE user_id=(to_jsonb(OLD)->>'user_id')::uuid AND epoch>(to_jsonb(OLD)->>'epoch')::bigint) THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'completion baseline: source facts cannot be issued or modified' USING ERRCODE='42501';
END $$;

DO $exact_predecessor$ BEGIN
 IF (SELECT prosrc FROM pg_proc WHERE oid='completion_baseline_internal.enforce_closed_native_consumer()'::regprocedure) IS DISTINCT FROM $prior$
DECLARE r jsonb:=to_jsonb(NEW); owner_uuid uuid;
BEGIN
 PERFORM * FROM completion_baseline_internal.contract_identity();
 IF TG_TABLE_NAME IN('rag_source_reviews','rag_source_claim_receipts') AND r->>'assessment_evidence_id' IS NOT NULL THEN
  RAISE EXCEPTION 'completion baseline: new source/assessment authority denied' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='rag_source_admissions' AND EXISTS(SELECT 1 FROM rag_source_reviews WHERE id=(r->>'review_id')::uuid AND assessment_evidence_id IS NOT NULL) THEN
  RAISE EXCEPTION 'completion baseline: source admission denied' USING ERRCODE='42501'; END IF;
 IF r->>'private_native_version_id' IS NOT NULL OR r->>'native_generation_artifact_id' IS NOT NULL
  OR r->>'schema_version'='candidate_validation_v2' THEN
  RAISE EXCEPTION 'completion baseline: native receiving domain denied' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='tutor_learning_artifacts' AND r->>'owner_kind'='learning_item' THEN owner_uuid:=(r->>'owner_id')::uuid;
 ELSIF TG_TABLE_NAME IN('tutor_learning_item_publication_events','tutor_learning_item_practice_materializations') THEN owner_uuid:=(r->>'version_id')::uuid;
 ELSIF TG_TABLE_NAME='tutor_knowledge_check_response_receipts' THEN owner_uuid:=(r->>'learning_item_version_id')::uuid; END IF;
 IF owner_uuid IS NOT NULL AND (EXISTS(SELECT 1 FROM tutor_item_supply_private_versions WHERE id=owner_uuid)
  OR EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs WHERE version_id=owner_uuid)) THEN
  RAISE EXCEPTION 'completion baseline: P2/P7 original consumer denied' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END $prior$ THEN RAISE EXCEPTION '600: exact predecessor changed: completion_baseline_internal.enforce_closed_native_consumer()' USING ERRCODE='23514'; END IF;
END $exact_predecessor$;
CREATE OR REPLACE FUNCTION completion_baseline_internal.enforce_closed_native_consumer() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE r jsonb:=to_jsonb(NEW); owner_uuid uuid;
BEGIN

 IF TG_OP='INSERT' AND TG_TABLE_NAME IN('rag_source_reviews','rag_source_claim_receipts')
  AND completion_baseline_internal.validation_source_allowed((r->>'assessment_evidence_id')::uuid)
  AND ((TG_TABLE_NAME='rag_source_reviews' AND r->>'status'='quarantined' AND r->>'quality_code'='STORAGE_VALIDATION_ONLY')
   OR (TG_TABLE_NAME='rag_source_claim_receipts' AND r->>'method'='completion_storage_validation' AND r->>'revoked_at' IS NOT NULL)) THEN RETURN NEW; END IF;
 IF TG_OP='INSERT' AND TG_TABLE_NAME='rag_source_admissions' AND (r->>'active')::boolean IS FALSE
  AND r->>'revoked_at' IS NOT NULL AND completion_baseline_internal.validation_source_allowed(
   (SELECT assessment_evidence_id FROM rag_source_reviews WHERE id=(r->>'review_id')::uuid)) THEN RETURN NEW; END IF;
 PERFORM * FROM completion_baseline_internal.contract_identity();
 IF TG_TABLE_NAME IN('rag_source_reviews','rag_source_claim_receipts') AND r->>'assessment_evidence_id' IS NOT NULL THEN
  RAISE EXCEPTION 'completion baseline: new source/assessment authority denied' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='rag_source_admissions' AND EXISTS(SELECT 1 FROM rag_source_reviews WHERE id=(r->>'review_id')::uuid AND assessment_evidence_id IS NOT NULL) THEN
  RAISE EXCEPTION 'completion baseline: source admission denied' USING ERRCODE='42501'; END IF;
 IF r->>'private_native_version_id' IS NOT NULL OR r->>'native_generation_artifact_id' IS NOT NULL
  OR r->>'schema_version'='candidate_validation_v2' THEN
  RAISE EXCEPTION 'completion baseline: native receiving domain denied' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='tutor_learning_artifacts' AND r->>'owner_kind'='learning_item' THEN owner_uuid:=(r->>'owner_id')::uuid;
 ELSIF TG_TABLE_NAME IN('tutor_learning_item_publication_events','tutor_learning_item_practice_materializations') THEN owner_uuid:=(r->>'version_id')::uuid;
 ELSIF TG_TABLE_NAME='tutor_knowledge_check_response_receipts' THEN owner_uuid:=(r->>'learning_item_version_id')::uuid; END IF;
 IF owner_uuid IS NOT NULL AND (EXISTS(SELECT 1 FROM tutor_item_supply_private_versions WHERE id=owner_uuid)
  OR EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs WHERE version_id=owner_uuid)) THEN
  RAISE EXCEPTION 'completion baseline: P2/P7 original consumer denied' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END $$;

DO $exact_predecessor$ BEGIN
 IF (SELECT prosrc FROM pg_proc WHERE oid='public.rag_registered_capture_guard()'::regprocedure) IS DISTINCT FROM $prior$
DECLARE fetch_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE grant_row rag_registered_source_policies%ROWTYPE;
BEGIN
  IF TG_OP='INSERT' THEN
    SELECT * INTO fetch_row FROM rag_registered_fetch_attempts WHERE id=NEW.fetch_attempt_id;
    SELECT * INTO grant_row FROM rag_registered_source_policies
      WHERE policy_id=NEW.policy_id AND generation=NEW.generation;
    IF NEW.cleared_at IS NOT NULL OR NEW.retention_until<=clock_timestamp() OR
       fetch_row.id IS NULL OR grant_row.policy_id IS NULL OR
       fetch_row.state<>'settled' OR fetch_row.policy_id<>NEW.policy_id OR
       fetch_row.generation<>NEW.generation OR
       fetch_row.response_sha256<>NEW.fetched_sha256 OR
       fetch_row.response_bytes<>NEW.captured_bytes OR
       grant_row.enabled IS NOT TRUE OR grant_row.revoked_at IS NOT NULL OR
       grant_row.expires_at<=clock_timestamp() OR
       grant_row.license_id<>NEW.license_id OR
       NEW.retention_until>grant_row.retention_until OR
       NEW.captured_bytes>grant_row.max_captured_bytes OR
       NEW.final_url<>grant_row.canonical_url OR
       NEW.request_chain->>0<>grant_row.canonical_url OR
       encode(digest(NEW.captured_body,'sha256'),'hex')<>NEW.fetched_sha256 THEN
      RAISE EXCEPTION 'registered capture not authorized or inconsistent' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' OR OLD.cleared_at IS NOT NULL OR NEW.cleared_at IS NULL OR
     NEW.captured_body IS NOT NULL OR
     (to_jsonb(NEW)-'captured_body'-'cleared_at') IS DISTINCT FROM
     (to_jsonb(OLD)-'captured_body'-'cleared_at') THEN
    RAISE EXCEPTION 'registered capture immutable or cleared' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $prior$ THEN RAISE EXCEPTION '600: exact predecessor changed: public.rag_registered_capture_guard()' USING ERRCODE='23514'; END IF;
END $exact_predecessor$;
CREATE OR REPLACE FUNCTION public.rag_registered_capture_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE fetch_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE grant_row rag_registered_source_policies%ROWTYPE;
BEGIN

  IF TG_OP='INSERT' AND NEW.evidence_level='completion_storage_validation' THEN
    PERFORM completion_baseline_internal.assert_validation_caller();
    SELECT * INTO fetch_row FROM rag_registered_fetch_attempts WHERE id=NEW.fetch_attempt_id;
    SELECT * INTO grant_row FROM rag_registered_source_policies WHERE policy_id=NEW.policy_id AND generation=NEW.generation;
    IF NOT EXISTS(SELECT 1 FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current())
      OR NEW.fetch_attempt_id IS NULL
      OR fetch_row.id IS NULL OR grant_row.policy_id IS NULL OR fetch_row.state<>'unknown'
      OR fetch_row.error_code IS DISTINCT FROM 'STORAGE_VALIDATION_NO_FETCH'
      OR fetch_row.policy_id IS DISTINCT FROM NEW.policy_id OR fetch_row.generation IS DISTINCT FROM NEW.generation
      OR grant_row.enabled OR grant_row.revoked_at IS NULL OR grant_row.host<>'completion-storage.invalid'
      OR NEW.license_id<>grant_row.license_id OR NEW.retention_until<>grant_row.retention_until
      OR NEW.retention_until<>'2000-01-01T00:01:00Z'::timestamptz OR NEW.cleared_at IS NOT NULL
      OR NEW.final_url<>grant_row.canonical_url OR NEW.request_chain<>jsonb_build_array(grant_row.canonical_url)
      OR NEW.captured_body IS NULL OR NEW.captured_bytes<>octet_length(NEW.captured_body)
      OR encode(digest(NEW.captured_body,'sha256'),'hex')<>NEW.fetched_sha256
      OR NEW.transport_proof IS NOT NULL THEN
      RAISE EXCEPTION '600: unsigned synthetic capture structure invalid' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='INSERT' THEN
    SELECT * INTO fetch_row FROM rag_registered_fetch_attempts WHERE id=NEW.fetch_attempt_id;
    SELECT * INTO grant_row FROM rag_registered_source_policies
      WHERE policy_id=NEW.policy_id AND generation=NEW.generation;
    IF NEW.cleared_at IS NOT NULL OR NEW.retention_until<=clock_timestamp() OR
       fetch_row.id IS NULL OR grant_row.policy_id IS NULL OR
       fetch_row.state<>'settled' OR fetch_row.policy_id<>NEW.policy_id OR
       fetch_row.generation<>NEW.generation OR
       fetch_row.response_sha256<>NEW.fetched_sha256 OR
       fetch_row.response_bytes<>NEW.captured_bytes OR
       grant_row.enabled IS NOT TRUE OR grant_row.revoked_at IS NOT NULL OR
       grant_row.expires_at<=clock_timestamp() OR
       grant_row.license_id<>NEW.license_id OR
       NEW.retention_until>grant_row.retention_until OR
       NEW.captured_bytes>grant_row.max_captured_bytes OR
       NEW.final_url<>grant_row.canonical_url OR
       NEW.request_chain->>0<>grant_row.canonical_url OR
       encode(digest(NEW.captured_body,'sha256'),'hex')<>NEW.fetched_sha256 THEN
      RAISE EXCEPTION 'registered capture not authorized or inconsistent' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' OR OLD.cleared_at IS NOT NULL OR NEW.cleared_at IS NULL OR
     NEW.captured_body IS NOT NULL OR
     (to_jsonb(NEW)-'captured_body'-'cleared_at') IS DISTINCT FROM
     (to_jsonb(OLD)-'captured_body'-'cleared_at') THEN
    RAISE EXCEPTION 'registered capture immutable or cleared' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

DO $exact_predecessor$ BEGIN
 IF (SELECT prosrc FROM pg_proc WHERE oid='public.rag_source_admission_guard()'::regprocedure) IS DISTINCT FROM $prior$
DECLARE reviewed rag_source_reviews%ROWTYPE;
BEGIN
  -- Independent forward503 maintenance branch; original INSERT/UPDATE body unchanged.
  IF TG_OP='DELETE' AND rag_actual_d_private_delete_allowed((SELECT assessment_evidence_id FROM rag_source_reviews WHERE id=OLD.review_id)) THEN RETURN OLD; END IF;
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'source admission deletion denied' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.active OR
       (to_jsonb(NEW)-'active'-'revoked_at') IS DISTINCT FROM
       (to_jsonb(OLD)-'active'-'revoked_at') THEN
      RAISE EXCEPTION 'source admission immutable or revoked' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO reviewed FROM rag_source_reviews WHERE id=NEW.review_id;
  IF NOT FOUND OR reviewed.status<>'reviewed' OR
     NOT NEW.allowed_usages <@ reviewed.allowed_usages OR
     NEW.policy_generation<>reviewed.policy_generation THEN
    RAISE EXCEPTION 'source review not admitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $prior$ THEN RAISE EXCEPTION '600: exact predecessor changed: public.rag_source_admission_guard()' USING ERRCODE='23514'; END IF;
END $exact_predecessor$;
CREATE OR REPLACE FUNCTION public.rag_source_admission_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE reviewed rag_source_reviews%ROWTYPE;
BEGIN

  IF TG_OP='INSERT' AND NOT NEW.active AND NEW.revoked_at IS NOT NULL AND cardinality(NEW.allowed_usages)=0 THEN
    SELECT * INTO reviewed FROM rag_source_reviews WHERE id=NEW.review_id;
    IF reviewed.status='quarantined' AND reviewed.quality_code='STORAGE_VALIDATION_ONLY'
      AND NEW.policy_generation=reviewed.policy_generation
      AND completion_baseline_internal.validation_source_allowed(reviewed.assessment_evidence_id) THEN RETURN NEW; END IF;
  END IF;
  -- Independent forward503 maintenance branch; original INSERT/UPDATE body unchanged.
  IF TG_OP='DELETE' AND rag_actual_d_private_delete_allowed((SELECT assessment_evidence_id FROM rag_source_reviews WHERE id=OLD.review_id)) THEN RETURN OLD; END IF;
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'source admission deletion denied' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.active OR
       (to_jsonb(NEW)-'active'-'revoked_at') IS DISTINCT FROM
       (to_jsonb(OLD)-'active'-'revoked_at') THEN
      RAISE EXCEPTION 'source admission immutable or revoked' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO reviewed FROM rag_source_reviews WHERE id=NEW.review_id;
  IF NOT FOUND OR reviewed.status<>'reviewed' OR
     NOT NEW.allowed_usages <@ reviewed.allowed_usages OR
     NEW.policy_generation<>reviewed.policy_generation THEN
    RAISE EXCEPTION 'source review not admitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $function$;

-- Explicit replacement attributes: do not rely on omitted CREATE OR REPLACE
-- attributes preserving 599 proconfig. Owner/ACL remain closed to direct callers.
ALTER FUNCTION completion_baseline_internal.enforce_closed_storage() OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION completion_baseline_internal.enforce_closed_storage() SECURITY DEFINER;
ALTER FUNCTION completion_baseline_internal.enforce_closed_storage() VOLATILE;
ALTER FUNCTION completion_baseline_internal.enforce_closed_storage() SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp;
REVOKE ALL ON FUNCTION completion_baseline_internal.enforce_closed_storage() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION completion_baseline_internal.enforce_source_evidence_closed() OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION completion_baseline_internal.enforce_source_evidence_closed() SECURITY DEFINER;
ALTER FUNCTION completion_baseline_internal.enforce_source_evidence_closed() VOLATILE;
ALTER FUNCTION completion_baseline_internal.enforce_source_evidence_closed() SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp;
REVOKE ALL ON FUNCTION completion_baseline_internal.enforce_source_evidence_closed() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION completion_baseline_internal.enforce_closed_native_consumer() OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION completion_baseline_internal.enforce_closed_native_consumer() SECURITY DEFINER;
ALTER FUNCTION completion_baseline_internal.enforce_closed_native_consumer() VOLATILE;
ALTER FUNCTION completion_baseline_internal.enforce_closed_native_consumer() SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp;
REVOKE ALL ON FUNCTION completion_baseline_internal.enforce_closed_native_consumer() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) SECURITY INVOKER;
ALTER FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) IMMUTABLE;
ALTER FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
REVOKE ALL ON FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION public.rag_registered_capture_guard() OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION public.rag_registered_capture_guard() SECURITY INVOKER;
ALTER FUNCTION public.rag_registered_capture_guard() VOLATILE;
ALTER FUNCTION public.rag_registered_capture_guard() SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp;
REVOKE ALL ON FUNCTION public.rag_registered_capture_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION public.rag_source_admission_guard() OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION public.rag_source_admission_guard() SECURITY INVOKER;
ALTER FUNCTION public.rag_source_admission_guard() VOLATILE;
ALTER FUNCTION public.rag_source_admission_guard() SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
REVOKE ALL ON FUNCTION public.rag_source_admission_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION public.rag_source_claim_guard() OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION public.rag_source_claim_guard() SECURITY INVOKER;
ALTER FUNCTION public.rag_source_claim_guard() VOLATILE;
ALTER FUNCTION public.rag_source_claim_guard() SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
REVOKE ALL ON FUNCTION public.rag_source_claim_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

-- Definer privileges belong exclusively to this validation extension. Runtime
-- receives no INSERT authority into P2/P7/source storage; verifier only named ABI.
GRANT SELECT,INSERT ON TABLE public.tutor_learning_plan_sessions,public.tutor_learning_plan_drafts,
 public.rag_material_selections,public.rag_plan_material_bindings,public.tutor_learning_item_blueprints,
 public.tutor_learning_items,public.tutor_learning_item_versions,public.rag_budget_authority_roots,
 public.rag_registered_source_policies,public.rag_registered_fetch_attempts,public.rag_registered_source_captures,
 public.rag_source_reviews,public.rag_source_admissions,public.rag_source_claim_receipts,
 public.grounding_corpus_versions,public.grounding_corpus_source_snapshots,public.grounding_corpus_documents
 TO aearn_cb_schema_20261027;
GRANT SELECT,UPDATE(id) ON TABLE public.tutor_learning_artifacts,public.tutor_runs,
 public.tutor_learning_tracks,public.tutor_track_plan_nodes TO aearn_cb_schema_20261027;
GRANT UPDATE(state,generation,validation_summary_json) ON public.grounding_corpus_versions TO aearn_cb_schema_20261027;
ALTER FUNCTION completion_baseline_internal.validation_scope(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.validation_scope(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION completion_baseline_internal.validation_source_allowed(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.validation_source_allowed(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER FUNCTION completion_baseline_internal.issue_native_binding_graph(uuid,uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.issue_native_binding_graph(uuid,uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
GRANT EXECUTE ON FUNCTION completion_baseline_internal.issue_native_binding_graph(uuid,uuid,uuid) TO aearn_cb_verifier_20261027;
ALTER FUNCTION completion_baseline_internal.issue_shared_subscription_graph(uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.issue_shared_subscription_graph(uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
GRANT EXECUTE ON FUNCTION completion_baseline_internal.issue_shared_subscription_graph(uuid,uuid) TO aearn_cb_verifier_20261027;
ALTER FUNCTION completion_baseline_internal.issue_actual_d_tail_graph(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.issue_actual_d_tail_graph(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
GRANT EXECUTE ON FUNCTION completion_baseline_internal.issue_actual_d_tail_graph(uuid) TO aearn_cb_verifier_20261027;
ALTER FUNCTION public.rag_registered_capture_guard() OWNER TO aearn_cb_schema_20261027;
ALTER FUNCTION public.rag_registered_capture_guard() SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp;
REVOKE ALL ON FUNCTION public.rag_registered_capture_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

DO $exact_predecessor$ BEGIN
 IF (SELECT prosrc FROM pg_proc WHERE oid='public.rag_source_claim_guard()'::regprocedure) IS DISTINCT FROM $prior$
DECLARE primary_review rag_source_reviews%ROWTYPE;
DECLARE secondary_review rag_source_reviews%ROWTYPE;
BEGIN
  -- Independent forward503 maintenance branch; original INSERT/UPDATE body unchanged.
  IF TG_OP='DELETE' AND TG_TABLE_NAME='rag_source_claim_receipts' AND rag_actual_d_private_delete_allowed(OLD.assessment_evidence_id) THEN RETURN OLD; END IF;
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'claim receipt immutable' USING ERRCODE='23514';
  END IF;
  -- No execution verifier adapter is installed in C's default-off runtime.
  -- A text handle alone is not proof that a process was actually isolated/run.
  IF TG_TABLE_NAME='rag_source_claim_receipts' THEN
    IF NEW.method='isolated_execution' THEN
      RAISE EXCEPTION 'isolated execution verifier unavailable' USING ERRCODE='23514';
    END IF;
    SELECT review.* INTO primary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.admission_id AND admission.active FOR SHARE OF review,admission;
    SELECT review.* INTO secondary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.independent_admission_id AND admission.active FOR SHARE OF review,admission;
    IF primary_review.id IS NULL OR secondary_review.id IS NULL OR
       primary_review.document_hash<>NEW.source_document_hash OR
       secondary_review.document_hash<>NEW.independent_document_hash OR
       primary_review.lineage_family=secondary_review.lineage_family OR
       primary_review.subject_id<>NEW.subject_id OR
       secondary_review.subject_id<>NEW.subject_id OR
       primary_review.subject_version<>NEW.subject_version OR
       secondary_review.subject_version<>NEW.subject_version THEN
      RAISE EXCEPTION 'claim lineage or scope unverified' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $prior$ THEN RAISE EXCEPTION '600: exact predecessor changed: public.rag_source_claim_guard()' USING ERRCODE='23514'; END IF;
END $exact_predecessor$;
CREATE OR REPLACE FUNCTION public.rag_source_claim_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE primary_review rag_source_reviews%ROWTYPE;
DECLARE secondary_review rag_source_reviews%ROWTYPE;
BEGIN

  IF TG_OP='INSERT' AND TG_TABLE_NAME='rag_source_claim_receipts' AND NEW.method='completion_storage_validation' THEN
    SELECT r.* INTO primary_review FROM rag_source_reviews r JOIN rag_source_admissions a ON a.review_id=r.id
     WHERE a.id=NEW.admission_id AND NOT a.active AND a.revoked_at IS NOT NULL AND cardinality(a.allowed_usages)=0;
    IF primary_review.id IS NOT NULL AND primary_review.assessment_evidence_id=NEW.assessment_evidence_id
      AND primary_review.status='quarantined' AND primary_review.document_hash=NEW.source_document_hash
      AND primary_review.subject_id=NEW.subject_id AND primary_review.subject_version=NEW.subject_version
      AND NEW.revoked_at IS NOT NULL AND NEW.independent_admission_id IS NULL AND NEW.execution_receipt_handle IS NULL
      AND completion_baseline_internal.validation_source_allowed(NEW.assessment_evidence_id) THEN RETURN NEW; END IF;
    RAISE EXCEPTION '600: synthetic claim owner or structure invalid' USING ERRCODE='23514';
  END IF;
  -- Independent forward503 maintenance branch; original INSERT/UPDATE body unchanged.
  IF TG_OP='DELETE' AND TG_TABLE_NAME='rag_source_claim_receipts' AND rag_actual_d_private_delete_allowed(OLD.assessment_evidence_id) THEN RETURN OLD; END IF;
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'claim receipt immutable' USING ERRCODE='23514';
  END IF;
  -- No execution verifier adapter is installed in C's default-off runtime.
  -- A text handle alone is not proof that a process was actually isolated/run.
  IF TG_TABLE_NAME='rag_source_claim_receipts' THEN
    IF NEW.method='isolated_execution' THEN
      RAISE EXCEPTION 'isolated execution verifier unavailable' USING ERRCODE='23514';
    END IF;
    SELECT review.* INTO primary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.admission_id AND admission.active FOR SHARE OF review,admission;
    SELECT review.* INTO secondary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.independent_admission_id AND admission.active FOR SHARE OF review,admission;
    IF primary_review.id IS NULL OR secondary_review.id IS NULL OR
       primary_review.document_hash<>NEW.source_document_hash OR
       secondary_review.document_hash<>NEW.independent_document_hash OR
       primary_review.lineage_family=secondary_review.lineage_family OR
       primary_review.subject_id<>NEW.subject_id OR
       secondary_review.subject_id<>NEW.subject_id OR
       primary_review.subject_version<>NEW.subject_version OR
       secondary_review.subject_version<>NEW.subject_version THEN
      RAISE EXCEPTION 'claim lineage or scope unverified' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $function$;

-- The final replacement resets proconfig; restore the reviewed path after it.
ALTER FUNCTION public.rag_source_claim_guard() SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
