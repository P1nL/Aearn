-- STAGED/REGISTERED_NOT_INSTALLED. Partial clause DATA only; 509 hold unchanged.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_revision_recheck_preparations (
 id uuid PRIMARY KEY,
 lineage_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_revision_lineage(id) ON DELETE RESTRICT,
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid NOT NULL,
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576
   AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'native_shared_revision_recheck_preparation_v1'),
 snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 valid_until timestamptz NOT NULL,
 publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
 blockers_discharged boolean NOT NULL DEFAULT false CHECK(blockers_discharged=false),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,root_id,job_id,generation_artifact_id),
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_revision_recheck_receipts (
 id uuid PRIMARY KEY,
 preparation_id uuid NOT NULL UNIQUE,
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid NOT NULL,
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
 validation_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
 blind_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
 review_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576
   AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'native_shared_revision_recheck_receipt_v1'),
 snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
 blockers_discharged boolean NOT NULL DEFAULT false CHECK(blockers_discharged=false),
 admission_eligible boolean NOT NULL DEFAULT false CHECK(admission_eligible=false),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(preparation_id,root_id,job_id,generation_artifact_id)
   REFERENCES tutor_item_supply_shared_revision_recheck_preparations(id,root_id,job_id,generation_artifact_id) ON DELETE RESTRICT,
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
-- Exact audit projection of material findings; never a discharge decision.
CREATE OR REPLACE FUNCTION item_supply_internal.revision_recheck_disputes(bundle jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 WITH reports AS (
   SELECT report,report_order FROM jsonb_array_elements(bundle->'reports') WITH ORDINALITY AS rr(report,report_order)
 ), material AS (
   SELECT rr.report,rr.report_order,ff.finding,ff.finding_order-1 AS finding_index
   FROM reports rr CROSS JOIN LATERAL jsonb_array_elements(rr.report->'findings') WITH ORDINALITY AS ff(finding,finding_order)
   WHERE ff.finding->'blocking'='true'::jsonb OR ff.finding->>'severity' IN ('major','critical')
     OR ff.finding->>'safe_code' IN ('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit')
 ), disputes AS (
   SELECT mm.report,mm.report_order,mm.finding_index,item_supply_internal.snapshot_hash(mm.finding) AS finding_hash,
     mm.finding->>'safe_code' AS safe_code,CASE WHEN mm.report->>'schema_version'='item_supply_evidenced_review_report_v1'
       THEN mm.finding->'references' ELSE '[]'::jsonb END AS field_refs FROM material mm
   UNION ALL SELECT rr.report,rr.report_order,NULL::bigint,NULL::text,'report_requires_evidence','[]'::jsonb
     FROM reports rr WHERE rr.report->>'verdict'<>'approved' AND NOT EXISTS(SELECT 1 FROM material mm WHERE mm.report_order=rr.report_order)
 ) SELECT COALESCE(jsonb_agg(jsonb_build_object(
   'dispute_key',item_supply_internal.snapshot_hash(CASE WHEN dd.finding_index IS NULL
     THEN jsonb_build_array(item_supply_internal.snapshot_hash(bundle),item_supply_internal.snapshot_hash(dd.report))
     ELSE jsonb_build_array(item_supply_internal.snapshot_hash(bundle),item_supply_internal.snapshot_hash(dd.report),dd.finding_index,dd.finding_hash) END),
   'role',dd.report->>'role','report_hash',item_supply_internal.snapshot_hash(dd.report),'run_id',dd.report->'run'->>'run_id',
   'finding_index',dd.finding_index,'finding_hash',dd.finding_hash,'safe_code',dd.safe_code,'references',dd.field_refs)
   ORDER BY dd.report_order,dd.finding_index),'[]'::jsonb) FROM disputes dd
$$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_revision_recheck_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 lineage tutor_item_supply_shared_revision_lineage%ROWTYPE;
 revision_prep tutor_item_supply_shared_revision_preparations%ROWTYPE;
 artifact tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 validation_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 blind_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 review_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 validation_prep tutor_item_supply_shared_validation_preparations%ROWTYPE;
 usage_row tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 reservation_row tutor_item_supply_shared_reservations%ROWTYPE;
 p jsonb; receipt jsonb:=NEW.payload_json; lease jsonb; snapshot jsonb; stamp timestamptz;
 old_dispute jsonb; entry jsonb; historical jsonb; provider_run jsonb; property_facts jsonb; expected_property text;
 roles text[]; expected_ancestors jsonb; expected_run_ids jsonb; expected_version integer;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='recheck B1d only'; END IF;
 IF TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_receipts' THEN
   SELECT * INTO prep FROM tutor_item_supply_shared_revision_recheck_preparations rp WHERE rp.id=NEW.preparation_id FOR SHARE;
   IF NOT FOUND OR (NEW.root_id,NEW.job_id,NEW.generation_artifact_id) IS DISTINCT FROM (prep.root_id,prep.job_id,prep.generation_artifact_id)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_recheck_preparations rp WHERE rp.id=NEW.preparation_id AND rp.xmin::text::bigint=(txid_current()%4294967296)) THEN
     RAISE check_violation USING MESSAGE='recheck committed original preparation required';
   END IF;
   p:=prep.payload_json; lease:=receipt->'lease';
 ELSE p:=NEW.payload_json; lease:=p->'lease'; END IF;
 SELECT * INTO lineage FROM tutor_item_supply_shared_revision_lineage ll WHERE ll.id=(p->>'lineage_id')::uuid FOR SHARE;
 SELECT * INTO revision_prep FROM tutor_item_supply_shared_revision_preparations rr WHERE rr.id=lineage.preparation_id FOR SHARE;
 SELECT * INTO artifact FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id FOR SHARE;
 SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR UPDATE;
 stamp:=clock_timestamp();
 snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 IF (p - ARRAY['schema_version','preparation_id','lineage_id','lineage_hash','root_id','lease','artifact_id','artifact_hash','context_hash','original_disputes','ancestor_reviews','forbidden_run_ids','bundle_version','deadline_at','publication_enabled','blockers_discharged']) <> '{}'::jsonb
   OR jsonb_typeof(p->'bundle_version') IS DISTINCT FROM 'number'
   OR jsonb_typeof(lease) IS DISTINCT FROM 'object' THEN
   RAISE check_violation USING MESSAGE='recheck closed typed preparation required';
 END IF;
 IF lineage.id IS NULL OR revision_prep.id IS NULL OR artifact.id IS NULL OR control_row.id IS NULL
   OR lineage.root_id IS DISTINCT FROM NEW.root_id OR lineage.child_artifact_id IS DISTINCT FROM artifact.id
   OR lineage.child_job_id IS DISTINCT FROM NEW.job_id OR artifact.job_id IS DISTINCT FROM NEW.job_id
   OR artifact.root_id IS DISTINCT FROM NEW.root_id OR lineage.snapshot_hash IS DISTINCT FROM p->>'lineage_hash'
   OR artifact.artifact_hash IS DISTINCT FROM p->>'artifact_hash' OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text
   OR p->>'artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
   OR p->>'context_hash' IS DISTINCT FROM revision_prep.payload_json->>'context_hash'
   OR (p->>'deadline_at')::timestamptz IS DISTINCT FROM revision_prep.valid_until
   OR revision_prep.valid_until<=stamp OR control_row.state IS DISTINCT FROM 'leased'
   OR stamp>=LEAST(control_row.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz,
     (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'))
   OR control_row.lease_expires_at IS NULL OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
   OR lease->>'job_id' IS DISTINCT FROM NEW.job_id::text OR lease->>'visibility' IS DISTINCT FROM 'public'
   OR lease->'owner_id' IS DISTINCT FROM 'null'::jsonb OR lease->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
   OR lease->>'lease_owner' IS DISTINCT FROM control_row.lease_owner
   OR lease->>'generation' IS DISTINCT FROM control_row.lease_generation::text
   OR lease->>'state_version' IS DISTINCT FROM control_row.state_version::text
   OR lease->'profile' IS DISTINCT FROM snapshot OR p->'lease'->'profile' IS DISTINCT FROM snapshot
   OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
   OR p->>'bundle_version' IS NULL OR (p->>'bundle_version')::integer<2
   OR jsonb_typeof(p->'forbidden_run_ids') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p->'original_disputes') IS DISTINCT FROM 'array'
   OR jsonb_array_length(p->'original_disputes') NOT BETWEEN 1 AND 144
   OR jsonb_typeof(p->'ancestor_reviews') IS DISTINCT FROM 'array'
   OR jsonb_array_length(p->'ancestor_reviews') NOT BETWEEN 1 AND 64
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff
     WHERE ff.generation_artifact_id IN (artifact.id,lineage.parent_artifact_id))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr
     WHERE rr.generation_artifact_id IN (artifact.id,lineage.parent_artifact_id) AND rr.artifact_kind='admission_evaluation')
   OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe
     JOIN tutor_item_supply_shared_generation_artifacts aa ON aa.version_id=pe.version_id
     WHERE aa.id IN (artifact.id,lineage.parent_artifact_id)) THEN
   RAISE check_violation USING MESSAGE='recheck exact current lineage/source/profile operation required';
 END IF;
 IF p->'original_disputes' IS DISTINCT FROM (SELECT ir.payload_json->'disputes'
   FROM tutor_item_supply_shared_review_investigation_receipts ir
   WHERE ir.id=(revision_prep.payload_json->>'investigation_receipt_id')::uuid) THEN
   RAISE check_violation USING MESSAGE='recheck original issued dispute inventory must remain exact';
 END IF;
 WITH RECURSIVE history AS (
   SELECT ll.parent_artifact_id AS id FROM tutor_item_supply_shared_revision_lineage ll WHERE ll.id=lineage.id
   UNION SELECT ll.parent_artifact_id FROM tutor_item_supply_shared_revision_lineage ll JOIN history hh ON ll.child_artifact_id=hh.id
 ), bundles AS (
   SELECT rr.id,rr.receipt_hash,rr.payload_json FROM tutor_item_supply_shared_pipeline_receipts rr
   JOIN history hh ON hh.id=rr.generation_artifact_id WHERE rr.artifact_kind='review_bundle'
 ), runs AS (
   SELECT bb.payload_json->'blind_solve'->'run'->>'run_id' AS run_id FROM bundles bb
   UNION SELECT pp->'run'->>'run_id' FROM bundles bb CROSS JOIN LATERAL jsonb_array_elements(bb.payload_json->'reports') pp
 ) SELECT (SELECT jsonb_agg(jsonb_build_object('receipt_id',bb.id::text,'receipt_hash',bb.receipt_hash) ORDER BY bb.id) FROM bundles bb),
   (SELECT jsonb_agg(rr.run_id ORDER BY rr.run_id) FROM runs rr),
   (SELECT max((bb.payload_json->>'bundle_version')::integer)+1 FROM bundles bb)
 INTO expected_ancestors,expected_run_ids,expected_version;
 IF expected_ancestors IS NULL OR p->'ancestor_reviews' IS DISTINCT FROM expected_ancestors
   OR p->'forbidden_run_ids' IS DISTINCT FROM expected_run_ids OR (p->>'bundle_version')::integer IS DISTINCT FROM expected_version THEN
   RAISE check_violation USING MESSAGE='recheck complete ancestral identities cannot be dropped';
 END IF;
 -- Original process issuers recheck CURRENT RAG authority at each transaction.
 -- These immutable source hashes/declared retained bounds cannot renew a grant.
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id
   AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=artifact.artifact_hash)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(revision_prep.payload_json->'source_deadlines') sd
     WHERE (sd->>'retained_until')::timestamptz<=stamp) THEN
   RAISE check_violation USING MESSAGE='recheck current committed generation/source required';
 END IF;
 FOR historical IN SELECT value FROM jsonb_array_elements(p->'ancestor_reviews') LOOP
   IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=(historical->>'receipt_id')::uuid
     AND rr.artifact_kind='review_bundle' AND rr.receipt_hash=historical->>'receipt_hash'
     AND rr.xmin::text::bigint<>(txid_current()%4294967296)
     AND (rr.payload_json->>'bundle_version')::integer<(p->>'bundle_version')::integer) THEN
     RAISE check_violation USING MESSAGE='recheck committed ancestral review/version missing';
   END IF;
 END LOOP;
 IF TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_preparations' THEN
   IF NEW.valid_until IS DISTINCT FROM revision_prep.valid_until OR NEW.lineage_id IS DISTINCT FROM lineage.id
     OR p->>'preparation_id' IS DISTINCT FROM NEW.id::text
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='validating' AND cp.status='completed') THEN
     RAISE check_violation USING MESSAGE='recheck preparation must precede full new validation';
   END IF;
 ELSE
   SELECT * INTO validation_row FROM tutor_item_supply_shared_pipeline_receipts vr WHERE vr.id=NEW.validation_receipt_id FOR SHARE;
   SELECT * INTO blind_row FROM tutor_item_supply_shared_pipeline_receipts br WHERE br.id=NEW.blind_receipt_id FOR SHARE;
   SELECT * INTO review_row FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id FOR SHARE;
   IF (receipt - ARRAY['schema_version','preparation_id','preparation_hash','lease','artifact_id','lineage_hash','validation_receipt_id','blind_receipt_id','review_receipt_id','review_hash','entries','new_material_disputes','finite_unique_property_hash','publication_enabled','admission_eligible','blockers_discharged']) <> '{}'::jsonb
     OR jsonb_typeof(receipt->'entries') IS DISTINCT FROM 'array'
     OR jsonb_typeof(receipt->'new_material_disputes') IS DISTINCT FROM 'array'
     OR NOT (receipt ? 'finite_unique_property_hash') THEN
     RAISE check_violation USING MESSAGE='recheck closed typed receipt required';
   END IF;
   IF validation_row.id IS NULL OR blind_row.id IS NULL OR review_row.id IS NULL
     OR validation_row.artifact_kind IS DISTINCT FROM 'validation' OR blind_row.artifact_kind IS DISTINCT FROM 'blind_solve'
     OR review_row.artifact_kind IS DISTINCT FROM 'review_bundle'
     OR validation_row.job_id IS DISTINCT FROM NEW.job_id OR blind_row.job_id IS DISTINCT FROM NEW.job_id OR review_row.job_id IS DISTINCT FROM NEW.job_id
     OR validation_row.generation_artifact_id IS DISTINCT FROM artifact.id OR blind_row.generation_artifact_id IS DISTINCT FROM artifact.id
     OR review_row.generation_artifact_id IS DISTINCT FROM artifact.id
     OR validation_row.source_hash IS DISTINCT FROM artifact.source_hash OR review_row.source_hash IS DISTINCT FROM artifact.source_hash
     OR validation_row.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
     OR review_row.payload_json->'blind_solve' IS DISTINCT FROM blind_row.payload_json
     OR review_row.payload_json->>'state' IS DISTINCT FROM 'completed'
     OR review_row.payload_json->>'bundle_version' IS DISTINCT FROM p->>'bundle_version'
     OR review_row.payload_json->'binding'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id IN (NEW.validation_receipt_id,NEW.blind_receipt_id,NEW.review_receipt_id)
       AND rr.xmin::text::bigint=(txid_current()%4294967296))
     OR receipt->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text OR receipt->>'preparation_hash' IS DISTINCT FROM prep.snapshot_hash
     OR receipt->>'artifact_id' IS DISTINCT FROM artifact.id::text OR receipt->>'lineage_hash' IS DISTINCT FROM lineage.snapshot_hash
     OR receipt->>'review_hash' IS DISTINCT FROM review_row.receipt_hash
     OR receipt->'new_material_disputes' IS DISTINCT FROM item_supply_internal.revision_recheck_disputes(review_row.payload_json)
     OR validation_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR blind_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR review_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR validation_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR blind_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR review_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR receipt->>'validation_receipt_id' IS DISTINCT FROM NEW.validation_receipt_id::text
     OR receipt->>'blind_receipt_id' IS DISTINCT FROM NEW.blind_receipt_id::text OR receipt->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
     OR receipt->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR receipt->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
     OR receipt->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
     OR jsonb_array_length(receipt->'entries') IS DISTINCT FROM jsonb_array_length(p->'original_disputes') THEN
     RAISE check_violation USING MESSAGE='recheck original committed new validation/blind/six receipts required';
   END IF;
   SELECT array_agg(rr->>'role' ORDER BY rr->>'role') INTO roles FROM jsonb_array_elements(review_row.payload_json->'reports') rr;
   IF roles IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[] THEN
     RAISE check_violation USING MESSAGE='recheck all six peer-blind roles required';
   END IF;
   FOR provider_run IN SELECT blind_row.payload_json->'run' UNION ALL
     SELECT rr->'run' FROM jsonb_array_elements(review_row.payload_json->'reports') rr LOOP
     IF provider_run->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
       OR provider_run->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
       OR p->'forbidden_run_ids' @> jsonb_build_array(provider_run->>'run_id') THEN
       RAISE check_violation USING MESSAGE='recheck formal output/profile or ancestor run reuse mismatch';
     END IF;
   END LOOP;
   SELECT * INTO reservation_row FROM tutor_item_supply_shared_reservations rs WHERE rs.job_id=NEW.job_id
     AND rs.reservation_key='review.'||replace(artifact.id::text,'-','');
   SELECT * INTO usage_row FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.reservation_id=reservation_row.id
     AND ss.settlement_key=reservation_row.reservation_key;
   IF reservation_row.id IS NULL OR reservation_row.root_id IS DISTINCT FROM NEW.root_id OR reservation_row.requests<>7
     OR reservation_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
       WHERE ra.reservation_namespace='shared' AND ra.reservation_id=reservation_row.id
         AND ra.resource_kind='output_tokens' AND ra.reserved_amount=430080)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
       WHERE ra.reservation_namespace='shared' AND ra.reservation_id=reservation_row.id
         AND ra.resource_kind='output_tokens' AND ra.reserved_amount<>430080)
     OR usage_row.id IS NULL OR usage_row.usage_state IS DISTINCT FROM 'unknown'
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=usage_row.id AND ss.xmin::text::bigint=(txid_current()%4294967296)) THEN
     RAISE check_violation USING MESSAGE='recheck committed independent UNKNOWN review allocation required';
   END IF;
   SELECT * INTO validation_prep FROM tutor_item_supply_shared_validation_preparations vv
     WHERE vv.job_id=NEW.job_id AND vv.generation_artifact_id=artifact.id AND vv.lease_generation=control_row.lease_generation;
   property_facts:=validation_prep.payload_json->'inputs'->'static_facts';
   expected_property:=NULL;
   IF property_facts->>'schema_version'='finite_kc_validation_facts_v1'
     AND property_facts->>'source_hash'=artifact.source_hash AND property_facts->'validation'=validation_row.payload_json
     AND (SELECT count(*) FROM jsonb_array_elements(property_facts->'options') oo WHERE oo->'accepted'='true'::jsonb)=1
     AND artifact.source_json->'private'->'content'->'accepted_answers'=jsonb_build_array(property_facts->>'correct_option_id') THEN
     expected_property:=item_supply_internal.snapshot_hash(jsonb_build_object('check','finite_kc_unique_truth_v1',
       'source_hash',artifact.source_hash,'static_facts_hash',item_supply_internal.snapshot_hash(property_facts),
       'scorer_version',property_facts->>'scorer_version','validation_hash',validation_row.receipt_hash));
   END IF;
   IF receipt->'finite_unique_property_hash' IS DISTINCT FROM COALESCE(to_jsonb(expected_property),'null'::jsonb) THEN
     RAISE check_violation USING MESSAGE='recheck exact finite property projection required';
   END IF;
   FOR old_dispute IN SELECT value FROM jsonb_array_elements(p->'original_disputes') LOOP
     IF (SELECT count(*) FROM jsonb_array_elements(receipt->'entries') ee WHERE ee->'original_dispute'=old_dispute)<>1 THEN
       RAISE check_violation USING MESSAGE='recheck every old finding/field identity must remain';
     END IF;
   END LOOP;
   FOR entry IN SELECT value FROM jsonb_array_elements(receipt->'entries') LOOP
     IF jsonb_typeof(entry) IS DISTINCT FROM 'object'
       OR (entry - ARRAY['original_dispute','new_binding','validation_receipt_id','validation_hash','review_receipt_id','review_hash','state','supported_check','issuer_evidence_hash','safe_reason','historical_finding_resolved','publication_enabled']) <> '{}'::jsonb
       OR COALESCE(entry->>'state','') NOT IN ('check_supported','unsupported','unresolved')
       OR entry->>'safe_reason' IS DISTINCT FROM (CASE entry->>'state'
         WHEN 'check_supported' THEN 'finite_property_only_not_claim_resolution'
         WHEN 'unsupported' THEN 'no_clause_specific_adapter' WHEN 'unresolved' THEN 'new_material_dispute_retained' END)
       OR ((entry->>'state'='unresolved') IS DISTINCT FROM EXISTS(
         SELECT 1 FROM jsonb_array_elements(receipt->'new_material_disputes') dd
         WHERE dd->>'safe_code'=entry->'original_dispute'->>'safe_code'))
       OR entry->'new_binding' IS DISTINCT FROM review_row.payload_json->'binding'
       OR entry->>'validation_hash' IS DISTINCT FROM validation_row.receipt_hash OR entry->>'review_hash' IS DISTINCT FROM review_row.receipt_hash
       OR entry->>'validation_receipt_id' IS DISTINCT FROM NEW.validation_receipt_id::text OR entry->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
       OR entry->'historical_finding_resolved' IS DISTINCT FROM 'false'::jsonb OR entry->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN
       RAISE check_violation USING MESSAGE='recheck bounded non-authoritative clause data required';
     END IF;
     IF entry->>'state'='check_supported' AND (expected_property IS NULL
       OR entry->>'supported_check' IS DISTINCT FROM 'finite_kc_unique_truth_v1'
       OR entry->>'issuer_evidence_hash' IS DISTINCT FROM expected_property
       OR entry->'original_dispute'->>'safe_code' IS DISTINCT FROM 'unique_answer'
       OR entry->>'safe_reason' IS DISTINCT FROM 'finite_property_only_not_claim_resolution'
       OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(entry->'original_dispute'->'references') rf
         WHERE rf->>'pointer' LIKE '/source/public/content/options%')
       OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(entry->'original_dispute'->'references') rf
         WHERE rf->>'pointer' LIKE '/source/private/content/accepted_answers%')) THEN
       RAISE check_violation USING MESSAGE='recheck concrete finite unique-property issuer required';
     END IF;
     IF entry->>'state'<>'check_supported' AND (entry->'supported_check' IS DISTINCT FROM 'null'::jsonb OR entry->'issuer_evidence_hash' IS DISTINCT FROM 'null'::jsonb) THEN
       RAISE check_violation USING MESSAGE='unsupported historical finding cannot acquire proof';
     END IF;
   END LOOP;
 END IF;
 IF clock_timestamp()>=LEAST(revision_prep.valid_until,control_row.lease_expires_at,control_row.parent_deadline,
   (snapshot->>'parent_deadline_at')::timestamptz,
   (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) THEN
   RAISE check_violation USING MESSAGE='recheck final current deadline reached';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_revision_recheck_insert() FROM PUBLIC;
DO $$ DECLARE table_name text; BEGIN
 FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_revision_recheck_preparations','tutor_item_supply_shared_revision_recheck_receipts'] LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS revision_recheck_insert ON %I',table_name);
   EXECUTE format('CREATE TRIGGER revision_recheck_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_revision_recheck_insert()',table_name);
   EXECUTE format('DROP TRIGGER IF EXISTS revision_recheck_immutable ON %I',table_name);
   EXECUTE format('CREATE TRIGGER revision_recheck_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''shared'')',table_name);
 END LOOP;
END $$;
