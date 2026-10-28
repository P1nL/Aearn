-- One separately authorized post-588 quality correction, 2026-10-22.
-- Only the three existing adjudication receivers below are replaced.
-- Capture may retain UNKNOWN/failed DATA; only authenticated KNOWN original
-- accounting/report DATA may grant revision or same-version facts consumption.
-- No table, budget, trigger, once, source, deadline or historical row is changed.

DO $pin589$ BEGIN
 IF COALESCE((SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_shared_review_adjudication()')),'missing')
  NOT IN ('439c598154d51c53bd9f1e9e045d5268','5676044f6b3d903637c4f63cadfde562') THEN
  RAISE EXCEPTION '589 original enforce_shared_review_adjudication body changed'; END IF;
END $pin589$;
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

DO $pin589$ BEGIN
 IF COALESCE((SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_incremental_direct_revision(jsonb)')),'missing')
  NOT IN ('8b8d10f75f9ec051d3e0267e423ae612','6331dc21b703cddaf54d793b4b30436c') THEN
  RAISE EXCEPTION '589 original assert_incremental_direct_revision body changed'; END IF;
END $pin589$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_incremental_direct_revision(p jsonb)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE a tutor_item_supply_shared_generation_artifacts%ROWTYPE; receipt tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 instruction jsonb:=p->'instruction'; report jsonb; finding jsonb; hash text; path text; adjudicated boolean:=false;
 disposition jsonb; adjudication record;
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'parent_lease',(p->>'parent_artifact_id')::uuid);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'parent_artifact_id')::uuid FOR SHARE;
 SELECT * INTO receipt FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'review_receipt_id')::uuid FOR SHARE;
 IF p ? 'adjudication' THEN
  SELECT e.* INTO adjudication FROM tutor_item_supply_shared_review_adjudication_events e
   JOIN tutor_item_supply_shared_review_adjudication_preparations prep ON prep.id=e.preparation_id
   WHERE e.id=(p->'adjudication'->>'receipt_id')::uuid AND e.event_kind='committed'
    AND prep.generation_artifact_id=a.id AND prep.payload_json->'request'->'original_input'->>'review_receipt_id'=receipt.id::text
    AND e.payload_json->>'report_hash'=p->'adjudication'->>'report_hash'
    AND e.payload_json->>'usage_state'='known' AND jsonb_typeof(e.payload_json->'report')='object'
    AND e.payload_json->>'report_hash'=item_supply_internal.snapshot_hash(e.payload_json->'report')
    AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements u
      WHERE u.id=(e.payload_json->>'settlement_id')::uuid AND u.reservation_id=prep.reservation_id
       AND u.settlement_key='adjudicate.'||prep.action_hash AND u.usage_state='known'
       AND u.receipt_hash=e.payload_json->>'report_hash'
       AND u.xmin::text::bigint<>txid_current()%4294967296
       AND (SELECT jsonb_object_agg(sa.resource_kind,sa.actual_amount)
         FROM tutor_item_supply_shared_runtime_settlement_amounts sa WHERE sa.settlement_id=u.id)
        =jsonb_build_object('requests',1,'input_tokens',e.payload_json#>'{report,run,input_tokens}',
          'output_tokens',e.payload_json#>'{report,run,output_tokens}','execution_seconds',0,
          'fetches',0,'candidates',0,'revision_rounds',0,'investigation_rounds',1))
    AND e.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE OF e,prep;
  IF adjudication.id IS NULL OR adjudication.payload_json->'report' IS NULL
   OR adjudication.payload_json->'report'='null'::jsonb THEN
   RAISE EXCEPTION '588 original committed new adjudication required'; END IF;
  adjudicated:=true;
 END IF;
 IF receipt.id IS NULL OR receipt.artifact_kind IS DISTINCT FROM 'review_bundle' OR receipt.mode IS DISTINCT FROM 'live'
  OR receipt.generation_artifact_id IS DISTINCT FROM a.id
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.id=receipt.id AND r.xmin::text::bigint=txid_current()%4294967296)
  OR receipt.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(receipt.payload_json)
  OR p->>'schema_version' IS DISTINCT FROM 'native_shared_revision_preparation_v2' OR p->>'basis_kind' IS DISTINCT FROM 'direct_review'
  OR p->'investigation_receipt_id' IS DISTINCT FROM 'null'::jsonb OR p->'investigation_receipt_hash' IS DISTINCT FROM 'null'::jsonb
  OR instruction->>'schema_version' IS DISTINCT FROM 'item_supply_direct_revision_instruction_v1'
  OR instruction->>'origin' IS DISTINCT FROM 'verified_review_findings'
  OR instruction->'parent_binding' IS DISTINCT FROM receipt.payload_json->'binding'
  OR p->>'instruction_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(instruction)
  OR p->'context'->'direct_revision_instruction' IS DISTINCT FROM instruction
  OR p->'context'->>'parent_review_hash' IS DISTINCT FROM receipt.receipt_hash
  OR p->'context'->'investigation_receipt_id' IS DISTINCT FROM 'null'::jsonb
  OR p->'context'->'investigation_receipt_hash' IS DISTINCT FROM 'null'::jsonb
  OR p->'context'->'investigation_report_hash' IS DISTINCT FROM 'null'::jsonb
  OR p->'request'->>'item_key' IS DISTINCT FROM a.request_json->>'item_key'
  OR p->'request'->'blueprint' IS DISTINCT FROM a.request_json->'blueprint'
  OR p->'request'->'materials' IS DISTINCT FROM a.request_json->'materials'
  OR (NOT adjudicated AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts ir
    WHERE ir.generation_artifact_id=a.id AND ir.payload_json::text LIKE '%contested%')) THEN
  RAISE EXCEPTION '588 exact committed actionable review origin required'; END IF;
 SELECT r INTO report FROM jsonb_array_elements(item_supply_internal.incremental_reports(receipt.payload_json)) r
  WHERE item_supply_internal.snapshot_hash(r)=instruction->>'original_report_hash';
 IF report IS NULL OR report->>'schema_version' IS DISTINCT FROM 'item_supply_evidenced_review_report_v1'
  OR jsonb_array_length(instruction->'finding_hashes') NOT BETWEEN 1 AND 12
  OR jsonb_array_length(instruction->'allowed_paths') NOT BETWEEN 1 AND 32 THEN
  RAISE EXCEPTION '588 original evidenced findings required'; END IF;
 FOR hash IN SELECT jsonb_array_elements_text(instruction->'finding_hashes') LOOP
  SELECT v INTO finding FROM jsonb_array_elements(report->'findings') v WHERE item_supply_internal.snapshot_hash(v)=hash;
  IF finding IS NULL OR (NOT adjudicated AND finding->>'safe_code' IN ('rubric_mismatch','adversarial_exploit','unique_answer','security','data_leakage'))
   OR NOT (finding->'blocking'='true'::jsonb OR finding->>'severity' IN ('major','critical')) THEN
   RAISE EXCEPTION '588 disputed semantic finding requires investigation'; END IF;
  IF adjudicated THEN
   SELECT d INTO disposition FROM jsonb_array_elements(adjudication.payload_json->'report'->'output'->'dispositions') d
    WHERE d->>'disposition'='supported' AND length(btrim(d->>'proposed_revision'))>0
     AND d->>'dispute_key' IN (SELECT x->>'dispute_key' FROM jsonb_array_elements(item_supply_internal.revision_recheck_disputes(receipt.payload_json)) x
       WHERE x->>'finding_hash'=hash AND x->>'report_hash'=item_supply_internal.snapshot_hash(report));
   IF disposition IS NULL THEN RAISE EXCEPTION '588 exact supported original finding and substantive adjudicated revision required'; END IF;
  END IF;
 END LOOP;
 FOR path IN SELECT jsonb_array_elements_text(instruction->'allowed_paths') LOOP
  IF path !~ '^/(public|private)/' OR path IN ('/public/version','/private/version')
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(report->'findings') finding,
    LATERAL jsonb_array_elements(finding->'references') ref
    WHERE instruction->'finding_hashes' @> jsonb_build_array(item_supply_internal.snapshot_hash(finding))
    AND (ref->>'pointer'='/source'||path OR '/source'||path LIKE (ref->>'pointer')||'/%')
    AND ref->>'value_hash'=item_supply_internal.snapshot_hash(item_supply_internal.review_investigation_pointer_value(
      jsonb_build_object('source',a.source_json),ref->>'pointer'))) THEN
   RAISE EXCEPTION '588 instruction path must match original authenticated finding'; END IF;
 END LOOP;
END $function$;

DO $pin589$ BEGIN
 IF COALESCE((SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_shared_adjudicated_facts(tutor_item_supply_shared_admission_facts)')),'missing')
  NOT IN ('34b82b41bc754aa5d5145fcdb763f158','d10d4d9bd53a5c70fcf5b01fc9114f02') THEN
  RAISE EXCEPTION '589 original assert_shared_adjudicated_facts body changed'; END IF;
END $pin589$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_adjudicated_facts(n tutor_item_supply_shared_admission_facts)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE p jsonb:=n.payload_json; old tutor_item_supply_shared_admission_facts%ROWTYPE;
 adjudication record;
 prep tutor_item_supply_shared_review_adjudication_preparations%ROWTYPE;
 review tutor_item_supply_shared_pipeline_receipts%ROWTYPE;validation tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;e jsonb:=p->'evidence';evaluation jsonb:=p->'evaluation';
 report jsonb;disputes jsonb;probes text[];policy text;execution_required boolean;
 allowed text[]:=ARRAY['schema_version','receipt_id','lease','profile_hash','continuation_binding_hash',
  'same_version_predecessor_id','same_version_predecessor_hash','adjudication_receipt_id','adjudication_report_hash',
  'evidence','evaluation','checked_at','valid_until'];
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',n.generation_artifact_id);
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
END $function$;
