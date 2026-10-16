-- Explicit PUBLIC finite source/current ingress; not PRIVATE relabeling. 0 tables.
-- Installed486/503/504/508-529 bytes and historical facts/claims/UNKNOWN remain immutable.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='530 B1d only'; END IF; END $$;
DO $helpers530$
DECLARE expected record;actual record;
BEGIN
 FOR expected IN SELECT * FROM (VALUES
 ('item_supply_internal.public_normal_mapping_current(uuid,uuid,bigint)','f16fb7d1eb82deb33ce1492db4faa56c8ad43cfc3a4086df6665f637583e488d','jsonb',ARRAY['mid','u','e']::text[]),
 ('item_supply_internal.public_native_source_current(jsonb)','82dcdf136055421ab5c7f60f0606308abdb23d57214bfa83e0d22c92ad4447e2','bool',ARRAY['q']::text[])
 ) AS functions(signature,sha256,returntype,argnames) LOOP
  SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(expected.signature);
  IF FOUND AND (encode(sha256(convert_to(replace(actual.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM expected.sha256
   OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef
   OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
   OR actual.prorettype IS DISTINCT FROM to_regtype('pg_catalog.'||expected.returntype)
   OR actual.pronargs<>cardinality(expected.argnames) OR actual.proargnames IS DISTINCT FROM expected.argnames
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
  THEN RAISE check_violation USING MESSAGE='530 unknown public helper body/authority attributes'; END IF;
 END LOOP;
END $helpers530$;

CREATE OR REPLACE FUNCTION item_supply_internal.public_normal_mapping_current(mid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE m record;n jsonb;s record;
BEGIN
 PERFORM rag_actual_d_private_epoch(u,e,true);
 PERFORM item_supply_internal.native_exposure_lock(u,e);
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' OR NOT EXISTS(
    SELECT 1 FROM tutor_item_supply_user_epochs WHERE user_id=u AND epoch=e AND enabled)
 THEN RAISE check_violation USING MESSAGE='530 original current mapping epoch/read-write required'; END IF;
 SELECT * INTO m FROM tutor_item_supply_finite_course_mappings WHERE id=mid AND user_id=u AND epoch=e FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='530 original mapping missing'; END IF;
 n:=m.receipt_json->'frozen_node';
 PERFORM 1 FROM tutor_track_active_plans p JOIN tutor_track_plan_nodes node
 ON node.revision_id=p.revision_id AND node.track_id=p.track_id AND node.user_id=p.user_id
 WHERE p.user_id=u AND p.track_id=(n->>'track_id')::uuid AND p.revision_id=(n->>'revision_id')::uuid
 AND node.id=(n->>'node_id')::uuid AND node.knowledge_key=n->>'knowledge_key'
 AND node.title IS NOT DISTINCT FROM n->>'title' AND node.description IS NOT DISTINCT FROM n->>'description'
 AND node.is_core::text IS NOT DISTINCT FROM n->>'is_core' AND node.prerequisite_keys_json IS NOT DISTINCT FROM n->'prerequisite_keys'
 AND node.required_capabilities_json IS NOT DISTINCT FROM n->'required_capabilities'
 AND node.catalog_knowledge_key IS NOT DISTINCT FROM n->>'catalog_knowledge_key' FOR SHARE OF p,node;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='530 current actual goal missing'; END IF;
 PERFORM 1 FROM tutor_learning_plan_sessions ps JOIN tutor_learning_plan_drafts d ON d.id=ps.current_draft_id AND d.user_id=ps.user_id
 JOIN tutor_track_plan_revisions r ON r.id=m.revision_id AND r.user_id=u
 JOIN tutor_learning_tracks tr ON tr.id=m.track_id AND tr.user_id=u
 WHERE ps.id=m.session_id AND ps.user_id=u AND ps.status='confirmed' AND ps.confirmed_track_id=m.track_id
 AND d.id=m.draft_id AND d.draft_version::text IS NOT DISTINCT FROM n->>'draft_version'
 AND d.content_hash IS NOT DISTINCT FROM n->>'draft_content_hash'
 AND d.source_run_id::text IS NOT DISTINCT FROM n->>'source_run_id'
 AND d.source_input_revision::text IS NOT DISTINCT FROM n->>'source_input_revision'
 AND r.status='active' AND r.content_hash IS NOT DISTINCT FROM n->>'plan_content_hash'
 AND tr.language_id IS NOT DISTINCT FROM n->>'language_id' FOR SHARE OF ps,d,r,tr;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='530 current original confirmed plan required'; END IF;
 RETURN m.receipt_json;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.public_normal_mapping_current(uuid,uuid,bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.public_native_source_current(q jsonb) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb; material jsonb; e jsonb; b jsonb; claim jsonb; t timestamptz; r record;
 v record; proof record; prepared jsonb; claim_receipt jsonb; declared jsonb; computed_claim text;
 catalog constant jsonb:=$public530${"python-state-update-v1":{"profile_id":"python-state-source-v1","target_definition_hash":"185544231076d15cb9c50539e57bb1bf115ff748d68c35d0ae04d6e4346e3891","execution_scope":{"runtime_profile":"python-stdout-v1","input_hash":"a5fa214c0d4f22ab2d410008f0a8cd2a0dc1c72803a2fac82104efe9040c4690","semantics_hash":"dd49e089be93b846714fb21ca4bd1782a4b825349cbe6872b2415d83cdcfccd2"},"applicability":"Registered finite Python integer state curriculum: current RHS, ordered update, derived refresh, saved swap and conserved transfer; pinned runtime only.","course_goal_hash":"8807ca3ec1d3781318a6dac53faf0c72306b5bbefbe9fca58ceca50bd2658a45"},"python-kc-binding-v1":{"profile_id":"python-binding-source-v1","target_definition_hash":"ac716c31c68c112c9b73ecc68b90c0ccb7e29f1694a77e23038375c4d4795abd","execution_scope":{"runtime_profile":"python-stdout-v1","input_hash":"c403b921fd12ac9415d7ce64feacba5e081d0f41ad6b16301ecc8db5dbc57e3a","semantics_hash":"bc2e4b0118ea3c008d18be0cdd89fb8c6c16fea79632e1df64bac626fdf7ddfe"},"applicability":"Registered Python integer binding curriculum: RHS time, saved versus rebound names and non-live derived values; source semantic oracle, not a KC execution score.","course_goal_hash":"0556ea372de2883f7b68d6d4a8f0faeff44f368065c3debb964fd3e8b05c5b56"},"sqlite-predicate-order-v1":{"profile_id":"sqlite-predicate-source-v1","target_definition_hash":"333d8108ac641f79580e5c36df2a41fe9cc1271853d536c4d735f97b535b7b54","execution_scope":{"runtime_profile":"sqlite-query-v1","input_hash":"b1a49f9b5eecec2633fa26627bb94864a5b8bfc016f1086e09619b344fca97ed","semantics_hash":"b18eb774bca700bb53926345de0adec515d468ededfc6c7fc3c9232622139e85"},"applicability":"Registered finite SQLite predicate/order curriculum: AND, NULL fallback, exclusive flags, strict cursor, multiset and full order; pinned runtime only.","course_goal_hash":"7f496a72d293b3a54a2d9b43197b635736a9c8f337196af0778ab332da123c23"}}$public530$;
 deadline timestamptz := 'infinity'::timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' OR item_supply_internal.snapshot_keys(q,ARRAY['request','ref']) IS DISTINCT FROM true
  OR q->'request'->>'schema_version' IS DISTINCT FROM 'item_generation_request_v2' THEN RETURN false; END IF;
 PERFORM item_supply_internal.public_normal_mapping_current((q->'ref'->>'mapping_receipt_id')::uuid,
  (q->'ref'->>'user_id')::uuid,(q->'ref'->>'epoch')::bigint);
 p:=jsonb_build_object('materials',q->'request'->'materials');
 IF p IS NULL OR jsonb_typeof(p->'materials') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'materials') NOT BETWEEN 1 AND 12 THEN RETURN false; END IF;
 FOR material IN SELECT value FROM jsonb_array_elements(p->'materials') LOOP
   declared:=catalog->(material->'binding'->>'target_id');
   IF declared IS NULL THEN RETURN false; END IF;
   IF material->'binding'->>'target_definition_hash' IS DISTINCT FROM declared->>'target_definition_hash'
     OR material->'binding'->>'course_goal_hash' IS DISTINCT FROM declared->>'course_goal_hash'
     OR material->'binding'->>'contract_version' IS DISTINCT FROM 'rag_public_course_binding_v1'
     OR material->'access_request'->>'actor_id' IS DISTINCT FROM 'service.rag-public-course'
     OR material->'access_request'->>'action' IS DISTINCT FROM 'consume'
     OR material->'access_request'->>'purpose' IS DISTINCT FROM 'assessment_evidence'
     OR material->'binding'->>'purpose' IS DISTINCT FROM 'assessment_evidence'
     OR material->'binding'->>'binding_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash((material->'binding')-'binding_digest')
     OR material->'access_request'->'scope' IS DISTINCT FROM material->'binding'->'demand'->'scope'
     OR material->'access_request'->>'demand_hash' IS DISTINCT FROM material->'binding'->'demand'->>'demand_hash'
     OR jsonb_typeof(material->'exact_claims') IS DISTINCT FROM 'array'
     OR jsonb_array_length(material->'exact_claims') IS DISTINCT FROM jsonb_array_length(material->'binding'->'evidence')
     OR material->>'classification' IS DISTINCT FROM 'approved_public'
     OR jsonb_typeof(material->'binding'->'evidence') IS DISTINCT FROM 'array'
     OR jsonb_array_length(material->'binding'->'evidence') NOT BETWEEN 1 AND 12 THEN RETURN false; END IF;
   FOR e IN SELECT value FROM jsonb_array_elements(material->'binding'->'evidence') LOOP
     b:=e->'binding';
     -- Original C lock order: version -> links/source/claim -> final active pointer.
     SELECT * INTO v FROM grounding_corpus_versions WHERE id=(e->>'corpus_version_id')::uuid FOR UPDATE;
     IF NOT FOUND OR v.state IS DISTINCT FROM 'published' OR v.summary_hash IS DISTINCT FROM e->>'summary_hash'
       OR v.subject_id IS DISTINCT FROM e->>'subject_id'
       OR v.subject_id IS DISTINCT FROM material->'access_request'->'scope'->>'subject_id'
       OR v.subject_version IS DISTINCT FROM material->'access_request'->'scope'->>'subject_version'
       OR v.registry_digest IS DISTINCT FROM e->>'registry_digest'
       OR item_supply_internal.snapshot_hash(v.validation_summary_json) IS DISTINCT FROM e->>'validation_hash'
       OR item_supply_internal.snapshot_hash(v.coverage_summary_json) IS DISTINCT FROM e->>'coverage_hash'
       OR item_supply_internal.snapshot_hash(to_jsonb(v.retrieval_policy_version)) IS DISTINCT FROM e->>'retrieval_hash'
     THEN RETURN false; END IF;
     PERFORM 1 FROM grounding_corpus_chunks chunk
       JOIN grounding_corpus_documents doc ON doc.corpus_version_id=chunk.corpus_version_id AND doc.document_id=chunk.document_id
       JOIN rag_corpus_admission_links link ON link.corpus_id=chunk.corpus_version_id AND link.document_id=chunk.document_id
       JOIN rag_source_admissions admission ON admission.id=link.admission_id
       JOIN rag_source_reviews review ON review.id=admission.review_id
       WHERE chunk.corpus_version_id=v.id AND chunk.chunk_id=e->>'chunk_id'
         AND chunk.document_id=b->>'document_handle' AND link.document_hash=b->>'document_hash'
         AND doc.document_hash=b->>'document_hash' AND chunk.chunk_hash=e->>'chunk_hash'
         AND encode(sha256(convert_to(chunk.content,'UTF8')),'hex')=e->>'approved_excerpt_hash'
         AND chunk.content=material->>'excerpt' AND review.id=(e->>'source_review_id')::uuid
         AND review.policy_id=e->>'source_policy_id' AND review.policy_generation=(e->>'source_policy_generation')::integer
         AND admission.receipt_handle=b->>'admission_receipt_id'
         AND chunk.facets_json @> (material->'access_request'->'scope'->'facets')
       FOR SHARE OF chunk,doc,link,admission,review;
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
       root.policy_id AS root_policy,root.policy_generation AS root_generation,admission.id AS admission_id,
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
     -- 486 PUBLIC isolated-execution proof registry, NOT rag_source_claim_receipts.
     SELECT se.*,cr.applicability,cr.admission_id AS claim_admission_id,cr.scope_facets,cr.execution_scope_json,
       cr.verification_receipt_hash INTO proof FROM rag_assessment_source_evidence se
       JOIN rag_source_claim_receipts cr ON cr.assessment_evidence_id=se.id AND cr.receipt_handle=se.claim_handle
         AND cr.method='isolated_execution' AND cr.revoked_at IS NULL AND cr.claim_hash=se.claim_hash
         AND cr.demand_hash=se.demand_hash AND cr.source_document_hash=se.document_hash
         AND cr.execution_receipt_handle=se.execution_handle AND cr.verification_receipt_hash=se.proof_hash
       WHERE se.claim_handle=b->>'claim_receipt_id' AND se.execution_handle=e->>'execution_receipt_id'
         AND se.claim_handle=e->>'claim_id' AND se.source_handle=b->>'source_handle'
         AND se.document_handle=b->>'document_handle' AND se.document_hash=b->>'document_hash'
         AND se.policy_id=e->>'source_policy_id' AND se.policy_generation=(e->>'source_policy_generation')::integer
       FOR SHARE OF se,cr;
     IF NOT FOUND OR proof.private_user_id IS NOT NULL OR proof.private_epoch IS NOT NULL
       OR proof.revoked_at IS NOT NULL OR proof.expires_at<=clock_timestamp()
       OR proof.proof_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(proof.signed_proof)
       OR proof.terminal_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(proof.signed_proof->'payload'->'terminal')
       OR proof.issued_at>clock_timestamp() OR (proof.signed_proof->'payload'->>'format' IS DISTINCT FROM 'aearn.rag.fresh-assessment-source.v1'
         AND proof.signed_proof->'payload'->>'format' IS DISTINCT FROM 'aearn.rag.fresh-assessment-source.v2')
       OR proof.signed_proof->'payload'->'prepared' ? 'actual_d'
       OR proof.id IS DISTINCT FROM r.assessment_evidence_id THEN RETURN false; END IF;
     prepared:=proof.signed_proof->'payload'->'prepared';
     computed_claim:=item_supply_internal.snapshot_hash(jsonb_build_object('profile',proof.profile_id,
       'spans',prepared->'spans','execution_scope',proof.execution_scope_json,'document_hash',proof.document_hash));
     IF proof.profile_id='sqlite-predicate-source-v1' THEN
       computed_claim:=item_supply_internal.snapshot_hash(jsonb_build_object('primary_claim_hash',computed_claim,
         'companions',prepared->'companions'));
     END IF;
     IF proof.claim_hash IS DISTINCT FROM computed_claim OR proof.profile_id IS DISTINCT FROM declared->>'profile_id'
       OR proof.execution_scope_json IS DISTINCT FROM declared->'execution_scope'
       OR proof.applicability IS DISTINCT FROM declared->>'applicability' THEN RETURN false; END IF;
     IF prepared->'demand'->>'demand_hash' IS DISTINCT FROM b->>'demand_hash'
       OR prepared->'demand'->'scope' IS DISTINCT FROM b->'scope'
       OR proof.claim_hash IS DISTINCT FROM (SELECT c->>'claim_hash' FROM jsonb_array_elements(material->'exact_claims') c
         WHERE c->>'claim_receipt_id'=proof.claim_handle)
       OR prepared->>'document_hash' IS DISTINCT FROM b->>'document_hash'
       OR prepared->>'source_handle' IS DISTINCT FROM proof.source_handle OR prepared->>'document_handle' IS DISTINCT FROM proof.document_handle
       OR prepared->>'capture_id' IS DISTINCT FROM proof.capture_id::text OR prepared->>'profile_id' IS DISTINCT FROM proof.profile_id
       OR prepared->>'policy_id' IS DISTINCT FROM proof.policy_id OR prepared->>'policy_generation' IS DISTINCT FROM proof.policy_generation::text
       OR prepared->'budget'->>'root_id' IS DISTINCT FROM proof.root_id
       OR prepared->'demand'->>'purpose' IS DISTINCT FROM 'assessment_evidence'
       OR proof.scope_facets IS DISTINCT FROM ARRAY(SELECT jsonb_array_elements_text(b->'scope'->'facets'))
       OR proof.signed_proof->'payload'->>'admission_id' IS DISTINCT FROM proof.claim_admission_id::text
       OR proof.signed_proof->'payload'->>'evidence_id' IS DISTINCT FROM proof.id::text
       OR proof.execution_handle IS DISTINCT FROM 'source-execution.'||replace(proof.id::text,'-','')
       OR proof.claim_handle IS DISTINCT FROM 'source-claim.'||replace(proof.signed_proof->'payload'->>'claim_id','-','')
       OR proof.signed_proof->'payload'->'terminal'->>'mode' IS DISTINCT FROM 'live'
       OR proof.signed_proof->'payload'->'terminal'->>'isolation' IS DISTINCT FROM 'approved_os_boundary'
       OR proof.signed_proof->'payload'->'terminal'->'result'->>'status' IS DISTINCT FROM 'success'
       OR proof.claim_admission_id IS DISTINCT FROM r.admission_id
     THEN RETURN false; END IF;
     claim_receipt:=jsonb_build_object('receipt_id',proof.claim_handle,'demand_hash',prepared->'demand'->>'demand_hash',
       'purpose','assessment_evidence','admission_receipt_id',b->>'admission_receipt_id',
       'claim_hash',proof.claim_hash,'scope',prepared->'demand'->'scope',
       'source_handle',proof.source_handle,'document_handle',proof.document_handle,
       'document_revision',proof.document_hash,'document_hash',proof.document_hash,'applicability',proof.applicability,
       'method','isolated_execution','primary_lineage_family',NULL,'independent_lineage_family',NULL,
       'independent_source_handle',NULL,'independent_document_handle',NULL,'independent_document_revision',NULL,
       'independent_document_hash',NULL,'independent_lineage_verified',false,'execution_receipt_id',proof.execution_handle,
       'execution_scope',proof.execution_scope_json,'verified',true,'revoked',false);
     IF item_supply_internal.snapshot_hash(claim_receipt) IS DISTINCT FROM e->>'claim_receipt_hash' THEN RETURN false; END IF;
     FOR claim IN SELECT value FROM jsonb_array_elements(material->'exact_claims') WHERE value->>'claim_receipt_id'=proof.claim_handle LOOP
       IF claim->'binding' IS DISTINCT FROM b OR claim->'scope' IS DISTINCT FROM b->'scope'
         OR claim->>'claim_hash' IS DISTINCT FROM proof.claim_hash OR claim->>'applicability' IS DISTINCT FROM proof.applicability
         OR claim->'execution_scope' IS DISTINCT FROM proof.execution_scope_json THEN RETURN false; END IF;
     END LOOP;
     deadline:=LEAST(deadline,proof.expires_at);
     PERFORM 1 FROM grounding_active_corpora active WHERE active.subject_id=v.subject_id
       AND active.corpus_version_id=v.id AND active.generation=(e->>'active_generation')::integer FOR SHARE;
     IF NOT FOUND THEN RETURN false; END IF;
   END LOOP;

 END LOOP;
 RETURN clock_timestamp()<deadline;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.public_native_source_current(jsonb) FROM PUBLIC;

DO $upgrade530_continuation$
DECLARE actual record;verified record;definition text;source text;
 old_sha constant text:='4747daa0a01ba9e3370d4fcc9405218c42ae98b1a1624a0217e615a06907cf80';new_sha constant text:='08ed45d7d088992ba6d9e9ee6d3db0745509dc4f39f1dfca98ffa69aa1106191';
 reviewed_body constant text:=$body530_continuation$
DECLARE a record; c record; root_facts record; t timestamptz; snapshot jsonb; b jsonb:=NEW.binding_json;
  phase_row record; version_row record; private_header record; phase jsonb;
  stage_key text; persistent_permission boolean:=false;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared continuation B1d owner required';
  END IF;
  SELECT c1.*,j.root_id,j.parent_job_id,j.job_key,p.profile_hash,p.profile_json INTO c
    FROM tutor_item_supply_shared_job_controls c1 JOIN tutor_item_supply_shared_jobs j ON j.id=c1.job_id
    JOIN tutor_item_supply_parameter_profiles p ON p.id=c1.profile_id
    WHERE c1.job_id=NEW.job_id FOR UPDATE OF c1;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation job unavailable'; END IF;
  stage_key:='continue.'||replace(NEW.generation_artifact_id::text,'-','')||'.'||NEW.operation_key;
  IF NEW.operation_key LIKE 'persistent.%' AND c.job_key IS DISTINCT FROM encode(digest(convert_to(
      NEW.root_id::text||chr(31)||stage_key,'UTF8'),'sha256'),'hex') THEN
    -- Controlled ancestry wins BEFORE looking for any normal phase permission.
    PERFORM id FROM tutor_item_supply_shared_generation_artifacts
      WHERE id=NEW.generation_artifact_id AND root_id=NEW.root_id
        AND item_supply_internal.controlled_counterexample_held(job_id) IS FALSE FOR SHARE;
    IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(NEW.job_id) IS DISTINCT FROM false
    THEN RAISE check_violation USING MESSAGE='528 controlled ancestry denied first'; END IF;
    IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off'
      OR item_supply_internal.snapshot_keys(b,ARRAY['schema_version','operation_key','root_id','canonical_root_key',
        'coverage_blueprint_hash','scope_hash','generation_artifact_id','original_job_id','original_lease_generation',
        'original_profile_hash','artifact_hash','original_request_hash','material_set_hash','source_receipt_set_hash',
        'candidate_id','item_id','version_id','source_hash','content_hash','target_id','target_definition_hash',
        'specification_hash','adoption_lease','authority','execution_authority_reusable','publication_enabled']) IS DISTINCT FROM true
      OR b->>'schema_version' IS DISTINCT FROM 'shared_candidate_continuation_v1'
    THEN RAISE check_violation USING MESSAGE='528 closed original binding and read-write phase required'; END IF;
    IF (SELECT count(*) FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.record_kind='phase' AND j.job_id=NEW.job_id AND j.root_id=NEW.root_id
        AND NEW.operation_key='persistent.'||replace(j.phase_id::text,'-',''))<>1
    THEN RAISE check_violation USING MESSAGE='528 unique original candidate phase required'; END IF;
    SELECT j.* INTO phase_row FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.record_kind='phase' AND j.job_id=NEW.job_id AND j.root_id=NEW.root_id
        AND NEW.operation_key='persistent.'||replace(j.phase_id::text,'-','') FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='528 committed original candidate phase required'; END IF;
    phase:=phase_row.payload_json;
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
    IF phase->>'kind' IS DISTINCT FROM 'candidate' OR phase->>'job_id' IS DISTINCT FROM NEW.job_id::text
      OR phase->>'root_id' IS DISTINCT FROM NEW.root_id::text
      OR phase->>'phase_id' IS DISTINCT FROM phase_row.phase_id::text
      OR phase->>'public_task_id' IS DISTINCT FROM phase_row.public_task_id::text
      OR phase->'lease' IS DISTINCT FROM b->'adoption_lease'
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j
        WHERE j.phase_id=phase_row.phase_id AND j.record_kind='phase_result')
    THEN RAISE check_violation USING MESSAGE='528 exact active candidate phase lease required'; END IF;
    SELECT j.* INTO version_row FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.public_task_id=phase_row.public_task_id AND j.record_kind IN('version','qualified')
        AND j.payload_json->>'revision_id'=phase->>'revision_id'
      ORDER BY j.created_at DESC,j.id LIMIT 1 FOR SHARE;
    IF NOT FOUND OR version_row.root_id IS DISTINCT FROM NEW.root_id
      OR version_row.payload_json->>'artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
      OR version_row.payload_json->'public_slot_id' IS DISTINCT FROM phase->'public_slot_id'
      OR version_row.payload_json->>'root_id' IS DISTINCT FROM NEW.root_id::text
      OR b->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(version_row.payload_json->'specification')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j
        WHERE j.public_task_id=phase_row.public_task_id AND j.record_kind IN('version','qualified')
          AND j.payload_json->'public_slot_id'=phase->'public_slot_id'
          AND (j.payload_json->>'revision_seq')::integer>(version_row.payload_json->>'revision_seq')::integer)
    THEN RAISE check_violation USING MESSAGE='528 exact current fixed-slot immutable artifact required'; END IF;
    IF (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j
      JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=j.pack_task_id
        AND attachment.user_id=j.user_id AND attachment.epoch=j.epoch AND attachment.scope_id=j.scope_id
        AND attachment.record_kind='phase'
        AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
        AND attachment.payload_json->>'phase_id'=phase_row.phase_id::text
        AND attachment.payload_json->>'public_task_id'=phase_row.public_task_id::text
      WHERE j.record_kind='task' AND j.id=j.pack_task_id
        AND j.payload_json->'ref'->>'public_task_id'=phase_row.public_task_id::text)<>1
    THEN RAISE check_violation USING MESSAGE='528 unique original private phase attachment required'; END IF;
    SELECT j.* INTO private_header FROM tutor_item_supply_private_persistent_pack_journal j
      JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=j.pack_task_id
        AND attachment.user_id=j.user_id AND attachment.epoch=j.epoch AND attachment.scope_id=j.scope_id
        AND attachment.record_kind='phase'
        AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
        AND attachment.payload_json->>'phase_id'=phase_row.phase_id::text
        AND attachment.payload_json->>'public_task_id'=phase_row.public_task_id::text
      WHERE j.record_kind='task' AND j.id=j.pack_task_id
        AND j.payload_json->'ref'->>'public_task_id'=phase_row.public_task_id::text FOR SHARE OF j,attachment;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='528 original private task attachment required'; END IF;
    PERFORM item_supply_internal.public_normal_mapping_current(
      (private_header.payload_json->'ref'->>'mapping_receipt_id')::uuid,private_header.user_id,private_header.epoch::bigint);
    persistent_permission:=true;
    stage_key:='persistent.phase.'||replace(phase_row.phase_id::text,'-','');
  END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.parent_job_id IS NOT NULL
    OR c.lease_owner IS DISTINCT FROM b->'adoption_lease'->>'lease_owner'
    OR c.lease_generation::text IS DISTINCT FROM b->'adoption_lease'->>'generation'
    OR c.state_version::text IS DISTINCT FROM b->'adoption_lease'->>'state_version'
    OR c.lease_expires_at IS NULL OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM b->'adoption_lease'->'profile'
    OR c.profile_hash IS DISTINCT FROM snapshot->>'profile_hash'
    OR c.job_key IS DISTINCT FROM encode(digest(convert_to(NEW.root_id::text||chr(31)||
        stage_key,'UTF8'),'sha256'),'hex') THEN
    RAISE check_violation USING MESSAGE='continuation current new-job lease mismatch';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id THEN
    RAISE check_violation USING MESSAGE='continuation must retain original canonical root';
  END IF;
  SELECT r.canonical_key,bp.blueprint_hash,o.provider_key INTO root_facts
    FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_blueprints bp ON bp.id=r.blueprint_id
    JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id WHERE r.id=NEW.root_id FOR SHARE OF r,bp,o;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation root unavailable'; END IF;
  IF b->>'root_id' IS DISTINCT FROM NEW.root_id::text OR b->>'generation_artifact_id' IS DISTINCT FROM a.id::text
    OR b->>'original_job_id' IS DISTINCT FROM a.job_id::text
    OR b->>'original_lease_generation' IS DISTINCT FROM a.lease_generation::text
    OR b->>'candidate_id' IS DISTINCT FROM a.candidate_id::text OR b->>'item_id' IS DISTINCT FROM a.item_id::text
    OR b->>'version_id' IS DISTINCT FROM a.version_id::text OR b->>'source_hash' IS DISTINCT FROM a.source_hash
    OR b->>'content_hash' IS DISTINCT FROM a.content_hash OR b->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR b->>'target_id' IS DISTINCT FROM a.target_id OR b->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR b->>'operation_key' IS DISTINCT FROM NEW.operation_key
    OR b->>'canonical_root_key' IS DISTINCT FROM root_facts.canonical_key
    OR b->>'coverage_blueprint_hash' IS DISTINCT FROM root_facts.blueprint_hash
    OR b->>'scope_hash' IS DISTINCT FROM a.request_json->>'scope_hash'
    OR b->>'original_profile_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_hash'
    OR b->>'original_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json)
    OR b->>'material_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json->'materials')
    OR b->>'source_receipt_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.receipt_json->'sources')
    OR b->'adoption_lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR b->'adoption_lease'->>'visibility' IS DISTINCT FROM 'public'
    OR b->'adoption_lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb
    OR b->'adoption_lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR snapshot->>'profile_key_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_key_hash'
    OR c.profile_json->'profile_key'->>'provider' IS DISTINCT FROM root_facts.provider_key
    OR a.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
    OR b->>'authority' IS DISTINCT FROM 'immutable_generation_data_only'
    OR b->'execution_authority_reusable' IS DISTINCT FROM 'false'::jsonb
    OR b->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN
    RAISE check_violation USING MESSAGE='continuation immutable original binding mismatch';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id
      AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=a.reservation_id
      AND s.settlement_key='generation.'||replace(a.candidate_id::text,'-','')) THEN
    RAISE check_violation USING MESSAGE='continuation requires complete settled original generation';
  END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=NEW.job_id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=NEW.job_id AND stage='generating')
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=NEW.job_id AND reservation_key LIKE 'gen.%') THEN
    RAISE check_violation USING MESSAGE='continuation cannot masquerade as new generation';
  END IF;
  IF persistent_permission THEN
    -- No new author permissions: retain complete original491 checks above.
    -- Current source and all real phase deadlines are rechecked AFTER every wait.
    IF version_row.payload_json->'specification'->'blueprint' IS DISTINCT FROM a.request_json->'blueprint'
      OR version_row.payload_json->'specification'->'public_template' IS DISTINCT FROM a.request_json->'public_template'
      OR item_supply_internal.public_native_source_current(jsonb_build_object(
        'request',a.request_json,'ref',private_header.payload_json->'ref')) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='528 original fixed specification/current source required'; END IF;
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
    t:=clock_timestamp();
    IF COALESCE(c.lease_expires_at>t,false) IS DISTINCT FROM true OR COALESCE(c.parent_deadline>t,false) IS DISTINCT FROM true
      OR COALESCE((phase->>'valid_until')::timestamptz>t,false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='528 final acceptance deadline expired'; END IF;
  END IF;
  RETURN NEW;
END $body530_continuation$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('public.enforce_item_supply_shared_candidate_continuation()');
 IF NOT FOUND OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef
  OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype
  OR actual.pronargs<>0 OR actual.proargnames IS DISTINCT FROM NULL::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='530 original continuation receiver authority attributes changed'; END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR encode(sha256(convert_to(reviewed_body,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='530 original continuation receiver source changed'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1
 THEN RAISE check_violation USING MESSAGE='530 original continuation receiver framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,reviewed_body);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='530 original continuation receiver attributes/owner/ACL changed'; END IF;
END $upgrade530_continuation$;

DO $upgrade530_normal$
DECLARE actual record;verified record;definition text;source text;
 old_sha constant text:='3d90ba5383546ee4576656f34daf3f2d846519385aa5d9a41d3144da207a68c0';new_sha constant text:='1e4139459d5138c5af7f205a226b0747e27f9dcaaa846acce3a8a41dc66e9401';
 reviewed_body constant text:=$body530_normal$
DECLARE a record; vr record; br record; rr record; continuation record; header record; pair_fact record;
 phase jsonb; f jsonb; req jsonb; finding jsonb; member jsonb; pair_id uuid; expected_fields jsonb;
 stamp timestamptz; peer_count integer; clone_count integer; bound_pair jsonb; original jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' THEN RAISE check_violation USING MESSAGE='525 original read-write boundary required'; END IF;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'generation_artifact_id')::uuid FOR SHARE;
 -- Controlled ancestry ALWAYS wins, before payload/normal permission.
 IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='525 controlled ancestry denied first'; END IF;
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','preparation_id','root_id','lease','generation_artifact_id','artifact_hash',
  'validation_receipt_id','blind_receipt_id','review_receipt_id','review_receipt_hash','original_review_reservation_id','continuation_binding_hash',
  'reservation_id','reservation_key','request_hash','request_payload','identity','resources','source_deadlines','deadline_at','timeout_seconds',
  'publication_enabled','admission_eligible','persistent_frame']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(p->'persistent_frame',ARRAY['schema_version','phase','original_review_frame']) IS DISTINCT FROM true
  OR p->'persistent_frame'->>'schema_version' IS DISTINCT FROM 'persistent_normal_investigation_frame_v1'
 THEN RAISE check_violation USING MESSAGE='525 explicit concrete frame required'; END IF;
 phase:=p->'persistent_frame'->'phase'; f:=p->'persistent_frame'->'original_review_frame'; req:=p->'request_payload';
 PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
 IF phase->>'kind' IS DISTINCT FROM 'candidate' OR phase->>'root_id' IS DISTINCT FROM a.root_id::text
  OR phase->'lease' IS DISTINCT FROM p->'lease' OR p->>'root_id' IS DISTINCT FROM a.root_id::text
  OR p->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
  OR item_supply_internal.snapshot_keys(f,ARRAY['schema_version','phase_id','review_receipt_id','blind_receipt_id',
       'validation_receipt_id','review_hash','blind_hash','validation_hash','continuation_binding_hash']) IS DISTINCT FROM true
  OR f->>'schema_version' IS DISTINCT FROM 'persistent_committed_review_frame_v1' OR f->'phase_id' IS DISTINCT FROM phase->'phase_id'
  OR f->>'review_receipt_id' IS DISTINCT FROM p->>'review_receipt_id' OR f->>'review_hash' IS DISTINCT FROM p->>'review_receipt_hash'
  OR f->>'blind_receipt_id' IS DISTINCT FROM p->>'blind_receipt_id' OR f->>'validation_receipt_id' IS DISTINCT FROM p->>'validation_receipt_id'
  OR f->>'continuation_binding_hash' IS DISTINCT FROM p->>'continuation_binding_hash'
 THEN RAISE check_violation USING MESSAGE='525 exact original phase/root/review frame required'; END IF;
 SELECT payload_json INTO original FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=(phase->>'public_task_id')::uuid
  AND record_kind IN('version','qualified') AND payload_json->>'revision_id'=phase->>'revision_id' ORDER BY created_at DESC,id LIMIT 1 FOR SHARE;
 IF NOT FOUND OR original->>'artifact_id' IS DISTINCT FROM a.id::text OR original->'public_slot_id' IS DISTINCT FROM phase->'public_slot_id'
  OR original->>'root_id' IS DISTINCT FROM a.root_id::text
 THEN RAISE check_violation USING MESSAGE='525 immutable fixed parent slot required'; END IF;
 SELECT * INTO continuation FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=(phase->>'job_id')::uuid
  AND generation_artifact_id=a.id AND root_id=a.root_id FOR SHARE;
 IF NOT FOUND OR continuation.binding_hash IS DISTINCT FROM f->>'continuation_binding_hash'
  OR continuation.binding_json->'adoption_lease' IS DISTINCT FROM phase->'lease'
  OR continuation.binding_json->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(original->'specification')
 THEN RAISE check_violation USING MESSAGE='525 original491 exact current adoption required'; END IF;
 SELECT r.* INTO rr FROM tutor_item_supply_shared_pipeline_receipts r WHERE id=(f->>'review_receipt_id')::uuid
  AND generation_artifact_id=a.id AND artifact_kind='review_bundle' AND mode='live' FOR SHARE;
 SELECT r.* INTO br FROM tutor_item_supply_shared_pipeline_receipts r WHERE id=(f->>'blind_receipt_id')::uuid
  AND generation_artifact_id=a.id AND artifact_kind='blind_solve' AND mode='live' FOR SHARE;
 SELECT r.* INTO vr FROM tutor_item_supply_shared_pipeline_receipts r WHERE id=(f->>'validation_receipt_id')::uuid
  AND generation_artifact_id=a.id AND artifact_kind='validation' AND mode='live' FOR SHARE;
 IF rr.id IS NULL OR br.id IS NULL OR vr.id IS NULL OR rr.receipt_hash IS DISTINCT FROM f->>'review_hash'
  OR br.receipt_hash IS DISTINCT FROM f->>'blind_hash' OR vr.receipt_hash IS DISTINCT FROM f->>'validation_hash'
  OR (rr.job_id,rr.lease_generation,rr.lease_owner) IS DISTINCT FROM (br.job_id,br.lease_generation,br.lease_owner)
  OR (rr.job_id,rr.lease_generation,rr.lease_owner) IS DISTINCT FROM (vr.job_id,vr.lease_generation,vr.lease_owner)
  OR rr.payload_json->'blind_solve' IS DISTINCT FROM br.payload_json
  OR rr.payload_json->'binding'->>'source_hash' IS DISTINCT FROM a.source_hash
  OR rr.payload_json->'binding'->>'content_hash' IS DISTINCT FROM a.content_hash
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts r WHERE id IN(rr.id,br.id,vr.id)
     AND xmin::text::bigint=(txid_current()%4294967296))
 THEN RAISE check_violation USING MESSAGE='525 original committed validation/blind/six DATA required'; END IF;
 IF item_supply_internal.snapshot_keys(req,ARRAY['schema_version','purpose','authority','review_receipt_id','review_receipt_hash',
      'review_input','execution_profile_hash','revision_allocation','disputes','evidence_index']) IS DISTINCT FROM true
  OR (req->'review_input'-ARRAY['schema_version','binding','role','source','validation_receipt','validation_receipt_hash','scoring_descriptor'])<>'{}'::jsonb
  OR req->'review_input'->>'schema_version' IS DISTINCT FROM 'item_supply_review_input_v2'
  OR req->'review_input'->>'role' IS DISTINCT FROM 'technical'
  OR req->>'schema_version' IS DISTINCT FROM 'persistent_normal_investigation_input_v1'
  OR req->>'purpose' IS DISTINCT FROM 'same_item_substantive_repair' OR req->>'authority' IS DISTINCT FROM 'original_shared_owner_required'
  OR req->>'execution_profile_hash' IS DISTINCT FROM phase->'lease'->'profile'->>'profile_hash'
  OR req->'review_input'->'binding' IS DISTINCT FROM rr.payload_json->'binding'
  OR req->'review_input'->'source' IS DISTINCT FROM a.source_json OR req->'review_input'->'validation_receipt' IS DISTINCT FROM vr.payload_json
 THEN RAISE check_violation USING MESSAGE='525 retained quality/new execution explicit closure required'; END IF;
 SELECT h.* INTO header FROM tutor_item_supply_private_persistent_pack_journal h
  JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=h.pack_task_id
    AND attachment.user_id=h.user_id AND attachment.epoch=h.epoch AND attachment.scope_id=h.scope_id
  WHERE h.record_kind='task' AND attachment.record_kind='phase'
   AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
   AND attachment.payload_json->'phase_id'=phase->'phase_id' AND attachment.payload_json->'public_task_id'=phase->'public_task_id'
  ORDER BY h.id LIMIT 1 FOR SHARE OF h,attachment;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='525 original PRIVATE task attachment required'; END IF;
 PERFORM user_id FROM tutor_item_supply_user_epochs WHERE user_id=header.user_id AND epoch=header.epoch AND enabled FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='525 current user epoch required'; END IF;
 PERFORM id FROM tutor_item_supply_private_scopes WHERE id=header.scope_id AND user_id=header.user_id AND epoch=header.epoch FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='525 current private scope required'; END IF;
 -- Original A524 receiver implements the installed503/504 actual-D current mapping fence.
 PERFORM item_supply_internal.public_normal_mapping_current((header.payload_json->'ref'->>'mapping_receipt_id')::uuid,header.user_id,header.epoch::bigint);
 clone_count:=0; peer_count:=0;
 FOR finding IN SELECT value FROM jsonb_array_elements(req->'disputes') LOOP
  IF finding->>'schema_version'='persistent_deterministic_clone_finding_v1' THEN
   clone_count:=clone_count+1;
   IF item_supply_internal.snapshot_keys(finding,ARRAY['schema_version','role','safe_code','rule','pair','equal_fields','dispute_key','references',
       'model_finding_asserted','historical_finding_resolved']) IS DISTINCT FROM true
    OR finding->>'role' IS DISTINCT FROM 'deterministic' OR finding->>'safe_code' IS DISTINCT FROM 'assessment_clone'
    OR finding->>'rule' IS DISTINCT FROM 'original_assessment_clone_v2' OR finding->'references' IS DISTINCT FROM '[]'::jsonb
    OR finding->'model_finding_asserted' IS DISTINCT FROM 'false'::jsonb OR finding->'historical_finding_resolved' IS DISTINCT FROM 'false'::jsonb
    OR finding->>'dispute_key' IS DISTINCT FROM item_supply_internal.snapshot_hash(finding-'dispute_key')
    OR jsonb_typeof(finding->'pair') IS DISTINCT FROM 'array' OR jsonb_array_length(finding->'pair') IS DISTINCT FROM 2
    OR finding->'pair'->0->'version_id' IS NOT DISTINCT FROM finding->'pair'->1->'version_id'
   THEN RAISE check_violation USING MESSAGE='525 actual deterministic finding shape required'; END IF;
   bound_pair:=finding->'pair';
   FOR member IN SELECT value FROM jsonb_array_elements(bound_pair) LOOP
    pair_id:=(member->>'version_id')::uuid;
    SELECT n.*,g.job_id,g.root_id,g.id AS artifact_id,g.request_json,pe.occurred_at INTO pair_fact
      FROM tutor_item_supply_native_content_facts cf JOIN tutor_learning_item_native_publication_proofs n ON n.id=cf.proof_id
      JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=n.generation_artifact_id
      JOIN tutor_learning_item_publication_events pe ON pe.id=n.publication_event_id AND pe.state='published'
      WHERE cf.user_id=header.user_id AND cf.epoch=header.epoch AND cf.version_id=pair_id AND cf.content_json=member
       AND cf.proof_hash=n.proof_hash AND n.version_id=pair_id FOR SHARE OF cf,n,g,pe;
    IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(pair_fact.job_id) IS DISTINCT FROM false
      OR pair_fact.occurred_at<(pair_fact.proof_json->>'checked_at')::timestamptz
      OR pair_fact.occurred_at>(pair_fact.proof_json->>'valid_until')::timestamptz
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.public_task_id=(phase->>'public_task_id')::uuid
       AND j.record_kind='qualified' AND j.payload_json->>'published_version_id'=pair_id::text AND j.root_id=pair_fact.root_id
       AND j.payload_json->>'artifact_id'=pair_fact.artifact_id::text)
    THEN RAISE check_violation USING MESSAGE='525 exact original current-source/public fixed pair required'; END IF;
    IF item_supply_internal.public_native_source_current(jsonb_build_object('request',pair_fact.request_json,'ref',header.payload_json->'ref')) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='525 actual pair current source denied'; END IF;
   END LOOP;
   SELECT jsonb_agg(to_jsonb(field) ORDER BY ordinal) INTO expected_fields FROM unnest(ARRAY[
      'item_handle','content_hash','actual_public_task_hash','decision_signature','answer_leakage_signature']) WITH ORDINALITY AS fields(field,ordinal)
    WHERE bound_pair->0->field=bound_pair->1->field;
   IF expected_fields IS NULL OR finding->'equal_fields' IS DISTINCT FROM expected_fields
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(bound_pair) m WHERE m->>'version_id'=original->>'published_version_id')
     OR original->'specification'->'allocation'->>'slot' IS DISTINCT FROM 'assessment'
     OR original->>'slot' IS DISTINCT FROM (SELECT max(j.payload_json->>'slot') FROM tutor_item_supply_shared_persistent_pack_journal j
       WHERE j.public_task_id=(phase->>'public_task_id')::uuid AND j.record_kind='qualified'
       AND j.payload_json->'specification'->'allocation'->>'slot'='assessment'
       AND j.payload_json->>'published_version_id' IN(bound_pair->0->>'version_id',bound_pair->1->>'version_id'))
   THEN RAISE check_violation USING MESSAGE='525 original assessment clone and exact affected parent required'; END IF;
  ELSE
   peer_count:=peer_count+1;
  END IF;
 END LOOP;
 IF clone_count>1 OR clone_count+peer_count NOT BETWEEN 1 AND 144
  OR ((clone_count=1) IS DISTINCT FROM (req->'revision_allocation' IS DISTINCT FROM 'null'::jsonb))
  OR (original->>'published_version_id' IS NOT NULL AND clone_count<>1)
 THEN RAISE check_violation USING MESSAGE='525 published parent requires actual single clone finding'; END IF;
 -- All ordinary peer findings, scalar references, source grants, actual resources
 -- and UNKNOWN settlement remain independently enforced by original508 below.
 PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
 stamp:=clock_timestamp();
 IF COALESCE((p->>'deadline_at')::timestamptz>stamp,false) IS DISTINCT FROM true
  OR (p->>'deadline_at')::timestamptz>(phase->>'valid_until')::timestamptz
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'source_deadlines') s WHERE
     COALESCE((s->>'retained_until')::timestamptz>stamp,false) IS DISTINCT FROM true)
 THEN RAISE check_violation USING MESSAGE='525 acceptance clock/source/phase deadline expired'; END IF;
END $body530_normal$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_persistent_normal_repair(jsonb)');
 IF NOT FOUND OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef
  OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype
  OR actual.pronargs<>1 OR actual.proargnames IS DISTINCT FROM ARRAY['p']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='530 original normal receiver authority attributes changed'; END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR encode(sha256(convert_to(reviewed_body,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='530 original normal receiver source changed'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1
 THEN RAISE check_violation USING MESSAGE='530 original normal receiver framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,reviewed_body);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='530 original normal receiver attributes/owner/ACL changed'; END IF;
END $upgrade530_normal$;
