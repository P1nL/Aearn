-- C17: registered isolated-execution ClaimEvidenceReceipt and SignedSourceAssessment are distinct hash domains.
-- Exact final524 body patch only. All other source guards, locks, exact claims and final clock remain.
-- No old hash rewrite, alternate-hash acceptance, new object or authority restoration. Caller owns transaction.
DO $fix561$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old561$
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
     IF b->>'purpose'='assessment_evidence' THEN
       PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
         WHERE ad.receipt_handle=b->>'admission_receipt_id' AND cr.verification_receipt_hash=e->>'claim_receipt_hash'
           AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash FOR SHARE OF cr,ad;
       IF NOT FOUND THEN RETURN false; END IF;
     END IF;
   END LOOP;
   FOR claim IN SELECT value FROM jsonb_array_elements(material->'exact_claims') LOOP
     PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
       WHERE cr.receipt_handle=claim->>'claim_receipt_id' AND cr.claim_hash=claim->>'claim_hash'
         AND cr.demand_hash=claim->'binding'->>'demand_hash'
         AND cr.source_document_hash=claim->'binding'->>'document_hash'
         AND ad.receipt_handle=claim->'binding'->>'admission_receipt_id'
         AND cr.revoked_at IS NULL AND ad.active AND ad.revoked_at IS NULL FOR SHARE OF cr,ad;
     IF NOT FOUND THEN RETURN false; END IF;
   END LOOP;
 END LOOP;
 RETURN clock_timestamp()<deadline;
END $old561$;
 new_body constant text := $new561$
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
     IF b->>'purpose'='assessment_evidence' THEN
       -- Registered isolated-execution claims have TWO distinct canonical hash domains.
       -- Classify from the already resolved DB review/admission, never the supplied hash/handle.
       IF r.assessment_evidence_id IS NOT NULL AND EXISTS(
         SELECT 1 FROM rag_source_claim_receipts registered_claim
           JOIN rag_source_admissions registered_admission ON registered_admission.id=registered_claim.admission_id
           WHERE registered_admission.review_id=r.id AND registered_claim.method='isolated_execution') THEN
         PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
           JOIN rag_source_reviews claim_review ON claim_review.id=ad.review_id
           JOIN rag_assessment_source_evidence registered ON registered.id=cr.assessment_evidence_id
             AND registered.id=claim_review.assessment_evidence_id
           WHERE claim_review.id=r.id AND registered.id=r.assessment_evidence_id
             AND ad.receipt_handle=b->>'admission_receipt_id' AND ad.active AND ad.revoked_at IS NULL
             AND cr.method='isolated_execution' AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash
             AND cr.receipt_handle=e->>'claim_id' AND cr.receipt_handle=b->>'claim_receipt_id'
             AND registered.claim_handle=cr.receipt_handle
             AND cr.execution_receipt_handle=e->>'execution_receipt_id'
             AND registered.execution_handle=cr.execution_receipt_handle
             AND registered.claim_hash=cr.claim_hash AND registered.document_hash=cr.source_document_hash
             AND registered.revoked_at IS NULL
             AND cr.verification_receipt_hash=item_supply_internal.snapshot_hash(registered.signed_proof)
             AND e->>'claim_receipt_hash'=item_supply_internal.snapshot_hash(jsonb_build_object(
               'receipt_id',cr.receipt_handle,'demand_hash',cr.demand_hash,'purpose','assessment_evidence',
               'admission_receipt_id',ad.receipt_handle,'claim_hash',cr.claim_hash,
               'scope',jsonb_build_object('subject_id',cr.subject_id,'subject_version',cr.subject_version,'facets',to_jsonb(cr.scope_facets)),
               'source_handle',claim_review.source_handle,'document_handle',claim_review.document_handle,
               'document_revision',claim_review.document_hash,'document_hash',cr.source_document_hash,
               'applicability',cr.applicability,'method',cr.method,
               'primary_lineage_family',NULL,'independent_lineage_family',NULL,'independent_source_handle',NULL,
               'independent_document_handle',NULL,'independent_document_revision',NULL,'independent_document_hash',NULL,
               'independent_lineage_verified',false,'execution_receipt_id',cr.execution_receipt_handle,
               'execution_scope',cr.execution_scope_json,'verified',true,'revoked',false))
           FOR SHARE OF cr,ad;
       ELSE
       PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
         WHERE ad.receipt_handle=b->>'admission_receipt_id' AND cr.verification_receipt_hash=e->>'claim_receipt_hash'
           AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash FOR SHARE OF cr,ad;
       END IF;
       IF NOT FOUND THEN RETURN false; END IF;
     END IF;
   END LOOP;
   FOR claim IN SELECT value FROM jsonb_array_elements(material->'exact_claims') LOOP
     PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
       WHERE cr.receipt_handle=claim->>'claim_receipt_id' AND cr.claim_hash=claim->>'claim_hash'
         AND cr.demand_hash=claim->'binding'->>'demand_hash'
         AND cr.source_document_hash=claim->'binding'->>'document_hash'
         AND ad.receipt_handle=claim->'binding'->>'admission_receipt_id'
         AND cr.revoked_at IS NULL AND ad.active AND ad.revoked_at IS NULL FOR SHARE OF cr,ad;
     IF NOT FOUND THEN RETURN false; END IF;
   END LOOP;
 END LOOP;
 RETURN clock_timestamp()<deadline;
END $new561$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='561 original isolated writable transaction required'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_native_source_current(jsonb)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_native_source_current'
  OR actual.lanname IS DISTINCT FROM 'plpgsql' OR actual.prokind<>'f'
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM pg_catalog.format('%s','pg_catalog.jsonb'::regtype::oid)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['q']
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='561 original source receiver identity/attributes changed'; END IF;
 -- Keep the actual owner and entire ACL; never reassign or grant privileges.
 IF EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(actual.proacl,pg_catalog.acldefault('f',actual.proowner))) privilege
   WHERE privilege.grantee=0 AND privilege.privilege_type='EXECUTE')
 THEN RAISE check_violation USING MESSAGE='561 original source receiver PUBLIC privilege changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='561 original final524 source receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='561 original source receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.*,l.lanname INTO verified FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='561 source receiver metadata/OID/owner/ACL or body changed'; END IF;
END $fix561$;
