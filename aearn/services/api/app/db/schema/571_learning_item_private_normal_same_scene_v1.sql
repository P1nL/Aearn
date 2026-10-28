-- C25: only original normal receiver; typed ref-minus and exact committed same-scene R1 child.
-- Frozen <=570 unchanged; no new object/API/trigger/readiness patch, no old veto discharge.
DO $patch571$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old571$
DECLARE p jsonb:=n.payload_json;invest record;aux record;prep jsonb;parent_review record;parent_artifact record;
 child record;v record;br record;peer record;j record;cv record;pv record;stamp timestamptz;binding jsonb;ev jsonb;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(n.user_id,n.epoch);
 IF n.kind IS DISTINCT FROM 'normal' OR item_supply_internal.snapshot_keys(p,ARRAY[
  'schema_version','ref','investigation_id','investigation_hash','revision_preparation_id','revision_request_hash',
  'child_artifact_id','child_artifact_hash','parent_version_id','parent_review_id','parent_review_hash',
  'parent_substantive_hash','child_substantive_hash','validation_id','validation_hash','blind_id','blind_hash',
  'review_id','review_hash','policy','evidence','machine_hashes','clause_proof_hash','evaluation','source_hash','content_hash']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_normal_readmission_v1'
  OR EXISTS(SELECT 1 FROM jsonb_each(p) x WHERE x.value='null'::jsonb)
  OR jsonb_typeof(p->'ref') IS DISTINCT FROM 'object' OR jsonb_typeof(p->'evaluation') IS DISTINCT FROM 'object'
  OR jsonb_typeof(p->'evidence') IS DISTINCT FROM 'object' OR jsonb_typeof(p->'policy') IS DISTINCT FROM 'object'
  OR jsonb_typeof(p->'machine_hashes') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'machine_hashes') NOT BETWEEN 1 AND 16
  OR p->>'parent_version_id' IS DISTINCT FROM p->'ref'->>'parent_version_id'
  OR p->>'parent_version_id'=n.version_id::text
  OR (SELECT count(DISTINCT x) FROM unnest(ARRAY[p->>'validation_id',p->>'blind_id',p->>'review_id',p->>'parent_review_id']) x)<>4 THEN
  RAISE check_violation USING MESSAGE='524 normal requires exact nonnull complete new PRIVATE chain'; END IF;
 SELECT * INTO invest FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'investigation_id')::uuid
  AND kind='investigation' AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id
  AND slot_id=n.slot_id AND root_id=n.root_id AND version_id=(p->>'parent_version_id')::uuid
  AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO parent_review FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'parent_review_id')::uuid
  AND kind='review' AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id
  AND slot_id=n.slot_id AND root_id=n.root_id AND version_id=(p->>'parent_version_id')::uuid
  AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'revision_preparation_id')::uuid
  AND pack_task_id=n.pack_task_id AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 prep:=aux.payload_json->'request';
 IF invest.id IS NULL OR parent_review.id IS NULL OR aux.id IS NULL
  OR invest.payload_hash IS DISTINCT FROM p->>'investigation_hash' OR parent_review.payload_hash IS DISTINCT FROM p->>'parent_review_hash'
  OR invest.payload_json->>'parent_review_id' IS DISTINCT FROM parent_review.id::text
  OR invest.payload_json->>'parent_review_hash' IS DISTINCT FROM parent_review.payload_hash
  OR (invest.payload_json->'ref'-'parent_version_id') IS DISTINCT FROM (p->'ref'-'parent_version_id')
  OR prep->>'schema_version' IS DISTINCT FROM 'private_native_revision_phase_v1'
  OR prep->'ref' IS DISTINCT FROM p->'ref' OR prep->>'investigation_id' IS DISTINCT FROM invest.id::text
  OR prep->>'parent_version_id' IS DISTINCT FROM p->>'parent_version_id'
  OR prep->>'directive_hash' !~ '^[0-9a-f]{64}$'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(invest.payload_json->'output'->'analyses') a
   WHERE jsonb_typeof(a->'proposed_revision')='string' AND length(btrim(a->>'proposed_revision'))>0) THEN
  RAISE check_violation USING MESSAGE='524 committed same-root/slot investigation and substantive child preparation required'; END IF;
 SELECT * INTO child FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'child_artifact_id')::uuid
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND version_id=n.version_id
  AND mode='live' AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO parent_artifact FROM tutor_item_supply_private_generation_artifacts
  WHERE id=(invest.payload_json->>'parent_artifact_id')::uuid AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id
  AND version_id=(p->>'parent_version_id')::uuid AND mode='live';
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=child.job_id AND user_id=n.user_id AND epoch=n.epoch
  AND scope_id=n.scope_id AND root_id=n.root_id;
 IF child.id IS NULL OR parent_artifact.id IS NULL OR j.id IS NULL OR child.id=parent_artifact.id
  OR child.artifact_hash IS DISTINCT FROM p->>'child_artifact_hash'
  OR child.source_hash IS DISTINCT FROM p->>'source_hash' OR child.content_hash IS DISTINCT FROM p->>'content_hash'
  OR aux.payload_json->>'job_id' IS DISTINCT FROM child.job_id::text
  OR child.request_json IS DISTINCT FROM prep->'request'
  OR p->>'revision_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(child.request_json)
  OR child.created_at<aux.created_at OR child.created_at>=(aux.payload_json->>'valid_until')::timestamptz
  OR child.created_at>=(prep->'lease'->>'expires_at')::timestamptz
  OR child.created_at>=(prep->'lease'->>'parent_deadline')::timestamptz
  OR child.lease_generation::text IS DISTINCT FROM prep->'lease'->>'generation'
  OR child.request_json->'profile' IS DISTINCT FROM prep->'lease'->'profile'
  OR child.source_json->'public'->>'item_key' IS DISTINCT FROM parent_artifact.source_json->'public'->>'item_key'
  OR child.source_json->'public'->>'version' IS NOT DISTINCT FROM parent_artifact.source_json->'public'->>'version'
  OR child.source_json->'public'->'content' IS DISTINCT FROM parent_artifact.source_json->'public'->'content'
  OR item_supply_internal.revision_substantive_hash(child.source_json) IS DISTINCT FROM p->>'child_substantive_hash'
  OR item_supply_internal.revision_substantive_hash(parent_artifact.source_json) IS DISTINCT FROM p->>'parent_substantive_hash'
  OR p->>'child_substantive_hash'=p->>'parent_substantive_hash' THEN
  RAISE check_violation USING MESSAGE='524 exact new same-task PRIVATE material child, not identity/seed replacement required'; END IF;
 -- Same PRIVATE candidate/version chain; never shared522 or a new wallet.
 SELECT * INTO cv FROM tutor_item_supply_private_versions WHERE id=child.version_id AND user_id=n.user_id AND epoch=n.epoch;
 SELECT * INTO pv FROM tutor_item_supply_private_versions WHERE id=parent_artifact.version_id AND user_id=n.user_id AND epoch=n.epoch;
 IF cv.candidate_id IS DISTINCT FROM pv.candidate_id OR cv.version<>pv.version+1
  OR cv.public_json IS DISTINCT FROM child.source_json->'public' OR cv.private_json IS DISTINCT FROM child.source_json->'private'
  OR cv.scope_id IS DISTINCT FROM n.scope_id OR pv.scope_id IS DISTINCT FROM n.scope_id THEN
  RAISE check_violation USING MESSAGE='524 fixed PRIVATE candidate version chain required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'validation_id')::uuid AND kind='validation'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=item_supply_internal.private_native_review_evidence_job(n.job_id,(p->>'review_id')::uuid) AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'blind_id')::uuid AND kind='blind'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=item_supply_internal.private_native_review_evidence_job(n.job_id,(p->>'review_id')::uuid) AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'review_id')::uuid AND kind='review'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=item_supply_internal.private_native_review_evidence_job(n.job_id,(p->>'review_id')::uuid) AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 binding:=peer.payload_json->'bundle'->'binding';ev:=p->'evidence';
 IF v.id IS NULL OR br.id IS NULL OR peer.id IS NULL
  OR v.created_at<child.created_at OR br.created_at<child.created_at OR peer.created_at<child.created_at
  OR v.payload_hash IS DISTINCT FROM p->>'validation_hash' OR br.payload_hash IS DISTINCT FROM p->>'blind_hash'
  OR peer.payload_hash IS DISTINCT FROM p->>'review_hash'
  OR v.payload_json->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2' OR v.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
  OR (v.payload_json->>'source_hash',v.payload_json->>'content_hash') IS DISTINCT FROM (child.source_hash,child.content_hash)
  OR br.payload_json IS DISTINCT FROM peer.payload_json->'bundle'->'blind_solve'
  OR (binding->>'version_key',binding->>'source_hash',binding->>'content_hash') IS DISTINCT FROM (child.version_id::text,child.source_hash,child.content_hash)
  OR peer.payload_json->'ref' IS DISTINCT FROM p->'ref' OR peer.payload_json->'spec'->>'seed' IS DISTINCT FROM parent_review.payload_json->'spec'->>'seed'
  OR peer.payload_json->'spec'->'allocation' IS DISTINCT FROM parent_review.payload_json->'spec'->'allocation'
  OR peer.payload_json->'spec'->>'target_definition_hash' IS DISTINCT FROM parent_review.payload_json->'spec'->>'target_definition_hash'
  OR p->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal' OR p->'evaluation'->>'publication_enabled' IS DISTINCT FROM 'false'
  OR p->'evaluation'->'binding' IS DISTINCT FROM binding OR ev->'binding' IS DISTINCT FROM binding
  OR binding->>'policy_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'policy')
  OR p->'policy' IS DISTINCT FROM peer.payload_json->'policy'
  OR p->'evaluation'->>'policy_version' IS DISTINCT FROM p->'policy'->>'policy_version'
  OR p->'evaluation'->'bundle_hashes' IS DISTINCT FROM jsonb_build_array(item_supply_internal.snapshot_hash(peer.payload_json->'bundle'))
  OR binding->>'risk_tier' IS DISTINCT FROM child.source_json->'blueprint'->'publication_policy'->>'risk_tier'
  OR p->'evaluation'->>'state' IS DISTINCT FROM 'evaluated'
  OR p->'evaluation'->>'mode' IS DISTINCT FROM 'internal_only'
  OR p->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ev)
  OR ev->>'validation_receipt_hash' IS DISTINCT FROM v.payload_hash
  OR ev->>'coverage_proof_hash' IS DISTINCT FROM p->>'clause_proof_hash' THEN
  RAISE check_violation USING MESSAGE='524 fresh complete PRIVATE validation/blind/six-peer/full-risk evaluation required'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') report,
  jsonb_array_elements(parent_review.payload_json->'bundle'->'reports') old_report WHERE report->'run'->>'run_id'=old_report->'run'->>'run_id')
  OR br.payload_json->'run'->>'run_id'=parent_review.payload_json->'bundle'->'blind_solve'->'run'->>'run_id'
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(ev->'probes') x WHERE x->>'passed' IS DISTINCT FROM 'true') THEN
  RAISE check_violation USING MESSAGE='524 parent runs/evidence cannot replace child recheck'; END IF;
 -- Preparation deadline was consumed by the original writer at child creation;
 -- old producer expiry alone does NOT revoke historically lawful new content.
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',p->'ref','request',child.request_json,
  'source_receipts',child.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 fresh source authorization for PRIVATE normal required'; END IF;
 stamp:=clock_timestamp();
 IF n.checked_at>stamp OR stamp>=n.valid_until THEN RAISE check_violation USING MESSAGE='524 normal stale after source/receipt waits'; END IF;
END $old571$;
 new_body constant text := $new571$
DECLARE p jsonb:=n.payload_json;invest record;aux record;prep jsonb;parent_review record;parent_artifact record;
 child record;v record;br record;peer record;j record;cv record;pv record;stamp timestamptz;binding jsonb;ev jsonb;r1 jsonb;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(n.user_id,n.epoch);
 IF n.kind IS DISTINCT FROM 'normal' OR item_supply_internal.snapshot_keys(p,ARRAY[
  'schema_version','ref','investigation_id','investigation_hash','revision_preparation_id','revision_request_hash',
  'child_artifact_id','child_artifact_hash','parent_version_id','parent_review_id','parent_review_hash',
  'parent_substantive_hash','child_substantive_hash','validation_id','validation_hash','blind_id','blind_hash',
  'review_id','review_hash','policy','evidence','machine_hashes','clause_proof_hash','evaluation','source_hash','content_hash']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_normal_readmission_v1'
  OR EXISTS(SELECT 1 FROM jsonb_each(p) x WHERE x.value='null'::jsonb)
  OR jsonb_typeof(p->'ref') IS DISTINCT FROM 'object' OR jsonb_typeof(p->'evaluation') IS DISTINCT FROM 'object'
  OR jsonb_typeof(p->'evidence') IS DISTINCT FROM 'object' OR jsonb_typeof(p->'policy') IS DISTINCT FROM 'object'
  OR jsonb_typeof(p->'machine_hashes') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'machine_hashes') NOT BETWEEN 1 AND 16
  OR p->>'parent_version_id' IS DISTINCT FROM p->'ref'->>'parent_version_id'
  OR p->>'parent_version_id'=n.version_id::text
  OR (SELECT count(DISTINCT x) FROM unnest(ARRAY[p->>'validation_id',p->>'blind_id',p->>'review_id',p->>'parent_review_id']) x)<>4 THEN
  RAISE check_violation USING MESSAGE='524 normal requires exact nonnull complete new PRIVATE chain'; END IF;
 SELECT * INTO invest FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'investigation_id')::uuid
  AND kind='investigation' AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id
  AND slot_id=n.slot_id AND root_id=n.root_id AND version_id=(p->>'parent_version_id')::uuid
  AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO parent_review FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'parent_review_id')::uuid
  AND kind='review' AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id
  AND slot_id=n.slot_id AND root_id=n.root_id AND version_id=(p->>'parent_version_id')::uuid
  AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'revision_preparation_id')::uuid
  AND pack_task_id=n.pack_task_id AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 prep:=aux.payload_json->'request';
 IF invest.id IS NULL OR parent_review.id IS NULL OR aux.id IS NULL
  OR invest.payload_hash IS DISTINCT FROM p->>'investigation_hash' OR parent_review.payload_hash IS DISTINCT FROM p->>'parent_review_hash'
  OR invest.payload_json->>'parent_review_id' IS DISTINCT FROM parent_review.id::text
  OR invest.payload_json->>'parent_review_hash' IS DISTINCT FROM parent_review.payload_hash
  OR ((invest.payload_json->'ref') - 'parent_version_id'::text) IS DISTINCT FROM ((p->'ref') - 'parent_version_id'::text)
  OR prep->>'schema_version' IS DISTINCT FROM 'private_native_revision_phase_v1'
  OR prep->'ref' IS DISTINCT FROM p->'ref' OR prep->>'investigation_id' IS DISTINCT FROM invest.id::text
  OR prep->>'parent_version_id' IS DISTINCT FROM p->>'parent_version_id'
  OR prep->>'directive_hash' !~ '^[0-9a-f]{64}$'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(invest.payload_json->'output'->'analyses') a
   WHERE jsonb_typeof(a->'proposed_revision')='string' AND length(btrim(a->>'proposed_revision'))>0) THEN
  RAISE check_violation USING MESSAGE='524 committed same-root/slot investigation and substantive child preparation required'; END IF;
 SELECT * INTO child FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'child_artifact_id')::uuid
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND version_id=n.version_id
  AND mode='live' AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO parent_artifact FROM tutor_item_supply_private_generation_artifacts
  WHERE id=(invest.payload_json->>'parent_artifact_id')::uuid AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id
  AND version_id=(p->>'parent_version_id')::uuid AND mode='live';
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=child.job_id AND user_id=n.user_id AND epoch=n.epoch
  AND scope_id=n.scope_id AND root_id=n.root_id;
 IF child.request_json->'blueprint'->>'version'='finite-public-spec-v3-diagnose-d1-r1' THEN
  IF (n.pack_task_id,n.slot_id,n.root_id,n.user_id,n.epoch,n.scope_id) IS DISTINCT FROM
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'50df2afa-158c-586e-83c7-60bb99ea4307'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid,
    'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid)
   OR p->'ref'->>'business_item_id' IS DISTINCT FROM '2e1251b9-efd2-5624-930f-174f726c35ea'
   OR p->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
   OR p->'ref'->>'goal_scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'
   OR p->'ref'->>'slot' IS DISTINCT FROM 'practice'
   OR p->>'parent_version_id' IS DISTINCT FROM 'a8e9af49-a9ae-4464-aea9-41239ab3a43d'
   OR invest.id IS DISTINCT FROM '8914dcd5-a275-480f-850c-c4563be6ebe5'::uuid
   OR invest.payload_hash IS DISTINCT FROM '132d0344345787adbcaf9587e56a31252017cc1f2f40b886e3b993d8fc539f8e'
   OR parent_review.id IS DISTINCT FROM 'b90b09bd-cac4-4ed7-98d9-f58adb739d99'::uuid
   OR parent_review.payload_hash IS DISTINCT FROM 'af34b1bda02a58e1a1a500dba4be779bdde20cbbe090eae5415758d2c6557c28'
   OR parent_artifact.id IS DISTINCT FROM '1d43ebb0-3ad2-4d25-a6ce-ca70960173a8'::uuid
   OR parent_artifact.artifact_hash IS DISTINCT FROM 'f401a3fc9e42678079f7b0956db069d847120bd87ad4de1a172c43786bf0df84'
   OR prep->>'directive_hash' IS DISTINCT FROM '4a71086d8bf24fcfffd9c027b02cddcf27f77e3db7ce03c76df354580ae6f764'
   OR n.job_id IS DISTINCT FROM child.job_id THEN
   RAISE check_violation USING MESSAGE='571 exact C25 same-scene normal lineage required'; END IF;
  r1:=item_supply_internal.private_native_same_scene_d1_render_v1(parent_review.payload_json->'spec',parent_artifact.source_json);
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal o WHERE
   (o.pack_task_id,o.user_id,o.epoch,o.scope_id)=(n.pack_task_id,n.user_id,n.epoch,n.scope_id)
   AND o.record_kind='private_status' AND o.operation_key='private.revision.output.'||replace(aux.id::text,'-','')
   AND o.payload_json->>'schema_version'='private_native_revision_output_v1'
   AND o.payload_json->>'revision_preparation_id'=aux.id::text
   AND o.payload_json->>'generation_candidate_id'=child.request_json->>'candidate_id'
   AND o.payload_json->>'investigation_id'=invest.id::text AND o.payload_json->>'investigation_hash'=invest.payload_hash
   AND o.payload_json->>'parent_artifact_hash'=parent_artifact.artifact_hash
   AND o.payload_json->>'request_hash'=item_supply_internal.snapshot_hash(child.request_json)
   AND o.payload_json->>'render_spec_hash'=item_supply_internal.snapshot_hash(r1)
   AND o.payload_json->'capture'->>'schema_version'='private_native_revision_capture_v1'
   AND o.payload_json->'capture'->'context'->'ref'=prep->'ref'
   AND o.payload_json->'capture'->'context'->'lease'=prep->'lease'
   AND o.payload_json->'capture'->'context'->'request'=child.request_json
   AND o.payload_json->'capture'->'result'->'source'=child.source_json
   AND o.payload_json->'capture'->'result'->'receipt'=child.receipt_json
   AND o.payload_json->>'captured_top_xid'<>pg_current_xact_id()::text
   AND (o.payload_json->>'captured_at')::timestamptz<=child.created_at)
  THEN RAISE check_violation USING MESSAGE='571 committed same-job revision output required'; END IF;
 END IF;
 IF child.id IS NULL OR parent_artifact.id IS NULL OR j.id IS NULL OR child.id=parent_artifact.id
  OR child.artifact_hash IS DISTINCT FROM p->>'child_artifact_hash'
  OR child.source_hash IS DISTINCT FROM p->>'source_hash' OR child.content_hash IS DISTINCT FROM p->>'content_hash'
  OR aux.payload_json->>'job_id' IS DISTINCT FROM child.job_id::text
  OR child.request_json IS DISTINCT FROM prep->'request'
  OR p->>'revision_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(child.request_json)
  OR child.created_at<aux.created_at OR child.created_at>=(aux.payload_json->>'valid_until')::timestamptz
  OR child.created_at>=(prep->'lease'->>'expires_at')::timestamptz
  OR child.created_at>=(prep->'lease'->>'parent_deadline')::timestamptz
  OR child.lease_generation::text IS DISTINCT FROM prep->'lease'->>'generation'
  OR child.request_json->'profile' IS DISTINCT FROM prep->'lease'->'profile'
  OR child.source_json->'public'->>'item_key' IS DISTINCT FROM parent_artifact.source_json->'public'->>'item_key'
  OR child.source_json->'public'->>'version' IS NOT DISTINCT FROM parent_artifact.source_json->'public'->>'version'
  OR (CASE WHEN child.request_json->'blueprint'->>'version'='finite-public-spec-v3-diagnose-d1-r1' THEN
   r1 IS NULL OR child.source_json->'public' IS DISTINCT FROM r1->'public_template'
   OR child.source_json->'blueprint' IS DISTINCT FROM r1->'blueprint'
   OR child.request_json->'public_template' IS DISTINCT FROM r1->'public_template'
   OR child.request_json->'blueprint' IS DISTINCT FROM r1->'blueprint'
   OR child.source_json->'public'->'content' IS NOT DISTINCT FROM parent_artifact.source_json->'public'->'content'
   ELSE child.source_json->'public'->'content' IS DISTINCT FROM parent_artifact.source_json->'public'->'content' END)
  OR item_supply_internal.revision_substantive_hash(child.source_json) IS DISTINCT FROM p->>'child_substantive_hash'
  OR item_supply_internal.revision_substantive_hash(parent_artifact.source_json) IS DISTINCT FROM p->>'parent_substantive_hash'
  OR p->>'child_substantive_hash'=p->>'parent_substantive_hash' THEN
  RAISE check_violation USING MESSAGE='524 exact new same-task PRIVATE material child, not identity/seed replacement required'; END IF;
 -- Same PRIVATE candidate/version chain; never shared522 or a new wallet.
 SELECT * INTO cv FROM tutor_item_supply_private_versions WHERE id=child.version_id AND user_id=n.user_id AND epoch=n.epoch;
 SELECT * INTO pv FROM tutor_item_supply_private_versions WHERE id=parent_artifact.version_id AND user_id=n.user_id AND epoch=n.epoch;
 IF cv.candidate_id IS DISTINCT FROM pv.candidate_id OR cv.version<>pv.version+1
  OR cv.public_json IS DISTINCT FROM child.source_json->'public' OR cv.private_json IS DISTINCT FROM child.source_json->'private'
  OR cv.scope_id IS DISTINCT FROM n.scope_id OR pv.scope_id IS DISTINCT FROM n.scope_id THEN
  RAISE check_violation USING MESSAGE='524 fixed PRIVATE candidate version chain required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'validation_id')::uuid AND kind='validation'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=item_supply_internal.private_native_review_evidence_job(n.job_id,(p->>'review_id')::uuid) AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'blind_id')::uuid AND kind='blind'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=item_supply_internal.private_native_review_evidence_job(n.job_id,(p->>'review_id')::uuid) AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'review_id')::uuid AND kind='review'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=item_supply_internal.private_native_review_evidence_job(n.job_id,(p->>'review_id')::uuid) AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 binding:=peer.payload_json->'bundle'->'binding';ev:=p->'evidence';
 IF v.id IS NULL OR br.id IS NULL OR peer.id IS NULL
  OR v.created_at<child.created_at OR br.created_at<child.created_at OR peer.created_at<child.created_at
  OR v.payload_hash IS DISTINCT FROM p->>'validation_hash' OR br.payload_hash IS DISTINCT FROM p->>'blind_hash'
  OR peer.payload_hash IS DISTINCT FROM p->>'review_hash'
  OR v.payload_json->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2' OR v.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
  OR (v.payload_json->>'source_hash',v.payload_json->>'content_hash') IS DISTINCT FROM (child.source_hash,child.content_hash)
  OR br.payload_json IS DISTINCT FROM peer.payload_json->'bundle'->'blind_solve'
  OR (binding->>'version_key',binding->>'source_hash',binding->>'content_hash') IS DISTINCT FROM (child.version_id::text,child.source_hash,child.content_hash)
  OR peer.payload_json->'ref' IS DISTINCT FROM p->'ref' OR peer.payload_json->'spec'->>'seed' IS DISTINCT FROM parent_review.payload_json->'spec'->>'seed'
  OR peer.payload_json->'spec'->'allocation' IS DISTINCT FROM parent_review.payload_json->'spec'->'allocation'
  OR peer.payload_json->'spec'->>'target_definition_hash' IS DISTINCT FROM parent_review.payload_json->'spec'->>'target_definition_hash'
  OR (child.request_json->'blueprint'->>'version'='finite-public-spec-v3-diagnose-d1-r1' AND
   (peer.payload_json->'spec' IS DISTINCT FROM r1 OR v.job_id IS DISTINCT FROM child.job_id
    OR br.job_id IS DISTINCT FROM child.job_id OR peer.job_id IS DISTINCT FROM child.job_id))
  OR p->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal' OR p->'evaluation'->>'publication_enabled' IS DISTINCT FROM 'false'
  OR p->'evaluation'->'binding' IS DISTINCT FROM binding OR ev->'binding' IS DISTINCT FROM binding
  OR binding->>'policy_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'policy')
  OR p->'policy' IS DISTINCT FROM peer.payload_json->'policy'
  OR p->'evaluation'->>'policy_version' IS DISTINCT FROM p->'policy'->>'policy_version'
  OR p->'evaluation'->'bundle_hashes' IS DISTINCT FROM jsonb_build_array(item_supply_internal.snapshot_hash(peer.payload_json->'bundle'))
  OR binding->>'risk_tier' IS DISTINCT FROM child.source_json->'blueprint'->'publication_policy'->>'risk_tier'
  OR p->'evaluation'->>'state' IS DISTINCT FROM 'evaluated'
  OR p->'evaluation'->>'mode' IS DISTINCT FROM 'internal_only'
  OR p->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ev)
  OR ev->>'validation_receipt_hash' IS DISTINCT FROM v.payload_hash
  OR ev->>'coverage_proof_hash' IS DISTINCT FROM p->>'clause_proof_hash' THEN
  RAISE check_violation USING MESSAGE='524 fresh complete PRIVATE validation/blind/six-peer/full-risk evaluation required'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') report,
  jsonb_array_elements(parent_review.payload_json->'bundle'->'reports') old_report WHERE report->'run'->>'run_id'=old_report->'run'->>'run_id')
  OR br.payload_json->'run'->>'run_id'=parent_review.payload_json->'bundle'->'blind_solve'->'run'->>'run_id'
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(ev->'probes') x WHERE x->>'passed' IS DISTINCT FROM 'true') THEN
  RAISE check_violation USING MESSAGE='524 parent runs/evidence cannot replace child recheck'; END IF;
 -- Preparation deadline was consumed by the original writer at child creation;
 -- old producer expiry alone does NOT revoke historically lawful new content.
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',p->'ref','request',child.request_json,
  'source_receipts',child.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 fresh source authorization for PRIVATE normal required'; END IF;
 stamp:=clock_timestamp();
 IF n.checked_at>stamp OR stamp>=n.valid_until THEN RAISE check_violation USING MESSAGE='524 normal stale after source/receipt waits'; END IF;
END $new571$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='571 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.assert_private_native_normal(tutor_item_supply_private_native_quality_evidence)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'assert_private_native_normal' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM '5379789'::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['n']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='571 original normal readmission identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='571 original normal readmission body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='571 original normal readmission definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='571 normal readmission metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch571$;
