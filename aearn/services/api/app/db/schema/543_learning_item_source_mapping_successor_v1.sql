-- Explicit source/confirmed-course continuity for the one unconsumed542 successor.
-- This does not extend historical policies, captures, signed proofs, mappings or leases.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='543 original sandbox only'; END IF; END $$;

DO $helpers543$
DECLARE expected record; actual record;
BEGIN
 FOR expected IN SELECT * FROM (VALUES
  ('item_supply_internal.confirmed_source_successor_allowed(jsonb)','efd457d39e508464dc97a2b21f2c11487926011685dee1058f6bda03b5d4df86','bool'),
  ('item_supply_internal.assert_source_mapping_successor(jsonb)','4c67d2c7189bb7400af21402aba32be049b312bdb31332bffb77d7f8f832e206','void'),
  ('item_supply_internal.enforce_source_mapping_successor_insert()','0f4fd99b506f3b2e117c45d66727675faac547ebb0335d7c1c214faa80ef2bf2','trigger'),
  ('item_supply_internal.revision_source_successor_matches(jsonb)','450299724984a2c123774b0da6f768ecd541d125f8c207a84e9eb350b14ae504','bool')
 ) AS wanted(signature,sha,result_type) LOOP
  SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(expected.signature);
  IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') IS DISTINCT FROM expected.sha
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.'||expected.result_type)
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[])
  THEN RAISE check_violation USING MESSAGE='543 unexpected existing source successor receiver'; END IF;
 END LOOP;
END $helpers543$;
CREATE OR REPLACE FUNCTION item_supply_internal.confirmed_source_successor_allowed(q jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $source543$
DECLARE old_e rag_assessment_source_evidence%ROWTYPE; old_q jsonb;
 m tutor_item_supply_finite_course_mappings%ROWTYPE; course_binding rag_plan_material_bindings%ROWTYPE;
 cap rag_registered_source_captures%ROWTYPE; policy rag_registered_source_policies%ROWTYPE;
 root rag_budget_authority_roots%ROWTYPE; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
  OR q->>'profile_id' IS DISTINCT FROM 'python-binding-actual-d-source-v1'
  OR q->'actual_d'->>'oracle_run_id' IS DISTINCT FROM '366ab674-3091-5a37-bdcb-8984c75e9717'
 THEN RETURN false; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('confirmed-source-successor'),hashtext('d8e34e01-3514-41a3-9bbd-55ee3e627134'));
 SELECT * INTO m FROM tutor_item_supply_finite_course_mappings WHERE id='d8e34e01-3514-41a3-9bbd-55ee3e627134' FOR SHARE;
 IF NOT FOUND OR m.receipt_hash IS DISTINCT FROM 'f99b38e5f8bd749e5b0a7b56c19adddcc37696d27482a69d15da2b2f73ac1a98' THEN RETURN false; END IF;
 PERFORM item_supply_internal.public_normal_mapping_current(m.id,m.user_id,m.epoch::bigint);
 SELECT * INTO course_binding FROM rag_plan_material_bindings WHERE id=m.assessment_binding_id FOR SHARE;
 SELECT * INTO old_e FROM rag_assessment_source_evidence WHERE claim_handle='source-claim.b56c9153e8e84d70ac6262dbcc0c9828' FOR SHARE;
 old_q:=old_e.signed_proof->'payload'->'prepared';
 IF old_e.id IS NULL OR old_e.revoked_at IS NOT NULL OR course_binding.id IS NULL
  OR old_e.private_user_id IS DISTINCT FROM m.user_id OR old_e.private_epoch IS DISTINCT FROM m.epoch
  OR jsonb_array_length(course_binding.binding_json->'evidence') IS DISTINCT FROM 1
  OR course_binding.binding_json->'evidence'->0->'binding'->>'claim_receipt_id' IS DISTINCT FROM old_e.claim_handle
  OR ((q->'actual_d')-'oracle_run_id') IS DISTINCT FROM ((old_q->'actual_d')-'oracle_run_id')
  OR q->'demand' IS DISTINCT FROM old_q->'demand'
  OR q->'profile_id' IS DISTINCT FROM old_q->'profile_id'
  OR q->'source_handle' IS DISTINCT FROM old_q->'source_handle'
  OR q->'license_id' IS DISTINCT FROM old_q->'license_id'
  OR q->'origin' IS DISTINCT FROM old_q->'origin' OR q->'reading_level' IS DISTINCT FROM old_q->'reading_level'
  OR q->'capture_id' IS NOT DISTINCT FROM old_q->'capture_id'
  OR (SELECT jsonb_agg(jsonb_build_array(s->>'unit',s->>'sha256',(s->>'end_byte')::bigint-(s->>'start_byte')::bigint) ORDER BY s->>'unit') FROM jsonb_array_elements(q->'spans') s)
   IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array(s->>'unit',s->>'sha256',(s->>'end_byte')::bigint-(s->>'start_byte')::bigint) ORDER BY s->>'unit') FROM jsonb_array_elements(old_q->'spans') s)
 THEN RETURN false; END IF;
 SELECT * INTO cap FROM rag_registered_source_captures WHERE id=(q->>'capture_id')::uuid FOR SHARE;
 SELECT * INTO policy FROM rag_registered_source_policies WHERE policy_id=cap.policy_id FOR SHARE;
 SELECT * INTO root FROM rag_budget_authority_roots WHERE root_id=policy.root_id FOR SHARE;
 stamp:=clock_timestamp();
 IF cap.id IS NULL OR policy.policy_id IS NULL OR root.root_id IS NULL
  OR cap.cleared_at IS NOT NULL OR cap.captured_body IS NULL
  OR cap.fetched_sha256 IS DISTINCT FROM q->>'document_hash'
  OR policy.policy_id IS DISTINCT FROM q->>'policy_id' OR policy.generation::text IS DISTINCT FROM q->>'policy_generation'
  OR policy.generation<>3 OR cap.generation<>policy.generation OR policy.source_handle IS DISTINCT FROM q->>'source_handle'
  OR policy.canonical_url IS DISTINCT FROM 'https://docs.python.org/3/reference/simple_stmts.html'
  OR policy.enabled IS DISTINCT FROM true OR policy.revoked_at IS NOT NULL OR root.enabled IS DISTINCT FROM true
  OR root.policy_id IS DISTINCT FROM policy.policy_id OR root.policy_generation IS DISTINCT FROM policy.generation
  OR root.root_id IS DISTINCT FROM q->'budget'->>'root_id' OR root.period_start>stamp
  OR LEAST(cap.retention_until,policy.retention_until,policy.expires_at,root.period_end,root.delegation_expires_at)<=stamp
  OR (q->>'authority_expires_at')::timestamptz>LEAST(cap.retention_until,policy.retention_until,policy.expires_at,root.period_end,root.delegation_expires_at)
  OR (q->>'authority_expires_at')::timestamptz<=stamp
 THEN RETURN false; END IF;
 RETURN true;
END $source543$;
REVOKE ALL ON FUNCTION item_supply_internal.confirmed_source_successor_allowed(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_source_mapping_successor(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $bridge543$
DECLARE h tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 m tutor_item_supply_finite_course_mappings%ROWTYPE; cb rag_plan_material_bindings%ROWTYPE;
 prior_public rag_assessment_source_evidence%ROWTYPE; pub rag_assessment_source_evidence%ROWTYPE;
 priv rag_assessment_source_evidence%ROWTYPE; provenance rag_actual_d_private_provenance%ROWTYPE;
 pair record; nq jsonb; oq jsonb; part jsonb; coord jsonb; claim jsonb; expected_claim jsonb;
 public_id uuid; public_material jsonb; ceiling timestamptz:='infinity'; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','task_ref','parent_artifact_id','parent_artifact_hash','root_id',
   'historical_phase_id','investigation_receipt_id','historical_request_hash','public_materials','course_materials',
   'source_deadlines','issued_at','valid_until']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'persistent_source_mapping_successor_v1'
  OR p->>'parent_artifact_id' IS DISTINCT FROM 'a6433494-8167-4f2b-ad39-82a20ce62cde'
  OR p->>'root_id' IS DISTINCT FROM '7d4b85ba-a0ec-4348-ac11-3401c6bded47'
  OR p->>'historical_phase_id' IS DISTINCT FROM 'baa4d9d7-411d-452f-acf3-ed9551c12743'
  OR p->>'investigation_receipt_id' IS DISTINCT FROM '87596016-7639-4ed9-8f05-684b7bf8027c'
 THEN RAISE check_violation USING MESSAGE='543 exact source mapping successor required'; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal
  WHERE id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND record_kind='task' FOR SHARE;
 IF h.id IS NULL OR h.payload_json->'ref' IS DISTINCT FROM p->'task_ref'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=h.id AND user_id=h.user_id AND epoch=h.epoch AND record_kind IN('pause','stop'))
 THEN RAISE check_violation USING MESSAGE='543 current original task required'; END IF;
 PERFORM item_supply_internal.public_normal_mapping_current((p->'task_ref'->>'mapping_receipt_id')::uuid,h.user_id,h.epoch::bigint);
 SELECT * INTO m FROM tutor_item_supply_finite_course_mappings WHERE id=(p->'task_ref'->>'mapping_receipt_id')::uuid FOR SHARE;
 SELECT * INTO cb FROM rag_plan_material_bindings WHERE id=m.assessment_binding_id FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'parent_artifact_id')::uuid FOR SHARE;
 SELECT * INTO prior_public FROM rag_assessment_source_evidence WHERE claim_handle='source-claim.1528a8007c694a1cb4956aba272bd2e1' FOR SHARE;
 IF m.id IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'::uuid OR cb.id IS NULL OR a.id IS NULL OR prior_public.id IS NULL
  OR cb.binding_digest IS DISTINCT FROM m.binding_digest OR cb.selection_digest IS DISTINCT FROM m.selection_digest
  OR a.root_id::text IS DISTINCT FROM p->>'root_id' OR a.artifact_hash IS DISTINCT FROM p->>'parent_artifact_hash'
  OR item_supply_internal.snapshot_hash(a.request_json) IS DISTINCT FROM p->>'historical_request_hash'
  OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
  OR prior_public.revoked_at IS NOT NULL
  OR jsonb_typeof(p->'public_materials') IS DISTINCT FROM 'array' OR jsonb_typeof(p->'course_materials') IS DISTINCT FROM 'array'
  OR jsonb_array_length(p->'public_materials') IS DISTINCT FROM jsonb_array_length(a.request_json->'materials')
  OR jsonb_array_length(p->'course_materials') IS DISTINCT FROM jsonb_array_length(cb.binding_json->'evidence')
  OR jsonb_array_length(p->'course_materials')<>1
  OR jsonb_array_length(p->'source_deadlines') IS DISTINCT FROM jsonb_array_length(p->'public_materials')
 THEN RAISE check_violation USING MESSAGE='543 original history and exact material correspondence required'; END IF;
 IF item_supply_internal.public_native_source_current(jsonb_build_object('request',jsonb_set(a.request_json,'{materials}',p->'public_materials'),'ref',p->'task_ref')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='543 new PUBLIC source current required'; END IF;
 oq:=prior_public.signed_proof->'payload'->'prepared';
 FOR pair IN SELECT n.value AS new_material,o.value AS old_material,n.ordinality AS ordinal
  FROM jsonb_array_elements(p->'public_materials') WITH ORDINALITY n
  JOIN jsonb_array_elements(a.request_json->'materials') WITH ORDINALITY o USING(ordinality) LOOP
  part:=pair.new_material;
  SELECT * INTO pub FROM rag_assessment_source_evidence WHERE claim_handle=part->'exact_claims'->0->>'claim_receipt_id' FOR SHARE;
  nq:=pub.signed_proof->'payload'->'prepared';
  IF pub.id IS NULL OR pub.id=prior_public.id OR pub.private_user_id IS NOT NULL OR pub.policy_generation<>3
   OR (public_id IS NOT NULL AND public_id<>pub.id)
   OR pair.old_material->>'excerpt' IS DISTINCT FROM part->>'excerpt'
   OR pair.old_material->'binding'->'target_id' IS DISTINCT FROM part->'binding'->'target_id'
   OR pair.old_material->'binding'->'target_definition_hash' IS DISTINCT FROM part->'binding'->'target_definition_hash'
   OR pair.old_material->'binding'->'course_goal_hash' IS DISTINCT FROM part->'binding'->'course_goal_hash'
   OR nq->'profile_id' IS DISTINCT FROM oq->'profile_id' OR nq->'demand' IS DISTINCT FROM oq->'demand'
   OR nq->'source_handle' IS DISTINCT FROM oq->'source_handle' OR nq->'license_id' IS DISTINCT FROM oq->'license_id'
   OR nq->'origin' IS DISTINCT FROM oq->'origin' OR nq->'reading_level' IS DISTINCT FROM oq->'reading_level'
   OR (SELECT jsonb_agg(jsonb_build_array(s->>'unit',s->>'sha256',(s->>'end_byte')::bigint-(s->>'start_byte')::bigint) ORDER BY s->>'unit') FROM jsonb_array_elements(nq->'spans') s)
    IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array(s->>'unit',s->>'sha256',(s->>'end_byte')::bigint-(s->>'start_byte')::bigint) ORDER BY s->>'unit') FROM jsonb_array_elements(oq->'spans') s)
   OR p->'source_deadlines'->((pair.ordinal-1)::integer)->>'binding_digest' IS DISTINCT FROM part->'binding'->>'binding_digest'
   OR p->'source_deadlines'->((pair.ordinal-1)::integer)->>'claim_receipt_id' IS DISTINCT FROM pub.claim_handle
   OR (p->'source_deadlines'->((pair.ordinal-1)::integer)->>'retained_until')::timestamptz>pub.expires_at
  THEN RAISE check_violation USING MESSAGE='543 supported PUBLIC source semantics changed'; END IF;
  public_id:=pub.id; public_material:=part; ceiling:=LEAST(ceiling,pub.expires_at);
 END LOOP;
 part:=p->'course_materials'->0; coord:=part->'binding'->'evidence'->0; claim:=part->'exact_claims'->0;
 SELECT * INTO priv FROM rag_assessment_source_evidence WHERE claim_handle=claim->>'claim_receipt_id' FOR SHARE;
 SELECT * INTO provenance FROM rag_actual_d_private_provenance WHERE private_evidence_id=priv.id FOR SHARE;
 nq:=priv.signed_proof->'payload'->'prepared';
 IF priv.id IS NULL OR provenance.private_evidence_id IS NULL OR provenance.public_evidence_id IS DISTINCT FROM public_id
  OR (priv.private_user_id,priv.private_epoch) IS DISTINCT FROM (h.user_id,h.epoch)
  OR (provenance.user_id,provenance.epoch) IS DISTINCT FROM (h.user_id,h.epoch)
  OR provenance.private_proof_hash IS DISTINCT FROM priv.proof_hash OR provenance.public_proof_hash IS DISTINCT FROM pub.proof_hash
  OR provenance.corpus_id::text IS DISTINCT FROM coord->>'corpus_version_id' OR provenance.generation::text IS DISTINCT FROM coord->>'active_generation'
  OR priv.proof_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(priv.signed_proof)
  OR priv.revoked_at IS NOT NULL OR priv.issued_at>clock_timestamp() OR priv.expires_at<=clock_timestamp()
  OR priv.signed_proof->'payload'->>'format' IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3'
  OR item_supply_internal.confirmed_source_successor_allowed(nq) IS DISTINCT FROM true
  OR part->'binding'->'draft' IS DISTINCT FROM cb.binding_json->'draft'
  OR part->'binding'->'node_id' IS DISTINCT FROM cb.binding_json->'node_id'
  OR part->'binding'->'goal_hash' IS DISTINCT FROM cb.binding_json->'goal_hash'
  OR part->'binding'->>'purpose' IS DISTINCT FROM 'assessment_evidence'
  OR jsonb_array_length(part->'binding'->'evidence') IS DISTINCT FROM 1 OR jsonb_array_length(part->'exact_claims') IS DISTINCT FROM 1
  OR item_supply_internal.snapshot_hash((part->'binding')-'binding_digest') IS DISTINCT FROM part->'binding'->>'binding_digest'
  OR encode(sha256(convert_to(part->>'excerpt','UTF8')),'hex') IS DISTINCT FROM cb.binding_json->'evidence'->0->>'approved_excerpt_hash'
  OR coord->>'approved_excerpt_hash' IS DISTINCT FROM cb.binding_json->'evidence'->0->>'approved_excerpt_hash'
  OR coord->'binding' IS DISTINCT FROM claim->'binding' OR claim->>'claim_receipt_id' IS DISTINCT FROM priv.claim_handle
  OR claim->>'claim_hash' IS DISTINCT FROM priv.claim_hash OR claim->'scope' IS DISTINCT FROM nq->'demand'->'scope'
  OR claim->'execution_scope' IS DISTINCT FROM public_material->'exact_claims'->0->'execution_scope'
  OR claim->'applicability' IS DISTINCT FROM public_material->'exact_claims'->0->'applicability'
 THEN RAISE check_violation USING MESSAGE='543 NEW original PRIVATE actual-D source required'; END IF;
 expected_claim:=jsonb_build_object('receipt_id',priv.claim_handle,'demand_hash',nq->'demand'->>'demand_hash',
  'purpose','assessment_evidence','admission_receipt_id',public_material->'exact_claims'->0->'binding'->>'admission_receipt_id',
  'claim_hash',priv.claim_hash,'scope',nq->'demand'->'scope','source_handle',priv.source_handle,
  'document_handle',pub.document_handle,'document_revision',priv.document_hash,'document_hash',priv.document_hash,
  'applicability',public_material->'exact_claims'->0->>'applicability','method','isolated_execution',
  'primary_lineage_family',NULL,'independent_lineage_family',NULL,'independent_source_handle',NULL,
  'independent_document_handle',NULL,'independent_document_revision',NULL,'independent_document_hash',NULL,
  'independent_lineage_verified',false,'execution_receipt_id',priv.execution_handle,
  'execution_scope',public_material->'exact_claims'->0->'execution_scope','verified',true,'revoked',false);
 IF coord->>'claim_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(expected_claim)
  OR coord->>'claim_id' IS DISTINCT FROM priv.claim_handle OR coord->>'execution_receipt_id' IS DISTINCT FROM priv.execution_handle
 THEN RAISE check_violation USING MESSAGE='543 exact PRIVATE original claim binding required'; END IF;
 stamp:=clock_timestamp(); ceiling:=LEAST(ceiling,priv.expires_at);
 IF COALESCE((p->>'issued_at')::timestamptz<=stamp AND (p->>'valid_until')::timestamptz>stamp
  AND (p->>'valid_until')::timestamptz<=ceiling,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='543 successor source expired or extended'; END IF;
END $bridge543$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_source_mapping_successor(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_source_mapping_successor_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $insert543$
DECLARE h tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 IF NEW.record_kind<>'source_mapping_successor' THEN RETURN NEW; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal WHERE id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND record_kind='task' FOR SHARE;
 IF h.id IS NULL OR (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.intent_hash) IS DISTINCT FROM (h.id,h.user_id,h.epoch,h.scope_id,h.intent_hash)
  OR NEW.operation_key IS DISTINCT FROM 'p7.source-mapping-successor.6739d3c5661944ce970f0ab1e49f3acc.1'
 THEN RAISE check_violation USING MESSAGE='543 canonical PRIVATE successor journal required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('fresh-committed-revision'),hashtext('87596016-7639-4ed9-8f05-684b7bf8027c'));
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=h.id AND record_kind='committed_revision_execution'
  AND operation_key='p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution.successor.1')
 THEN RAISE check_violation USING MESSAGE='543 successor execution already consumed'; END IF;
 PERFORM item_supply_internal.assert_source_mapping_successor(NEW.payload_json);
 RETURN NEW;
END $insert543$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_source_mapping_successor_insert() FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.revision_source_successor_matches(p jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $matches543$
DECLARE e tutor_item_supply_private_persistent_pack_journal%ROWTYPE; b tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT * INTO e FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND record_kind='committed_revision_execution' AND operation_key='p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution.successor.1'
  AND payload_json->>'execution_job_id'=p->>'parent_job_id' FOR SHARE;
 IF NOT FOUND OR NOT (e.payload_json ? 'source_successor_id') THEN RETURN false; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(e.payload_json->>'source_successor_id')::uuid
  AND pack_task_id=e.pack_task_id AND user_id=e.user_id AND epoch=e.epoch AND scope_id=e.scope_id AND intent_hash=e.intent_hash
  AND record_kind='source_mapping_successor' AND operation_key='p7.source-mapping-successor.6739d3c5661944ce970f0ab1e49f3acc.1' FOR SHARE;
 IF b.id IS NULL OR b.payload_hash IS DISTINCT FROM e.payload_json->>'source_successor_hash'
  OR p->'request'->'materials' IS DISTINCT FROM b.payload_json->'public_materials'
  OR p->'source_deadlines' IS DISTINCT FROM b.payload_json->'source_deadlines'
  OR p->>'parent_artifact_id' IS DISTINCT FROM b.payload_json->>'parent_artifact_id'
  OR p->>'investigation_receipt_id' IS DISTINCT FROM b.payload_json->>'investigation_receipt_id'
  OR p->>'root_id' IS DISTINCT FROM b.payload_json->>'root_id'
 THEN RAISE check_violation USING MESSAGE='543 actual source-bound revision required'; END IF;
 PERFORM item_supply_internal.assert_source_mapping_successor(b.payload_json);
 RETURN true;
END $matches543$;
REVOKE ALL ON FUNCTION item_supply_internal.revision_source_successor_matches(jsonb) FROM PUBLIC;

-- Prior definition independently reconstructed and matched to actual installed542 definition SHA.
DO $receiver543_0$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='1ed3e8441df4f0204ea96fa7a22b63b84280701aec74a204ee35917cf570b003'; new_sha constant text:='7e6d8b7596d231dbac9fb83da54a3e47a8e58c85a85937b1a5d02c9a366736f1';
 expected_attrs constant jsonb:=$attrs543${"oid":"5390383","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"assert_committed_revision_execution","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2278","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["p"],"proargtypes":["3802"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs543$::jsonb;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.assert_committed_revision_execution(jsonb)');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='543 exact installed542 receiver metadata required'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='543 exact installed542 receiver body required'; END IF;
 repaired:=source;
 repaired:=replace(repaired,$old543_0$ expected record; digest text; lease_data jsonb; snapshot jsonb; bound jsonb; stamp timestamptz;$old543_0$,$new543_0$ expected record; digest text; lease_data jsonb; snapshot jsonb; bound jsonb; stamp timestamptz;
 bridge_row tutor_item_supply_private_persistent_pack_journal%ROWTYPE; source_bridge jsonb;$new543_0$);
 repaired:=replace(repaired,$old543_1$'execution_lease','batch_id','profile_hash','source_deadlines','issued_at','valid_until'])$old543_1$,$new543_1$'execution_lease','batch_id','profile_hash','source_deadlines','issued_at','valid_until']||CASE WHEN p ? 'source_successor_id' THEN ARRAY['source_successor_id','source_successor_hash'] ELSE ARRAY[]::text[] END)$new543_1$);
 repaired:=replace(repaired,$old543_2$ PERFORM item_supply_internal.private_native_mapping_current((p->'task_ref'->>'mapping_receipt_id')::uuid,h.user_id,h.epoch);$old543_2$,$new543_2$ IF p ? 'source_successor_id' THEN
  SELECT * INTO bridge_row FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'source_successor_id')::uuid
   AND pack_task_id=h.id AND user_id=h.user_id AND epoch=h.epoch AND scope_id=h.scope_id AND intent_hash=h.intent_hash
   AND record_kind='source_mapping_successor' AND operation_key='p7.source-mapping-successor.6739d3c5661944ce970f0ab1e49f3acc.1' FOR SHARE;
  IF bridge_row.id IS NULL OR bridge_row.payload_hash IS DISTINCT FROM p->>'source_successor_hash'
   OR p->>'authorization_sha256' IS DISTINCT FROM '68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243'
   OR p->'source_deadlines' IS DISTINCT FROM bridge_row.payload_json->'source_deadlines'
   OR (p->>'valid_until')::timestamptz>(bridge_row.payload_json->>'valid_until')::timestamptz
  THEN RAISE check_violation USING MESSAGE='543 exact source bridge execution required'; END IF;
  source_bridge:=bridge_row.payload_json;
  PERFORM item_supply_internal.assert_source_mapping_successor(source_bridge);
 ELSE
  PERFORM item_supply_internal.private_native_mapping_current((p->'task_ref'->>'mapping_receipt_id')::uuid,h.user_id,h.epoch);
 END IF;$new543_2$);
 repaired:=replace(repaired,$old543_3$OR ip.payload_json->'source_deadlines' IS DISTINCT FROM p->'source_deadlines'$old543_3$,$new543_3$OR (source_bridge IS NULL AND ip.payload_json->'source_deadlines' IS DISTINCT FROM p->'source_deadlines')$new543_3$);
 repaired:=replace(repaired,$old543_4$jsonb_build_object('request',a.request_json,'ref',p->'task_ref')$old543_4$,$new543_4$jsonb_build_object('request',CASE WHEN source_bridge IS NULL THEN a.request_json ELSE jsonb_set(a.request_json,'{materials}',source_bridge->'public_materials') END,'ref',p->'task_ref')$new543_4$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='543 exact source continuity delta required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='543 original definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='543 original metadata/body preservation failed'; END IF;
END $receiver543_0$;


-- Prior definition independently reconstructed and matched to actual installed542 definition SHA.
DO $receiver543_1$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='a23f9ecce6e34c8c2c9d3c7e12c0760ebd7b07ee8f92168879164d55befbe41b'; new_sha constant text:='503f44abd9500e210eeaf6fbd2750cc86d0c7122d3d68fca972d6eb158d9e2d6';
 expected_attrs constant jsonb:=$attrs543${"oid":"5374836","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_native_revision_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs543$::jsonb;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='543 exact installed542 receiver metadata required'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='543 exact installed542 receiver body required'; END IF;
 repaired:=source;
 repaired:=replace(repaired,$old543_0$fresh_permission boolean:=false;$old543_0$,$new543_0$fresh_permission boolean:=false; source_permission boolean:=false;$new543_0$);
 repaired:=replace(repaired,$old543_1$  fresh_permission:=item_supply_internal.fresh_committed_revision_matches(p);$old543_1$,$new543_1$  fresh_permission:=item_supply_internal.fresh_committed_revision_matches(p);
  source_permission:=item_supply_internal.revision_source_successor_matches(p);
  IF source_permission AND NOT fresh_permission THEN RAISE check_violation USING MESSAGE='543 original fresh execution required'; END IF;$new543_1$);
 repaired:=replace(repaired,$old543_2$OR p->'source_deadlines' IS DISTINCT FROM investigation_prep.payload_json->'source_deadlines'$old543_2$,$new543_2$OR (NOT source_permission AND p->'source_deadlines' IS DISTINCT FROM investigation_prep.payload_json->'source_deadlines')$new543_2$);
 repaired:=replace(repaired,$old543_3$OR request_payload->'materials' IS DISTINCT FROM parent_artifact.request_json->'materials'$old543_3$,$new543_3$OR (NOT source_permission AND request_payload->'materials' IS DISTINCT FROM parent_artifact.request_json->'materials')$new543_3$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='543 exact source continuity delta required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='543 original definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='543 original metadata/body preservation failed'; END IF;
END $receiver543_1$;

DO $kind543$
DECLARE definition text;
BEGIN
 SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint WHERE
  conrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass
  AND conname='tutor_item_supply_private_persistent_pack_jou_record_kind_check' AND contype='c' AND convalidated;
 IF definition=$new543$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text, 'committed_revision_execution'::text, 'source_mapping_successor'::text])))$new543$ THEN RETURN; END IF;
 IF definition IS DISTINCT FROM $old543$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text, 'committed_revision_execution'::text])))$old543$
 THEN RAISE check_violation USING MESSAGE='543 exact original PRIVATE journal kinds required'; END IF;
 ALTER TABLE tutor_item_supply_private_persistent_pack_journal DROP CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check;
 ALTER TABLE tutor_item_supply_private_persistent_pack_journal ADD CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check
  CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text, 'committed_revision_execution'::text, 'source_mapping_successor'::text])));
END $kind543$;
DO $trigger543$
DECLARE definition text;
BEGIN
 SELECT pg_get_triggerdef(oid) INTO definition FROM pg_trigger WHERE
  tgrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass
  AND tgname='a004_source_mapping_successor' AND NOT tgisinternal AND tgenabled='O';
 IF FOUND THEN
  IF definition IS DISTINCT FROM 'CREATE TRIGGER a004_source_mapping_successor BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_source_mapping_successor_insert()'
  THEN RAISE check_violation USING MESSAGE='543 exact source bridge trigger required'; END IF;
 ELSE
  CREATE TRIGGER a004_source_mapping_successor BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
   FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_source_mapping_successor_insert();
 END IF;
END $trigger543$;

-- Exact old definition hash matched to the actual post542 installation snapshot.
-- Capture and preserve the COMPLETE pg_proc metadata, including actual OID/owner/ACL.
DO $confirmed543$
DECLARE actual record; verified record; definition text; repaired text;
 expected_attrs constant jsonb:=$attrs543${"oid":"5349873","proacl":null,"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"rag_actual_d_finite_source_scope_check","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":null,"proretset":false,"prosecdef":false,"prorettype":"2278","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["e"],"proargtypes":["5324980"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"2200","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs543$::jsonb;
 old_sha constant text:='e6446eab249973694bcdad64691ce0906c6be705dc114f6cc7fd14c49d13bfab'; new_sha constant text:='23092c8ce3f37f3fc657a840dfed84740292e098bdbe475bc61e4d600472a770';
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('public.rag_actual_d_finite_source_scope_check(rag_assessment_source_evidence)');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='543 original actual-D receiver required'; END IF;
 IF encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR encode(sha256(convert_to(definition,'UTF8')),'hex') IS DISTINCT FROM 'f9b87196a84166792e2b9a96d6a69b4c235f96954c9f8e3f496559b0e6b4634d'
 THEN RAISE check_violation USING MESSAGE='543 exact installed actual-D definition required'; END IF;
 repaired:=replace(actual.prosrc,$old543$s.status<>'draft_ready' OR s.current_draft_id IS DISTINCT FROM d.id$old543$,$new543$(s.status<>'draft_ready' AND NOT (s.status='confirmed' AND item_supply_internal.confirmed_source_successor_allowed(q))) OR s.current_draft_id IS DISTINCT FROM d.id$new543$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='543 exact confirmed successor source branch required'; END IF;
 IF length(definition)-length(replace(definition,actual.prosrc,''))<>length(actual.prosrc)
 THEN RAISE check_violation USING MESSAGE='543 source receiver definition framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='543 source receiver metadata/body preservation failed'; END IF;
END $confirmed543$;
