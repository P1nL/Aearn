-- 593: original persistent pack two-slot execution closure. No new table,
-- record_kind, CHECK, receiver or grant. <=592 and W1 remain unchanged.
-- Baseline: Main READ ONLY installed catalog, 2026-10-25 16:13:41+08.
-- Receipt DATA must be prior-COMMIT (including rejection of sub-XID evidence).
-- PostgreSQL candidate/install/readback are Main-only and separately required.

DO $dp593_0$
DECLARE signature constant text := 'item_supply_internal.enforce_persistent_pack_journal_insert()';
 baseline_md5 constant text := '7caf62d9cea5573895ab88b5d07b67f2'; revised_md5 constant text := 'b93a8df0a058a710ebc93c0b526f86d9';
 revised_source constant text := $source593_0$
DECLARE p jsonb:=NEW.payload_json; parent record; proof record; phase record; header record; artifact record;
 private_header record;private_job record;private_control record;private_ref jsonb;private_lease jsonb;private_profile jsonb;fixed_slot jsonb;stamp timestamptz;
 committed_child_data boolean:=false; admission_action jsonb; admission_row record;
 slots text[]:=ARRAY['practice-1','practice-2','assessment-1','assessment-2','guided-remediation']; slot_index integer;

 dp_public uuid; dp_namespace text; dp_phase record; dp_control record; dp_start record; dp_done record;
 dp_receipt record; dp_jobs uuid[]; dp_count integer; dp_slot text; dp_active record; dp_existing boolean:=false;
 dp_artifact record; dp_relation record; dp_terminal_artifacts uuid[]:=ARRAY[]::uuid[];
 m03_data boolean:=false;m03_repair_data boolean:=false;m03_phase record;m03_parent record;m03_pa record;
 m03_context jsonb;m03_expected jsonb;m03_f record;m03_index integer;
BEGIN

 -- 593: all phase insertions/STARTs/closure use the same short pack lock.
 IF TG_TABLE_NAME='tutor_item_supply_shared_persistent_pack_journal' THEN
  dp_public:=NEW.public_task_id; dp_namespace:='shared';
 ELSE
  PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
  dp_namespace:='private';
  SELECT (h.payload_json->'ref'->>'public_task_id')::uuid INTO dp_public
   FROM tutor_item_supply_private_persistent_pack_journal h
   WHERE h.id=NEW.pack_task_id AND h.record_kind='task' AND h.user_id=NEW.user_id
    AND h.epoch=NEW.epoch AND h.scope_id=NEW.scope_id;
 END IF;
 IF dp_public IS NOT NULL THEN
  PERFORM pg_advisory_xact_lock(hashtext('persistent-pack-dispatch'),hashtext(dp_public::text));
 END IF;
 IF p->>'schema_version'='persistent_phase_execution_outcome_v2' THEN
  IF current_setting('transaction_isolation')<>'read committed' OR dp_public IS NULL
   OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','namespace','phase_id','phase_hash','job_id',
     'lease_generation','slot_id','revision_id','execution_state','status','artifact_id','published_version_id','safe_reason']) IS DISTINCT FROM true
   OR p->>'namespace' IS DISTINCT FROM dp_namespace
   OR COALESCE(p->>'execution_state' IN('committed_complete','committed_known_stop','abandoned_unstarted'),false) IS DISTINCT FROM true
   OR COALESCE(p->>'status' IN('qualified','quality_failed','blocked','relation_ready'),false) IS DISTINCT FROM true
   OR jsonb_typeof(p->'lease_generation') IS DISTINCT FROM 'number'
   OR COALESCE(p->>'safe_reason' ~ '^[a-z0-9_]{1,160}$',false) IS DISTINCT FROM true
   OR NEW.operation_key IS DISTINCT FROM replace(p->>'phase_id','-','')||'.closed'
  THEN RAISE check_violation USING MESSAGE='593 execution closure exact typed binding required'; END IF;
  IF dp_namespace='shared' THEN
   IF NEW.record_kind<>'phase_result' THEN RAISE check_violation USING MESSAGE='593 execution closure shared kind'; END IF;
   SELECT q.*,q.xmin AS row_xmin,q.payload_json->>'frame_hash' AS frame INTO dp_phase
    FROM tutor_item_supply_shared_persistent_pack_journal q WHERE q.record_kind='phase'
     AND q.phase_id=(p->>'phase_id')::uuid AND q.public_task_id=NEW.public_task_id FOR SHARE;
   IF dp_phase.id IS NULL OR NEW.phase_id IS DISTINCT FROM dp_phase.phase_id
    OR NEW.job_id IS DISTINCT FROM dp_phase.job_id OR NEW.root_id IS DISTINCT FROM dp_phase.root_id
    OR p->'slot_id' IS DISTINCT FROM dp_phase.payload_json->'public_slot_id'
    OR p->'revision_id' IS DISTINCT FROM dp_phase.payload_json->'revision_id'
   THEN RAISE check_violation USING MESSAGE='593 execution closure original shared frame'; END IF;
   WITH RECURSIVE jobs AS (SELECT id FROM tutor_item_supply_shared_jobs WHERE id=dp_phase.job_id
    UNION SELECT j.id FROM tutor_item_supply_shared_jobs j JOIN jobs x ON j.parent_job_id=x.id)
   SELECT array_agg(id ORDER BY id) INTO dp_jobs FROM jobs;
   PERFORM job_id FROM tutor_item_supply_shared_job_controls WHERE job_id=ANY(dp_jobs) ORDER BY job_id FOR UPDATE;
   SELECT * INTO dp_control FROM tutor_item_supply_shared_job_controls WHERE job_id=dp_phase.job_id;
  ELSE
   PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
   IF NEW.record_kind<>'private_status' THEN RAISE check_violation USING MESSAGE='593 execution closure private kind'; END IF;
   PERFORM id FROM tutor_item_supply_private_scopes
    WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='593 execution closure original PRIVATE scope required'; END IF;
   -- The early v2 RETURN must retain the original non-task identity check.
   SELECT h.* INTO private_header FROM tutor_item_supply_private_persistent_pack_journal h
    WHERE h.id=NEW.pack_task_id AND h.pack_task_id=h.id AND h.record_kind='task'
     AND h.user_id=NEW.user_id AND h.epoch=NEW.epoch AND h.scope_id=NEW.scope_id
     AND h.intent_hash=NEW.intent_hash FOR SHARE;
   IF private_header.id IS NULL THEN
    RAISE check_violation USING MESSAGE='593 execution closure original PRIVATE task intent required'; END IF;
   SELECT q.*,q.xmin AS row_xmin,q.payload_hash AS frame INTO dp_phase
    FROM tutor_item_supply_private_persistent_pack_journal q WHERE q.id=(p->>'phase_id')::uuid
     AND q.record_kind='phase' AND q.payload_json->>'schema_version'='private_native_phase_v1'
     AND q.pack_task_id=NEW.pack_task_id AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id FOR SHARE;
   IF dp_phase.id IS NULL OR p->'slot_id' IS DISTINCT FROM dp_phase.payload_json->'slot_id'
    OR p->'revision_id' IS DISTINCT FROM dp_phase.payload_json->'ref'->'parent_version_id'
   THEN RAISE check_violation USING MESSAGE='593 execution closure original private frame'; END IF;
   SELECT * INTO dp_control FROM tutor_item_supply_private_job_controls
    WHERE job_id=(dp_phase.payload_json->>'job_id')::uuid AND user_id=NEW.user_id AND epoch=NEW.epoch FOR UPDATE;
   dp_jobs:=ARRAY[dp_control.job_id];
  END IF;
  IF dp_control.job_id IS NULL OR p->>'phase_hash' IS DISTINCT FROM dp_phase.frame
   OR p->>'job_id' IS DISTINCT FROM dp_control.job_id::text
   OR (p->>'lease_generation')::bigint IS DISTINCT FROM dp_control.lease_generation
   OR p->'lease_generation' IS DISTINCT FROM dp_phase.payload_json->'lease'->'generation'
   OR pg_xact_status(dp_phase.row_xmin::text::xid8) IS DISTINCT FROM 'committed'
  THEN RAISE check_violation USING MESSAGE='593 execution closure prior-COMMIT frame/generation required'; END IF;
  -- Explicit abandonment has NO dispatch, provider/stage/runner START or reservation.
  -- An expiry, NULL receipt or exception never proves abandonment.
  IF p->>'execution_state'='abandoned_unstarted' THEN
   IF p->>'status'<>'blocked' OR p->'artifact_id'<>'null'::jsonb OR p->'published_version_id'<>'null'::jsonb THEN
    RAISE check_violation USING MESSAGE='593 execution closure abandoned status'; END IF;
   IF dp_namespace='shared' THEN
    IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal q WHERE q.phase_id=dp_phase.phase_id
       AND q.record_kind IN('dispatch_started','stage_started'))
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations r WHERE r.job_id=ANY(dp_jobs)
      AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=r.id
       AND s.usage_state='unknown' AND s.receipt_hash IS NULL
       AND s.settlement_key='persistent.unstarted.'||replace(dp_phase.phase_id::text,'-','')||'.'||replace(r.id::text,'-','')))
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events WHERE job_id=ANY(dp_jobs) AND event_kind='started')
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_probe_events WHERE job_id=ANY(dp_jobs) AND event_kind='started')
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_events a
      JOIN tutor_item_supply_shared_review_adjudication_preparations r ON r.id=a.preparation_id
      WHERE r.job_id=ANY(dp_jobs) AND a.event_kind='started')
     OR EXISTS(SELECT 1 FROM tutor_item_supply_private_subscriptions WHERE shared_job_id=ANY(dp_jobs) AND state='active')
    THEN RAISE check_violation USING MESSAGE='593 execution closure abandonment is not proven'; END IF;
   ELSE
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal q WHERE q.pack_task_id=NEW.pack_task_id
       AND q.record_kind='private_status' AND q.payload_json->>'schema_version'='private_native_stage_v1'
       AND q.payload_json->>'job_id'=p->>'job_id' AND q.payload_json->>'status'='started')
     OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations WHERE job_id=dp_control.job_id)
    THEN RAISE check_violation USING MESSAGE='593 execution closure abandonment is not proven'; END IF;
   END IF;
  ELSE
   IF dp_namespace='shared' THEN
    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal q WHERE q.phase_id=dp_phase.phase_id
      AND q.record_kind='dispatch_started' AND pg_xact_status(q.xmin::text::xid8)='committed') THEN
     RAISE check_violation USING MESSAGE='593 execution closure committed dispatch required'; END IF;
    SELECT a.* INTO dp_artifact FROM tutor_item_supply_shared_generation_artifacts a
     WHERE EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal v
      WHERE v.public_task_id=dp_phase.public_task_id AND v.record_kind IN('version','qualified')
       AND v.payload_json->'public_slot_id'=dp_phase.payload_json->'public_slot_id'
       AND v.payload_json->'revision_id'=dp_phase.payload_json->'revision_id'
       AND v.payload_json->>'artifact_id'=a.id::text AND v.payload_json->>'candidate_id'=a.candidate_id::text
       AND v.root_id=a.root_id AND pg_xact_status(v.xmin::text::xid8)='committed')
      AND a.root_id=dp_phase.root_id AND pg_xact_status(a.xmin::text::xid8)='committed';
    IF dp_phase.payload_json ? 'm03_exact' THEN
     IF dp_artifact.id IS NULL
      OR dp_artifact.candidate_id::text IS DISTINCT FROM dp_phase.payload_json->'m03_exact'->>'candidate_id'
      OR dp_artifact.request_json->'blueprint' IS DISTINCT FROM dp_phase.payload_json->'m03_exact'->'specification'->'blueprint'
      OR dp_artifact.request_json->'public_template' IS DISTINCT FROM dp_phase.payload_json->'m03_exact'->'specification'->'public_template'
      OR dp_artifact.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(dp_phase.payload_json->'m03_exact'->'specification'->'coverage_blueprint'->'scope')
      OR (dp_phase.payload_json->'m03_exact'->>'schema_version'='m03_author_preflight_subject_v1'
       AND (dp_artifact.request_json->'author_preflight_repair' IS DISTINCT FROM dp_phase.payload_json->'m03_exact'->'repair_context'
        OR dp_artifact.job_id IS DISTINCT FROM dp_phase.job_id
        OR dp_artifact.lease_generation::text IS DISTINCT FROM dp_phase.payload_json->'lease'->>'generation'
        OR dp_artifact.request_json->'profile' IS DISTINCT FROM dp_phase.payload_json->'lease'->'profile'))
     THEN RAISE check_violation USING MESSAGE='593 M03 closure exact original author or committed subject required'; END IF;
     IF p->>'safe_reason'='m03_original_author_preflight_repair_required' AND (
       p->>'status' IS DISTINCT FROM 'quality_failed' OR p->>'execution_state' IS DISTINCT FROM 'committed_known_stop'
       OR dp_phase.payload_json->'m03_exact'->>'schema_version' IS DISTINCT FROM 'm03_exact_candidate_subject_v1'
       OR dp_artifact.request_json ? 'author_preflight_repair'
       OR dp_artifact.job_id IS DISTINCT FROM dp_phase.job_id
       OR dp_artifact.lease_generation::text IS DISTINCT FROM dp_phase.payload_json->'lease'->>'generation'
       OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal q WHERE q.phase_id=dp_phase.phase_id
          AND q.record_kind='stage_started' AND q.payload_json->>'stage'<>'author')
       OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_validation_preparations q WHERE q.generation_artifact_id=dp_artifact.id)
       OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=dp_artifact.reservation_id
         AND s.usage_state='known' AND s.receipt_hash=item_supply_internal.snapshot_hash(dp_artifact.receipt_json->'provider')
         AND s.settlement_key='generation.'||replace(dp_artifact.candidate_id::text,'-','')
         AND pg_xact_status(s.xmin::text::xid8)='committed')) THEN
      RAISE check_violation USING MESSAGE='593 M03 known preflight stop requires sole real committed author'; END IF;
    END IF;
    -- relation_pack has an original aggregate receipt, not candidate stages.
    -- Keep diagnoses private: derive its locator from the exact preparation frame.
    SELECT b.* INTO dp_relation FROM tutor_item_supply_native_relation_batches b
     JOIN tutor_item_supply_native_relation_preparations a ON a.id=b.preparation_id
      AND (a.user_id,a.epoch,a.mapping_receipt_id,a.root_id,a.job_id,a.reservation_id)=
          (b.user_id,b.epoch,b.mapping_receipt_id,b.root_id,b.job_id,b.reservation_id)
     JOIN tutor_item_supply_shared_reservations r ON r.id=b.reservation_id AND r.job_id=b.job_id AND r.root_id=b.root_id
     JOIN tutor_item_supply_shared_runtime_settlements s ON s.reservation_id=r.id
     WHERE dp_phase.payload_json->>'kind'='relation_pack' AND b.job_id=dp_phase.job_id AND b.root_id=dp_phase.root_id
      AND a.payload_json->'persistent_phase'=dp_phase.payload_json
      AND a.payload_json->'lease'=dp_phase.payload_json->'lease'
      AND r.lease_generation=(p->>'lease_generation')::bigint AND r.requests=4
      AND r.reservation_key='native.relation.'||replace(a.id::text,'-','')
      AND s.settlement_key=r.reservation_key AND s.usage_state='unknown'
      AND b.payload_json->'pairs'=a.payload_json->'pairs' AND b.payload_json->'contents'=a.payload_json->'contents'
      AND b.request_hash=a.payload_json->>'request_hash'
      AND b.payload_json->>'profile_hash'=dp_phase.payload_json->'lease'->'profile'->>'profile_hash'
      AND b.checked_at>=a.checked_at AND b.checked_at<a.valid_until AND b.valid_until=a.evidence_valid_until
      AND jsonb_array_length(b.payload_json->'contents') BETWEEN 5 AND 16
      AND (SELECT jsonb_agg(c->'version_id') FROM jsonb_array_elements(b.payload_json->'contents') c)
          @> dp_phase.payload_json->'candidate_version_ids'
      AND jsonb_array_length(b.payload_json->'reports')=4
      AND (SELECT array_agg(c->>'role' ORDER BY c->>'role') FROM jsonb_array_elements(b.payload_json->'reports') c)
          =ARRAY['adversarial','ambiguity','curriculum','technical']::text[]
      AND EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal h WHERE h.record_kind='task'
       AND h.user_id=b.user_id AND h.epoch=b.epoch AND h.payload_json->'ref'->>'public_task_id'=dp_phase.public_task_id::text
       AND h.payload_json->'ref'->>'mapping_receipt_id'=b.mapping_receipt_id::text)
      AND pg_xact_status(a.xmin::text::xid8)='committed' AND pg_xact_status(b.xmin::text::xid8)='committed'
      AND pg_xact_status(r.xmin::text::xid8)='committed' AND pg_xact_status(s.xmin::text::xid8)='committed';
    IF dp_phase.payload_json->>'kind'='relation_pack' AND dp_relation.id IS NULL THEN
     RAISE check_violation USING MESSAGE='593 execution closure exact committed relation batch required'; END IF;
    -- Enumerate EVERY journal START, not a caller-provided completed subset.
    dp_count:=0;
    FOR dp_start IN SELECT q.*,q.xmin AS receipt_xmin FROM tutor_item_supply_shared_persistent_pack_journal q
     WHERE q.phase_id=dp_phase.phase_id AND q.record_kind='stage_started' ORDER BY q.operation_key LOOP
     dp_count:=dp_count+1;
     IF (dp_phase.payload_json->>'kind'='relation_pack'
       AND dp_start.operation_key IS DISTINCT FROM 'persistent.relation.'||replace(dp_phase.phase_id::text,'-',''))
      OR (dp_phase.payload_json->>'kind'<>'relation_pack' AND dp_start.payload_json->>'stage'<>'investigation'
       AND dp_start.operation_key IS DISTINCT FROM 'persistent.stage.'||replace(dp_phase.payload_json->>'revision_id','-','')
          ||'.'||(dp_start.payload_json->>'stage')) THEN
      RAISE check_violation USING MESSAGE='593 execution closure original stage action key required'; END IF;
     SELECT q.*,q.xmin AS receipt_xmin INTO dp_done FROM tutor_item_supply_shared_persistent_pack_journal q
      WHERE q.phase_id=dp_phase.phase_id AND q.record_kind='stage_result' AND q.operation_key=dp_start.operation_key;
     -- SHARED may stop between serial roles. All ACTUALLY STARTed actions must
     -- be committed; unstarted roles retain no dispatch right after this seal.
     -- This does not extend PRIVATE initial partial/fresh-profile recovery.
     IF dp_start.payload_json->>'stage'='review' AND p->>'status'='blocked'
      AND p->>'execution_state'='committed_known_stop'
      AND (dp_done.id IS NULL OR dp_done.payload_json->>'receipt_id' IS NULL)
      AND pg_xact_status(dp_start.receipt_xmin::text::xid8)='committed'
      AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events a
       WHERE a.job_id=dp_phase.job_id AND a.generation_artifact_id=dp_artifact.id
        AND a.payload_json->'lease'->'generation'=p->'lease_generation' AND a.event_kind='started')
      AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events s
       WHERE s.job_id=dp_phase.job_id AND s.event_kind='started' AND NOT EXISTS(
        SELECT 1 FROM tutor_item_supply_shared_incremental_role_events d WHERE d.review_reservation_id=s.review_reservation_id
         AND d.role=s.role AND d.input_hash=s.input_hash AND d.event_kind='committed'
         AND d.payload_json->>'started_event_id'=s.id::text AND pg_xact_status(d.xmin::text::xid8)='committed'
         AND s.generation_artifact_id=dp_artifact.id AND d.generation_artifact_id=s.generation_artifact_id
         AND d.job_id=s.job_id AND s.payload_json->'lease'->'generation'=p->'lease_generation'
         AND d.payload_json->'lease'->'generation'=s.payload_json->'lease'->'generation'
         AND (jsonb_typeof(d.payload_json->'result')='object' OR jsonb_typeof(d.payload_json->'report')='object')))
     THEN CONTINUE; END IF;
     IF dp_done.id IS NULL OR dp_done.payload_json->>'stage' IS DISTINCT FROM dp_start.payload_json->>'stage'
      OR dp_done.payload_json->>'outcome' IS DISTINCT FROM 'completed' OR dp_done.payload_json->>'receipt_id' IS NULL
      OR pg_xact_status(dp_start.receipt_xmin::text::xid8) IS DISTINCT FROM 'committed'
      OR pg_xact_status(dp_done.receipt_xmin::text::xid8) IS DISTINCT FROM 'committed' THEN
      RAISE check_violation USING MESSAGE='593 execution closure unresolved START'; END IF;
     -- Each arm retains the real action frame, not merely receipt ID + stage.
     SELECT z.* INTO dp_receipt FROM (
      SELECT a.id,'author'::text AS stage FROM tutor_item_supply_shared_generation_artifacts a
       WHERE a.id=dp_artifact.id AND a.job_id=dp_phase.job_id AND a.lease_generation=(p->>'lease_generation')::bigint
        AND pg_xact_status(a.xmin::text::xid8)='committed'
      UNION ALL SELECT a.id,CASE a.artifact_kind WHEN 'review_bundle' THEN 'review' ELSE 'validation' END
       FROM tutor_item_supply_shared_pipeline_receipts a WHERE a.artifact_kind IN('validation','review_bundle')
        AND (a.generation_artifact_id,a.item_id,a.version_id,a.source_hash,a.content_hash)=
            (dp_artifact.id,dp_artifact.item_id,dp_artifact.version_id,dp_artifact.source_hash,dp_artifact.content_hash)
        AND a.job_id=dp_phase.job_id AND a.lease_generation=(p->>'lease_generation')::bigint
        AND (a.artifact_kind='validation' OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations r
         WHERE r.job_id=a.job_id AND r.lease_generation=a.lease_generation
          AND r.reservation_key='review.'||replace(a.generation_artifact_id::text,'-','')
          AND a.artifact_key='review_bundle.'||replace(r.id::text,'-','')))
        AND (a.artifact_kind='validation' OR a.payload_json->>'state'='completed'
         OR a.payload_json->>'schema_version'='item_supply_review_coverage_v1')
        AND pg_xact_status(a.xmin::text::xid8)='committed'
      UNION ALL SELECT a.id,'investigation' FROM tutor_item_supply_shared_review_investigation_receipts a
       JOIN tutor_item_supply_shared_review_investigation_preparations b ON b.id=a.preparation_id
       WHERE a.generation_artifact_id=dp_artifact.id AND a.root_id=dp_phase.root_id AND a.job_id=dp_phase.job_id
        AND a.lease_generation=(p->>'lease_generation')::bigint
        AND b.payload_json->'lease'->'generation'=p->'lease_generation'
        AND b.payload_json->>'generation_artifact_id'=dp_artifact.id::text
        AND b.payload_json->>'artifact_hash'=dp_artifact.artifact_hash
        AND b.payload_json->>'review_receipt_id'=a.review_receipt_id::text
        AND (dp_start.operation_key='persistent.stage.'||replace(dp_phase.payload_json->>'revision_id','-','')||'.investigation'
         OR b.payload_json->'persistent_phase'=dp_phase.payload_json)
        AND a.payload_json->'report' IS NOT NULL AND a.payload_json->'report'<>'null'::jsonb
        AND pg_xact_status(a.xmin::text::xid8)='committed' AND pg_xact_status(b.xmin::text::xid8)='committed'
      UNION ALL SELECT a.id,'revision' FROM tutor_item_supply_shared_revision_lineage a
       JOIN tutor_item_supply_shared_revision_preparations b ON b.id=a.preparation_id
       JOIN tutor_item_supply_shared_generation_artifacts c ON c.id=a.child_artifact_id
       WHERE a.parent_artifact_id=dp_artifact.id AND a.root_id=dp_phase.root_id AND b.parent_artifact_id=dp_artifact.id
        AND b.payload_json->'parent_lease'->>'job_id'=dp_phase.job_id::text
        AND b.payload_json->'parent_lease'->'generation'=p->'lease_generation'
        AND b.child_job_id=a.child_job_id AND c.job_id=a.child_job_id
        AND c.request_json=b.payload_json->'request' AND c.candidate_id=b.candidate_id
        AND b.payload_json->'child_lease'->>'job_id'=c.job_id::text
        AND b.payload_json->'child_lease'->>'generation'=c.lease_generation::text
        AND a.payload_json->'lease'->>'generation'=c.lease_generation::text
        AND a.payload_json->>'child_artifact_hash'=c.artifact_hash
        AND pg_xact_status(a.xmin::text::xid8)='committed' AND pg_xact_status(b.xmin::text::xid8)='committed'
        AND pg_xact_status(c.xmin::text::xid8)='committed'
      UNION ALL SELECT a.id,'recheck' FROM tutor_item_supply_shared_revision_recheck_receipts a
       JOIN tutor_item_supply_shared_revision_recheck_preparations b ON b.id=a.preparation_id
       JOIN tutor_item_supply_shared_revision_lineage l ON l.id=b.lineage_id AND l.child_artifact_id=a.generation_artifact_id
       JOIN tutor_item_supply_shared_generation_artifacts c ON c.id=a.generation_artifact_id
       JOIN tutor_item_supply_shared_pipeline_receipts v ON v.id=a.validation_receipt_id
       JOIN tutor_item_supply_shared_pipeline_receipts r ON r.id=a.review_receipt_id
       WHERE a.root_id=dp_phase.root_id AND (l.parent_artifact_id=dp_artifact.id OR c.id=dp_artifact.id)
        AND a.job_id=b.job_id AND b.payload_json->'lease'->>'job_id'=a.job_id::text
        AND (a.job_id=dp_phase.job_id AND b.payload_json->'lease'->'generation'=p->'lease_generation'
         OR a.job_id=l.child_job_id AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations x
          WHERE x.id=l.preparation_id AND x.payload_json->'parent_lease'->>'job_id'=dp_phase.job_id::text
           AND x.payload_json->'parent_lease'->'generation'=p->'lease_generation'))
        AND b.payload_json->>'artifact_id'=c.id::text AND b.payload_json->>'artifact_hash'=c.artifact_hash
        AND (v.generation_artifact_id,v.job_id,v.lease_generation,v.version_id,v.source_hash,v.content_hash)=
            (c.id,a.job_id,(b.payload_json->'lease'->>'generation')::bigint,c.version_id,c.source_hash,c.content_hash)
        AND (r.generation_artifact_id,r.job_id,r.lease_generation,r.version_id,r.source_hash,r.content_hash)=
            (v.generation_artifact_id,v.job_id,v.lease_generation,v.version_id,v.source_hash,v.content_hash)
        AND pg_xact_status(a.xmin::text::xid8)='committed' AND pg_xact_status(b.xmin::text::xid8)='committed'
        AND pg_xact_status(v.xmin::text::xid8)='committed' AND pg_xact_status(r.xmin::text::xid8)='committed'
      UNION ALL SELECT dp_relation.id,'relation' WHERE dp_relation.id IS NOT NULL
     ) z WHERE z.id=(dp_done.payload_json->>'receipt_id')::uuid AND z.stage=dp_start.payload_json->>'stage';
     IF dp_receipt.id IS NULL THEN RAISE check_violation USING MESSAGE='593 execution closure genuine original terminal receipt required'; END IF;
    END LOOP;
    IF dp_count=0 AND dp_relation.id IS NULL AND NOT EXISTS(
     SELECT 1 FROM tutor_item_supply_shared_incremental_role_events s WHERE s.job_id=dp_phase.job_id
      AND s.generation_artifact_id=dp_artifact.id AND s.event_kind='started'
      AND s.payload_json->'lease'->'generation'=p->'lease_generation'
      AND pg_xact_status(s.xmin::text::xid8)='committed'
      AND (p->>'status'='blocked' AND p->>'execution_state'='committed_known_stop'
       OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts a WHERE a.job_id=s.job_id
        AND a.lease_generation=(p->>'lease_generation')::bigint AND a.generation_artifact_id=dp_artifact.id
        AND (a.version_id,a.source_hash,a.content_hash)=(dp_artifact.version_id,dp_artifact.source_hash,dp_artifact.content_hash)
        AND a.artifact_kind='review_bundle' AND pg_xact_status(a.xmin::text::xid8)='committed')))
    THEN RAISE check_violation USING MESSAGE='593 execution closure no committed stage'; END IF;
    IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events s WHERE s.job_id=ANY(dp_jobs) AND s.event_kind='started'
     AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events d WHERE d.review_reservation_id=s.review_reservation_id
       AND d.role=s.role AND d.input_hash=s.input_hash AND d.event_kind='committed'
       AND d.job_id=s.job_id AND d.generation_artifact_id=s.generation_artifact_id
       AND d.logical_action_hash=s.logical_action_hash
       AND d.payload_json->'binding'=s.payload_json->'binding'
       AND d.payload_json->'subject'=s.payload_json->'subject'
       AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=s.generation_artifact_id
        AND (s.payload_json->'binding'->>'source_hash',s.payload_json->'binding'->>'content_hash',s.payload_json->'binding'->>'version_key')=
            (a.source_hash,a.content_hash,a.version_id::text))
       AND d.payload_json->'lease'->'generation'=s.payload_json->'lease'->'generation'
       AND (s.job_id=dp_phase.job_id AND s.payload_json->'lease'->'generation'=p->'lease_generation'
        OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations x
         WHERE x.child_job_id=s.job_id AND x.parent_artifact_id=dp_artifact.id
          AND x.payload_json->'parent_lease'->>'job_id'=dp_phase.job_id::text
          AND x.payload_json->'parent_lease'->'generation'=p->'lease_generation'
          AND x.payload_json->'child_lease'->'generation'=s.payload_json->'lease'->'generation'))
       AND (s.generation_artifact_id=dp_artifact.id OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_lineage l
        WHERE l.parent_artifact_id=dp_artifact.id AND l.child_artifact_id=s.generation_artifact_id AND l.child_job_id=s.job_id))
       AND d.payload_json->>'started_event_id'=s.id::text AND pg_xact_status(d.xmin::text::xid8)='committed')) THEN
     RAISE check_violation USING MESSAGE='593 execution closure unresolved original role START'; END IF;
    -- Every actual reservation needs BOTH settlement and a real typed terminal.
    -- Accounting UNKNOWN alone is neither an execution failure nor completion.
    IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations r WHERE r.job_id=ANY(dp_jobs) AND (
     NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=r.id
       AND pg_xact_status(s.xmin::text::xid8)='committed') OR NOT (
      EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts a WHERE a.reservation_id=r.id
       AND a.job_id=r.job_id AND a.lease_generation=r.lease_generation AND pg_xact_status(a.xmin::text::xid8)='committed')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_validation_evidence a WHERE a.reservation_id=r.id
        AND a.payload_json->'validation' IS NOT NULL AND a.payload_json->'validation'<>'null'::jsonb AND pg_xact_status(a.xmin::text::xid8)='committed')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts a WHERE a.job_id=r.job_id AND a.artifact_kind='review_bundle'
        AND r.reservation_key='review.'||replace(a.generation_artifact_id::text,'-','')
        AND (a.payload_json->>'state'='completed' OR a.payload_json->>'schema_version'='item_supply_review_coverage_v1')
        AND pg_xact_status(a.xmin::text::xid8)='committed')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts a WHERE a.reservation_id=r.id
        AND a.payload_json->'report' IS NOT NULL AND a.payload_json->'report'<>'null'::jsonb AND pg_xact_status(a.xmin::text::xid8)='committed')
      OR (p->>'status'='blocked' AND p->>'execution_state'='committed_known_stop'
       AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events a WHERE a.review_reservation_id=r.id
        AND a.job_id=r.job_id AND a.event_kind='committed' AND pg_xact_status(a.xmin::text::xid8)='committed')
       AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events s WHERE s.review_reservation_id=r.id
        AND s.event_kind='started' AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events d
         WHERE d.review_reservation_id=s.review_reservation_id AND d.role=s.role AND d.event_kind='committed'
          AND d.payload_json->>'started_event_id'=s.id::text AND pg_xact_status(d.xmin::text::xid8)='committed')))
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_probe_events a WHERE a.reservation_id=r.id
       AND a.event_kind='completed' AND a.payload_json->'result' IS NOT NULL AND a.payload_json->'result'<>'null'::jsonb
       AND pg_xact_status(a.xmin::text::xid8)='committed')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_preparations a
       JOIN tutor_item_supply_shared_review_adjudication_events d ON d.preparation_id=a.id AND d.event_kind='committed'
       WHERE a.reservation_id=r.id AND d.payload_json->'report' IS NOT NULL AND d.payload_json->'report'<>'null'::jsonb
        AND pg_xact_status(d.xmin::text::xid8)='committed')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_native_relation_batches a WHERE a.id=dp_relation.id
       AND a.reservation_id=r.id AND a.job_id=r.job_id AND r.lease_generation=(p->>'lease_generation')::bigint)
     ))) THEN RAISE check_violation USING MESSAGE='593 execution closure unsettled or opaque reservation'; END IF;
   ELSE
    dp_count:=0;
    FOR dp_start IN SELECT q.*,q.xmin AS receipt_xmin FROM tutor_item_supply_private_persistent_pack_journal q
     WHERE q.pack_task_id=NEW.pack_task_id AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id
      AND q.record_kind='private_status' AND q.payload_json->>'schema_version'='private_native_stage_v1'
      AND q.payload_json->>'job_id'=p->>'job_id' AND (q.payload_json->>'status'='started'
       OR (q.payload_json->>'status'='committed' AND q.payload_json->>'stage'='review'
        AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal t
         WHERE t.pack_task_id=q.pack_task_id AND t.user_id=q.user_id AND t.epoch=q.epoch AND t.scope_id=q.scope_id
          AND t.operation_key=regexp_replace(q.operation_key,'[.]result$','.started'))
        AND EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.job_id=dp_control.job_id
         AND e.kind='started' AND e.payload_json->'frame'->>'review_id'=q.payload_json->>'receipt_id')))
      ORDER BY q.operation_key LOOP
     dp_count:=dp_count+1;
     SELECT q.*,q.xmin AS receipt_xmin INTO dp_done FROM tutor_item_supply_private_persistent_pack_journal q
      WHERE q.pack_task_id=NEW.pack_task_id AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id AND q.record_kind='private_status'
       AND q.operation_key=regexp_replace(dp_start.operation_key,'[.]started$','.result');
     IF dp_done.id IS NULL OR dp_done.payload_json->>'status' IS DISTINCT FROM 'committed'
      OR dp_done.payload_json->'job_id' IS DISTINCT FROM dp_start.payload_json->'job_id'
      OR dp_done.payload_json->'slot_id' IS DISTINCT FROM dp_start.payload_json->'slot_id'
      OR dp_done.payload_json->'subject_hash' IS DISTINCT FROM dp_start.payload_json->'subject_hash'
      OR dp_done.payload_json->'stage' IS DISTINCT FROM dp_start.payload_json->'stage'
      OR dp_done.payload_json->>'receipt_id' IS NULL
      OR pg_xact_status(dp_start.receipt_xmin::text::xid8) IS DISTINCT FROM 'committed'
      OR pg_xact_status(dp_done.receipt_xmin::text::xid8) IS DISTINCT FROM 'committed' THEN
      RAISE check_violation USING MESSAGE='593 execution closure unresolved PRIVATE START'; END IF;
     IF dp_start.payload_json->'slot_id' IS DISTINCT FROM dp_phase.payload_json->'slot_id' THEN
      RAISE check_violation USING MESSAGE='593 execution closure PRIVATE START slot mismatch'; END IF;
     SELECT z.* INTO dp_receipt FROM (
      SELECT a.id,st.stage,a.id AS artifact_id,a.version_id,a.source_hash,a.content_hash,
       item_supply_internal.snapshot_hash(to_jsonb(a.request_json->>'version')) AS subject_hash
       FROM tutor_item_supply_private_generation_artifacts a
       CROSS JOIN (VALUES('author'::text),('revision'::text)) st(stage)
       WHERE a.user_id=NEW.user_id AND a.epoch=NEW.epoch AND a.scope_id=NEW.scope_id AND a.mode='live'
        AND a.job_id=dp_control.job_id AND a.lease_generation=(p->>'lease_generation')::bigint
        AND EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal b
         WHERE b.pack_task_id=NEW.pack_task_id AND b.user_id=NEW.user_id AND b.epoch=NEW.epoch AND b.scope_id=NEW.scope_id
          AND b.record_kind='private_attachment' AND b.payload_json->>'schema_version'='private_native_auxiliary_v1'
          AND b.payload_json->>'job_id'=p->>'job_id' AND b.payload_json->'request'->'ref'=dp_phase.payload_json->'ref'
          AND b.payload_json->'request'->'request'=a.request_json
          AND ((st.stage='author' AND b.payload_json->'request'->>'schema_version'='private_native_initial_author_v1')
           OR (st.stage='revision' AND b.payload_json->'request'->>'schema_version' IN
            ('private_native_revision_phase_v1','private_native_direct_revision_phase_v1')))
          AND pg_xact_status(b.xmin::text::xid8)='committed')
        AND pg_xact_status(a.xmin::text::xid8)='committed'
      UNION ALL SELECT a.id,a.kind,c.id,c.version_id,c.source_hash,c.content_hash,
       item_supply_internal.snapshot_hash(to_jsonb(CASE a.kind WHEN 'review' THEN a.payload_json->>'artifact_id'
        ELSE a.payload_json->>'parent_review_id' END))
       FROM tutor_item_supply_private_native_quality_evidence a
       JOIN tutor_item_supply_private_generation_artifacts c ON c.id=(CASE a.kind WHEN 'review'
        THEN a.payload_json->>'artifact_id' ELSE a.payload_json->>'parent_artifact_id' END)::uuid
        AND c.user_id=a.user_id AND c.epoch=a.epoch AND c.scope_id=a.scope_id AND c.version_id=a.version_id
       WHERE a.user_id=NEW.user_id AND a.epoch=NEW.epoch AND a.scope_id=NEW.scope_id AND a.pack_task_id=NEW.pack_task_id
        AND a.slot_id=(p->>'slot_id')::uuid AND a.root_id=(dp_phase.payload_json->>'root_id')::uuid
        AND a.kind IN('review','investigation') AND a.job_id=dp_control.job_id
        AND a.payload_json->'ref'=dp_phase.payload_json->'ref'
        AND a.payload_json->'lease'->>'job_id'=p->>'job_id'
        AND a.payload_json->'lease'->'generation'=p->'lease_generation'
        AND (a.kind='investigation' AND EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence parent
          WHERE parent.id=(a.payload_json->>'parent_review_id')::uuid AND parent.kind='review'
           AND parent.user_id=a.user_id AND parent.epoch=a.epoch AND parent.scope_id=a.scope_id
           AND parent.pack_task_id=a.pack_task_id AND parent.slot_id=a.slot_id AND parent.version_id=c.version_id
           AND parent.payload_json->>'artifact_id'=c.id::text AND parent.payload_hash=a.payload_json->>'parent_review_hash')
         OR a.kind='review' AND a.payload_json->'bundle'->'binding'->>'version_key'=c.version_id::text
          AND a.payload_json->'bundle'->'binding'->>'source_hash'=c.source_hash
          AND a.payload_json->'bundle'->'binding'->>'content_hash'=c.content_hash)
        AND pg_xact_status(a.xmin::text::xid8)='committed' AND pg_xact_status(c.xmin::text::xid8)='committed'
      UNION ALL SELECT a.id,st.stage,NULL::uuid,a.version_id,NULL::text,NULL::text,
       item_supply_internal.snapshot_hash(to_jsonb(item_supply_internal.snapshot_hash(b.payload_json->'request'->'payload')))
       FROM tutor_item_supply_private_native_quality_evidence a
       JOIN tutor_item_supply_private_persistent_pack_journal b ON b.id=(a.payload_json->>'preparation_id')::uuid
       CROSS JOIN (VALUES('relation'::text),('fallback_relation'::text)) st(stage)
       WHERE a.user_id=NEW.user_id AND a.epoch=NEW.epoch AND a.scope_id=NEW.scope_id AND a.pack_task_id=NEW.pack_task_id
        AND a.slot_id=(p->>'slot_id')::uuid AND a.root_id=(dp_phase.payload_json->>'root_id')::uuid
        AND a.kind='relation' AND a.job_id=dp_control.job_id AND a.payload_json->'ref'=dp_phase.payload_json->'ref'
        AND a.payload_json->'lease'->>'job_id'=p->>'job_id' AND a.payload_json->'lease'->'generation'=p->'lease_generation'
        AND (b.user_id,b.epoch,b.scope_id,b.pack_task_id)=(a.user_id,a.epoch,a.scope_id,a.pack_task_id)
        AND b.payload_json->>'job_id'=p->>'job_id' AND b.payload_json->'request'->'ref'=a.payload_json->'ref'
        AND b.payload_json->'request'->'lease'->'generation'=p->'lease_generation'
        AND b.payload_json->>'reservation_id'=a.payload_json->>'reservation_id'
        AND (a.payload_json-ARRAY['schema_version','reports','preparation_id','reservation_id','ref','lease'])=
            (b.payload_json->'request'->'payload'-'schema_version')
        AND jsonb_array_length(a.payload_json->'reports')=4
        AND (SELECT array_agg(c->>'role' ORDER BY c->>'role') FROM jsonb_array_elements(a.payload_json->'reports') c)
            =ARRAY['adversarial','ambiguity','curriculum','technical']::text[]
        AND pg_xact_status(a.xmin::text::xid8)='committed' AND pg_xact_status(b.xmin::text::xid8)='committed'
     ) z WHERE z.id=(dp_done.payload_json->>'receipt_id')::uuid AND z.stage=dp_start.payload_json->>'stage'
      AND z.subject_hash=dp_start.payload_json->>'subject_hash';
     IF dp_receipt.id IS NULL THEN RAISE check_violation USING MESSAGE='593 execution closure genuine PRIVATE terminal receipt required'; END IF;
     IF dp_receipt.artifact_id IS NOT NULL THEN
      dp_terminal_artifacts:=array_append(dp_terminal_artifacts,dp_receipt.artifact_id); END IF;
     IF p->>'artifact_id' IS NOT NULL AND dp_receipt.artifact_id IS NOT NULL
      AND p->>'artifact_id' IS DISTINCT FROM dp_receipt.artifact_id::text THEN
      RAISE check_violation USING MESSAGE='593 execution closure PRIVATE outcome artifact mismatch'; END IF;
    END LOOP;
    IF dp_count=0 THEN RAISE check_violation USING MESSAGE='593 execution closure no committed PRIVATE stage'; END IF;
    IF p->>'artifact_id' IS NOT NULL AND NOT ((p->>'artifact_id')::uuid=ANY(dp_terminal_artifacts)) THEN
     RAISE check_violation USING MESSAGE='593 execution closure PRIVATE outcome artifact has no actual terminal'; END IF;
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events s WHERE s.job_id=dp_control.job_id AND s.kind='started'
     AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events d WHERE d.job_id=s.job_id AND d.kind='committed'
       AND (d.user_id,d.epoch,d.scope_id,d.pack_task_id,d.slot_id,d.root_id,d.generation_artifact_id)=
           (s.user_id,s.epoch,s.scope_id,s.pack_task_id,s.slot_id,s.root_id,s.generation_artifact_id)
       AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch AND s.scope_id=NEW.scope_id AND s.pack_task_id=NEW.pack_task_id
       AND s.slot_id=(p->>'slot_id')::uuid AND s.payload_json->'frame'->'lease'->'generation'=p->'lease_generation'
       AND d.action_key=s.action_key AND d.payload_json->'data'->>'claim_id'=s.id::text
       AND d.payload_json->'frame'->'subject'=s.payload_json->'frame'->'subject'
       AND EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence a
        WHERE a.id=(s.payload_json->'frame'->>'review_id')::uuid AND a.kind='review'
         AND a.user_id=s.user_id AND a.epoch=s.epoch AND a.scope_id=s.scope_id AND a.pack_task_id=s.pack_task_id
         AND a.slot_id=s.slot_id AND a.root_id=s.root_id AND a.job_id=s.job_id
         AND a.payload_json->>'artifact_id'=s.generation_artifact_id::text
         AND a.payload_json->'lease'->'generation'=p->'lease_generation'
         AND a.payload_json->'bundle'->'binding'=s.payload_json->'frame'->'subject'->'binding'
         AND pg_xact_status(a.xmin::text::xid8)='committed')
       AND d.payload_json->'data'->'result' IS NOT NULL AND d.payload_json->'data'->'result'<>'null'::jsonb
       AND pg_xact_status(s.xmin::text::xid8)='committed' AND pg_xact_status(d.xmin::text::xid8)='committed')) THEN
     RAISE check_violation USING MESSAGE='593 execution closure unresolved PRIVATE role START'; END IF;
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=dp_control.job_id AND (
     NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_runtime_settlements s WHERE s.reservation_id=r.id
       AND pg_xact_status(s.xmin::text::xid8)='committed') OR NOT (
      EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=r.job_id AND a.mode='live'
        AND r.reservation_key='gen.'||replace(a.candidate_id::text,'-','') AND pg_xact_status(a.xmin::text::xid8)='committed')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence a WHERE a.job_id=r.job_id
        AND a.payload_json->>'reservation_id'=r.id::text AND a.kind IN('review','investigation','relation')
        AND pg_xact_status(a.xmin::text::xid8)='committed')
     ))) THEN RAISE check_violation USING MESSAGE='593 execution closure unsettled or opaque PRIVATE reservation'; END IF;
   END IF;
  END IF;
  IF dp_namespace='shared' AND p->>'artifact_id' IS NOT NULL THEN
   IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=(p->>'artifact_id')::uuid
    AND a.root_id=dp_phase.root_id AND (a.id=dp_artifact.id OR EXISTS(
     SELECT 1 FROM tutor_item_supply_shared_revision_lineage l JOIN tutor_item_supply_shared_revision_preparations x ON x.id=l.preparation_id
     WHERE l.parent_artifact_id=dp_artifact.id AND l.child_artifact_id=a.id AND l.child_job_id=a.job_id
      AND x.payload_json->'parent_lease'->>'job_id'=dp_phase.job_id::text
      AND x.payload_json->'parent_lease'->'generation'=p->'lease_generation'
      AND x.payload_json->'child_lease'->>'generation'=a.lease_generation::text
      AND pg_xact_status(l.xmin::text::xid8)='committed'))
    AND (p->>'published_version_id' IS NULL OR p->>'published_version_id'=a.version_id::text)
    AND pg_xact_status(a.xmin::text::xid8)='committed') THEN
    RAISE check_violation USING MESSAGE='593 execution closure outcome artifact not original phase/child'; END IF;
  END IF;
  IF p->>'published_version_id' IS NOT NULL AND p->>'status'<>'qualified' THEN
   RAISE check_violation USING MESSAGE='593 execution closure publication locator requires qualified receipt'; END IF;
  IF p->>'status'='relation_ready' AND (dp_namespace<>'shared' OR dp_phase.payload_json->>'kind'<>'relation_pack') THEN
   RAISE check_violation USING MESSAGE='593 execution closure relation status requires original relation phase'; END IF;
  IF p->>'status'='qualified' THEN
   IF p->>'execution_state'<>'committed_complete' OR p->>'published_version_id' IS NULL THEN
    RAISE check_violation USING MESSAGE='593 execution closure qualified requires publication'; END IF;
   IF dp_namespace='shared' THEN
    IF NOT EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs q
     JOIN tutor_item_supply_shared_admission_facts f ON f.id=q.facts_receipt_id
     JOIN tutor_item_supply_shared_jobs j ON j.id=f.job_id
     WHERE q.version_id=(p->>'published_version_id')::uuid AND q.generation_artifact_id=(p->>'artifact_id')::uuid
      AND j.id=ANY(dp_jobs) AND pg_xact_status(q.xmin::text::xid8)='committed') THEN
     RAISE check_violation USING MESSAGE='593 execution closure published proof required'; END IF;
   ELSE
    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications q
     JOIN tutor_item_supply_private_native_quality_evidence a ON a.id=q.quality_id WHERE q.pack_task_id=NEW.pack_task_id
     AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id AND q.slot_id=(p->>'slot_id')::uuid
     AND a.job_id=dp_control.job_id AND q.version_id=(p->>'published_version_id')::uuid AND q.state='published'
     AND a.version_id=q.version_id AND EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts g
      WHERE g.id=(p->>'artifact_id')::uuid AND g.user_id=NEW.user_id AND g.epoch=NEW.epoch AND g.scope_id=NEW.scope_id
       AND g.version_id=q.version_id)
     AND pg_xact_status(q.xmin::text::xid8)='committed') THEN
     RAISE check_violation USING MESSAGE='593 execution closure PRIVATE publication required'; END IF;
   END IF;
  ELSIF p->>'execution_state'='committed_complete' AND p->>'status' NOT IN('blocked','relation_ready') THEN
   RAISE check_violation USING MESSAGE='593 execution closure status/state mismatch';
  END IF;
  -- Seal dispatch on the real controls; do not manufacture runtime checkpoints.
  IF dp_namespace='shared' THEN
   IF EXISTS(SELECT 1 FROM tutor_item_supply_private_subscriptions WHERE shared_job_id=ANY(dp_jobs) AND state='active') THEN
    RAISE check_violation USING MESSAGE='593 execution closure active shared consumer retained'; END IF;
   UPDATE tutor_item_supply_shared_job_controls SET state='blocked',breaker_open=true,state_version=state_version+1,
     lease_owner=NULL,lease_expires_at=NULL,updated_at=clock_timestamp() WHERE job_id=ANY(dp_jobs) AND state NOT IN('completed','cancelled','blocked');
  ELSE
   UPDATE tutor_item_supply_private_job_controls SET state='blocked',breaker_open=true,state_version=state_version+1,
    lease_owner=NULL,lease_expires_at=NULL,updated_at=clock_timestamp() WHERE job_id=dp_control.job_id AND state NOT IN('completed','cancelled','blocked');
  END IF;
  RETURN NEW;
 END IF;
 -- An untrusted private_status START may not bypass the original phase owner.
 IF dp_namespace='private' AND NEW.record_kind='private_status' AND p->>'schema_version'='private_native_stage_v1'
  AND p->>'status'='started' THEN
  SELECT q.* INTO dp_phase FROM tutor_item_supply_private_persistent_pack_journal q WHERE q.pack_task_id=NEW.pack_task_id
   AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id AND q.record_kind='phase'
   AND q.payload_json->>'schema_version'='private_native_phase_v1' AND q.payload_json->>'job_id'=p->>'job_id';
  IF dp_phase.id IS NULL THEN RAISE check_violation USING MESSAGE='593 private START original phase required'; END IF;
  PERFORM item_supply_internal.assert_private_native_phase(dp_phase.payload_json,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.pack_task_id);
 END IF;
 IF NEW.record_kind='phase' AND (dp_namespace='shared' OR p->>'schema_version'='private_native_phase_v1') THEN
  IF current_setting('transaction_isolation')<>'read committed' OR dp_public IS NULL THEN
   RAISE check_violation USING MESSAGE='593 receipt-current read committed pack dispatch required'; END IF;
  IF dp_namespace='shared' THEN
   dp_slot:=p->>'public_slot_id';
  ELSE
   SELECT s->>'public_slot_id' INTO dp_slot FROM tutor_item_supply_private_persistent_pack_journal h,
    LATERAL jsonb_array_elements(h.payload_json->'slots') s WHERE h.id=NEW.pack_task_id AND s->>'slot_id'=p->>'slot_id';
   IF p->'lease'->>'lease_owner' LIKE 'private.persistent.relation.phase.%' THEN dp_slot:=NULL; END IF;
  END IF;
  IF dp_namespace='shared' THEN
   SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal q WHERE q.public_task_id=NEW.public_task_id
    AND q.record_kind='phase' AND q.phase_id=NEW.phase_id AND q.job_id=NEW.job_id AND q.root_id=NEW.root_id
    AND q.operation_key=NEW.operation_key AND q.payload_json=p) INTO dp_existing;
  ELSE
   SELECT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal q WHERE q.pack_task_id=NEW.pack_task_id
    AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id AND q.record_kind='phase'
    AND q.operation_key=NEW.operation_key AND q.intent_hash=NEW.intent_hash AND q.payload_json=p) INTO dp_existing;
  END IF;
  -- Exact idempotent rebind still runs ALL original validators below. It is
  -- not another slot and cannot resurrect a sealed control/generation.
  IF NOT dp_existing THEN
  dp_count:=0;
  FOR dp_active IN
   SELECT q.phase_id AS id,q.payload_json->>'public_slot_id' AS slot FROM tutor_item_supply_shared_persistent_pack_journal q
    WHERE q.public_task_id=dp_public AND q.record_kind='phase' AND NOT EXISTS(
     SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal d WHERE d.phase_id=q.phase_id AND d.record_kind='phase_result'
      AND d.payload_json->>'schema_version'='persistent_phase_execution_outcome_v2')
   UNION ALL
   SELECT q.id,(CASE WHEN q.payload_json->'lease'->>'lease_owner' LIKE 'private.persistent.relation.phase.%'
    THEN NULL::text ELSE s->>'public_slot_id' END) FROM tutor_item_supply_private_persistent_pack_journal q
    JOIN tutor_item_supply_private_persistent_pack_journal h ON h.id=q.pack_task_id AND h.record_kind='task',
    LATERAL jsonb_array_elements(h.payload_json->'slots') s
    WHERE h.payload_json->'ref'->>'public_task_id'=dp_public::text AND q.record_kind='phase'
     AND q.payload_json->>'schema_version'='private_native_phase_v1' AND s->>'slot_id'=q.payload_json->>'slot_id'
     AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal d WHERE d.pack_task_id=q.pack_task_id
      AND d.record_kind='private_status' AND d.payload_json->>'schema_version'='persistent_phase_execution_outcome_v2'
      AND d.payload_json->>'phase_id'=q.id::text)
  LOOP
   dp_count:=dp_count+1;
   IF dp_active.slot IS NULL OR dp_slot IS NULL OR dp_active.slot=dp_slot THEN
    RAISE check_violation USING MESSAGE='593 same-slot or package phase already active'; END IF;
  END LOOP;
  IF dp_count>=2 THEN RAISE check_violation USING MESSAGE='593 original pack total slot workers limited to two'; END IF;
  END IF;
 END IF;
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
   SELECT a.*,a.xmin AS row_xmin INTO artifact FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=(p->>'artifact_id')::uuid
    AND a.root_id=NEW.root_id AND a.candidate_id=(p->>'candidate_id')::uuid FOR SHARE;
   IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(artifact.job_id) IS DISTINCT FROM false
    OR artifact.target_id IS DISTINCT FROM p->'specification'->>'target_id'
    OR artifact.target_definition_hash IS DISTINCT FROM p->'specification'->>'target_definition_hash'
    OR artifact.request_json->'blueprint' IS DISTINCT FROM p->'specification'->'blueprint'
    OR artifact.request_json->'public_template' IS DISTINCT FROM p->'specification'->'public_template'
    OR artifact.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'specification'->'coverage_blueprint'->'scope')
   THEN RAISE check_violation USING MESSAGE='523 genuine original candidate artifact specification required'; END IF;
   -- Exact M03 author DATA is legal BEFORE validation preparation (the finite
   -- mismatch is discovered there). It is NOT a validation/admission verdict.
   SELECT q.* INTO m03_phase FROM tutor_item_supply_shared_persistent_pack_journal q
    WHERE q.public_task_id=NEW.public_task_id AND q.record_kind='phase' AND q.root_id=artifact.root_id
     AND q.job_id=artifact.job_id AND q.payload_json->'revision_id'=p->'revision_id'
     AND q.payload_json->'public_slot_id'=p->'public_slot_id'
     AND q.payload_json->'m03_exact'->>'candidate_id'=artifact.candidate_id::text
     AND q.payload_json->'m03_exact'->'specification'=p->'specification'
     AND q.payload_json->'lease'->>'generation'=artifact.lease_generation::text
     AND pg_xact_status(q.xmin::text::xid8)='committed' FOR SHARE;
   IF m03_phase.id IS NOT NULL THEN
    IF pg_xact_status(artifact.row_xmin::text::xid8) IS DISTINCT FROM 'committed'
     OR artifact.request_json->'profile' IS DISTINCT FROM m03_phase.payload_json->'lease'->'profile'
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=artifact.job_id
       AND cp.lease_generation=artifact.lease_generation AND cp.stage='generating' AND cp.status='completed'
       AND cp.receipt_hash=artifact.artifact_hash AND pg_xact_status(cp.xmin::text::xid8)='committed')
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s
       JOIN tutor_item_supply_shared_reservations r ON r.id=s.reservation_id AND r.id=artifact.reservation_id
        AND r.job_id=artifact.job_id AND r.root_id=artifact.root_id AND r.lease_generation=artifact.lease_generation
        AND r.reservation_key='gen.'||replace(artifact.candidate_id::text,'-','')
       WHERE s.reservation_id=artifact.reservation_id
       AND s.settlement_key='generation.'||replace(artifact.candidate_id::text,'-','') AND s.usage_state='known'
       AND s.receipt_hash=item_supply_internal.snapshot_hash(artifact.receipt_json->'provider')
       AND pg_xact_status(s.xmin::text::xid8)='committed' AND pg_xact_status(r.xmin::text::xid8)='committed')
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal s
       JOIN tutor_item_supply_shared_persistent_pack_journal d ON d.phase_id=s.phase_id AND d.record_kind='stage_result'
        AND d.operation_key=s.operation_key
       WHERE s.phase_id=m03_phase.phase_id AND s.record_kind='stage_started' AND s.payload_json->>'stage'='author'
        AND s.operation_key='persistent.stage.'||replace(p->>'revision_id','-','')||'.author'
        AND d.payload_json->>'stage'='author' AND d.payload_json->>'outcome'='completed'
        AND d.payload_json->>'receipt_id'=artifact.id::text
        AND pg_xact_status(s.xmin::text::xid8)='committed' AND pg_xact_status(d.xmin::text::xid8)='committed')
    THEN RAISE check_violation USING MESSAGE='593 M03 version DATA exact prior-committed author receipt required'; END IF;
    m03_data:=true;
    IF m03_phase.payload_json->'m03_exact'->>'schema_version'='m03_author_preflight_subject_v1' THEN
     m03_context:=m03_phase.payload_json->'m03_exact'->'repair_context';
     SELECT q.* INTO m03_parent FROM tutor_item_supply_shared_persistent_pack_journal q
      WHERE q.public_task_id=NEW.public_task_id AND q.record_kind='version'
       AND q.payload_json=m03_phase.payload_json->'m03_exact'->'parent_version'
       AND pg_xact_status(q.xmin::text::xid8)='committed' FOR SHARE;
     SELECT a.* INTO m03_pa FROM tutor_item_supply_shared_generation_artifacts a
      WHERE a.id=(m03_context->>'parent_artifact_id')::uuid AND pg_xact_status(a.xmin::text::xid8)='committed' FOR SHARE;
     IF m03_parent.id IS NULL OR m03_pa.id IS NULL
      OR artifact.request_json->'author_preflight_repair' IS DISTINCT FROM m03_context
      OR p->'parent_revision_id' IS DISTINCT FROM m03_parent.payload_json->'revision_id'
      OR (p->>'revision_seq')::integer IS DISTINCT FROM (m03_parent.payload_json->>'revision_seq')::integer+1
      OR m03_parent.payload_json->>'artifact_id' IS DISTINCT FROM m03_pa.id::text
      OR m03_context->'parent_source' IS DISTINCT FROM m03_pa.source_json
      OR m03_context->>'parent_artifact_hash' IS DISTINCT FROM m03_pa.artifact_hash
      OR artifact.request_json->'materials' IS DISTINCT FROM m03_pa.request_json->'materials'
      OR artifact.request_json->'limits' IS DISTINCT FROM m03_pa.request_json->'limits'
      OR artifact.request_json->>'item_key' IS DISTINCT FROM m03_pa.request_json->>'item_key'
      OR artifact.request_json->'blueprint' IS DISTINCT FROM m03_pa.request_json->'blueprint'
      OR artifact.request_json->>'version' IS DISTINCT FROM (m03_pa.request_json->>'version')||'.repair1'
     THEN RAISE check_violation USING MESSAGE='593 M03 preflight child actual request parent and version required'; END IF;
     -- Comparison only: never UPDATE the authored source/gold. The original
     -- AuthorPreflightRepairOwner is the oracle/issuer; receiver binds its exact
     -- committed preparation context and checks its expected-only child diff.
     m03_expected:=jsonb_set(jsonb_set(m03_pa.source_json,'{public,version}',m03_context->'child_version'),
       '{private,version}',m03_context->'child_version');
     FOR m03_f IN SELECT value FROM jsonb_array_elements(m03_context->'findings') LOOP
      SELECT (t.ordinality-1)::integer INTO m03_index
       FROM jsonb_array_elements(m03_pa.source_json->'private'->'content'->'tests') WITH ORDINALITY t(value,ordinality)
       WHERE t.value->'id'=m03_f.value->'case_id' AND t.value->'order_index'=m03_f.value->'order_index'
        AND t.value->'expected_output'=m03_f.value->'actual_expected';
      IF m03_index IS NULL THEN RAISE check_violation USING MESSAGE='593 M03 preflight immutable finding missing'; END IF;
      m03_expected:=jsonb_set(m03_expected,ARRAY['private','content','tests',m03_index::text,'expected_output'],m03_f.value->'oracle_expected');
     END LOOP;
     IF artifact.source_json IS DISTINCT FROM m03_expected THEN
      RAISE check_violation USING MESSAGE='593 M03 preflight child must preserve every nonexpected field'; END IF;
     m03_repair_data:=true;
    ELSIF artifact.request_json ? 'author_preflight_repair' THEN
     RAISE check_violation USING MESSAGE='593 M03 preflight child requires original dedicated phase';
    END IF;
   END IF;
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
    IF NOT FOUND AND NOT committed_child_data AND NOT m03_data THEN RAISE check_violation USING MESSAGE='523 original full-spec validation preparation required'; END IF;
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
    IF NOT FOUND AND NOT m03_repair_data THEN RAISE check_violation USING MESSAGE='523 original same-item substantive revision required'; END IF;
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
   SELECT q.*,q.xmin AS row_xmin INTO phase FROM tutor_item_supply_shared_persistent_pack_journal q WHERE phase_id=NEW.phase_id AND record_kind='phase' FOR SHARE;
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
    IF phase.payload_json ? 'm03_exact' AND pg_xact_status(phase.row_xmin::text::xid8) IS DISTINCT FROM 'committed' THEN
     RAISE check_violation USING MESSAGE='593 M03 START requires prior-COMMIT original exact phase'; END IF;
    IF NEW.record_kind='stage_started' AND p->>'stage'='author' AND phase.payload_json ? 'm03_exact'
     AND phase.payload_json->'m03_exact'->>'schema_version'='m03_exact_candidate_subject_v1'
     AND phase.payload_json->>'operation_key' NOT LIKE 'm03.g.initial.%' THEN
     RAISE check_violation USING MESSAGE='593 M03 committed quality phase cannot dispatch an author'; END IF;
    IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=NEW.phase_id AND record_kind='phase_result')
    THEN RAISE check_violation USING MESSAGE='523 terminal phase cannot dispatch'; END IF;
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $source593_0$;
 original pg_proc%ROWTYPE; revised pg_proc%ROWTYPE; definition text;
BEGIN
 SELECT * INTO original FROM pg_proc WHERE oid=to_regprocedure(signature);
 IF current_database()<>'aearn_b1d_sandbox_20261001'
  OR original.oid IS NULL OR NOT original.prosecdef OR original.prokind<>'f'
  OR original.proowner IS DISTINCT FROM to_regrole('aearn_b1d_runtime_20261001')::oid
  OR original.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR original.provolatile IS DISTINCT FROM 'v'::"char"
  OR original.proparallel IS DISTINCT FROM 'u'::"char"
  OR original.proisstrict IS DISTINCT FROM false
  OR original.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
  RAISE check_violation USING MESSAGE='593 installed original receiver attributes required'; END IF;
 IF md5(original.prosrc)=revised_md5 THEN RETURN; END IF;
 IF md5(original.prosrc)<>baseline_md5 OR md5(revised_source)<>revised_md5 THEN
  RAISE check_violation USING MESSAGE='593 installed raw receiver baseline changed'; END IF;
 definition:=pg_get_functiondef(original.oid);
 IF strpos(definition,original.prosrc)=0 THEN RAISE check_violation USING MESSAGE='593 original function definition mismatch'; END IF;
 EXECUTE replace(definition,original.prosrc,revised_source);
 SELECT * INTO revised FROM pg_proc WHERE oid=original.oid;
 IF md5(revised.prosrc)<>revised_md5 OR (to_jsonb(revised)-'prosrc') IS DISTINCT FROM (to_jsonb(original)-'prosrc') THEN
  RAISE check_violation USING MESSAGE='593 receiver attributes/ACL changed'; END IF;
END $dp593_0$;

DO $dp593_1$
DECLARE signature constant text := 'item_supply_internal.assert_persistent_pack_phase(jsonb)';
 baseline_md5 constant text := '91a0dc603c6f5dcdd11ed2f54c18dbd9'; revised_md5 constant text := 'e56a832f2924fcd120cbd53d6acaafb3';
 revised_source constant text := $source593_1$
DECLARE c record; b record; phase record; stamp timestamptz;
 m jsonb; ms jsonb; mc jsonb; mslot text; mcase record; mh record; mj record;
 mp record; ma record; mf record; mclosure record; mknown record;
BEGIN

 PERFORM pg_advisory_xact_lock(hashtext('persistent-pack-dispatch'),hashtext(p->>'public_task_id'));
 IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal q WHERE q.phase_id=(p->>'phase_id')::uuid
  AND q.record_kind='phase_result' AND q.payload_json->>'schema_version'='persistent_phase_execution_outcome_v2') THEN
  RAISE check_violation USING MESSAGE='593 execution-closed shared phase cannot dispatch'; END IF;
 IF item_supply_internal.snapshot_keys(CASE WHEN p ? 'm03_exact' THEN p-'m03_exact' ELSE p END,ARRAY['schema_version','public_task_id','public_slot_id','phase_id','revision_id','kind','operation_key','job_id','root_id','batch_id','lease','valid_until','frame_hash','anchor_version_id','candidate_version_ids']) IS DISTINCT FROM true
  OR p->>'frame_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p-'frame_hash')
 THEN RAISE check_violation USING MESSAGE='523 exact phase schema/frame required'; END IF;
 IF p->>'schema_version' IS DISTINCT FROM 'persistent_public_phase_v1'
  OR COALESCE(p->>'kind' IN('candidate','relation_pack'),false) IS DISTINCT FROM true OR p->'lease'->>'visibility' IS DISTINCT FROM 'public'
  OR p->'lease'->>'owner_id' IS NOT NULL OR p->'lease'->>'owner_epoch' IS NOT NULL
  OR COALESCE(p->>'frame_hash' ~ '^[0-9a-f]{64}$',false) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(p->'lease',ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
  OR p->>'job_id' IS DISTINCT FROM p->'lease'->>'job_id'
  OR COALESCE(p->>'operation_key' ~ '^[a-z0-9][a-z0-9._:-]{2,159}$',false) IS DISTINCT FROM true
  OR COALESCE(p->>'valid_until' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
  OR jsonb_typeof(p->'candidate_version_ids') IS DISTINCT FROM 'array'
  THEN RAISE check_violation USING MESSAGE='523 closed public phase required'; END IF;
 IF p->>'kind'='relation_pack' THEN
  IF p->'public_slot_id' IS DISTINCT FROM 'null'::jsonb OR p->'revision_id' IS DISTINCT FROM 'null'::jsonb
   OR jsonb_array_length(p->'candidate_version_ids') IS DISTINCT FROM 5
   OR (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p->'candidate_version_ids'))<>5
   OR COALESCE(p->'candidate_version_ids' @> jsonb_build_array(p->>'anchor_version_id'),false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='523 exact five relation versions required'; END IF;
 ELSE
  IF p->'anchor_version_id' IS DISTINCT FROM 'null'::jsonb OR p->'candidate_version_ids' IS DISTINCT FROM '[]'::jsonb
   OR COALESCE(p->>'public_slot_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
   OR COALESCE(p->>'revision_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='523 exact candidate slot revision required'; END IF;
 END IF;
 SELECT j.root_id,ctrl.* INTO c FROM tutor_item_supply_shared_jobs j
 JOIN tutor_item_supply_shared_job_controls ctrl ON ctrl.job_id=j.id WHERE j.id=(p->>'job_id')::uuid FOR SHARE OF j FOR UPDATE OF ctrl;
 IF NOT FOUND OR c.root_id IS DISTINCT FROM (p->>'root_id')::uuid OR c.state<>'leased'
  OR c.lease_owner IS DISTINCT FROM p->'lease'->>'lease_owner'
  OR c.lease_generation::text IS DISTINCT FROM p->'lease'->>'generation'
  OR c.state_version<(p->'lease'->>'state_version')::integer
  OR c.parent_deadline IS DISTINCT FROM (p->'lease'->>'parent_deadline')::timestamptz
  OR (p->'lease'->>'expires_at')::timestamptz>c.lease_expires_at
  OR jsonb_typeof(p->'lease'->'generation') IS DISTINCT FROM 'number'
  OR jsonb_typeof(p->'lease'->'state_version') IS DISTINCT FROM 'number'
  OR (CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END) IS DISTINCT FROM p->'lease'->'profile'
  OR item_supply_internal.controlled_counterexample_held(c.job_id) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='523 original current public lease required'; END IF;
 SELECT batches.* INTO b FROM tutor_item_supply_development_model_accounting_batches batches
 JOIN tutor_item_supply_development_model_accounting_jobs bindings ON bindings.batch_id=batches.id
 WHERE batches.id=(p->>'batch_id')::uuid AND batches.root_id=(p->>'root_id')::uuid
 AND bindings.job_id=(p->>'job_id')::uuid AND bindings.lease_generation=c.lease_generation
 AND bindings.lease_owner=c.lease_owner AND bindings.parent_deadline=c.parent_deadline FOR SHARE OF batches,bindings;
 IF NOT FOUND OR b.authorization_key<>'development-unlimited-model-calls-20261010'
  OR c.parent_deadline>b.valid_until OR b.valid_until>b.started_at+interval '7200 seconds'
 THEN RAISE check_violation USING MESSAGE='523 original517 accounting binding required'; END IF;
 -- 593 M03: a complete subject is received BEFORE the first START, never
 -- retrofitted onto a direct job. Frozen full-spec pins below are pure original
 -- build_specs DATA (retained original G materials + approved SQLite lock), not
 -- source/current authority; every original live fence below remains mandatory.
 IF p ? 'm03_exact' THEN
  m:=p->'m03_exact';ms:=m->'specification';mc:=m->'repair_context';
  SELECT q.* INTO phase FROM tutor_item_supply_shared_persistent_pack_journal q
   WHERE q.phase_id=(p->>'phase_id')::uuid AND q.record_kind='phase' FOR SHARE;
  IF FOUND AND phase.payload_json IS DISTINCT FROM p THEN
   RAISE check_violation USING MESSAGE='593 M03 stored original phase subject cannot change'; END IF;
  IF p->>'kind' IS DISTINCT FROM 'candidate'
   OR (CASE m->>'schema_version'
    WHEN 'm03_exact_candidate_subject_v1' THEN item_supply_internal.snapshot_keys(m,ARRAY['schema_version','candidate_id','specification'])
    WHEN 'm03_author_preflight_subject_v1' THEN item_supply_internal.snapshot_keys(m,ARRAY['schema_version','candidate_id','specification','parent_phase_id','parent_version','repair_context'])
    ELSE false END) IS DISTINCT FROM true
   OR item_supply_internal.snapshot_keys(ms,ARRAY['schema_version','target_id','target_definition_hash','family_definition_hash','allocation','seed','blueprint','public_template','coverage_blueprint','python_goal','sql_target']) IS DISTINCT FROM true
   OR ms->>'schema_version' IS DISTINCT FROM 'finite_candidate_spec_v1'
   OR ms->>'target_id' IS DISTINCT FROM 'sqlite-predicate-order-v1'
   OR COALESCE(m->>'candidate_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='593 M03 closed exact candidate subject required'; END IF;
  mslot:=split_part(ms->'allocation'->>'variant_id',':',2);
  SELECT * INTO mcase FROM (VALUES
   ('assessment-1','92be1066-54a0-443f-af3d-42eccdbec695'::uuid,'22b8953f-3177-4cfd-936f-cc77060665ee'::uuid,
    '2df2f73a3042f7d36d4161cea8fef367cc8189c1cceaba748632301e6811a981'),
   ('assessment-2','109f2b9b-78b3-4f07-971d-7aa59887eb2c'::uuid,'22b8953f-3177-4cfd-936f-cc77060665ee'::uuid,
    'b9f50ab2c979d9af56ff8ff292f04c32fad6a8154d89cc436d9f728e1704e113'),
   ('guided-remediation','ab725fd9-1b9f-43f0-ab1f-4c1dabee2efa'::uuid,'22f7944a-73c3-4988-9060-2ea8030b844c'::uuid,
    '8c1ee109cb04bad1967aa95338642ef2c7d24ad2da791651a3276275477d728c')
   ) q(slot,candidate_id,root_id,specification_hash) WHERE q.slot=mslot;
  SELECT * INTO mh FROM tutor_item_supply_shared_persistent_pack_journal
   WHERE record_kind='task' AND public_task_id=(p->>'public_task_id')::uuid FOR SHARE;
  SELECT * INTO mj FROM tutor_item_supply_shared_jobs WHERE id=c.job_id FOR SHARE;
  IF mcase.slot IS NULL OR mh.id IS NULL OR mj.id IS NULL
   OR mh.payload_json->>'target_id' IS DISTINCT FROM ms->>'target_id'
   OR mh.payload_json->>'target_definition_hash' IS DISTINCT FROM ms->>'target_definition_hash'
   OR p->'public_slot_id' IS DISTINCT FROM mh.payload_json->'public_slots'->
      (array_position(ARRAY['practice-1','practice-2','assessment-1','assessment-2','guided-remediation'],mslot)-1)
   OR p->>'root_id' IS DISTINCT FROM mcase.root_id::text
   OR item_supply_internal.snapshot_hash(jsonb_set(ms,'{public_template,version}','"v1"'::jsonb)) IS DISTINCT FROM mcase.specification_hash
   OR c.lease_generation<>1 OR c.attempt_count<>1 OR mj.parent_job_id IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_blueprints bp ON bp.id=r.blueprint_id
     WHERE r.id=mcase.root_id AND bp.snapshot_json=ms->'coverage_blueprint')
   OR NOT EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs n
     JOIN tutor_item_supply_shared_generation_artifacts a ON a.id=n.generation_artifact_id
     JOIN tutor_item_supply_shared_job_controls ctrl ON ctrl.job_id=a.job_id
     JOIN tutor_item_supply_parameter_profiles pr ON pr.id=ctrl.profile_id
     WHERE n.version_id='1fe141fb-66f8-5b42-8258-116a1c5d04d0'
      AND pr.profile_hash=p->'lease'->'profile'->>'profile_hash')
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal q
     WHERE q.record_kind='phase' AND q.job_id=c.job_id AND q.phase_id<>(p->>'phase_id')::uuid)
  THEN RAISE check_violation USING MESSAGE='593 M03 original slot full-spec root profile and fresh exact job required'; END IF;
  IF m->>'schema_version'='m03_author_preflight_subject_v1' THEN
   IF item_supply_internal.snapshot_keys(mc,ARRAY['schema_version','repair_round','reason','parent_artifact_id','parent_artifact_hash',
     'parent_request_hash','parent_source_hash','parent_content_hash','parent_specification_hash','child_specification_hash',
     'root_id','scope_hash','slot','family_id','seed','child_candidate_id','item_key','child_version','parent_source','child_public_template','findings']) IS DISTINCT FROM true
    OR mc->>'schema_version' IS DISTINCT FROM 'author_preflight_repair_context_v1'
    OR mc->'repair_round' IS DISTINCT FROM '1'::jsonb
    OR mc->>'reason' IS DISTINCT FROM 'finite_sql_private_expectation_mismatch'
   THEN RAISE check_violation USING MESSAGE='593 M03 original author-preflight context required'; END IF;
   SELECT q.* INTO mp FROM tutor_item_supply_shared_persistent_pack_journal q
    WHERE q.public_task_id=(p->>'public_task_id')::uuid AND q.record_kind='version'
     AND q.payload_json=m->'parent_version' AND pg_xact_status(q.xmin::text::xid8)='committed' FOR SHARE;
   SELECT * INTO ma FROM tutor_item_supply_shared_generation_artifacts
    WHERE id=(mc->>'parent_artifact_id')::uuid AND pg_xact_status(xmin::text::xid8)='committed' FOR SHARE;
   SELECT q.* INTO mf FROM tutor_item_supply_shared_persistent_pack_journal q
    WHERE q.phase_id=(m->>'parent_phase_id')::uuid AND q.public_task_id=(p->>'public_task_id')::uuid
     AND q.record_kind='phase' AND pg_xact_status(q.xmin::text::xid8)='committed' FOR SHARE;
   SELECT q.* INTO mclosure FROM tutor_item_supply_shared_persistent_pack_journal q
    WHERE q.phase_id=mf.phase_id AND q.record_kind='phase_result'
     AND q.payload_json->>'schema_version'='persistent_phase_execution_outcome_v2'
     AND pg_xact_status(q.xmin::text::xid8)='committed' FOR SHARE;
   SELECT q.* INTO mknown FROM tutor_item_supply_shared_runtime_settlements q
    JOIN tutor_item_supply_shared_reservations r ON r.id=q.reservation_id AND r.id=ma.reservation_id
     AND r.job_id=ma.job_id AND r.root_id=ma.root_id AND r.lease_generation=ma.lease_generation
     AND r.reservation_key='gen.'||replace(ma.candidate_id::text,'-','')
    WHERE q.reservation_id=ma.reservation_id AND q.settlement_key='generation.'||replace(ma.candidate_id::text,'-','')
     AND pg_xact_status(q.xmin::text::xid8)='committed' AND pg_xact_status(r.xmin::text::xid8)='committed' FOR SHARE OF q,r;
   IF mp.id IS NULL OR ma.id IS NULL OR mf.id IS NULL OR mclosure.id IS NULL OR mknown.id IS NULL
    OR ma.candidate_id IS DISTINCT FROM mcase.candidate_id OR ma.root_id IS DISTINCT FROM mcase.root_id
    OR ma.request_json ? 'author_preflight_repair'
    OR mp.payload_json->>'artifact_id' IS DISTINCT FROM ma.id::text
    OR mp.payload_json->>'candidate_id' IS DISTINCT FROM ma.candidate_id::text
    OR mp.payload_json->'public_slot_id' IS DISTINCT FROM p->'public_slot_id'
    OR mp.payload_json->>'root_id' IS DISTINCT FROM p->>'root_id'
    OR item_supply_internal.snapshot_hash(mp.payload_json->'specification') IS DISTINCT FROM mcase.specification_hash
    OR mf.job_id IS DISTINCT FROM ma.job_id OR mf.root_id IS DISTINCT FROM ma.root_id
    OR mf.payload_json->'lease'->>'generation' IS DISTINCT FROM ma.lease_generation::text
    OR mf.payload_json->'revision_id' IS DISTINCT FROM mp.payload_json->'revision_id'
    OR mf.payload_json->'public_slot_id' IS DISTINCT FROM p->'public_slot_id'
    OR mf.payload_json->'m03_exact'->>'schema_version' IS DISTINCT FROM 'm03_exact_candidate_subject_v1'
    OR mf.payload_json->'m03_exact'->>'candidate_id' IS DISTINCT FROM ma.candidate_id::text
    OR mf.payload_json->'m03_exact'->'specification' IS DISTINCT FROM mp.payload_json->'specification'
    OR mclosure.payload_json->>'phase_hash' IS DISTINCT FROM mf.payload_json->>'frame_hash'
    OR mclosure.payload_json->>'artifact_id' IS DISTINCT FROM ma.id::text
    OR mclosure.payload_json->>'status' IS DISTINCT FROM 'quality_failed'
    OR mclosure.payload_json->>'execution_state' IS DISTINCT FROM 'committed_known_stop'
    OR mclosure.payload_json->>'safe_reason' IS DISTINCT FROM 'm03_original_author_preflight_repair_required'
    OR mknown.usage_state IS DISTINCT FROM 'known'
    OR mknown.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(ma.receipt_json->'provider')
    OR ma.artifact_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('source',ma.source_json,'receipt',ma.receipt_json,'request',ma.request_json))
    OR mc->>'parent_artifact_hash' IS DISTINCT FROM ma.artifact_hash
    OR mc->>'parent_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ma.request_json)
    OR mc->>'parent_source_hash' IS DISTINCT FROM ma.source_hash OR mc->>'parent_content_hash' IS DISTINCT FROM ma.content_hash
    OR mc->'parent_source' IS DISTINCT FROM ma.source_json
    OR mc->>'parent_specification_hash' IS DISTINCT FROM mcase.specification_hash
    OR mc->>'child_specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ms)
    OR mc->>'root_id' IS DISTINCT FROM p->>'root_id' OR mc->>'scope_hash' IS DISTINCT FROM ma.request_json->>'scope_hash'
    OR mc->>'slot' IS DISTINCT FROM mslot OR mc->'family_id' IS DISTINCT FROM ms->'allocation'->'family_id'
    OR mc->'seed' IS DISTINCT FROM ms->'seed' OR mc->'child_candidate_id' IS DISTINCT FROM m->'candidate_id'
    OR mc->'item_key' IS DISTINCT FROM ma.request_json->'item_key'
    OR mc->>'child_version' IS DISTINCT FROM (ma.request_json->>'version')||'.repair1'
    OR mc->'child_version' IS DISTINCT FROM ms->'public_template'->'version'
    OR mc->'child_public_template' IS DISTINCT FROM ms->'public_template'
    OR p->'lease'->'profile'->'values' IS DISTINCT FROM ma.request_json->'profile'->'values'
    OR p->'lease'->'profile'->'profile_key_hash' IS DISTINCT FROM ma.request_json->'profile'->'profile_key_hash'
    OR mj.id=ma.job_id OR m->'candidate_id'=to_jsonb(ma.candidate_id::text)
    OR mj.job_key IS DISTINCT FROM encode(sha256(convert_to(p->>'root_id'||chr(31)||'author-preflight.'||replace(ma.id::text,'-','')||'.repair1','UTF8')),'hex')
    OR p->>'operation_key' IS DISTINCT FROM 'm03.g.author-preflight.'||replace(ma.id::text,'-','')||'.'||item_supply_internal.snapshot_hash(ms)||'.frame.1'
    OR jsonb_typeof(mc->'findings') IS DISTINCT FROM 'array' OR jsonb_array_length(mc->'findings')<1
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=ma.job_id
      AND cp.lease_generation=ma.lease_generation AND cp.stage='generating' AND cp.status='completed'
      AND cp.receipt_hash=ma.artifact_hash AND pg_xact_status(cp.xmin::text::xid8)='committed')
   THEN RAISE check_violation USING MESSAGE='593 M03 exact prior-committed preflight parent receipt context and once required'; END IF;
   IF EXISTS(SELECT 1 FROM jsonb_array_elements(mc->'findings') f WHERE
     item_supply_internal.snapshot_keys(f,ARRAY['case_id','order_index','actual_expected','oracle_expected']) IS DISTINCT FROM true
     OR f->'actual_expected'=f->'oracle_expected'
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(ma.source_json->'private'->'content'->'tests') t
       WHERE t->'id'=f->'case_id' AND t->'order_index'=f->'order_index' AND t->'expected_output'=f->'actual_expected')) THEN
    RAISE check_violation USING MESSAGE='593 M03 preflight findings must reference immutable parent tests'; END IF;
  ELSIF m->>'candidate_id'=mcase.candidate_id::text AND ms->'public_template'->>'version'='v1'
    AND p->>'operation_key'='m03.g.initial.'||replace(mcase.candidate_id::text,'-','')||'.'||mcase.specification_hash||'.frame.1' THEN
   IF mj.job_key IS DISTINCT FROM encode(sha256(convert_to(p->>'root_id'||chr(31)||'m03.g.initial.'||replace(mcase.candidate_id::text,'-',''),'UTF8')),'hex')
    OR mj.created_at<b.started_at THEN RAISE check_violation USING MESSAGE='593 M03 exact original fresh initial job required'; END IF;
  ELSE
   PERFORM v.id FROM tutor_item_supply_shared_persistent_pack_journal v
    JOIN tutor_item_supply_shared_generation_artifacts a ON a.id=(v.payload_json->>'artifact_id')::uuid
    WHERE v.public_task_id=(p->>'public_task_id')::uuid AND v.record_kind IN('version','qualified')
     AND v.payload_json->'revision_id'=p->'revision_id' AND v.payload_json->'public_slot_id'=p->'public_slot_id'
     AND v.root_id=c.root_id AND v.payload_json->'candidate_id'=m->'candidate_id' AND v.payload_json->'specification'=ms
     AND a.candidate_id=(m->>'candidate_id')::uuid AND a.root_id=c.root_id
     AND a.request_json->'blueprint'=ms->'blueprint' AND a.request_json->'public_template'=ms->'public_template'
     AND pg_xact_status(v.xmin::text::xid8)='committed' AND pg_xact_status(a.xmin::text::xid8)='committed' FOR SHARE OF v,a;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='593 M03 committed subject requires exact original version artifact'; END IF;
  END IF;
 END IF;
 stamp:=clock_timestamp();
 IF c.lease_expires_at<=stamp OR c.parent_deadline<=stamp OR b.valid_until<=stamp
  OR (p->>'valid_until')::timestamptz<=stamp
  OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,(p->'lease'->>'expires_at')::timestamptz,c.parent_deadline,b.valid_until,
   (p->'lease'->'profile'->>'bound_at')::timestamptz+
   (p->'lease'->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='523 phase deadline expired or extended'; END IF;
END $source593_1$;
 original pg_proc%ROWTYPE; revised pg_proc%ROWTYPE; definition text;
BEGIN
 SELECT * INTO original FROM pg_proc WHERE oid=to_regprocedure(signature);
 IF current_database()<>'aearn_b1d_sandbox_20261001'
  OR original.oid IS NULL OR NOT original.prosecdef OR original.prokind<>'f'
  OR original.proowner IS DISTINCT FROM to_regrole('aearn_b1d_runtime_20261001')::oid
  OR original.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR original.provolatile IS DISTINCT FROM 'v'::"char"
  OR original.proparallel IS DISTINCT FROM 'u'::"char"
  OR original.proisstrict IS DISTINCT FROM false
  OR original.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
  RAISE check_violation USING MESSAGE='593 installed original receiver attributes required'; END IF;
 IF md5(original.prosrc)=revised_md5 THEN RETURN; END IF;
 IF md5(original.prosrc)<>baseline_md5 OR md5(revised_source)<>revised_md5 THEN
  RAISE check_violation USING MESSAGE='593 installed raw receiver baseline changed'; END IF;
 definition:=pg_get_functiondef(original.oid);
 IF strpos(definition,original.prosrc)=0 THEN RAISE check_violation USING MESSAGE='593 original function definition mismatch'; END IF;
 EXECUTE replace(definition,original.prosrc,revised_source);
 SELECT * INTO revised FROM pg_proc WHERE oid=original.oid;
 IF md5(revised.prosrc)<>revised_md5 OR (to_jsonb(revised)-'prosrc') IS DISTINCT FROM (to_jsonb(original)-'prosrc') THEN
  RAISE check_violation USING MESSAGE='593 receiver attributes/ACL changed'; END IF;
END $dp593_1$;

DO $dp593_2$
DECLARE signature constant text := 'item_supply_internal.private_pack_bind_phase(jsonb,jsonb)';
 baseline_md5 constant text := '895967eb654e3da5bf0b336556c73566'; revised_md5 constant text := 'af95a3b44ea0f9db1ec8d11629178d7a';
 revised_source constant text := $source593_2$
DECLARE t record;j record;c record;prior record;entry jsonb;rid uuid:=gen_random_uuid();stamp timestamptz;deadline timestamptz;p jsonb;
BEGIN
 PERFORM item_supply_internal.private_native_epoch((r->>'user_id')::uuid,(r->>'epoch')::bigint);

 PERFORM pg_advisory_xact_lock(hashtext('persistent-pack-dispatch'),hashtext((SELECT h.payload_json->'ref'->>'public_task_id'
  FROM tutor_item_supply_private_persistent_pack_journal h WHERE h.id=(r->>'pack_task_id')::uuid AND h.record_kind='task')));
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(r->>'pack_task_id')::uuid
  AND pack_task_id=id AND record_kind='task' AND user_id=(r->>'user_id')::uuid
  AND epoch=(r->>'epoch')::bigint AND scope_id=(r->>'scope_id')::uuid FOR SHARE;
 SELECT s INTO entry FROM jsonb_array_elements(t.payload_json->'slots') s
  WHERE s->>'slot_id'=r->>'slot_id' AND s->>'logical_item_id'=r->>'business_item_id';
 IF t.id IS NULL OR entry IS NULL OR l->>'visibility' IS DISTINCT FROM 'private'
  OR l->>'owner_id' IS DISTINCT FROM r->>'user_id' OR l->>'owner_epoch' IS DISTINCT FROM r->>'epoch' THEN
  RAISE check_violation USING MESSAGE='524 original fixed PRIVATE task/slot/lease required'; END IF;
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=(l->>'job_id')::uuid AND user_id=t.user_id
  AND epoch=t.epoch AND scope_id=t.scope_id AND root_id=(r->>'root_id')::uuid FOR SHARE;
 SELECT * INTO c FROM tutor_item_supply_private_job_controls WHERE job_id=j.id AND user_id=t.user_id AND epoch=t.epoch FOR SHARE;
 stamp:=clock_timestamp();deadline:=LEAST(c.lease_expires_at,c.parent_deadline,(l->>'expires_at')::timestamptz,(l->>'parent_deadline')::timestamptz,
  (l->'profile'->>'bound_at')::timestamptz+(l->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF j.id IS NULL OR c.state NOT IN('leased','generating','validating','reviewing','investigating','revising','simulating','admitting') OR c.lease_owner IS DISTINCT FROM l->>'lease_owner'
  OR c.lease_generation::text IS DISTINCT FROM l->>'generation' OR deadline IS NULL OR stamp>=deadline THEN
  RAISE check_violation USING MESSAGE='524 current original PRIVATE job control required'; END IF;
 -- Each PRIVATE domain root is fixed for this task, including after technical expiry.
 SELECT * INTO prior FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=t.id
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1;
 IF prior.id IS NOT NULL AND prior.payload_json->>'root_id' IS DISTINCT FROM r->>'root_id' THEN
  RAISE check_violation USING MESSAGE='524 PRIVATE canonical root cannot reroll'; END IF;
 p:=jsonb_build_object('schema_version','private_native_phase_v1','root_id',r->>'root_id','job_id',l->>'job_id',
  'slot_id',r->>'slot_id','business_item_id',r->>'business_item_id','goal_scope_id',r->>'goal_scope_id',
  'ref',r,'lease',l,'valid_until',deadline);
 PERFORM item_supply_internal.assert_private_native_phase(p,t.user_id,t.epoch,t.scope_id,t.id);
 PERFORM item_supply_internal.private_native_mapping_current((r->>'mapping_receipt_id')::uuid,t.user_id,t.epoch);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_finite_course_mappings m,
  LATERAL jsonb_array_elements(m.receipt_json->'pack_request'->'demands') d
  WHERE m.id=(r->>'mapping_receipt_id')::uuid AND m.user_id=t.user_id AND m.epoch=t.epoch
  AND d->>'slot'=r->>'slot' AND d->>'storage_scope_id'=r->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 real role goal scope required, not copied storage scope'; END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal
  (id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(rid,t.id,t.user_id,t.epoch,t.scope_id,'phase','private.phase.'||j.id::text,t.intent_hash,p)
 ON CONFLICT(user_id,epoch,operation_key,record_kind) DO NOTHING RETURNING id INTO rid;
 IF rid IS NULL THEN SELECT id INTO rid FROM tutor_item_supply_private_persistent_pack_journal
  WHERE user_id=t.user_id AND epoch=t.epoch AND operation_key='private.phase.'||j.id::text AND record_kind='phase'
  AND payload_hash=item_supply_internal.snapshot_hash(p);
  IF rid IS NULL THEN RAISE check_violation USING MESSAGE='524 private phase identity conflict'; END IF; END IF;
 RETURN rid;
END $source593_2$;
 original pg_proc%ROWTYPE; revised pg_proc%ROWTYPE; definition text;
BEGIN
 SELECT * INTO original FROM pg_proc WHERE oid=to_regprocedure(signature);
 IF current_database()<>'aearn_b1d_sandbox_20261001'
  OR original.oid IS NULL OR NOT original.prosecdef OR original.prokind<>'f'
  OR original.proowner IS DISTINCT FROM to_regrole('aearn_b1d_runtime_20261001')::oid
  OR original.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR original.provolatile IS DISTINCT FROM 'v'::"char"
  OR original.proparallel IS DISTINCT FROM 'u'::"char"
  OR original.proisstrict IS DISTINCT FROM false
  OR original.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
  RAISE check_violation USING MESSAGE='593 installed original receiver attributes required'; END IF;
 IF md5(original.prosrc)=revised_md5 THEN RETURN; END IF;
 IF md5(original.prosrc)<>baseline_md5 OR md5(revised_source)<>revised_md5 THEN
  RAISE check_violation USING MESSAGE='593 installed raw receiver baseline changed'; END IF;
 definition:=pg_get_functiondef(original.oid);
 IF strpos(definition,original.prosrc)=0 THEN RAISE check_violation USING MESSAGE='593 original function definition mismatch'; END IF;
 EXECUTE replace(definition,original.prosrc,revised_source);
 SELECT * INTO revised FROM pg_proc WHERE oid=original.oid;
 IF md5(revised.prosrc)<>revised_md5 OR (to_jsonb(revised)-'prosrc') IS DISTINCT FROM (to_jsonb(original)-'prosrc') THEN
  RAISE check_violation USING MESSAGE='593 receiver attributes/ACL changed'; END IF;
END $dp593_2$;

DO $dp593_3$
DECLARE signature constant text := 'item_supply_internal.assert_private_native_phase(jsonb,uuid,bigint,uuid,uuid)';
 baseline_md5 constant text := 'dcad3b3e8d6ff04d4c3ca560f3a2251c'; revised_md5 constant text := '59ea33637ad5fdea942b024bda77d5e4';
 revised_source constant text := $source593_3$
DECLARE t record;j record;c record;o record;prior record;s jsonb;r jsonb:=p->'ref';l jsonb:=p->'lease';m jsonb;
 frozen jsonb;retry jsonb;deadline timestamptz;stamp timestamptz;role text;windows integer;
 dev_job public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 dev_batch public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','root_id','job_id','slot_id','business_item_id','goal_scope_id','ref','lease','valid_until']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(r,ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(l,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_phase_v1'
  OR jsonb_typeof(r) IS DISTINCT FROM 'object' OR jsonb_typeof(l) IS DISTINCT FROM 'object'
  OR (r->>'pack_task_id',r->>'user_id',r->>'epoch',r->>'scope_id') IS DISTINCT FROM (task::text,u::text,e::text,scope::text)
  OR (p->>'root_id',p->>'job_id',p->>'slot_id',p->>'business_item_id',p->>'goal_scope_id')
   IS DISTINCT FROM (r->>'root_id',l->>'job_id',r->>'slot_id',r->>'business_item_id',r->>'goal_scope_id')
  OR (l->>'visibility',l->>'owner_id',l->>'owner_epoch') IS DISTINCT FROM ('private',u::text,e::text) THEN
  RAISE check_violation USING MESSAGE='524 exact PRIVATE phase schema/frame/namespace required'; END IF;
 -- A locator is not permission: only an actual immutable 551 mapping selects this branch.
 SELECT aj.* INTO dev_job FROM tutor_item_supply_private_development_model_accounting_jobs aj WHERE aj.job_id=(l->>'job_id')::uuid;
 IF dev_job.id IS NOT NULL THEN
  SELECT bd.* INTO dev_batch FROM tutor_item_supply_private_development_model_accounting_batches bd WHERE bd.id=dev_job.batch_id;
  IF dev_batch.id IS NULL OR (dev_job.job_id,dev_job.user_id,dev_job.epoch,dev_job.scope_id,dev_job.root_id,dev_job.window_id) IS DISTINCT FROM
   ((l->>'job_id')::uuid,u,e,scope,(r->>'root_id')::uuid,dev_batch.window_id)
   OR (dev_batch.user_id,dev_batch.epoch,dev_batch.scope_id,dev_batch.root_id) IS DISTINCT FROM (u,e,scope,(r->>'root_id')::uuid) THEN
   RAISE check_violation USING MESSAGE='568 exact current job-bound development accounting phase required'; END IF;
  -- Original 551 user/epoch/scope/active-plan locks precede original task/job/control locks.
  PERFORM item_supply_internal.private_development_accounting_batch_current(dev_batch);
 END IF;

 PERFORM pg_advisory_xact_lock(hashtext('persistent-pack-dispatch'),hashtext((SELECT h.payload_json->'ref'->>'public_task_id'
  FROM tutor_item_supply_private_persistent_pack_journal h WHERE h.id=task AND h.record_kind='task')));
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal q WHERE q.pack_task_id=task AND q.user_id=u AND q.epoch=e
  AND q.scope_id=scope AND q.record_kind='private_status' AND q.payload_json->>'schema_version'='persistent_phase_execution_outcome_v2'
  AND q.payload_json->>'job_id'=p->>'job_id') THEN
  RAISE check_violation USING MESSAGE='593 execution-closed PRIVATE phase cannot dispatch'; END IF;
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task
  AND record_kind='task' AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 SELECT value INTO s FROM jsonb_array_elements(t.payload_json->'slots') WHERE value->>'slot_id'=r->>'slot_id'
  AND value->>'logical_item_id'=r->>'business_item_id';
 role:=CASE WHEN s->>'slot' IN('practice-1','practice-2') THEN 'practice'
  WHEN s->>'slot' IN('assessment-1','assessment-2') THEN 'assessment'
  WHEN s->>'slot'='guided-remediation' THEN 'remediation' END;
 IF t.id IS NULL OR s IS NULL OR role IS NULL OR role IS DISTINCT FROM r->>'slot'
  OR item_supply_internal.private_native_task_enhancement(task,u,e,scope) IS DISTINCT FROM true
  OR t.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM r->>'mapping_receipt_id' THEN
  RAISE check_violation USING MESSAGE='524 actual fixed PRIVATE task/business role required'; END IF;
 m:=item_supply_internal.private_native_mapping_current((r->>'mapping_receipt_id')::uuid,u,e);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_finite_course_mappings x,
  LATERAL jsonb_array_elements(x.receipt_json->'pack_request'->'demands') d WHERE x.id=(r->>'mapping_receipt_id')::uuid
  AND x.user_id=u AND x.epoch=e AND x.assessment_scope_id=scope AND d->>'slot'=role
  AND d->>'storage_scope_id'=r->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 real goal_scope distinct from assessment storage required'; END IF;
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=(l->>'job_id')::uuid AND user_id=u AND epoch=e
  AND scope_id=scope AND root_id=(r->>'root_id')::uuid FOR SHARE;
 SELECT * INTO o FROM tutor_item_supply_private_obligations WHERE root_id=j.root_id AND user_id=u AND epoch=e AND scope_id=scope;
 SELECT * INTO c FROM tutor_item_supply_private_job_controls WHERE job_id=j.id AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 frozen:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 retry:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'retry_policy' ELSE 'null'::jsonb END;
 deadline:=LEAST(c.lease_expires_at,c.parent_deadline,(frozen->>'bound_at')::timestamptz+
  (frozen->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF j.id IS NULL OR o.root_id IS NULL OR c.state IS DISTINCT FROM 'leased'
  OR (l->>'lease_owner',l->>'generation',l->>'state_version')
   IS DISTINCT FROM (c.lease_owner,c.lease_generation::text,c.state_version::text)
  OR (l->>'expires_at')::timestamptz IS DISTINCT FROM c.lease_expires_at
  OR (l->>'parent_deadline')::timestamptz IS DISTINCT FROM c.parent_deadline
  OR l->'profile' IS DISTINCT FROM frozen OR l->'retry_policy' IS DISTINCT FROM retry
  OR (p->>'valid_until')::timestamptz IS DISTINCT FROM deadline THEN
  RAISE check_violation USING MESSAGE='524 original PRIVATE issuer control/profile/finite deadline required'; END IF;
 SELECT * INTO prior FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=task AND user_id=u AND epoch=e
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1;
 IF prior.id IS NOT NULL AND prior.payload_json->>'root_id' IS DISTINCT FROM r->>'root_id' THEN
  RAISE check_violation USING MESSAGE='524 fixed PRIVATE canonical root required'; END IF;
 IF dev_job.id IS NOT NULL THEN
  IF dev_job.parent_job_id IS DISTINCT FROM j.parent_job_id OR dev_job.lease_generation IS DISTINCT FROM c.lease_generation
   OR dev_job.lease_owner IS DISTINCT FROM c.lease_owner OR dev_job.profile_hash IS DISTINCT FROM frozen->>'profile_hash'
   OR dev_job.parent_deadline IS DISTINCT FROM c.parent_deadline OR c.parent_deadline>dev_batch.valid_until
   OR dev_job.lease_state_version<=0 OR dev_job.lease_state_version>c.state_version
   OR c.lease_generation<>1 OR c.attempt_count<>1 OR c.breaker_open IS DISTINCT FROM false THEN
   RAISE check_violation USING MESSAGE='568 exact current job-bound development accounting phase required'; END IF;
  PERFORM item_supply_internal.private_development_accounting_batch_current(dev_batch);
 END IF;
 stamp:=clock_timestamp();
 IF dev_job.id IS NOT NULL THEN
  SELECT count(*) INTO windows FROM tutor_item_supply_private_budget_windows w WHERE w.root_id=j.root_id AND w.user_id=u AND w.epoch=e
   AND w.scope_id=scope AND w.pool_key=o.pool_class AND w.provider_key=o.provider_key AND w.id=dev_job.window_id
   AND w.window_start<=stamp AND w.window_end>=deadline;
 ELSE
 SELECT count(*) INTO windows FROM tutor_item_supply_private_budget_windows w WHERE w.root_id=j.root_id AND w.user_id=u AND w.epoch=e
  AND w.scope_id=scope AND w.pool_key=o.pool_class AND w.provider_key=o.provider_key AND w.window_start<=stamp AND w.window_end>=deadline;
 END IF;
 IF windows<>1 OR deadline IS NULL OR stamp>=deadline THEN
  RAISE check_violation USING MESSAGE='524 current original PRIVATE resource window required after locks'; END IF;
END $source593_3$;
 original pg_proc%ROWTYPE; revised pg_proc%ROWTYPE; definition text;
BEGIN
 SELECT * INTO original FROM pg_proc WHERE oid=to_regprocedure(signature);
 IF current_database()<>'aearn_b1d_sandbox_20261001'
  OR original.oid IS NULL OR NOT original.prosecdef OR original.prokind<>'f'
  OR original.proowner IS DISTINCT FROM to_regrole('aearn_b1d_runtime_20261001')::oid
  OR original.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR original.provolatile IS DISTINCT FROM 'v'::"char"
  OR original.proparallel IS DISTINCT FROM 'u'::"char"
  OR original.proisstrict IS DISTINCT FROM false
  OR original.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
  RAISE check_violation USING MESSAGE='593 installed original receiver attributes required'; END IF;
 IF md5(original.prosrc)=revised_md5 THEN RETURN; END IF;
 IF md5(original.prosrc)<>baseline_md5 OR md5(revised_source)<>revised_md5 THEN
  RAISE check_violation USING MESSAGE='593 installed raw receiver baseline changed'; END IF;
 definition:=pg_get_functiondef(original.oid);
 IF strpos(definition,original.prosrc)=0 THEN RAISE check_violation USING MESSAGE='593 original function definition mismatch'; END IF;
 EXECUTE replace(definition,original.prosrc,revised_source);
 SELECT * INTO revised FROM pg_proc WHERE oid=original.oid;
 IF md5(revised.prosrc)<>revised_md5 OR (to_jsonb(revised)-'prosrc') IS DISTINCT FROM (to_jsonb(original)-'prosrc') THEN
  RAISE check_violation USING MESSAGE='593 receiver attributes/ACL changed'; END IF;
END $dp593_3$;

CREATE UNIQUE INDEX IF NOT EXISTS persistent_public_phase_id_once ON tutor_item_supply_shared_persistent_pack_journal(phase_id) WHERE record_kind='phase';
