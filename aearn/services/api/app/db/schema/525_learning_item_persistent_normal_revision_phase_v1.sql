-- Existing helper replay is exact body AND all authority attributes, never overwrite unknown changes.
DO $helpers525$
DECLARE expected record; actual record;
BEGIN
 FOR expected IN SELECT * FROM (VALUES
 ('item_supply_internal.assert_persistent_normal_repair(jsonb)','3d90ba5383546ee4576656f34daf3f2d846519385aa5d9a41d3144da207a68c0','void'),
 ('item_supply_internal.persistent_registered_family_revision_matches(jsonb)','8df23b08aee40c277a320efa8df047d279250944d89157342349253aad83026b','bool')
 ) AS guards(signature,sha256,returntype) LOOP
  SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(expected.signature);
  IF FOUND AND (encode(sha256(convert_to(replace(actual.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM expected.sha256
   OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef
   OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype IS DISTINCT FROM to_regtype('pg_catalog.'||expected.returntype)
   OR actual.pronargs<>1 OR actual.proargnames IS DISTINCT FROM ARRAY['p']::text[] OR actual.proallargtypes IS NOT NULL
   OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
  THEN RAISE check_violation USING MESSAGE='525 unknown existing helper body or attributes'; END IF;
 END LOOP;
END $helpers525$;

-- STAGED ONLY: explicit persistent PUBLIC normal repair. 0 new tables.
-- 508-524 files/rows immutable. No historical discharge, controlled release or budget reset.
DO $$ BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='525 B1d only'; END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_persistent_normal_repair(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a record; vr record; br record; rr record; continuation record; header record; pair_fact record;
 phase jsonb; f jsonb; req jsonb; finding jsonb; member jsonb; pair_id uuid; expected_fields jsonb;
 stamp timestamptz; peer_count integer; clone_count integer; bound_pair jsonb; original jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' THEN RAISE check_violation USING MESSAGE='525 original read-write boundary required'; END IF;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'generation_artifact_id')::uuid FOR SHARE;
 -- Controlled ancestry ALWAYS wins, before payload/normal permission.
 IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='525 controlled ancestry denied first'; END IF;
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','preparation_id','root_id','lease','generation_artifact_id','artifact_hash',
  'validation_receipt_id','blind_receipt_id','review_receipt_id','review_receipt_hash','original_review_reservation_id','continuation_binding_hash',
  'reservation_id','reservation_key','request_hash','request_payload','identity','resources','source_deadlines','deadline_at','timeout_seconds',
  'publication_enabled','admission_eligible','persistent_frame']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(p->'persistent_frame',ARRAY['schema_version','phase','original_review_frame']) IS DISTINCT FROM true
  OR p->'persistent_frame'->>'schema_version' IS DISTINCT FROM 'persistent_normal_investigation_frame_v1'
 THEN RAISE check_violation USING MESSAGE='525 explicit concrete frame required'; END IF;
 phase:=p->'persistent_frame'->'phase'; f:=p->'persistent_frame'->'original_review_frame'; req:=p->'request_payload';
 PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
 IF phase->>'kind' IS DISTINCT FROM 'candidate' OR phase->>'root_id' IS DISTINCT FROM a.root_id::text
  OR phase->'lease' IS DISTINCT FROM p->'lease' OR p->>'root_id' IS DISTINCT FROM a.root_id::text
  OR p->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
  OR item_supply_internal.snapshot_keys(f,ARRAY['schema_version','phase_id','review_receipt_id','blind_receipt_id',
       'validation_receipt_id','review_hash','blind_hash','validation_hash','continuation_binding_hash']) IS DISTINCT FROM true
  OR f->>'schema_version' IS DISTINCT FROM 'persistent_committed_review_frame_v1' OR f->'phase_id' IS DISTINCT FROM phase->'phase_id'
  OR f->>'review_receipt_id' IS DISTINCT FROM p->>'review_receipt_id' OR f->>'review_hash' IS DISTINCT FROM p->>'review_receipt_hash'
  OR f->>'blind_receipt_id' IS DISTINCT FROM p->>'blind_receipt_id' OR f->>'validation_receipt_id' IS DISTINCT FROM p->>'validation_receipt_id'
  OR f->>'continuation_binding_hash' IS DISTINCT FROM p->>'continuation_binding_hash'
 THEN RAISE check_violation USING MESSAGE='525 exact original phase/root/review frame required'; END IF;
 SELECT payload_json INTO original FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=(phase->>'public_task_id')::uuid
  AND record_kind IN('version','qualified') AND payload_json->>'revision_id'=phase->>'revision_id' ORDER BY created_at DESC,id LIMIT 1 FOR SHARE;
 IF NOT FOUND OR original->>'artifact_id' IS DISTINCT FROM a.id::text OR original->'public_slot_id' IS DISTINCT FROM phase->'public_slot_id'
  OR original->>'root_id' IS DISTINCT FROM a.root_id::text
 THEN RAISE check_violation USING MESSAGE='525 immutable fixed parent slot required'; END IF;
 SELECT * INTO continuation FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=(phase->>'job_id')::uuid
  AND generation_artifact_id=a.id AND root_id=a.root_id FOR SHARE;
 IF NOT FOUND OR continuation.binding_hash IS DISTINCT FROM f->>'continuation_binding_hash'
  OR continuation.binding_json->'adoption_lease' IS DISTINCT FROM phase->'lease'
  OR continuation.binding_json->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(original->'specification')
 THEN RAISE check_violation USING MESSAGE='525 original491 exact current adoption required'; END IF;
 SELECT r.* INTO rr FROM tutor_item_supply_shared_pipeline_receipts r WHERE id=(f->>'review_receipt_id')::uuid
  AND generation_artifact_id=a.id AND artifact_kind='review_bundle' AND mode='live' FOR SHARE;
 SELECT r.* INTO br FROM tutor_item_supply_shared_pipeline_receipts r WHERE id=(f->>'blind_receipt_id')::uuid
  AND generation_artifact_id=a.id AND artifact_kind='blind_solve' AND mode='live' FOR SHARE;
 SELECT r.* INTO vr FROM tutor_item_supply_shared_pipeline_receipts r WHERE id=(f->>'validation_receipt_id')::uuid
  AND generation_artifact_id=a.id AND artifact_kind='validation' AND mode='live' FOR SHARE;
 IF rr.id IS NULL OR br.id IS NULL OR vr.id IS NULL OR rr.receipt_hash IS DISTINCT FROM f->>'review_hash'
  OR br.receipt_hash IS DISTINCT FROM f->>'blind_hash' OR vr.receipt_hash IS DISTINCT FROM f->>'validation_hash'
  OR (rr.job_id,rr.lease_generation,rr.lease_owner) IS DISTINCT FROM (br.job_id,br.lease_generation,br.lease_owner)
  OR (rr.job_id,rr.lease_generation,rr.lease_owner) IS DISTINCT FROM (vr.job_id,vr.lease_generation,vr.lease_owner)
  OR rr.payload_json->'blind_solve' IS DISTINCT FROM br.payload_json
  OR rr.payload_json->'binding'->>'source_hash' IS DISTINCT FROM a.source_hash
  OR rr.payload_json->'binding'->>'content_hash' IS DISTINCT FROM a.content_hash
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts r WHERE id IN(rr.id,br.id,vr.id)
     AND xmin::text::bigint=(txid_current()%4294967296))
 THEN RAISE check_violation USING MESSAGE='525 original committed validation/blind/six DATA required'; END IF;
 IF item_supply_internal.snapshot_keys(req,ARRAY['schema_version','purpose','authority','review_receipt_id','review_receipt_hash',
      'review_input','execution_profile_hash','revision_allocation','disputes','evidence_index']) IS DISTINCT FROM true
  OR (req->'review_input'-ARRAY['schema_version','binding','role','source','validation_receipt','validation_receipt_hash','scoring_descriptor'])<>'{}'::jsonb
  OR req->'review_input'->>'schema_version' IS DISTINCT FROM 'item_supply_review_input_v2'
  OR req->'review_input'->>'role' IS DISTINCT FROM 'technical'
  OR req->>'schema_version' IS DISTINCT FROM 'persistent_normal_investigation_input_v1'
  OR req->>'purpose' IS DISTINCT FROM 'same_item_substantive_repair' OR req->>'authority' IS DISTINCT FROM 'original_shared_owner_required'
  OR req->>'execution_profile_hash' IS DISTINCT FROM phase->'lease'->'profile'->>'profile_hash'
  OR req->'review_input'->'binding' IS DISTINCT FROM rr.payload_json->'binding'
  OR req->'review_input'->'source' IS DISTINCT FROM a.source_json OR req->'review_input'->'validation_receipt' IS DISTINCT FROM vr.payload_json
 THEN RAISE check_violation USING MESSAGE='525 retained quality/new execution explicit closure required'; END IF;
 SELECT h.* INTO header FROM tutor_item_supply_private_persistent_pack_journal h
  JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=h.pack_task_id
    AND attachment.user_id=h.user_id AND attachment.epoch=h.epoch AND attachment.scope_id=h.scope_id
  WHERE h.record_kind='task' AND attachment.record_kind='phase'
   AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
   AND attachment.payload_json->'phase_id'=phase->'phase_id' AND attachment.payload_json->'public_task_id'=phase->'public_task_id'
  ORDER BY h.id LIMIT 1 FOR SHARE OF h,attachment;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='525 original PRIVATE task attachment required'; END IF;
 PERFORM user_id FROM tutor_item_supply_user_epochs WHERE user_id=header.user_id AND epoch=header.epoch AND enabled FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='525 current user epoch required'; END IF;
 PERFORM id FROM tutor_item_supply_private_scopes WHERE id=header.scope_id AND user_id=header.user_id AND epoch=header.epoch FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='525 current private scope required'; END IF;
 -- Original A524 receiver implements the installed503/504 actual-D current mapping fence.
 PERFORM item_supply_internal.private_native_mapping_current((header.payload_json->'ref'->>'mapping_receipt_id')::uuid,header.user_id,header.epoch::bigint);
 clone_count:=0; peer_count:=0;
 FOR finding IN SELECT value FROM jsonb_array_elements(req->'disputes') LOOP
  IF finding->>'schema_version'='persistent_deterministic_clone_finding_v1' THEN
   clone_count:=clone_count+1;
   IF item_supply_internal.snapshot_keys(finding,ARRAY['schema_version','role','safe_code','rule','pair','equal_fields','dispute_key','references',
       'model_finding_asserted','historical_finding_resolved']) IS DISTINCT FROM true
    OR finding->>'role' IS DISTINCT FROM 'deterministic' OR finding->>'safe_code' IS DISTINCT FROM 'assessment_clone'
    OR finding->>'rule' IS DISTINCT FROM 'original_assessment_clone_v2' OR finding->'references' IS DISTINCT FROM '[]'::jsonb
    OR finding->'model_finding_asserted' IS DISTINCT FROM 'false'::jsonb OR finding->'historical_finding_resolved' IS DISTINCT FROM 'false'::jsonb
    OR finding->>'dispute_key' IS DISTINCT FROM item_supply_internal.snapshot_hash(finding-'dispute_key')
    OR jsonb_typeof(finding->'pair') IS DISTINCT FROM 'array' OR jsonb_array_length(finding->'pair') IS DISTINCT FROM 2
    OR finding->'pair'->0->'version_id' IS NOT DISTINCT FROM finding->'pair'->1->'version_id'
   THEN RAISE check_violation USING MESSAGE='525 actual deterministic finding shape required'; END IF;
   bound_pair:=finding->'pair';
   FOR member IN SELECT value FROM jsonb_array_elements(bound_pair) LOOP
    pair_id:=(member->>'version_id')::uuid;
    SELECT n.*,g.job_id,g.root_id,g.id AS artifact_id,g.request_json,pe.occurred_at INTO pair_fact
      FROM tutor_item_supply_native_content_facts cf JOIN tutor_learning_item_native_publication_proofs n ON n.id=cf.proof_id
      JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=n.generation_artifact_id
      JOIN tutor_learning_item_publication_events pe ON pe.id=n.publication_event_id AND pe.state='published'
      WHERE cf.user_id=header.user_id AND cf.epoch=header.epoch AND cf.version_id=pair_id AND cf.content_json=member
       AND cf.proof_hash=n.proof_hash AND n.version_id=pair_id FOR SHARE OF cf,n,g,pe;
    IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(pair_fact.job_id) IS DISTINCT FROM false
      OR pair_fact.occurred_at<(pair_fact.proof_json->>'checked_at')::timestamptz
      OR pair_fact.occurred_at>(pair_fact.proof_json->>'valid_until')::timestamptz
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.public_task_id=(phase->>'public_task_id')::uuid
       AND j.record_kind='qualified' AND j.payload_json->>'published_version_id'=pair_id::text AND j.root_id=pair_fact.root_id
       AND j.payload_json->>'artifact_id'=pair_fact.artifact_id::text)
    THEN RAISE check_violation USING MESSAGE='525 exact original current-source/public fixed pair required'; END IF;
    IF item_supply_internal.private_native_source_current(jsonb_build_object('request',pair_fact.request_json,'ref',header.payload_json->'ref')) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='525 actual pair current source denied'; END IF;
   END LOOP;
   SELECT jsonb_agg(to_jsonb(field) ORDER BY ordinal) INTO expected_fields FROM unnest(ARRAY[
      'item_handle','content_hash','actual_public_task_hash','decision_signature','answer_leakage_signature']) WITH ORDINALITY AS fields(field,ordinal)
    WHERE bound_pair->0->field=bound_pair->1->field;
   IF expected_fields IS NULL OR finding->'equal_fields' IS DISTINCT FROM expected_fields
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(bound_pair) m WHERE m->>'version_id'=original->>'published_version_id')
     OR original->'specification'->'allocation'->>'slot' IS DISTINCT FROM 'assessment'
     OR original->>'slot' IS DISTINCT FROM (SELECT max(j.payload_json->>'slot') FROM tutor_item_supply_shared_persistent_pack_journal j
       WHERE j.public_task_id=(phase->>'public_task_id')::uuid AND j.record_kind='qualified'
       AND j.payload_json->'specification'->'allocation'->>'slot'='assessment'
       AND j.payload_json->>'published_version_id' IN(bound_pair->0->>'version_id',bound_pair->1->>'version_id'))
   THEN RAISE check_violation USING MESSAGE='525 original assessment clone and exact affected parent required'; END IF;
  ELSE
   peer_count:=peer_count+1;
  END IF;
 END LOOP;
 IF clone_count>1 OR clone_count+peer_count NOT BETWEEN 1 AND 144
  OR ((clone_count=1) IS DISTINCT FROM (req->'revision_allocation' IS DISTINCT FROM 'null'::jsonb))
  OR (original->>'published_version_id' IS NOT NULL AND clone_count<>1)
 THEN RAISE check_violation USING MESSAGE='525 published parent requires actual single clone finding'; END IF;
 -- All ordinary peer findings, scalar references, source grants, actual resources
 -- and UNKNOWN settlement remain independently enforced by original508 below.
 PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
 stamp:=clock_timestamp();
 IF COALESCE((p->>'deadline_at')::timestamptz>stamp,false) IS DISTINCT FROM true
  OR (p->>'deadline_at')::timestamptz>(phase->>'valid_until')::timestamptz
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'source_deadlines') s WHERE
     COALESCE((s->>'retained_until')::timestamptz>stamp,false) IS DISTINCT FROM true)
 THEN RAISE check_violation USING MESSAGE='525 acceptance clock/source/phase deadline expired'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_normal_repair(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.persistent_registered_family_revision_matches(p jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE ir record; ip record; parent jsonb; frame jsonb; spec jsonb; req jsonb; family jsonb; template jsonb;
 c jsonb:=p->'context'; matched boolean:=false; catalog constant jsonb:=$catalog525$[{"family_id":"python-kc-binding-v1:trace","definition_hash":"ab9c9963c8f559bbdb95257c1391fc27eb7c1fd4a92aa0f17cde9c6aa646debc","task_kind":"trace","allocation":{"schema_version":"finite_slot_allocation_v2","target_id":"python-kc-binding-v1","family_id":"python-kc-binding-v1:trace","family_definition_hash":"ab9c9963c8f559bbdb95257c1391fc27eb7c1fd4a92aa0f17cde9c6aa646debc","slot":"assessment","purpose":"knowledge_check","clause_refs":[{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C1","clause_definition_hash":"b7c470480baf55d2a3dda27983e622a41d0bf42a19a22f9b3bf5e95a0cbd992e"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C2","clause_definition_hash":"745af86776456d1ad4fcb557987c3975f1a823af0f86349d46951e7030b482dd"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C3","clause_definition_hash":"917c6e8cefcf4f0110eb6f11e2edd41b092172a83e5ca166d7463c326b424c93"}],"guidance":"unguided","binding_requirement":"native_scope"},"templates":[{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"按Python顺序赋值规则，选择数值与原因都正确的一项。检查第2/4行的右值，以及第3/5行重绑定后先前保存的值。\n~~~python\nsource = 4\nsaved = source\nsource = 9\ntail = saved + 3\nsaved = 6\nprint(source, saved, tail)\n~~~","options":[{"option_id":"choice-1","label":"第2/4行右值4/7；但source变化使saved联动为9、tail最终为12；输出9 6 12。"},{"option_id":"choice-2","label":"第2/4行右值提前取后来source的9，得到9/12；saved曾为9、tail为12；输出9 6 12。"},{"option_id":"choice-3","label":"第2/4行右值4/7；source变9后saved仍4，saved变6后tail仍7；输出9 6 7，因为赋值保存当时求出的值。"},{"option_id":"choice-4","label":"第2/4行右值4/7，先前saved为4、tail为7，输出9 6 7；原因是saved=source建立永久等式，后来两边始终联动。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"按Python顺序赋值规则，选择数值与原因都正确的一项。检查第2/4行的右值，以及第3/5行重绑定后先前保存的值。\n~~~python\nsource = 4\nsaved = source\nsource = 9\ntail = saved + 3\nsaved = 6\nprint(source, saved, tail)\n~~~","options":[{"option_id":"choice-1","label":"第2/4行右值提前取后来source的9，得到9/12；saved曾为9、tail为12；输出9 6 12。"},{"option_id":"choice-2","label":"第2/4行右值4/7；source变9后saved仍4，saved变6后tail仍7；输出9 6 7，因为赋值保存当时求出的值。"},{"option_id":"choice-3","label":"第2/4行右值4/7，先前saved为4、tail为7，输出9 6 7；原因是saved=source建立永久等式，后来两边始终联动。"},{"option_id":"choice-4","label":"第2/4行右值4/7；但source变化使saved联动为9、tail最终为12；输出9 6 12。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"按Python顺序赋值规则，选择数值与原因都正确的一项。检查第2/4行的右值，以及第3/5行重绑定后先前保存的值。\n~~~python\nsource = 4\nsaved = source\nsource = 9\ntail = saved + 3\nsaved = 6\nprint(source, saved, tail)\n~~~","options":[{"option_id":"choice-1","label":"第2/4行右值4/7；source变9后saved仍4，saved变6后tail仍7；输出9 6 7，因为赋值保存当时求出的值。"},{"option_id":"choice-2","label":"第2/4行右值4/7，先前saved为4、tail为7，输出9 6 7；原因是saved=source建立永久等式，后来两边始终联动。"},{"option_id":"choice-3","label":"第2/4行右值4/7；但source变化使saved联动为9、tail最终为12；输出9 6 12。"},{"option_id":"choice-4","label":"第2/4行右值提前取后来source的9，得到9/12；saved曾为9、tail为12；输出9 6 12。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"按Python顺序赋值规则，选择数值与原因都正确的一项。检查第2/4行的右值，以及第3/5行重绑定后先前保存的值。\n~~~python\nsource = 4\nsaved = source\nsource = 9\ntail = saved + 3\nsaved = 6\nprint(source, saved, tail)\n~~~","options":[{"option_id":"choice-1","label":"第2/4行右值4/7，先前saved为4、tail为7，输出9 6 7；原因是saved=source建立永久等式，后来两边始终联动。"},{"option_id":"choice-2","label":"第2/4行右值4/7；但source变化使saved联动为9、tail最终为12；输出9 6 12。"},{"option_id":"choice-3","label":"第2/4行右值提前取后来source的9，得到9/12；saved曾为9、tail为12；输出9 6 12。"},{"option_id":"choice-4","label":"第2/4行右值4/7；source变9后saved仍4，saved变6后tail仍7；输出9 6 7，因为赋值保存当时求出的值。"}]}}]},{"family_id":"python-kc-binding-v1:diagnose","definition_hash":"f3e56a40c8242fa794f99d1887ec6e17df30b76a58474d5eb164b8060fcb213c","task_kind":"diagnose","allocation":{"schema_version":"finite_slot_allocation_v2","target_id":"python-kc-binding-v1","family_id":"python-kc-binding-v1:diagnose","family_definition_hash":"f3e56a40c8242fa794f99d1887ec6e17df30b76a58474d5eb164b8060fcb213c","slot":"assessment","purpose":"knowledge_check","clause_refs":[{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C1","clause_definition_hash":"b7c470480baf55d2a3dda27983e622a41d0bf42a19a22f9b3bf5e95a0cbd992e"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C2","clause_definition_hash":"745af86776456d1ad4fcb557987c3975f1a823af0f86349d46951e7030b482dd"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C3","clause_definition_hash":"917c6e8cefcf4f0110eb6f11e2edd41b092172a83e5ca166d7463c326b424c93"}],"guidance":"unguided","binding_requirement":"native_scope"},"templates":[{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"选择首个错误解释的位置、实际值和原因全部正确的一项。\n~~~python\nprice = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)\n~~~\n待诊断解释：①第3行后total=18；②第4行后total自动变成24；③第5行后receipt=25。","options":[{"option_id":"choice-1","label":"首错①：第3/5行右值提前取未来价格，得到24/25；total保持24，输出24 25。"},{"option_id":"choice-2","label":"首错②：第3/5行右值18/19；第4行后total仍为18；输出18 19，因为派生值不自动重算。"},{"option_id":"choice-3","label":"没有错误：第3行右值18，第5行右值25；total联动为24，输出24 25，赋值保存动态公式。"},{"option_id":"choice-4","label":"首错③：第3/5行右值18/19，total仍为18，输出18 19；派生值不重算，但第二步解释正确。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"选择首个错误解释的位置、实际值和原因全部正确的一项。\n~~~python\nprice = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)\n~~~\n待诊断解释：①第3行后total=18；②第4行后total自动变成24；③第5行后receipt=25。","options":[{"option_id":"choice-1","label":"首错②：第3/5行右值18/19；第4行后total仍为18；输出18 19，因为派生值不自动重算。"},{"option_id":"choice-2","label":"没有错误：第3行右值18，第5行右值25；total联动为24，输出24 25，赋值保存动态公式。"},{"option_id":"choice-3","label":"首错③：第3/5行右值18/19，total仍为18，输出18 19；派生值不重算，但第二步解释正确。"},{"option_id":"choice-4","label":"首错①：第3/5行右值提前取未来价格，得到24/25；total保持24，输出24 25。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"选择首个错误解释的位置、实际值和原因全部正确的一项。\n~~~python\nprice = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)\n~~~\n待诊断解释：①第3行后total=18；②第4行后total自动变成24；③第5行后receipt=25。","options":[{"option_id":"choice-1","label":"没有错误：第3行右值18，第5行右值25；total联动为24，输出24 25，赋值保存动态公式。"},{"option_id":"choice-2","label":"首错③：第3/5行右值18/19，total仍为18，输出18 19；派生值不重算，但第二步解释正确。"},{"option_id":"choice-3","label":"首错①：第3/5行右值提前取未来价格，得到24/25；total保持24，输出24 25。"},{"option_id":"choice-4","label":"首错②：第3/5行右值18/19；第4行后total仍为18；输出18 19，因为派生值不自动重算。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"选择首个错误解释的位置、实际值和原因全部正确的一项。\n~~~python\nprice = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)\n~~~\n待诊断解释：①第3行后total=18；②第4行后total自动变成24；③第5行后receipt=25。","options":[{"option_id":"choice-1","label":"首错③：第3/5行右值18/19，total仍为18，输出18 19；派生值不重算，但第二步解释正确。"},{"option_id":"choice-2","label":"首错①：第3/5行右值提前取未来价格，得到24/25；total保持24，输出24 25。"},{"option_id":"choice-3","label":"首错②：第3/5行右值18/19；第4行后total仍为18；输出18 19，因为派生值不自动重算。"},{"option_id":"choice-4","label":"没有错误：第3行右值18，第5行右值25；total联动为24，输出24 25，赋值保存动态公式。"}]}}]},{"family_id":"python-kc-binding-v1:repair","definition_hash":"ff6d8edf86d69ebb32406288ea8e86dae92e72bbc95e240a868f13a2ffa77cf9","task_kind":"repair","allocation":{"schema_version":"finite_slot_allocation_v2","target_id":"python-kc-binding-v1","family_id":"python-kc-binding-v1:repair","family_definition_hash":"ff6d8edf86d69ebb32406288ea8e86dae92e72bbc95e240a868f13a2ffa77cf9","slot":"assessment","purpose":"knowledge_check","clause_refs":[{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C1","clause_definition_hash":"b7c470480baf55d2a3dda27983e622a41d0bf42a19a22f9b3bf5e95a0cbd992e"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C2","clause_definition_hash":"745af86776456d1ad4fcb557987c3975f1a823af0f86349d46951e7030b482dd"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C3","clause_definition_hash":"917c6e8cefcf4f0110eb6f11e2edd41b092172a83e5ca166d7463c326b424c93"}],"guidance":"unguided","binding_requirement":"native_scope"},"templates":[{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"入口x分别为3和8。每个补丁替换缺失的三行，然后执行print(old, new)。要求old保存入口x；把x增加2后，new是更新后x的两倍。两场景均须满足，禁止写死某个场景结果。选择唯一符合全部条件的补丁，核对保存/更新/计算三处右值时点。","options":[{"option_id":"choice-1","label":"~~~python\nx = x + 2\nold = x\nnew = x * 2\n~~~\n先更新再保存。"},{"option_id":"choice-2","label":"~~~python\nold = x\nx = x + 2\nnew = x * 2\n~~~\n先保存旧值，再更新并计算new。"},{"option_id":"choice-3","label":"~~~python\nold = x\nx = x + 2\nnew = 10\n~~~\n保存旧值，用固定10作为new。"},{"option_id":"choice-4","label":"~~~python\nold = x\nnew = x * 2\nx = x + 2\n~~~\n先计算new，再更新x。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"入口x分别为3和8。每个补丁替换缺失的三行，然后执行print(old, new)。要求old保存入口x；把x增加2后，new是更新后x的两倍。两场景均须满足，禁止写死某个场景结果。选择唯一符合全部条件的补丁，核对保存/更新/计算三处右值时点。","options":[{"option_id":"choice-1","label":"~~~python\nold = x\nx = x + 2\nnew = x * 2\n~~~\n先保存旧值，再更新并计算new。"},{"option_id":"choice-2","label":"~~~python\nold = x\nx = x + 2\nnew = 10\n~~~\n保存旧值，用固定10作为new。"},{"option_id":"choice-3","label":"~~~python\nold = x\nnew = x * 2\nx = x + 2\n~~~\n先计算new，再更新x。"},{"option_id":"choice-4","label":"~~~python\nx = x + 2\nold = x\nnew = x * 2\n~~~\n先更新再保存。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"入口x分别为3和8。每个补丁替换缺失的三行，然后执行print(old, new)。要求old保存入口x；把x增加2后，new是更新后x的两倍。两场景均须满足，禁止写死某个场景结果。选择唯一符合全部条件的补丁，核对保存/更新/计算三处右值时点。","options":[{"option_id":"choice-1","label":"~~~python\nold = x\nx = x + 2\nnew = 10\n~~~\n保存旧值，用固定10作为new。"},{"option_id":"choice-2","label":"~~~python\nold = x\nnew = x * 2\nx = x + 2\n~~~\n先计算new，再更新x。"},{"option_id":"choice-3","label":"~~~python\nx = x + 2\nold = x\nnew = x * 2\n~~~\n先更新再保存。"},{"option_id":"choice-4","label":"~~~python\nold = x\nx = x + 2\nnew = x * 2\n~~~\n先保存旧值，再更新并计算new。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"入口x分别为3和8。每个补丁替换缺失的三行，然后执行print(old, new)。要求old保存入口x；把x增加2后，new是更新后x的两倍。两场景均须满足，禁止写死某个场景结果。选择唯一符合全部条件的补丁，核对保存/更新/计算三处右值时点。","options":[{"option_id":"choice-1","label":"~~~python\nold = x\nnew = x * 2\nx = x + 2\n~~~\n先计算new，再更新x。"},{"option_id":"choice-2","label":"~~~python\nx = x + 2\nold = x\nnew = x * 2\n~~~\n先更新再保存。"},{"option_id":"choice-3","label":"~~~python\nold = x\nx = x + 2\nnew = x * 2\n~~~\n先保存旧值，再更新并计算new。"},{"option_id":"choice-4","label":"~~~python\nold = x\nx = x + 2\nnew = 10\n~~~\n保存旧值，用固定10作为new。"}]}}]},{"family_id":"python-kc-binding-v1:counterexample","definition_hash":"39ed371387a05c6cc5193e5df9098e9919bbf82831c937f2c76af76cb7210a1e","task_kind":"counterexample","allocation":{"schema_version":"finite_slot_allocation_v2","target_id":"python-kc-binding-v1","family_id":"python-kc-binding-v1:counterexample","family_definition_hash":"39ed371387a05c6cc5193e5df9098e9919bbf82831c937f2c76af76cb7210a1e","slot":"assessment","purpose":"knowledge_check","clause_refs":[{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C1","clause_definition_hash":"b7c470480baf55d2a3dda27983e622a41d0bf42a19a22f9b3bf5e95a0cbd992e"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C2","clause_definition_hash":"745af86776456d1ad4fcb557987c3975f1a823af0f86349d46951e7030b482dd"},{"definition_version":"1.0.0","status":"declaration_pending","schema_version":"finite_clause_reference_v1","clause_id":"KC-C3","clause_definition_hash":"917c6e8cefcf4f0110eb6f11e2edd41b092172a83e5ca166d7463c326b424c93"}],"guidance":"unguided","binding_requirement":"native_scope"},"templates":[{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"有人断言：对整数执行saved = source后，只要把source重新赋成不同整数，saved也一定随之改变。选择唯一触发source重绑定、反驳断言且右值说明与输出一致的选项。","options":[{"option_id":"choice-1","label":"~~~python\nsource = 4\nsaved = source\nprint(source, saved)\n~~~\n保存时右值4，saved仍4，输出4 4；这足以反驳断言。"},{"option_id":"choice-2","label":"~~~python\nsource = 4\nsaved = source\nsaved = 9\nprint(source, saved)\n~~~\n保存时右值4，saved变9，输出4 9；这足以反驳断言。"},{"option_id":"choice-3","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\n保存时右值4，source重绑定后saved仍4；输出9 4，故不是联动关系。"},{"option_id":"choice-4","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\nsaved的右值延到print时取9，saved变9；输出9 9，却说明saved保持原值，因而反驳断言。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"有人断言：对整数执行saved = source后，只要把source重新赋成不同整数，saved也一定随之改变。选择唯一触发source重绑定、反驳断言且右值说明与输出一致的选项。","options":[{"option_id":"choice-1","label":"~~~python\nsource = 4\nsaved = source\nsaved = 9\nprint(source, saved)\n~~~\n保存时右值4，saved变9，输出4 9；这足以反驳断言。"},{"option_id":"choice-2","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\n保存时右值4，source重绑定后saved仍4；输出9 4，故不是联动关系。"},{"option_id":"choice-3","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\nsaved的右值延到print时取9，saved变9；输出9 9，却说明saved保持原值，因而反驳断言。"},{"option_id":"choice-4","label":"~~~python\nsource = 4\nsaved = source\nprint(source, saved)\n~~~\n保存时右值4，saved仍4，输出4 4；这足以反驳断言。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"有人断言：对整数执行saved = source后，只要把source重新赋成不同整数，saved也一定随之改变。选择唯一触发source重绑定、反驳断言且右值说明与输出一致的选项。","options":[{"option_id":"choice-1","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\n保存时右值4，source重绑定后saved仍4；输出9 4，故不是联动关系。"},{"option_id":"choice-2","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\nsaved的右值延到print时取9，saved变9；输出9 9，却说明saved保持原值，因而反驳断言。"},{"option_id":"choice-3","label":"~~~python\nsource = 4\nsaved = source\nprint(source, saved)\n~~~\n保存时右值4，saved仍4，输出4 4；这足以反驳断言。"},{"option_id":"choice-4","label":"~~~python\nsource = 4\nsaved = source\nsaved = 9\nprint(source, saved)\n~~~\n保存时右值4，saved变9，输出4 9；这足以反驳断言。"}]}},{"instruction_markdown":"### finite-public-task-v3:start\n阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。\n### finite-public-task-v3:end","content":{"type":"knowledge_check","response_kind":"single_choice","prompt_markdown":"有人断言：对整数执行saved = source后，只要把source重新赋成不同整数，saved也一定随之改变。选择唯一触发source重绑定、反驳断言且右值说明与输出一致的选项。","options":[{"option_id":"choice-1","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\nsaved的右值延到print时取9，saved变9；输出9 9，却说明saved保持原值，因而反驳断言。"},{"option_id":"choice-2","label":"~~~python\nsource = 4\nsaved = source\nprint(source, saved)\n~~~\n保存时右值4，saved仍4，输出4 4；这足以反驳断言。"},{"option_id":"choice-3","label":"~~~python\nsource = 4\nsaved = source\nsaved = 9\nprint(source, saved)\n~~~\n保存时右值4，saved变9，输出4 9；这足以反驳断言。"},{"option_id":"choice-4","label":"~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\n保存时右值4，source重绑定后saved仍4；输出9 4，故不是联动关系。"}]}}]}]$catalog525$::jsonb;
BEGIN
 SELECT * INTO ir FROM tutor_item_supply_shared_review_investigation_receipts WHERE id=(p->>'investigation_receipt_id')::uuid FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO ip FROM tutor_item_supply_shared_review_investigation_preparations WHERE id=ir.preparation_id FOR SHARE;
 IF NOT FOUND OR NOT (ip.payload_json ? 'persistent_frame') THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_persistent_normal_repair(ip.payload_json);
 frame:=c->'persistent_family_revision';req:=p->'request'; spec:=frame->'child_specification';
 SELECT payload_json INTO parent FROM tutor_item_supply_shared_persistent_pack_journal
  WHERE public_task_id=(ip.payload_json->'persistent_frame'->'phase'->>'public_task_id')::uuid
   AND record_kind IN('version','qualified') AND payload_json->>'revision_id'=frame->>'parent_revision_id'
  ORDER BY created_at DESC,id LIMIT 1 FOR SHARE;
 IF NOT FOUND OR item_supply_internal.snapshot_keys(c,ARRAY['schema_version','purpose','parent_artifact_id','parent_artifact_hash',
  'parent_source_hash','parent_content_hash','parent_review_hash','investigation_receipt_id','investigation_receipt_hash','investigation_report_hash',
  'child_candidate_id','child_item_key','child_version','scope_hash','policy_hash','target_definition_hash','parent_source','problems',
  'publication_enabled','blockers_discharged','persistent_family_revision']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(spec,ARRAY['schema_version','target_id','target_definition_hash','family_definition_hash','allocation','seed',
     'blueprint','public_template','coverage_blueprint','python_goal','sql_target']) IS DISTINCT FROM true
  OR c->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'
  OR item_supply_internal.snapshot_keys(frame,ARRAY['schema_version','phase_id','public_slot_id','parent_revision_id','parent_specification_hash','finding_key','child_specification']) IS DISTINCT FROM true
  OR frame->>'schema_version' IS DISTINCT FROM 'persistent_registered_family_revision_v1'
  OR frame->'phase_id' IS DISTINCT FROM ip.payload_json->'persistent_frame'->'phase'->'phase_id'
  OR frame->'public_slot_id' IS DISTINCT FROM parent->'public_slot_id'
  OR frame->'parent_revision_id' IS DISTINCT FROM ip.payload_json->'persistent_frame'->'phase'->'revision_id'
  OR frame->>'parent_specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(parent->'specification')
  OR parent->>'artifact_id' IS DISTINCT FROM p->>'parent_artifact_id' OR parent->>'root_id' IS DISTINCT FROM p->>'root_id'
  OR spec->'allocation' IS DISTINCT FROM ip.payload_json->'request_payload'->'revision_allocation'
  OR spec->'seed' IS DISTINCT FROM parent->'specification'->'seed'
  OR spec->'target_id' IS DISTINCT FROM parent->'specification'->'target_id'
  OR spec->>'target_id' IS DISTINCT FROM 'python-kc-binding-v1'
  OR spec->'target_definition_hash' IS DISTINCT FROM parent->'specification'->'target_definition_hash'
  OR spec->'coverage_blueprint' IS DISTINCT FROM parent->'specification'->'coverage_blueprint'
  OR spec->'allocation'->'variant_id' IS DISTINCT FROM parent->'specification'->'allocation'->'variant_id'
  OR spec->'allocation'->>'slot' IS DISTINCT FROM 'assessment'
  OR spec->'allocation'->'family_id' IS NOT DISTINCT FROM parent->'specification'->'allocation'->'family_id'
  OR spec->'blueprint'->>'version' IS DISTINCT FROM 'finite-public-spec-v3'
  OR (spec->'blueprint'-ARRAY['blueprint_key','version']) IS DISTINCT FROM (parent->'specification'->'blueprint'-ARRAY['blueprint_key','version'])
  OR spec->'blueprint' IS DISTINCT FROM req->'blueprint' OR spec->'public_template' IS DISTINCT FROM req->'public_template'
  OR p->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(spec)
  OR spec->'python_goal' IS DISTINCT FROM 'null'::jsonb OR spec->'sql_target' IS DISTINCT FROM 'null'::jsonb
 THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(ip.payload_json->'request_payload'->'disputes') d
   WHERE d->>'schema_version'='persistent_deterministic_clone_finding_v1' AND d->>'dispute_key'=frame->>'finding_key')
 THEN RETURN false; END IF;
 FOR family IN SELECT value FROM jsonb_array_elements(catalog) LOOP
  IF family->'family_id'=spec->'allocation'->'family_id' THEN
   template:=family->'templates'->((spec->>'seed')::integer%4);
   matched:=spec->'family_definition_hash'=family->'definition_hash'
     AND (spec->'allocation'-'variant_id')=family->'allocation'
     AND spec->'public_template'->'content'=template->'content'
     AND spec->'public_template'->'instruction_markdown'=template->'instruction_markdown'
     AND (spec->'public_template'-ARRAY['item_key','version','title','content','instruction_markdown'])
       =(parent->'specification'->'public_template'-ARRAY['item_key','version','title','content','instruction_markdown'])
     AND spec->'public_template'->>'title'='PY-KC-BIND-01 · '||(family->>'task_kind')
     AND spec->'blueprint'->>'blueprint_key'='finite.python-kc-binding-v1.'||split_part(spec->'allocation'->>'variant_id',':',2)||
        '.family-'||(family->>'task_kind')||'.s'||(spec->>'seed');
  END IF;
 END LOOP;
 RETURN COALESCE(matched,false);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.persistent_registered_family_revision_matches(jsonb) FROM PUBLIC;

DO $upgrade525_investigation$
DECLARE actual record; verified record; definition text; source text;
 old_sha constant text:='0adf81528263aff748eeae7aef130c0cebc69a7f1efbf8096f86da7fa7078c93'; new_sha constant text:='4623fa4db4a521346d34be436d14c53e1444273ee4968011e879e53494245f41';
 reviewed_body constant text:=$body525_investigation$
DECLARE control_row tutor_item_supply_shared_job_controls%ROWTYPE;
  artifact_row tutor_item_supply_shared_generation_artifacts%ROWTYPE;
  review_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
  blind_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
  validation_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
  preparation_row tutor_item_supply_shared_review_investigation_preparations%ROWTYPE;
  reservation_row tutor_item_supply_shared_reservations%ROWTYPE;
  settlement_row tutor_item_supply_shared_runtime_settlements%ROWTYPE;
  p jsonb; output_payload jsonb:=NEW.payload_json; snapshot jsonb; stamp timestamptz;
  request_payload jsonb; binding jsonb; dimensions jsonb; material jsonb; source_bound jsonb;
  analysis jsonb; ref jsonb; dispute jsonb; report jsonb; field_value jsonb;
  kind text; amount jsonb; role_names text[]; source_expiry timestamptz;
  material_count integer; expected_disputes integer:=0; persistent_permission boolean:=false;
  quality_job uuid; quality_generation integer; quality_owner text;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='native investigation B1d only';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_review_investigation_receipts' THEN
    SELECT * INTO preparation_row FROM tutor_item_supply_shared_review_investigation_preparations pp
      WHERE pp.id=NEW.preparation_id FOR SHARE;
    IF NOT FOUND OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_preparations pp
      WHERE pp.id=NEW.preparation_id AND pp.xmin::text::bigint=(txid_current()%4294967296))
      OR (NEW.root_id,NEW.job_id,NEW.lease_owner,NEW.lease_generation,NEW.lease_state_version,
          NEW.generation_artifact_id,NEW.review_receipt_id,NEW.reservation_id,NEW.valid_until)
        IS DISTINCT FROM (preparation_row.root_id,preparation_row.job_id,preparation_row.lease_owner,
          preparation_row.lease_generation,preparation_row.lease_state_version,preparation_row.generation_artifact_id,
          preparation_row.review_receipt_id,preparation_row.reservation_id,preparation_row.valid_until) THEN
      RAISE check_violation USING MESSAGE='investigation committed original preparation required';
    END IF;
    p:=preparation_row.payload_json;
  ELSE
    p:=NEW.payload_json;
  END IF;
  IF p ? 'persistent_frame' THEN
    PERFORM item_supply_internal.assert_persistent_normal_repair(p);
    persistent_permission:=true;
  END IF;
  SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls co WHERE co.job_id=NEW.job_id FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='investigation current control missing'; END IF;
  snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
  stamp:=clock_timestamp();
  IF control_row.state IS DISTINCT FROM 'leased' OR control_row.lease_owner IS DISTINCT FROM NEW.lease_owner
    OR control_row.lease_generation<>NEW.lease_generation OR control_row.state_version<>NEW.lease_state_version
    OR control_row.lease_expires_at IS NULL OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
    OR NEW.valid_until<=stamp OR NEW.valid_until>LEAST(control_row.lease_expires_at,control_row.parent_deadline,
      (snapshot->>'parent_deadline_at')::timestamptz,
      (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint * interval '1 millisecond'))
    OR p->'lease'->'profile' IS DISTINCT FROM snapshot
    OR p->'lease'->>'visibility' IS DISTINCT FROM 'public'
    OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
    OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
    OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
    OR (snapshot->'values'->>'discussion_rounds')::integer<2
    OR (snapshot->'values'->>'investigation_rounds')::integer<1
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_parameter_profiles pr WHERE pr.id=control_row.profile_id
      AND pr.profile_hash=snapshot->>'profile_hash' AND pr.profile_key_hash=snapshot->>'profile_key_hash'
      AND pr.profile_json->'profile_key'->>'provider'=p->'identity'->>'provider'
      AND pr.profile_json->'profile_key'->>'model_version'=p->'identity'->>'model_version') THEN
    RAISE check_violation USING MESSAGE='investigation exact current lease/profile required';
  END IF;
  -- Current legal position can still be reviewing: original SharedReview does
  -- not checkpoint until later facts/coverage. Never fabricate that checkpoint.
  IF (NOT persistent_permission AND (NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='validating' AND cp.status='completed')
    OR NOT (EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='generating' AND cp.status='completed')
      OR item_supply_internal.shared_continuation_generation_inherited(NEW.job_id))))
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id
      AND cp.stage IN ('investigating','revising','simulating','admitting') AND cp.status='completed') THEN
    RAISE check_violation USING MESSAGE='investigation original reviewing or investigating position required';
  END IF;
  SELECT * INTO artifact_row FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id FOR SHARE;
  SELECT * INTO review_row FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id FOR SHARE;
  quality_job:=CASE WHEN persistent_permission THEN review_row.job_id ELSE NEW.job_id END;
  quality_generation:=CASE WHEN persistent_permission THEN review_row.lease_generation ELSE NEW.lease_generation END;
  quality_owner:=CASE WHEN persistent_permission THEN review_row.lease_owner ELSE NEW.lease_owner END;
  IF artifact_row.id IS NULL OR review_row.id IS NULL OR artifact_row.root_id<>NEW.root_id
    OR review_row.job_id<>quality_job OR review_row.lease_generation<>quality_generation
    OR review_row.lease_owner IS DISTINCT FROM quality_owner OR review_row.artifact_kind<>'review_bundle'
    OR review_row.mode<>'live' OR review_row.generation_artifact_id<>artifact_row.id
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id AND rr.xmin::text::bigint=(txid_current()%4294967296))
    OR item_supply_internal.shared_stage_original_matches(quality_job,quality_generation,artifact_row.id,review_row.continuation_binding_hash) IS DISTINCT FROM true
    OR (NOT persistent_permission AND p->>'continuation_binding_hash' IS DISTINCT FROM review_row.continuation_binding_hash)
    OR review_row.source_hash IS DISTINCT FROM artifact_row.source_hash OR review_row.content_hash IS DISTINCT FROM artifact_row.content_hash
    OR (NOT persistent_permission AND (EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=artifact_row.id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.generation_artifact_id=artifact_row.id AND rr.artifact_kind='admission_evaluation')
    OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe WHERE pe.version_id=artifact_row.version_id))) THEN
    RAISE check_violation USING MESSAGE='investigation original complete review or terminal history mismatch';
  END IF;
  request_payload:=p->'request_payload'; binding:=request_payload->'review_input'->'binding'; dimensions:=p->'resources';
  IF p->>'root_id' IS DISTINCT FROM NEW.root_id::text OR p->>'generation_artifact_id' IS DISTINCT FROM artifact_row.id::text
    OR p->>'artifact_hash' IS DISTINCT FROM artifact_row.artifact_hash OR p->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
    OR p->>'review_receipt_hash' IS DISTINCT FROM review_row.receipt_hash
    OR p->>'reservation_id' IS DISTINCT FROM NEW.reservation_id::text
    OR p->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(request_payload)
    OR (p->>'deadline_at')::timestamptz IS DISTINCT FROM NEW.valid_until
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
    OR request_payload->>'schema_version' IS DISTINCT FROM (CASE WHEN persistent_permission THEN 'persistent_normal_investigation_input_v1' ELSE 'native_shared_review_investigation_input_v1' END)
    OR request_payload->>'purpose' IS DISTINCT FROM (CASE WHEN persistent_permission THEN 'same_item_substantive_repair' ELSE 'live_dispute_investigation' END)
    OR request_payload->>'authority' IS DISTINCT FROM 'original_shared_owner_required'
    OR request_payload->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
    OR request_payload->>'review_receipt_hash' IS DISTINCT FROM review_row.receipt_hash
    OR request_payload ?| ARRAY['bundle','blind_solve','score','answer','lease','budget']
    OR request_payload->'review_input'->'source' IS DISTINCT FROM artifact_row.source_json
    OR binding IS DISTINCT FROM review_row.payload_json->'binding'
    OR (CASE WHEN persistent_permission THEN request_payload->>'execution_profile_hash' ELSE binding->>'profile_hash' END) IS DISTINCT FROM snapshot->>'profile_hash'
    OR p->'identity'->>'provider' IS DISTINCT FROM 'deepseek' OR p->'identity'->>'model' IS DISTINCT FROM 'deepseek-flash'
    OR p->'identity'->>'identity' IS DISTINCT FROM 'deepseek.native.shared.investigator'
    OR (p->>'timeout_seconds')::numeric<=0 OR (p->>'timeout_seconds')::numeric>3600
    OR (p->>'timeout_seconds')::numeric*1000>(snapshot->'values'->>'request_timeout_ms')::numeric THEN
    RAISE check_violation USING MESSAGE='investigation source/request/protocol binding mismatch';
  END IF;
  IF p ?| ARRAY['user_id','epoch','learner_id','learner_payload','private_demand']
    OR output_payload ?| ARRAY['user_id','epoch','learner_id','learner_payload','private_demand']
    OR (TG_TABLE_NAME='tutor_item_supply_shared_review_investigation_preparations' AND p->>'preparation_id' IS DISTINCT FROM NEW.id::text)
    OR review_row.artifact_key IS DISTINCT FROM 'review_bundle.'||replace(p->>'original_review_reservation_id','-','')
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rs
      JOIN tutor_item_supply_shared_runtime_settlements us ON us.reservation_id=rs.id
      WHERE rs.id=(p->>'original_review_reservation_id')::uuid AND rs.job_id=quality_job
        AND rs.root_id=NEW.root_id AND rs.lease_generation=quality_generation
        AND rs.reservation_key='review.'||replace(artifact_row.id::text,'-','')
        AND us.settlement_key=rs.reservation_key AND us.usage_state='unknown'
        AND us.xmin::text::bigint<>(txid_current()%4294967296)) THEN
    RAISE check_violation USING MESSAGE='investigation original shared review accounting required';
  END IF;
  SELECT * INTO validation_row FROM tutor_item_supply_shared_pipeline_receipts vr WHERE vr.id=(p->>'validation_receipt_id')::uuid;
  SELECT * INTO blind_row FROM tutor_item_supply_shared_pipeline_receipts br WHERE br.id=(p->>'blind_receipt_id')::uuid;
  IF validation_row.id IS NULL OR blind_row.id IS NULL
    OR validation_row.job_id<>quality_job OR validation_row.lease_generation<>quality_generation
    OR validation_row.generation_artifact_id<>artifact_row.id OR validation_row.artifact_kind<>'validation'
    OR validation_row.payload_json IS DISTINCT FROM request_payload->'review_input'->'validation_receipt'
    OR blind_row.job_id<>quality_job OR blind_row.lease_generation<>quality_generation
    OR blind_row.generation_artifact_id<>artifact_row.id OR blind_row.artifact_kind<>'blind_solve'
    OR blind_row.artifact_key IS DISTINCT FROM 'blind_solve.'||replace(p->>'original_review_reservation_id','-','')
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr
      WHERE rr.id IN (validation_row.id,blind_row.id) AND rr.xmin::text::bigint=(txid_current()%4294967296))
    OR blind_row.payload_json IS DISTINCT FROM review_row.payload_json->'blind_solve'
    OR review_row.payload_json->>'state' IS DISTINCT FROM 'completed'
    OR review_row.payload_json->>'mode' IS DISTINCT FROM 'peer_blind'
    OR jsonb_array_length(review_row.payload_json->'reports')<>6 THEN
    RAISE check_violation USING MESSAGE='investigation committed full validation/blind/six review required';
  END IF;
  SELECT array_agg(r->>'role' ORDER BY r->>'role') INTO role_names FROM jsonb_array_elements(review_row.payload_json->'reports') r;
  IF role_names IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[] THEN
    RAISE check_violation USING MESSAGE='investigation all six original responsibilities required';
  END IF;
  IF jsonb_array_length(request_payload->'disputes') NOT BETWEEN 1 AND 144
    OR jsonb_array_length(request_payload->'evidence_index') NOT BETWEEN 1 AND 1024 THEN
    RAISE check_violation USING MESSAGE='investigation bounded concrete disputes required';
  END IF;
  FOR report IN SELECT value FROM jsonb_array_elements(review_row.payload_json->'reports') LOOP
    SELECT count(*) INTO material_count FROM jsonb_array_elements(report->'findings') ff
      WHERE ff->'blocking'='true'::jsonb OR ff->>'severity' IN ('major','critical')
        OR ff->>'safe_code' IN ('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit');
    expected_disputes:=expected_disputes+CASE WHEN material_count>0 THEN material_count
      WHEN report->>'verdict'<>'approved' THEN 1 ELSE 0 END;
  END LOOP;
  IF persistent_permission THEN
    expected_disputes:=expected_disputes+(SELECT count(*) FROM jsonb_array_elements(request_payload->'disputes') d
      WHERE d->>'schema_version'='persistent_deterministic_clone_finding_v1');
  END IF;
  IF jsonb_array_length(request_payload->'disputes')<>expected_disputes
    OR (SELECT count(DISTINCT dd->>'dispute_key') FROM jsonb_array_elements(request_payload->'disputes') dd)<>expected_disputes THEN
    RAISE check_violation USING MESSAGE='investigation cannot drop or merge original material disputes';
  END IF;
  FOR dispute IN SELECT value FROM jsonb_array_elements(request_payload->'disputes') LOOP
    IF persistent_permission AND dispute->>'schema_version'='persistent_deterministic_clone_finding_v1' THEN CONTINUE; END IF;
    IF dispute->>'dispute_key' !~ '^[0-9a-f]{64}$'
      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(review_row.payload_json->'reports') rr
        WHERE rr->>'role'=dispute->>'role' AND (dispute->'finding'='null'::jsonb OR rr->'findings' @> jsonb_build_array(dispute->'finding'))) THEN
      RAISE check_violation USING MESSAGE='investigation exact original finding required';
    END IF;
    SELECT value INTO report FROM jsonb_array_elements(review_row.payload_json->'reports') rr
      WHERE rr->>'role'=dispute->>'role';
    IF dispute->>'report_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(report)
      OR (dispute->>'finding_index' IS NOT NULL AND (
        report->'findings'->((dispute->>'finding_index')::integer) IS DISTINCT FROM dispute->'finding'
        OR NOT (dispute->'finding'->'blocking'='true'::jsonb OR dispute->'finding'->>'severity' IN ('major','critical')
          OR dispute->'finding'->>'safe_code' IN ('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit'))
        OR dispute->>'finding_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(dispute->'finding')
        OR dispute->>'dispute_key' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_array(
          review_row.receipt_hash,dispute->>'report_hash',(dispute->>'finding_index')::integer,dispute->>'finding_hash'))))
      OR (dispute->>'finding_index' IS NULL AND (dispute->'finding' IS DISTINCT FROM 'null'::jsonb
        OR report->>'verdict'='approved' OR dispute->>'dispute_key' IS DISTINCT FROM item_supply_internal.snapshot_hash(
          jsonb_build_array(review_row.receipt_hash,dispute->>'report_hash')))) THEN
      RAISE check_violation USING MESSAGE='investigation immutable report/finding identity required';
    END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(request_payload->'evidence_index') ix
    GROUP BY ix->>'pointer' HAVING count(*)<>1) THEN
    RAISE check_violation USING MESSAGE='investigation unique leaf field index required';
  END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(request_payload->'evidence_index') LOOP
    field_value:=item_supply_internal.review_investigation_pointer_value(request_payload->'review_input',ref->>'pointer');
    IF jsonb_typeof(ref) IS DISTINCT FROM 'object'
      OR (ref - ARRAY['pointer','value_hash']) <> '{}'::jsonb
      OR jsonb_typeof(ref->'pointer') IS DISTINCT FROM 'string'
      OR jsonb_typeof(ref->'value_hash') IS DISTINCT FROM 'string'
      OR field_value IS NULL OR jsonb_typeof(field_value) IN ('object','array')
      OR ref->>'value_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(field_value) THEN
      RAISE check_violation USING MESSAGE='investigation field index must match actual projected fields';
    END IF;
  END LOOP;
  -- Complete RAG proof/source currency is still rechecked by SAME concrete
  -- connection owner. SQL also rejects revoked/expired retained native claims.
  IF artifact_row.request_json->>'demand_binding' IS NOT NULL
    OR jsonb_array_length(p->'source_deadlines')<>jsonb_array_length(artifact_row.request_json->'materials') THEN
    RAISE check_violation USING MESSAGE='investigation public source-only payload required';
  END IF;
  FOR material IN SELECT value FROM jsonb_array_elements(artifact_row.request_json->'materials') LOOP
    SELECT ev.expires_at INTO source_expiry FROM rag_source_claim_receipts cr
      JOIN rag_assessment_source_evidence ev ON ev.id=cr.assessment_evidence_id
      JOIN rag_source_admissions ad ON ad.id=cr.admission_id
      JOIN rag_registered_source_captures ca ON ca.id=ev.capture_id
      JOIN rag_registered_source_policies po ON po.policy_id=ev.policy_id
      WHERE cr.receipt_handle=material->'exact_claims'->0->>'claim_receipt_id'
        AND cr.claim_hash=material->'exact_claims'->0->>'claim_hash'
        AND cr.revoked_at IS NULL AND ev.revoked_at IS NULL AND ad.active AND ad.revoked_at IS NULL
        AND 'assessment_evidence'=ANY(ad.allowed_usages)
        AND ca.cleared_at IS NULL AND ca.retention_until>=NEW.valid_until AND po.enabled AND po.revoked_at IS NULL
        AND po.generation=ev.policy_generation AND ca.generation=ev.policy_generation
        AND ev.expires_at>stamp AND ev.document_hash=material->'binding'->'evidence'->0->'binding'->>'document_hash'
        FOR SHARE OF cr,ev,ad,ca,po;
    SELECT value INTO source_bound FROM jsonb_array_elements(p->'source_deadlines') sb
      WHERE sb->>'binding_digest'=material->'binding'->>'binding_digest'
        AND sb->>'claim_receipt_id'=material->'exact_claims'->0->>'claim_receipt_id';
    IF source_expiry IS NULL OR source_bound IS NULL OR NEW.valid_until>source_expiry
      OR NEW.valid_until>(source_bound->>'retained_until')::timestamptz THEN
      RAISE check_violation USING MESSAGE='investigation current native source evidence expired';
    END IF;
  END LOOP;
  SELECT * INTO reservation_row FROM tutor_item_supply_shared_reservations rs WHERE rs.id=NEW.reservation_id FOR SHARE;
  IF reservation_row.id IS NULL OR reservation_row.root_id<>NEW.root_id OR reservation_row.job_id<>NEW.job_id
    OR reservation_row.lease_generation<>NEW.lease_generation
    OR reservation_row.reservation_key IS DISTINCT FROM 'investigate.'||replace(artifact_row.id::text,'-','')||'.'||replace(NEW.review_receipt_id::text,'-','')
    OR p->>'reservation_key' IS DISTINCT FROM reservation_row.reservation_key
    OR reservation_row.requests<>1 OR reservation_row.resources<>0
    OR reservation_row.tokens<>(dimensions->>'input_tokens')::bigint+(dimensions->>'output_tokens')::bigint
    OR dimensions->>'requests' IS DISTINCT FROM '1' OR dimensions->>'investigation_rounds' IS DISTINCT FROM '1'
    OR dimensions->>'output_tokens' IS DISTINCT FROM '61440'
    OR (dimensions->>'input_tokens')::bigint NOT BETWEEN 1 AND 262144
    OR dimensions->>'execution_seconds' IS DISTINCT FROM '0' OR dimensions->>'fetches' IS DISTINCT FROM '0'
    OR dimensions->>'candidates' IS DISTINCT FROM '0' OR dimensions->>'revision_rounds' IS DISTINCT FROM '0' THEN
    RAISE check_violation USING MESSAGE='investigation independent original reservation amounts mismatch';
  END IF;
  FOR kind,amount IN SELECT key,value FROM jsonb_each(dimensions) LOOP
    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
      WHERE ra.reservation_namespace='shared' AND ra.reservation_id=NEW.reservation_id AND ra.resource_kind=kind)
      OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
        WHERE ra.reservation_namespace='shared' AND ra.reservation_id=NEW.reservation_id AND ra.resource_kind=kind AND ra.reserved_amount<>(amount::text)::bigint) THEN
      RAISE check_violation USING MESSAGE='investigation original cumulative reservation missing';
    END IF;
  END LOOP;
  IF TG_TABLE_NAME='tutor_item_supply_shared_review_investigation_receipts' THEN
    SELECT * INTO settlement_row FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=NEW.settlement_id;
    IF settlement_row.id IS NULL OR settlement_row.reservation_id<>NEW.reservation_id
      OR settlement_row.settlement_key IS DISTINCT FROM reservation_row.reservation_key
      OR settlement_row.usage_state IS DISTINCT FROM 'unknown'
      OR settlement_row.cost_amount IS NOT NULL OR settlement_row.receipt_hash IS NOT NULL
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts sa WHERE sa.settlement_id=NEW.settlement_id)
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=NEW.settlement_id AND ss.xmin::text::bigint=(txid_current()%4294967296))
      OR output_payload->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text
      OR output_payload->>'reservation_id' IS DISTINCT FROM NEW.reservation_id::text
      OR output_payload->>'preparation_hash' IS DISTINCT FROM preparation_row.snapshot_hash
      OR output_payload->>'request_hash' IS DISTINCT FROM p->>'request_hash'
      OR output_payload->>'review_receipt_hash' IS DISTINCT FROM review_row.receipt_hash
      OR output_payload->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
      OR jsonb_array_length(output_payload->'disputes')<>jsonb_array_length(request_payload->'disputes')
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(request_payload->'disputes') dd
        WHERE (SELECT count(*) FROM jsonb_array_elements(output_payload->'disputes') rr
          WHERE rr->>'dispute_key'=dd->>'dispute_key' AND rr->>'report_hash' IS NOT DISTINCT FROM dd->>'report_hash'
            AND rr->>'finding_hash' IS NOT DISTINCT FROM dd->>'finding_hash'
            AND rr->>'finding_index' IS NOT DISTINCT FROM dd->>'finding_index')<>1)
      OR output_payload->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
      OR output_payload->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
      OR output_payload->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
      OR output_payload->>'usage_state' IS DISTINCT FROM 'unknown'
      OR output_payload->>'state' IS DISTINCT FROM 'investigation_pending_revision_owner'
      OR output_payload->>'safe_reason' IS NULL
      OR output_payload->>'safe_reason' NOT IN ('investigation_analysis_pending_revision_owner','investigation_provider_or_fence_pending')
      OR (output_payload->>'safe_reason'='investigation_provider_or_fence_pending'
        AND output_payload->'report' IS DISTINCT FROM 'null'::jsonb) THEN
      RAISE check_violation USING MESSAGE='investigation committed UNKNOWN result binding mismatch';
    END IF;
    report:=output_payload->'report';
    IF report IS DISTINCT FROM 'null'::jsonb THEN
      IF report->>'schema_version' IS DISTINCT FROM (CASE WHEN persistent_permission THEN 'persistent_normal_investigation_report_v1' ELSE 'native_shared_review_investigation_report_v1' END)
        OR report->'output'->>'schema_version' IS DISTINCT FROM 'native_shared_review_investigation_output_v1'
        OR report->'binding' IS DISTINCT FROM binding OR report->>'review_receipt_hash' IS DISTINCT FROM review_row.receipt_hash
        OR report->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
        OR report->'run'->'provider_identity' IS DISTINCT FROM p->'identity'
        OR report->'run'->>'input_hash' IS DISTINCT FROM p->>'request_hash'
        OR report->'run'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
        OR ((NOT persistent_permission AND (report->'run'->>'prompt_version' IS NULL OR report->'run'->>'prompt_version' NOT IN
          ('native-shared-review-investigation-v1', 'native-shared-review-investigation-v2'))) OR (persistent_permission AND report->'run'->>'prompt_version' IS DISTINCT FROM 'native-persistent-normal-investigation-v1'))
        OR report->'run'->>'max_output_tokens' IS DISTINCT FROM '61440'
        OR (report->'run'->>'timeout_seconds')::numeric>(p->>'timeout_seconds')::numeric
        OR report->'run'->>'output_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(report->'output')
        OR report->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR report->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
        OR jsonb_array_length(report->'output'->'analyses')<>jsonb_array_length(request_payload->'disputes') THEN
        RAISE check_violation USING MESSAGE='investigation actual one-call report mismatch';
      END IF;
      FOR dispute IN SELECT value FROM jsonb_array_elements(request_payload->'disputes') LOOP
        IF (SELECT count(*) FROM jsonb_array_elements(report->'output'->'analyses') aa WHERE aa->>'dispute_key'=dispute->>'dispute_key')<>1 THEN
          RAISE check_violation USING MESSAGE='investigation all original disputes retained';
        END IF;
      END LOOP;
      FOR analysis IN SELECT value FROM jsonb_array_elements(report->'output'->'analyses') LOOP
        IF jsonb_typeof(analysis) IS DISTINCT FROM 'object'
          OR (analysis - ARRAY['dispute_key','finding_status','analysis','verification_question','proposed_revision','references']) <> '{}'::jsonb
          OR jsonb_typeof(analysis->'finding_status') IS DISTINCT FROM 'string'
          OR analysis->>'finding_status' NOT IN ('supported','contested','insufficient_evidence')
          OR jsonb_typeof(analysis->'analysis') IS DISTINCT FROM 'string'
          OR jsonb_typeof(analysis->'verification_question') IS DISTINCT FROM 'string'
          OR length(analysis->>'analysis') NOT BETWEEN 1 AND 1600 OR analysis->>'analysis' !~ '\S'
          OR length(analysis->>'verification_question') NOT BETWEEN 1 AND 1200 OR analysis->>'verification_question' !~ '\S'
          OR (analysis ? 'proposed_revision' AND analysis->'proposed_revision' <> 'null'::jsonb AND (
            jsonb_typeof(analysis->'proposed_revision') IS DISTINCT FROM 'string'
            OR length(analysis->>'proposed_revision') NOT BETWEEN 1 AND 1600 OR analysis->>'proposed_revision' !~ '\S'))
          OR jsonb_typeof(analysis->'references') IS DISTINCT FROM 'array'
          OR jsonb_array_length(analysis->'references') NOT BETWEEN 1 AND 6
          OR (SELECT count(DISTINCT ar->>'pointer') FROM jsonb_array_elements(analysis->'references') ar)
            <>jsonb_array_length(analysis->'references') THEN
          RAISE check_violation USING MESSAGE='investigation concrete bounded analysis required';
        END IF;
        SELECT value INTO dispute FROM jsonb_array_elements(request_payload->'disputes') dd
          WHERE dd->>'dispute_key'=analysis->>'dispute_key';
        IF jsonb_array_length(dispute->'references')>0 AND NOT EXISTS(
          SELECT 1 FROM jsonb_array_elements(analysis->'references') ar,
            jsonb_array_elements(dispute->'references') dr
          WHERE ar->>'pointer'=dr->>'pointer'
            OR left(ar->>'pointer',length(dr->>'pointer')+1)=(dr->>'pointer')||'/') THEN
          RAISE check_violation USING MESSAGE='investigation original finding field location required';
        END IF;
        FOR ref IN SELECT value FROM jsonb_array_elements(analysis->'references') LOOP
          IF jsonb_typeof(ref) IS DISTINCT FROM 'object'
            OR (ref - ARRAY['pointer','value_hash']) <> '{}'::jsonb
            OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(request_payload->'evidence_index') ix
            WHERE ix->>'pointer'=ref->>'pointer' AND ix->>'value_hash'=ref->>'value_hash') THEN
            RAISE check_violation USING MESSAGE='investigation exact field references required';
          END IF;
        END LOOP;
      END LOOP;
    END IF;
  END IF;
  IF clock_timestamp()>=NEW.valid_until OR clock_timestamp()>=control_row.lease_expires_at OR clock_timestamp()>=control_row.parent_deadline THEN
    RAISE check_violation USING MESSAGE='investigation final insertion deadline reached';
  END IF;
  IF persistent_permission THEN PERFORM item_supply_internal.assert_persistent_normal_repair(p); END IF;
  RETURN NEW;
END $body525_investigation$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()');
 IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql' OR actual.pronargs<>0
  OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset OR actual.proisstrict
  OR NOT actual.prosecdef OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
 THEN RAISE check_violation USING MESSAGE='525 original investigation receiver attributes changed'; END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR encode(sha256(convert_to(reviewed_body,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='525 unknown original investigation receiver source'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1
 THEN RAISE check_violation USING MESSAGE='525 original investigation receiver framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,reviewed_body);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='525 original investigation attributes/owner/ACL not preserved'; END IF;
END $upgrade525_investigation$;

DO $upgrade525_revision$
DECLARE actual record; verified record; definition text; source text;
 old_sha constant text:='fccbd68dac8bfebebc6a7deb89de33df383a6a214604027716864c838b9e83b3'; new_sha constant text:='15b0fbedb2def4854104b90b527ba261ba7583bd148fb7daeff76aca257cebc4';
 reviewed_body constant text:=$body525_revision$
DECLARE preparation_row tutor_item_supply_shared_revision_preparations%ROWTYPE;
  investigation_row tutor_item_supply_shared_review_investigation_receipts%ROWTYPE;
  investigation_prep tutor_item_supply_shared_review_investigation_preparations%ROWTYPE;
  parent_artifact tutor_item_supply_shared_generation_artifacts%ROWTYPE;
  child_artifact tutor_item_supply_shared_generation_artifacts%ROWTYPE;
  parent_control tutor_item_supply_shared_job_controls%ROWTYPE;
  child_control tutor_item_supply_shared_job_controls%ROWTYPE;
  child_job tutor_item_supply_shared_jobs%ROWTYPE;
  author_reservation tutor_item_supply_shared_reservations%ROWTYPE;
  author_usage tutor_item_supply_shared_runtime_settlements%ROWTYPE;
  p jsonb; context_payload jsonb; request_payload jsonb; snapshot jsonb; stamp timestamptz;
  issue jsonb; source_bound jsonb; actual_input jsonb; kind text; amount jsonb;
  persistent_permission boolean:=false; family_permission boolean:=false;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='revision B1d only'; END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_revision_lineage' THEN
    SELECT * INTO preparation_row FROM tutor_item_supply_shared_revision_preparations pp WHERE pp.id=NEW.preparation_id FOR SHARE;
    IF NOT FOUND OR (NEW.root_id,NEW.child_job_id,NEW.parent_artifact_id) IS DISTINCT FROM
      (preparation_row.root_id,preparation_row.child_job_id,preparation_row.parent_artifact_id) THEN
      RAISE check_violation USING MESSAGE='revision original preparation missing';
    END IF;
    p:=preparation_row.payload_json;
  ELSE p:=NEW.payload_json; END IF;
  SELECT * INTO investigation_row FROM tutor_item_supply_shared_review_investigation_receipts ir
    WHERE ir.id=(p->>'investigation_receipt_id')::uuid FOR SHARE;
  SELECT * INTO investigation_prep FROM tutor_item_supply_shared_review_investigation_preparations ip
    WHERE ip.id=investigation_row.preparation_id FOR SHARE;
  SELECT * INTO parent_artifact FROM tutor_item_supply_shared_generation_artifacts pa WHERE pa.id=NEW.parent_artifact_id FOR SHARE;
  SELECT * INTO parent_control FROM tutor_item_supply_shared_job_controls pc WHERE pc.job_id=(p->>'parent_job_id')::uuid FOR UPDATE;
  SELECT * INTO child_job FROM tutor_item_supply_shared_jobs cj WHERE cj.id=NEW.child_job_id FOR SHARE;
  SELECT * INTO child_control FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.child_job_id FOR UPDATE;
  -- New normal branch is closed by the SAME original investigation/phase receiver.
  IF investigation_prep.payload_json ? 'persistent_frame' THEN
    IF item_supply_internal.controlled_counterexample_held(parent_artifact.job_id) IS DISTINCT FROM false
      OR item_supply_internal.controlled_counterexample_held(NEW.child_job_id) IS DISTINCT FROM false
    THEN RAISE check_violation USING MESSAGE='525 controlled ancestry denied first'; END IF;
    PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);
    persistent_permission:=true;
    IF p->'context'->>'schema_version'='native_revision_author_context_v2' THEN
      family_permission:=item_supply_internal.persistent_registered_family_revision_matches(p);
      IF family_permission IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='525 exact registered family child required'; END IF;
    END IF;
    IF investigation_prep.payload_json->'request_payload'->'revision_allocation' IS DISTINCT FROM 'null'::jsonb
      AND NOT family_permission THEN RAISE check_violation USING MESSAGE='525 frozen clone family cannot become v1 text reroll'; END IF;
  END IF;
  context_payload:=p->'context'; request_payload:=p->'request'; stamp:=clock_timestamp();
  snapshot:=CASE WHEN child_control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN child_control.profile_snapshot_json->'profile' ELSE child_control.profile_snapshot_json END;
  IF investigation_row.id IS NULL OR investigation_prep.id IS NULL OR parent_artifact.id IS NULL
    OR parent_control.id IS NULL OR child_control.id IS NULL OR child_job.id IS NULL
    OR child_job.root_id IS DISTINCT FROM NEW.root_id OR parent_artifact.root_id IS DISTINCT FROM NEW.root_id
    OR investigation_row.root_id IS DISTINCT FROM NEW.root_id OR investigation_row.generation_artifact_id IS DISTINCT FROM NEW.parent_artifact_id
    OR investigation_row.job_id IS DISTINCT FROM parent_control.job_id
    OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text OR p->>'parent_artifact_id' IS DISTINCT FROM NEW.parent_artifact_id::text
    OR p->'child_lease'->>'job_id' IS DISTINCT FROM NEW.child_job_id::text
    OR jsonb_typeof(context_payload) IS DISTINCT FROM 'object' OR jsonb_typeof(request_payload) IS DISTINCT FROM 'object'
    OR jsonb_typeof(context_payload->'problems') IS DISTINCT FROM 'array'
    OR jsonb_typeof(snapshot->'values') IS DISTINCT FROM 'object'
    OR p->'source_deadlines' IS DISTINCT FROM investigation_prep.payload_json->'source_deadlines'
    OR child_job.parent_job_id IS DISTINCT FROM parent_control.job_id OR child_job.id=parent_control.job_id
    OR investigation_row.snapshot_hash IS DISTINCT FROM p->>'investigation_receipt_hash'
    OR investigation_row.payload_json->>'safe_reason' IS DISTINCT FROM 'investigation_analysis_pending_revision_owner'
    OR jsonb_typeof(investigation_row.payload_json->'report') IS DISTINCT FROM 'object'
    OR investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts ir WHERE ir.id=investigation_row.id AND ir.xmin::text::bigint=(txid_current()%4294967296))
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=investigation_row.settlement_id
      AND ss.reservation_id=investigation_row.reservation_id AND ss.settlement_key=investigation_prep.payload_json->>'reservation_key'
      AND ss.usage_state='unknown' AND ss.xmin::text::bigint<>(txid_current()%4294967296))
    OR parent_control.state IS DISTINCT FROM 'leased' OR child_control.state IS DISTINCT FROM 'leased'
    OR parent_control.lease_expires_at IS NULL OR child_control.lease_expires_at IS NULL
    OR parent_control.lease_expires_at<=stamp OR child_control.lease_expires_at<=stamp
    OR parent_control.parent_deadline<=stamp OR child_control.parent_deadline<=stamp
    OR child_control.parent_deadline>parent_control.parent_deadline
    OR parent_control.lease_owner IS DISTINCT FROM p->'parent_lease'->>'lease_owner'
    OR parent_control.lease_generation::text IS DISTINCT FROM p->'parent_lease'->>'generation'
    OR parent_control.state_version::text IS DISTINCT FROM p->'parent_lease'->>'state_version'
    OR p->'parent_lease' IS DISTINCT FROM investigation_prep.payload_json->'lease'
    OR snapshot IS DISTINCT FROM p->'child_lease'->'profile' OR request_payload->'profile' IS DISTINCT FROM snapshot
    OR snapshot->>'profile_hash' IS DISTINCT FROM p->'parent_lease'->'profile'->>'profile_hash'
    OR snapshot->'values' IS DISTINCT FROM p->'parent_lease'->'profile'->'values'
    OR (snapshot->'values'->>'discussion_rounds')::integer<2 OR (snapshot->'values'->>'revision_rounds')::integer<1
    OR p->'child_lease'->>'visibility' IS DISTINCT FROM 'public'
    OR p->'child_lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'child_lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR (p->>'deadline_at')::timestamptz<=stamp OR (p->>'deadline_at')::timestamptz>LEAST(investigation_row.valid_until,
      investigation_prep.valid_until,parent_control.lease_expires_at,child_control.lease_expires_at,child_control.parent_deadline,
      (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'))
    OR (NOT persistent_permission AND (EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=parent_artifact.id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.generation_artifact_id=parent_artifact.id AND rr.artifact_kind='admission_evaluation')
    OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe WHERE pe.version_id=parent_artifact.version_id))) THEN
    RAISE check_violation USING MESSAGE='revision current original investigation/child/source/history required';
  END IF;
  IF context_payload->>'schema_version' IS DISTINCT FROM (CASE WHEN family_permission THEN 'native_revision_author_context_v2' ELSE 'native_revision_author_context_v1' END)
    OR context_payload->>'purpose' IS DISTINCT FROM 'bounded_content_revision_not_admission'
    OR context_payload->'parent_source' IS DISTINCT FROM parent_artifact.source_json
    OR context_payload->>'parent_artifact_hash' IS DISTINCT FROM parent_artifact.artifact_hash
    OR p->>'parent_artifact_hash' IS DISTINCT FROM parent_artifact.artifact_hash
    OR p->>'parent_substantive_hash' IS DISTINCT FROM item_supply_internal.revision_substantive_hash(parent_artifact.source_json)
    OR context_payload->>'parent_artifact_id' IS DISTINCT FROM parent_artifact.id::text
    OR context_payload->>'parent_source_hash' IS DISTINCT FROM parent_artifact.source_hash
    OR context_payload->>'parent_content_hash' IS DISTINCT FROM parent_artifact.content_hash
    OR context_payload->>'parent_review_hash' IS DISTINCT FROM investigation_row.payload_json->>'review_receipt_hash'
    OR context_payload->>'investigation_receipt_id' IS DISTINCT FROM investigation_row.id::text
    OR context_payload->>'investigation_receipt_hash' IS DISTINCT FROM investigation_row.snapshot_hash
    OR context_payload->>'investigation_report_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(investigation_row.payload_json->'report')
    OR context_payload->>'policy_hash' IS DISTINCT FROM investigation_prep.payload_json->'request_payload'->'review_input'->'binding'->>'policy_hash'
    OR context_payload->>'scope_hash' IS DISTINCT FROM parent_artifact.request_json->>'scope_hash'
    OR context_payload->>'target_definition_hash' IS DISTINCT FROM parent_artifact.target_definition_hash
    OR p->>'context_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(context_payload)
    OR p->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(request_payload)
    OR (NOT family_permission AND request_payload->'blueprint' IS DISTINCT FROM parent_artifact.source_json->'blueprint')
    OR request_payload->'materials' IS DISTINCT FROM parent_artifact.request_json->'materials'
    OR request_payload->>'demand_binding' IS NOT NULL OR request_payload->>'scope_hash' IS DISTINCT FROM context_payload->>'scope_hash'
    OR request_payload->>'candidate_id' IS DISTINCT FROM context_payload->>'child_candidate_id'
    OR request_payload->>'item_key' IS DISTINCT FROM context_payload->>'child_item_key'
    OR request_payload->>'version' IS DISTINCT FROM context_payload->>'child_version'
    OR request_payload->>'candidate_id'=parent_artifact.candidate_id::text
    OR request_payload->>'item_key'=parent_artifact.source_json->'public'->>'item_key'
    OR request_payload->>'version'=parent_artifact.source_json->'public'->>'version'
    OR request_payload->'limits'->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
    OR (NOT family_permission AND ((request_payload->'public_template') - ARRAY['item_key','version']) IS DISTINCT FROM
      ((parent_artifact.request_json->'public_template') - ARRAY['item_key','version']))
    OR p->'resources' IS DISTINCT FROM jsonb_build_object('requests',1,
      'input_tokens',request_payload->'limits'->'max_input_bytes','output_tokens',61440,
      'execution_seconds',0,'fetches',0,'candidates',1,'revision_rounds',1,'investigation_rounds',0)
    OR request_payload->'limits'->'max_input_bytes' IS DISTINCT FROM parent_artifact.request_json->'limits'->'max_input_bytes'
    OR request_payload->'limits'->'max_output_bytes' IS DISTINCT FROM parent_artifact.request_json->'limits'->'max_output_bytes'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
    OR context_payload->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR context_payload->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
    OR jsonb_array_length(context_payload->'problems') IS DISTINCT FROM jsonb_array_length(investigation_row.payload_json->'report'->'output'->'analyses') THEN
    RAISE check_violation USING MESSAGE='revision exact supplemental source/context required';
  END IF;
  FOR issue IN SELECT value FROM jsonb_array_elements(investigation_row.payload_json->'report'->'output'->'analyses') LOOP
    IF (SELECT count(*) FROM jsonb_array_elements(context_payload->'problems') pp WHERE pp->>'dispute_key'=issue->>'dispute_key'
      AND pp->'analysis' IS NOT DISTINCT FROM issue->'analysis' AND pp->'verification_question' IS NOT DISTINCT FROM issue->'verification_question'
      AND pp->'proposed_revision' IS NOT DISTINCT FROM issue->'proposed_revision' AND pp->'references' IS NOT DISTINCT FROM issue->'references')<>1 THEN
      RAISE check_violation USING MESSAGE='revision all original concrete questions required';
    END IF;
  END LOOP;
  FOR source_bound IN SELECT value FROM jsonb_array_elements(p->'source_deadlines') LOOP
    IF (p->>'deadline_at')::timestamptz>(source_bound->>'retained_until')::timestamptz THEN
      RAISE check_violation USING MESSAGE='revision source deadline cannot extend';
    END IF;
  END LOOP;
  IF TG_TABLE_NAME='tutor_item_supply_shared_revision_preparations' THEN
    IF (NEW.parent_job_id,NEW.candidate_id,NEW.investigation_receipt_id) IS DISTINCT FROM
      (parent_control.job_id,(request_payload->>'candidate_id')::uuid,investigation_row.id)
      OR NEW.valid_until IS DISTINCT FROM (p->>'deadline_at')::timestamptz
      OR p->>'preparation_id' IS DISTINCT FROM NEW.id::text
      OR p->'resources'->>'requests' IS DISTINCT FROM '1' OR p->'resources'->>'candidates' IS DISTINCT FROM '1'
      OR p->'resources'->>'revision_rounds' IS DISTINCT FROM '1'
      OR p->'resources'->>'output_tokens' IS DISTINCT FROM '61440'
      OR p->'resources'->'input_tokens' IS DISTINCT FROM request_payload->'limits'->'max_input_bytes'
      OR p->>'reservation_key' IS DISTINCT FROM 'gen.'||replace(NEW.candidate_id::text,'-','')
      OR child_control.lease_owner IS DISTINCT FROM p->'child_lease'->>'lease_owner'
      OR child_control.lease_generation::text IS DISTINCT FROM p->'child_lease'->>'generation'
      OR child_control.state_version::text IS DISTINCT FROM p->'child_lease'->>'state_version'
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rs WHERE rs.job_id=NEW.child_job_id)
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts ca WHERE ca.job_id=NEW.child_job_id) THEN
      RAISE check_violation USING MESSAGE='revision context must be frozen before independent author reservation';
    END IF;
  ELSE
    SELECT * INTO child_artifact FROM tutor_item_supply_shared_generation_artifacts ca WHERE ca.id=NEW.child_artifact_id FOR SHARE;
    SELECT * INTO author_reservation FROM tutor_item_supply_shared_reservations ar WHERE ar.id=NEW.reservation_id FOR SHARE;
    SELECT * INTO author_usage FROM tutor_item_supply_shared_runtime_settlements au WHERE au.id=NEW.settlement_id FOR SHARE;
    actual_input:=NEW.payload_json->'author_input';
    IF child_artifact.id IS NULL OR author_reservation.id IS NULL OR author_usage.id IS NULL
      OR child_artifact.job_id IS DISTINCT FROM NEW.child_job_id OR child_artifact.root_id IS DISTINCT FROM NEW.root_id
      OR child_artifact.candidate_id IS DISTINCT FROM preparation_row.candidate_id OR child_artifact.reservation_id IS DISTINCT FROM NEW.reservation_id
      OR child_artifact.lease_generation IS DISTINCT FROM child_control.lease_generation
      OR child_artifact.lease_owner IS DISTINCT FROM child_control.lease_owner
      OR child_artifact.request_json IS DISTINCT FROM request_payload
      OR child_artifact.source_hash=parent_artifact.source_hash OR child_artifact.content_hash=parent_artifact.content_hash
      OR child_artifact.item_id=parent_artifact.item_id OR child_artifact.version_id=parent_artifact.version_id
      OR item_supply_internal.revision_substantive_hash(child_artifact.source_json)=item_supply_internal.revision_substantive_hash(parent_artifact.source_json)
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts ca WHERE ca.id=NEW.child_artifact_id AND ca.xmin::text::bigint=(txid_current()%4294967296))
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements au WHERE au.id=NEW.settlement_id AND au.xmin::text::bigint=(txid_current()%4294967296))
      OR author_reservation.root_id IS DISTINCT FROM NEW.root_id OR author_reservation.job_id IS DISTINCT FROM NEW.child_job_id
      OR author_reservation.lease_generation IS DISTINCT FROM child_control.lease_generation
      OR author_reservation.reservation_key IS DISTINCT FROM p->>'reservation_key'
      OR author_reservation.requests<>1 OR author_reservation.tokens<>(request_payload->'limits'->>'max_input_bytes')::bigint+61440
      OR author_usage.reservation_id IS DISTINCT FROM NEW.reservation_id
      OR author_usage.settlement_key IS DISTINCT FROM 'generation.'||replace(preparation_row.candidate_id::text,'-','')
      OR author_usage.usage_state NOT IN ('known','unknown')
      OR (author_usage.usage_state='unknown' AND (author_usage.cost_amount IS NOT NULL OR author_usage.receipt_hash IS NOT NULL
        OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts sa WHERE sa.settlement_id=NEW.settlement_id)))
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.child_job_id
        AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=child_artifact.artifact_hash)
      OR jsonb_typeof(actual_input) IS DISTINCT FROM 'object'
      OR (actual_input - ARRAY['schema_version','request_hash','context_hash','envelope_hash','messages_hash','output_schema_hash','input_bytes']) <> '{}'::jsonb
      OR jsonb_typeof(actual_input->'input_bytes') IS DISTINCT FROM 'number'
      OR actual_input->>'schema_version' IS DISTINCT FROM 'native_revision_author_input_binding_v1'
      OR NEW.payload_json->>'root_id' IS DISTINCT FROM NEW.root_id::text
      OR NEW.payload_json->>'parent_artifact_id' IS DISTINCT FROM NEW.parent_artifact_id::text
      OR NEW.payload_json->>'child_artifact_id' IS DISTINCT FROM NEW.child_artifact_id::text
      OR NEW.payload_json->'lease'->>'job_id' IS DISTINCT FROM NEW.child_job_id::text
      OR NEW.payload_json->'lease'->'profile' IS DISTINCT FROM snapshot
      OR NEW.payload_json->'lease'->>'visibility' IS DISTINCT FROM 'public'
      OR NEW.payload_json->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb
      OR NEW.payload_json->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
      OR actual_input->>'context_hash' IS DISTINCT FROM p->>'context_hash'
      OR actual_input->>'request_hash' IS DISTINCT FROM p->>'request_hash'
      OR COALESCE(actual_input->>'envelope_hash','') !~ '^[0-9a-f]{64}$'
      OR COALESCE(actual_input->>'messages_hash','') !~ '^[0-9a-f]{64}$'
      OR COALESCE(actual_input->>'output_schema_hash','') !~ '^[0-9a-f]{64}$'
      OR COALESCE((actual_input->>'input_bytes')::bigint,0) NOT BETWEEN 1 AND (request_payload->'limits'->>'max_input_bytes')::bigint
      OR NEW.payload_json->>'preparation_hash' IS DISTINCT FROM preparation_row.snapshot_hash
      OR NEW.payload_json->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text
      OR NEW.payload_json->>'reservation_id' IS DISTINCT FROM NEW.reservation_id::text
      OR NEW.payload_json->>'settlement_id' IS DISTINCT FROM NEW.settlement_id::text
      OR NEW.payload_json->>'usage_state' IS DISTINCT FROM author_usage.usage_state
      OR NEW.payload_json->>'context_hash' IS DISTINCT FROM p->>'context_hash'
      OR NEW.payload_json->>'child_artifact_hash' IS DISTINCT FROM child_artifact.artifact_hash
      OR NEW.payload_json->>'provider_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(child_artifact.receipt_json->'provider')
      OR NEW.payload_json->>'child_substantive_hash' IS DISTINCT FROM item_supply_internal.revision_substantive_hash(child_artifact.source_json)
      OR NEW.payload_json->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
      OR NEW.payload_json->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb OR NEW.payload_json->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
      OR child_control.lease_owner IS DISTINCT FROM NEW.payload_json->'lease'->>'lease_owner'
      OR child_control.lease_generation::text IS DISTINCT FROM NEW.payload_json->'lease'->>'generation'
      OR child_control.state_version::text IS DISTINCT FROM NEW.payload_json->'lease'->>'state_version' THEN
      RAISE check_violation USING MESSAGE='revision original settled author/artifact/envelope lineage mismatch';
    END IF;
    FOR kind,amount IN SELECT key,value FROM jsonb_each(p->'resources') LOOP
      IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra WHERE ra.reservation_namespace='shared'
          AND ra.reservation_id=NEW.reservation_id AND ra.resource_kind=kind AND ra.reserved_amount=(amount::text)::bigint)
        OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra WHERE ra.reservation_namespace='shared'
          AND ra.reservation_id=NEW.reservation_id AND ra.resource_kind=kind AND ra.reserved_amount<>(amount::text)::bigint) THEN
        RAISE check_violation USING MESSAGE='revision exact original cumulative resource allocation required';
      END IF;
    END LOOP;
    IF author_usage.usage_state='known' AND (author_usage.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(child_artifact.receipt_json->'provider')
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts sa
        WHERE sa.settlement_id=NEW.settlement_id AND sa.resource_kind='revision_rounds' AND sa.actual_amount=1)
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts sa
        WHERE sa.settlement_id=NEW.settlement_id AND sa.resource_kind='candidates' AND sa.actual_amount=1)) THEN
      RAISE check_violation USING MESSAGE='revision actual round cannot settle as zero';
    END IF;
  END IF;
  IF clock_timestamp()>=(p->>'deadline_at')::timestamptz THEN RAISE check_violation USING MESSAGE='revision final deadline expired'; END IF;
  IF persistent_permission THEN
    PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);
    stamp:=clock_timestamp();
    IF (p->>'deadline_at')::timestamptz<=stamp OR investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp
      OR parent_control.lease_expires_at<=stamp OR parent_control.parent_deadline<=stamp
      OR child_control.lease_expires_at<=stamp OR child_control.parent_deadline<=stamp
    THEN RAISE check_violation USING MESSAGE='525 final acceptance deadline expired'; END IF;
  END IF;
  RETURN NEW;
END $body525_revision$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()');
 IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql' OR actual.pronargs<>0
  OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset OR actual.proisstrict
  OR NOT actual.prosecdef OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
 THEN RAISE check_violation USING MESSAGE='525 original revision receiver attributes changed'; END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR encode(sha256(convert_to(reviewed_body,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='525 unknown original revision receiver source'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1
 THEN RAISE check_violation USING MESSAGE='525 original revision receiver framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,reviewed_body);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='525 original revision attributes/owner/ACL not preserved'; END IF;
END $upgrade525_revision$;

DO $upgrade525_journal$
DECLARE actual record; verified record; definition text; source text;
 old_sha constant text:='30456f50482feed7c23d119752287d3559fced4a33d9bc98d01c5d0ac80cd0dd'; new_sha constant text:='59cbbd4d9fcd1eca6f3db40e0733cc9ffdcdd2e77dc14b87bdf6c6d396617de8';
 reviewed_body constant text:=$body525_journal$
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
     OR (parent.payload_json->'specification'->'allocation' IS DISTINCT FROM p->'specification'->'allocation'
       AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp
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
END $body525_journal$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.enforce_persistent_pack_journal_insert()');
 IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql' OR actual.pronargs<>0
  OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset OR actual.proisstrict
  OR NOT actual.prosecdef OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
 THEN RAISE check_violation USING MESSAGE='525 original journal receiver attributes changed'; END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR encode(sha256(convert_to(reviewed_body,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='525 unknown original journal receiver source'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1
 THEN RAISE check_violation USING MESSAGE='525 original journal receiver framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,reviewed_body);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='525 original journal attributes/owner/ACL not preserved'; END IF;
END $upgrade525_journal$;

