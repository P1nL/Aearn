-- Exact approved M03 P2 normal follow-up; original SQL <=586 stays immutable.
-- One new original-owner operation, not restoration of its quarantined parent.
DO $scope587$ BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
  RAISE check_violation USING MESSAGE='587 M03 P2 isolated B1d only';
 END IF;
END $scope587$;

CREATE TABLE IF NOT EXISTS tutor_item_supply_m03_p2_normal_loop_grants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
 review_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
 facts_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_admission_facts(id) ON DELETE RESTRICT,
 continuation_job_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
 profile_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_parameter_profiles(id) ON DELETE RESTRICT,
 window_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_windows(id) ON DELETE RESTRICT,
 global_limit_ids uuid[] NOT NULL,
 valid_until timestamptz NOT NULL,
 resource_caps jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
COMMENT ON TABLE tutor_item_supply_m03_p2_normal_loop_grants IS
 'shared-confidential; one exact P2 follow-up authorization, immutable old review/facts DATA, not a renewed time window or historical discharge';
CREATE TABLE IF NOT EXISTS tutor_item_supply_m03_p2_loop_reservations (
 reservation_id uuid PRIMARY KEY REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
 grant_id uuid NOT NULL REFERENCES tutor_item_supply_m03_p2_normal_loop_grants(id) ON DELETE RESTRICT,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
COMMENT ON TABLE tutor_item_supply_m03_p2_loop_reservations IS
 'shared-confidential; original reservation links for exact approved supplement, never refund old UNKNOWN or held160';

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_m03_p2_loop_grant() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $grant587$
DECLARE a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 f tutor_item_supply_shared_admission_facts%ROWTYPE;
 r tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 c tutor_item_supply_shared_job_controls%ROWTYPE;
 b tutor_item_supply_shared_candidate_continuations%ROWTYPE;
 w tutor_item_supply_shared_budget_windows%ROWTYPE;
 p tutor_item_supply_parameter_profiles%ROWTYPE;
 oldp tutor_item_supply_parameter_profiles%ROWTYPE;
 s jsonb; v jsonb; expected uuid[]; stamp timestamptz:=clock_timestamp();
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_read_only')<>'off'
  OR NEW.root_id<>'22b8953f-3177-4cfd-936f-cc77060665ee'
  OR NEW.artifact_id<>'3e766df2-a5e2-41d0-ba69-03a3084e9738'
  OR NEW.review_receipt_id<>'6d60254c-c6cf-4dc5-8212-7aa9644331dc'
  OR NEW.facts_receipt_id<>'0e70534a-5865-4631-b8f3-4ca24fb47dc1' THEN
  RAISE check_violation USING MESSAGE='587 exact human approved P2 scope required';
 END IF;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.artifact_id FOR SHARE;
 SELECT * INTO f FROM tutor_item_supply_shared_admission_facts WHERE id=NEW.facts_receipt_id FOR SHARE;
 SELECT * INTO r FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.review_receipt_id FOR SHARE;
 SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.continuation_job_id FOR UPDATE;
 SELECT * INTO b FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=NEW.continuation_job_id FOR SHARE;
 SELECT * INTO w FROM tutor_item_supply_shared_budget_windows WHERE id=NEW.window_id FOR UPDATE;
 SELECT * INTO p FROM tutor_item_supply_parameter_profiles WHERE id=NEW.profile_id FOR SHARE;
 SELECT * INTO oldp FROM tutor_item_supply_parameter_profiles WHERE id='a3e3423e-9df7-4919-bd49-ab6c49e8de1c' FOR SHARE;
 s:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 v:=s->'values';
 SELECT array_agg(g.id ORDER BY g.id) INTO expected FROM tutor_item_supply_runtime_global_limits g
  WHERE g.window_start='2026-10-21 00:13:13.229525+08' AND g.window_end='2026-10-22 00:13:13.229525+08';
 stamp:=clock_timestamp();
 IF a.id IS NULL OR f.id IS NULL OR r.id IS NULL OR c.id IS NULL OR b.job_id IS NULL OR w.id IS NULL OR p.id IS NULL OR oldp.id IS NULL
  OR a.root_id<>NEW.root_id OR f.generation_artifact_id<>a.id OR r.generation_artifact_id<>a.id
  OR f.payload_json->'evaluation'->>'disposition' IS DISTINCT FROM 'quarantine'
  OR f.payload_json->'evaluation'->'safe_reasons' IS DISTINCT FROM '["material_review_failure"]'::jsonb
  OR f.payload_json->>'review_receipt_id' IS DISTINCT FROM r.id::text
  OR r.artifact_kind<>'review_bundle' OR r.mode<>'live' OR r.job_id<>'70a82688-dc2c-4840-a60a-0a7b70fa801e'
  OR (SELECT count(*) FROM jsonb_array_elements(r.payload_json->'reports') e WHERE e->>'role'='adversarial'
    AND e->>'verdict'='changes_required' AND jsonb_array_length(e->'findings')=1
    AND e->'findings'->0->>'safe_code'='adversarial_exploit' AND e->'findings'->0->>'severity'='major'
    AND e->'findings'->0->'blocking'='true'::jsonb)<>1
  OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
  OR item_supply_internal.controlled_counterexample_held(NEW.continuation_job_id) IS DISTINCT FROM false
  OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events WHERE version_id=a.version_id)
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE id='28a1355b-f2ab-4d4b-97f3-6197974b44c9' AND root_id=NEW.root_id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id='28a1355b-f2ab-4d4b-97f3-6197974b44c9')
  OR b.root_id<>NEW.root_id OR b.generation_artifact_id<>a.id
  OR b.operation_key<>'m03.p2.normal-loop.0e70534a58654631b8f34ca24fb47dc1'
  OR c.profile_id<>NEW.profile_id OR c.state<>'leased' OR c.lease_generation<>1
  OR c.lease_expires_at IS NULL OR c.lease_expires_at<=stamp OR c.parent_deadline<=stamp
  OR NEW.continuation_job_id=r.job_id OR NEW.profile_id=oldp.id
  OR p.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR p.profile_key_hash IS DISTINCT FROM oldp.profile_key_hash
  OR s->>'profile_hash' IS DISTINCT FROM p.profile_hash
  OR p.profile_json->'initial' IS DISTINCT FROM v
  OR (p.profile_json->>'version')::integer IS DISTINCT FROM 3
  OR (p.profile_json->>'parent_version')::integer IS DISTINCT FROM (oldp.profile_json->>'version')::integer
  OR p.profile_json->'current' IS DISTINCT FROM v OR p.profile_json->'last_stable' IS DISTINCT FROM v
  OR p.profile_json->'floor' IS DISTINCT FROM v OR p.profile_json->'ceiling' IS DISTINCT FROM v
  OR COALESCE((v->>'discussion_rounds')::integer=2 AND (v->>'revision_rounds')::integer=1
    AND (v->>'investigation_rounds')::integer=1 AND (v->>'request_timeout_ms')::bigint<=100000
    AND (v->>'parent_deadline_ms')::bigint<=3600000 AND (v->>'stage_deadline_ms')::bigint<=3600000,false) IS DISTINCT FROM true
  OR w.root_id<>NEW.root_id OR w.window_start<>'2026-10-21 00:13:13.229525+08'
  OR w.window_end<>'2026-10-22 00:13:13.229525+08'
  OR cardinality(expected)<>32 OR NEW.global_limit_ids IS DISTINCT FROM expected
  OR NEW.resource_caps IS DISTINCT FROM '{"requests":9,"input_tokens":2228224,"output_tokens":552960,"execution_seconds":190,"fetches":0,"candidates":1,"revision_rounds":1,"investigation_rounds":1}'::jsonb
  OR NEW.valid_until<=stamp OR NEW.valid_until>LEAST(w.window_end,c.lease_expires_at,c.parent_deadline,(s->>'parent_deadline_at')::timestamptz)
  OR NEW.created_at>stamp OR NEW.created_at<stamp-interval '5 minutes'
 THEN RAISE check_violation USING MESSAGE='587 exact immutable P2 history/new control/profile/original window required'; END IF;
 RETURN NEW;
END $grant587$;

CREATE OR REPLACE FUNCTION item_supply_internal.m03_p2_normal_loop_for_job(job uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $lookup587$
DECLARE g tutor_item_supply_m03_p2_normal_loop_grants%ROWTYPE; c record; s jsonb; stamp timestamptz;
BEGIN
 SELECT x.* INTO g FROM tutor_item_supply_m03_p2_normal_loop_grants x
  WHERE x.continuation_job_id=job OR EXISTS(
   SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp
   JOIN tutor_item_supply_shared_review_investigation_receipts ir ON ir.id=rp.investigation_receipt_id
   JOIN tutor_item_supply_shared_jobs j ON j.id=rp.child_job_id
   WHERE rp.child_job_id=job AND rp.parent_job_id=x.continuation_job_id AND rp.parent_artifact_id=x.artifact_id
    AND ir.job_id=x.continuation_job_id AND ir.review_receipt_id=x.review_receipt_id
    AND j.parent_job_id=x.continuation_job_id AND j.root_id=x.root_id);
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=job;
 s:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 stamp:=clock_timestamp();
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR c.job_id IS NULL OR c.profile_id<>g.profile_id
  OR c.state<>'leased' OR c.lease_expires_at IS NULL OR c.lease_expires_at<=stamp OR c.parent_deadline<=stamp
  OR g.valid_until<=stamp OR c.parent_deadline>g.valid_until
  OR item_supply_internal.controlled_counterexample_held(job) IS DISTINCT FROM false
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_budget_windows w WHERE w.id=g.window_id AND w.root_id=g.root_id
    AND w.window_start<=stamp AND w.window_end>stamp AND g.valid_until<=w.window_end)
 THEN RAISE check_violation USING MESSAGE='587 current exact P2 loop operation required'; END IF;
 RETURN to_jsonb(g);
END $lookup587$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_m03_p2_loop_reservation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $reserve587$
DECLARE r tutor_item_supply_shared_reservations%ROWTYPE; g tutor_item_supply_m03_p2_normal_loop_grants%ROWTYPE;
 frame jsonb; ids uuid[]; kind text; total bigint; current_amount bigint;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id FOR SHARE;
 SELECT * INTO g FROM tutor_item_supply_m03_p2_normal_loop_grants WHERE id=NEW.grant_id FOR UPDATE;
 IF r.id IS NULL OR g.id IS NULL THEN RAISE check_violation USING MESSAGE='587 original reservation/grant missing'; END IF;
 frame:=item_supply_internal.m03_p2_normal_loop_for_job(r.job_id);
 SELECT array_agg(DISTINCT a.limit_id ORDER BY a.limit_id) INTO ids
  FROM tutor_item_supply_runtime_global_reservation_amounts a WHERE a.reservation_namespace='shared' AND a.reservation_id=r.id;
 IF frame IS NULL OR frame->>'id'<>g.id::text OR r.root_id<>g.root_id OR r.window_id<>g.window_id
  OR ids IS DISTINCT FROM g.global_limit_ids
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_job_controls c WHERE c.job_id=r.job_id
    AND c.state='leased' AND c.profile_id=g.profile_id AND c.lease_generation=r.lease_generation
    AND c.lease_expires_at>clock_timestamp() AND c.parent_deadline>clock_timestamp())
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations x WHERE x.id=r.id
    AND x.xmin::text::bigint=(txid_current()%4294967296))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts a
    JOIN tutor_item_supply_runtime_global_limits lim ON lim.id=a.limit_id
    WHERE a.reservation_namespace='shared' AND a.reservation_id=r.id AND a.resource_kind<>lim.resource_kind)
  OR (SELECT count(*) FROM tutor_item_supply_runtime_global_reservation_amounts a WHERE a.reservation_namespace='shared' AND a.reservation_id=r.id)<>32
 THEN RAISE check_violation USING MESSAGE='587 exact original mixed reservation scope required'; END IF;
 FOR kind IN SELECT jsonb_object_keys(g.resource_caps) LOOP
  SELECT min(a.reserved_amount) INTO current_amount FROM tutor_item_supply_runtime_global_reservation_amounts a
   WHERE a.reservation_namespace='shared' AND a.reservation_id=r.id AND a.resource_kind=kind;
  IF current_amount IS NULL OR (SELECT count(DISTINCT a.reserved_amount) FROM tutor_item_supply_runtime_global_reservation_amounts a
    WHERE a.reservation_namespace='shared' AND a.reservation_id=r.id AND a.resource_kind=kind)<>1 THEN
   RAISE check_violation USING MESSAGE='587 exact full resource dimensions required';
  END IF;
  SELECT COALESCE(sum(z.reserved_amount),0) INTO total FROM (
   SELECT DISTINCT a.reservation_id,a.reserved_amount FROM tutor_item_supply_m03_p2_loop_reservations l
    JOIN tutor_item_supply_runtime_global_reservation_amounts a ON a.reservation_namespace='shared' AND a.reservation_id=l.reservation_id
    WHERE l.grant_id=g.id AND a.resource_kind=kind) z;
  IF total+current_amount>(g.resource_caps->>kind)::bigint THEN
   RAISE check_violation USING MESSAGE='587 bounded P2 supplement exhausted';
  END IF;
 END LOOP;
 RETURN NEW;
END $reserve587$;

DO $triggers587$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='tutor_item_supply_m03_p2_normal_loop_grants'::regclass AND tgname='m03_p2_loop_grant_insert') THEN
  CREATE TRIGGER m03_p2_loop_grant_insert BEFORE INSERT ON tutor_item_supply_m03_p2_normal_loop_grants
   FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_m03_p2_loop_grant();
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='tutor_item_supply_m03_p2_loop_reservations'::regclass AND tgname='m03_p2_loop_reservation_insert') THEN
  CREATE TRIGGER m03_p2_loop_reservation_insert BEFORE INSERT ON tutor_item_supply_m03_p2_loop_reservations
   FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_m03_p2_loop_reservation();
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='tutor_item_supply_m03_p2_normal_loop_grants'::regclass AND tgname='m03_p2_loop_grant_immutable') THEN
  CREATE TRIGGER m03_p2_loop_grant_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_m03_p2_normal_loop_grants
   FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='tutor_item_supply_m03_p2_loop_reservations'::regclass AND tgname='m03_p2_loop_reservation_immutable') THEN
  CREATE TRIGGER m03_p2_loop_reservation_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_m03_p2_loop_reservations
   FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
 END IF;
END $triggers587$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_m03_p2_loop_grant() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.m03_p2_normal_loop_for_job(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_m03_p2_loop_reservation() FROM PUBLIC;
-- Original quality receiver branches appended after exact Python payload contract review.
-- BEGIN GENERATED ORIGINAL QUALITY RECEIVERS 587

CREATE OR REPLACE FUNCTION item_supply_internal.assert_m03_p2_investigation(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $frame587$
DECLARE g jsonb; frame jsonb:=p->'m03_p2_frame'; expected jsonb;
 f tutor_item_supply_shared_admission_facts%ROWTYPE;
 rr tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 cb tutor_item_supply_shared_candidate_continuations%ROWTYPE;
 historical_cb tutor_item_supply_shared_candidate_continuations%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
BEGIN
 g:=item_supply_internal.m03_p2_normal_loop_for_job((p->'lease'->>'job_id')::uuid);
 IF g IS NULL OR p ? 'persistent_frame' OR g->>'continuation_job_id' IS DISTINCT FROM p->'lease'->>'job_id' THEN
  RAISE check_violation USING MESSAGE='587 exact concrete P2 parent continuation required'; END IF;
 SELECT * INTO f FROM tutor_item_supply_shared_admission_facts WHERE id=(g->>'facts_receipt_id')::uuid FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(g->>'review_receipt_id')::uuid FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(f.payload_json->>'blind_receipt_id')::uuid FOR SHARE;
 SELECT * INTO vr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(f.payload_json->>'validation_receipt_id')::uuid FOR SHARE;
 SELECT * INTO cb FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=(g->>'continuation_job_id')::uuid FOR SHARE;
 SELECT * INTO historical_cb FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=rr.job_id FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(g->>'artifact_id')::uuid FOR SHARE;
 expected:=jsonb_build_object('schema_version','m03_p2_committed_review_frame_v1','grant',g,
  'facts_receipt_id',f.id,'facts_hash',f.payload_hash,'review_receipt_id',rr.id,'review_hash',rr.receipt_hash,
  'blind_receipt_id',br.id,'blind_hash',br.receipt_hash,'validation_receipt_id',vr.id,'validation_hash',vr.receipt_hash,
  'original_review_job_id',rr.job_id,'original_lease_generation',rr.lease_generation,
  'original_review_reservation_id',f.payload_json->'review_budget'->>'reservation_id',
  'original_profile_hash',f.payload_json->>'profile_hash','continuation_binding_hash',cb.binding_hash,'execution_lease',p->'lease');
 IF f.id IS NULL OR rr.id IS NULL OR br.id IS NULL OR vr.id IS NULL OR cb.job_id IS NULL OR a.id IS NULL
  OR frame IS DISTINCT FROM expected
  OR p->>'root_id' IS DISTINCT FROM g->>'root_id' OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text
  OR p->>'review_receipt_id' IS DISTINCT FROM rr.id::text OR p->>'continuation_binding_hash' IS DISTINCT FROM cb.binding_hash
  OR p->>'original_review_reservation_id' IS DISTINCT FROM f.payload_json->'review_budget'->>'reservation_id'
  OR p->>'blind_receipt_id' IS DISTINCT FROM br.id::text OR p->>'validation_receipt_id' IS DISTINCT FROM vr.id::text
  OR f.generation_artifact_id<>a.id OR f.payload_json->'evaluation'->>'disposition' IS DISTINCT FROM 'quarantine'
  OR f.payload_json->'evaluation'->'safe_reasons' IS DISTINCT FROM '["material_review_failure"]'::jsonb
  OR rr.id<>'6d60254c-c6cf-4dc5-8212-7aa9644331dc' OR f.id<>'0e70534a-5865-4631-b8f3-4ca24fb47dc1'
  OR rr.job_id<>'70a82688-dc2c-4840-a60a-0a7b70fa801e'
  OR cb.generation_artifact_id<>a.id OR cb.root_id<>a.root_id OR a.root_id<>(g->>'root_id')::uuid
  OR cb.operation_key<>'m03.p2.normal-loop.0e70534a58654631b8f34ca24fb47dc1'
  OR historical_cb.job_id IS NULL OR historical_cb.binding_hash IS DISTINCT FROM rr.continuation_binding_hash
  OR historical_cb.generation_artifact_id IS DISTINCT FROM a.id OR historical_cb.root_id IS DISTINCT FROM a.root_id
  OR historical_cb.original_job_id IS DISTINCT FROM a.job_id OR historical_cb.original_lease_generation IS DISTINCT FROM a.lease_generation
  OR historical_cb.item_id IS DISTINCT FROM a.item_id OR historical_cb.version_id IS DISTINCT FROM a.version_id
  OR historical_cb.source_hash IS DISTINCT FROM a.source_hash OR historical_cb.content_hash IS DISTINCT FROM a.content_hash
  OR historical_cb.binding_json->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
  OR historical_cb.binding_json->>'original_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json)
  OR historical_cb.binding_json->'adoption_lease'->>'job_id' IS DISTINCT FROM rr.job_id::text
  OR historical_cb.binding_json->'adoption_lease'->>'generation' IS DISTINCT FROM rr.lease_generation::text
  OR historical_cb.binding_json->'adoption_lease'->'profile'->>'profile_hash' IS DISTINCT FROM f.payload_json->>'profile_hash'
  OR f.payload_json->>'continuation_binding_hash' IS DISTINCT FROM historical_cb.binding_hash
  OR item_supply_internal.controlled_counterexample_held(rr.job_id) IS DISTINCT FROM false
  OR item_supply_internal.shared_stage_original_matches(cb.job_id,(p->'lease'->>'generation')::integer,a.id,cb.binding_hash) IS DISTINCT FROM true
  OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts x WHERE x.generation_artifact_id=a.id AND x.id<>f.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts x WHERE x.generation_artifact_id=a.id AND x.artifact_kind='admission_evaluation')
  OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events x WHERE x.version_id=a.version_id)
  OR p->'request_payload'->>'schema_version' IS DISTINCT FROM 'native_shared_review_investigation_input_v1'
  OR p->'request_payload'->>'purpose' IS DISTINCT FROM 'live_dispute_investigation'
  OR p->'request_payload'->>'execution_profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
  OR p->'request_payload'->'review_input'->'binding' IS DISTINCT FROM rr.payload_json->'binding'
  OR p->'request_payload'->'review_input'->'binding'->>'profile_hash' IS DISTINCT FROM f.payload_json->>'profile_hash'
  OR p->'request_payload'->>'execution_profile_hash'=f.payload_json->>'profile_hash'
  OR jsonb_array_length(p->'request_payload'->'disputes') IS DISTINCT FROM 1
  OR p->'request_payload'->'disputes'->0->>'safe_code' IS DISTINCT FROM 'adversarial_exploit'
  OR p->'request_payload'->'review_input'->>'role' IS DISTINCT FROM 'technical'
  OR (p->>'deadline_at')::timestamptz>(g->>'valid_until')::timestamptz
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_m03_p2_loop_reservations l WHERE l.grant_id=(g->>'id')::uuid
    AND l.reservation_id=(p->>'reservation_id')::uuid)
 THEN RAISE check_violation USING MESSAGE='587 retained P2 review DATA/current execution closure required'; END IF;
END $frame587$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_m03_p2_investigation(jsonb) FROM PUBLIC;

DO $enforce_shared_review_investigation_insert_587$
DECLARE f record; body text := $source_enforce_shared_review_investigation_insert_587$
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
  quality_job uuid; quality_generation integer; quality_owner text; m03_permission boolean:=false;
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
  IF p ? 'm03_p2_frame' THEN
    PERFORM item_supply_internal.assert_m03_p2_investigation(p);
    m03_permission:=true;
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
  IF (NOT (persistent_permission OR m03_permission) AND (NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='validating' AND cp.status='completed')
    OR NOT (EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='generating' AND cp.status='completed')
      OR item_supply_internal.shared_continuation_generation_inherited(NEW.job_id))))
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id
      AND cp.stage IN ('investigating','revising','simulating','admitting') AND cp.status='completed') THEN
    RAISE check_violation USING MESSAGE='investigation original reviewing or investigating position required';
  END IF;
  SELECT * INTO artifact_row FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id FOR SHARE;
  SELECT * INTO review_row FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id FOR SHARE;
  quality_job:=CASE WHEN (persistent_permission OR m03_permission) THEN review_row.job_id ELSE NEW.job_id END;
  quality_generation:=CASE WHEN (persistent_permission OR m03_permission) THEN review_row.lease_generation ELSE NEW.lease_generation END;
  quality_owner:=CASE WHEN (persistent_permission OR m03_permission) THEN review_row.lease_owner ELSE NEW.lease_owner END;
  IF artifact_row.id IS NULL OR review_row.id IS NULL OR artifact_row.root_id<>NEW.root_id
    OR review_row.job_id<>quality_job OR review_row.lease_generation<>quality_generation
    OR review_row.lease_owner IS DISTINCT FROM quality_owner OR review_row.artifact_kind<>'review_bundle'
    OR review_row.mode<>'live' OR review_row.generation_artifact_id<>artifact_row.id
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id AND rr.xmin::text::bigint=(txid_current()%4294967296))
    OR (NOT m03_permission AND item_supply_internal.shared_stage_original_matches(quality_job,quality_generation,artifact_row.id,review_row.continuation_binding_hash) IS DISTINCT FROM true)
    OR (NOT (persistent_permission OR m03_permission) AND p->>'continuation_binding_hash' IS DISTINCT FROM review_row.continuation_binding_hash)
    OR review_row.source_hash IS DISTINCT FROM artifact_row.source_hash OR review_row.content_hash IS DISTINCT FROM artifact_row.content_hash
    OR (NOT (persistent_permission OR m03_permission) AND (EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=artifact_row.id)
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
    OR (CASE WHEN (persistent_permission OR m03_permission) THEN request_payload->>'execution_profile_hash' ELSE binding->>'profile_hash' END) IS DISTINCT FROM snapshot->>'profile_hash'
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
  IF m03_permission THEN PERFORM item_supply_internal.assert_m03_p2_investigation(p); END IF;
  RETURN NEW;
END $source_enforce_shared_review_investigation_insert_587$;
BEGIN
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()');
 IF NOT FOUND OR encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('4623fa4db4a521346d34be436d14c53e1444273ee4968011e879e53494245f41','01d080fcdc204f3d9b42ebe1262038072f17c5e1a8c265aee5c46be3cd4ffa84')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  OR f.proargnames IS NOT NULL OR f.prokind<>'f' OR f.proretset OR f.proisstrict
 THEN RAISE check_violation USING MESSAGE='587 unexpected original receiver: enforce_shared_review_investigation_insert'; END IF;
 EXECUTE 'CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_review_investigation_insert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS ' || quote_literal(body);
 SELECT p.* INTO f FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()');
 IF encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')<>'01d080fcdc204f3d9b42ebe1262038072f17c5e1a8c265aee5c46be3cd4ffa84' THEN
  RAISE check_violation USING MESSAGE='587 receiver replacement mismatch: enforce_shared_review_investigation_insert'; END IF;
END $enforce_shared_review_investigation_insert_587$;

DO $enforce_native_revision_insert_587$
DECLARE f record; body text := $source_enforce_native_revision_insert_587$
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
  m03_permission boolean:=false; persistent_permission boolean:=false; family_permission boolean:=false; fresh_permission boolean:=false; source_permission boolean:=false;
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
  fresh_permission:=item_supply_internal.fresh_committed_revision_matches(p);
  source_permission:=item_supply_internal.revision_source_successor_matches(p);
  IF source_permission AND NOT fresh_permission THEN RAISE check_violation USING MESSAGE='543 original fresh execution required'; END IF;
  -- New normal branch is closed by the SAME original investigation/phase receiver.
  IF investigation_prep.payload_json ? 'm03_p2_frame' THEN
    PERFORM item_supply_internal.assert_m03_p2_investigation(investigation_prep.payload_json);
    m03_permission:=true;
    IF TG_TABLE_NAME='tutor_item_supply_shared_revision_preparations' AND EXISTS(
      SELECT 1 FROM tutor_item_supply_shared_revision_preparations prior
       WHERE prior.parent_job_id=NEW.parent_job_id AND prior.id<>NEW.id) THEN
      RAISE check_violation USING MESSAGE='587 one original P2 revision child only';
    END IF;
  END IF;
  IF investigation_prep.payload_json ? 'persistent_frame' THEN
    IF item_supply_internal.controlled_counterexample_held(parent_artifact.job_id) IS DISTINCT FROM false
      OR item_supply_internal.controlled_counterexample_held(NEW.child_job_id) IS DISTINCT FROM false
    THEN RAISE check_violation USING MESSAGE='525 controlled ancestry denied first'; END IF;
    IF fresh_permission THEN
      IF item_supply_internal.fresh_committed_revision_matches(p) IS DISTINCT FROM true
      THEN RAISE check_violation USING MESSAGE='539 fresh revision authority changed'; END IF;
    ELSE
      PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);
    END IF;
    persistent_permission:=true;
    IF p->'context'->>'schema_version' IN('native_revision_author_context_v2','native_revision_author_context_v3') THEN
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
    OR (NOT fresh_permission AND investigation_row.job_id IS DISTINCT FROM parent_control.job_id)
    OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text OR p->>'parent_artifact_id' IS DISTINCT FROM NEW.parent_artifact_id::text
    OR p->'child_lease'->>'job_id' IS DISTINCT FROM NEW.child_job_id::text
    OR jsonb_typeof(context_payload) IS DISTINCT FROM 'object' OR jsonb_typeof(request_payload) IS DISTINCT FROM 'object'
    OR jsonb_typeof(context_payload->'problems') IS DISTINCT FROM 'array'
    OR jsonb_typeof(snapshot->'values') IS DISTINCT FROM 'object'
    OR (NOT source_permission AND p->'source_deadlines' IS DISTINCT FROM investigation_prep.payload_json->'source_deadlines')
    OR child_job.parent_job_id IS DISTINCT FROM parent_control.job_id OR child_job.id=parent_control.job_id
    OR investigation_row.snapshot_hash IS DISTINCT FROM p->>'investigation_receipt_hash'
    OR investigation_row.payload_json->>'safe_reason' IS DISTINCT FROM 'investigation_analysis_pending_revision_owner'
    OR jsonb_typeof(investigation_row.payload_json->'report') IS DISTINCT FROM 'object'
    OR (NOT fresh_permission AND (investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp))
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
    OR (NOT fresh_permission AND p->'parent_lease' IS DISTINCT FROM investigation_prep.payload_json->'lease')
    OR snapshot IS DISTINCT FROM p->'child_lease'->'profile' OR request_payload->'profile' IS DISTINCT FROM snapshot
    OR snapshot->>'profile_hash' IS DISTINCT FROM p->'parent_lease'->'profile'->>'profile_hash'
    OR snapshot->'values' IS DISTINCT FROM p->'parent_lease'->'profile'->'values'
    OR (snapshot->'values'->>'discussion_rounds')::integer<2 OR (snapshot->'values'->>'revision_rounds')::integer<1
    OR p->'child_lease'->>'visibility' IS DISTINCT FROM 'public'
    OR p->'child_lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'child_lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR (p->>'deadline_at')::timestamptz<=stamp OR (p->>'deadline_at')::timestamptz>LEAST(
      CASE WHEN fresh_permission THEN parent_control.lease_expires_at ELSE investigation_row.valid_until END,
      CASE WHEN fresh_permission THEN parent_control.lease_expires_at ELSE investigation_prep.valid_until END,parent_control.lease_expires_at,child_control.lease_expires_at,child_control.parent_deadline,
      (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'))
    OR (NOT (persistent_permission OR m03_permission) AND (EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=parent_artifact.id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.generation_artifact_id=parent_artifact.id AND rr.artifact_kind='admission_evaluation')
    OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe WHERE pe.version_id=parent_artifact.version_id))) THEN
    RAISE check_violation USING MESSAGE='revision current original investigation/child/source/history required';
  END IF;
  IF context_payload->>'schema_version' IS DISTINCT FROM (CASE WHEN family_permission AND source_permission THEN 'native_revision_author_context_v3'
      WHEN family_permission THEN 'native_revision_author_context_v2' ELSE 'native_revision_author_context_v1' END)
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
    OR (NOT source_permission AND request_payload->'materials' IS DISTINCT FROM parent_artifact.request_json->'materials')
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
    IF NEW.investigation_receipt_id='87596016-7639-4ed9-8f05-684b7bf8027c' AND NEW.id<>'c8593cb3-2360-48c0-a7f8-a3a69c930184' THEN
      IF fresh_permission IS DISTINCT FROM true OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal e
       WHERE e.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND e.record_kind='committed_revision_execution'
        AND e.operation_key='p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution.successor.1'
        AND e.payload_json->>'authorization_sha256'='68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243'
        AND e.payload_json->>'execution_job_id'=NEW.parent_job_id::text)
      THEN RAISE check_violation USING MESSAGE='542 registered successor preparation required'; END IF;
    END IF;
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
    IF fresh_permission THEN
      IF item_supply_internal.fresh_committed_revision_matches(p) IS DISTINCT FROM true
      THEN RAISE check_violation USING MESSAGE='539 fresh revision authority changed'; END IF;
    ELSE
      PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);
    END IF;
    stamp:=clock_timestamp();
    IF (p->>'deadline_at')::timestamptz<=stamp OR (NOT fresh_permission AND (investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp))
      OR parent_control.lease_expires_at<=stamp OR parent_control.parent_deadline<=stamp
      OR child_control.lease_expires_at<=stamp OR child_control.parent_deadline<=stamp
    THEN RAISE check_violation USING MESSAGE='525 final acceptance deadline expired'; END IF;
  END IF;
  RETURN NEW;
END $source_enforce_native_revision_insert_587$;
BEGIN
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()');
 IF NOT FOUND OR encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('b11320c5f781e34f0b962e73b3d91ea313502fd6cd0da30acb84a0d3d20dfbe5','62b65bb789737a33b41308a2fae2bc9137f6f3a820b03e8cf743dcfb98f53386')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  OR f.proargnames IS NOT NULL OR f.prokind<>'f' OR f.proretset OR f.proisstrict
 THEN RAISE check_violation USING MESSAGE='587 unexpected original receiver: enforce_native_revision_insert'; END IF;
 EXECUTE 'CREATE OR REPLACE FUNCTION item_supply_internal.enforce_native_revision_insert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS ' || quote_literal(body);
 SELECT p.* INTO f FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()');
 IF encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')<>'62b65bb789737a33b41308a2fae2bc9137f6f3a820b03e8cf743dcfb98f53386' THEN
  RAISE check_violation USING MESSAGE='587 receiver replacement mismatch: enforce_native_revision_insert'; END IF;
END $enforce_native_revision_insert_587$;

DO $enforce_revision_recheck_insert_587$
DECLARE f record; body text := $source_enforce_revision_recheck_insert_587$
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
 committed boolean:=false; m03_permission boolean:=false; m03_grant jsonb;
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
 committed:=p->>'schema_version'='native_shared_revision_recheck_preparation_v2';
 IF committed THEN
   PERFORM item_supply_internal.assert_committed_child_recheck(p->'committed_child',lease);
   IF p->>'deadline_at' IS DISTINCT FROM p->'committed_child'->>'deadline_at'
     OR (TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_receipts'
       AND receipt->>'schema_version' IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v2')
   THEN RAISE check_violation USING MESSAGE='546 explicit v2 committed recheck wire required'; END IF;
 ELSE
   IF p->>'schema_version' IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v1'
     OR (TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_receipts'
       AND receipt->>'schema_version' IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v1')
   THEN RAISE check_violation USING MESSAGE='546 original v1 recheck wire required'; END IF;
 END IF;
 SELECT * INTO lineage FROM tutor_item_supply_shared_revision_lineage ll WHERE ll.id=(p->>'lineage_id')::uuid FOR SHARE;
 SELECT * INTO revision_prep FROM tutor_item_supply_shared_revision_preparations rr WHERE rr.id=lineage.preparation_id FOR SHARE;
 SELECT * INTO artifact FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id FOR SHARE;
 SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR UPDATE;
 m03_grant:=item_supply_internal.m03_p2_normal_loop_for_job(NEW.job_id);
 IF m03_grant IS NOT NULL THEN
  IF committed OR lineage.parent_artifact_id IS DISTINCT FROM (m03_grant->>'artifact_id')::uuid
   OR revision_prep.parent_job_id IS DISTINCT FROM (m03_grant->>'continuation_job_id')::uuid
   OR lineage.child_job_id IS DISTINCT FROM NEW.job_id THEN
   RAISE check_violation USING MESSAGE='587 exact original P2 recheck lineage required'; END IF;
  m03_permission:=true;
 END IF;
 stamp:=clock_timestamp();
 snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 IF (p - ARRAY['schema_version','preparation_id','lineage_id','lineage_hash','root_id','lease','artifact_id','artifact_hash','context_hash','original_disputes','ancestor_reviews','forbidden_run_ids','bundle_version','deadline_at','publication_enabled','blockers_discharged'] - (CASE WHEN committed THEN ARRAY['committed_child'] ELSE ARRAY[]::text[] END)) <> '{}'::jsonb
   OR jsonb_typeof(p->'bundle_version') IS DISTINCT FROM 'number'
   OR jsonb_typeof(lease) IS DISTINCT FROM 'object' THEN
   RAISE check_violation USING MESSAGE='recheck closed typed preparation required';
 END IF;
 IF lineage.id IS NULL OR revision_prep.id IS NULL OR artifact.id IS NULL OR control_row.id IS NULL
   OR lineage.root_id IS DISTINCT FROM NEW.root_id OR lineage.child_artifact_id IS DISTINCT FROM artifact.id
   OR lineage.child_job_id IS DISTINCT FROM artifact.job_id
   OR (NOT committed AND artifact.job_id IS DISTINCT FROM NEW.job_id)
   OR artifact.root_id IS DISTINCT FROM NEW.root_id OR lineage.snapshot_hash IS DISTINCT FROM p->>'lineage_hash'
   OR artifact.artifact_hash IS DISTINCT FROM p->>'artifact_hash' OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text
   OR p->>'artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
   OR p->>'context_hash' IS DISTINCT FROM revision_prep.payload_json->>'context_hash'
   OR (NOT committed AND ((p->>'deadline_at')::timestamptz IS DISTINCT FROM revision_prep.valid_until
     OR revision_prep.valid_until<=stamp)) OR control_row.state IS DISTINCT FROM 'leased'
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
     WHERE ff.generation_artifact_id=artifact.id OR (NOT committed AND ff.generation_artifact_id=lineage.parent_artifact_id
       AND (NOT m03_permission OR ff.id IS DISTINCT FROM (m03_grant->>'facts_receipt_id')::uuid)))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr
     WHERE (rr.generation_artifact_id=artifact.id OR (NOT committed AND rr.generation_artifact_id=lineage.parent_artifact_id)) AND rr.artifact_kind='admission_evaluation')
   OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe
     JOIN tutor_item_supply_shared_generation_artifacts aa ON aa.version_id=pe.version_id
     WHERE aa.id=artifact.id OR (NOT committed AND aa.id=lineage.parent_artifact_id)) THEN
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
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=(CASE WHEN committed THEN artifact.job_id ELSE NEW.job_id END)
   AND (NOT committed OR cp.lease_generation=artifact.lease_generation) AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=artifact.artifact_hash)
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
   IF NEW.valid_until IS DISTINCT FROM (CASE WHEN committed THEN (p->>'deadline_at')::timestamptz ELSE revision_prep.valid_until END) OR NEW.lineage_id IS DISTINCT FROM lineage.id
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
 IF clock_timestamp()>=LEAST((CASE WHEN committed THEN (p->>'deadline_at')::timestamptz ELSE revision_prep.valid_until END),control_row.lease_expires_at,control_row.parent_deadline,
   (snapshot->>'parent_deadline_at')::timestamptz,
   (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) THEN
   RAISE check_violation USING MESSAGE='recheck final current deadline reached';
 END IF;
 RETURN NEW;
END $source_enforce_revision_recheck_insert_587$;
BEGIN
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.enforce_revision_recheck_insert()');
 IF NOT FOUND OR encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('9885428fd7199eb110aa5707baf8aa689445bc2233037bbcdb23afff37d5daba','52ad3eb3b44382b8cd30171a76fd5a94987664cf3708d90bd5122f332a2b74c3')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  OR f.proargnames IS NOT NULL OR f.prokind<>'f' OR f.proretset OR f.proisstrict
 THEN RAISE check_violation USING MESSAGE='587 unexpected original receiver: enforce_revision_recheck_insert'; END IF;
 EXECUTE 'CREATE OR REPLACE FUNCTION item_supply_internal.enforce_revision_recheck_insert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS ' || quote_literal(body);
 SELECT p.* INTO f FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_revision_recheck_insert()');
 IF encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')<>'52ad3eb3b44382b8cd30171a76fd5a94987664cf3708d90bd5122f332a2b74c3' THEN
  RAISE check_violation USING MESSAGE='587 receiver replacement mismatch: enforce_revision_recheck_insert'; END IF;
END $enforce_revision_recheck_insert_587$;

DO $assert_normal_revision_readmission_587$
DECLARE f record; body text := $source_assert_normal_revision_readmission_587$
DECLARE child tutor_item_supply_shared_generation_artifacts%ROWTYPE; parent tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE; rp tutor_item_supply_shared_revision_preparations%ROWTYPE;
 rr tutor_item_supply_shared_revision_recheck_receipts%ROWTYPE; prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE; vp tutor_item_supply_shared_validation_preparations%ROWTYPE;
 gp tutor_item_supply_shared_generation_policy_bindings%ROWTYPE;
 control_row record; stamp timestamptz; snapshot jsonb; f jsonb:=p->'facts_payload'; roles text[]; m03_permission boolean:=false; m03_grant jsonb;
BEGIN
 IF p->>'schema_version'='normal_revision_readmission_v3' THEN
  PERFORM item_supply_internal.assert_normal_revision_readmission_v3(p); RETURN;
 END IF;
 IF p->>'schema_version'='normal_revision_readmission_v2' THEN
   PERFORM item_supply_internal.assert_normal_revision_readmission_v2(p); RETURN;
 END IF;
 IF p->>'schema_version'='normal_revision_readmission_m03_p2_v1' THEN
  m03_grant:=item_supply_internal.m03_p2_normal_loop_for_job((p->'lease'->>'job_id')::uuid);
  IF m03_grant IS NULL OR p->'m03_p2_grant' IS DISTINCT FROM m03_grant
   OR p->'lease'->>'job_id'=m03_grant->>'continuation_job_id' THEN
   RAISE check_violation USING MESSAGE='587 original P2 normal child grant required'; END IF;
  m03_permission:=true;
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
   'publication_enabled','historical_findings_discharged'] || (CASE WHEN m03_permission THEN ARRAY['m03_p2_grant']::text[] ELSE ARRAY[]::text[] END)) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM (CASE WHEN m03_permission THEN 'normal_revision_readmission_m03_p2_v1' ELSE 'normal_revision_readmission_v1' END)
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
 IF m03_permission AND (parent.id IS DISTINCT FROM (m03_grant->>'artifact_id')::uuid
  OR rp.parent_job_id IS DISTINCT FROM (m03_grant->>'continuation_job_id')::uuid
  OR child.target_id IS DISTINCT FROM 'sqlite-predicate-order-v1'
  OR child.root_id IS DISTINCT FROM (m03_grant->>'root_id')::uuid) THEN
  RAISE check_violation USING MESSAGE='587 exact P2 same-root substantive child required'; END IF;
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
   OR peer.payload_json->>'schema_version' IS DISTINCT FROM (CASE WHEN m03_permission THEN 'item_supply_review_bundle_v2' ELSE 'item_supply_review_bundle_v3' END)
   OR p->>'policy_hash' IS DISTINCT FROM (CASE WHEN m03_permission THEN '7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab' ELSE '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' END)
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
   OR f->'evaluation'->>'schema_version' IS DISTINCT FROM (CASE WHEN m03_permission THEN 'item_supply_admission_evaluation_v2' ELSE 'item_supply_admission_evaluation_v3' END)
   OR (f->>'checked_at')::timestamptz IS DISTINCT FROM (p->>'checked_at')::timestamptz
   OR (f->>'valid_until')::timestamptz IS DISTINCT FROM (p->>'valid_until')::timestamptz
   OR f->>'validation_preparation_id' IS DISTINCT FROM vp.id::text
   OR f->>'validation_receipt_id' IS DISTINCT FROM vr.id::text OR f->>'validation_receipt_hash' IS DISTINCT FROM vr.receipt_hash
   OR f->>'blind_receipt_id' IS DISTINCT FROM br.id::text OR f->>'blind_receipt_hash' IS DISTINCT FROM br.receipt_hash
   OR f->>'review_receipt_id' IS DISTINCT FROM peer.id::text OR f->>'review_receipt_hash' IS DISTINCT FROM peer.receipt_hash THEN
   RAISE check_violation USING MESSAGE='normal original full facts/evaluation exact hash required';
 END IF;
 IF m03_permission AND (br.payload_json->>'state' IS DISTINCT FROM 'completed'
  OR br.payload_json->>'mode' IS DISTINCT FROM 'public_only'
  OR br.payload_json->'score'->'passed' IS DISTINCT FROM 'true'::jsonb
  OR item_supply_internal.shared_evaluation_policy_matches(child,f->'evaluation',peer.payload_json) IS DISTINCT FROM true
  OR item_supply_internal.m03_p2_normal_loop_for_job(child.job_id) IS DISTINCT FROM m03_grant) THEN
  RAISE check_violation USING MESSAGE='587 unchanged full V2 quality and current grant required'; END IF;
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
   OR gp.policy_hash IS DISTINCT FROM (CASE WHEN m03_permission THEN '7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab' ELSE '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' END)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(rp.payload_json->'source_deadlines') source_bound
     WHERE (source_bound.value->>'retained_until')::timestamptz IS NULL
       OR (source_bound.value->>'retained_until')::timestamptz<=stamp) THEN
   RAISE check_violation USING MESSAGE='normal readmission final current bound/controlled/policy expired';
 END IF;
END $source_assert_normal_revision_readmission_587$;
BEGIN
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission(jsonb)');
 IF NOT FOUND OR encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN ('db1ab4aaf95bfb60fd2e48d6237cffb46f4d09384e4529a83a90ecb8c9ec72ae','0c9da57c7aea17c5e7df7608391d76f47f20f701f7c8c5ca4a14eebd1077017d')
  OR f.prosecdef IS DISTINCT FROM true OR f.lanname IS DISTINCT FROM 'plpgsql'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  OR f.proargnames IS DISTINCT FROM ARRAY['p']::text[] OR f.prokind<>'f' OR f.proretset OR f.proisstrict
 THEN RAISE check_violation USING MESSAGE='587 unexpected original receiver: assert_normal_revision_readmission'; END IF;
 EXECUTE 'CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_revision_readmission(p jsonb) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS ' || quote_literal(body);
 SELECT p.* INTO f FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission(jsonb)');
 IF encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')<>'0c9da57c7aea17c5e7df7608391d76f47f20f701f7c8c5ca4a14eebd1077017d' THEN
  RAISE check_violation USING MESSAGE='587 receiver replacement mismatch: assert_normal_revision_readmission'; END IF;
END $assert_normal_revision_readmission_587$;
