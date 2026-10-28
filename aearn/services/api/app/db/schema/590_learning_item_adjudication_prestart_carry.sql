-- Separately authorized pre-START adjudication preparation carry, 2026-10-22.
-- Preserve immutable originals, logical action identity and global event once.
-- Only the existing assertion and preparation uniqueness change; no DATA rewrite.

DO $pin590$ BEGIN
 IF COALESCE((SELECT md5(prosrc) FROM pg_proc
   WHERE oid=to_regprocedure('item_supply_internal.assert_shared_review_adjudication(jsonb)')),'missing')
  NOT IN ('8fac6c63f4f13528f306c4c1a2503e5e','11481b1c2db61f4ba9afa9427db7ea74') THEN
  RAISE EXCEPTION '590 original assert_shared_review_adjudication body changed'; END IF;
END $pin590$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_review_adjudication(p jsonb)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE request jsonb:=p->'request';input jsonb:=p->'request_payload';original jsonb:=request->'original_input';
 rr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; previous tutor_item_supply_shared_review_investigation_receipts%ROWTYPE;
 probe tutor_item_supply_shared_review_probe_events%ROWTYPE;a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 reserve tutor_item_supply_shared_reservations%ROWTYPE;bound jsonb;k text;v jsonb;
 predecessor tutor_item_supply_shared_review_adjudication_preparations%ROWTYPE;
 old_control tutor_item_supply_shared_job_controls%ROWTYPE;old_profile jsonb;checked_at timestamptz;
 old_registry tutor_item_supply_parameter_profiles%ROWTYPE;new_registry tutor_item_supply_parameter_profiles%ROWTYPE;
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',(p->>'artifact_id')::uuid);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(original->>'review_receipt_id')::uuid FOR SHARE;
 SELECT * INTO previous FROM tutor_item_supply_shared_review_investigation_receipts WHERE id=(request->>'previous_investigation_receipt_id')::uuid FOR SHARE;
 SELECT * INTO probe FROM tutor_item_supply_shared_review_probe_events WHERE preparation_id=(request->>'probe_receipt_id')::uuid AND event_kind='completed' FOR SHARE;
 SELECT * INTO reserve FROM tutor_item_supply_shared_reservations WHERE id=(p->>'reservation_id')::uuid FOR SHARE;
 IF p->>'schema_version' IS DISTINCT FROM 'native_shared_review_adjudication_preparation_v1'
  OR rr.id IS NULL OR previous.id IS NULL OR probe.id IS NULL OR reserve.id IS NULL
  OR rr.generation_artifact_id IS DISTINCT FROM a.id OR rr.artifact_kind IS DISTINCT FROM 'review_bundle'
  OR previous.generation_artifact_id IS DISTINCT FROM a.id OR previous.review_receipt_id IS DISTINCT FROM rr.id
  OR previous.snapshot_hash IS DISTINCT FROM request->>'previous_investigation_hash'
  OR previous.payload_json->'report' IS DISTINCT FROM request->'previous_investigation'
  OR probe.generation_artifact_id IS DISTINCT FROM a.id OR probe.review_receipt_id IS DISTINCT FROM rr.id
  OR probe.payload_json IS DISTINCT FROM request->'probe_evidence'
  OR item_supply_internal.snapshot_hash(probe.payload_json) IS DISTINCT FROM request->>'probe_hash'
  OR original->'bundle' IS DISTINCT FROM rr.payload_json OR original->>'review_receipt_hash' IS DISTINCT FROM rr.receipt_hash
  OR original->'review_input'->'source' IS DISTINCT FROM a.source_json
  OR original->'review_input'->'binding' IS DISTINCT FROM rr.payload_json->'binding'
  OR original->'disputes' IS DISTINCT FROM item_supply_internal.revision_recheck_disputes(rr.payload_json)
  OR request->>'execution_profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
  OR jsonb_typeof(input) IS DISTINCT FROM 'object' OR item_supply_internal.snapshot_hash(input) IS DISTINCT FROM p->>'request_hash'
  OR input->'previous_investigation' IS DISTINCT FROM request->'previous_investigation'
  OR input->'probe_evidence' IS DISTINCT FROM probe.payload_json OR input->>'probe_hash' IS DISTINCT FROM request->>'probe_hash'
  OR input->'original'->'review_input'->'source' IS DISTINCT FROM a.source_json
  OR input->'original'->>'review_receipt_hash' IS DISTINCT FROM rr.receipt_hash
  OR input->>'execution_profile_hash' IS DISTINCT FROM request->>'execution_profile_hash'
  OR p->>'action_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('review_hash',rr.receipt_hash,
     'previous_hash',previous.snapshot_hash,'probe_hash',request->>'probe_hash'))
  OR reserve.job_id::text IS DISTINCT FROM p->'lease'->>'job_id' OR reserve.root_id IS DISTINCT FROM a.root_id
  OR reserve.reservation_key IS DISTINCT FROM 'adjudicate.'||(p->>'action_hash') OR reserve.requests<>1
  OR p->'resources'->'requests' IS DISTINCT FROM '1'::jsonb OR p->'resources'->'output_tokens' IS DISTINCT FROM '61440'::jsonb
  OR p->'resources'->'investigation_rounds' IS DISTINCT FROM '1'::jsonb
  OR p->'resources'->'execution_seconds' IS DISTINCT FROM '0'::jsonb OR p->'resources'->'fetches' IS DISTINCT FROM '0'::jsonb
  OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR (p->>'valid_until')::timestamptz<=clock_timestamp()
  OR (p->>'valid_until')::timestamptz>LEAST((p->'lease'->>'expires_at')::timestamptz,(p->'lease'->>'parent_deadline')::timestamptz)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts q WHERE q.id=rr.id AND q.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts q WHERE q.id=previous.id AND q.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_probe_events q WHERE q.id=probe.id AND q.xmin::text::bigint=txid_current()%4294967296) THEN
  RAISE EXCEPTION '588 adjudication requires original committed review investigation measured probe and new control'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(p->'resources') LOOP
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra WHERE ra.reservation_namespace='shared'
    AND ra.reservation_id=reserve.id AND ra.resource_kind=k AND ra.reserved_amount=(v::text)::bigint) THEN
   RAISE EXCEPTION '588 original adjudication charge allocation required'; END IF;
 END LOOP;
 -- Optional physical predecessor is DATA, never a restored execution capability.
 IF (p ? 'predecessor_preparation_id') IS DISTINCT FROM (p ? 'predecessor_preparation_hash') THEN
  RAISE EXCEPTION '590 predecessor preparation ID and hash must be supplied together';
 ELSIF p ? 'predecessor_preparation_id' THEN
  IF jsonb_typeof(p->'predecessor_preparation_id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(p->'predecessor_preparation_hash') IS DISTINCT FROM 'string' THEN
   RAISE EXCEPTION '590 explicit nonnull original predecessor ID and hash required'; END IF;
  SELECT * INTO predecessor FROM tutor_item_supply_shared_review_adjudication_preparations
   WHERE id=(p->>'predecessor_preparation_id')::uuid
    AND xmin::text::bigint<>txid_current()%4294967296 FOR UPDATE;
  IF predecessor.id IS NULL THEN RAISE EXCEPTION '590 prior-TOP original predecessor required'; END IF;
  SELECT * INTO old_control FROM tutor_item_supply_shared_job_controls
   WHERE job_id=predecessor.job_id FOR UPDATE;
  old_profile:=CASE WHEN old_control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN old_control.profile_snapshot_json->'profile' ELSE old_control.profile_snapshot_json END;
  SELECT * INTO old_registry FROM tutor_item_supply_parameter_profiles
   WHERE id=old_control.profile_id FOR SHARE;
  SELECT pr.* INTO new_registry FROM tutor_item_supply_parameter_profiles pr
   JOIN tutor_item_supply_shared_job_controls co ON co.profile_id=pr.id
   WHERE co.job_id=reserve.job_id FOR SHARE OF pr;
  checked_at:=clock_timestamp();
  IF p->>'predecessor_preparation_id' IS DISTINCT FROM predecessor.id::text
   OR p->>'predecessor_preparation_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(predecessor.payload_json)
   OR predecessor.valid_until>checked_at
   OR predecessor.action_hash IS DISTINCT FROM p->>'action_hash'
   OR predecessor.root_id IS DISTINCT FROM a.root_id OR predecessor.root_id::text IS DISTINCT FROM p->>'root_id'
   OR predecessor.generation_artifact_id IS DISTINCT FROM a.id
   OR predecessor.previous_investigation_receipt_id IS DISTINCT FROM previous.id
   OR predecessor.probe_receipt_id::text IS DISTINCT FROM request->>'probe_receipt_id'
   OR predecessor.payload_json->'request'->'original_input'->>'review_receipt_id' IS DISTINCT FROM rr.id::text
   OR predecessor.id::text IS NOT DISTINCT FROM p->>'preparation_id'
   OR predecessor.job_id IS NOT DISTINCT FROM reserve.job_id OR predecessor.reservation_id IS NOT DISTINCT FROM reserve.id
   OR reserve.lease_generation::text IS DISTINCT FROM p->'lease'->>'generation'
   OR old_control.id IS NULL OR old_control.state IS DISTINCT FROM 'leased'
   OR old_control.lease_owner IS DISTINCT FROM predecessor.payload_json->'lease'->>'lease_owner'
   OR old_control.lease_generation::text IS DISTINCT FROM predecessor.payload_json->'lease'->>'generation'
   OR old_control.state_version::text IS DISTINCT FROM predecessor.payload_json->'lease'->>'state_version'
   OR old_control.lease_expires_at IS DISTINCT FROM (predecessor.payload_json->'lease'->>'expires_at')::timestamptz
   OR old_control.parent_deadline IS DISTINCT FROM (predecessor.payload_json->'lease'->>'parent_deadline')::timestamptz
   OR old_profile IS DISTINCT FROM predecessor.payload_json->'lease'->'profile'
   OR LEAST(old_control.lease_expires_at,old_control.parent_deadline)>checked_at
   OR old_profile->>'profile_key_hash' IS NULL
   OR old_profile->>'profile_key_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_key_hash'
   OR p->'lease'->'profile'->>'profile_key_hash' IS NULL
   OR old_registry.id IS NULL OR new_registry.id IS NULL
   OR old_registry.profile_hash IS DISTINCT FROM old_profile->>'profile_hash'
   OR old_registry.profile_version::text IS DISTINCT FROM old_profile->>'profile_version'
   OR old_registry.profile_key_hash IS DISTINCT FROM old_profile->>'profile_key_hash'
   OR new_registry.profile_hash IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
   OR new_registry.profile_version::text IS DISTINCT FROM p->'lease'->'profile'->>'profile_version'
   OR new_registry.profile_key_hash IS DISTINCT FROM p->'lease'->'profile'->>'profile_key_hash'
   OR jsonb_typeof(old_registry.profile_json->'profile_key') IS DISTINCT FROM 'object'
   OR jsonb_typeof(new_registry.profile_json->'profile_key') IS DISTINCT FROM 'object'
   OR old_registry.profile_key_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(old_registry.profile_json->'profile_key')
   OR new_registry.profile_key_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(new_registry.profile_json->'profile_key')
   OR old_registry.profile_json->'profile_key' IS DISTINCT FROM new_registry.profile_json->'profile_key'
   OR (((predecessor.payload_json->'request')-'execution_profile_hash') #- '{original_input,execution_profile_hash}')
      IS DISTINCT FROM ((request-'execution_profile_hash') #- '{original_input,execution_profile_hash}')
   OR (((predecessor.payload_json->'request_payload')-'execution_profile_hash') #- '{original,execution_profile_hash}')
      IS DISTINCT FROM ((input-'execution_profile_hash') #- '{original,execution_profile_hash}') THEN
   RAISE EXCEPTION '590 expired unchanged predecessor and fresh physical original-owner preparation required'; END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_events e WHERE e.action_hash=predecessor.action_hash)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements u
     WHERE u.reservation_id=reserve.id OR EXISTS(
      SELECT 1 FROM tutor_item_supply_shared_review_adjudication_preparations q
       WHERE q.action_hash=predecessor.action_hash AND q.reservation_id=u.reservation_id))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_preparations q
     WHERE q.payload_json->>'predecessor_preparation_id'=predecessor.id::text
      AND (q.id::text IS DISTINCT FROM p->>'preparation_id' OR q.payload_json IS DISTINCT FROM p)) THEN
   RAISE EXCEPTION '590 prestart carry forbids any action event settlement or other physical successor'; END IF;
 END IF;
END $function$;

-- Missing predecessor denotes the one original for a logical action. A successor
-- must carry a nonnull canonical ID/hash, checked above on prepare and start.
CREATE UNIQUE INDEX IF NOT EXISTS shared_adjudication_original_action_once
 ON public.tutor_item_supply_shared_review_adjudication_preparations(action_hash)
 WHERE NOT (payload_json ? 'predecessor_preparation_id');
CREATE UNIQUE INDEX IF NOT EXISTS shared_adjudication_predecessor_once
 ON public.tutor_item_supply_shared_review_adjudication_preparations((payload_json->>'predecessor_preparation_id'))
 WHERE payload_json ? 'predecessor_preparation_id';
ALTER TABLE public.tutor_item_supply_shared_review_adjudication_preparations
 DROP CONSTRAINT IF EXISTS tutor_item_supply_shared_review_adjudication_pr_action_hash_key;
-- Preparation PK/immutable guards and event UNIQUE(action_hash,event_kind) stay unchanged.
