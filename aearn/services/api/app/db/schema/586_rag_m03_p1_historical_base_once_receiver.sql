-- 586: M03 P1 receiver only: two original gen1 histories and exact claim hash domains.
-- Installed <=585 is frozen. SELECT supplemental and all new grants stay mandatory.
-- Main must pass full original-owner S4 in this candidate's SAME outer rollback
-- before its one atomic installation; no GET, once, source window or oracle here.
DO $patch586$
DECLARE
 actual pg_catalog.pg_proc%ROWTYPE; verified pg_catalog.pg_proc%ROWTYPE;
 source text; replacement text; definition text; before_attrs jsonb; default_at integer;
 expected_attrs constant jsonb := $attrs586${"oid":"5414997","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"native_consumer_m03_p1_source_current","prorows":0,"pronargs":4,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["p_proof","p_materialization","p_current_materials","p_enabled"],"proargtypes":["2950","2950","3802","16"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"2200","proallargtypes":null,"proargdefaults":"({CONST :consttype 16 :consttypmod -1 :constcollid 0 :constlen 1 :constbyval true :constisnull false :location 45204 :constvalue 1 [ 0 0 0 0 0 0 0 0 ]})","pronargdefaults":1}$attrs586$::jsonb;
 old_block constant text := $old586$    SELECT * INTO old_auth FROM public.rag_registered_supplemental_authorizations WHERE id=old_attempt.supplemental_authorization_id FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO new_auth FROM public.rag_registered_supplemental_authorizations WHERE id=grant_row.supplemental_authorization_id FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO historical_root FROM public.rag_budget_authority_roots WHERE root_id=old_attempt.root_id FOR SHARE;
    IF NOT FOUND OR historical_root.enabled IS NOT TRUE OR
       old_attempt.state<>'settled' OR old_attempt.settled_at IS NULL OR
       old_attempt.dispatched_at>old_attempt.settled_at OR old_attempt.settled_at>(frozen.proof_json->>'checked_at')::timestamptz OR
       old_attempt.response_sha256<>old_capture.fetched_sha256 OR old_attempt.response_bytes<>old_capture.captured_bytes OR
       ROW(old_attempt.policy_id,old_attempt.generation,old_attempt.root_id,old_attempt.canonical_url_sha256,
           old_attempt.request_hash,old_attempt.id)
        IS DISTINCT FROM ROW(old_auth.policy_id,old_auth.generation,old_auth.root_id,old_auth.canonical_url_sha256,
                             old_auth.request_hash,old_auth.dispatch_id) OR
       old_attempt.dispatched_at>=old_auth.expires_at OR old_attempt.dispatched_at>=old_policy.expires_at OR
       old_attempt.settled_at>=old_policy.retention_until OR old_attempt.settled_at>=old_capture.retention_until OR
       historical_root.policy_id<>old_policy.policy_id OR historical_root.policy_generation<>old_policy.generation OR
       old_attempt.dispatched_at<historical_root.period_start OR old_attempt.dispatched_at>=historical_root.period_end OR
       old_attempt.dispatched_at>=historical_root.delegation_expires_at OR
       ROW(new_auth.id,new_auth.course_refresh_authorization_id,new_auth.dispatch_id,new_auth.policy_id,new_auth.generation,
           new_auth.root_id,new_auth.request_hash,new_auth.prior_attempt_id,new_auth.expires_at,new_auth.approval_ref)
        IS DISTINCT FROM ROW(grant_row.supplemental_authorization_id,grant_row.id,grant_row.dispatch_id,grant_row.policy_id,
           grant_row.generation,grant_row.root_id,grant_row.request_hash,grant_row.latest_attempt_id,grant_row.dispatch_expires_at,
           (CASE k WHEN 0 THEN 'standingpolicy.m03-sqlite-source-recovery.20261019'::text
              ELSE 'standingpolicy.m03-companion-unspent-dispatch-successor.20261019'::text END)) OR
       new_auth.replaces_authorization_id IS NOT NULL OR new_auth.explicit_followup_id IS NOT NULL OR
       new_attempt.operation_key<>grant_row.operation_key OR new_attempt.dispatched_at<grant_row.issued_at OR
       new_attempt.dispatched_at>=grant_row.dispatch_expires_at OR new_attempt.settled_at IS NULL OR
       new_attempt.settled_at<new_attempt.dispatched_at OR new_attempt.settled_at>new_source.issued_at OR
       new_attempt.settled_at>=grant_row.source_expires_at OR
       EXISTS(SELECT 1 FROM public.rag_registered_supplemental_revocations v WHERE v.authorization_id IN(old_auth.id,new_auth.id)
          OR v.prior_attempt_id IN(old_attempt.id,new_attempt.id)) THEN RETURN false; END IF;
$old586$;
 new_block constant text := $new586$    -- Exact immutable P1 history, not a general NULL-supplemental permission.
    -- Clear the previous SELECT row before checking either original base once.
    old_auth:=NULL;
    IF k=0 THEN
     SELECT * INTO old_auth FROM public.rag_registered_supplemental_authorizations WHERE id=old_attempt.supplemental_authorization_id FOR SHARE;
     IF NOT FOUND OR old_auth.id IS DISTINCT FROM '5421844c-9c3a-4c10-9896-bdb0ebbde5a4'::uuid OR
        ROW(old_attempt.policy_id,old_attempt.generation,old_attempt.root_id,old_attempt.canonical_url_sha256,
           old_attempt.request_hash,old_attempt.id)
        IS DISTINCT FROM ROW(old_auth.policy_id,old_auth.generation,old_auth.root_id,old_auth.canonical_url_sha256,
                             old_auth.request_hash,old_auth.dispatch_id) OR
       old_attempt.dispatched_at>=old_auth.expires_at THEN RETURN false; END IF;
    ELSE
     IF old_attempt.supplemental_authorization_id IS NOT NULL OR old_attempt.error_code IS NOT NULL OR NOT (
      (k=1 AND ROW(old_capture.id,old_attempt.id,old_attempt.policy_id,old_attempt.generation,
        old_attempt.root_id,old_attempt.canonical_url_sha256,old_attempt.request_hash,old_attempt.operation_key,
        old_attempt.dispatched_at,old_attempt.settled_at,old_capture.fetched_at,old_capture.fetched_sha256,
        old_capture.transport_proof_sha256,old_capture.attestor_key_sha256,old_capture.worker_image_sha256,old_capture.captured_bytes)
       IS NOT DISTINCT FROM ROW('01eaf753-8021-41e2-a936-9968656eb979'::uuid,'e68a79ad-0319-4109-b663-81f6c241d0fd'::uuid,
        'source.course.sqlite_expression.20261003'::text,1,'root.course.sqlite_expression.20261003'::text,
        '93727d8f15d0190e75b0d7e4dae1a3b58fe5024cda663df1979ca7d5ca038890'::text,
        'fe5d28e9acf02aee4cfa5c4a34a3368373c7b1655ff710103008a33fdbce4593'::text,
        'course.source.sqlite_expression.e68a79ad-0319-4109-b663-81f6c241d0fd'::text,
        '2026-10-03T16:56:54.411634+08:00'::timestamptz,'2026-10-03T16:56:56.669763+08:00'::timestamptz,
        '2026-10-03 16:56:56.666858+08:00'::timestamptz,'e2d855812998814eef43c4d009a19eade9511b990384400daf8895d25b5f02e8'::text,
        'e7db2cfd44c6d73f921721e44d8c220b6ba543620ac64053087aef25cce91ea6'::text,
        '151c22041e9c7464bfb51fc9290ce7ddfb59e747adf571de9a6a90ff6f158d3e'::text,
        'faa183112c8383d9c623672fc2230fd26e256faff293febe8c397466bbba63ae'::text,379232)) OR
      (k=2 AND ROW(old_capture.id,old_attempt.id,old_attempt.policy_id,old_attempt.generation,
        old_attempt.root_id,old_attempt.canonical_url_sha256,old_attempt.request_hash,old_attempt.operation_key,
        old_attempt.dispatched_at,old_attempt.settled_at,old_capture.fetched_at,old_capture.fetched_sha256,
        old_capture.transport_proof_sha256,old_capture.attestor_key_sha256,old_capture.worker_image_sha256,old_capture.captured_bytes)
       IS NOT DISTINCT FROM ROW('0f459f6a-66d2-4eac-9828-ff48da41fe83'::uuid,'bfd46b39-50b5-4444-ba85-32f54550f5d3'::uuid,
        'source.course.sqlite_functions.20261003'::text,1,'root.course.sqlite_functions.20261003'::text,
        'f467154a2c43cb62ef1b9102aa6f6b259dcd4453109e4b0d3c3fff226bda7ee9'::text,
        '232bde0f77dc0f8423bcaf658ea12d2371e87b68d5f80a024b0acadbc4045431'::text,
        'course.source.sqlite_functions.bfd46b39-50b5-4444-ba85-32f54550f5d3'::text,
        '2026-10-03T16:57:05.11462+08:00'::timestamptz,'2026-10-03T16:57:06.605941+08:00'::timestamptz,
        '2026-10-03 16:57:06.603533+08:00'::timestamptz,'fd7322767f7816f35fd179f0c6f22e0c6b10e1762f1b826c6420d6a9251694ac'::text,
        'd8158517f18475ee7759be742de09189c76799f6cf02ed4b41daf4a63a264ce7'::text,
        'e236a004501b3d10e26f98c3b29a790ebc1ee8fd23b24fa7818b04ccb82de4d9'::text,
        'faa183112c8383d9c623672fc2230fd26e256faff293febe8c397466bbba63ae'::text,42583))
     ) OR (SELECT count(*) FROM public.rag_registered_fetch_attempts
       WHERE canonical_url_sha256=old_policy.canonical_url_sha256 AND supplemental_authorization_id IS NULL)<>1
      THEN RETURN false; END IF;
    END IF;
    SELECT * INTO new_auth FROM public.rag_registered_supplemental_authorizations WHERE id=grant_row.supplemental_authorization_id FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO historical_root FROM public.rag_budget_authority_roots WHERE root_id=old_attempt.root_id FOR SHARE;
    IF NOT FOUND OR historical_root.enabled IS NOT TRUE OR
       ROW(old_attempt.policy_id,old_attempt.generation,old_attempt.root_id,old_attempt.canonical_url_sha256)
        IS DISTINCT FROM ROW(old_policy.policy_id,old_policy.generation,old_policy.root_id,old_policy.canonical_url_sha256) OR
       (k>0 AND (historical_root.cap_units<>1 OR historical_root.delegation_generation<>1 OR
        historical_root.period_key<>'course.sources.20261003' OR
        historical_root.delegation_id IS DISTINCT FROM 'delegation.course.'||target_name||'.20261003')) OR
       old_attempt.state<>'settled' OR old_attempt.settled_at IS NULL OR
       old_attempt.dispatched_at>old_attempt.settled_at OR old_attempt.settled_at>(frozen.proof_json->>'checked_at')::timestamptz OR
       old_attempt.response_sha256<>old_capture.fetched_sha256 OR old_attempt.response_bytes<>old_capture.captured_bytes OR
       old_attempt.dispatched_at>=old_policy.expires_at OR
       old_attempt.settled_at>=old_policy.retention_until OR old_attempt.settled_at>=old_capture.retention_until OR
       historical_root.policy_id<>old_policy.policy_id OR historical_root.policy_generation<>old_policy.generation OR
       old_attempt.dispatched_at<historical_root.period_start OR old_attempt.dispatched_at>=historical_root.period_end OR
       old_attempt.dispatched_at>=historical_root.delegation_expires_at OR
       ROW(new_auth.id,new_auth.course_refresh_authorization_id,new_auth.dispatch_id,new_auth.policy_id,new_auth.generation,
           new_auth.root_id,new_auth.request_hash,new_auth.prior_attempt_id,new_auth.expires_at,new_auth.approval_ref)
        IS DISTINCT FROM ROW(grant_row.supplemental_authorization_id,grant_row.id,grant_row.dispatch_id,grant_row.policy_id,
           grant_row.generation,grant_row.root_id,grant_row.request_hash,grant_row.latest_attempt_id,grant_row.dispatch_expires_at,
           (CASE k WHEN 0 THEN 'standingpolicy.m03-sqlite-source-recovery.20261019'::text
              ELSE 'standingpolicy.m03-companion-unspent-dispatch-successor.20261019'::text END)) OR
       new_auth.replaces_authorization_id IS NOT NULL OR new_auth.explicit_followup_id IS NOT NULL OR
       new_attempt.operation_key<>grant_row.operation_key OR new_attempt.dispatched_at<grant_row.issued_at OR
       new_attempt.dispatched_at>=grant_row.dispatch_expires_at OR new_attempt.settled_at IS NULL OR
       new_attempt.settled_at<new_attempt.dispatched_at OR new_attempt.settled_at>new_source.issued_at OR
       new_attempt.settled_at>=grant_row.source_expires_at OR
       EXISTS(SELECT 1 FROM public.rag_registered_supplemental_revocations v WHERE v.authorization_id IN(old_auth.id,new_auth.id)
          OR v.prior_attempt_id IN(old_attempt.id,new_attempt.id)) THEN RETURN false; END IF;
$new586$;
 old_claim_block constant text := $oldclaim586$       PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
         WHERE ad.receipt_handle=b->>'admission_receipt_id' AND cr.verification_receipt_hash=e->>'claim_receipt_hash'
           AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash FOR SHARE OF cr,ad;
       IF NOT FOUND THEN RETURN false; END IF;$oldclaim586$;
 new_claim_block constant text := $newclaim586$       -- Typed ClaimEvidenceReceipt hash and signed-source verification hash are
       -- different domains. Verify BOTH original-owner projections independently.
       PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
         WHERE ad.receipt_handle=b->>'admission_receipt_id'
           AND cr.assessment_evidence_id=new_source.id
           AND cr.id=(new_source.signed_proof->'payload'->>'claim_id')::uuid
           AND cr.receipt_handle=new_source.claim_handle AND cr.receipt_handle=b->>'claim_receipt_id'
           AND cr.receipt_handle=e->>'claim_id' AND cr.claim_hash=new_source.claim_hash
           AND cr.demand_hash=new_source.demand_hash AND cr.source_document_hash=r.document_hash
           AND cr.subject_id=new_prepared->'demand'->'scope'->>'subject_id'
           AND cr.subject_version=new_prepared->'demand'->'scope'->>'subject_version'
           AND to_jsonb(cr.scope_facets)=new_prepared->'demand'->'scope'->'facets'
           AND cr.execution_receipt_handle=new_source.execution_handle
           AND cr.execution_receipt_handle=e->>'execution_receipt_id'
           AND cr.execution_scope_json=material->'exact_claims'->0->'execution_scope'
           AND cr.method='isolated_execution' AND cr.verified_at=new_source.issued_at
           AND cr.independent_admission_id IS NULL AND cr.independent_document_hash IS NULL
           AND cr.applicability_hash=encode(digest(cr.applicability,'sha256'),'hex')
           AND cr.verification_receipt_hash=new_source.proof_hash
           AND new_source.proof_hash=item_supply_internal.snapshot_hash(new_source.signed_proof)
           AND e->>'claim_receipt_hash'=item_supply_internal.snapshot_hash(jsonb_build_object(
             'receipt_id',cr.receipt_handle,'demand_hash',cr.demand_hash,'purpose','assessment_evidence',
             'admission_receipt_id',ad.receipt_handle,'claim_hash',cr.claim_hash,
             'scope',new_prepared->'demand'->'scope','source_handle',new_source.source_handle,
             'document_handle',new_source.document_handle,'document_revision',new_source.document_hash,
             'document_hash',cr.source_document_hash,'applicability',cr.applicability,'method',cr.method,
             'primary_lineage_family',NULL,'independent_lineage_family',NULL,'independent_source_handle',NULL,
             'independent_document_handle',NULL,'independent_document_revision',NULL,'independent_document_hash',NULL,
             'independent_lineage_verified',false,'execution_receipt_id',cr.execution_receipt_handle,
             'execution_scope',cr.execution_scope_json,'verified',true,'revoked',false))
           AND cr.revoked_at IS NULL FOR SHARE OF cr,ad;
       IF NOT FOUND THEN RETURN false; END IF;$newclaim586$;
BEGIN
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p
  WHERE p.oid=5414997 AND p.oid=to_regprocedure('public.native_consumer_m03_p1_source_current(uuid,uuid,jsonb,boolean)');
 IF NOT FOUND OR current_database()<>'aearn_b1d_sandbox_20261001' OR
    pg_get_userbyid(actual.proowner)<>'aearn_b1d_runtime_20261001' OR
    (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs THEN
  RAISE check_violation USING MESSAGE='586 exact installed585 OID owner ACL and all attributes required'; END IF;
 source:=actual.prosrc; before_attrs:=to_jsonb(actual)-'prosrc';
 IF encode(sha256(convert_to(source,'UTF8')),'hex')='1442c5470abd5b9464a648d1a67c4fcd6c16da75a1c53224b8609f897c1c1eba' THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')<>'31ccd7db6111df49c0e32796d4b31ac98367ffde7c9d30d6a06037d22b3d9431' THEN
  RAISE check_violation USING MESSAGE='586 exact installed585 receiver body required'; END IF;
 IF length(source)-length(replace(source,old_block,''))<>length(old_block) THEN
  RAISE check_violation USING MESSAGE='586 exact single historical receiver block required'; END IF;
 IF length(source)-length(replace(source,old_claim_block,''))<>length(old_claim_block) THEN
  RAISE check_violation USING MESSAGE='586 exact single typed claim receiver block required'; END IF;
 replacement:=replace(replace(source,old_block,new_block),old_claim_block,new_claim_block);
 IF encode(sha256(convert_to(replacement,'UTF8')),'hex')<>'1442c5470abd5b9464a648d1a67c4fcd6c16da75a1c53224b8609f897c1c1eba' THEN
  RAISE check_violation USING MESSAGE='586 exact candidate receiver body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source) THEN
  RAISE check_violation USING MESSAGE='586 exact original function framing required'; END IF;
 definition:=replace(definition,source,replacement);
 default_at:=strpos(definition,'DEFAULT false')-1+length('DEFAULT ');
 IF default_at<length('DEFAULT ') OR default_at>45204 THEN
  RAISE check_violation USING MESSAGE='586 default node framing'; END IF;
 definition:=replace(definition,'DEFAULT false','DEFAULT '||repeat(' ',45204-default_at)||'false');
 EXECUTE definition;
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM before_attrs OR
    encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex')<>'1442c5470abd5b9464a648d1a67c4fcd6c16da75a1c53224b8609f897c1c1eba' THEN
  RAISE check_violation USING MESSAGE='586 replaced receiver metadata changed'; END IF;
END $patch586$;
