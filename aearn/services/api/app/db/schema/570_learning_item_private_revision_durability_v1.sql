-- C25: original normal revision output durability. Exactly six new functions/two triggers/zero tables.
-- Frozen <=569, all560 bodies/readiness pins and original559 remain unchanged.
-- No restored sender/old grant, new wallet, cross-job writer or phase inheritance.
DO $install570$
DECLARE spec record; actual record; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001'
  OR item_supply_internal.private_generation_durability_ready() IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='570 original isolated writable transaction and frozen560 required'; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_native_same_scene_d1_render_v1(jsonb,jsonb)','private_native_same_scene_d1_render_v1(p_parent_spec jsonb,p_parent_source jsonb)','jsonb','3802 3802',ARRAY['p_parent_spec','p_parent_source']::text[],$render570$
DECLARE contract constant jsonb := $contract570${"schema_version":"private_normal_same_scene_render_v1","render_version":"finite-public-spec-v3-diagnose-d1-r1","target_id":"python-kc-binding-v1","target_definition_hash":"ac716c31c68c112c9b73ecc68b90c0ccb7e29f1694a77e23038375c4d4795abd","base_fixture_hash":"b4458ab4e6b3c66024d5543a71d3a9ed001650244da8d8d302a4b703808b10fc","base_scorer_version":"kc-binding-v1.8fd9c91ae997f6ff703644e4949cb04458614f4c387a213d36286855c64333c8","family_id":"python-kc-binding-v1:diagnose","family_definition_hash":"f3e56a40c8242fa794f99d1887ec6e17df30b76a58474d5eb164b8060fcb213c","seed":0,"program":"price = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)","instruction_markdown":"### finite-public-task-v3:start\n已确认第3行后total=18、解释①正确。只诊断解释②：第4行price重绑定为8后，total是否自动改变。请选择对这一因果偏差的正确诊断；右值、输出和原解释编号保留为辅助命题，不要求另行定位三条解释的首错或独立筛选多个判据。\n### finite-public-task-v3:end","prompt_markdown":"已知第3行执行后total=18，这是本题给定的起点。现在只诊断②“第4行后total自动变成24”这一因果解释：price的重绑定是否会自动改写先前保存的total？\n~~~python\nprice = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)\n~~~\n辅助说明索引（不是额外作答要求）：①第3行后total=18；②第4行后total自动变成24；③第5行后receipt=25。选择对②的正确诊断；选项中完整的右值、保存值、输出及原因仍须真实一致。","options":[{"option_id":"choice-1","label":"首错①：第3/5行右值提前取未来价格，得到24/25；total保持24，输出24 25。","rhs":[24,25],"saved":[24],"observation":[1,24,25],"reason":"future_rhs","failure_reason":"第3行只使用当前price，不能提前取未来价格。"},{"option_id":"choice-2","label":"首错②：第3/5行右值18/19；第4行后total仍为18；输出18 19，因为派生值不自动重算。","rhs":[18,19],"saved":[18],"observation":[2,18,19],"reason":"derived_snapshot","failure_reason":""},{"option_id":"choice-3","label":"没有错误：第3行右值18，第5行右值25；total联动为24，输出24 25，赋值保存动态公式。","rhs":[18,25],"saved":[24],"observation":[0,24,25],"reason":"dynamic_formula","failure_reason":"派生整数不是动态公式；第二步已经发生解释偏差。"},{"option_id":"choice-4","label":"首错③：第3/5行右值18/19；第4行后total为19；输出19 19，因为后续receipt的值会回写到total。","rhs":[18,19],"saved":[19],"observation":[3,19,19],"reason":"receipt_backflow","failure_reason":"receipt在第5行才创建，且程序没有把receipt赋回total。"}],"truth":{"rhs":[18,19],"saved":[18],"observation":[2,18,19],"reason":"derived_snapshot"},"scaffold":{"after_line":3,"total":18,"known_true_explanation":1},"core_selector":"saved_equals_after_line3_total_v1","full_selector":"rhs_saved_complete_observation_reason_equal_v1"}$contract570$::jsonb;
 expected jsonb; public_template jsonb; options jsonb;
BEGIN
 IF item_supply_internal.snapshot_hash(p_parent_spec) IS DISTINCT FROM '052072d8461a5050bfaf6925bc92e352bafa00a0a1ddb059fa8d3e041231bbbd'
  OR item_supply_internal.snapshot_hash(p_parent_source) IS DISTINCT FROM '1d5262aadc00c7f704114794078bf27a1b4a011b578833b8b77b6671e4a0e4fd'
  OR item_supply_internal.snapshot_hash(contract) IS DISTINCT FROM '7fcb09dcbc8b1b994dca5711f3066f78c773ce1864aff59ae048146d76127c4a' THEN
  RAISE check_violation USING MESSAGE='570 exact C25 same-scene render parent required'; END IF;
 SELECT jsonb_agg(jsonb_build_object('option_id',x.value->>'option_id','label',x.value->>'label') ORDER BY x.n)
  INTO options FROM jsonb_array_elements(contract->'options') WITH ORDINALITY x(value,n);
 public_template:=jsonb_set(p_parent_spec->'public_template','{version}','"v2"'::jsonb,false);
 public_template:=jsonb_set(public_template,'{instruction_markdown}',contract->'instruction_markdown',false);
 public_template:=jsonb_set(public_template,'{content,prompt_markdown}',contract->'prompt_markdown',false);
 public_template:=jsonb_set(public_template,'{content,options}',options,false);
 expected:=jsonb_set(p_parent_spec,'{blueprint,version}',contract->'render_version',false);
 expected:=jsonb_set(expected,'{public_template}',public_template,false);
 IF item_supply_internal.snapshot_hash(expected) IS DISTINCT FROM 'd22a358fdf5f82f2b2fe444ed6e396c9ce8d9df7a9ef6fe9b37ab64b947faa26' THEN
  RAISE check_violation USING MESSAGE='570 exact C25 rebuilt child specification required'; END IF;
 RETURN expected;
END;
$render570$),
 ('private_native_revision_durability_attempt_v1(uuid)','private_native_revision_durability_attempt_v1(p_preparation uuid)','jsonb','2950',ARRAY['p_preparation']::text[],$attempt570$
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
$attempt570$),
 ('private_native_revision_output_capture_v1(uuid,jsonb)','private_native_revision_output_capture_v1(p_preparation uuid,p_capture jsonb)','uuid','2950 3802',ARRAY['p_preparation','p_capture']::text[],$capture570$
DECLARE d jsonb; existing public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 identity uuid:=gen_random_uuid(); output_key text; stamp timestamptz;
BEGIN
 d:=item_supply_internal.private_native_revision_durability_attempt_v1(p_preparation);
 output_key:='private.revision.output.'||replace(p_preparation::text,'-','');
 SELECT j.* INTO existing FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=((d->'task'->>'id')::uuid,(d->'task'->>'user_id')::uuid,(d->'task'->>'epoch')::integer,(d->'task'->>'scope_id')::uuid)
  AND j.record_kind='private_status' AND j.operation_key=output_key FOR SHARE;
 IF existing.id IS NOT NULL THEN
  IF existing.payload_json->>'schema_version' IS DISTINCT FROM 'private_native_revision_output_v1'
   OR existing.payload_json->'capture' IS DISTINCT FROM p_capture THEN
   RAISE check_violation USING MESSAGE='570 original revision output/context conflict'; END IF;
  RETURN existing.id;
 END IF;
 stamp:=clock_timestamp();
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,(d->'task'->>'id')::uuid,(d->'task'->>'user_id')::uuid,(d->'task'->>'epoch')::integer,(d->'task'->>'scope_id')::uuid,
  'private_status',output_key,d->'task'->>'intent_hash',jsonb_build_object('schema_version','private_native_revision_output_v1','revision_preparation_id',p_preparation,
   'generation_candidate_id',d->>'generation_candidate_id','investigation_id',d->'investigation'->>'id','investigation_hash',d->'investigation'->>'payload_hash',
   'parent_review_id',d->'parent_review'->>'id','parent_review_hash',d->'parent_review'->>'payload_hash',
   'parent_artifact_id',d->'parent_artifact'->>'id','parent_artifact_hash',d->'parent_artifact'->>'artifact_hash',
   'parent_version_id',d->'parent_artifact'->>'version_id','reservation_id',d->'reservation'->>'id','settlement_id',d->'settlement'->>'id',
   'started_id',d->'started'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
   'render_spec_hash',item_supply_internal.snapshot_hash(d->'expected_spec'),'capture',p_capture,
   'captured_top_xid',pg_current_xact_id()::text,'captured_at',stamp));
 RETURN identity;
END;
$capture570$),
 ('private_native_revision_output_committed_v1(uuid,jsonb)','private_native_revision_output_committed_v1(p_preparation uuid,p_capture jsonb)','uuid','2950 3802',ARRAY['p_preparation','p_capture']::text[],$committed570$
DECLARE d jsonb; output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; body jsonb;
BEGIN
 d:=item_supply_internal.private_native_revision_durability_attempt_v1(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=((d->'task'->>'id')::uuid,(d->'task'->>'user_id')::uuid,(d->'task'->>'epoch')::integer,(d->'task'->>'scope_id')::uuid)
  AND j.record_kind='private_status' AND j.operation_key='private.revision.output.'||replace(p_preparation::text,'-','') FOR SHARE;
 body:=output_row.payload_json;
 IF output_row.id IS NULL OR body IS DISTINCT FROM jsonb_build_object('schema_version','private_native_revision_output_v1','revision_preparation_id',p_preparation,
   'generation_candidate_id',d->>'generation_candidate_id','investigation_id',d->'investigation'->>'id','investigation_hash',d->'investigation'->>'payload_hash',
   'parent_review_id',d->'parent_review'->>'id','parent_review_hash',d->'parent_review'->>'payload_hash',
   'parent_artifact_id',d->'parent_artifact'->>'id','parent_artifact_hash',d->'parent_artifact'->>'artifact_hash',
   'parent_version_id',d->'parent_artifact'->>'version_id','reservation_id',d->'reservation'->>'id','settlement_id',d->'settlement'->>'id',
   'started_id',d->'started'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
   'render_spec_hash',item_supply_internal.snapshot_hash(d->'expected_spec'),'capture',p_capture,
   'captured_top_xid',body->>'captured_top_xid','captured_at',body->'captured_at')
  OR jsonb_typeof(body->'captured_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'captured_top_xid')::xid8::text IS DISTINCT FROM body->>'captured_top_xid'
  OR (body->>'captured_at')::timestamptz IS NULL OR (body->>'captured_at')::timestamptz>clock_timestamp() THEN
  RAISE check_violation USING MESSAGE='570 exact revision sealed output/context required'; END IF;
 IF body->>'captured_top_xid'=pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='570 revision output requires a different committed TOP'; END IF;
 RETURN output_row.id;
END;
$committed570$),
 ('enforce_private_native_revision_output_insert_v1()','enforce_private_native_revision_output_insert_v1()','trigger','',ARRAY[]::text[],$insert570$
DECLARE body jsonb:=NEW.payload_json; protocol text:=body->>'schema_version'; d jsonb; p_preparation uuid; p_capture jsonb;
 capture jsonb;ctx jsonb;result jsonb;source jsonb;receipt jsonb;provider jsonb;request jsonb;expected_content text;stamp timestamptz;known boolean;
BEGIN
 IF COALESCE(protocol<>'private_native_revision_output_v1',true) AND NEW.operation_key NOT LIKE 'private.revision.output.%' THEN RETURN NEW; END IF;
 IF protocol IS DISTINCT FROM 'private_native_revision_output_v1' THEN
  RAISE check_violation USING MESSAGE='570 closed normal revision output schema required'; END IF;
 p_preparation:=(body->>'revision_preparation_id')::uuid;p_capture:=body->'capture';
 d:=item_supply_internal.private_native_revision_durability_attempt_v1(p_preparation);
 IF (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.record_kind,NEW.intent_hash) IS DISTINCT FROM
  ((d->'task'->>'id')::uuid,(d->'task'->>'user_id')::uuid,(d->'task'->>'epoch')::integer,(d->'task'->>'scope_id')::uuid,'private_status',d->'task'->>'intent_hash')
  OR NEW.operation_key IS DISTINCT FROM 'private.revision.output.'||replace(p_preparation::text,'-','') THEN
  RAISE check_violation USING MESSAGE='570 exact original revision output namespace required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=NEW.pack_task_id
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result')) THEN
  RAISE check_violation USING MESSAGE='570 revision capture must precede child artifacts and quality'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=NEW.pack_task_id
  AND (j.operation_key=NEW.operation_key OR (j.payload_json->>'schema_version'='private_native_revision_output_v1'
   AND (j.payload_json->>'revision_preparation_id'=p_preparation::text OR j.payload_json->>'generation_candidate_id'=d->>'generation_candidate_id')))) THEN
  RAISE check_violation USING MESSAGE='570 original revision output already recorded'; END IF;
 stamp:=(body->>'captured_at')::timestamptz;
 IF body IS DISTINCT FROM jsonb_build_object('schema_version','private_native_revision_output_v1','revision_preparation_id',p_preparation,
   'generation_candidate_id',d->>'generation_candidate_id','investigation_id',d->'investigation'->>'id','investigation_hash',d->'investigation'->>'payload_hash',
   'parent_review_id',d->'parent_review'->>'id','parent_review_hash',d->'parent_review'->>'payload_hash',
   'parent_artifact_id',d->'parent_artifact'->>'id','parent_artifact_hash',d->'parent_artifact'->>'artifact_hash',
   'parent_version_id',d->'parent_artifact'->>'version_id','reservation_id',d->'reservation'->>'id','settlement_id',d->'settlement'->>'id',
   'started_id',d->'started'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
   'render_spec_hash',item_supply_internal.snapshot_hash(d->'expected_spec'),'capture',p_capture,
   'captured_top_xid',pg_current_xact_id()::text,'captured_at',stamp)
  OR stamp IS NULL OR stamp>clock_timestamp() THEN
  RAISE check_violation USING MESSAGE='570 exact revision output refs and server TOP required'; END IF;
 capture:=body->'capture'; ctx:=capture->'context'; result:=capture->'result'; request:=ctx->'request';
 source:=result->'source'; receipt:=result->'receipt'; provider:=receipt->'provider';
 IF item_supply_internal.snapshot_keys(capture,ARRAY['schema_version','context','result']) IS DISTINCT FROM true
  OR capture->>'schema_version' IS DISTINCT FROM 'private_native_revision_capture_v1'
  OR item_supply_internal.snapshot_keys(ctx,ARRAY['ref','lease','scope_id','request','reservation_id','sources','attempt_bound','mode','producer_binding']) IS DISTINCT FROM true
  OR ctx->'ref' IS DISTINCT FROM d->'aux'->'payload_json'->'request'->'ref'
  OR ctx->'lease' IS DISTINCT FROM d->'aux'->'payload_json'->'request'->'lease'
  OR ctx->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR request IS DISTINCT FROM d->'aux'->'payload_json'->'request'->'request'
  OR ctx->'reservation_id' IS DISTINCT FROM d->'reservation'->'id'
  OR ctx->'attempt_bound' IS DISTINCT FROM '1'::jsonb OR ctx->>'mode' IS DISTINCT FROM 'live'
  OR ctx->'producer_binding' IS DISTINCT FROM d->'producer_binding'
  OR item_supply_internal.snapshot_keys(result,ARRAY['state','source','receipt','safe_reason']) IS DISTINCT FROM true
  OR result->>'state' IS DISTINCT FROM 'staged' OR result->>'safe_reason' IS DISTINCT FROM 'staged'
  OR item_supply_internal.snapshot_keys(source,ARRAY['schema_version','blueprint','public','private']) IS DISTINCT FROM true
  OR source->>'schema_version' IS DISTINCT FROM 'learning_item_source_v1'
  OR source->'blueprint' IS DISTINCT FROM request->'blueprint'
  OR (source->'public'->>'item_key',source->'public'->>'version') IS DISTINCT FROM (request->>'item_key',request->>'version')
  OR (source->'private'->>'item_key',source->'private'->>'version',source->'private'->>'kind') IS DISTINCT FROM
     (source->'public'->>'item_key',source->'public'->>'version',source->'public'->>'kind')
  OR item_supply_internal.snapshot_keys(receipt,ARRAY['schema_version','candidate_id','scope_hash','source_hash','content_hash','provider','sources']) IS DISTINCT FROM true
  OR receipt->>'schema_version' IS DISTINCT FROM 'item_generation_receipt_v2'
  OR receipt->>'candidate_id' IS DISTINCT FROM d->>'generation_candidate_id' OR receipt->>'scope_hash' IS DISTINCT FROM request->>'scope_hash'
  OR receipt->'sources' IS DISTINCT FROM ctx->'sources'
  OR item_supply_internal.snapshot_keys(provider,ARRAY['provider','provider_version','configured_model','model','prompt_version','role','run_id','request_attempt_bound','actual_requests','usage','mode']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(provider->'usage',ARRAY['state','input_tokens','cached_input_tokens','output_tokens','total_tokens','reasoning_tokens','cost']) IS DISTINCT FROM true
  OR provider->>'mode' IS DISTINCT FROM 'provider' OR provider->>'role' IS DISTINCT FROM 'item_author'
  OR provider->>'prompt_version' IS DISTINCT FROM 'item_author.public_material.v2' OR provider->'usage'->'cost' IS DISTINCT FROM 'null'::jsonb
  OR provider->'request_attempt_bound' IS DISTINCT FROM '1'::jsonb
  OR (provider->'actual_requests'<>'null'::jsonb AND provider->'actual_requests' IS DISTINCT FROM '1'::jsonb)
  OR jsonb_build_array(provider->>'provider',provider->>'configured_model') IS DISTINCT FROM ctx->'producer_binding'
  OR provider->>'model' IS DISTINCT FROM provider->>'configured_model'
 THEN RAISE check_violation USING MESSAGE='570 full original sealed context/staged source/receipt identity required'; END IF;
 expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object('item_key',source->'public'->>'item_key','version',source->'public'->>'version',
  'blueprint_hash',item_supply_internal.snapshot_hash(source->'blueprint'),'public_hash',item_supply_internal.snapshot_hash(source->'public'),
  'private_hash',item_supply_internal.snapshot_hash(source->'private')));
 IF receipt->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(source) OR receipt->>'content_hash' IS DISTINCT FROM expected_content
  OR jsonb_typeof(ctx->'sources') IS DISTINCT FROM 'array' OR jsonb_array_length(ctx->'sources') NOT BETWEEN 1 AND 12
  OR jsonb_array_length(ctx->'sources') IS DISTINCT FROM jsonb_array_length(request->'materials')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(ctx->'sources') WITH ORDINALITY s(value,n)
   JOIN jsonb_array_elements(request->'materials') WITH ORDINALITY m(value,n) ON m.n=s.n
   WHERE item_supply_internal.snapshot_keys(s.value,ARRAY['material_digest','binding_digest','corpus_version_id','active_generation','checked_at_iso','claim_receipt_hashes','mode']) IS DISTINCT FROM true
    OR s.value->>'mode' IS DISTINCT FROM 'current_authority'
    OR s.value->>'binding_digest' IS DISTINCT FROM m.value->'binding'->>'binding_digest'
    OR s.value->>'corpus_version_id' IS DISTINCT FROM m.value->'binding'->'evidence'->0->>'corpus_version_id'
    OR s.value->'active_generation' IS DISTINCT FROM m.value->'binding'->'evidence'->0->'active_generation'
    OR s.value->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('binding',m.value->'binding',
      'access_request',m.value->'access_request','exact_claims',m.value->'exact_claims',
      'excerpt_hash',encode(sha256(convert_to(m.value->>'excerpt','UTF8')),'hex'))))
 THEN RAISE check_violation USING MESSAGE='570 complete original source/content/material hashes required'; END IF;
 IF source->'public' IS DISTINCT FROM d->'expected_spec'->'public_template'
  OR source->'blueprint' IS DISTINCT FROM d->'expected_spec'->'blueprint'
  OR item_supply_internal.revision_substantive_hash(source) IS NOT DISTINCT FROM item_supply_internal.revision_substantive_hash(d->'parent_artifact'->'source_json') THEN
  RAISE check_violation USING MESSAGE='570 exact substantive R1 source required'; END IF;
 known:=provider->'usage'->>'state'='known' AND provider->>'actual_requests' IS NOT NULL
  AND provider->'usage'->>'input_tokens' IS NOT NULL AND provider->'usage'->>'output_tokens' IS NOT NULL;
 IF d->'settlement'->'cost_amount' IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='570 original null cost must be retained'; END IF;
 IF known THEN
  IF d->'settlement'->>'usage_state' IS DISTINCT FROM 'known' OR d->'settlement'->>'receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(provider)
   OR d->'amounts' IS DISTINCT FROM jsonb_build_object('requests',(provider->>'actual_requests')::bigint,'candidates',1,
    'input_tokens',(provider->'usage'->>'input_tokens')::bigint,'output_tokens',(provider->'usage'->>'output_tokens')::bigint,
    'execution_seconds',0,'fetches',0,'revision_rounds',0,'investigation_rounds',0)
  THEN RAISE check_violation USING MESSAGE='570 exact known original provider/settlement amounts required'; END IF;
 ELSE
  IF COALESCE(provider->'usage'->>'state' IN('known','unknown'),false) IS DISTINCT FROM true
   OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'unknown' OR d->'settlement'->'receipt_hash' IS DISTINCT FROM 'null'::jsonb
   OR d->'amounts' IS DISTINCT FROM 'null'::jsonb
  THEN RAISE check_violation USING MESSAGE='570 UNKNOWN/null original settlement must be retained'; END IF;
 END IF;

 RETURN NEW;
END;
$insert570$),
 ('enforce_private_native_revision_output_artifact_v1()','enforce_private_native_revision_output_artifact_v1()','trigger','',ARRAY[]::text[],$artifact570$
DECLARE phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 p_preparation uuid; preparations bigint; output_id uuid;
BEGIN
 IF NEW.mode IS DISTINCT FROM 'live' OR NEW.user_id IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid
  OR NEW.epoch<>1 OR NEW.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid THEN RETURN NEW; END IF;
 SELECT ph.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal ph WHERE
  ph.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND ph.user_id=NEW.user_id AND ph.epoch=NEW.epoch AND ph.scope_id=NEW.scope_id
  AND ph.record_kind='phase' AND ph.payload_json->>'schema_version'='private_native_phase_v1'
  AND ph.payload_json->>'job_id'=NEW.job_id::text AND ph.payload_json->'ref'->>'slot_id'='50df2afa-158c-586e-83c7-60bb99ea4307';
 IF phase.id IS NULL OR phase.payload_json->'ref'->'parent_version_id'='null'::jsonb THEN RETURN NEW; END IF;
 SELECT count(*),(array_agg(j.id ORDER BY j.id))[1] INTO preparations,p_preparation FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(phase.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id)
  AND j.record_kind='private_attachment' AND j.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND j.payload_json->>'job_id'=NEW.job_id::text AND j.payload_json->'request'->>'schema_version'='private_native_revision_phase_v1'
  AND j.payload_json->'request'->'ref'=phase.payload_json->'ref'
  AND j.payload_json->'request'->'request'->>'candidate_id'=NEW.request_json->>'candidate_id';
 IF preparations<>1 THEN RAISE check_violation USING MESSAGE='570 one original normal revision preparation required before child Artifact'; END IF;
 PERFORM item_supply_internal.private_native_revision_durability_attempt_v1(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE
  (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(phase.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id)
  AND j.record_kind='private_status' AND j.operation_key='private.revision.output.'||replace(p_preparation::text,'-','');
 output_id:=item_supply_internal.private_native_revision_output_committed_v1(p_preparation,output_row.payload_json->'capture');
 IF output_id IS NULL OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM NEW.request_json
  OR output_row.payload_json->'capture'->'context'->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
  OR output_row.payload_json->'capture'->'context'->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
  OR NEW.artifact_key IS DISTINCT FROM 'generation.'||replace(NEW.request_json->>'candidate_id','-','')
  OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM NEW.source_json
  OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json THEN
  RAISE check_violation USING MESSAGE='570 exact committed revision output required before child Artifact'; END IF;
 RETURN NEW; -- Original559 still owns actual bank/version, SOURCE/goal/current control and final clock.
END;
$artifact570$)
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
    RAISE check_violation USING MESSAGE='570 unexpected existing revision receiver: '||spec.signature; END IF;
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
   RAISE check_violation USING MESSAGE='570 installed revision receiver attributes/body changed: '||spec.signature; END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','private_native_revision_output_insert','enforce_private_native_revision_output_insert_v1'),
  ('tutor_item_supply_private_generation_artifacts','private_native_revision_output_artifact','enforce_private_native_revision_output_artifact_v1')
 ) AS triggers(table_name,trigger_name,function_name) LOOP
  SELECT t.* INTO actual FROM pg_catalog.pg_trigger t WHERE t.tgrelid=to_regclass('public.'||tr.table_name) AND t.tgname=tr.trigger_name;
  IF NOT FOUND THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON public.%I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.%I()',tr.trigger_name,tr.table_name,tr.function_name);
  END IF;
  SELECT t.* INTO actual FROM pg_catalog.pg_trigger t WHERE t.tgrelid=to_regclass('public.'||tr.table_name) AND t.tgname=tr.trigger_name;
  IF NOT FOUND OR actual.tgfoid IS DISTINCT FROM to_regprocedure('item_supply_internal.'||tr.function_name||'()')
   OR actual.tgtype<>7 OR actual.tgenabled<>'O' OR actual.tgisinternal OR actual.tgdeferrable OR actual.tginitdeferred
   OR actual.tgnargs<>0 OR actual.tgqual IS NOT NULL OR actual.tgattr::text<>'' OR actual.tgargs<>''::bytea
   OR actual.tgparentid<>0 OR actual.tgconstrrelid<>0 OR actual.tgconstrindid<>0 OR actual.tgconstraint<>0
   OR actual.tgoldtable IS NOT NULL OR actual.tgnewtable IS NOT NULL
   OR pg_get_triggerdef(actual.oid) IS DISTINCT FROM format('CREATE TRIGGER %I BEFORE INSERT ON public.%I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.%I()',tr.trigger_name,tr.table_name,tr.function_name) THEN
   RAISE check_violation USING MESSAGE='570 exact revision output trigger required: '||tr.trigger_name; END IF;
 END LOOP;
 IF item_supply_internal.private_generation_durability_ready() IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='570 frozen560 readiness changed'; END IF;
END;
$install570$;
