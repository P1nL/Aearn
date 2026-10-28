-- One approved schema-failure correction receiving increment, 2026-10-22.
-- No historical row rewrite, no new table/function, no relaxed known consumption.
-- Trusted original adapter/owner authenticates wire; SQL verifies stored bindings.

DO $pin591$ DECLARE definition text; BEGIN
 IF COALESCE((SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_shared_review_adjudication(jsonb)')),'missing')
  NOT IN ('11481b1c2db61f4ba9afa9427db7ea74','6633c2693148fdee1e968a592ad69592') THEN
  RAISE EXCEPTION '591 original adjudication assertion changed'; END IF;
 IF COALESCE((SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_shared_review_adjudication()')),'missing')
  NOT IN ('5676044f6b3d903637c4f63cadfde562','0d06bd65aac0db65837d74e5be169f8e') THEN
  RAISE EXCEPTION '591 original adjudication event receiver changed'; END IF;
 SELECT pg_get_constraintdef(c.oid) INTO definition FROM pg_constraint c
  WHERE c.conrelid='public.tutor_item_supply_shared_review_adjudication_events'::regclass
   AND c.conname='tutor_item_supply_shared_review_adjudication_e_event_kind_check' AND c.contype='c';
 IF definition IS NULL OR definition NOT IN ('CHECK ((event_kind = ANY (ARRAY[''started''::text, ''committed''::text])))','CHECK ((event_kind = ANY (ARRAY[''started''::text, ''committed''::text, ''schema_failed''::text])))') THEN
  RAISE EXCEPTION '591 original adjudication event CHECK changed'; END IF;
END $pin591$;

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
 parent_prep tutor_item_supply_shared_review_adjudication_preparations%ROWTYPE;
 parent_receipt tutor_item_supply_shared_review_adjudication_events%ROWTYPE;failure tutor_item_supply_shared_review_adjudication_events%ROWTYPE;
 root_action text;expected_action text;feedback jsonb;correction_count integer;
 correction_keys text[]:=ARRAY['root_semantic_action_hash','correction_kind','correction_parent_receipt_id',
  'correction_parent_receipt_hash','correction_failure_event_id','correction_failure_event_hash','correction_protocol_hash'];
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',(p->>'artifact_id')::uuid);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(original->>'review_receipt_id')::uuid FOR SHARE;
 SELECT * INTO previous FROM tutor_item_supply_shared_review_investigation_receipts WHERE id=(request->>'previous_investigation_receipt_id')::uuid FOR SHARE;
 SELECT * INTO probe FROM tutor_item_supply_shared_review_probe_events WHERE preparation_id=(request->>'probe_receipt_id')::uuid AND event_kind='completed' FOR SHARE;
 SELECT * INTO reserve FROM tutor_item_supply_shared_reservations WHERE id=(p->>'reservation_id')::uuid FOR SHARE;
 root_action:=item_supply_internal.snapshot_hash(jsonb_build_object('review_hash',rr.receipt_hash,
  'previous_hash',previous.snapshot_hash,'probe_hash',request->>'probe_hash'));
 SELECT count(*) INTO correction_count FROM unnest(correction_keys) AS keys(field) WHERE p ? keys.field;
 expected_action:=root_action;
 IF correction_count>0 THEN
  expected_action:=item_supply_internal.snapshot_hash(jsonb_build_object('kind','schema_correction',
   'root_semantic_action_hash',p->>'root_semantic_action_hash','parent_receipt_id',p->>'correction_parent_receipt_id',
   'parent_receipt_hash',p->>'correction_parent_receipt_hash','failure_evidence_hash',p->>'correction_failure_event_hash',
   'correction_protocol_hash',p->>'correction_protocol_hash'));
 END IF;
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
  OR p->>'action_hash' IS DISTINCT FROM expected_action
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
 -- Serialize the semantic root, not a caller-chosen physical reservation.
 PERFORM pg_advisory_xact_lock(hashtext('shared.review.adjudication'),hashtext(root_action));
 IF correction_count=0 THEN
  IF request ? 'schema_failure_feedback' OR input ? 'schema_failure_feedback' THEN
   RAISE EXCEPTION '591 feedback requires the complete controlled correction lineage'; END IF;
 ELSE
  IF correction_count<>cardinality(correction_keys) THEN
   RAISE EXCEPTION '591 complete nonnull correction lineage required'; END IF;
  FOREACH k IN ARRAY correction_keys LOOP
   IF jsonb_typeof(p->k) IS DISTINCT FROM 'string' OR COALESCE(length(p->>k),0)=0 THEN
    RAISE EXCEPTION '591 correction lineage fields must be nonnull strings'; END IF;
  END LOOP;
  SELECT * INTO parent_receipt FROM tutor_item_supply_shared_review_adjudication_events
   WHERE id=(p->>'correction_parent_receipt_id')::uuid AND event_kind='committed'
    AND xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  SELECT * INTO parent_prep FROM tutor_item_supply_shared_review_adjudication_preparations
   WHERE id=parent_receipt.preparation_id AND xmin::text::bigint<>txid_current()%4294967296 FOR UPDATE;
  SELECT * INTO failure FROM tutor_item_supply_shared_review_adjudication_events
   WHERE id=(p->>'correction_failure_event_id')::uuid AND event_kind='schema_failed'
    AND xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  IF parent_receipt.id IS NULL OR parent_prep.id IS NULL OR failure.id IS NULL
   OR p->>'correction_kind' IS DISTINCT FROM 'schema_correction'
   OR p->>'root_semantic_action_hash' IS DISTINCT FROM root_action
   OR COALESCE(parent_prep.payload_json->>'root_semantic_action_hash',parent_prep.action_hash) IS DISTINCT FROM root_action
   OR parent_receipt.action_hash IS DISTINCT FROM parent_prep.action_hash
   OR failure.action_hash IS DISTINCT FROM parent_prep.action_hash OR failure.preparation_id IS DISTINCT FROM parent_prep.id
   OR parent_receipt.id::text IS DISTINCT FROM p->>'correction_parent_receipt_id'
   OR p->>'correction_parent_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(parent_receipt.payload_json)
   OR failure.id::text IS DISTINCT FROM p->>'correction_failure_event_id'
   OR p->>'correction_failure_event_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(failure.payload_json)
   OR failure.payload_json->>'parent_receipt_id' IS DISTINCT FROM parent_receipt.id::text
   OR failure.payload_json->>'parent_receipt_hash' IS DISTINCT FROM p->>'correction_parent_receipt_hash'
   OR parent_receipt.payload_json->'report' IS DISTINCT FROM 'null'::jsonb
   OR parent_receipt.payload_json->>'usage_state' IS DISTINCT FROM 'unknown'
   OR p->>'correction_protocol_hash' IS DISTINCT FROM '54d003e246a9e3b3f89616917e01582f8a19620ffb31cf6a4f45fe124dc5690d'
   OR failure.payload_json->>'strict_output_schema_hash' IS DISTINCT FROM '9ec7b6381cad02b90baf996d360c4e7c6ca5686901a7b85c96e30eddfaaf8a87'
   OR parent_prep.root_id IS DISTINCT FROM a.root_id OR parent_prep.generation_artifact_id IS DISTINCT FROM a.id
   OR parent_prep.previous_investigation_receipt_id IS DISTINCT FROM previous.id
   OR parent_prep.probe_receipt_id::text IS DISTINCT FROM request->>'probe_receipt_id'
   OR parent_prep.job_id IS NOT DISTINCT FROM reserve.job_id OR parent_prep.reservation_id IS NOT DISTINCT FROM reserve.id
   OR reserve.lease_generation::text IS DISTINCT FROM p->'lease'->>'generation' THEN
   RAISE EXCEPTION '591 exact committed schema failure and fresh original-owner correction required'; END IF;
  feedback:=jsonb_build_object('schema_version','native_adjudication_schema_failure_feedback_v1',
   'parent_receipt_id',parent_receipt.id::text,'parent_receipt_hash',p->>'correction_parent_receipt_hash',
   'failure_event_id',failure.id::text,'failure_event_hash',p->>'correction_failure_event_hash',
   'strict_output_schema_hash',failure.payload_json->>'strict_output_schema_hash',
   'correction_protocol_hash',p->>'correction_protocol_hash','diagnostics',failure.payload_json->'parser_diagnostics');
  IF request->'schema_failure_feedback' IS DISTINCT FROM feedback OR input->'schema_failure_feedback' IS DISTINCT FROM feedback
   OR (((parent_prep.payload_json->'request')-ARRAY['execution_profile_hash','schema_failure_feedback']) #- '{original_input,execution_profile_hash}')
      IS DISTINCT FROM ((request-ARRAY['execution_profile_hash','schema_failure_feedback']) #- '{original_input,execution_profile_hash}')
   OR (((parent_prep.payload_json->'request_payload')-ARRAY['execution_profile_hash','schema_failure_feedback']) #- '{original,execution_profile_hash}')
      IS DISTINCT FROM ((input-ARRAY['execution_profile_hash','schema_failure_feedback']) #- '{original,execution_profile_hash}') THEN
   RAISE EXCEPTION '591 only exact machine feedback and operational profile may change'; END IF;
  old_profile:=parent_prep.payload_json->'lease'->'profile';
  SELECT * INTO old_registry FROM tutor_item_supply_parameter_profiles
   WHERE profile_hash=old_profile->>'profile_hash' FOR SHARE;
  SELECT pr.* INTO new_registry FROM tutor_item_supply_parameter_profiles pr
   JOIN tutor_item_supply_shared_job_controls co ON co.profile_id=pr.id
   WHERE co.job_id=reserve.job_id FOR SHARE OF pr;
  IF old_registry.id IS NULL OR new_registry.id IS NULL OR old_profile->>'profile_key_hash' IS NULL
   OR p->'lease'->'profile'->>'profile_key_hash' IS NULL
   OR old_registry.profile_key_hash IS DISTINCT FROM old_profile->>'profile_key_hash'
   OR old_registry.profile_version::text IS DISTINCT FROM old_profile->>'profile_version'
   OR new_registry.profile_hash IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
   OR new_registry.profile_version::text IS DISTINCT FROM p->'lease'->'profile'->>'profile_version'
   OR new_registry.profile_key_hash IS DISTINCT FROM p->'lease'->'profile'->>'profile_key_hash'
   OR old_registry.profile_key_hash IS DISTINCT FROM new_registry.profile_key_hash
   OR jsonb_typeof(old_registry.profile_json->'profile_key') IS DISTINCT FROM 'object'
   OR jsonb_typeof(new_registry.profile_json->'profile_key') IS DISTINCT FROM 'object'
   OR old_registry.profile_key_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(old_registry.profile_json->'profile_key')
   OR new_registry.profile_key_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(new_registry.profile_json->'profile_key')
   OR old_registry.profile_json->'profile_key' IS DISTINCT FROM new_registry.profile_json->'profile_key' THEN
   RAISE EXCEPTION '591 original registry model provider policy semantics must remain bound'; END IF;
  IF parent_prep.payload_json->>'correction_protocol_hash'=p->>'correction_protocol_hash'
   AND parent_prep.payload_json->'request'->'schema_failure_feedback'->>'strict_output_schema_hash'=feedback->>'strict_output_schema_hash'
   AND parent_prep.payload_json->'request'->'schema_failure_feedback'->'diagnostics'=feedback->'diagnostics' THEN
   RAISE EXCEPTION '591 identical schema diagnosis and correction protocol make no progress'; END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_preparations q
    WHERE q.payload_json->>'correction_parent_receipt_id'=parent_receipt.id::text
     AND NOT (q.payload_json ? 'predecessor_preparation_id') AND q.action_hash IS DISTINCT FROM p->>'action_hash') THEN
   RAISE EXCEPTION '591 one logical correction per failed parent; inherit existing stages instead'; END IF;
 END IF;
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
  FOREACH k IN ARRAY correction_keys LOOP
   IF p->k IS DISTINCT FROM predecessor.payload_json->k THEN
    RAISE EXCEPTION '591 physical prestart carry must preserve exact correction lineage'; END IF;
  END LOOP;
 END IF;
END $function$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_review_adjudication()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE prep tutor_item_supply_shared_review_adjudication_preparations%ROWTYPE;
 started tutor_item_supply_shared_review_adjudication_events%ROWTYPE; usage tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 p jsonb:=NEW.payload_json;request jsonb;report jsonb;disposition jsonb;reference jsonb;i integer:=0;
 known_report boolean;actual jsonb;amounts jsonb;
 done tutor_item_supply_shared_review_adjudication_events%ROWTYPE;registry tutor_item_supply_parameter_profiles%ROWTYPE;
 root_action text;obs jsonb;diagnostics jsonb;diagnostic jsonb;k text;v jsonb;
 failure_fields text[]:=ARRAY['schema_version','failure_event_id','preparation_id','preparation_hash','action_hash',
  'start_event_id','start_event_hash','parent_receipt_id','parent_receipt_hash','settlement_id','reservation_id',
  'request_hash','envelope_hash','wire_intent_hash','wire_observation_hash','response_hash','physical_call_hash',
  'provider_model','strict_output_schema_hash','parser_diagnostics','observation','report','publication_enabled','historical_findings_changed'];
 observation_fields text[]:=ARRAY['schema_version','phase','failed_role','safe_code','usage','response_diagnostics',
  'logical_client_invocations','invocation_count_scope','invocation_count_semantics'];
 diagnostic_fields text[]:=ARRAY['response_status','incomplete_reason','requested_max_output_tokens','requested_reasoning_effort','visible_output_chars'];
 usage_fields text[]:=ARRAY['input_tokens','cached_input_tokens','output_tokens','total_tokens','reasoning_tokens'];
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_shared_review_adjudication_preparations' THEN
  IF NEW.id::text IS DISTINCT FROM p->>'preparation_id' OR NEW.root_id::text IS DISTINCT FROM p->>'root_id'
   OR NEW.job_id::text IS DISTINCT FROM p->'lease'->>'job_id' OR NEW.generation_artifact_id::text IS DISTINCT FROM p->>'artifact_id'
   OR NEW.reservation_id::text IS DISTINCT FROM p->>'reservation_id' OR NEW.action_hash IS DISTINCT FROM p->>'action_hash'
   OR NEW.previous_investigation_receipt_id::text IS DISTINCT FROM p->'request'->>'previous_investigation_receipt_id'
   OR NEW.probe_receipt_id::text IS DISTINCT FROM p->'request'->>'probe_receipt_id' OR NEW.valid_until IS DISTINCT FROM (p->>'valid_until')::timestamptz THEN
   RAISE EXCEPTION '588 exact adjudication preparation columns required'; END IF;
  PERFORM item_supply_internal.assert_shared_review_adjudication(p);RETURN NEW;
 END IF;
 -- Late failure evidence is DATA: no expired producer lease/current renewal.
 -- The trusted original adapter/owner authenticates exact wire and strict parsing;
 -- these checks establish DB relations, closed metadata and canonical bindings.
 IF NEW.event_kind='schema_failed' THEN
  SELECT * INTO prep FROM tutor_item_supply_shared_review_adjudication_preparations WHERE id=NEW.preparation_id;
  IF prep.id IS NULL THEN RAISE EXCEPTION '591 original failure preparation required'; END IF;
  root_action:=item_supply_internal.snapshot_hash(jsonb_build_object(
   'review_hash',prep.payload_json->'request'->'original_input'->>'review_receipt_hash',
   'previous_hash',prep.payload_json->'request'->>'previous_investigation_hash','probe_hash',prep.payload_json->'request'->>'probe_hash'));
  PERFORM pg_advisory_xact_lock(hashtext('shared.review.adjudication'),hashtext(root_action));
  SELECT * INTO prep FROM tutor_item_supply_shared_review_adjudication_preparations WHERE id=NEW.preparation_id
   AND xmin::text::bigint<>txid_current()%4294967296 FOR UPDATE;
  SELECT * INTO started FROM tutor_item_supply_shared_review_adjudication_events
   WHERE action_hash=prep.action_hash AND event_kind='started'
    AND xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  SELECT * INTO done FROM tutor_item_supply_shared_review_adjudication_events
   WHERE action_hash=prep.action_hash AND event_kind='committed'
    AND xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  SELECT * INTO usage FROM tutor_item_supply_shared_runtime_settlements
   WHERE id=(p->>'settlement_id')::uuid AND reservation_id=prep.reservation_id
    AND settlement_key='adjudicate.'||prep.action_hash AND xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  SELECT * INTO registry FROM tutor_item_supply_parameter_profiles
   WHERE profile_hash=prep.payload_json->'lease'->'profile'->>'profile_hash' FOR SHARE;
  IF prep.id IS NULL OR started.id IS NULL OR done.id IS NULL OR usage.id IS NULL OR registry.id IS NULL
   OR jsonb_typeof(p) IS DISTINCT FROM 'object' OR (p-failure_fields) IS DISTINCT FROM '{}'::jsonb OR NOT (p ?& failure_fields)
   OR p->>'schema_version' IS DISTINCT FROM 'native_shared_review_adjudication_schema_failure_v1'
   OR p->>'failure_event_id' IS DISTINCT FROM NEW.id::text OR p->>'preparation_id' IS DISTINCT FROM prep.id::text
   OR NEW.action_hash IS DISTINCT FROM prep.action_hash OR p->>'action_hash' IS DISTINCT FROM prep.action_hash
   OR p->>'preparation_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json)
   OR started.preparation_id IS DISTINCT FROM prep.id OR done.preparation_id IS DISTINCT FROM prep.id
   OR p->>'start_event_id' IS DISTINCT FROM started.id::text OR p->>'start_event_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(started.payload_json)
   OR started.payload_json->>'preparation_hash' IS DISTINCT FROM p->>'preparation_hash'
   OR started.payload_json->>'request_hash' IS DISTINCT FROM prep.payload_json->>'request_hash'
   OR started.payload_json->'lease' IS DISTINCT FROM prep.payload_json->'lease'
   OR p->>'parent_receipt_id' IS DISTINCT FROM done.id::text OR p->>'parent_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(done.payload_json)
   OR done.payload_json->'report' IS DISTINCT FROM 'null'::jsonb OR done.payload_json->>'usage_state' IS DISTINCT FROM 'unknown'
   OR done.payload_json->>'report_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash('null'::jsonb)
   OR done.payload_json->>'settlement_id' IS DISTINCT FROM usage.id::text
   OR done.payload_json->>'request_hash' IS DISTINCT FROM prep.payload_json->>'request_hash'
   OR p->>'reservation_id' IS DISTINCT FROM prep.reservation_id::text
   OR p->>'request_hash' IS DISTINCT FROM prep.payload_json->>'request_hash' OR p->>'envelope_hash' IS DISTINCT FROM prep.payload_json->>'envelope_hash'
   OR usage.usage_state IS DISTINCT FROM 'unknown' OR usage.receipt_hash IS NOT NULL
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts sa WHERE sa.settlement_id=usage.id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements u WHERE u.reservation_id=prep.reservation_id AND u.id<>usage.id)
   OR registry.profile_key_hash IS DISTINCT FROM prep.payload_json->'lease'->'profile'->>'profile_key_hash'
   OR registry.profile_version::text IS DISTINCT FROM prep.payload_json->'lease'->'profile'->>'profile_version'
   OR registry.profile_json->'profile_key'->>'model_version' IS NULL
   OR jsonb_typeof(p->'provider_model') IS DISTINCT FROM 'string'
   OR p->>'provider_model' IS DISTINCT FROM registry.profile_json->'profile_key'->>'model_version'
   OR p->>'strict_output_schema_hash' IS DISTINCT FROM '9ec7b6381cad02b90baf996d360c4e7c6ca5686901a7b85c96e30eddfaaf8a87'
   OR p->'report' IS DISTINCT FROM 'null'::jsonb OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR p->'historical_findings_changed' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION '591 exact prior committed NULL unknown call and closed failure DATA required'; END IF;
  FOREACH k IN ARRAY ARRAY['preparation_hash','action_hash','start_event_hash','parent_receipt_hash','request_hash',
    'envelope_hash','wire_intent_hash','wire_observation_hash','response_hash','physical_call_hash','strict_output_schema_hash'] LOOP
   IF jsonb_typeof(p->k) IS DISTINCT FROM 'string' OR (p->>k) !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION '591 canonical failure evidence digests required'; END IF;
  END LOOP;
  IF p->>'physical_call_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
    'preparation_id',prep.id::text,'reservation_id',prep.reservation_id::text,'request_hash',p->>'request_hash',
    'envelope_hash',p->>'envelope_hash','wire_intent_hash',p->>'wire_intent_hash','wire_observation_hash',p->>'wire_observation_hash',
    'response_hash',p->>'response_hash','provider_model',p->>'provider_model')) THEN
   RAISE EXCEPTION '591 original physical-call wire and request binding required'; END IF;
  IF jsonb_typeof(p->'parser_diagnostics') IS DISTINCT FROM 'array'
   OR jsonb_array_length(p->'parser_diagnostics') NOT BETWEEN 1 AND 32 THEN
   RAISE EXCEPTION '591 bounded strict-parser diagnostics required'; END IF;
  FOR diagnostic IN SELECT value FROM jsonb_array_elements(p->'parser_diagnostics') LOOP
   IF jsonb_typeof(diagnostic) IS DISTINCT FROM 'object' OR (diagnostic-ARRAY['pointer','code']) IS DISTINCT FROM '{}'::jsonb
    OR NOT (diagnostic ?& ARRAY['pointer','code']) OR jsonb_typeof(diagnostic->'pointer') IS DISTINCT FROM 'string'
    OR length(diagnostic->>'pointer')>180
    OR (diagnostic->>'pointer') !~ '^/(schema_version|dispositions)(/[0-9]+)?(/(dispute_key|disposition|rationale|applicable_contract|references|probe_hash|proposed_revision|pointer|value_hash|other_field))?(/[0-9]+)?(/(pointer|value_hash|other_field))?$'
    OR jsonb_typeof(diagnostic->'code') IS DISTINCT FROM 'string'
    OR diagnostic->>'code' NOT IN ('missing','extra_forbidden','too_long','too_short','string_too_long','string_too_short',
      'literal_error','string_type','tuple_type','model_type','dict_type','schema_invalid') THEN
    RAISE EXCEPTION '591 closed diagnostic paths and machine codes only'; END IF;
  END LOOP;
  IF p->'parser_diagnostics' IS DISTINCT FROM (SELECT jsonb_agg(canonical.v ORDER BY (canonical.v->>'pointer') COLLATE "C",(canonical.v->>'code') COLLATE "C")
    FROM (SELECT DISTINCT value AS v FROM jsonb_array_elements(p->'parser_diagnostics')) canonical) THEN
   RAISE EXCEPTION '591 diagnostics must be sorted and deduplicated without raw text'; END IF;
  obs:=p->'observation';diagnostics:=obs->'response_diagnostics';
  IF jsonb_typeof(obs) IS DISTINCT FROM 'object' OR (obs-observation_fields) IS DISTINCT FROM '{}'::jsonb OR NOT (obs ?& observation_fields)
   OR obs->>'schema_version' IS DISTINCT FROM 'item_supply_review_failure_observation_v1'
   OR obs->>'phase' IS DISTINCT FROM 'output_schema' OR obs->>'safe_code' IS DISTINCT FROM 'schema_validation'
   OR obs->'failed_role' IS DISTINCT FROM 'null'::jsonb OR jsonb_typeof(obs->'logical_client_invocations') IS DISTINCT FROM 'number'
   OR obs->>'logical_client_invocations' IS DISTINCT FROM '1'
   OR obs->>'invocation_count_scope' IS DISTINCT FROM 'failed_adapter_operation'
   OR obs->>'invocation_count_semantics' IS DISTINCT FROM 'logical_client_invocations_not_http_attempts'
   OR jsonb_typeof(diagnostics) IS DISTINCT FROM 'object' OR (diagnostics-diagnostic_fields) IS DISTINCT FROM '{}'::jsonb
   OR NOT (diagnostics ?& diagnostic_fields) OR diagnostics->>'response_status' IS DISTINCT FROM 'completed'
   OR diagnostics->'incomplete_reason' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION '591 completed output-schema failure observation required, never unknown or transport'; END IF;
  IF diagnostics->'requested_max_output_tokens'<>'null'::jsonb AND
    (jsonb_typeof(diagnostics->'requested_max_output_tokens') IS DISTINCT FROM 'number' OR diagnostics->>'requested_max_output_tokens' IS DISTINCT FROM '61440') THEN
   RAISE EXCEPTION '591 original output-token request limit required when observed'; END IF;
  IF diagnostics->'requested_reasoning_effort'<>'null'::jsonb AND
    (jsonb_typeof(diagnostics->'requested_reasoning_effort') IS DISTINCT FROM 'string' OR diagnostics->>'requested_reasoning_effort' NOT IN ('none','minimal','low','medium','high','xhigh','max')) THEN
   RAISE EXCEPTION '591 allowlisted reasoning metadata required'; END IF;
  IF diagnostics->'visible_output_chars'<>'null'::jsonb AND
    (jsonb_typeof(diagnostics->'visible_output_chars') IS DISTINCT FROM 'number' OR (diagnostics->>'visible_output_chars') !~ '^[0-9]+$') THEN
   RAISE EXCEPTION '591 nonnegative observed output length required'; END IF;
  IF obs->'usage'<>'null'::jsonb THEN
   IF jsonb_typeof(obs->'usage') IS DISTINCT FROM 'object' OR ((obs->'usage')-usage_fields) IS DISTINCT FROM '{}'::jsonb
    OR NOT ((obs->'usage') ?& usage_fields) THEN
    RAISE EXCEPTION '591 closed usage observation only, not settlement authority'; END IF;
   FOR k,v IN SELECT key,value FROM jsonb_each(obs->'usage') LOOP
    IF v<>'null'::jsonb AND (jsonb_typeof(v) IS DISTINCT FROM 'number' OR v::text !~ '^[0-9]+$') THEN
     RAISE EXCEPTION '591 observed token counts must be nonnegative integers or null'; END IF;
   END LOOP;
   IF obs->'usage'->'cached_input_tokens'<>'null'::jsonb AND
     (obs->'usage'->'input_tokens'='null'::jsonb OR (obs->'usage'->>'cached_input_tokens')::numeric>(obs->'usage'->>'input_tokens')::numeric) THEN
    RAISE EXCEPTION '591 cached-token observation cannot exceed input'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO prep FROM tutor_item_supply_shared_review_adjudication_preparations WHERE id=NEW.preparation_id FOR SHARE;
 SELECT * INTO started FROM tutor_item_supply_shared_review_adjudication_events WHERE action_hash=NEW.action_hash AND event_kind='started' FOR SHARE;
 IF prep.id IS NULL OR NEW.action_hash IS DISTINCT FROM prep.action_hash THEN RAISE EXCEPTION '588 original adjudication action required'; END IF;
 request:=prep.payload_json->'request';
 IF NEW.event_kind='started' THEN
  PERFORM item_supply_internal.assert_shared_review_adjudication(prep.payload_json);
  IF started.id IS NOT NULL OR p->>'preparation_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json)
   OR p->>'request_hash' IS DISTINCT FROM prep.payload_json->>'request_hash' OR p->'lease' IS DISTINCT FROM prep.payload_json->'lease'
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_preparations q WHERE q.id=prep.id AND q.xmin::text::bigint=txid_current()%4294967296) THEN
   RAISE EXCEPTION '588 adjudication must commit prepare before one start'; END IF;
 ELSE
  SELECT * INTO usage FROM tutor_item_supply_shared_runtime_settlements WHERE id=(p->>'settlement_id')::uuid
   AND reservation_id=prep.reservation_id AND settlement_key='adjudicate.'||prep.action_hash
   AND xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  report:=p->'report';
  IF started.id IS NULL OR started.preparation_id IS DISTINCT FROM prep.id OR usage.id IS NULL
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_events e WHERE e.id=started.id AND e.xmin::text::bigint=txid_current()%4294967296)
   OR p->>'schema_version' IS DISTINCT FROM 'native_shared_review_adjudication_receipt_v1'
   OR p->>'preparation_id' IS DISTINCT FROM prep.id::text OR p->>'action_hash' IS DISTINCT FROM NEW.action_hash
   OR p->>'request_hash' IS DISTINCT FROM prep.payload_json->>'request_hash'
   OR report IS NULL OR p->>'usage_state' IS DISTINCT FROM usage.usage_state
   OR p->>'report_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(report)
   OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'historical_findings_changed' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION '588 adjudication actual committed original start and settlement required'; END IF;
  -- Result capture authenticates original committed accounting, not a renewed
  -- producer lease. Preparation/start keep their existing current-authority gates.
  known_report:=report<>'null'::jsonb
   AND report#>'{run,input_tokens}' IS NOT NULL AND report#>'{run,input_tokens}'<>'null'::jsonb
   AND report#>'{run,output_tokens}' IS NOT NULL AND report#>'{run,output_tokens}'<>'null'::jsonb;
  IF usage.usage_state IS DISTINCT FROM (CASE WHEN known_report THEN 'known' ELSE 'unknown' END) THEN
   RAISE EXCEPTION '589 adjudication report token availability and settlement state must agree'; END IF;
  SELECT jsonb_object_agg(sa.resource_kind,sa.actual_amount) INTO amounts
   FROM tutor_item_supply_shared_runtime_settlement_amounts sa WHERE sa.settlement_id=usage.id;
  IF known_report THEN
   IF jsonb_typeof(report#>'{run,input_tokens}') IS DISTINCT FROM 'number'
    OR jsonb_typeof(report#>'{run,output_tokens}') IS DISTINCT FROM 'number'
    OR (report#>>'{run,input_tokens}') !~ '^[0-9]+$' OR (report#>>'{run,output_tokens}') !~ '^[0-9]+$' THEN
    RAISE EXCEPTION '589 known adjudication requires actual nonnegative integer token counts'; END IF;
   actual:=jsonb_build_object('requests',1,'input_tokens',(report#>>'{run,input_tokens}')::bigint,
    'output_tokens',(report#>>'{run,output_tokens}')::bigint,'execution_seconds',0,
    'fetches',0,'candidates',0,'revision_rounds',0,'investigation_rounds',1);
   IF usage.receipt_hash IS DISTINCT FROM p->>'report_hash' OR amounts IS DISTINCT FROM actual
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts sa
      WHERE sa.settlement_id=usage.id AND sa.xmin::text::bigint=txid_current()%4294967296) THEN
    RAISE EXCEPTION '589 known adjudication requires exact committed report hash and actual resource amounts'; END IF;
  ELSE
   IF usage.receipt_hash IS NOT NULL OR amounts IS NOT NULL THEN
    RAISE EXCEPTION '589 unknown adjudication DATA cannot claim known hash or actual resource amounts'; END IF;
  END IF;
  IF report<>'null'::jsonb THEN
   IF report->>'schema_version' IS DISTINCT FROM 'native_shared_review_adjudication_report_v1'
    OR report->>'request_hash' IS DISTINCT FROM prep.payload_json->>'request_hash'
    OR report->'run'->>'input_hash' IS DISTINCT FROM prep.payload_json->>'request_hash'
    OR report->'run'->>'output_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(report->'output')
    OR report->'run'->>'profile_hash' IS DISTINCT FROM request->>'execution_profile_hash'
    OR report->'run'->>'prompt_version' IS DISTINCT FROM 'native-review-adjudication-v1'
    OR report->'run'->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
    OR jsonb_array_length(report->'output'->'dispositions') IS DISTINCT FROM jsonb_array_length(request->'original_input'->'disputes') THEN
    RAISE EXCEPTION '588 exact provider adjudication report input and output required'; END IF;
   FOR disposition IN SELECT value FROM jsonb_array_elements(report->'output'->'dispositions') LOOP
    IF disposition->>'dispute_key' IS DISTINCT FROM request->'original_input'->'disputes'->i->>'dispute_key'
     OR disposition->>'probe_hash' IS DISTINCT FROM request->>'probe_hash'
     OR disposition->>'disposition' NOT IN ('refuted','supported','unresolved')
     OR (disposition->>'disposition'='refuted' AND disposition->'proposed_revision' IS DISTINCT FROM 'null'::jsonb)
     OR COALESCE(length(btrim(disposition->>'rationale')),0)=0 OR COALESCE(length(btrim(disposition->>'applicable_contract')),0)=0 THEN
     RAISE EXCEPTION '588 per original finding disposition proof required'; END IF;
    FOR reference IN SELECT value FROM jsonb_array_elements(disposition->'references') LOOP
     IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(prep.payload_json->'request_payload'->'original'->'evidence_index') e WHERE e=reference) THEN
      RAISE EXCEPTION '588 actual original source contract reference required'; END IF;
    END LOOP;
    i:=i+1;
   END LOOP;
  END IF;
 END IF;
 RETURN NEW;
END $function$;

ALTER TABLE public.tutor_item_supply_shared_review_adjudication_events
 DROP CONSTRAINT tutor_item_supply_shared_review_adjudication_e_event_kind_check;
ALTER TABLE public.tutor_item_supply_shared_review_adjudication_events
 ADD CONSTRAINT tutor_item_supply_shared_review_adjudication_e_event_kind_check
 CHECK (event_kind IN ('started','committed','schema_failed'));
-- One logical correction per failed receipt. Physical prestart successors retain
-- the same correction lineage but are governed by the unchanged 590 chain indexes.
CREATE UNIQUE INDEX IF NOT EXISTS shared_adjudication_correction_parent_once
 ON public.tutor_item_supply_shared_review_adjudication_preparations((payload_json->>'correction_parent_receipt_id'))
 WHERE payload_json ? 'correction_parent_receipt_id' AND NOT (payload_json ? 'predecessor_preparation_id');
-- PK/FK, append-only guards, 590 indexes and UNIQUE(action_hash,event_kind) unchanged.
