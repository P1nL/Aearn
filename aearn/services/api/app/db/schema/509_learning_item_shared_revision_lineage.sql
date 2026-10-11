-- STAGED/REGISTERED_NOT_INSTALLED: no DDL/real revision acceptance is asserted.
-- Shared-confidential attempted revision DATA, never admission/discharge authority.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_revision_preparations (
  id uuid PRIMARY KEY,
  root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  parent_job_id uuid NOT NULL,
  child_job_id uuid NOT NULL UNIQUE,
  parent_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  investigation_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_review_investigation_receipts(id) ON DELETE RESTRICT,
  candidate_id uuid NOT NULL UNIQUE,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'native_shared_revision_preparation_v1'),
  snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  valid_until timestamptz NOT NULL,
  mode text NOT NULL DEFAULT 'live_revision_pending' CHECK(mode='live_revision_pending'),
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  blockers_discharged boolean NOT NULL DEFAULT false CHECK(blockers_discharged=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,root_id,child_job_id,parent_artifact_id),
  FOREIGN KEY(parent_job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(child_job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_revision_lineage (
  id uuid PRIMARY KEY,
  preparation_id uuid NOT NULL UNIQUE,
  root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  parent_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  child_artifact_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  child_job_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  settlement_id uuid NOT NULL REFERENCES tutor_item_supply_shared_runtime_settlements(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'native_shared_revision_lineage_v1'),
  snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  mode text NOT NULL DEFAULT 'verified_parent_child_data_only' CHECK(mode='verified_parent_child_data_only'),
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  blockers_discharged boolean NOT NULL DEFAULT false CHECK(blockers_discharged=false),
  admission_eligible boolean NOT NULL DEFAULT false CHECK(admission_eligible=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(preparation_id,root_id,child_job_id,parent_artifact_id)
    REFERENCES tutor_item_supply_shared_revision_preparations(id,root_id,child_job_id,parent_artifact_id) ON DELETE RESTRICT,
  FOREIGN KEY(child_job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,child_job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION item_supply_internal.revision_substantive_hash(source_payload jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT item_supply_internal.snapshot_hash(jsonb_build_object(
   'instruction',source_payload->'public'->'instruction_markdown','content',source_payload->'public'->'content',
   'hints',source_payload->'public'->'hints','private_content',source_payload->'private'->'content',
   'source_references',source_payload->'public'->'source_references'))
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.native_revision_descendant(operation_job uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 WITH RECURSIVE ancestry AS (
   SELECT j.id,j.parent_job_id FROM tutor_item_supply_shared_jobs j WHERE j.id=operation_job
   UNION
   SELECT j.id,j.parent_job_id FROM tutor_item_supply_shared_jobs j JOIN ancestry aa ON j.id=aa.parent_job_id
 ) SELECT EXISTS(SELECT 1 FROM ancestry aa JOIN tutor_item_supply_shared_revision_preparations rp ON rp.child_job_id=aa.id)
$$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_native_revision_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=parent_artifact.id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.generation_artifact_id=parent_artifact.id AND rr.artifact_kind='admission_evaluation')
    OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe WHERE pe.version_id=parent_artifact.version_id) THEN
    RAISE check_violation USING MESSAGE='revision current original investigation/child/source/history required';
  END IF;
  IF context_payload->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v1'
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
    OR request_payload->'blueprint' IS DISTINCT FROM parent_artifact.source_json->'blueprint'
    OR request_payload->'materials' IS DISTINCT FROM parent_artifact.request_json->'materials'
    OR request_payload->>'demand_binding' IS NOT NULL OR request_payload->>'scope_hash' IS DISTINCT FROM context_payload->>'scope_hash'
    OR request_payload->>'candidate_id' IS DISTINCT FROM context_payload->>'child_candidate_id'
    OR request_payload->>'item_key' IS DISTINCT FROM context_payload->>'child_item_key'
    OR request_payload->>'version' IS DISTINCT FROM context_payload->>'child_version'
    OR request_payload->>'candidate_id'=parent_artifact.candidate_id::text
    OR request_payload->>'item_key'=parent_artifact.source_json->'public'->>'item_key'
    OR request_payload->>'version'=parent_artifact.source_json->'public'->>'version'
    OR request_payload->'limits'->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
    OR (request_payload->'public_template' - ARRAY['item_key','version']) IS DISTINCT FROM
      (parent_artifact.request_json->'public_template' - ARRAY['item_key','version'])
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
  RETURN NEW;
END $$;

-- Additive guard on the ORIGINAL generation writer. No old function replacement.
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_revision_generation_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE preparation_row tutor_item_supply_shared_revision_preparations%ROWTYPE;
BEGIN
  SELECT * INTO preparation_row FROM tutor_item_supply_shared_revision_preparations rp WHERE rp.child_job_id=NEW.job_id;
  IF FOUND AND (NEW.candidate_id IS DISTINCT FROM preparation_row.candidate_id OR NEW.root_id IS DISTINCT FROM preparation_row.root_id
    OR NEW.request_json IS DISTINCT FROM preparation_row.payload_json->'request'
    OR NEW.source_json->'blueprint' IS DISTINCT FROM preparation_row.payload_json->'context'->'parent_source'->'blueprint'
    OR item_supply_internal.revision_substantive_hash(NEW.source_json)=preparation_row.payload_json->>'parent_substantive_hash'
    OR preparation_row.valid_until<=clock_timestamp()) THEN
    RAISE check_violation USING MESSAGE='revision child requires frozen context and substantive new source';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.deny_revision_admission_without_discharge() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE artifact_job uuid;
BEGIN
  SELECT a.job_id INTO artifact_job FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=NEW.generation_artifact_id;
  IF artifact_job IS NOT NULL AND item_supply_internal.native_revision_descendant(artifact_job) THEN
    RAISE check_violation USING MESSAGE='revision historical blocker discharge owner pending';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_native_revision_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_revision_generation_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.deny_revision_admission_without_discharge() FROM PUBLIC;
DO $$ DECLARE table_name text; BEGIN
 FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_revision_preparations','tutor_item_supply_shared_revision_lineage'] LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS native_revision_insert ON %I',table_name);
   EXECUTE format('CREATE TRIGGER native_revision_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_native_revision_insert()',table_name);
   EXECUTE format('DROP TRIGGER IF EXISTS native_revision_immutable ON %I',table_name);
   EXECUTE format('CREATE TRIGGER native_revision_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''shared'')',table_name);
 END LOOP;
END $$;
DROP TRIGGER IF EXISTS native_revision_generation_insert ON tutor_item_supply_shared_generation_artifacts;
CREATE TRIGGER native_revision_generation_insert BEFORE INSERT ON tutor_item_supply_shared_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_revision_generation_insert();
DROP TRIGGER IF EXISTS native_revision_no_admission ON tutor_item_supply_shared_admission_facts;
CREATE TRIGGER native_revision_no_admission BEFORE INSERT ON tutor_item_supply_shared_admission_facts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.deny_revision_admission_without_discharge();
DROP TRIGGER IF EXISTS native_revision_no_publication ON tutor_learning_item_native_publication_proofs;
CREATE TRIGGER native_revision_no_publication BEFORE INSERT ON tutor_learning_item_native_publication_proofs
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.deny_revision_admission_without_discharge();
