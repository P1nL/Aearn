-- 547: exact committed finite-KC admission action, no provider authority.
-- Historical generation/review are immutable DATA; only the fresh action is current.

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_committed_child_quality(jsonb)');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('91dc7179a46665986be1018d382386c1772a8e6b007f39937ba2f866fdd4b720')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.assert_committed_child_quality(jsonb)'; END IF;
 
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_committed_child_quality(q jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE; rp tutor_item_supply_shared_revision_preparations%ROWTYPE;
 rr tutor_item_supply_shared_revision_recheck_receipts%ROWTYPE; prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 vp tutor_item_supply_shared_validation_preparations%ROWTYPE; ve tutor_item_supply_shared_validation_evidence%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE; gp tutor_item_supply_shared_generation_policy_bindings%ROWTYPE;
 adoption tutor_item_supply_shared_candidate_continuations%ROWTYPE; rs tutor_item_supply_shared_reservations%ROWTYPE;
 ss tutor_item_supply_shared_runtime_settlements%ROWTYPE; old_lease jsonb; static_data jsonb; expected jsonb; resources jsonb;
 roles text[]; runs text[]; matched text; matches integer; item jsonb; ancestor record; bound timestamptz;
BEGIN
 PERFORM item_supply_internal.assert_committed_child_history('4228be3f-a129-4c06-a531-4d69a37c1d46','4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3','4228be3f-a129-4c06-a531-4d69a37c1d46');
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id='4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3' FOR SHARE;
 SELECT * INTO line FROM tutor_item_supply_shared_revision_lineage WHERE id='4228be3f-a129-4c06-a531-4d69a37c1d46' FOR SHARE;
 SELECT * INTO rp FROM tutor_item_supply_shared_revision_preparations WHERE id=line.preparation_id FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_revision_recheck_receipts WHERE id='f3c2a54f-7f4b-4181-a8c0-ef783f24c919' FOR SHARE;
 SELECT * INTO prep FROM tutor_item_supply_shared_revision_recheck_preparations WHERE id=rr.preparation_id FOR SHARE;
 SELECT * INTO vr FROM tutor_item_supply_shared_pipeline_receipts WHERE id='d358224f-bc80-4aec-8eee-3a6ed6d7b0ec' FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_shared_pipeline_receipts WHERE id='8b74793c-8153-44a2-83ba-3b8ec9fc0cb5' FOR SHARE;
 SELECT * INTO peer FROM tutor_item_supply_shared_pipeline_receipts WHERE id='402d599d-a5f1-45e3-a285-c115e40238f6' FOR SHARE;
 SELECT * INTO vp FROM tutor_item_supply_shared_validation_preparations WHERE id=substring(vr.artifact_key FROM 12)::uuid FOR SHARE;
 SELECT * INTO ve FROM tutor_item_supply_shared_validation_evidence WHERE preparation_id=vp.id FOR SHARE;
 SELECT * INTO gp FROM tutor_item_supply_shared_generation_policy_bindings WHERE candidate_id=a.candidate_id FOR SHARE;
 SELECT * INTO adoption FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=rr.job_id FOR SHARE;
 old_lease:=rr.payload_json->'lease'; static_data:=vp.payload_json->'inputs'->'static_facts';
 bound:=LEAST(prep.valid_until,(old_lease->>'expires_at')::timestamptz,(old_lease->>'parent_deadline')::timestamptz,
   (old_lease->'profile'->>'parent_deadline_at')::timestamptz);
 -- Exactly the already committed receipt. Its historical dispute entries are never rewritten.
 IF rr.id IS NULL OR prep.id IS NULL OR vp.id IS NULL OR ve.id IS NULL OR gp.candidate_id IS NULL OR adoption.job_id IS NULL
  OR rr.snapshot_hash IS DISTINCT FROM 'be64e55940ec7a53c3e51c7ee43a2212828c484ee05a01a0100ec8434bb6fea2'
  OR rr.snapshot_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(rr.payload_json)
  OR rr.job_id IS DISTINCT FROM '4316f475-9655-4f58-baf1-fcc0359be8b8'::uuid
  OR rr.preparation_id IS DISTINCT FROM rr.id OR rr.generation_artifact_id IS DISTINCT FROM a.id
  OR rr.root_id IS DISTINCT FROM a.root_id OR prep.lineage_id IS DISTINCT FROM line.id
  OR rr.payload_json->>'preparation_hash' IS DISTINCT FROM prep.snapshot_hash
  OR rr.payload_json->>'lineage_hash' IS DISTINCT FROM line.snapshot_hash
  OR (rr.validation_receipt_id,rr.blind_receipt_id,rr.review_receipt_id) IS DISTINCT FROM (vr.id,br.id,peer.id)
  OR NOT (prep.created_at<=rr.created_at AND rr.created_at<bound)
  OR item_supply_internal.controlled_counterexample_held(rr.job_id) IS DISTINCT FROM false
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_recheck_receipts x WHERE x.id=rr.id AND x.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_validation_preparations x WHERE x.id=vp.id AND x.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_validation_evidence x WHERE x.id=ve.id AND x.xmin::text::bigint=txid_current()%4294967296)
 THEN RAISE check_violation USING MESSAGE='547 exact committed historical quality required'; END IF;
 -- Producer generation policy remains bound to producer request, never the admission profile.
 IF (gp.job_id,gp.root_id,gp.lease_generation) IS DISTINCT FROM (a.job_id,a.root_id,a.lease_generation)
  OR gp.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json)
  OR gp.profile_hash IS DISTINCT FROM a.request_json->'profile'->>'profile_hash'
  OR gp.policy_hash IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(a)
  OR gp.policy_hash IS DISTINCT FROM '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
  OR adoption.original_job_id IS DISTINCT FROM a.job_id OR adoption.generation_artifact_id IS DISTINCT FROM a.id
  OR adoption.original_lease_generation IS DISTINCT FROM a.lease_generation
  OR adoption.binding_json->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
  OR adoption.binding_json->>'original_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json)
  OR adoption.binding_json->'adoption_lease'->'profile' IS DISTINCT FROM old_lease->'profile'
  OR vp.payload_json->'lease'->'profile' IS DISTINCT FROM old_lease->'profile'
  OR vp.job_id IS DISTINCT FROM rr.job_id OR vp.generation_artifact_id IS DISTINCT FROM a.id
  OR vp.payload_json->'request' IS DISTINCT FROM a.request_json
  OR vp.payload_json->'spec' IS DISTINCT FROM rp.payload_json->'context'->'persistent_family_revision'->'child_specification'
  OR vp.payload_json->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
  OR ve.payload_json->'validation' IS DISTINCT FROM vr.payload_json OR ve.reservation_id IS NOT NULL
  OR ve.payload_json->'terminals' IS DISTINCT FROM '[]'::jsonb
  OR static_data->'validation' IS DISTINCT FROM vr.payload_json
  OR vr.payload_json->>'state' IS DISTINCT FROM 'machine_verified' OR vr.payload_json->>'mode' IS DISTINCT FROM 'static'
  OR a.target_id IS DISTINCT FROM 'python-kc-binding-v1'
 THEN RAISE check_violation USING MESSAGE='547 original producer policy and static validation DATA required'; END IF;
 FOR ancestor IN SELECT x.*,x.xmin::text::bigint=txid_current()%4294967296 AS same_top FROM tutor_item_supply_shared_pipeline_receipts x
  WHERE x.id IN(vr.id,br.id,peer.id) LOOP
  IF ancestor.same_top OR ancestor.job_id IS DISTINCT FROM rr.job_id OR ancestor.generation_artifact_id IS DISTINCT FROM a.id
   OR ancestor.lease_generation::text IS DISTINCT FROM old_lease->>'generation'
   OR ancestor.lease_owner IS DISTINCT FROM old_lease->>'lease_owner'
   OR ancestor.continuation_binding_hash IS DISTINCT FROM adoption.binding_hash
   OR ancestor.source_hash IS DISTINCT FROM a.source_hash OR ancestor.content_hash IS DISTINCT FROM a.content_hash
   OR ancestor.mode IS DISTINCT FROM 'live' OR ancestor.publication_enabled IS DISTINCT FROM false
   OR NOT (prep.created_at<=ancestor.created_at AND ancestor.created_at<=rr.created_at)
  THEN RAISE check_violation USING MESSAGE='547 original committed stage coordinates required'; END IF;
 END LOOP;
 IF br.payload_json->'binding' IS DISTINCT FROM peer.payload_json->'binding'
  OR peer.payload_json->'blind_solve' IS DISTINCT FROM br.payload_json
  OR peer.payload_json->'binding'->>'profile_hash' IS DISTINCT FROM old_lease->'profile'->>'profile_hash'
  OR peer.payload_json->'binding'->>'source_hash' IS DISTINCT FROM a.source_hash
  OR peer.payload_json->'binding'->>'content_hash' IS DISTINCT FROM a.content_hash
  OR peer.payload_json->'binding'->>'policy_hash' IS DISTINCT FROM gp.policy_hash
  OR peer.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM a.item_id::text
  OR peer.payload_json->'binding'->>'version_key' IS DISTINCT FROM a.version_id::text
  OR peer.payload_json->>'state' IS DISTINCT FROM 'completed' OR br.payload_json->>'state' IS DISTINCT FROM 'completed'
  OR peer.payload_json->>'schema_version' IS DISTINCT FROM 'item_supply_review_bundle_v3'
  OR peer.payload_json->'bundle_version' IS DISTINCT FROM prep.payload_json->'bundle_version'
  OR rr.payload_json->>'review_hash' IS DISTINCT FROM peer.receipt_hash
  OR br.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(br.payload_json)
  OR peer.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(peer.payload_json)
 THEN RAISE check_violation USING MESSAGE='547 historical review binding required'; END IF;
 SELECT array_agg(x->>'role' ORDER BY x->>'role') INTO roles FROM jsonb_array_elements(peer.payload_json->'reports') x;
 SELECT array_agg(x->>'run_id') INTO runs FROM (SELECT br.payload_json->'run' x UNION ALL
  SELECT r->'run' FROM jsonb_array_elements(peer.payload_json->'reports') r) all_runs;
 IF roles IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
  OR (SELECT count(DISTINCT x) FROM unnest(runs) x)<>7 THEN
  RAISE check_violation USING MESSAGE='547 seven independent historical runs required'; END IF;
 FOR item IN SELECT br.payload_json->'run' UNION ALL SELECT x->'run' FROM jsonb_array_elements(peer.payload_json->'reports') x LOOP
  IF item->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
   OR item->>'profile_hash' IS DISTINCT FROM old_lease->'profile'->>'profile_hash'
   OR prep.payload_json->'forbidden_run_ids' @> jsonb_build_array(item->>'run_id') THEN
   RAISE check_violation USING MESSAGE='547 historical bounded independent run required'; END IF;
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(prep.payload_json->'ancestor_reviews') LOOP
  PERFORM 1 FROM tutor_item_supply_shared_pipeline_receipts ar WHERE ar.id=(item->>'receipt_id')::uuid
   AND ar.receipt_hash=item->>'receipt_hash' AND ar.xmin::text::bigint<>txid_current()%4294967296;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='547 historical ancestry DATA missing'; END IF;
 END LOOP;
 -- Recover only by unique hash over the PUBLIC legal option-id set, not expected answer.
 SELECT count(*),min(o->>'option_id') INTO matches,matched FROM jsonb_array_elements(a.source_json->'public'->'content'->'options') o
  WHERE item_supply_internal.snapshot_hash(o->'option_id')=br.payload_json->>'solution_hash';
 IF matches<>1 OR jsonb_array_length(a.source_json->'public'->'content'->'options')<>4
  OR (SELECT count(DISTINCT o->>'option_id') FROM jsonb_array_elements(a.source_json->'public'->'content'->'options') o)<>4
  OR br.payload_json->'run'->>'prompt_version' IS DISTINCT FROM 'item-supply-blind-single-choice-id-v3'
  OR br.payload_json->'score'->>'scorer_identity' IS DISTINCT FROM 'finite-static-blind-scorer'
  OR br.payload_json->'score'->>'scorer_version' IS DISTINCT FROM static_data->>'scorer_version'
  OR br.payload_json->'score'->'passed' IS DISTINCT FROM (SELECT o->'accepted' FROM jsonb_array_elements(static_data->'options') o WHERE o->>'option_id'=matched)
  OR br.payload_json->'score'->>'receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
    'binding',br.payload_json->'binding','source_hash',a.source_hash,'specification_hash',item_supply_internal.snapshot_hash(vp.payload_json->'spec'),
    'static_facts_hash',item_supply_internal.snapshot_hash(static_data),'solution_hash',br.payload_json->>'solution_hash','passed',br.payload_json->'score'->'passed'))
 THEN RAISE check_violation USING MESSAGE='547 finite historical score evidence_missing'; END IF;
 SELECT * INTO rs FROM tutor_item_supply_shared_reservations WHERE id=substring(peer.artifact_key FROM 15)::uuid FOR SHARE;
 SELECT * INTO ss FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=rs.id FOR SHARE;
 SELECT jsonb_build_object('requests',0,'input_tokens',0,'output_tokens',0,'execution_seconds',0,'fetches',0,'candidates',0,'revision_rounds',0,'investigation_rounds',0)
  ||COALESCE(jsonb_object_agg(resource_kind,reserved_amount),'{}'::jsonb) INTO resources
  FROM (SELECT DISTINCT resource_kind,reserved_amount FROM tutor_item_supply_runtime_global_reservation_amounts
    WHERE reservation_namespace='shared' AND reservation_id=rs.id) amounts;
 IF rs.id IS NULL OR ss.id IS NULL OR rs.job_id IS DISTINCT FROM rr.job_id OR rs.root_id IS DISTINCT FROM a.root_id
  OR rs.lease_generation IS DISTINCT FROM br.lease_generation OR rs.requests<>7
  OR rs.reservation_key IS DISTINCT FROM 'review.'||replace(a.id::text,'-','')
  OR ss.settlement_key IS DISTINCT FROM rs.reservation_key OR ss.usage_state IS DISTINCT FROM 'unknown'
  OR ss.cost_amount IS NOT NULL OR ss.receipt_hash IS NOT NULL
  OR resources->'requests' IS DISTINCT FROM '7'::jsonb OR resources->'output_tokens' IS DISTINCT FROM '430080'::jsonb
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements x WHERE x.id=ss.id AND x.xmin::text::bigint=txid_current()%4294967296)
 THEN RAISE check_violation USING MESSAGE='547 historical UNKNOWN budget must remain'; END IF;
 expected:=jsonb_build_object('schema_version','committed_child_quality_data_v1','artifact_id',a.id,'artifact_hash',a.artifact_hash,
  'source_hash',a.source_hash,'content_hash',a.content_hash,'producer_job_id',a.job_id,'lineage_id',line.id,'lineage_hash',line.snapshot_hash,
  'recheck_receipt_id',rr.id,'recheck_hash',rr.snapshot_hash,'recheck_preparation_hash',prep.snapshot_hash,
  'validation_preparation_id',vp.id,'validation_preparation_hash',vp.payload_hash,'validation_evidence_id',ve.id,'validation_evidence_hash',ve.payload_hash,
  'validation_receipt_id',vr.id,'validation_hash',vr.receipt_hash,'blind_receipt_id',br.id,'blind_hash',br.receipt_hash,
  'review_receipt_id',peer.id,'review_hash',peer.receipt_hash,'review_lease',old_lease,'validation_lease',vp.payload_json->'lease',
  'historical_continuation_hash',adoption.binding_hash,'binding',peer.payload_json->'binding',
  'specification_hash',item_supply_internal.snapshot_hash(vp.payload_json->'spec'),'request_hash',item_supply_internal.snapshot_hash(a.request_json),
  'inputs_hash',item_supply_internal.snapshot_hash(vp.payload_json->'inputs'),'static_facts_hash',item_supply_internal.snapshot_hash(static_data),
  'matched_answer',matched,'solution_hash',br.payload_json->>'solution_hash','score',br.payload_json->'score',
  'review_budget',jsonb_build_object('reservation_id',rs.id,'settlement_id',ss.id,'settlement_key',ss.settlement_key,
    'reserved',resources,'usage_state','unknown','actual',NULL,'receipt_hash',NULL));
 IF q IS DISTINCT FROM expected THEN RAISE check_violation USING MESSAGE='547 closed exact historical quality DATA required'; END IF;
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_quality(jsonb) FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_committed_child_admission(jsonb)');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('6c0703ad83796e434b5b957b485d3f9e4c26b945ab7c9dd3c8480e17200b91d9')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.assert_committed_child_admission(jsonb)'; END IF;
 
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_committed_child_admission(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE q jsonb:=p->'quality'; lease jsonb:=p->'lease'; ambiguity jsonb:=p->'ambiguity';
 c record; snapshot jsonb; version_row record; header record; successor record; stamp timestamptz; deadline timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off'
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','purpose','admission_id','operation_key','public_task_id','public_slot_id',
   'revision_id','root_id','artifact_id','lineage_id','review_job_id','lease','version','quality','ambiguity','checked_at','valid_until','source_valid_until','capture_txid','provider_requests']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'committed_child_admission_v1'
  OR p->>'purpose' IS DISTINCT FROM 'admission_only_no_provider'
  OR p->>'admission_id' IS DISTINCT FROM '8bcf957c-d772-534e-9d97-786b609ca639'
  OR p->>'operation_key' IS DISTINCT FROM 'committed.admission.f3c2a54f7f4b4181a8c0ef783f24c919'
  OR p->>'public_task_id' IS DISTINCT FROM '9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c'
  OR p->>'revision_id' IS DISTINCT FROM '9bf34de8-7503-544d-bcd6-fde59925826c'
  OR p->>'artifact_id' IS DISTINCT FROM '4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3'
  OR p->>'lineage_id' IS DISTINCT FROM '4228be3f-a129-4c06-a531-4d69a37c1d46'
  OR p->>'root_id' IS DISTINCT FROM '7d4b85ba-a0ec-4348-ac11-3401c6bded47'
  OR p->>'review_job_id' IS DISTINCT FROM '4316f475-9655-4f58-baf1-fcc0359be8b8'
  OR p->'provider_requests' IS DISTINCT FROM '0'::jsonb OR COALESCE((p->>'capture_txid')::bigint>0,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='547 exact closed admission-only action required'; END IF;
 PERFORM item_supply_internal.assert_committed_child_quality(q);
 SELECT * INTO version_row FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=(p->>'public_task_id')::uuid
  AND record_kind='version' AND payload_json->>'revision_id'=p->>'revision_id' FOR SHARE;
 SELECT * INTO header FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=(p->>'public_task_id')::uuid AND record_kind='task' FOR SHARE;
 IF version_row.id IS NULL OR header.id IS NULL OR p->'version' IS DISTINCT FROM version_row.payload_json
  OR p->'version'->>'artifact_id' IS DISTINCT FROM p->>'artifact_id'
  OR p->'version'->>'public_slot_id' IS DISTINCT FROM p->>'public_slot_id'
  OR p->'version'->>'root_id' IS DISTINCT FROM p->>'root_id'
  OR item_supply_internal.snapshot_hash(p->'version'->'specification') IS DISTINCT FROM q->>'specification_hash'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.public_task_id=version_row.public_task_id
    AND j.record_kind IN('version','qualified') AND j.payload_json->>'public_slot_id'=p->>'public_slot_id'
    AND (j.payload_json->>'revision_seq')::integer>(p->'version'->>'revision_seq')::integer)
 THEN RAISE check_violation USING MESSAGE='547 original same-task same-slot child version required'; END IF;
 -- PRIVATE current user/epoch/actual-D mapping remains with the original source owner.
 SELECT b.* INTO successor FROM tutor_item_supply_private_persistent_pack_journal b
  JOIN tutor_item_supply_private_persistent_pack_journal e ON b.id=(e.payload_json->>'source_successor_id')::uuid
  JOIN tutor_item_supply_shared_revision_preparations rp ON rp.payload_json->>'parent_job_id'=e.payload_json->>'execution_job_id'
  WHERE rp.id='4228be3f-a129-4c06-a531-4d69a37c1d46' AND e.record_kind='committed_revision_execution'
    AND b.record_kind='source_mapping_successor' FOR SHARE OF b,e,rp;
 IF successor.id IS NULL OR (p->>'source_valid_until')::timestamptz IS DISTINCT FROM (successor.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='547 original current source bound required'; END IF;
 PERFORM item_supply_internal.assert_source_mapping_successor(successor.payload_json);
 SELECT co.*,j.root_id,j.parent_job_id,j.job_key,pr.profile_hash,pr.profile_json INTO c
  FROM tutor_item_supply_shared_job_controls co JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id
  JOIN tutor_item_supply_parameter_profiles pr ON pr.id=co.profile_id WHERE co.job_id=(lease->>'job_id')::uuid FOR SHARE OF co,j,pr;
 snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1' THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 stamp:=clock_timestamp();
 deadline:=LEAST(c.lease_expires_at,c.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz,
  (snapshot->>'bound_at')::timestamptz+interval '15 minutes',(successor.payload_json->>'valid_until')::timestamptz);
 IF c.job_id IS NULL OR c.root_id::text IS DISTINCT FROM p->>'root_id' OR c.parent_job_id IS NOT NULL
  OR c.job_key IS DISTINCT FROM encode(sha256(convert_to(c.root_id::text||chr(31)||'committed.admission.8bcf957cd772534e9d97786b609ca639','UTF8')),'hex')
  OR c.state IS DISTINCT FROM 'leased' OR c.lease_generation IS DISTINCT FROM 1
  OR c.lease_owner IS DISTINCT FROM 'committed.admission.8bcf957cd772534e9d97786b609ca639'
  OR lease->>'visibility' IS DISTINCT FROM 'public' OR lease->'owner_id' IS DISTINCT FROM 'null'::jsonb
  OR lease->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
  OR lease->>'lease_owner' IS DISTINCT FROM c.lease_owner OR lease->>'generation' IS DISTINCT FROM c.lease_generation::text
  OR lease->>'state_version' IS DISTINCT FROM c.state_version::text OR lease->'profile' IS DISTINCT FROM snapshot
  OR (lease->>'expires_at')::timestamptz IS DISTINCT FROM c.lease_expires_at
  OR (lease->>'parent_deadline')::timestamptz IS DISTINCT FROM c.parent_deadline
  OR snapshot->>'profile_hash' IS DISTINCT FROM c.profile_hash
  OR c.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.shared.admission-only-v1'
  OR c.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'no-provider-admission-v1'
  OR snapshot->'values'->'stage_deadline_ms' IS DISTINCT FROM '900000'::jsonb
  OR snapshot->'values'->'parent_deadline_ms' IS DISTINCT FROM '900000'::jsonb
  OR item_supply_internal.controlled_counterexample_held(c.job_id) IS DISTINCT FROM false
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=c.job_id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=c.job_id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts WHERE job_id=c.job_id AND artifact_kind<>'admission_evaluation')
  OR COALESCE((p->>'checked_at')::timestamptz<=stamp AND stamp<(p->>'valid_until')::timestamptz
    AND (p->>'checked_at')::timestamptz>=(snapshot->>'bound_at')::timestamptz
    AND (p->>'valid_until')::timestamptz<=deadline,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='547 fresh unfunded admission control required'; END IF;
 -- New local observation over the exact finite public plan; no fabricated historical run.
 IF item_supply_internal.snapshot_keys(ambiguity,ARRAY['schema_version','plan','run_id','started_at','completed_at','parent_deadline_at','mode','terminals',
   'selected_case_results','alternative_case_results','alternative_predictions_matched','conclusion','publication_enabled']) IS DISTINCT FROM true
  OR ambiguity->>'schema_version' IS DISTINCT FROM 'native_finite_ambiguity_receipt_v1'
  OR ambiguity->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
  OR item_supply_internal.snapshot_hash(ambiguity->'plan') IS DISTINCT FROM '50349f0448c672adb6ec9f42973a1ed8e17ab80dd03b24017c615012f28b4e01'
  OR ambiguity->>'mode' IS DISTINCT FROM 'static_options' OR ambiguity->'terminals' IS DISTINCT FROM '[]'::jsonb
  OR ambiguity->'selected_case_results' IS DISTINCT FROM '[true]'::jsonb
  OR ambiguity->'alternative_case_results' IS DISTINCT FROM '[false,false,false]'::jsonb
  OR ambiguity->'alternative_predictions_matched' IS DISTINCT FROM '[true,true,true]'::jsonb
  OR ambiguity->>'conclusion' IS DISTINCT FROM 'registered_option_propositions_unique'
  OR COALESCE(ambiguity->>'run_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
  OR (ambiguity->>'parent_deadline_at')::timestamptz IS DISTINCT FROM (p->>'valid_until')::timestamptz
  OR COALESCE((ambiguity->>'started_at')::timestamptz>=(p->>'checked_at')::timestamptz
    AND (ambiguity->>'completed_at')::timestamptz>=(ambiguity->>'started_at')::timestamptz
    AND (ambiguity->>'completed_at')::timestamptz<=stamp,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='547 new finite ambiguity observation required'; END IF;
 IF clock_timestamp()>=deadline OR clock_timestamp()>=(p->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='547 final current admission bound expired'; END IF;
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_admission(jsonb) FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.committed_child_admission_for_job(uuid)');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('d1d767f1e8b795b7d9449ddb1671e0f180b23783961253b282720c1d84992da3')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.committed_child_admission_for_job(uuid)'; END IF;
 
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.committed_child_admission_for_job(operation_job uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE r tutor_item_supply_shared_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_shared_persistent_pack_journal WHERE record_kind='committed_admission' AND job_id=operation_job FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF r.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(r.payload_json)
  OR (r.payload_json->>'capture_txid')::bigint=txid_current() THEN
  RAISE check_violation USING MESSAGE='547 admission capability must first commit'; END IF;
 PERFORM item_supply_internal.assert_committed_child_admission(r.payload_json);
 RETURN r.payload_json;
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.committed_child_admission_for_job(uuid) FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission_v3(jsonb)');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('e798ca1018007fc2b9c5863ad14d7f2287424da38e5f81f51d8778c26becc24c')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.assert_normal_revision_readmission_v3(jsonb)'; END IF;
 
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_revision_readmission_v3(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE action jsonb; q jsonb; f jsonb:=p->'facts_payload'; expected jsonb;
 child tutor_item_supply_shared_generation_artifacts%ROWTYPE; vp tutor_item_supply_shared_validation_preparations%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE; peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
BEGIN
 action:=item_supply_internal.committed_child_admission_for_job((p->'lease'->>'job_id')::uuid);
 IF action IS NULL THEN RAISE check_violation USING MESSAGE='547 committed admission original capability required'; END IF;
 q:=action->'quality';
 SELECT * INTO child FROM tutor_item_supply_shared_generation_artifacts WHERE id=(q->>'artifact_id')::uuid;
 SELECT * INTO vp FROM tutor_item_supply_shared_validation_preparations WHERE id=(q->>'validation_preparation_id')::uuid;
 SELECT * INTO vr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(q->>'validation_receipt_id')::uuid;
 SELECT * INTO br FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(q->>'blind_receipt_id')::uuid;
 SELECT * INTO peer FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(q->>'review_receipt_id')::uuid;
 expected:=jsonb_build_object('schema_version','normal_revision_readmission_v3','receipt_id',action->>'admission_id','root_id',child.root_id,
  'lineage_id',q->>'lineage_id','lineage_hash',q->>'lineage_hash','recheck_receipt_id',q->>'recheck_receipt_id','recheck_hash',q->>'recheck_hash',
  'artifact_id',child.id,'artifact_hash',child.artifact_hash,'lease',action->'lease','binding',q->'binding',
  'validation_preparation_id',vp.id,'validation_receipt_id',vr.id,'validation_hash',vr.receipt_hash,
  'blind_receipt_id',br.id,'blind_hash',br.receipt_hash,'review_receipt_id',peer.id,'review_hash',peer.receipt_hash,
  'policy_hash',q->'binding'->>'policy_hash','facts_receipt_id',action->>'admission_id','facts_payload_hash',item_supply_internal.snapshot_hash(f),
  'facts_payload',f,'checked_at',p->'checked_at','valid_until',p->'valid_until','publication_enabled',false,'historical_findings_discharged',false,
  'admission_action_id',action->>'admission_id','admission_action_hash',item_supply_internal.snapshot_hash(action));
 IF p IS DISTINCT FROM expected OR f->'lease' IS DISTINCT FROM action->'lease'
  OR f->>'profile_hash' IS DISTINCT FROM action->'lease'->'profile'->>'profile_hash'
  OR f->'continuation_binding_hash' IS DISTINCT FROM 'null'::jsonb
  OR f->'ambiguity' IS DISTINCT FROM action->'ambiguity' OR f->'review_budget' IS DISTINCT FROM q->'review_budget'
  OR f->'validation_budget' IS DISTINCT FROM 'null'::jsonb
  OR COALESCE((p->>'checked_at')::timestamptz>=(action->>'checked_at')::timestamptz
   AND (p->>'checked_at')::timestamptz<=clock_timestamp() AND clock_timestamp()<(p->>'valid_until')::timestamptz
   AND (p->>'valid_until')::timestamptz<=(action->>'valid_until')::timestamptz,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='547 exact full fresh normal facts binding required'; END IF;
 IF f->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v1'
   OR p->>'facts_payload_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f)
   OR f->>'receipt_id' IS DISTINCT FROM p->>'receipt_id' OR f->>'generation_artifact_id' IS DISTINCT FROM child.id::text
   OR f->>'root_id' IS DISTINCT FROM child.root_id::text OR f->>'artifact_hash' IS DISTINCT FROM child.artifact_hash
   OR f->>'item_id' IS DISTINCT FROM child.item_id::text OR f->>'version_id' IS DISTINCT FROM child.version_id::text
   OR f->>'target_id' IS DISTINCT FROM child.target_id OR f->>'target_definition_hash' IS DISTINCT FROM child.target_definition_hash
   OR f->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(vp.payload_json->'spec')
   OR f->'evidence'->'binding' IS DISTINCT FROM p->'binding' OR f->'evaluation'->'binding' IS DISTINCT FROM p->'binding'
   OR f->'evidence'->'source_current' IS DISTINCT FROM 'true'::jsonb
   OR jsonb_typeof(f->'evidence'->'source_claim_receipt_hashes') IS DISTINCT FROM 'array'
   OR jsonb_array_length(f->'evidence'->'source_claim_receipt_hashes')=0
   OR f->'evidence'->'source_claim_receipt_hashes' IS DISTINCT FROM (
      SELECT jsonb_agg(h ORDER BY h) FROM (SELECT DISTINCT leaf.value AS h
        FROM jsonb_array_elements(child.receipt_json->'sources') source
        CROSS JOIN LATERAL jsonb_array_elements(source.value->'claim_receipt_hashes') leaf) hashes)
   OR f->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f->'evidence')
   OR f->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR f->'evaluation'->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR f->'evaluation'->>'schema_version' IS DISTINCT FROM 'item_supply_admission_evaluation_v3'
   OR (f->>'checked_at')::timestamptz IS DISTINCT FROM (p->>'checked_at')::timestamptz
   OR (f->>'valid_until')::timestamptz IS DISTINCT FROM (p->>'valid_until')::timestamptz
   OR f->>'validation_preparation_id' IS DISTINCT FROM vp.id::text
   OR f->>'validation_receipt_id' IS DISTINCT FROM vr.id::text OR f->>'validation_receipt_hash' IS DISTINCT FROM vr.receipt_hash
   OR f->>'blind_receipt_id' IS DISTINCT FROM br.id::text OR f->>'blind_receipt_hash' IS DISTINCT FROM br.receipt_hash
   OR f->>'review_receipt_id' IS DISTINCT FROM peer.id::text OR f->>'review_receipt_hash' IS DISTINCT FROM peer.receipt_hash THEN
   RAISE check_violation USING MESSAGE='normal original full facts/evaluation exact hash required';
 END IF;

 IF item_supply_internal.shared_evaluation_policy_matches(child,f->'evaluation',peer.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='547 full original policy evaluation required'; END IF;
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission_v3(jsonb) FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission(jsonb)');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('45d342fc646610142261e290bd12ca7d638a8c5148d37c0e3805d0b90f3bbc6c','db1ab4aaf95bfb60fd2e48d6237cffb46f4d09384e4529a83a90ecb8c9ec72ae')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.assert_normal_revision_readmission(jsonb)'; END IF;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='547 required prior receiver: item_supply_internal.assert_normal_revision_readmission(jsonb)'; END IF;
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_revision_readmission(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE child tutor_item_supply_shared_generation_artifacts%ROWTYPE; parent tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE; rp tutor_item_supply_shared_revision_preparations%ROWTYPE;
 rr tutor_item_supply_shared_revision_recheck_receipts%ROWTYPE; prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE; vp tutor_item_supply_shared_validation_preparations%ROWTYPE;
 gp tutor_item_supply_shared_generation_policy_bindings%ROWTYPE;
 control_row record; stamp timestamptz; snapshot jsonb; f jsonb:=p->'facts_payload'; roles text[];
BEGIN
 IF p->>'schema_version'='normal_revision_readmission_v3' THEN
  PERFORM item_supply_internal.assert_normal_revision_readmission_v3(p); RETURN;
 END IF;
 IF p->>'schema_version'='normal_revision_readmission_v2' THEN
   PERFORM item_supply_internal.assert_normal_revision_readmission_v2(p); RETURN;
 END IF;
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')<>'off' THEN
   RAISE check_violation USING MESSAGE='normal readmission B1d read committed read-write only';
 END IF;
 SELECT * INTO child FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 IF child.id IS NULL OR item_supply_internal.controlled_counterexample_held(child.job_id) IS DISTINCT FROM false THEN
   RAISE check_violation USING MESSAGE='controlled experiment ancestry held';
 END IF;
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','receipt_id','root_id','lineage_id','lineage_hash',
   'recheck_receipt_id','recheck_hash','artifact_id','artifact_hash','lease','binding','validation_preparation_id',
   'validation_receipt_id','validation_hash','blind_receipt_id','blind_hash','review_receipt_id','review_hash',
   'policy_hash','facts_receipt_id','facts_payload_hash','facts_payload','checked_at','valid_until',
   'publication_enabled','historical_findings_discharged']) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM 'normal_revision_readmission_v1'
   OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR p->'historical_findings_discharged' IS DISTINCT FROM 'false'::jsonb
   OR p->>'receipt_id' IS DISTINCT FROM p->>'facts_receipt_id'
   OR item_supply_internal.native_revision_descendant(child.job_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='closed explicit normal revision permission required';
 END IF;
 SELECT * INTO line FROM tutor_item_supply_shared_revision_lineage WHERE id=(p->>'lineage_id')::uuid FOR SHARE;
 SELECT * INTO rp FROM tutor_item_supply_shared_revision_preparations WHERE id=line.preparation_id FOR SHARE;
 SELECT * INTO parent FROM tutor_item_supply_shared_generation_artifacts WHERE id=line.parent_artifact_id FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_revision_recheck_receipts WHERE id=(p->>'recheck_receipt_id')::uuid FOR SHARE;
 SELECT * INTO prep FROM tutor_item_supply_shared_revision_recheck_preparations WHERE id=rr.preparation_id FOR SHARE;
 stamp:=clock_timestamp();
 IF line.id IS NULL OR rp.id IS NULL OR parent.id IS NULL OR rr.id IS NULL OR prep.id IS NULL
   OR line.snapshot_hash IS DISTINCT FROM p->>'lineage_hash' OR rr.snapshot_hash IS DISTINCT FROM p->>'recheck_hash'
   OR (line.root_id,line.child_job_id,line.child_artifact_id) IS DISTINCT FROM (child.root_id,child.job_id,child.id)
   OR (rr.root_id,rr.job_id,rr.generation_artifact_id) IS DISTINCT FROM (child.root_id,child.job_id,child.id)
   OR prep.lineage_id IS DISTINCT FROM line.id OR prep.valid_until<=stamp OR rp.valid_until<=stamp
   OR child.artifact_hash IS DISTINCT FROM p->>'artifact_hash' OR child.root_id::text IS DISTINCT FROM p->>'root_id'
   OR line.payload_json->>'child_substantive_hash' IS DISTINCT FROM item_supply_internal.revision_substantive_hash(child.source_json)
   OR item_supply_internal.revision_substantive_hash(child.source_json)=item_supply_internal.revision_substantive_hash(parent.source_json)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_lineage x WHERE x.id=line.id AND x.xmin::text::bigint=(txid_current()%4294967296))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_recheck_receipts x WHERE x.id=rr.id AND x.xmin::text::bigint=(txid_current()%4294967296))
   OR rr.payload_json->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
   OR rr.payload_json->'admission_eligible' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE check_violation USING MESSAGE='normal current committed substantive lineage/recheck required';
 END IF;
 SELECT co.*,j.root_id INTO control_row FROM tutor_item_supply_shared_job_controls co
   JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id WHERE co.job_id=child.job_id FOR SHARE OF co,j;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='normal current child control required'; END IF;
 stamp:=clock_timestamp(); -- Fresh AFTER the control/queue lock wait.
 snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 IF control_row.state IS DISTINCT FROM 'leased' OR control_row.root_id IS DISTINCT FROM child.root_id
   OR control_row.lease_expires_at IS NULL OR control_row.parent_deadline IS NULL
   OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
   OR p->'lease' IS DISTINCT FROM rr.payload_json->'lease'
   OR p->'lease' IS DISTINCT FROM f->'lease'
   OR p->'lease'->'profile' IS DISTINCT FROM snapshot
   OR p->'lease'->>'job_id' IS DISTINCT FROM child.job_id::text
   OR p->'lease'->>'visibility' IS DISTINCT FROM 'public'
   OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
   OR p->'lease'->>'lease_owner' IS DISTINCT FROM control_row.lease_owner
   OR p->'lease'->>'generation' IS DISTINCT FROM control_row.lease_generation::text
   OR p->'lease'->>'state_version' IS DISTINCT FROM control_row.state_version::text
   OR (p->>'checked_at')::timestamptz IS NULL OR (p->>'valid_until')::timestamptz IS NULL
   OR (p->>'checked_at')::timestamptz>stamp OR (p->>'valid_until')::timestamptz<=stamp
   OR (p->>'checked_at')::timestamptz>=(p->>'valid_until')::timestamptz
   OR (p->>'valid_until')::timestamptz>LEAST(rp.valid_until,prep.valid_until,control_row.lease_expires_at,
     control_row.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz,
     (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) THEN
   RAISE check_violation USING MESSAGE='normal exact current source/lease bound required';
 END IF;
 SELECT * INTO vr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'validation_receipt_id')::uuid FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'blind_receipt_id')::uuid FOR SHARE;
 SELECT * INTO peer FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'review_receipt_id')::uuid FOR SHARE;
 SELECT * INTO vp FROM tutor_item_supply_shared_validation_preparations WHERE id=(p->>'validation_preparation_id')::uuid FOR SHARE;
 SELECT * INTO gp FROM tutor_item_supply_shared_generation_policy_bindings WHERE candidate_id=child.candidate_id FOR SHARE;
 stamp:=clock_timestamp(); -- Fresh AFTER ALL new-stage/policy receipt locks.
 IF vr.id IS NULL OR br.id IS NULL OR peer.id IS NULL OR vp.id IS NULL OR gp.candidate_id IS NULL
   OR (rr.validation_receipt_id,rr.blind_receipt_id,rr.review_receipt_id) IS DISTINCT FROM (vr.id,br.id,peer.id)
   OR (vr.generation_artifact_id,br.generation_artifact_id,peer.generation_artifact_id,vp.generation_artifact_id)
      IS DISTINCT FROM (child.id,child.id,child.id,child.id)
   OR (vr.job_id,br.job_id,peer.job_id,vp.job_id,gp.job_id) IS DISTINCT FROM (child.job_id,child.job_id,child.job_id,child.job_id,child.job_id)
   OR vr.artifact_kind IS DISTINCT FROM 'validation' OR br.artifact_kind IS DISTINCT FROM 'blind_solve'
   OR peer.artifact_kind IS DISTINCT FROM 'review_bundle' OR (vr.mode,br.mode,peer.mode) IS DISTINCT FROM ('live','live','live')
   OR (vr.lease_generation,br.lease_generation,peer.lease_generation,vp.lease_generation,gp.lease_generation)
      IS DISTINCT FROM (control_row.lease_generation,control_row.lease_generation,control_row.lease_generation,control_row.lease_generation,control_row.lease_generation)
   OR (vr.lease_owner,br.lease_owner,peer.lease_owner,vp.lease_owner)
      IS DISTINCT FROM (control_row.lease_owner,control_row.lease_owner,control_row.lease_owner,control_row.lease_owner)
   OR vr.receipt_hash IS DISTINCT FROM p->>'validation_hash' OR br.receipt_hash IS DISTINCT FROM p->>'blind_hash'
   OR peer.receipt_hash IS DISTINCT FROM p->>'review_hash'
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts x WHERE x.id IN (vr.id,br.id,peer.id) AND x.xmin::text::bigint=(txid_current()%4294967296))
   OR p->'binding' IS DISTINCT FROM peer.payload_json->'binding' OR p->'binding' IS DISTINCT FROM br.payload_json->'binding'
   OR peer.payload_json->'blind_solve' IS DISTINCT FROM br.payload_json
   OR peer.payload_json->>'schema_version' IS DISTINCT FROM 'item_supply_review_bundle_v3'
   OR p->>'policy_hash' IS DISTINCT FROM '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
   OR gp.policy_hash IS DISTINCT FROM p->>'policy_hash'
   OR gp.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(child.request_json)
   OR gp.profile_hash IS DISTINCT FROM snapshot->>'profile_hash'
   OR p->'binding'->>'policy_hash' IS DISTINCT FROM gp.policy_hash
   OR p->'binding'->>'source_hash' IS DISTINCT FROM child.source_hash
   OR p->'binding'->>'content_hash' IS DISTINCT FROM child.content_hash
   OR p->'binding'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
   OR p->'binding'->>'candidate_key' IS DISTINCT FROM child.item_id::text
   OR p->'binding'->>'version_key' IS DISTINCT FROM child.version_id::text
   OR peer.payload_json->'bundle_version' IS DISTINCT FROM prep.payload_json->'bundle_version'
   OR vr.payload_json->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2'
   OR vr.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
   OR (vr.payload_json->'legacy_receipt' IS DISTINCT FROM 'null'::jsonb AND vr.payload_json->'legacy_receipt'->'passed' IS DISTINCT FROM 'true'::jsonb) THEN
   RAISE check_violation USING MESSAGE='normal original new diagnostic blind/validation/full six binding required';
 END IF;
 SELECT array_agg(role->>'role' ORDER BY role->>'role') INTO roles FROM jsonb_array_elements(peer.payload_json->'reports') role;
 IF roles IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'reports') role
     WHERE role->'binding' IS DISTINCT FROM p->'binding'
       OR role->'run'->>'run_id' IN (SELECT value#>>'{}' FROM jsonb_array_elements(prep.payload_json->'forbidden_run_ids')))
   OR br.payload_json->'run'->>'run_id' IN (SELECT value#>>'{}' FROM jsonb_array_elements(prep.payload_json->'forbidden_run_ids')) THEN
   RAISE check_violation USING MESSAGE='normal independent six/ancestor identities required';
 END IF;
 IF f->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v1'
   OR p->>'facts_payload_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f)
   OR f->>'receipt_id' IS DISTINCT FROM p->>'receipt_id' OR f->>'generation_artifact_id' IS DISTINCT FROM child.id::text
   OR f->>'root_id' IS DISTINCT FROM child.root_id::text OR f->>'artifact_hash' IS DISTINCT FROM child.artifact_hash
   OR f->>'item_id' IS DISTINCT FROM child.item_id::text OR f->>'version_id' IS DISTINCT FROM child.version_id::text
   OR f->>'target_id' IS DISTINCT FROM child.target_id OR f->>'target_definition_hash' IS DISTINCT FROM child.target_definition_hash
   OR f->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(vp.payload_json->'spec')
   OR f->'evidence'->'binding' IS DISTINCT FROM p->'binding' OR f->'evaluation'->'binding' IS DISTINCT FROM p->'binding'
   OR f->'evidence'->'source_current' IS DISTINCT FROM 'true'::jsonb
   OR jsonb_typeof(f->'evidence'->'source_claim_receipt_hashes') IS DISTINCT FROM 'array'
   OR jsonb_array_length(f->'evidence'->'source_claim_receipt_hashes')=0
   OR f->'evidence'->'source_claim_receipt_hashes' IS DISTINCT FROM (
      SELECT jsonb_agg(h ORDER BY h) FROM (SELECT DISTINCT leaf.value AS h
        FROM jsonb_array_elements(child.receipt_json->'sources') source
        CROSS JOIN LATERAL jsonb_array_elements(source.value->'claim_receipt_hashes') leaf) hashes)
   OR f->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f->'evidence')
   OR f->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR f->'evaluation'->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR f->'evaluation'->>'schema_version' IS DISTINCT FROM 'item_supply_admission_evaluation_v3'
   OR (f->>'checked_at')::timestamptz IS DISTINCT FROM (p->>'checked_at')::timestamptz
   OR (f->>'valid_until')::timestamptz IS DISTINCT FROM (p->>'valid_until')::timestamptz
   OR f->>'validation_preparation_id' IS DISTINCT FROM vp.id::text
   OR f->>'validation_receipt_id' IS DISTINCT FROM vr.id::text OR f->>'validation_receipt_hash' IS DISTINCT FROM vr.receipt_hash
   OR f->>'blind_receipt_id' IS DISTINCT FROM br.id::text OR f->>'blind_receipt_hash' IS DISTINCT FROM br.receipt_hash
   OR f->>'review_receipt_id' IS DISTINCT FROM peer.id::text OR f->>'review_receipt_hash' IS DISTINCT FROM peer.receipt_hash THEN
   RAISE check_violation USING MESSAGE='normal original full facts/evaluation exact hash required';
 END IF;
 -- Last acceptance clock after every lock/current-authority/read/composition.
 -- Earlier snapshots are not proof that a bound survived a lock wait.
 stamp:=clock_timestamp();
 IF item_supply_internal.controlled_counterexample_held(child.job_id) IS DISTINCT FROM false
   OR control_row.lease_expires_at IS NULL OR control_row.parent_deadline IS NULL
   OR stamp>=control_row.lease_expires_at OR stamp>=control_row.parent_deadline
   OR stamp>=rp.valid_until OR stamp>=prep.valid_until
   OR stamp>=(p->>'valid_until')::timestamptz
   OR stamp>=(snapshot->>'parent_deadline_at')::timestamptz
   OR stamp>=(snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
   OR gp.policy_hash IS DISTINCT FROM '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(rp.payload_json->'source_deadlines') source_bound
     WHERE (source_bound.value->>'retained_until')::timestamptz IS NULL
       OR (source_bound.value->>'retained_until')::timestamptz<=stamp) THEN
   RAISE check_violation USING MESSAGE='normal readmission final current bound/controlled/policy expired';
 END IF;
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission(jsonb) FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('enforce_item_supply_shared_admission_facts()');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('3c10ae9c08a194c8cdf3e1758011f5a41a6cc034d71393f3a1be3cbb1c9580ee','93a806a714bf7c0bf65a683e89eef03f6a3460ca204cf2913fc5eceaa12ce17f')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: enforce_item_supply_shared_admission_facts()'; END IF;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='547 required prior receiver: enforce_item_supply_shared_admission_facts()'; END IF;
END $guard547$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_admission_facts() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE p jsonb:=NEW.payload_json; a public.tutor_item_supply_shared_generation_artifacts%ROWTYPE; c record; prep record; v record; b record; r record;
  usage record; reservation record; budget jsonb; snapshot jsonb; t timestamptz; kind text; rid uuid;
  action jsonb; quality_job uuid:=NEW.job_id; quality_generation integer:=NEW.lease_generation;
  quality_owner text:=NEW.lease_owner; quality_profile text:=NEW.profile_hash; quality_continuation text:=NEW.continuation_binding_hash;
BEGIN
  action:=item_supply_internal.committed_child_admission_for_job(NEW.job_id);
  IF action IS NOT NULL THEN
    IF p->'lease' IS DISTINCT FROM action->'lease' OR NEW.generation_artifact_id::text IS DISTINCT FROM action->>'artifact_id'
      OR NEW.id::text IS DISTINCT FROM action->>'admission_id' OR NEW.continuation_binding_hash IS NOT NULL
      OR p->'ambiguity' IS DISTINCT FROM action->'ambiguity' OR p->'review_budget' IS DISTINCT FROM action->'quality'->'review_budget'
      OR p->'evidence'->'binding' IS DISTINCT FROM action->'quality'->'binding'
      OR item_supply_internal.normal_revision_readmission_matches(NEW.generation_artifact_id,NEW.id,item_supply_internal.snapshot_hash(p)) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='547 exact normal permission and historical quality required'; END IF;
    quality_job:=(action->'quality'->'review_lease'->>'job_id')::uuid;
    quality_generation:=(action->'quality'->'review_lease'->>'generation')::integer;
    quality_owner:=action->'quality'->'review_lease'->>'lease_owner';
    quality_profile:=action->'quality'->'binding'->>'profile_hash';
    quality_continuation:=action->'quality'->>'historical_continuation_hash';
  END IF;
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared facts B1d only';
  END IF;
  SELECT co.*,j.root_id,pr.profile_hash INTO c FROM tutor_item_supply_shared_job_controls co
    JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id
    JOIN tutor_item_supply_parameter_profiles pr ON pr.id=co.profile_id
    WHERE co.job_id=NEW.job_id FOR SHARE OF co;
  t:=clock_timestamp();
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared facts current job missing'; END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.profile_hash<>NEW.profile_hash
    OR c.lease_owner IS DISTINCT FROM NEW.lease_owner OR c.lease_generation<>NEW.lease_generation
    OR c.state_version<>NEW.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR p->'lease'->'profile' IS DISTINCT FROM snapshot
    OR (p->>'checked_at')::timestamptz>t OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz)
    OR (p->>'checked_at')::timestamptz>=(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts current lease expired or mismatched';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id OR a.item_id<>NEW.item_id OR a.version_id<>NEW.version_id
    OR a.source_hash<>NEW.source_hash OR a.content_hash<>NEW.content_hash
    OR (CASE WHEN action IS NOT NULL THEN NEW.generation_artifact_id::text=action->>'artifact_id'
      ELSE item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,
      NEW.generation_artifact_id,NEW.continuation_binding_hash) END) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared facts original generation/adoption mismatch';
  END IF;
  IF p->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v1'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->>'receipt_id' IS DISTINCT FROM NEW.id::text OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text
    OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text OR p->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR p->>'item_id' IS DISTINCT FROM NEW.item_id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
    OR p->>'continuation_binding_hash' IS DISTINCT FROM NEW.continuation_binding_hash
    OR p->'lease'->>'visibility' IS DISTINCT FROM 'public' OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
    OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
    OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
    OR p->>'target_id' IS DISTINCT FROM a.target_id OR p->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR a.target_id NOT IN ('python-state-update-v1','sqlite-predicate-order-v1','python-kc-binding-v1')
    OR p->'evidence'->'binding'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'evidence'->'binding'->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR p->'evidence'->'binding'->>'candidate_key' IS DISTINCT FROM NEW.item_id::text
    OR p->'evidence'->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
    OR p->'evidence'->'binding'->>'profile_hash' IS DISTINCT FROM quality_profile
    OR p->'evaluation'->'binding' IS DISTINCT FROM p->'evidence'->'binding'
    OR p->'evaluation'->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'evidence') THEN
    RAISE check_violation USING MESSAGE='shared facts payload identity mismatch';
  END IF;
  SELECT * INTO prep FROM tutor_item_supply_shared_validation_preparations WHERE id=NEW.validation_preparation_id;
  IF NOT FOUND OR prep.job_id<>quality_job OR prep.lease_generation<>quality_generation
    OR prep.generation_artifact_id<>a.id OR prep.profile_hash<>quality_profile
    OR p->>'validation_preparation_id' IS DISTINCT FROM prep.id::text
    OR p->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'spec')
    OR p->>'inputs_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'inputs')
    OR p->>'public_task_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'public_task_hash'
    OR p->>'instance_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'instance_hash'
    OR p->>'scorer_version' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'scorer_version'
    OR p->>'runtime_profile_hash' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'runtime_profile_hash' THEN
    RAISE check_violation USING MESSAGE='shared facts finite preparation mismatch';
  END IF;
  FOR kind,rid IN SELECT * FROM (VALUES ('validation',NEW.validation_receipt_id),
      ('blind_solve',NEW.blind_receipt_id),('review_bundle',NEW.review_receipt_id)) AS stages(kind,rid) LOOP
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO r
      FROM tutor_item_supply_shared_pipeline_receipts s WHERE s.id=rid;
    IF NOT FOUND OR r.same_transaction OR r.job_id<>quality_job OR r.lease_generation<>quality_generation
      OR r.lease_owner<>quality_owner OR r.generation_artifact_id<>a.id OR r.mode<>'live'
      OR r.item_id<>NEW.item_id OR r.version_id<>NEW.version_id OR r.source_hash<>NEW.source_hash OR r.content_hash<>NEW.content_hash
      OR r.artifact_kind<>kind OR r.continuation_binding_hash IS DISTINCT FROM quality_continuation THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed exact stages required';
    END IF;
    IF kind='validation' THEN
      v:=r;
      IF p->>'validation_receipt_id' IS DISTINCT FROM r.id::text OR p->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR p->'evidence'->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts validation receipt mismatch';
      END IF;
    ELSIF kind='blind_solve' THEN
      b:=r;
      IF p->>'blind_receipt_id' IS DISTINCT FROM r.id::text OR p->>'blind_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts blind receipt mismatch';
      END IF;
    ELSE
      IF p->>'review_receipt_id' IS DISTINCT FROM r.id::text OR p->>'review_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR r.payload_json->'blind_solve' IS DISTINCT FROM b.payload_json THEN
        RAISE check_violation USING MESSAGE='shared facts review receipt mismatch';
      END IF;
    END IF;
  END LOOP;
  FOR kind,budget IN SELECT * FROM (VALUES ('validation',p->'validation_budget'),('review',p->'review_budget')) AS budgets(kind,budget) LOOP
    IF kind='validation' AND a.target_id='python-kc-binding-v1' THEN
      IF budget IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='static facts have no execution budget'; END IF;
      CONTINUE;
    END IF;
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=(budget->>'reservation_id')::uuid;
    IF NOT FOUND OR reservation.job_id<>quality_job OR reservation.root_id<>NEW.root_id
      OR reservation.lease_generation<>quality_generation OR reservation.reservation_key IS DISTINCT FROM budget->>'settlement_key'
      OR reservation.reservation_key<>(CASE WHEN kind='review' THEN 'review.'||replace(a.id::text,'-','') ELSE prep.reservation_key END) THEN
      RAISE check_violation USING MESSAGE='shared facts reservation identity mismatch';
    END IF;
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO usage
      FROM tutor_item_supply_shared_runtime_settlements s WHERE s.id=(budget->>'settlement_id')::uuid;
    IF NOT FOUND OR usage.same_transaction OR usage.reservation_id<>reservation.id
      OR usage.settlement_key<>reservation.reservation_key OR usage.usage_state IS DISTINCT FROM budget->>'usage_state'
      OR usage.receipt_hash IS DISTINCT FROM budget->>'receipt_hash'
      OR usage.usage_state<>(CASE WHEN kind='review' THEN 'unknown' ELSE 'known' END) THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed usage required';
    END IF;
    IF kind='review' AND (budget->'actual' IS DISTINCT FROM 'null'::jsonb OR budget->'receipt_hash' IS DISTINCT FROM 'null'::jsonb) THEN
      RAISE check_violation USING MESSAGE='unknown provider usage cannot become zero';
    END IF;
  END LOOP;
  IF p->'ambiguity'->'plan'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'ambiguity'->'plan'->>'specification_hash' IS DISTINCT FROM p->>'specification_hash'
    OR p->'ambiguity'->'plan'->>'inputs_hash' IS DISTINCT FROM p->>'inputs_hash'
    OR (p->'ambiguity'->>'parent_deadline_at')::timestamptz<(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts finite interpretation mismatch';
  END IF;
  IF a.target_id='python-kc-binding-v1' THEN
    IF p->'validation_terminals' IS DISTINCT FROM '[]'::jsonb OR p->'blind_terminals' IS DISTINCT FROM '[]'::jsonb
      OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'static_options'
      OR p->'evidence'->'runner_available' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_isolated' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_receipt_hash' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE check_violation USING MESSAGE='static facts cannot claim OS execution';
    END IF;
  ELSIF jsonb_array_length(p->'validation_terminals') NOT BETWEEN 1 AND 32
    OR jsonb_array_length(p->'blind_terminals')<>1 OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'sealed_pair'
    OR p->'evidence'->>'execution_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(v.payload_json->'execution_evidence') THEN
    RAISE check_violation USING MESSAGE='runtime facts original terminal projection missing';
  END IF;
  IF p->'target_proof'<>'null'::jsonb AND (p->'target_proof'->>'claim_scope' IS DISTINCT FROM 'per_item_registered_target_not_inventory'
    OR p->'target_proof'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'target_proof'->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR p->'evidence'->>'coverage_proof_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'target_proof')) THEN
    RAISE check_violation USING MESSAGE='shared facts per-item proof mismatch';
  END IF;
  SELECT * INTO r FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.review_receipt_id;
  IF item_supply_internal.shared_evaluation_policy_matches(a::tutor_item_supply_shared_generation_artifacts,p->'evaluation',r.payload_json) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared facts exact frozen policy/warning mismatch';
  END IF;
  RETURN NEW;
END $body547$;
REVOKE ALL ON FUNCTION public.enforce_item_supply_shared_admission_facts() FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.committed_child_evaluation_matches(jsonb)');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('c35f1f08e8aa90808891390b248e289919ee5d81ada162f5b558fd9a06226bcb')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.committed_child_evaluation_matches(jsonb)'; END IF;
 
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.committed_child_evaluation_matches(r jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE action jsonb; f record; lease jsonb;
BEGIN
 action:=item_supply_internal.committed_child_admission_for_job((r->>'job_id')::uuid);
 IF action IS NULL THEN RETURN false; END IF;
 lease:=action->'lease';
 SELECT x.*,x.xmin::text::bigint=txid_current()%4294967296 AS same_top INTO f FROM tutor_item_supply_shared_admission_facts x
  WHERE x.id=(action->>'admission_id')::uuid AND x.job_id=(lease->>'job_id')::uuid FOR SHARE;
 IF f.id IS NULL OR f.same_top OR r->>'artifact_kind' IS DISTINCT FROM 'admission_evaluation'
  OR r->>'schema_version' IS DISTINCT FROM 'item_supply_admission_evaluation_v3'
  OR r->>'generation_artifact_id' IS DISTINCT FROM action->>'artifact_id'
  OR r->>'artifact_key' IS DISTINCT FROM 'native_admission.'||replace(f.id::text,'-','')
  OR r->>'lease_generation' IS DISTINCT FROM lease->>'generation' OR r->>'lease_owner' IS DISTINCT FROM lease->>'lease_owner'
  OR r->>'lease_state_version' IS DISTINCT FROM lease->>'state_version'
  OR r->>'item_id' IS DISTINCT FROM f.item_id::text OR r->>'version_id' IS DISTINCT FROM f.version_id::text
  OR r->>'source_hash' IS DISTINCT FROM f.source_hash OR r->>'content_hash' IS DISTINCT FROM f.content_hash
  OR r->>'mode' IS DISTINCT FROM 'live' OR r->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
  OR r->'continuation_binding_hash' IS DISTINCT FROM 'null'::jsonb
  OR r->'payload_json' IS DISTINCT FROM f.payload_json->'evaluation'
  OR item_supply_internal.normal_revision_readmission_matches(f.generation_artifact_id,f.id,f.payload_hash) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='547 exact committed full facts evaluation required'; END IF;
 RETURN true;
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.committed_child_evaluation_matches(jsonb) FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('enforce_item_supply_shared_stage_original()');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('24d421d6fa47895d235090a74a22768fee46f2241d9f6ca353b2c36012c4959c','59a08acf16bd66e1f405a8496898965d666bdedfdf531f4df4fb9e38f06bb101')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: enforce_item_supply_shared_stage_original()'; END IF;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='547 required prior receiver: enforce_item_supply_shared_stage_original()'; END IF;
END $guard547$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_stage_original() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE a record; x record; committed_evaluation boolean:=false;
BEGIN
  IF TG_TABLE_NAME='tutor_item_supply_shared_pipeline_receipts' THEN
    committed_evaluation:=item_supply_internal.committed_child_evaluation_matches(to_jsonb(NEW));
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR NEW.item_id<>a.item_id OR NEW.version_id<>a.version_id
    OR NEW.source_hash<>a.source_hash OR NEW.content_hash<>a.content_hash
    OR (NOT committed_evaluation AND item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,
       NEW.generation_artifact_id,NEW.continuation_binding_hash) IS DISTINCT FROM true) THEN
    RAISE check_violation USING MESSAGE='shared stage original coordinates or adoption mismatch';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_validation_preparations' THEN
    IF NEW.root_id<>a.root_id THEN RAISE check_violation USING MESSAGE='shared continuation root mismatch'; END IF;
    IF NEW.continuation_binding_hash IS NULL THEN
      IF NEW.payload_json ? 'continuation_binding_hash' THEN
        RAISE check_violation USING MESSAGE='unexpected continuation preparation binding';
      END IF;
    ELSE
      SELECT * INTO x FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=NEW.job_id;
      IF NEW.payload_json->>'continuation_binding_hash' IS DISTINCT FROM NEW.continuation_binding_hash
        OR NEW.payload_json->'inputs'->>'specification_hash' IS DISTINCT FROM x.binding_json->>'specification_hash' THEN
        RAISE check_violation USING MESSAGE='continued validation preparation binding mismatch';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $body547$;
REVOKE ALL ON FUNCTION public.enforce_item_supply_shared_stage_original() FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('enforce_item_supply_shared_pipeline_artifact()');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('a9475fd94420a0c04f4647ef7618df31d3d9e89d3fe0415f81308b78f4f8a65e','062595c5137f2d272d240331bfd0ae529c167141beca5609cc40b0c7f3c34272')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: enforce_item_supply_shared_pipeline_artifact()'; END IF;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='547 required prior receiver: enforce_item_supply_shared_pipeline_artifact()'; END IF;
END $guard547$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_pipeline_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE control record; facts public.tutor_item_supply_shared_generation_artifacts%ROWTYPE; root_facts record; reservation record;
  committed_evaluation boolean:=false; quality_profile text;
  scope jsonb; snapshot jsonb; material jsonb; source_receipt jsonb; expected_content text; expected_schema text; i integer;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared pipeline outside B1d';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.job_id FOR UPDATE;
  IF NOT FOUND OR control.state<>'leased' OR control.lease_generation<>NEW.lease_generation
    OR control.state_version<>NEW.lease_state_version OR control.lease_owner IS DISTINCT FROM NEW.lease_owner
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp()
    OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale shared pipeline lease';
  END IF;
  snapshot:=CASE WHEN control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN control.profile_snapshot_json->'profile' ELSE control.profile_snapshot_json END;
  quality_profile:=snapshot->>'profile_hash';
  IF TG_TABLE_NAME='tutor_item_supply_shared_pipeline_receipts' THEN
    committed_evaluation:=item_supply_internal.committed_child_evaluation_matches(to_jsonb(NEW));
    IF committed_evaluation THEN quality_profile:=NEW.payload_json->'binding'->>'profile_hash'; END IF;
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_generation_artifacts' THEN
    SELECT b.snapshot_json,o.obligation_json,o.provider_key,r.canonical_key INTO root_facts
      FROM tutor_item_supply_shared_budget_roots r
      JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id
      JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id
      WHERE r.id=NEW.root_id AND b.id=NEW.blueprint_id FOR SHARE OF r,b,o;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline root unavailable'; END IF;
    scope:=root_facts.snapshot_json->'scope';
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id;
    IF NOT FOUND OR reservation.root_id<>NEW.root_id OR reservation.job_id<>NEW.job_id
      OR reservation.lease_generation<>NEW.lease_generation
      OR reservation.reservation_key IS DISTINCT FROM 'gen.' || replace(NEW.candidate_id::text,'-','')
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements
        WHERE reservation_id=NEW.reservation_id AND settlement_key='generation.' || replace(NEW.candidate_id::text,'-','')) THEN
      RAISE check_violation USING MESSAGE='shared pipeline reservation mismatch';
    END IF;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',NEW.source_json->'public'->>'item_key','version',NEW.source_json->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(NEW.source_json->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(NEW.source_json->'public'),
      'private_hash',item_supply_internal.snapshot_hash(NEW.source_json->'private')));
    IF scope->>'visibility' IS DISTINCT FROM 'public' OR scope->>'owner_ref' IS NOT NULL
      OR NEW.request_json->>'demand_binding' IS NOT NULL
      OR NEW.request_json->'profile' IS DISTINCT FROM snapshot
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(scope)
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM root_facts.obligation_json->>'scope_hash'
      OR item_supply_internal.snapshot_hash(root_facts.obligation_json) IS DISTINCT FROM root_facts.canonical_key
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'scope_hash' IS DISTINCT FROM NEW.request_json->>'scope_hash'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.source_json)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->'blueprint' IS DISTINCT FROM NEW.source_json->'blueprint'
      OR NEW.source_json->'public'->>'item_key' IS DISTINCT FROM NEW.request_json->>'item_key'
      OR NEW.source_json->'public'->>'version' IS DISTINCT FROM NEW.request_json->>'version'
      OR NEW.item_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('item',NEW.request_json->>'item_key')
      OR NEW.version_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('version',NEW.request_json->>'item_key' || '@' || (NEW.request_json->>'version'))
      OR item_supply_internal.shared_public_template_matches(NEW.request_json,NEW.source_json->'public',NEW.target_id) IS DISTINCT FROM true
      OR NEW.source_json->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope->>'knowledge_key'
      OR NEW.source_json->'blueprint'->>'language_id' IS DISTINCT FROM scope->>'language_id'
      OR NEW.source_json->'blueprint'->>'item_kind' IS DISTINCT FROM scope->>'item_kind'
      OR NEW.source_json->'blueprint'->>'purpose' IS DISTINCT FROM scope->>'purpose'
      OR NEW.source_json->'blueprint'->'required_capabilities' IS DISTINCT FROM scope->'required_capabilities'
      OR NOT (NEW.source_json->'blueprint'->'allowed_interactions' @> jsonb_build_array(scope->>'interaction'))
      OR scope->>'assessment_contract_version' IS DISTINCT FROM NEW.target_id
      OR scope->>'runtime_profile_id' IS DISTINCT FROM (CASE NEW.target_id
        WHEN 'python-state-update-v1' THEN 'python-stdout-v1' WHEN 'sqlite-predicate-order-v1' THEN 'sqlite-query-v1' ELSE 'static-exact-v1' END)
      OR NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
      OR NEW.receipt_json->'provider'->>'provider' IS DISTINCT FROM root_facts.provider_key
      OR NEW.receipt_json->'provider'->>'model' IS DISTINCT FROM NEW.receipt_json->'provider'->>'configured_model'
      OR NEW.receipt_json->'provider'->>'provider_version' IS DISTINCT FROM 'openai_compatible.v2'
      OR NEW.receipt_json->'provider'->>'prompt_version' IS DISTINCT FROM 'item_author.public_material.v2'
      OR jsonb_typeof(NEW.request_json->'materials') IS DISTINCT FROM 'array'
      OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array' THEN
      RAISE check_violation USING MESSAGE='shared pipeline generation identity mismatch';
    END IF;
    IF jsonb_array_length(NEW.request_json->'materials') NOT BETWEEN 1 AND 12
      OR jsonb_array_length(NEW.receipt_json->'sources')<>jsonb_array_length(NEW.request_json->'materials') THEN
      RAISE check_violation USING MESSAGE='shared pipeline source count mismatch';
    END IF;
    FOR i IN 0..jsonb_array_length(NEW.request_json->'materials')-1 LOOP
      material:=NEW.request_json->'materials'->i;
      source_receipt:=NEW.receipt_json->'sources'->i;
      IF material->'binding'->>'contract_version' IS DISTINCT FROM 'rag_public_course_binding_v1'
        OR material->'binding'->>'target_id' IS DISTINCT FROM NEW.target_id
        OR material->'binding'->>'target_definition_hash' IS DISTINCT FROM NEW.target_definition_hash
        OR material->'binding' ? 'draft' OR material->'binding' ? 'user_id'
        OR material->'access_request'->>'actor_id' IS DISTINCT FROM 'service.rag-public-course'
        OR source_receipt->>'mode' IS DISTINCT FROM 'current_authority'
        OR source_receipt->>'binding_digest' IS DISTINCT FROM material->'binding'->>'binding_digest'
        OR source_receipt->>'corpus_version_id' IS DISTINCT FROM material->'binding'->'evidence'->0->>'corpus_version_id'
        OR source_receipt->>'active_generation' IS DISTINCT FROM material->'binding'->'evidence'->0->>'active_generation'
        OR source_receipt->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
          'binding',material->'binding','access_request',material->'access_request','exact_claims',material->'exact_claims',
          'excerpt_hash',encode(digest(convert_to(material->>'excerpt','UTF8'),'sha256'),'hex'))) THEN
        RAISE check_violation USING MESSAGE='shared pipeline native source mismatch';
      END IF;
    END LOOP;
  ELSE
    SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id AND (committed_evaluation OR item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,NEW.generation_artifact_id,NEW.continuation_binding_hash));
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline generation unavailable'; END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN CASE WHEN item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_review_bundle_v3' ELSE 'item_supply_review_bundle_v2' END
      WHEN 'admission_evaluation' THEN CASE WHEN item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_admission_evaluation_v3' ELSE 'item_supply_admission_evaluation_v2' END END;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',NEW.payload_json->'binding'->>'content_hash') IS DISTINCT FROM facts.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',NEW.payload_json->'binding'->>'source_hash') IS DISTINCT FROM facts.source_hash
      OR (NEW.artifact_kind<>'validation' AND (
        NEW.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM facts.item_id::text
        OR NEW.payload_json->'binding'->>'version_key' IS DISTINCT FROM facts.version_id::text
        OR NEW.payload_json->'binding'->>'profile_hash' IS DISTINCT FROM quality_profile
        OR NEW.payload_json->'binding'->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='shared pipeline receipt identity mismatch';
    END IF;
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_generation_artifacts' THEN
    PERFORM item_supply_internal.shared_generation_policy_hash(NEW::tutor_item_supply_shared_generation_artifacts);
  END IF;
  RETURN NEW;
END $body547$;
REVOKE ALL ON FUNCTION public.enforce_item_supply_shared_pipeline_artifact() FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('enforce_learning_item_native_validation_import()');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('f364f9b747d387a62b0233822142c589a76f53c376f0fc5500b83397c7508900','262346250b49d1dd49b073175d0162738aa8c9fd85d0bb7dfdea10b5d4784e68')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: enforce_learning_item_native_validation_import()'; END IF;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='547 required prior receiver: enforce_learning_item_native_validation_import()'; END IF;
END $guard547$;
CREATE OR REPLACE FUNCTION public.enforce_learning_item_native_validation_import() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE r record; p record; e record; a record; v record; c record; j record;
  lease jsonb:=NEW.native_import_lease_json; snapshot jsonb; scope jsonb; terminal jsonb;
  action jsonb; quality_profile jsonb; current_job uuid;
BEGIN
  IF NEW.schema_version='learning_item_validation_v1' THEN RETURN NEW; END IF;
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NEW.schema_version<>'candidate_validation_v2' THEN
    RAISE check_violation USING MESSAGE='native bank import is B1d V2 only';
  END IF;
  action:=item_supply_internal.committed_child_admission_for_job((lease->>'job_id')::uuid);
  quality_profile:=lease->'profile';
  IF action IS NOT NULL THEN
    IF lease IS DISTINCT FROM action->'lease' OR NEW.native_generation_artifact_id::text IS DISTINCT FROM action->>'artifact_id'
     OR NEW.native_validation_receipt_id::text IS DISTINCT FROM action->'quality'->>'validation_receipt_id'
     OR NEW.native_validation_evidence_id::text IS DISTINCT FROM action->'quality'->>'validation_evidence_id'
     OR NEW.native_specification_hash IS DISTINCT FROM action->'quality'->>'specification_hash' THEN
      RAISE check_violation USING MESSAGE='547 original committed validation and fresh import capability required'; END IF;
    quality_profile:=action->'quality'->'validation_lease'->'profile';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO r
    FROM tutor_item_supply_shared_pipeline_receipts x WHERE id=NEW.native_validation_receipt_id;
  IF NOT FOUND OR r.same_transaction OR r.artifact_kind<>'validation' OR r.mode<>'live' OR r.publication_enabled
    OR r.schema_version<>'candidate_validation_v2' OR r.payload_json IS DISTINCT FROM NEW.receipt_json
    OR r.receipt_hash IS DISTINCT FROM NEW.receipt_hash OR r.version_id IS DISTINCT FROM NEW.version_id
    OR r.content_hash IS DISTINCT FROM NEW.content_hash OR r.generation_artifact_id IS DISTINCT FROM NEW.native_generation_artifact_id
    OR r.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
    OR r.payload_json->>'source_hash' IS DISTINCT FROM r.source_hash
    OR r.payload_json->>'content_hash' IS DISTINCT FROM r.content_hash THEN
    RAISE check_violation USING MESSAGE='native bank requires exact committed shared V2 validation';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO e
    FROM tutor_item_supply_shared_validation_evidence x WHERE id=NEW.native_validation_evidence_id;
  IF NOT FOUND OR e.same_transaction OR e.publication_enabled
    OR e.payload_json->'validation' IS DISTINCT FROM NEW.receipt_json THEN
    RAISE check_violation USING MESSAGE='native bank committed evidence mismatch';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO p
    FROM tutor_item_supply_shared_validation_preparations x WHERE id=e.preparation_id;
  IF NOT FOUND OR p.same_transaction OR p.job_id IS DISTINCT FROM r.job_id OR p.lease_generation IS DISTINCT FROM r.lease_generation
    OR p.generation_artifact_id IS DISTINCT FROM r.generation_artifact_id OR p.item_id IS DISTINCT FROM r.item_id
    OR p.version_id IS DISTINCT FROM r.version_id OR p.source_hash IS DISTINCT FROM r.source_hash
    OR p.content_hash IS DISTINCT FROM r.content_hash OR p.profile_hash IS DISTINCT FROM quality_profile->>'profile_hash'
    OR r.artifact_key IS DISTINCT FROM 'validation.'||replace(p.id::text,'-','')
    OR NEW.native_specification_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(p.payload_json->'spec')
    OR p.payload_json->'inputs'->>'specification_hash' IS DISTINCT FROM NEW.native_specification_hash THEN
    RAISE check_violation USING MESSAGE='native bank exact finite preparation required';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=r.generation_artifact_id;
  SELECT * INTO v FROM tutor_learning_item_versions WHERE id=NEW.version_id;
  IF a.id IS NULL OR v.id IS NULL OR a.item_id IS DISTINCT FROM v.item_id OR a.version_id IS DISTINCT FROM v.id
    OR a.source_hash IS DISTINCT FROM v.source_hash OR a.content_hash IS DISTINCT FROM v.content_hash
    OR NEW.item_handle IS DISTINCT FROM v.handle
    OR v.public_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'public')
    OR v.private_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'private')
    OR v.blueprint_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'blueprint')
    OR p.payload_json->'request' IS DISTINCT FROM a.request_json
    OR p.payload_json->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR a.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
    OR v.creator_identity IS DISTINCT FROM 'native.author.'||replace(a.receipt_json->'provider'->>'run_id','-','')
    OR (action IS NULL AND item_supply_internal.shared_stage_original_matches(r.job_id,r.lease_generation,a.id,r.continuation_binding_hash) IS DISTINCT FROM true) THEN
    RAISE check_violation USING MESSAGE='native bank original immutable content mismatch';
  END IF;
  current_job:=CASE WHEN action IS NULL THEN r.job_id ELSE (lease->>'job_id')::uuid END;
  SELECT * INTO j FROM tutor_item_supply_shared_jobs WHERE id=current_job;
  SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=current_job FOR UPDATE;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  IF j.root_id IS DISTINCT FROM a.root_id OR c.job_id IS NULL OR c.state<>'leased'
    OR c.lease_generation IS DISTINCT FROM (CASE WHEN action IS NULL THEN r.lease_generation ELSE (lease->>'generation')::integer END) OR c.lease_expires_at IS NULL
    OR c.lease_expires_at<=clock_timestamp() OR c.parent_deadline<=clock_timestamp()
    OR lease->>'visibility' IS DISTINCT FROM 'public' OR lease->>'job_id' IS DISTINCT FROM current_job::text
    OR lease->>'generation' IS DISTINCT FROM c.lease_generation::text
    OR lease->>'state_version' IS DISTINCT FROM c.state_version::text
    OR lease->>'lease_owner' IS DISTINCT FROM c.lease_owner OR lease->'profile' IS DISTINCT FROM snapshot
    OR p.payload_json->'lease'->'profile' IS DISTINCT FROM quality_profile
    OR (action IS NOT NULL AND p.payload_json->'lease' IS DISTINCT FROM action->'quality'->'validation_lease') THEN
    RAISE check_violation USING MESSAGE='native bank current operation lease required';
  END IF;
  scope:=p.payload_json->'spec'->'coverage_blueprint'->'scope';
  IF a.source_json->'public'->>'kind'='knowledge_check' THEN
    IF NEW.receipt_json->>'mode' IS DISTINCT FROM 'static'
      OR NEW.receipt_json IS DISTINCT FROM p.payload_json->'inputs'->'static_facts'->'validation'
      OR NEW.receipt_json->'execution_evidence' IS DISTINCT FROM 'null'::jsonb
      OR e.reservation_id IS NOT NULL OR e.payload_json->'terminals' IS DISTINCT FROM '[]'::jsonb THEN
      RAISE check_violation USING MESSAGE='native bank actual static proof required';
    END IF;
  ELSE
    IF a.source_json->'public'->>'kind' NOT IN ('code','sql') OR NEW.receipt_json->>'mode' IS DISTINCT FROM 'live'
      OR NEW.receipt_json->'legacy_receipt' IS DISTINCT FROM 'null'::jsonb
      OR NEW.receipt_json->'execution_evidence'->>'mode' IS DISTINCT FROM 'live'
      OR NEW.receipt_json->'execution_evidence'->>'isolation' IS DISTINCT FROM 'approved_os_boundary'
      OR NEW.receipt_json->'execution_evidence'->>'runtime_profile_id' IS DISTINCT FROM v.runtime_profile_key
      OR NEW.receipt_json->'execution_evidence'->>'scorer_version' IS DISTINCT FROM scope->>'scorer_version'
      OR e.reservation_id IS NULL OR jsonb_typeof(e.payload_json->'terminals') IS DISTINCT FROM 'array'
      OR jsonb_array_length(e.payload_json->'terminals')<1 THEN
      RAISE check_violation USING MESSAGE='native bank execution binding required';
    END IF;
    FOR terminal IN SELECT value FROM jsonb_array_elements(e.payload_json->'terminals') LOOP
      IF terminal->>'lock_fingerprint' IS DISTINCT FROM scope->>'runtime_profile_hash'
        OR terminal->>'run_id' IS DISTINCT FROM NEW.receipt_json->'execution_evidence'->>'run_id'
        OR terminal->>'mode' IS DISTINCT FROM 'live' OR terminal->>'isolation' IS DISTINCT FROM 'approved_os_boundary' THEN
        RAISE check_violation USING MESSAGE='native bank stored terminal binding mismatch';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $body547$;
REVOKE ALL ON FUNCTION public.enforce_learning_item_native_validation_import() FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_persistent_pack_journal_insert()');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('5ace67de112f22687c435cbfa432237464832fb735ef04880bb570c5f97003ba','6cb924d2b8a396cf2bb2c01f7315e659eadbc41bdcd0eea386190a5e8886580d')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.enforce_persistent_pack_journal_insert()'; END IF;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='547 required prior receiver: item_supply_internal.enforce_persistent_pack_journal_insert()'; END IF;
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_persistent_pack_journal_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
DECLARE p jsonb:=NEW.payload_json; parent record; proof record; phase record; header record; artifact record;
 private_header record;private_job record;private_control record;private_ref jsonb;private_lease jsonb;private_profile jsonb;fixed_slot jsonb;stamp timestamptz;
 committed_child_data boolean:=false; admission_action jsonb; admission_row record;
 slots text[]:=ARRAY['practice-1','practice-2','assessment-1','assessment-2','guided-remediation']; slot_index integer;
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_shared_persistent_pack_journal' AND NEW.record_kind='committed_admission' THEN
  IF NEW.id::text IS DISTINCT FROM p->>'admission_id' OR NEW.phase_id IS DISTINCT FROM NEW.id
   OR NEW.public_task_id::text IS DISTINCT FROM p->>'public_task_id' OR NEW.root_id::text IS DISTINCT FROM p->>'root_id'
   OR NEW.job_id::text IS DISTINCT FROM p->'lease'->>'job_id' OR NEW.operation_key IS DISTINCT FROM p->>'operation_key'
   OR (p->>'capture_txid')::bigint IS DISTINCT FROM txid_current()
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_normal_revision_readmissions WHERE generation_artifact_id=(p->>'artifact_id')::uuid)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts WHERE generation_artifact_id=(p->>'artifact_id')::uuid)
  THEN RAISE check_violation USING MESSAGE='547 unconsumed exact admission journal scalar binding required'; END IF;
  PERFORM item_supply_internal.assert_committed_child_admission(p);
  RETURN NEW;
 END IF;
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
   IF artifact.id='4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3' THEN
    SELECT * INTO admission_row FROM tutor_item_supply_shared_persistent_pack_journal WHERE record_kind='committed_admission'
      AND public_task_id=NEW.public_task_id AND payload_json->>'artifact_id'=artifact.id::text FOR SHARE;
    IF NEW.record_kind='qualified' AND admission_row.id IS NOT NULL THEN
     admission_action:=item_supply_internal.committed_child_admission_for_job(admission_row.job_id);
     IF p IS DISTINCT FROM (admission_action->'version'||jsonb_build_object('published_version_id',artifact.version_id))
       OR NOT EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs pp
        JOIN tutor_item_supply_shared_admission_facts ff ON ff.id=pp.facts_receipt_id
        WHERE pp.version_id=artifact.version_id AND pp.generation_artifact_id=artifact.id
         AND ff.id=admission_row.id AND ff.job_id=admission_row.job_id
         AND pp.proof_json->'lease'=admission_action->'lease'
         AND pp.proof_json->>'specification_hash'=item_supply_internal.snapshot_hash(p->'specification')
         AND item_supply_internal.normal_revision_readmission_matches(artifact.id,ff.id,ff.payload_hash))
     THEN RAISE check_violation USING MESSAGE='547 original same-slot full publication required'; END IF;
     committed_child_data:=true;
    ELSE
     committed_child_data:=item_supply_internal.committed_child_version_data_matches(p);
    END IF;
   END IF;
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
    IF NOT FOUND AND NOT committed_child_data THEN RAISE check_violation USING MESSAGE='523 original full-spec validation preparation required'; END IF;
   END IF;
   IF (p->>'revision_seq')::integer>1 THEN
    SELECT payload_json INTO parent FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=NEW.public_task_id
     AND record_kind IN('version','qualified') AND payload_json->>'revision_id'=p->>'parent_revision_id' ORDER BY created_at DESC LIMIT 1 FOR SHARE;
    IF NOT FOUND OR parent.payload_json->>'public_slot_id' IS DISTINCT FROM p->>'public_slot_id'
     OR parent.payload_json->>'root_id' IS DISTINCT FROM p->>'root_id'
     OR (parent.payload_json->>'revision_seq')::integer+1 IS DISTINCT FROM (p->>'revision_seq')::integer
     OR parent.payload_json->'specification'->>'seed' IS DISTINCT FROM p->'specification'->>'seed'
     OR (parent.payload_json->'specification'->'allocation' IS DISTINCT FROM p->'specification'->'allocation'
       AND NOT committed_child_data AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp
         WHERE rp.candidate_id=artifact.candidate_id AND rp.child_job_id=artifact.job_id
           AND rp.parent_artifact_id=(parent.payload_json->>'artifact_id')::uuid
           AND rp.payload_json->'context'->'persistent_family_revision'->'child_specification'=p->'specification'
           AND item_supply_internal.persistent_registered_family_revision_matches(rp.payload_json)))
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
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_persistent_pack_journal_insert() FROM PUBLIC;

DO $guard547$ DECLARE f record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='547 B1d only'; END IF;
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.deny_committed_admission_reservation()');
 IF FOUND AND (encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('558862b541e3d8c6d169da2cc173c2f705246648af1d72f78e4ca05121aaf46d')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[])
 THEN RAISE check_violation USING MESSAGE='547 unexpected installed receiver: item_supply_internal.deny_committed_admission_reservation()'; END IF;
 
END $guard547$;
CREATE OR REPLACE FUNCTION item_supply_internal.deny_committed_admission_reservation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body547$
BEGIN
 IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_job_controls c JOIN tutor_item_supply_parameter_profiles p ON p.id=c.profile_id
   WHERE c.job_id=NEW.job_id AND p.profile_json->'profile_key'->>'agent_role'='native.shared.admission-only-v1') THEN
  RAISE check_violation USING MESSAGE='547 admission-only action has no provider or paid reservation authority';
 END IF;
 RETURN NEW;
END $body547$;
REVOKE ALL ON FUNCTION item_supply_internal.deny_committed_admission_reservation() FROM PUBLIC;

DO $constraints547$ DECLARE d text; BEGIN
 SELECT pg_get_constraintdef(oid) INTO d FROM pg_constraint WHERE conrelid='public.tutor_item_supply_shared_persistent_pack_journal'::regclass AND conname='tutor_item_supply_shared_persistent_pack_jour_record_kind_check';
 IF d IS DISTINCT FROM $old547$CHECK ((record_kind = ANY (ARRAY['task'::text, 'version'::text, 'qualified'::text, 'phase'::text, 'dispatch_started'::text, 'stage_started'::text, 'stage_result'::text, 'phase_result'::text])))$old547$ AND d IS DISTINCT FROM $new547$CHECK ((record_kind = ANY (ARRAY['task'::text, 'version'::text, 'qualified'::text, 'phase'::text, 'dispatch_started'::text, 'stage_started'::text, 'stage_result'::text, 'phase_result'::text, 'committed_admission'::text])))$new547$ THEN
  RAISE check_violation USING MESSAGE='547 expected journal closed record kinds required'; END IF;
 IF d=$old547$CHECK ((record_kind = ANY (ARRAY['task'::text, 'version'::text, 'qualified'::text, 'phase'::text, 'dispatch_started'::text, 'stage_started'::text, 'stage_result'::text, 'phase_result'::text])))$old547$ THEN
  ALTER TABLE public.tutor_item_supply_shared_persistent_pack_journal DROP CONSTRAINT tutor_item_supply_shared_persistent_pack_jour_record_kind_check;
  ALTER TABLE public.tutor_item_supply_shared_persistent_pack_journal ADD CONSTRAINT tutor_item_supply_shared_persistent_pack_jour_record_kind_check CHECK ((record_kind = ANY (ARRAY['task'::text, 'version'::text, 'qualified'::text, 'phase'::text, 'dispatch_started'::text, 'stage_started'::text, 'stage_result'::text, 'phase_result'::text, 'committed_admission'::text])));
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='public.tutor_item_supply_shared_reservations'::regclass AND tgname='a000_committed_admission_no_paid') THEN
  CREATE TRIGGER a000_committed_admission_no_paid BEFORE INSERT ON public.tutor_item_supply_shared_reservations
   FOR EACH ROW EXECUTE FUNCTION item_supply_internal.deny_committed_admission_reservation();
 ELSIF (SELECT tgfoid FROM pg_trigger WHERE tgrelid='public.tutor_item_supply_shared_reservations'::regclass AND tgname='a000_committed_admission_no_paid')
   IS DISTINCT FROM 'item_supply_internal.deny_committed_admission_reservation()'::regprocedure THEN
  RAISE check_violation USING MESSAGE='547 reservation denial trigger mismatch'; END IF;
END $constraints547$;

