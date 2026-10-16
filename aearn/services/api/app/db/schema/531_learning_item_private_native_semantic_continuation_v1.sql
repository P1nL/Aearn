-- 531 independent PRIVATE source/semantic continuation (no new tables).
-- Installed508..528 and530 are immutable. No PUBLIC source helper/capability,
-- shared522/525 admission receiver, namespace relabel, or replayed provider IO.
-- This checkpoint implements the PRIVATE source correction only; semantic
-- investigation/child/readmission receiver is a separate pending extension.

DO $prior531$
DECLARE p record;
BEGIN
 SELECT fn.*,l.lanname INTO p FROM pg_proc fn JOIN pg_language l ON l.oid=fn.prolang
 WHERE fn.oid=to_regprocedure('item_supply_internal.private_native_source_current(jsonb)');
 IF p.oid IS NULL OR p.lanname<>'plpgsql' OR p.prorettype<>'boolean'::regtype
  OR p.pronargs<>1 OR p.proretset OR p.proisstrict OR p.proleakproof OR p.proparallel<>'u'
  OR NOT p.prosecdef OR p.provolatile<>'v'
  OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') NOT IN(
   '517337fdd158334f649a9ab475074d60a370e165aef5b0394e8081ce1eaf6b4b','71121b02606ec610fe3257e8cf0d1be5e837e6a4e7921fb3c143b1407e085595') THEN
  RAISE check_violation USING MESSAGE='531 unknown PRIVATE original524 source receiver'; END IF;
 IF to_regprocedure('item_supply_internal.private_native_claim_dto_current_v1(jsonb,jsonb,jsonb)') IS NOT NULL THEN
  SELECT fn.*,l.lanname INTO p FROM pg_proc fn JOIN pg_language l ON l.oid=fn.prolang
   WHERE fn.oid=to_regprocedure('item_supply_internal.private_native_claim_dto_current_v1(jsonb,jsonb,jsonb)');
  IF p.lanname<>'plpgsql' OR p.prorettype<>'boolean'::regtype OR p.pronargs<>3 OR p.proretset
   OR p.proisstrict OR p.proleakproof OR p.proparallel<>'u' OR NOT p.prosecdef OR p.provolatile<>'v'
   OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex')<>'81ba36b51713bd5bec740781b37a4f92d1be98c2f240399f6e7070b6cd84ece1' THEN
   RAISE check_violation USING MESSAGE='531 unknown private DTO current helper'; END IF;
 END IF;
END $prior531$;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_claim_dto_current_v1(
 q jsonb, material jsonb, coordinate jsonb) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE
 b jsonb:=coordinate->'binding'; claim jsonb; dto jsonb; prepared jsonb; signed_payload jsonb;
 cr public.rag_source_claim_receipts%ROWTYPE;
 original_ad public.rag_source_admissions%ROWTYPE;
 original_review public.rag_source_reviews%ROWTYPE;
 proof public.rag_assessment_source_evidence%ROWTYPE;
 carrier public.rag_assessment_source_evidence%ROWTYPE;
 carrier_ad public.rag_source_admissions%ROWTYPE;
 bridge public.rag_actual_d_private_provenance%ROWTYPE;
 stamp timestamptz; deadline timestamptz;
BEGIN
 -- DATA hashes are not signatures. Resolve the actual original claim first;
 -- the signed-proof digest remains a separate immutable source fence.
 IF b->>'purpose' IS DISTINCT FROM 'assessment_evidence'
  OR jsonb_typeof(material->'exact_claims') IS DISTINCT FROM 'array'
  OR (SELECT count(*) FROM jsonb_array_elements(material->'exact_claims') v
      WHERE v->'binding'=b)<>1 THEN RETURN false; END IF;
 SELECT v INTO claim FROM jsonb_array_elements(material->'exact_claims') v WHERE v->'binding'=b;
 SELECT * INTO cr FROM rag_source_claim_receipts
  WHERE receipt_handle=claim->>'claim_receipt_id' FOR SHARE;
 IF NOT FOUND OR cr.method IS DISTINCT FROM 'isolated_execution' OR cr.revoked_at IS NOT NULL
  OR cr.assessment_evidence_id IS NULL THEN RETURN false; END IF;
 SELECT * INTO proof FROM rag_assessment_source_evidence WHERE id=cr.assessment_evidence_id FOR SHARE;
 SELECT * INTO original_ad FROM rag_source_admissions WHERE id=cr.admission_id FOR SHARE;
 SELECT * INTO original_review FROM rag_source_reviews WHERE id=original_ad.review_id FOR SHARE;
 signed_payload:=proof.signed_proof->'payload'; prepared:=signed_payload->'prepared';
 IF proof.id IS NULL OR original_ad.id IS NULL OR original_review.id IS NULL
  OR original_review.assessment_evidence_id IS DISTINCT FROM proof.id
  OR original_ad.revoked_at IS NOT NULL OR original_ad.active IS DISTINCT FROM true
  OR original_review.review_receipt_hash IS DISTINCT FROM proof.proof_hash
  OR original_review.quality_evidence_hash IS DISTINCT FROM proof.proof_hash
  OR cr.verification_receipt_hash IS DISTINCT FROM proof.proof_hash
  OR item_supply_internal.snapshot_hash(proof.signed_proof) IS DISTINCT FROM proof.proof_hash
  OR cr.claim_hash IS DISTINCT FROM proof.claim_hash OR cr.demand_hash IS DISTINCT FROM proof.demand_hash
  OR cr.source_document_hash IS DISTINCT FROM proof.document_hash
  OR cr.execution_receipt_handle IS DISTINCT FROM proof.execution_handle
  OR signed_payload->>'evidence_id' IS DISTINCT FROM proof.id::text
  OR signed_payload->>'claim_id' IS DISTINCT FROM cr.id::text
  OR signed_payload->>'admission_id' IS DISTINCT FROM original_ad.id::text
  OR signed_payload->>'review_id' IS DISTINCT FROM original_review.id::text
  OR proof.claim_handle IS DISTINCT FROM cr.receipt_handle
  OR proof.claim_handle IS DISTINCT FROM 'source-claim.'||replace(cr.id::text,'-','')
  OR proof.execution_handle IS DISTINCT FROM 'source-execution.'||replace(proof.id::text,'-','')
  OR prepared->>'source_handle' IS DISTINCT FROM proof.source_handle
  OR prepared->>'document_handle' IS DISTINCT FROM proof.document_handle
  OR prepared->>'document_hash' IS DISTINCT FROM proof.document_hash
  OR prepared->>'capture_id' IS DISTINCT FROM proof.capture_id::text
  OR prepared->>'policy_id' IS DISTINCT FROM proof.policy_id
  OR prepared->>'policy_generation' IS DISTINCT FROM proof.policy_generation::text
  OR prepared->'execution_scope' IS DISTINCT FROM cr.execution_scope_json
  OR prepared->'demand'->'scope' IS DISTINCT FROM jsonb_build_object(
       'subject_id',cr.subject_id,'subject_version',cr.subject_version,'facets',to_jsonb(cr.scope_facets))
  OR original_review.registered_capture_id IS DISTINCT FROM proof.capture_id
  OR original_review.policy_id IS DISTINCT FROM proof.policy_id
  OR original_review.policy_generation IS DISTINCT FROM proof.policy_generation
  OR original_review.root_id IS DISTINCT FROM proof.root_id
  OR original_review.document_hash IS DISTINCT FROM proof.document_hash
  OR original_review.source_handle IS DISTINCT FROM proof.source_handle
  OR original_review.document_handle IS DISTINCT FROM proof.document_handle
  OR original_review.status IS DISTINCT FROM 'reviewed'
  OR original_review.reading_fit IS DISTINCT FROM 'suitable'
  OR original_review.version_fit IS DISTINCT FROM 'current'
  OR original_review.technical_status IS DISTINCT FROM 'correct'
  OR original_review.conflict_status IS DISTINCT FROM 'resolved'
  OR original_review.known_error IS DISTINCT FROM 'absent'
  OR NOT ('assessment_evidence'=ANY(original_ad.allowed_usages))
  OR NOT ('assessment_evidence'=ANY(original_review.allowed_usages))
  OR cr.applicability IS NULL OR cr.applicability_hash IS DISTINCT FROM
       encode(sha256(convert_to(cr.applicability,'UTF8')),'hex')
  OR proof.revoked_at IS NOT NULL THEN RETURN false; END IF;
 deadline:=proof.expires_at;
 IF proof.private_user_id IS NULL THEN
  IF proof.private_epoch IS NOT NULL OR signed_payload->>'format' IS NULL OR signed_payload->>'format' NOT IN
    ('aearn.rag.fresh-assessment-source.v1','aearn.rag.fresh-assessment-source.v2')
   THEN RETURN false; END IF;
  carrier:=proof; carrier_ad:=original_ad;
 ELSE
  -- Original 504 association, not a caller alias or a PUBLIC capability.
  -- The private claim/execution/demand stay private; only its already-current
  -- independently admitted public document/admission are the source carrier.
  SELECT * INTO bridge FROM rag_actual_d_private_provenance WHERE private_evidence_id=proof.id FOR SHARE;
  SELECT * INTO carrier FROM rag_assessment_source_evidence WHERE id=bridge.public_evidence_id FOR SHARE;
  SELECT * INTO carrier_ad FROM rag_source_admissions a WHERE a.review_id IN(
    SELECT r.id FROM rag_source_reviews r WHERE r.assessment_evidence_id=carrier.id) FOR SHARE;
  IF bridge.private_evidence_id IS NULL OR carrier.id IS NULL OR carrier_ad.id IS NULL
   OR proof.private_user_id::text IS DISTINCT FROM q->'ref'->>'user_id'
   OR proof.private_epoch::text IS DISTINCT FROM q->'ref'->>'epoch'
   OR bridge.user_id IS DISTINCT FROM proof.private_user_id OR bridge.epoch IS DISTINCT FROM proof.private_epoch
   OR signed_payload->>'format' IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3'
   OR prepared->'actual_d'->'draft'->>'user_id' IS DISTINCT FROM proof.private_user_id::text
   OR prepared->'actual_d'->>'user_epoch' IS DISTINCT FROM proof.private_epoch::text
   OR prepared->'actual_d'->'draft'->>'draft_id' IS DISTINCT FROM bridge.draft_id::text
   OR prepared->'actual_d'->>'node_id' IS DISTINCT FROM bridge.node_id
   OR prepared->'actual_d'->>'goal_hash' IS DISTINCT FROM bridge.goal_hash
   OR prepared->'actual_d'->>'target_id' IS DISTINCT FROM bridge.target_id
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_user_epochs ue WHERE ue.user_id=proof.private_user_id
       AND ue.epoch=proof.private_epoch AND ue.enabled)
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_finite_course_mappings m
       WHERE m.id=(q->'ref'->>'mapping_receipt_id')::uuid AND m.user_id=bridge.user_id AND m.epoch=bridge.epoch
        AND m.draft_id=bridge.draft_id AND m.knowledge_key=bridge.node_id
        AND m.receipt_json->'frozen_node'->>'goal_hash'=bridge.goal_hash)
   OR carrier.private_user_id IS NOT NULL OR carrier.private_epoch IS NOT NULL
   OR carrier.signed_proof->'payload'->>'format' IS NULL OR carrier.signed_proof->'payload'->>'format' NOT IN
       ('aearn.rag.fresh-assessment-source.v1','aearn.rag.fresh-assessment-source.v2')
   OR (proof.capture_id,proof.source_handle,proof.document_hash,proof.policy_id,proof.policy_generation,proof.root_id,proof.profile_id)
       IS DISTINCT FROM (carrier.capture_id,carrier.source_handle,carrier.document_hash,carrier.policy_id,carrier.policy_generation,carrier.root_id,carrier.profile_id)
   OR bridge.private_proof_hash IS DISTINCT FROM proof.proof_hash
   OR bridge.public_proof_hash IS DISTINCT FROM carrier.proof_hash
   OR item_supply_internal.snapshot_hash(carrier.signed_proof) IS DISTINCT FROM carrier.proof_hash
   OR bridge.corpus_id::text IS DISTINCT FROM coordinate->>'corpus_version_id'
   OR bridge.generation::text IS DISTINCT FROM coordinate->>'active_generation'
   OR bridge.document_id IS DISTINCT FROM carrier.document_handle
   OR bridge.document_hash IS DISTINCT FROM carrier.document_hash
   OR prepared->'spans' IS DISTINCT FROM carrier.signed_proof->'payload'->'prepared'->'spans'
   OR prepared->'demand'->'scope' IS DISTINCT FROM carrier.signed_proof->'payload'->'prepared'->'demand'->'scope'
   OR prepared->'execution_scope' IS DISTINCT FROM carrier.signed_proof->'payload'->'prepared'->'execution_scope'
   OR carrier.revoked_at IS NOT NULL OR carrier_ad.active IS DISTINCT FROM true
   OR carrier_ad.revoked_at IS NOT NULL THEN RETURN false; END IF;
  deadline:=LEAST(deadline,carrier.expires_at);
 END IF;
 -- Outer source receiver has already locked/current-checked this exact
 -- carrier's corpus, review, policy, capture, admission, and authority root.
 IF carrier_ad.receipt_handle IS DISTINCT FROM b->>'admission_receipt_id'
  OR carrier_ad.receipt_handle IS DISTINCT FROM 'admission.'||replace(carrier_ad.id::text,'-','')
  OR carrier_ad.review_id::text IS DISTINCT FROM coordinate->>'source_review_id'
  OR proof.source_handle IS DISTINCT FROM b->>'source_handle'
  OR carrier.document_handle IS DISTINCT FROM b->>'document_handle'
  OR proof.document_hash IS DISTINCT FROM b->>'document_hash'
  OR proof.document_hash IS DISTINCT FROM b->>'document_revision'
  OR cr.demand_hash IS DISTINCT FROM b->>'demand_hash'
  OR cr.demand_hash IS DISTINCT FROM material->'access_request'->>'demand_hash'
  OR b->'scope' IS DISTINCT FROM prepared->'demand'->'scope'
  OR claim->'scope' IS DISTINCT FROM b->'scope'
  OR claim->>'claim_hash' IS DISTINCT FROM cr.claim_hash
  OR claim->>'applicability' IS DISTINCT FROM cr.applicability
  OR claim->'execution_scope' IS DISTINCT FROM cr.execution_scope_json
  OR cr.receipt_handle IS DISTINCT FROM b->>'claim_receipt_id'
  OR cr.receipt_handle IS DISTINCT FROM coordinate->>'claim_id'
  OR proof.execution_handle IS DISTINCT FROM coordinate->>'execution_receipt_id' THEN RETURN false; END IF;
 dto:=jsonb_build_object('receipt_id',cr.receipt_handle,'demand_hash',cr.demand_hash,
  'purpose','assessment_evidence','admission_receipt_id',carrier_ad.receipt_handle,
  'claim_hash',cr.claim_hash,'scope',prepared->'demand'->'scope','source_handle',proof.source_handle,
  'document_handle',carrier.document_handle,'document_revision',proof.document_hash,'document_hash',proof.document_hash,
  'applicability',cr.applicability,'method','isolated_execution',
  'primary_lineage_family',NULL,'independent_lineage_family',NULL,'independent_source_handle',NULL,
  'independent_document_handle',NULL,'independent_document_revision',NULL,'independent_document_hash',NULL,
  'independent_lineage_verified',false,'execution_receipt_id',proof.execution_handle,
  'execution_scope',cr.execution_scope_json,'verified',true,'revoked',false);
 IF item_supply_internal.snapshot_hash(dto) IS DISTINCT FROM coordinate->>'claim_receipt_hash' THEN RETURN false; END IF;
 -- A lock wait must not turn historical issuance into current authorization.
 stamp:=clock_timestamp();
 RETURN (proof.issued_at<=stamp AND carrier.issued_at<=stamp AND cr.verified_at<=stamp AND stamp<deadline) IS TRUE;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_claim_dto_current_v1(jsonb,jsonb,jsonb) FROM PUBLIC;

-- Source->bank lock order, policy/retention/epoch/root fences unchanged.
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_source_current(q jsonb) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb; material jsonb; e jsonb; b jsonb; claim jsonb; t timestamptz; r record;
 deadline timestamptz := 'infinity'::timestamptz;
BEGIN
 p:=jsonb_build_object('materials',q->'request'->'materials');
 IF p IS NULL OR jsonb_typeof(p->'materials') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'materials') NOT BETWEEN 1 AND 12 THEN RETURN false; END IF;
 FOR material IN SELECT value FROM jsonb_array_elements(p->'materials') LOOP
   IF material->>'classification' IS DISTINCT FROM 'approved_public'
     OR jsonb_typeof(material->'binding'->'evidence') IS DISTINCT FROM 'array'
     OR jsonb_array_length(material->'binding'->'evidence') NOT BETWEEN 1 AND 12 THEN RETURN false; END IF;
   FOR e IN SELECT value FROM jsonb_array_elements(material->'binding'->'evidence') LOOP
     b:=e->'binding';
     PERFORM 1 FROM grounding_active_corpora a JOIN grounding_corpus_versions c ON c.id=a.corpus_version_id
       WHERE a.subject_id=e->>'subject_id' AND a.corpus_version_id=(e->>'corpus_version_id')::uuid
         AND a.generation=(e->>'active_generation')::integer AND c.summary_hash=e->>'summary_hash'
         AND c.state='published' FOR SHARE OF a,c;
     IF NOT FOUND THEN RETURN false; END IF;
     SELECT review.*, policy.enabled AS policy_enabled,policy.revoked_at AS policy_revoked,
       policy.generation AS current_generation,policy.allowed_usages AS policy_usages,
       policy.retention_until AS policy_retention,policy.expires_at AS policy_expires,
       capture.retention_until AS capture_retention,capture.cleared_at,
       (capture.captured_body IS NOT NULL) AS capture_body_available,
       capture.fetched_sha256,capture.generation AS capture_generation,
       admission.active AS admission_active,admission.revoked_at AS admission_revoked,
       admission.policy_generation AS admission_generation,admission.allowed_usages AS admission_usages,
       root.enabled AS root_enabled,root.period_start,root.period_end,root.delegation_expires_at,
       root.policy_id AS root_policy,root.policy_generation AS root_generation,
       evidence.expires_at AS evidence_expires,evidence.revoked_at AS evidence_revoked
       INTO r FROM rag_source_reviews review
       JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
       JOIN rag_registered_source_captures capture ON capture.id=review.registered_capture_id AND capture.policy_id=policy.policy_id
       JOIN rag_source_admissions admission ON admission.review_id=review.id
       JOIN rag_budget_authority_roots root ON root.root_id=review.root_id AND root.root_id=policy.root_id
       LEFT JOIN rag_assessment_source_evidence evidence ON evidence.id=review.assessment_evidence_id
       WHERE review.id=(e->>'source_review_id')::uuid AND review.source_handle=b->>'source_handle'
         AND review.document_handle=b->>'document_handle' AND review.document_hash=b->>'document_hash'
         AND review.policy_id=e->>'source_policy_id' AND review.policy_generation=(e->>'source_policy_generation')::integer
         AND admission.receipt_handle=b->>'admission_receipt_id'
       FOR SHARE OF review,policy,capture,admission,root;
     IF NOT FOUND THEN RETURN false; END IF;
     IF r.assessment_evidence_id IS NOT NULL AND EXISTS(SELECT 1 FROM rag_assessment_source_evidence se WHERE se.id=r.assessment_evidence_id AND se.private_user_id IS NOT NULL AND (se.private_user_id::text IS DISTINCT FROM q->'ref'->>'user_id' OR se.private_epoch::text IS DISTINCT FROM q->'ref'->>'epoch' OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_user_epochs ue WHERE ue.user_id=se.private_user_id AND ue.epoch=se.private_epoch AND ue.enabled))) THEN RETURN false; END IF;
     -- Clock follows every possible lock wait; no entry-time deadline authority.
     t:=clock_timestamp();
     deadline:=LEAST(deadline,r.policy_retention,r.policy_expires,r.capture_retention,
       r.period_end,r.delegation_expires_at,r.evidence_expires);
     IF r.policy_enabled IS DISTINCT FROM true OR r.policy_revoked IS NOT NULL
       OR r.current_generation<>r.policy_generation OR r.capture_generation<>r.policy_generation OR r.admission_generation<>r.policy_generation
       OR r.policy_retention<=t OR r.policy_expires<=t OR r.capture_retention<=t OR r.cleared_at IS NOT NULL OR r.capture_body_available IS DISTINCT FROM true
       OR r.fetched_sha256<>r.document_hash OR r.admission_active IS DISTINCT FROM true OR r.admission_revoked IS NOT NULL
       OR NOT (b->>'purpose'=ANY(r.policy_usages) AND b->>'purpose'=ANY(r.admission_usages) AND b->>'purpose'=ANY(r.allowed_usages))
       OR r.status<>'reviewed' OR r.reading_fit<>'suitable' OR r.version_fit<>'current' OR r.technical_status<>'correct'
       OR r.conflict_status<>'resolved' OR r.known_error<>'absent' OR r.root_enabled IS DISTINCT FROM true
       OR NOT(r.period_start<=t AND t<r.period_end AND t<r.delegation_expires_at)
       OR r.root_policy<>r.policy_id OR r.root_generation<>r.policy_generation
       OR (r.assessment_evidence_id IS NOT NULL AND (r.evidence_expires IS NULL OR r.evidence_expires<=t OR r.evidence_revoked IS NOT NULL)) THEN RETURN false; END IF;
     IF b->>'purpose'='assessment_evidence' AND NOT
       item_supply_internal.private_native_claim_dto_current_v1(q,material,e) THEN RETURN false; END IF;
   END LOOP;
   FOR claim IN SELECT value FROM jsonb_array_elements(material->'exact_claims') LOOP
     -- A private actual-D claim names its independently current public carrier
     -- admission/document through original504, never the private admission as
     -- a PUBLIC alias. Check both domains against the original locked rows.
     IF (SELECT count(*) FROM jsonb_array_elements(material->'binding'->'evidence') v
          WHERE v->'binding'=claim->'binding')<>1 THEN RETURN false; END IF;
     SELECT v INTO e FROM jsonb_array_elements(material->'binding'->'evidence') v
       WHERE v->'binding'=claim->'binding';
     IF NOT item_supply_internal.private_native_claim_dto_current_v1(q,material,e) THEN RETURN false; END IF;
   END LOOP;
 END LOOP;
 -- All source rows above are now locked; re-read private proof/epoch clocks
 -- after the LAST material's waits, not just at each earlier coordinate.
 FOR material IN SELECT value FROM jsonb_array_elements(p->'materials') LOOP
   FOR e IN SELECT value FROM jsonb_array_elements(material->'binding'->'evidence') LOOP
     IF e->'binding'->>'purpose'='assessment_evidence' AND NOT
       item_supply_internal.private_native_claim_dto_current_v1(q,material,e) THEN RETURN false; END IF;
   END LOOP;
 END LOOP;
 SELECT LEAST(deadline,min(se.expires_at)) INTO deadline
  FROM jsonb_array_elements(p->'materials') m
  CROSS JOIN LATERAL jsonb_array_elements(m->'exact_claims') c
  JOIN rag_source_claim_receipts cr ON cr.receipt_handle=c->>'claim_receipt_id'
  JOIN rag_assessment_source_evidence se ON se.id=cr.assessment_evidence_id;
 RETURN clock_timestamp()<deadline;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_source_current(jsonb) FROM PUBLIC;

DO $semantic_helpers531$
DECLARE f record;expected record;
BEGIN
 FOR expected IN SELECT * FROM (VALUES
  ('item_supply_internal.assert_private_native_semantic_preparation(tutor_item_supply_private_persistent_pack_journal)','4131de36ad3d971ec711784cb79e54e767ef230e34227bb440be798f9acf8093','void'::regtype),
  ('item_supply_internal.enforce_private_native_semantic_preparation_insert()','234bbdcc260e52c326df9eae900555653d3f42c1f12490f8a9ead05daf8c811b','trigger'::regtype),
  ('item_supply_internal.assert_private_native_semantic_normal(tutor_item_supply_private_native_quality_evidence)','0ec31dfb5e9fed833bdcccd6b8d28424f2658f32ca2ec7f41b0594684c212007','void'::regtype)) x(signature,body_hash,result_type) LOOP
  SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(expected.signature);
  IF f.oid IS NOT NULL AND (f.lanname<>'plpgsql' OR f.prorettype<>expected.result_type OR f.prokind<>'f'
    OR f.proisstrict OR f.proretset OR f.proleakproof OR f.proparallel<>'u' OR NOT f.prosecdef OR f.provolatile<>'v'
    OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
    OR encode(sha256(convert_to(replace(f.prosrc,E'\r\n',E'\n'),'UTF8')),'hex')<>expected.body_hash) THEN
   RAISE check_violation USING MESSAGE='531 unknown PRIVATE semantic helper checkpoint'; END IF;
 END LOOP;
END $semantic_helpers531$;

-- Independent PRIVATE compiled-child frame. Generic registry is DATA only;
-- original PRIVATE investigation/resume/reservation/writers issue authority.

-- Parent and child refs remain distinct immutable DATA. The fresh phase is the
-- CHILD phase; original parent review/validation/blind/six peers remain exactly
-- on the PARENT ref. Neither row is relabeled as the other or re-issued as IO.
CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_semantic_parent_investigation(
 n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=n.payload_json;a record;peer record;aux record;settled record;report jsonb;finding jsonb;ds jsonb:='[]'::jsonb;
 material boolean;idx integer;rh text;fh text;key text;analysis jsonb;d jsonb;ref jsonb;leaf jsonb;path text[];cnt integer;stamp timestamptz;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence actual
  WHERE actual.id=n.id AND actual.kind='investigation' AND to_jsonb(actual)=to_jsonb(n)
   AND actual.xmin::text::bigint<>(txid_current()%4294967296)) THEN
  RAISE check_violation USING MESSAGE='531 immutable actual PRIVATE investigation data required'; END IF;
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','parent_version_id','parent_artifact_id','parent_review_id','parent_review_hash',
  'request','output','run','preparation_id','reservation_id','lease']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_investigation_v1'
  OR EXISTS(SELECT 1 FROM jsonb_each(p) x WHERE x.value='null'::jsonb)
  OR item_supply_internal.snapshot_keys(p->'request',ARRAY['schema_version','review_input','disputes','evidence_index']) IS DISTINCT FROM true
  OR p->'request'->>'schema_version' IS DISTINCT FROM 'private_native_investigation_input_v1'
  OR p->'run'->>'prompt_version' IS DISTINCT FROM 'private_native_investigation_scalar_v1'
  OR p->'run'->>'input_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'request')
  OR p->'run'->>'output_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'output')
  OR p->'run'->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
  OR p->'run'->'provider_identity'->>'identity' IS NULL
  OR p->>'parent_version_id' IS DISTINCT FROM n.version_id::text THEN
  RAISE check_violation USING MESSAGE='524 exact original PRIVATE investigation run/frame required'; END IF;
 SELECT * INTO a FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'parent_artifact_id')::uuid
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND version_id=n.version_id AND mode='live';
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'parent_review_id')::uuid
  AND kind='review' AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id
  AND slot_id=n.slot_id AND root_id=n.root_id AND version_id=n.version_id
  AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'preparation_id')::uuid
  AND pack_task_id=n.pack_task_id AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO settled FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=(p->>'reservation_id')::uuid
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id;
 IF a.id IS NULL OR peer.id IS NULL OR aux.id IS NULL OR settled.id IS NULL
  OR peer.payload_hash IS DISTINCT FROM p->>'parent_review_hash'
  OR peer.payload_json->>'artifact_id' IS DISTINCT FROM a.id::text OR peer.payload_json->'ref' IS DISTINCT FROM p->'ref'
  OR aux.payload_json->>'job_id' IS DISTINCT FROM n.job_id::text OR aux.payload_json->>'reservation_id' IS DISTINCT FROM p->>'reservation_id'
  OR aux.payload_json->'request'->>'schema_version' IS DISTINCT FROM 'private_native_investigation_phase_v1'
  OR aux.payload_json->'request'->'ref' IS DISTINCT FROM p->'ref'
  OR aux.payload_json->'request'->'lease' IS DISTINCT FROM p->'lease'
  OR aux.payload_json->'request'->'request' IS DISTINCT FROM p->'request'
  OR p->'request'->'review_input'->'source' IS DISTINCT FROM a.source_json
  OR p->'request'->'review_input'->'binding' IS DISTINCT FROM peer.payload_json->'bundle'->'binding' THEN
  RAISE check_violation USING MESSAGE='524 exact committed parent/auxiliary/original settlement required'; END IF;
 -- Reconstruct every original minority dispute, not caller-selected voting.
 FOR report IN SELECT value FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') LOOP
  material:=false;rh:=item_supply_internal.snapshot_hash(report);idx:=0;
  FOR finding IN SELECT value FROM jsonb_array_elements(report->'findings') LOOP
   IF finding->>'blocking'='true' OR finding->>'severity' IN('major','critical')
    OR finding->>'safe_code' IN('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit') THEN
    material:=true;fh:=item_supply_internal.snapshot_hash(finding);
    key:=item_supply_internal.snapshot_hash(jsonb_build_array(item_supply_internal.snapshot_hash(peer.payload_json->'bundle'),rh,idx,fh));
    ds:=ds||jsonb_build_array(jsonb_build_object('dispute_key',key,'role',report->>'role','report_hash',rh,'run_id',report->'run'->>'run_id',
     'finding_index',idx,'finding_hash',fh,'safe_code',finding->>'safe_code','references',COALESCE(finding->'references','[]'::jsonb)));
   END IF;idx:=idx+1;
  END LOOP;
  IF NOT material AND report->>'verdict'<>'approved' THEN
   key:=item_supply_internal.snapshot_hash(jsonb_build_array(item_supply_internal.snapshot_hash(peer.payload_json->'bundle'),rh));
   ds:=ds||jsonb_build_array(jsonb_build_object('dispute_key',key,'role',report->>'role','report_hash',rh,'run_id',report->'run'->>'run_id',
    'finding_index',NULL,'finding_hash',NULL,'safe_code','report_requires_evidence','references','[]'::jsonb));
  END IF;
 END LOOP;
 IF jsonb_array_length(ds)=0 OR p->'request'->'disputes' IS DISTINCT FROM ds
  OR jsonb_typeof(p->'output'->'analyses') IS DISTINCT FROM 'array'
  OR jsonb_array_length(p->'output'->'analyses')<>jsonb_array_length(ds)
  OR (SELECT count(DISTINCT x->>'dispute_key') FROM jsonb_array_elements(p->'output'->'analyses') x)<>jsonb_array_length(ds) THEN
  RAISE check_violation USING MESSAGE='524 complete exact PRIVATE minority disputes required'; END IF;
 FOR analysis IN SELECT value FROM jsonb_array_elements(p->'output'->'analyses') LOOP
  SELECT value INTO d FROM jsonb_array_elements(ds) WHERE value->>'dispute_key'=analysis->>'dispute_key';
  IF d IS NULL OR analysis->>'finding_status' NOT IN('supported','contested','insufficient_evidence')
   OR jsonb_typeof(analysis->'references') IS DISTINCT FROM 'array' OR jsonb_array_length(analysis->'references') NOT BETWEEN 1 AND 6
   OR (SELECT count(DISTINCT x->>'pointer') FROM jsonb_array_elements(analysis->'references') x)<>jsonb_array_length(analysis->'references') THEN
   RAISE check_violation USING MESSAGE='524 exact PRIVATE dispute references required'; END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(analysis->'references') LOOP
   SELECT array_agg(replace(replace(token,'~1','/'),'~0','~') ORDER BY ord) INTO path
    FROM unnest(string_to_array(substr(ref->>'pointer',2),'/')) WITH ORDINALITY x(token,ord);
   leaf:=p->'request'->'review_input'#>path;
   IF path[1] NOT IN('source','validation_receipt','scoring_descriptor') OR leaf IS NULL OR jsonb_typeof(leaf) IN('array','object')
    OR item_supply_internal.snapshot_hash(leaf) IS DISTINCT FROM ref->>'value_hash'
    OR NOT(p->'request'->'evidence_index' @> jsonb_build_array(ref)) THEN
    RAISE check_violation USING MESSAGE='524 PRIVATE scalar evidence cannot be fabricated'; END IF;
  END LOOP;
  IF jsonb_array_length(d->'references')>0 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(analysis->'references') chosen,
   jsonb_array_elements(d->'references') original WHERE chosen->>'pointer'=original->>'pointer'
    OR starts_with(chosen->>'pointer',(original->>'pointer')||'/')) THEN
   RAISE check_violation USING MESSAGE='524 PRIVATE original finding region required'; END IF;
 END LOOP;
 stamp:=clock_timestamp();
 IF n.checked_at>stamp OR n.checked_at>=n.valid_until OR n.created_at>=n.valid_until
  OR n.created_at<aux.created_at OR n.checked_at>=(aux.payload_json->>'valid_until')::timestamptz
  OR n.checked_at>=(p->'lease'->>'expires_at')::timestamptz
  OR n.checked_at>=(p->'lease'->>'parent_deadline')::timestamptz THEN
  RAISE check_violation USING MESSAGE='531 original PRIVATE investigation historical issuance required'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_semantic_parent_investigation(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_semantic_parent_resume(p jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE ref jsonb:=p->'ref'; lease jsonb:=p->'lease'; peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 v public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;b public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 g public.tutor_item_supply_private_generation_artifacts%ROWTYPE;ph record;invest public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;stamp timestamptz;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','parent_ref','investigation_id','lease','review_id','validation_id','blind_id','artifact_id']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_semantic_parent_resume_v1' THEN
  RAISE check_violation USING MESSAGE='527 exact PRIVATE review continuation frame required'; END IF;
 PERFORM item_supply_internal.private_native_epoch((ref->>'user_id')::uuid,(ref->>'epoch')::bigint);
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='phase'
  AND pack_task_id=(ref->>'pack_task_id')::uuid AND user_id=(ref->>'user_id')::uuid AND epoch=(ref->>'epoch')::integer
  AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=lease->>'job_id';
 IF ph.id IS NULL OR ph.payload_json->'ref' IS DISTINCT FROM ref
  OR (ph.payload_json->'lease'-'state_version') IS DISTINCT FROM (lease-'state_version') THEN
  RAISE check_violation USING MESSAGE='527 current concrete phase required'; END IF;
 PERFORM item_supply_internal.assert_private_native_phase(ph.payload_json,ph.user_id,ph.epoch,ph.scope_id,ph.pack_task_id);
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'review_id')::uuid AND kind='review'
  AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id AND pack_task_id=ph.pack_task_id
  AND slot_id=(ref->>'slot_id')::uuid AND root_id=(ref->>'root_id')::uuid AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO g FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'artifact_id')::uuid
  AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id AND version_id=peer.version_id AND mode='live'
  AND xmin::text::bigint<>(txid_current()%4294967296);
 -- Original source locks before private bank/current material locks.
 IF g.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',ref,'request',g.request_json,'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 current source for historical PRIVATE quality required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_versions WHERE id=g.version_id AND user_id=ph.user_id AND epoch=ph.epoch
  AND scope_id=ph.scope_id AND public_json=g.source_json->'public' AND private_json=g.source_json->'private' FOR SHARE;
 IF NOT FOUND OR peer.id IS NULL OR peer.payload_json->'ref' IS DISTINCT FROM p->'parent_ref'
  OR (ref-'parent_version_id') IS DISTINCT FROM (p->'parent_ref'-'parent_version_id')
  OR ref->>'parent_version_id' IS DISTINCT FROM peer.version_id::text
  OR peer.payload_json->>'artifact_id' IS DISTINCT FROM g.id::text
  OR peer.payload_json->'bundle'->'binding'->>'version_key' IS DISTINCT FROM g.version_id::text
  OR peer.payload_json->'bundle'->'binding'->>'source_hash' IS DISTINCT FROM g.source_hash
  OR peer.payload_json->'bundle'->'binding'->>'content_hash' IS DISTINCT FROM g.content_hash
  OR peer.checked_at>=peer.valid_until OR peer.created_at>=peer.valid_until THEN
  RAISE check_violation USING MESSAGE='527 actual lawful historical PRIVATE review required'; END IF;
 PERFORM item_supply_internal.assert_private_native_review_stage(peer);
 SELECT * INTO invest FROM tutor_item_supply_private_native_quality_evidence
  WHERE id=(p->>'investigation_id')::uuid AND kind='investigation' AND user_id=peer.user_id AND epoch=peer.epoch
   AND scope_id=peer.scope_id AND pack_task_id=peer.pack_task_id AND slot_id=peer.slot_id AND root_id=peer.root_id
   AND version_id=peer.version_id AND payload_json->>'parent_review_id'=peer.id::text
   AND payload_json->>'parent_review_hash'=peer.payload_hash AND payload_json->'ref'=p->'parent_ref'
   AND xmin::text::bigint<>(txid_current()%4294967296);
 IF invest.id IS NULL THEN RAISE check_violation USING MESSAGE='531 actual same parent PRIVATE investigation required'; END IF;
 PERFORM item_supply_internal.assert_private_native_semantic_parent_investigation(invest);
 SELECT * INTO v FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'validation_id')::uuid AND kind='validation'
  AND user_id=peer.user_id AND epoch=peer.epoch AND scope_id=peer.scope_id AND pack_task_id=peer.pack_task_id
  AND slot_id=peer.slot_id AND root_id=peer.root_id AND version_id=peer.version_id AND job_id=peer.job_id
  AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO b FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'blind_id')::uuid AND kind='blind'
  AND user_id=peer.user_id AND epoch=peer.epoch AND scope_id=peer.scope_id AND pack_task_id=peer.pack_task_id
  AND slot_id=peer.slot_id AND root_id=peer.root_id AND version_id=peer.version_id AND job_id=peer.job_id
  AND xmin::text::bigint<>(txid_current()%4294967296);
 IF v.id IS NULL OR b.id IS NULL OR v.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
  OR (v.payload_json->>'source_hash',v.payload_json->>'content_hash') IS DISTINCT FROM (g.source_hash,g.content_hash)
  OR b.payload_json IS DISTINCT FROM peer.payload_json->'bundle'->'blind_solve'
  OR peer.payload_json->'bundle'->>'state' IS DISTINCT FROM 'completed'
  OR jsonb_array_length(peer.payload_json->'bundle'->'reports')<>6
  OR (SELECT array_agg(x->>'role' ORDER BY x->>'role') FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') x)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[] THEN
  RAISE check_violation USING MESSAGE='527 unchanged complete historical validation blind six-review required'; END IF;
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',g.request_json,
  'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 source changed after bank wait'; END IF;
 stamp:=clock_timestamp();
 IF stamp>=(ph.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='527 continuation phase stale after wait'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_semantic_parent_resume(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_semantic_parent_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.payload_json->>'schema_version'='private_native_semantic_parent_resume_v1' THEN
  IF NEW.record_kind IS DISTINCT FROM 'private_attachment'
   OR (NEW.pack_task_id::text,NEW.user_id::text,NEW.epoch::text,NEW.scope_id::text)
    IS DISTINCT FROM (NEW.payload_json->'ref'->>'pack_task_id',NEW.payload_json->'ref'->>'user_id',
     NEW.payload_json->'ref'->>'epoch',NEW.payload_json->'ref'->>'scope_id') THEN
   RAISE check_violation USING MESSAGE='531 current PRIVATE parent issuer journal namespace required'; END IF;
  PERFORM item_supply_internal.assert_private_native_semantic_parent_resume(NEW.payload_json);
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_semantic_parent_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_semantic_parent_insert ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER a000_private_native_semantic_parent_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_semantic_parent_insert();

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_semantic_parent_record(rid uuid,p jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE task public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->'ref'->>'pack_task_id')::uuid
  AND record_kind='task' AND user_id=(p->'ref'->>'user_id')::uuid AND epoch=(p->'ref'->>'epoch')::bigint
  AND scope_id=(p->'ref'->>'scope_id')::uuid;
 IF task.id IS NULL THEN RAISE check_violation USING MESSAGE='531 existing same task required'; END IF;
 PERFORM item_supply_internal.assert_private_native_semantic_parent_resume(p);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(rid,task.id,task.user_id,task.epoch,task.scope_id,'private_attachment',
  'private.semantic.parent.'||replace(rid::text,'-',''),task.intent_hash,p);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_semantic_parent_record(uuid,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_semantic_parent_current(rid uuid,job uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_semantic_parent_resume_v1'
  AND payload_json->'lease'->>'job_id'=job::text;
 IF r.id IS NULL THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_private_native_semantic_parent_resume(r.payload_json);
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_semantic_parent_current(uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_semantic_preparation(
 n tutor_item_supply_private_persistent_pack_journal) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=n.payload_json->'request';r jsonb:=p->'ref';plan jsonb:=p->'compiler_plan';spec jsonb;
 parent record;invest record;resume record;g record;family record;old_family record;directive text;
BEGIN
 spec:=plan->'child_specification';
 IF n.record_kind IS DISTINCT FROM 'private_attachment'
  OR n.payload_json->>'schema_version' IS DISTINCT FROM 'private_native_auxiliary_v1'
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','lease','investigation_id','parent_version_id',
   'parent_resume_id','request','directive_hash','compiler_plan','compiler_plan_hash']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_semantic_revision_phase_v1'
  OR plan->>'schema_version' IS DISTINCT FROM 'registered_semantic_child_plan_v1'
  OR plan->>'compiler_version' IS DISTINCT FROM 'registered-semantic-child-data-v1'
  OR item_supply_internal.snapshot_keys(plan,ARRAY['schema_version','compiler_version','business_item_id','root_id',
   'parent_version_id','parent_specification_hash','task_kind','child_specification']) IS DISTINCT FROM true
  OR p->>'compiler_plan_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(plan)
  OR (n.pack_task_id::text,n.user_id::text,n.epoch::text,n.scope_id::text)
    IS DISTINCT FROM (r->>'pack_task_id',r->>'user_id',r->>'epoch',r->>'scope_id')
  OR (plan->>'business_item_id',plan->>'root_id',plan->>'parent_version_id')
    IS DISTINCT FROM (r->>'business_item_id',r->>'root_id',r->>'parent_version_id')
  OR plan->>'parent_version_id' IS DISTINCT FROM p->>'parent_version_id'
  OR n.payload_json->>'job_id' IS DISTINCT FROM p->'lease'->>'job_id'
  OR spec->>'target_id' IS DISTINCT FROM 'python-kc-binding-v1'
  OR spec->'allocation'->>'schema_version' IS DISTINCT FROM 'finite_slot_allocation_v2' THEN
  RAISE check_violation USING MESSAGE='531 exact PRIVATE same-slot compiled semantic frame required'; END IF;
 SELECT * INTO resume FROM tutor_item_supply_private_persistent_pack_journal
  WHERE id=(p->>'parent_resume_id')::uuid AND pack_task_id=n.pack_task_id AND user_id=n.user_id AND epoch=n.epoch
   AND scope_id=n.scope_id AND record_kind='private_attachment'
   AND payload_json->>'schema_version'='private_native_semantic_parent_resume_v1';
 SELECT * INTO invest FROM tutor_item_supply_private_native_quality_evidence
  WHERE id=(p->>'investigation_id')::uuid AND kind='investigation' AND pack_task_id=n.pack_task_id
   AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND slot_id=(r->>'slot_id')::uuid
   AND root_id=(r->>'root_id')::uuid AND version_id=(p->>'parent_version_id')::uuid
   AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO parent FROM tutor_item_supply_private_native_quality_evidence
  WHERE id=(invest.payload_json->>'parent_review_id')::uuid AND kind='review' AND pack_task_id=n.pack_task_id
   AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND slot_id=invest.slot_id AND root_id=invest.root_id
   AND version_id=invest.version_id AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO g FROM tutor_item_supply_private_generation_artifacts WHERE id=(invest.payload_json->>'parent_artifact_id')::uuid
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND version_id=invest.version_id AND mode='live';
 SELECT string_agg(a->>'proposed_revision',E'\n' ORDER BY ord) INTO directive
  FROM jsonb_array_elements(invest.payload_json->'output'->'analyses') WITH ORDINALITY x(a,ord)
  WHERE jsonb_typeof(a->'proposed_revision')='string' AND length(btrim(a->>'proposed_revision'))>0;
 SELECT * INTO family FROM (VALUES
  ('python-kc-binding-v1:trace','trace','ab9c9963c8f559bbdb95257c1391fc27eb7c1fd4a92aa0f17cde9c6aa646debc'),
  ('python-kc-binding-v1:diagnose','diagnose','f3e56a40c8242fa794f99d1887ec6e17df30b76a58474d5eb164b8060fcb213c'),
  ('python-kc-binding-v1:repair','repair','ff6d8edf86d69ebb32406288ea8e86dae92e72bbc95e240a868f13a2ffa77cf9'),
  ('python-kc-binding-v1:counterexample','counterexample','39ed371387a05c6cc5193e5df9098e9919bbf82831c937f2c76af76cb7210a1e')) f(id,kind,hash)
  WHERE id=spec->'allocation'->>'family_id';
 SELECT * INTO old_family FROM (VALUES
  ('python-kc-binding-v1:trace','trace'),('python-kc-binding-v1:diagnose','diagnose'),
  ('python-kc-binding-v1:repair','repair'),('python-kc-binding-v1:counterexample','counterexample')) f(id,kind)
  WHERE id=parent.payload_json->'spec'->'allocation'->>'family_id';
 IF resume.id IS NULL OR invest.id IS NULL OR parent.id IS NULL OR g.id IS NULL OR directive IS NULL
  OR family.id IS NULL OR old_family.id IS NULL OR family.kind=old_family.kind
  OR plan->>'task_kind' IS DISTINCT FROM family.kind
  OR spec->'allocation'->>'family_definition_hash' IS DISTINCT FROM family.hash
  OR spec->>'family_definition_hash' IS DISTINCT FROM family.hash
  OR invest.payload_json->>'parent_review_hash' IS DISTINCT FROM parent.payload_hash
  OR resume.payload_json->>'review_id' IS DISTINCT FROM parent.id::text
  OR resume.payload_json->'ref' IS DISTINCT FROM r
  OR resume.payload_json->'parent_ref' IS DISTINCT FROM invest.payload_json->'ref'
  OR resume.payload_json->'lease' IS DISTINCT FROM p->'lease'
  OR resume.created_at>n.created_at
  OR resume.created_at>=(p->'lease'->>'expires_at')::timestamptz
  OR resume.created_at>=(p->'lease'->>'parent_deadline')::timestamptz
  OR invest.checked_at>=invest.valid_until OR invest.created_at>=invest.valid_until
  OR parent.checked_at>=parent.valid_until OR parent.created_at>=parent.valid_until
  OR p->>'directive_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(to_jsonb(directive))
  OR plan->>'parent_specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(parent.payload_json->'spec')
  OR spec->>'seed' IS DISTINCT FROM parent.payload_json->'spec'->>'seed'
  OR spec->>'target_definition_hash' IS DISTINCT FROM parent.payload_json->'spec'->>'target_definition_hash'
  OR spec->'coverage_blueprint' IS DISTINCT FROM parent.payload_json->'spec'->'coverage_blueprint'
  OR (spec->'blueprint'-ARRAY['blueprint_key','version']) IS DISTINCT FROM
     (parent.payload_json->'spec'->'blueprint'-ARRAY['blueprint_key','version'])
  OR (spec->'allocation'-ARRAY['family_id','family_definition_hash']) IS DISTINCT FROM
     (parent.payload_json->'spec'->'allocation'-ARRAY['family_id','family_definition_hash'])
  OR spec->'allocation'->>'slot' IS DISTINCT FROM r->>'slot'
  OR spec->'allocation'->>'slot'='remediation' -- Registry has no different legal KC remediation task kind.
  OR (p->'request'->'blueprint',p->'request'->'public_template')
     IS DISTINCT FROM (spec->'blueprint',spec->'public_template')
  OR p->'request'->'materials' IS DISTINCT FROM g.request_json->'materials'
  OR spec->'public_template'->>'item_key' IS DISTINCT FROM g.source_json->'public'->>'item_key'
  OR spec->'public_template'->>'version' IS NOT DISTINCT FROM g.source_json->'public'->>'version'
  OR spec->'public_template'->'content' IS NOT DISTINCT FROM g.source_json->'public'->'content'
  OR n.created_at>=(n.payload_json->>'valid_until')::timestamptz
  OR n.created_at>=(p->'lease'->>'expires_at')::timestamptz
  OR n.created_at>=(p->'lease'->>'parent_deadline')::timestamptz THEN
  RAISE check_violation USING MESSAGE='531 actual private investigation/resume, new registered family and immutable seed/objective required'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_semantic_preparation(tutor_item_supply_private_persistent_pack_journal) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_semantic_preparation_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND NEW.payload_json->'request'->>'schema_version'='private_native_semantic_revision_phase_v1' THEN
  IF item_supply_internal.private_native_semantic_parent_current(
     (NEW.payload_json->'request'->>'parent_resume_id')::uuid,
     (NEW.payload_json->>'job_id')::uuid) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='531 current original PRIVATE resume/investigation before author required'; END IF;
  PERFORM item_supply_internal.assert_private_native_semantic_preparation(NEW);
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_semantic_preparation_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_semantic_preparation_insert ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER a000_private_native_semantic_preparation_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_semantic_preparation_insert();

-- Exact original PRIVATE524 normal chain AFTER installed527 evidence-job
-- continuation. Only a distinct registered semantic child has these new frames.
DO $normal_prior531$
DECLARE f record;
BEGIN
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.assert_private_native_normal(tutor_item_supply_private_native_quality_evidence)');
 IF f.oid IS NULL OR f.lanname<>'plpgsql' OR f.prorettype<>'void'::regtype OR f.prokind<>'f'
  OR f.pronargs<>1 OR f.proisstrict OR f.proretset OR f.proleakproof OR f.proparallel<>'u'
  OR NOT f.prosecdef OR f.provolatile<>'v'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR encode(sha256(convert_to(replace(f.prosrc,E'\r\n',E'\n'),'UTF8')),'hex')<>'f3a13450a89d1f6faf9968efeb6f1fcfd54a8f5d234159b2fc5a26076464ccd4' THEN
  RAISE check_violation USING MESSAGE='531 unknown original PRIVATE normal continuation baseline'; END IF;
END $normal_prior531$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_semantic_normal(
 n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=n.payload_json;invest record;aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;prep jsonb;parent_review record;parent_artifact record;
 child record;v record;br record;peer record;j record;cv record;pv record;stamp timestamptz;binding jsonb;ev jsonb;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(n.user_id,n.epoch);
 IF n.kind IS DISTINCT FROM 'normal' OR item_supply_internal.snapshot_keys(p,ARRAY[
  'schema_version','ref','investigation_id','investigation_hash','revision_preparation_id','revision_request_hash',
  'child_artifact_id','child_artifact_hash','parent_version_id','parent_review_id','parent_review_hash',
  'parent_substantive_hash','child_substantive_hash','validation_id','validation_hash','blind_id','blind_hash',
  'review_id','review_hash','policy','evidence','machine_hashes','clause_proof_hash','evaluation','source_hash','content_hash']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_semantic_normal_readmission_v1'
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
 PERFORM item_supply_internal.assert_private_native_semantic_preparation(aux);
 IF invest.id IS NULL OR parent_review.id IS NULL OR aux.id IS NULL
  OR invest.payload_hash IS DISTINCT FROM p->>'investigation_hash' OR parent_review.payload_hash IS DISTINCT FROM p->>'parent_review_hash'
  OR invest.payload_json->>'parent_review_id' IS DISTINCT FROM parent_review.id::text
  OR invest.payload_json->>'parent_review_hash' IS DISTINCT FROM parent_review.payload_hash
  OR (invest.payload_json->'ref'-'parent_version_id') IS DISTINCT FROM (p->'ref'-'parent_version_id')
  OR prep->>'schema_version' IS DISTINCT FROM 'private_native_semantic_revision_phase_v1'
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
  OR child.source_json->'public'->'content' IS DISTINCT FROM prep->'compiler_plan'->'child_specification'->'public_template'->'content'
  OR child.source_json->'public'->>'item_key' IS DISTINCT FROM parent_artifact.source_json->'public'->>'item_key'
  OR child.source_json->'public'->>'version' IS NOT DISTINCT FROM parent_artifact.source_json->'public'->>'version'
  OR child.source_json->'public'->'content' IS NOT DISTINCT FROM parent_artifact.source_json->'public'->'content'
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
  OR peer.payload_json->'spec' IS DISTINCT FROM prep->'compiler_plan'->'child_specification'
  OR peer.payload_json->'ref' IS DISTINCT FROM p->'ref' OR peer.payload_json->'spec'->>'seed' IS DISTINCT FROM parent_review.payload_json->'spec'->>'seed'
  OR (peer.payload_json->'spec'->'allocation'-ARRAY['family_id','family_definition_hash']) IS DISTINCT FROM (parent_review.payload_json->'spec'->'allocation'-ARRAY['family_id','family_definition_hash'])
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_semantic_normal(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC;

-- Replace ONLY the normal dispatch frame; current phase/source->bank, epoch,
-- complete original risk/evaluation/producer guards and other kinds are unchanged.
DO $quality_dispatch531$
DECLARE f record;definition text;old_frame text:=$old_semantic_dispatch$  IF NEW.kind='normal' THEN PERFORM item_supply_internal.assert_private_native_normal(NEW); END IF;$old_semantic_dispatch$;
 new_frame text:=$new_semantic_dispatch$  IF NEW.kind='normal' THEN
   IF p->>'schema_version'='private_native_semantic_normal_readmission_v1' THEN
    PERFORM item_supply_internal.assert_private_native_semantic_normal(NEW);
   ELSE PERFORM item_supply_internal.assert_private_native_normal(NEW); END IF;
  END IF;$new_semantic_dispatch$;
BEGIN
 SELECT p.*,l.lanname INTO f FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('item_supply_internal.enforce_private_native_quality_insert()');
 IF f.oid IS NULL OR f.lanname<>'plpgsql' OR f.prorettype<>'trigger'::regtype OR f.prokind<>'f'
  OR f.pronargs<>0 OR f.proisstrict OR f.proretset OR f.proleakproof OR f.proparallel<>'u'
  OR NOT f.prosecdef OR f.provolatile<>'v'
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] THEN
  RAISE check_violation USING MESSAGE='531 original PRIVATE quality receiver attributes changed'; END IF;
 IF encode(sha256(convert_to(replace(f.prosrc,E'\r\n',E'\n'),'UTF8')),'hex')='63fc7bde47976aa62afed9a0d1154ba047a74a6b2817759209fad636633358e4' THEN RETURN; END IF;
 IF encode(sha256(convert_to(replace(f.prosrc,E'\r\n',E'\n'),'UTF8')),'hex')<>'c4b061762a22f5ce66cc804d52f2c941c861438a0495b37f0077e2ccd798c169' THEN
  RAISE check_violation USING MESSAGE='531 unknown original PRIVATE quality dispatch baseline'; END IF;
 definition:=replace(pg_get_functiondef(f.oid),E'\r\n',E'\n');
 IF (length(definition)-length(replace(definition,old_frame,'')))/length(old_frame)<>1 THEN
  RAISE check_violation USING MESSAGE='531 exact original normal dispatch frame missing'; END IF;
 EXECUTE replace(definition,old_frame,new_frame);
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=f.oid
  AND encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex')='63fc7bde47976aa62afed9a0d1154ba047a74a6b2817759209fad636633358e4') THEN
  RAISE check_violation USING MESSAGE='531 resulting original PRIVATE quality receiver fingerprint mismatch'; END IF;
END $quality_dispatch531$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_quality_insert() FROM PUBLIC;



