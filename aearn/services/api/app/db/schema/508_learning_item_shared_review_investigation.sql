-- STAGED/REGISTERED ONLY until separately authorized installation and DB validation.
-- Shared-confidential investigation audit, NOT learner-private or publication.
-- All original 440-507 functions/rows remain unchanged. No reset/export additions.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_review_investigation_preparations (
  id uuid PRIMARY KEY,
  root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  job_id uuid NOT NULL,
  lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  review_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  reservation_id uuid NOT NULL UNIQUE,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'native_shared_review_investigation_preparation_v1'),
  snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  valid_until timestamptz NOT NULL,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,root_id,job_id,review_receipt_id,reservation_id),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_review_investigation_receipts (
  id uuid PRIMARY KEY,
  preparation_id uuid NOT NULL UNIQUE,
  root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  job_id uuid NOT NULL,
  lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  review_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  reservation_id uuid NOT NULL,
  settlement_id uuid NOT NULL REFERENCES tutor_item_supply_shared_runtime_settlements(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'native_shared_review_investigation_receipt_v1'),
  snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  valid_until timestamptz NOT NULL,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(preparation_id,root_id,job_id,review_receipt_id,reservation_id)
    REFERENCES tutor_item_supply_shared_review_investigation_preparations(id,root_id,job_id,review_receipt_id,reservation_id) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION item_supply_internal.review_investigation_pointer_value(document jsonb, pointer text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE node jsonb:=document; token text; tokens text[];
BEGIN
  IF length(pointer)>512 OR pointer !~ '^/(source|validation_receipt|scoring_descriptor)/' THEN RETURN NULL; END IF;
  tokens:=string_to_array(substring(pointer FROM 2),'/');
  IF cardinality(tokens)>26 THEN RETURN NULL; END IF;
  FOREACH token IN ARRAY tokens LOOP
    token:=replace(replace(token,'~1','/'),'~0','~');
    IF jsonb_typeof(node)='array' THEN
      IF token !~ '^[0-9]{1,6}$' THEN RETURN NULL; END IF;
      node:=node->(token::integer);
    ELSE node:=node->token; END IF;
    IF node IS NULL THEN RETURN NULL; END IF;
  END LOOP;
  RETURN node;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_review_investigation_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
  material_count integer; expected_disputes integer:=0;
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
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='validating' AND cp.status='completed')
    OR NOT (EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='generating' AND cp.status='completed')
      OR item_supply_internal.shared_continuation_generation_inherited(NEW.job_id))
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id
      AND cp.stage IN ('investigating','revising','simulating','admitting') AND cp.status='completed') THEN
    RAISE check_violation USING MESSAGE='investigation original reviewing or investigating position required';
  END IF;
  SELECT * INTO artifact_row FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id FOR SHARE;
  SELECT * INTO review_row FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id FOR SHARE;
  IF artifact_row.id IS NULL OR review_row.id IS NULL OR artifact_row.root_id<>NEW.root_id
    OR review_row.job_id<>NEW.job_id OR review_row.lease_generation<>NEW.lease_generation
    OR review_row.lease_owner IS DISTINCT FROM NEW.lease_owner OR review_row.artifact_kind<>'review_bundle'
    OR review_row.mode<>'live' OR review_row.generation_artifact_id<>artifact_row.id
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id AND rr.xmin::text::bigint=(txid_current()%4294967296))
    OR item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,artifact_row.id,review_row.continuation_binding_hash) IS DISTINCT FROM true
    OR p->>'continuation_binding_hash' IS DISTINCT FROM review_row.continuation_binding_hash
    OR review_row.source_hash IS DISTINCT FROM artifact_row.source_hash OR review_row.content_hash IS DISTINCT FROM artifact_row.content_hash
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=artifact_row.id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.generation_artifact_id=artifact_row.id AND rr.artifact_kind='admission_evaluation')
    OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe WHERE pe.version_id=artifact_row.version_id) THEN
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
    OR request_payload->>'schema_version' IS DISTINCT FROM 'native_shared_review_investigation_input_v1'
    OR request_payload->>'purpose' IS DISTINCT FROM 'live_dispute_investigation'
    OR request_payload->>'authority' IS DISTINCT FROM 'original_shared_owner_required'
    OR request_payload->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
    OR request_payload->>'review_receipt_hash' IS DISTINCT FROM review_row.receipt_hash
    OR request_payload ?| ARRAY['bundle','blind_solve','score','answer','lease','budget']
    OR request_payload->'review_input'->'source' IS DISTINCT FROM artifact_row.source_json
    OR binding IS DISTINCT FROM review_row.payload_json->'binding'
    OR binding->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
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
      WHERE rs.id=(p->>'original_review_reservation_id')::uuid AND rs.job_id=NEW.job_id
        AND rs.root_id=NEW.root_id AND rs.lease_generation=NEW.lease_generation
        AND rs.reservation_key='review.'||replace(artifact_row.id::text,'-','')
        AND us.settlement_key=rs.reservation_key AND us.usage_state='unknown'
        AND us.xmin::text::bigint<>(txid_current()%4294967296)) THEN
    RAISE check_violation USING MESSAGE='investigation original shared review accounting required';
  END IF;
  SELECT * INTO validation_row FROM tutor_item_supply_shared_pipeline_receipts vr WHERE vr.id=(p->>'validation_receipt_id')::uuid;
  SELECT * INTO blind_row FROM tutor_item_supply_shared_pipeline_receipts br WHERE br.id=(p->>'blind_receipt_id')::uuid;
  IF validation_row.id IS NULL OR blind_row.id IS NULL
    OR validation_row.job_id<>NEW.job_id OR validation_row.lease_generation<>NEW.lease_generation
    OR validation_row.generation_artifact_id<>artifact_row.id OR validation_row.artifact_kind<>'validation'
    OR validation_row.payload_json IS DISTINCT FROM request_payload->'review_input'->'validation_receipt'
    OR blind_row.job_id<>NEW.job_id OR blind_row.lease_generation<>NEW.lease_generation
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
  IF jsonb_array_length(request_payload->'disputes')<>expected_disputes
    OR (SELECT count(DISTINCT dd->>'dispute_key') FROM jsonb_array_elements(request_payload->'disputes') dd)<>expected_disputes THEN
    RAISE check_violation USING MESSAGE='investigation cannot drop or merge original material disputes';
  END IF;
  FOR dispute IN SELECT value FROM jsonb_array_elements(request_payload->'disputes') LOOP
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
          WHERE rr->>'dispute_key'=dd->>'dispute_key' AND rr->>'report_hash'=dd->>'report_hash'
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
      IF report->>'schema_version' IS DISTINCT FROM 'native_shared_review_investigation_report_v1'
        OR report->'output'->>'schema_version' IS DISTINCT FROM 'native_shared_review_investigation_output_v1'
        OR report->'binding' IS DISTINCT FROM binding OR report->>'review_receipt_hash' IS DISTINCT FROM review_row.receipt_hash
        OR report->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
        OR report->'run'->'provider_identity' IS DISTINCT FROM p->'identity'
        OR report->'run'->>'input_hash' IS DISTINCT FROM p->>'request_hash'
        OR report->'run'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
        OR report->'run'->>'prompt_version' IS DISTINCT FROM 'native-shared-review-investigation-v1'
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
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_shared_review_investigation_insert() FROM PUBLIC;
DO $$ DECLARE table_name text; BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_review_investigation_preparations','tutor_item_supply_shared_review_investigation_receipts'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS shared_review_investigation_insert ON %I',table_name);
    EXECUTE format('CREATE TRIGGER shared_review_investigation_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_review_investigation_insert()',table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS shared_review_investigation_immutable ON %I',table_name);
    EXECUTE format('CREATE TRIGGER shared_review_investigation_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''shared'')',table_name);
  END LOOP;
END $$;
