-- 592: repair only the original publication guard's anonymous facts local.
-- Baseline: actual primary prosrc from the 2026-10-23 01:51+08 readonly catalog.
-- Raw LF pins: never normalize either the saved body or the current prosrc.
-- Keep its SELECT/row lock, assert call, branch order and all authority fences.
-- Reuse pg_get_functiondef; preserve all other pg_proc fields (OID/owner/ACL too).
-- No data, trigger, permission or transaction-boundary changes.
DO $repair592$
DECLARE
  signature constant text := 'public.enforce_learning_item_native_publication_proof()';
  baseline_md5 constant text := 'f5ca728a61a0f331429f439348b783fb';
  revised_md5 constant text := '67e8da2af4556d06f7026f5a49bd0263';
  old_declaration constant text := ' f record;';
  new_declaration constant text := ' f public.tutor_item_supply_shared_admission_facts%ROWTYPE;';
  baseline_source constant text := $old592$
DECLARE p jsonb:=NEW.proof_json; f record; e record; g public.tutor_item_supply_shared_generation_artifacts%ROWTYPE; v record; c record; snapshot jsonb; t timestamptz;
  clause_data jsonb; validation_app record;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NEW.publication_txid<>txid_current() THEN
    RAISE check_violation USING MESSAGE='native publication isolated caller transaction required';
  END IF;
  SELECT * INTO f FROM tutor_item_supply_shared_admission_facts WHERE id=NEW.facts_receipt_id FOR SHARE;
  IF f.payload_json->>'schema_version'='issued_shared_admission_facts_v2' THEN
   PERFORM item_supply_internal.assert_shared_adjudicated_facts(f::tutor_item_supply_shared_admission_facts);
  ELSIF f.payload_json ? 'validation_applicability_id' OR f.payload_json ? 'validation_applicability_hash' THEN
   SELECT * INTO validation_app FROM tutor_item_supply_shared_validation_applicabilities app WHERE app.job_id=f.job_id
    AND app.generation_artifact_id=f.generation_artifact_id AND app.original_receipt_id=f.validation_receipt_id
    AND app.id::text=f.payload_json->>'validation_applicability_id'
    AND app.applicability_hash=f.payload_json->>'validation_applicability_hash' FOR SHARE;
   IF validation_app.id IS NULL OR validation_app.payload_json->'lease' IS DISTINCT FROM f.payload_json->'lease' THEN
    RAISE EXCEPTION '588 resumed publication requires exact original issued validation applicability'; END IF;
   PERFORM item_supply_internal.assert_shared_validation_applicability(validation_app.payload_json);
  END IF;
  SELECT * INTO e FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.evaluation_receipt_id FOR SHARE;
  SELECT * INTO g FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  SELECT r.*,v1.handle,v1.content_hash AS version_content_hash,v1.risk_tier INTO v
    FROM tutor_learning_item_validation_receipts r JOIN tutor_learning_item_versions v1 ON v1.id=r.version_id
    WHERE r.id=(p->>'bank_validation_id')::uuid AND r.version_id=NEW.version_id;
  IF f.id IS NULL OR e.id IS NULL OR g.id IS NULL OR v.id IS NULL THEN
    RAISE check_violation USING MESSAGE='native publication typed authority missing';
  END IF;
  IF f.version_id<>NEW.version_id OR f.generation_artifact_id<>g.id OR g.version_id<>NEW.version_id
    OR e.generation_artifact_id<>g.id OR e.job_id<>f.job_id OR e.lease_generation<>f.lease_generation
    OR e.artifact_kind<>'admission_evaluation' OR e.schema_version IS DISTINCT FROM (CASE WHEN item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_admission_evaluation_v3' ELSE 'item_supply_admission_evaluation_v2' END)
    OR e.payload_json IS DISTINCT FROM f.payload_json->'evaluation'
    OR e.payload_json->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR e.payload_json->>'policy_version' IS DISTINCT FROM (CASE WHEN item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'autonomous_evidence_policy_v3' ELSE 'autonomous_evidence_policy_v2' END)
    OR e.payload_json->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR f.payload_json->'target_proof' IS NULL OR f.payload_json->'target_proof'='null'::jsonb
    OR v.schema_version<>'candidate_validation_v2' OR v.passed IS NOT NULL
    OR v.native_generation_artifact_id<>g.id OR v.native_validation_receipt_id<>f.validation_receipt_id
    OR v.receipt_hash IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR v.native_specification_hash IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR e.payload_json->'binding'->>'risk_tier' IS DISTINCT FROM v.risk_tier
    OR p->>'proof_id' IS DISTINCT FROM NEW.id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'item_handle' IS DISTINCT FROM v.handle OR p->>'content_hash' IS DISTINCT FROM v.version_content_hash
    OR p->>'source_hash' IS DISTINCT FROM g.source_hash OR p->>'content_hash' IS DISTINCT FROM g.content_hash
    OR p->>'generation_artifact_id' IS DISTINCT FROM g.id::text
    OR p->>'facts_receipt_id' IS DISTINCT FROM f.id::text OR p->>'facts_hash' IS DISTINCT FROM f.payload_hash
    OR p->>'evaluation_receipt_id' IS DISTINCT FROM e.id::text OR p->>'evaluation_hash' IS DISTINCT FROM e.receipt_hash
    OR p->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f.payload_json->'evidence')
    OR p->>'evidence_hash' IS DISTINCT FROM e.payload_json->>'evidence_hash'
    OR p->>'validation_receipt_id' IS DISTINCT FROM f.validation_receipt_id::text
    OR p->>'validation_hash' IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR p->>'review_receipt_id' IS DISTINCT FROM f.review_receipt_id::text
    OR p->>'review_hash' IS DISTINCT FROM f.payload_json->>'review_receipt_hash'
    OR p->'lease' IS DISTINCT FROM f.payload_json->'lease'
    OR p->>'specification_hash' IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR p->>'target_id' IS DISTINCT FROM g.target_id OR p->>'target_definition_hash' IS DISTINCT FROM g.target_definition_hash
    OR p->'materials' IS DISTINCT FROM g.request_json->'materials'
    OR p->'source_receipts' IS DISTINCT FROM g.receipt_json->'sources'
    OR p->'runtime'->>'runtime_profile_hash' IS DISTINCT FROM f.payload_json->>'runtime_profile_hash'
    OR p->'runtime'->>'scorer_version' IS DISTINCT FROM f.payload_json->>'scorer_version'
    OR p->>'policy_hash' IS DISTINCT FROM e.payload_json->'binding'->>'policy_hash'
    OR p->>'materialization_id' IS DISTINCT FROM NEW.materialization_id::text
    OR p->>'publication_event_id' IS DISTINCT FROM NEW.publication_event_id::text
    OR p->>'runner_material_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.runner_material_json)
    OR p->>'origin' IS DISTINCT FROM 'native_internal_b1d'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'inventory_ready' IS DISTINCT FROM 'false'::jsonb OR p->>'family_independence_status' IS DISTINCT FROM 'pending' THEN
    RAISE check_violation USING MESSAGE='native publication exact V2 provenance mismatch';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('clause_id',m->>'clause_id','clause_hash',m->>'clause_hash',
    'interpretation_hash',m->>'interpretation_hash') ORDER BY n) INTO clause_data
    FROM jsonb_array_elements(f.payload_json->'target_proof'->'mappings') WITH ORDINALITY AS clauses(m,n);
  IF p->'clauses' IS DISTINCT FROM clause_data OR jsonb_array_length(clause_data)<>3 THEN
    RAISE check_violation USING MESSAGE='native publication target clauses missing';
  END IF;
  IF v.risk_tier='high' AND (jsonb_array_length(e.payload_json->'bundle_hashes')<2
      OR jsonb_array_length(f.payload_json->'evidence'->'risk_evidence')=0) THEN
    RAISE check_violation USING MESSAGE='native high risk requires actual V2 adapters and independent bundle';
  END IF;
  IF g.target_id='python-kc-binding-v1' THEN
    IF p->'runtime'->'runtime_lock' IS DISTINCT FROM 'null'::jsonb
      OR p->'runtime'->'runner_version' IS DISTINCT FROM 'null'::jsonb
      OR f.payload_json->'validation_terminals' IS DISTINCT FROM '[]'::jsonb THEN
      RAISE check_violation USING MESSAGE='native static publication cannot claim OS authority';
    END IF;
  ELSIF jsonb_typeof(p->'runtime'->'runtime_lock') IS DISTINCT FROM 'object'
      OR jsonb_array_length(f.payload_json->'validation_terminals')=0 THEN
    RAISE check_violation USING MESSAGE='native runtime publication requires actual sealed evidence';
  END IF;
  SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=f.job_id FOR SHARE;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.id IS NULL OR c.state<>'leased' OR c.lease_owner<>f.lease_owner OR c.lease_generation<>f.lease_generation
    OR c.state_version<>f.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM p->'lease'->'profile' OR (p->>'checked_at')::timestamptz>t
    OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(f.payload_json->>'valid_until')::timestamptz) THEN
    RAISE check_violation USING MESSAGE='native publication current facts/lease expired';
  END IF;
  IF p->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts) THEN
    RAISE check_violation USING MESSAGE='native publication frozen generation policy mismatch';
  END IF;
  RETURN NEW;
END $old592$;
  actual pg_catalog.pg_proc%ROWTYPE;
  verified pg_catalog.pg_proc%ROWTYPE;
  source text;
  repaired_source text;
  definition text;
BEGIN
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p
    WHERE p.oid=to_regprocedure(signature);
  IF NOT FOUND OR NOT actual.prosecdef
    OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] THEN
    RAISE check_violation USING MESSAGE='592 original publication guard security/settings differ';
  END IF;
  source:=actual.prosrc;
  IF md5(source)=revised_md5 THEN
    RETURN; -- Same-fragment replay retains the original security/settings check.
  END IF;
  IF source IS DISTINCT FROM baseline_source OR md5(source) IS DISTINCT FROM baseline_md5
    OR (length(source)-length(replace(source,old_declaration,'')))/length(old_declaration)<>1 THEN
    RAISE check_violation USING MESSAGE='592 unknown original publication guard body';
  END IF;
  repaired_source:=replace(source,old_declaration,new_declaration);
  IF md5(repaired_source) IS DISTINCT FROM revised_md5 THEN
    RAISE check_violation USING MESSAGE='592 unexpected publication facts declaration repair';
  END IF;
  definition:=pg_get_functiondef(actual.oid);
  IF (length(definition)-length(replace(definition,source,'')))/length(source)<>1 THEN
    RAISE check_violation USING MESSAGE='592 original publication body framing mismatch';
  END IF;
  EXECUTE replace(definition,source,repaired_source);
  SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
  IF md5(verified.prosrc) IS DISTINCT FROM revised_md5
    OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc') THEN
    RAISE check_violation USING MESSAGE='592 publication body or original metadata verification failed';
  END IF;
END $repair592$;

-- 592 current-facts carry: preserve the original known-only assertion verbatim
-- around the closed lineage block. No producer capability or report is reissued.
DO $assert_carry592$
DECLARE
  signature constant text := 'item_supply_internal.assert_shared_adjudicated_facts(public.tutor_item_supply_shared_admission_facts)';
  baseline_md5 constant text := 'd10d4d9bd53a5c70fcf5b01fc9114f02';
  revised_md5 constant text := '337dc780e5ec7a4ea4ba11971b915034';
  revised_source constant text := $carrybody592$
DECLARE p jsonb:=n.payload_json; old tutor_item_supply_shared_admission_facts%ROWTYPE;
 adjudication record;
 prep tutor_item_supply_shared_review_adjudication_preparations%ROWTYPE;
 review tutor_item_supply_shared_pipeline_receipts%ROWTYPE;validation tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;e jsonb:=p->'evidence';evaluation jsonb:=p->'evaluation';
 report jsonb;disputes jsonb;probes text[];policy text;execution_required boolean;
 allowed text[]:=ARRAY['schema_version','receipt_id','lease','profile_hash','continuation_binding_hash',
  'same_version_predecessor_id','same_version_predecessor_hash','adjudication_receipt_id','adjudication_report_hash',
  'evidence','evaluation','checked_at','valid_until'];
 -- 592 current-carry locals: historical rows are DATA, not live producer leases.
 carry_fields constant text[]:=ARRAY['current_predecessor_facts_id','current_predecessor_facts_hash',
  'adjudication_origin_facts_id','adjudication_origin_facts_hash'];
 carry_mutable constant text[]:=ARRAY['receipt_id','lease','profile_hash','continuation_binding_hash',
  'checked_at','valid_until','evidence','evaluation']||carry_fields;
 stored_facts tutor_item_supply_shared_admission_facts%ROWTYPE;
 carry_parent tutor_item_supply_shared_admission_facts%ROWTYPE;
 carry_origin tutor_item_supply_shared_admission_facts%ROWTYPE;
 carry_parent_id uuid;carry_origin_id uuid;
 -- 592 current-carry locals end.

BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',n.generation_artifact_id);
 -- 592 current-carry fences begin.
 -- A consumer keeps SHARE on its own facts until its caller TOP ends. Issuance
 -- takes UPDATE on that same row as predecessor, so publication and supersession
 -- cannot both pass a stale leaf check. Do not lock an ancestor before this row.
 SELECT cf.* INTO stored_facts FROM tutor_item_supply_shared_admission_facts cf
  WHERE cf.id=n.id FOR SHARE;
 -- MVCC can expose our own RELEASEd savepoint row. For this fresh bounded TOP,
 -- require a normal xmin strictly preceding its TOP in 32-bit modular order.
 -- Do not use subtransaction status or snapshot-visible functions as a proof.
 IF stored_facts.id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM tutor_item_supply_shared_admission_facts cf WHERE cf.id=n.id
   AND cf.xmin::text::bigint>=3
   AND ((pg_catalog.txid_current()%4294967296-cf.xmin::text::bigint+4294967296)%4294967296) BETWEEN 1 AND 2147483647) THEN
  RAISE check_violation USING MESSAGE='592 current facts consumption requires prior-TOP COMMIT'; END IF;
 IF stored_facts.id IS NOT NULL AND (stored_facts.payload_json IS DISTINCT FROM p
  OR stored_facts.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(p)) THEN
  RAISE check_violation USING MESSAGE='592 persisted facts identity changed'; END IF;
 -- This is a separate READ COMMITTED statement after the row-lock wait above.
 IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts cf
  WHERE cf.payload_json->>'schema_version'='issued_shared_admission_facts_v2'
   AND cf.payload_json ? 'current_predecessor_facts_id'
   AND (cf.payload_json->>'current_predecessor_facts_id')::uuid=n.id) THEN
  RAISE check_violation USING MESSAGE='592 superseded facts are historical DATA only'; END IF;
 IF p ?| carry_fields THEN
  IF NOT (p ?& carry_fields) OR EXISTS(SELECT 1 FROM unnest(carry_fields) AS field(field_name)
    WHERE jsonb_typeof(p->field.field_name) IS DISTINCT FROM 'string') THEN
   RAISE check_violation USING MESSAGE='592 all four current lineage fields must be nonnull strings'; END IF;
  IF p->>'current_predecessor_facts_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR p->>'adjudication_origin_facts_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR p->>'current_predecessor_facts_hash' !~ '^[0-9a-f]{64}$'
   OR p->>'adjudication_origin_facts_hash' !~ '^[0-9a-f]{64}$' THEN
   RAISE check_violation USING MESSAGE='592 current lineage requires canonical UUIDs and hashes'; END IF;
  carry_parent_id:=(p->>'current_predecessor_facts_id')::uuid;
  carry_origin_id:=(p->>'adjudication_origin_facts_id')::uuid;
  IF carry_parent_id=n.id OR carry_origin_id=n.id THEN
   RAISE check_violation USING MESSAGE='592 current lineage cannot refer to itself'; END IF;
  IF stored_facts.id IS NULL THEN
   SELECT cp.* INTO carry_parent FROM tutor_item_supply_shared_admission_facts cp
    WHERE cp.id=carry_parent_id AND cp.job_id<>n.job_id AND cp.xmin::text::bigint>=3
     AND ((pg_catalog.txid_current()%4294967296-cp.xmin::text::bigint+4294967296)%4294967296) BETWEEN 1 AND 2147483647 FOR UPDATE;
  ELSE
   -- An existing child does not upgrade its ancestor lock. Another consumer may
   -- already hold SHARE there; its own row above is the supersession fence.
   SELECT cp.* INTO carry_parent FROM tutor_item_supply_shared_admission_facts cp
    WHERE cp.id=carry_parent_id AND cp.job_id<>n.job_id AND cp.xmin::text::bigint>=3
     AND ((pg_catalog.txid_current()%4294967296-cp.xmin::text::bigint+4294967296)%4294967296) BETWEEN 1 AND 2147483647 FOR SHARE;
  END IF;
  SELECT co.* INTO carry_origin FROM tutor_item_supply_shared_admission_facts co
   WHERE co.id=carry_origin_id AND co.xmin::text::bigint>=3
     AND ((pg_catalog.txid_current()%4294967296-co.xmin::text::bigint+4294967296)%4294967296) BETWEEN 1 AND 2147483647 FOR SHARE;
  IF carry_parent.id IS NULL OR carry_origin.id IS NULL
   OR carry_parent.payload_hash IS DISTINCT FROM p->>'current_predecessor_facts_hash'
   OR carry_origin.payload_hash IS DISTINCT FROM p->>'adjudication_origin_facts_hash'
   OR carry_parent.payload_json->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v2'
   OR carry_origin.payload_json->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v2'
   OR carry_parent.payload_json->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal'
   OR carry_origin.payload_json->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal'
   OR p->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal'
   OR carry_origin.payload_json ?| carry_fields THEN
   RAISE check_violation USING MESSAGE='592 exact prior-COMMIT eligible origin and predecessor required'; END IF;
  IF carry_parent.id<>carry_origin.id AND (
   NOT (carry_parent.payload_json ?& carry_fields)
   OR EXISTS(SELECT 1 FROM unnest(carry_fields) AS field(field_name)
     WHERE jsonb_typeof(carry_parent.payload_json->field.field_name) IS DISTINCT FROM 'string')
   OR carry_parent.payload_json->>'adjudication_origin_facts_id' IS DISTINCT FROM carry_origin.id::text
   OR carry_parent.payload_json->>'adjudication_origin_facts_hash' IS DISTINCT FROM carry_origin.payload_hash) THEN
   RAISE check_violation USING MESSAGE='592 current predecessor must retain the original semantic origin'; END IF;
  IF ROW(n.root_id,n.generation_artifact_id,n.item_id,n.version_id,n.source_hash,n.content_hash,
      n.validation_preparation_id,n.validation_receipt_id,n.blind_receipt_id,n.review_receipt_id,n.publication_enabled)
    IS DISTINCT FROM ROW(carry_origin.root_id,carry_origin.generation_artifact_id,carry_origin.item_id,
      carry_origin.version_id,carry_origin.source_hash,carry_origin.content_hash,carry_origin.validation_preparation_id,
      carry_origin.validation_receipt_id,carry_origin.blind_receipt_id,carry_origin.review_receipt_id,carry_origin.publication_enabled)
   OR ROW(carry_parent.root_id,carry_parent.generation_artifact_id,carry_parent.item_id,carry_parent.version_id,
      carry_parent.source_hash,carry_parent.content_hash,carry_parent.validation_preparation_id,
      carry_parent.validation_receipt_id,carry_parent.blind_receipt_id,carry_parent.review_receipt_id,carry_parent.publication_enabled)
    IS DISTINCT FROM ROW(carry_origin.root_id,carry_origin.generation_artifact_id,carry_origin.item_id,
      carry_origin.version_id,carry_origin.source_hash,carry_origin.content_hash,carry_origin.validation_preparation_id,
      carry_origin.validation_receipt_id,carry_origin.blind_receipt_id,carry_origin.review_receipt_id,carry_origin.publication_enabled)
   OR (p-carry_mutable) IS DISTINCT FROM (carry_origin.payload_json-carry_mutable)
   OR (carry_parent.payload_json-carry_mutable) IS DISTINCT FROM (carry_origin.payload_json-carry_mutable)
   OR ((p->'evidence')-ARRAY['source_current','source_claim_receipt_hashes'])
    IS DISTINCT FROM ((carry_origin.payload_json->'evidence')-ARRAY['source_current','source_claim_receipt_hashes'])
   OR ((carry_parent.payload_json->'evidence')-ARRAY['source_current','source_claim_receipt_hashes'])
    IS DISTINCT FROM ((carry_origin.payload_json->'evidence')-ARRAY['source_current','source_claim_receipt_hashes'])
   OR ((p->'evaluation')-'evidence_hash') IS DISTINCT FROM ((carry_origin.payload_json->'evaluation')-'evidence_hash')
   OR ((carry_parent.payload_json->'evaluation')-'evidence_hash') IS DISTINCT FROM ((carry_origin.payload_json->'evaluation')-'evidence_hash')
   OR p->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'evidence')
   OR jsonb_typeof(p#>'{lease,profile,profile_key_hash}') IS DISTINCT FROM 'string'
   OR p#>>'{lease,profile,profile_key_hash}' IS DISTINCT FROM carry_parent.payload_json#>>'{lease,profile,profile_key_hash}'
   OR p#>>'{lease,profile,profile_key_hash}' IS DISTINCT FROM carry_origin.payload_json#>>'{lease,profile,profile_key_hash}' THEN
   RAISE check_violation USING MESSAGE='592 current carry cannot change semantic facts or original producers'; END IF;
  IF n.job_id=carry_parent.job_id OR n.job_id=carry_origin.job_id
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts cf
    WHERE cf.job_id=n.job_id AND cf.generation_artifact_id=n.generation_artifact_id AND cf.id<>n.id) THEN
   RAISE check_violation USING MESSAGE='592 current carry requires a fresh different job with one facts'; END IF;
  -- With predecessor UPDATE held for a new row, this fresh statement sees a
  -- sibling that committed while we waited. Existing self-verification is valid.
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts cf
   WHERE cf.payload_json->>'schema_version'='issued_shared_admission_facts_v2'
    AND cf.payload_json ? 'current_predecessor_facts_id'
    AND (cf.payload_json->>'current_predecessor_facts_id')::uuid=carry_parent.id AND cf.id<>n.id) THEN
   RAISE check_violation USING MESSAGE='592 current predecessor already has another successor'; END IF;
  IF stored_facts.id IS NULL AND EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe
    WHERE pe.version_id=n.version_id AND pe.state='published') THEN
   RAISE check_violation USING MESSAGE='592 published version must use the original current query'; END IF;
  -- The initial semantic/quarantine/adjudication fields remain fixed. Only the
  -- four closed current-lineage keys are additionally omitted by the old guard.
  allowed:=allowed||carry_fields;
 END IF;
 -- 592 current-carry fences end.
 SELECT * INTO old FROM tutor_item_supply_shared_admission_facts WHERE id=(p->>'same_version_predecessor_id')::uuid FOR SHARE;
 SELECT * INTO adjudication FROM tutor_item_supply_shared_review_adjudication_events
  WHERE id=(p->>'adjudication_receipt_id')::uuid AND event_kind='committed' FOR SHARE;
 SELECT * INTO prep FROM tutor_item_supply_shared_review_adjudication_preparations WHERE id=adjudication.preparation_id FOR SHARE;
 SELECT * INTO review FROM tutor_item_supply_shared_pipeline_receipts WHERE id=n.review_receipt_id AND artifact_kind='review_bundle' FOR SHARE;
 SELECT * INTO validation FROM tutor_item_supply_shared_pipeline_receipts WHERE id=n.validation_receipt_id AND artifact_kind='validation' FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=n.generation_artifact_id FOR SHARE;
 IF old.id IS NULL OR adjudication.id IS NULL OR prep.id IS NULL OR review.id IS NULL OR validation.id IS NULL
  OR adjudication.payload_json->>'usage_state' IS DISTINCT FROM 'known'
  OR jsonb_typeof(adjudication.payload_json->'report') IS DISTINCT FROM 'object'
  OR adjudication.payload_json->>'report_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(adjudication.payload_json->'report')
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements u
      WHERE u.id=(adjudication.payload_json->>'settlement_id')::uuid AND u.reservation_id=prep.reservation_id
       AND u.settlement_key='adjudicate.'||prep.action_hash AND u.usage_state='known'
       AND u.receipt_hash=adjudication.payload_json->>'report_hash'
       AND u.xmin::text::bigint<>txid_current()%4294967296
       AND (SELECT jsonb_object_agg(sa.resource_kind,sa.actual_amount)
         FROM tutor_item_supply_shared_runtime_settlement_amounts sa WHERE sa.settlement_id=u.id)
        =jsonb_build_object('requests',1,'input_tokens',adjudication.payload_json#>'{report,run,input_tokens}',
          'output_tokens',adjudication.payload_json#>'{report,run,output_tokens}','execution_seconds',0,
          'fetches',0,'candidates',0,'revision_rounds',0,'investigation_rounds',1))
  OR p->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v2' OR old.payload_hash IS DISTINCT FROM p->>'same_version_predecessor_hash'
  OR old.generation_artifact_id IS DISTINCT FROM n.generation_artifact_id OR old.root_id IS DISTINCT FROM n.root_id
  OR old.item_id IS DISTINCT FROM n.item_id OR old.version_id IS DISTINCT FROM n.version_id
  OR old.source_hash IS DISTINCT FROM n.source_hash OR old.content_hash IS DISTINCT FROM n.content_hash
  OR old.review_receipt_id IS DISTINCT FROM n.review_receipt_id OR old.blind_receipt_id IS DISTINCT FROM n.blind_receipt_id
  OR old.validation_receipt_id IS DISTINCT FROM n.validation_receipt_id OR old.validation_preparation_id IS DISTINCT FROM n.validation_preparation_id
  OR (p-allowed) IS DISTINCT FROM (old.payload_json-allowed)
  OR (e-ARRAY['source_current','source_claim_receipt_hashes']) IS DISTINCT FROM ((old.payload_json->'evidence')-ARRAY['source_current','source_claim_receipt_hashes'])
  OR p->>'receipt_id' IS DISTINCT FROM n.id::text OR p->>'root_id' IS DISTINCT FROM n.root_id::text
  OR p->'lease'->>'job_id' IS DISTINCT FROM n.job_id::text OR p->'lease'->>'lease_owner' IS DISTINCT FROM n.lease_owner
  OR p->'lease'->>'generation' IS DISTINCT FROM n.lease_generation::text OR p->'lease'->>'state_version' IS DISTINCT FROM n.lease_state_version::text
  OR p->'lease'->'profile'->>'profile_hash' IS DISTINCT FROM n.profile_hash OR p->>'profile_hash' IS DISTINCT FROM n.profile_hash
  OR p->>'continuation_binding_hash' IS DISTINCT FROM n.continuation_binding_hash
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations c WHERE c.job_id=n.job_id
    AND c.root_id=n.root_id AND c.generation_artifact_id=n.generation_artifact_id AND c.binding_hash=n.continuation_binding_hash)
  OR prep.generation_artifact_id IS DISTINCT FROM n.generation_artifact_id OR prep.root_id IS DISTINCT FROM n.root_id
  OR prep.payload_json->'lease'->'profile'->>'profile_key_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_key_hash'
  OR prep.payload_json->'request'->'original_input'->>'review_receipt_id' IS DISTINCT FROM n.review_receipt_id::text
  OR adjudication.payload_json->>'report_hash' IS DISTINCT FROM p->>'adjudication_report_hash'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_events x WHERE x.id=adjudication.id AND x.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts x WHERE x.id=old.id AND x.xmin::text::bigint=txid_current()%4294967296)
  OR (p->>'checked_at')::timestamptz>clock_timestamp() OR (p->>'valid_until')::timestamptz<=clock_timestamp()
  OR (p->>'valid_until')::timestamptz>LEAST((p->'lease'->>'expires_at')::timestamptz,(p->'lease'->>'parent_deadline')::timestamptz)
  OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
  OR COALESCE((p->>'valid_until')::timestamptz<=item_supply_internal.incremental_shared_source_deadline(a.request_json),false) IS DISTINCT FROM true THEN
  RAISE EXCEPTION '588 same-version new facts require exact historical DATA and original current adjudication'; END IF;
 -- Original immutable committed adjudication is DATA. Current authority was checked
 -- above on the NEW facts lease; never renew its expired producer preparation.
 report:=adjudication.payload_json->'report';disputes:=item_supply_internal.revision_recheck_disputes(review.payload_json);
 policy:=item_supply_internal.shared_generation_policy_hash(a);
 IF report IS NULL OR report='null'::jsonb OR e->'binding' IS DISTINCT FROM review.payload_json->'binding'
  OR evaluation->'binding' IS DISTINCT FROM e->'binding' OR evaluation->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(e)
  OR evaluation->'bundle_hashes' IS DISTINCT FROM jsonb_build_array(review.receipt_hash)
  OR evaluation->'binding'->>'policy_hash' IS DISTINCT FROM policy
  OR evaluation->>'state' IS DISTINCT FROM 'evaluated' OR evaluation->>'mode' IS DISTINCT FROM 'internal_only'
  OR evaluation->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
  OR (policy='7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab'
    AND (evaluation->>'schema_version' IS DISTINCT FROM 'item_supply_admission_evaluation_v2' OR evaluation ? 'diagnostic_warnings'))
  OR (policy='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
    AND evaluation->>'schema_version' IS DISTINCT FROM 'item_supply_admission_evaluation_v3') THEN
  RAISE EXCEPTION '588 original same-version policy and evidence cannot be rebound'; END IF;
 IF evaluation->>'disposition'='eligible_internal' THEN
  SELECT array_agg(v->>'probe') INTO probes FROM jsonb_array_elements(e->'probes') v WHERE v->'passed'='true'::jsonb;
  execution_required:=e->'binding'->>'risk_tier'<>'low' OR a.source_json->'public'->>'kind'<>'knowledge_check';
  IF jsonb_array_length(report->'output'->'dispositions') IS DISTINCT FROM jsonb_array_length(disputes)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(report->'output'->'dispositions') d WHERE d->>'disposition'<>'refuted')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(disputes) d WHERE NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(report->'output'->'dispositions') x WHERE x->>'dispute_key'=d->>'dispute_key'))
   OR validation.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
   OR (policy='7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab'
      AND item_supply_internal.incremental_blind_score(review.payload_json->'blind_solve')->'passed' IS DISTINCT FROM 'true'::jsonb)
   OR e->'known_misjudgments' IS DISTINCT FROM '0'::jsonb OR e->'source_current' IS DISTINCT FROM 'true'::jsonb
   OR e->'source_claim_receipt_hashes' IS DISTINCT FROM (SELECT jsonb_agg(DISTINCT h ORDER BY h)
      FROM jsonb_array_elements(a.receipt_json->'sources') src,LATERAL jsonb_array_elements(src->'claim_receipt_hashes') h)
   OR jsonb_array_length(e->'source_claim_receipt_hashes')<1 OR e->>'coverage_proof_hash' IS NULL OR e->'scorer_available' IS DISTINCT FROM 'true'::jsonb
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(e->'probes') v WHERE v->'passed' IS DISTINCT FROM 'true'::jsonb)
   OR NOT (COALESCE(probes,'{}'::text[]) @> ARRAY['correct','incorrect','ambiguity']::text[])
   OR (execution_required AND (e->'execution_isolated' IS DISTINCT FROM 'true'::jsonb OR e->'runner_available' IS DISTINCT FROM 'true'::jsonb
      OR e->>'execution_receipt_hash' IS NULL OR NOT (COALESCE(probes,'{}'::text[]) @> ARRAY['equivalent','known_wrong','boundary','scorer_counterexample']::text[])))
   OR e->'binding'->>'risk_tier'='high' THEN
   RAISE EXCEPTION '588 disposition cannot waive original machine blind source coverage execution or high-risk gates'; END IF;
 END IF;
END $carrybody592$;
  actual pg_catalog.pg_proc%ROWTYPE;
  verified pg_catalog.pg_proc%ROWTYPE;
  definition text;
BEGIN
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=to_regprocedure(signature);
  IF NOT FOUND OR NOT actual.prosecdef
    OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] THEN
    RAISE check_violation USING MESSAGE='592 original adjudicated facts security/settings differ';
  END IF;
  IF md5(revised_source) IS DISTINCT FROM revised_md5 THEN
    RAISE check_violation USING MESSAGE='592 current-carry assertion literal pin mismatch';
  END IF;
  IF md5(actual.prosrc)=revised_md5 THEN RETURN; END IF;
  IF md5(actual.prosrc) IS DISTINCT FROM baseline_md5 THEN
    RAISE check_violation USING MESSAGE='592 unknown original adjudicated facts assertion';
  END IF;
  definition:=pg_get_functiondef(actual.oid);
  IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1 THEN
    RAISE check_violation USING MESSAGE='592 adjudicated facts body framing mismatch';
  END IF;
  EXECUTE replace(definition,actual.prosrc,revised_source);
  SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
  IF md5(verified.prosrc) IS DISTINCT FROM revised_md5
    OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc') THEN
    RAISE check_violation USING MESSAGE='592 adjudicated facts body or original metadata verification failed';
  END IF;
END $assert_carry592$;

-- One semantic facts origin per adjudication; one physical current successor per
-- predecessor. Keep the original PK/per-job/legacy/adjudication/probe uniqueness.
DO $indexes592$
DECLARE
  old_once constant text := $once_old592$CREATE UNIQUE INDEX shared_adjudicated_facts_once ON public.tutor_item_supply_shared_admission_facts USING btree (((payload_json ->> 'adjudication_receipt_id'::text))) WHERE ((payload_json ->> 'schema_version'::text) = 'issued_shared_admission_facts_v2'::text)$once_old592$;
  new_once constant text := $once_new592$CREATE UNIQUE INDEX shared_adjudicated_facts_once ON public.tutor_item_supply_shared_admission_facts USING btree (((payload_json ->> 'adjudication_receipt_id'::text))) WHERE (((payload_json ->> 'schema_version'::text) = 'issued_shared_admission_facts_v2'::text) AND (NOT (payload_json ? 'current_predecessor_facts_id'::text)))$once_new592$;
  new_successor constant text := $successor_new592$CREATE UNIQUE INDEX shared_adjudicated_facts_current_successor_once ON public.tutor_item_supply_shared_admission_facts USING btree ((((payload_json ->> 'current_predecessor_facts_id'::text))::uuid)) WHERE (((payload_json ->> 'schema_version'::text) = 'issued_shared_admission_facts_v2'::text) AND (payload_json ? 'current_predecessor_facts_id'::text))$successor_new592$;
  actual_once text;
  actual_successor text;
BEGIN
  LOCK TABLE public.tutor_item_supply_shared_admission_facts IN SHARE ROW EXCLUSIVE MODE;
  actual_once:=pg_get_indexdef(to_regclass('public.shared_adjudicated_facts_once'));
  actual_successor:=pg_get_indexdef(to_regclass('public.shared_adjudicated_facts_current_successor_once'));
  IF actual_once IS NULL OR actual_once NOT IN (old_once,new_once)
    OR (actual_successor IS NOT NULL AND actual_successor IS DISTINCT FROM new_successor) THEN
    RAISE check_violation USING MESSAGE='592 unknown adjudicated facts index definition';
  END IF;
  IF EXISTS(SELECT 1 FROM pg_catalog.pg_index ix WHERE ix.indexrelid IN (
      to_regclass('public.shared_adjudicated_facts_once'),to_regclass('public.shared_adjudicated_facts_current_successor_once'))
      AND (NOT ix.indisunique OR NOT ix.indisvalid OR NOT ix.indisready)) THEN
    RAISE check_violation USING MESSAGE='592 adjudicated facts index must be valid ready and unique';
  END IF;
  IF actual_once=old_once THEN
    DROP INDEX public.shared_adjudicated_facts_once;
    CREATE UNIQUE INDEX shared_adjudicated_facts_once
      ON public.tutor_item_supply_shared_admission_facts((payload_json->>'adjudication_receipt_id'))
      WHERE payload_json->>'schema_version'='issued_shared_admission_facts_v2'
        AND NOT (payload_json ? 'current_predecessor_facts_id');
  END IF;
  IF actual_successor IS NULL THEN
    CREATE UNIQUE INDEX shared_adjudicated_facts_current_successor_once
      ON public.tutor_item_supply_shared_admission_facts(((payload_json->>'current_predecessor_facts_id')::uuid))
      WHERE payload_json->>'schema_version'='issued_shared_admission_facts_v2'
        AND payload_json ? 'current_predecessor_facts_id';
  END IF;
  actual_once:=pg_get_indexdef(to_regclass('public.shared_adjudicated_facts_once'));
  actual_successor:=pg_get_indexdef(to_regclass('public.shared_adjudicated_facts_current_successor_once'));
  IF actual_once IS DISTINCT FROM new_once OR actual_successor IS DISTINCT FROM new_successor THEN
    RAISE check_violation USING MESSAGE='592 exact current-carry index verification failed',
      DETAIL=COALESCE(actual_once,'missing')||E'\n'||COALESCE(actual_successor,'missing');
  END IF;
END $indexes592$;
