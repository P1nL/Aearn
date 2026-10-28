-- Normal local revision / incremental review, original-owner authority only.
-- This forward fragment preserves all installed <=587 definitions and history
-- unless an explicit compatible receiver extension below says otherwise.

CREATE TABLE IF NOT EXISTS tutor_item_supply_development_execution_batch_caps (
 batch_id uuid PRIMARY KEY REFERENCES tutor_item_supply_development_model_accounting_batches(id),
 authorization_key text NOT NULL CHECK (authorization_key='normal-item-quality-successor-batches-20261021'),
 resource_caps jsonb NOT NULL CHECK (jsonb_typeof(resource_caps)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_development_execution_batch_caps_insert()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_catalog AS $$
DECLARE
 b tutor_item_supply_development_model_accounting_batches%ROWTYPE;
 k text;
BEGIN
 SELECT * INTO b FROM tutor_item_supply_development_model_accounting_batches WHERE id=NEW.batch_id FOR SHARE;
 IF NOT FOUND OR b.authorization_key<>'development-unlimited-model-calls-20261010'
    OR b.mode<>'accounting_only' OR b.cumulative_caps_enforced
    OR NOT (b.started_at<=clock_timestamp() AND clock_timestamp()<b.valid_until)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_batches x
      WHERE x.id=NEW.batch_id AND x.xmin::text::bigint=(txid_current() % 4294967296))
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations r WHERE r.window_id=b.window_id)
    OR NEW.authorization_key<>'normal-item-quality-successor-batches-20261021' THEN
   RAISE EXCEPTION 'DEVELOPMENT_EXECUTION_FRESH_ORIGINAL_BATCH_REQUIRED';
 END IF;
 IF (SELECT count(*) FROM jsonb_object_keys(NEW.resource_caps))<>8 THEN
   RAISE EXCEPTION 'DEVELOPMENT_EXECUTION_EXACT_RESOURCE_KINDS_REQUIRED';
 END IF;
 FOREACH k IN ARRAY ARRAY['requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds'] LOOP
   IF NOT (NEW.resource_caps ? k) OR jsonb_typeof(NEW.resource_caps->k)<>'number'
      OR (NEW.resource_caps->>k)!~'^[0-9]+$' THEN
     RAISE EXCEPTION 'DEVELOPMENT_EXECUTION_NONNEGATIVE_INTEGER_CAP_REQUIRED';
   END IF;
 END LOOP;
 IF (NEW.resource_caps->>'execution_seconds')::numeric NOT BETWEEN 1 AND 31536000
    OR (NEW.resource_caps->>'fetches')::numeric<>0
    OR (NEW.resource_caps->>'requests')::numeric>1000000
    OR (NEW.resource_caps->>'input_tokens')::numeric>10000000000
    OR (NEW.resource_caps->>'output_tokens')::numeric>10000000000
    OR (NEW.resource_caps->>'candidates')::numeric>1000000
    OR (NEW.resource_caps->>'revision_rounds')::numeric>100000
    OR (NEW.resource_caps->>'investigation_rounds')::numeric>100000 THEN
   RAISE EXCEPTION 'DEVELOPMENT_EXECUTION_FINITE_NO_FETCH_CAP_REQUIRED';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_development_execution_batch_caps_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS enforce_development_execution_batch_caps_insert ON tutor_item_supply_development_execution_batch_caps;
CREATE TRIGGER enforce_development_execution_batch_caps_insert BEFORE INSERT ON tutor_item_supply_development_execution_batch_caps
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_development_execution_batch_caps_insert();
DROP TRIGGER IF EXISTS immutable_development_execution_batch_caps ON tutor_item_supply_development_execution_batch_caps;
CREATE TRIGGER immutable_development_execution_batch_caps BEFORE UPDATE OR DELETE ON tutor_item_supply_development_execution_batch_caps
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable();

-- Effective projections preserve the ORIGINAL reports, never six rebound copies.
CREATE OR REPLACE FUNCTION item_supply_internal.incremental_reports(b jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN b->>'schema_version'='item_supply_review_coverage_v1'
 THEN (SELECT jsonb_agg(e->'original'->'report' ORDER BY n)
       FROM jsonb_array_elements(b->'entries') WITH ORDINALITY q(e,n))
 ELSE b->'reports' END
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.incremental_blind_original(b jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE result jsonb:=b; depth integer:=0;
BEGIN
 WHILE result->>'schema_version' IN ('item_supply_blind_rescore_applicability_v1','item_supply_committed_blind_applicability_v1') LOOP
  depth:=depth+1; IF depth>2 THEN RAISE EXCEPTION '588 blind evidence nesting invalid'; END IF;
  result:=result->'original_blind';
 END LOOP;
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.incremental_binding(b jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN b->>'schema_version' IN ('item_supply_blind_rescore_applicability_v1','item_supply_committed_blind_applicability_v1')
  THEN b->'target_binding' ELSE b->'binding' END
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.incremental_blind_score(b jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN b->>'schema_version'='item_supply_committed_blind_applicability_v1'
  THEN b->'original_blind'->'score' ELSE b->'score' END
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.incremental_changed_paths(a jsonb,b jsonb,p text DEFAULT '')
RETURNS text[] LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE k text; i integer; result text[]:='{}';
BEGIN
 IF jsonb_typeof(a)='object' AND jsonb_typeof(b)='object'
  AND (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(a) key)
    IS NOT DISTINCT FROM (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(b) key) THEN
  FOR k IN SELECT key FROM jsonb_object_keys(a) key ORDER BY key LOOP
   result:=result||item_supply_internal.incremental_changed_paths(a->k,b->k,p||'/'||replace(replace(k,'~','~0'),'/','~1'));
  END LOOP;
 ELSIF jsonb_typeof(a)='array' AND jsonb_typeof(b)='array' AND jsonb_array_length(a)=jsonb_array_length(b) THEN
  FOR i IN 0..jsonb_array_length(a)-1 LOOP
   result:=result||item_supply_internal.incremental_changed_paths(a->i,b->i,p||'/'||i::text);
  END LOOP;
 ELSIF a IS NOT DISTINCT FROM b
   AND (jsonb_typeof(a) IS DISTINCT FROM 'number'
     OR ((a::text ~ '[.eE]') IS NOT DISTINCT FROM (b::text ~ '[.eE]'))) THEN
  RETURN result;
 ELSE result:=ARRAY[p]; END IF;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.incremental_primary_dependency(s jsonb,role text)
RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE src jsonb:=s->'source'; spec jsonb:=s->'finite_spec'; descriptor jsonb:=s->'scoring_descriptor';
 spec_hash text:=s->>'specification_hash'; test jsonb; cell jsonb; options jsonb;
 i integer; r integer; c integer; marker jsonb:='{"finite_private_expected_value":true}';
BEGIN
 src:=(src#-'{public,version}')#-'{private,version}';
 IF spec IS NOT NULL AND spec<>'null'::jsonb THEN
  spec_hash:=item_supply_internal.snapshot_hash(spec#-'{public_template,version}');
 END IF;
 IF descriptor IS NOT NULL AND descriptor<>'null'::jsonb THEN
  descriptor:=descriptor-ARRAY['source_hash','content_hash','binding_hash','validation_receipt_hash','actual_public_task_hash','public_template_hash'];
  IF spec IS NOT NULL AND spec<>'null'::jsonb THEN
   IF descriptor->>'specification_hash'=s->>'specification_hash' THEN
    descriptor:=jsonb_set(descriptor,'{specification_hash}',to_jsonb(spec_hash));
   END IF;
   descriptor:=descriptor-'server_specification_template_hash';
  END IF;
 END IF;
 IF spec IS NOT NULL AND spec<>'null'::jsonb AND spec->>'target_id'='python-kc-binding-v1'
  AND src#>>'{public,content,type}'='knowledge_check' AND src#>>'{private,content,type}'='knowledge_check'
  AND role NOT IN ('technical','security') THEN
  src:=jsonb_set(src,'{private,content,answer_explanation_markdown}','{"native_kc_explanation":true}'::jsonb);
 END IF;
 IF role NOT IN ('technical','ambiguity','adversarial') THEN
  IF src#>>'{public,content,type}'='sql_v2' AND src#>>'{private,content,type}'='sql_v2' THEN
   FOR i IN 0..jsonb_array_length(src#>'{private,content,tests}')-1 LOOP
    test:=src#>ARRAY['private','content','tests',i::text];
    FOR r IN 0..jsonb_array_length(test#>'{expected_output,rows}')-1 LOOP
     FOR c IN 0..jsonb_array_length(test#>ARRAY['expected_output','rows',r::text])-1 LOOP
      cell:=test#>ARRAY['expected_output','rows',r::text,c::text];
      IF jsonb_typeof(cell)='number' OR (jsonb_typeof(cell)='string' AND EXISTS(
       SELECT 1 FROM jsonb_array_elements(test#>'{dataset,tables}') t,
        LATERAL jsonb_array_elements(t->'rows') rr,LATERAL jsonb_array_elements(rr) v WHERE v=cell)) THEN
       src:=jsonb_set(src,ARRAY['private','content','tests',i::text,'expected_output','rows',r::text,c::text],
         jsonb_build_object('finite_private_expected_value',true,'scalar_type',
          CASE WHEN jsonb_typeof(cell)='string' THEN 'str' WHEN cell::text ~ '[.eE]' THEN 'float' ELSE 'int' END));
      END IF;
     END LOOP;
    END LOOP;
   END LOOP;
  ELSIF src#>>'{public,content,type}'='knowledge_check' AND src#>>'{private,content,type}'='knowledge_check'
   AND src#>>'{public,content,response_kind}'='single_choice' THEN
   SELECT jsonb_agg(o->'option_id') INTO options FROM jsonb_array_elements(src#>'{public,content,options}') o;
   IF jsonb_array_length(src#>'{private,content,accepted_answers}')=1
    AND options @> (src#>'{private,content,accepted_answers}') THEN
    src:=jsonb_set(src,'{private,content,accepted_answers,0}',marker);
   END IF;
   FOR i IN 0..jsonb_array_length(src#>'{private,content,tests}')-1 LOOP
    test:=src#>ARRAY['private','content','tests',i::text];
    IF item_supply_internal.snapshot_keys(test->'input_json',ARRAY['answer']) IS TRUE
     AND item_supply_internal.snapshot_keys(test->'expected_output_json',ARRAY['accepted']) IS TRUE
     AND options @> jsonb_build_array(test#>'{input_json,answer}')
     AND jsonb_typeof(test#>'{expected_output_json,accepted}')='boolean' THEN
     src:=jsonb_set(src,ARRAY['private','content','tests',i::text,'expected_output_json','accepted'],marker);
    END IF;
   END LOOP;
  END IF;
 END IF;
 RETURN item_supply_internal.snapshot_hash(jsonb_build_object('rule_version','finite-primary-dependencies-v1',
  'role',role,'source',src,'specification_hash',spec_hash,'scoring_descriptor',descriptor,
  'policy_hash',s->'binding'->>'policy_hash','runtime_key',s->'binding'->>'runtime_key','risk_tier',s->'binding'->>'risk_tier'));
END $$;

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_incremental_role_events (
 id uuid PRIMARY KEY,
 review_reservation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_reservations(id),
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id),
 job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id),
 role text NOT NULL CHECK(role IN ('curriculum','difficulty','technical','ambiguity','security','adversarial','blind','blind_score','ambiguity_probe')),
 input_hash text NOT NULL CHECK(input_hash ~ '^[0-9a-f]{64}$'),
 event_kind text NOT NULL CHECK(event_kind IN ('scope_prepared','started','committed')),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(review_reservation_id,role,event_kind),
 CHECK(true)
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_incremental_coverages (
 id uuid PRIMARY KEY,
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id),
 parent_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id),
 review_reservation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_reservations(id),
 job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id),
 payload_json jsonb NOT NULL,
 coverage_hash text NOT NULL CHECK(coverage_hash ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(generation_artifact_id,review_reservation_id), UNIQUE(coverage_hash)
);

-- Original 530 PUBLIC source/claim predicates, shared subject without a PRIVATE plan mapping.
CREATE OR REPLACE FUNCTION item_supply_internal.incremental_shared_source_deadline(request jsonb) RETURNS timestamptz
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE q jsonb:=jsonb_build_object('request',request,'ref',NULL); p jsonb; material jsonb; e jsonb; b jsonb; claim jsonb; t timestamptz; r record;
 v record; proof record; prepared jsonb; claim_receipt jsonb; declared jsonb; computed_claim text;
 catalog constant jsonb:=$public530${"python-state-update-v1":{"profile_id":"python-state-source-v1","target_definition_hash":"185544231076d15cb9c50539e57bb1bf115ff748d68c35d0ae04d6e4346e3891","execution_scope":{"runtime_profile":"python-stdout-v1","input_hash":"a5fa214c0d4f22ab2d410008f0a8cd2a0dc1c72803a2fac82104efe9040c4690","semantics_hash":"dd49e089be93b846714fb21ca4bd1782a4b825349cbe6872b2415d83cdcfccd2"},"applicability":"Registered finite Python integer state curriculum: current RHS, ordered update, derived refresh, saved swap and conserved transfer; pinned runtime only.","course_goal_hash":"8807ca3ec1d3781318a6dac53faf0c72306b5bbefbe9fca58ceca50bd2658a45"},"python-kc-binding-v1":{"profile_id":"python-binding-source-v1","target_definition_hash":"ac716c31c68c112c9b73ecc68b90c0ccb7e29f1694a77e23038375c4d4795abd","execution_scope":{"runtime_profile":"python-stdout-v1","input_hash":"c403b921fd12ac9415d7ce64feacba5e081d0f41ad6b16301ecc8db5dbc57e3a","semantics_hash":"bc2e4b0118ea3c008d18be0cdd89fb8c6c16fea79632e1df64bac626fdf7ddfe"},"applicability":"Registered Python integer binding curriculum: RHS time, saved versus rebound names and non-live derived values; source semantic oracle, not a KC execution score.","course_goal_hash":"0556ea372de2883f7b68d6d4a8f0faeff44f368065c3debb964fd3e8b05c5b56"},"sqlite-predicate-order-v1":{"profile_id":"sqlite-predicate-source-v1","target_definition_hash":"333d8108ac641f79580e5c36df2a41fe9cc1271853d536c4d735f97b535b7b54","execution_scope":{"runtime_profile":"sqlite-query-v1","input_hash":"b1a49f9b5eecec2633fa26627bb94864a5b8bfc016f1086e09619b344fca97ed","semantics_hash":"b18eb774bca700bb53926345de0adec515d468ededfc6c7fc3c9232622139e85"},"applicability":"Registered finite SQLite predicate/order curriculum: AND, NULL fallback, exclusive flags, strict cursor, multiset and full order; pinned runtime only.","course_goal_hash":"7f496a72d293b3a54a2d9b43197b635736a9c8f337196af0778ab332da123c23"}}$public530$;
 deadline timestamptz := 'infinity'::timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' OR item_supply_internal.snapshot_keys(q,ARRAY['request','ref']) IS DISTINCT FROM true
  OR q->'request'->>'schema_version' IS DISTINCT FROM 'item_generation_request_v2' THEN RETURN NULL; END IF;
 -- Shared subject has no private plan mapping; all original source/claim checks below remain.
 p:=jsonb_build_object('materials',q->'request'->'materials');
 IF p IS NULL OR jsonb_typeof(p->'materials') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'materials') NOT BETWEEN 1 AND 12 THEN RETURN NULL; END IF;
 FOR material IN SELECT value FROM jsonb_array_elements(p->'materials') LOOP
   declared:=catalog->(material->'binding'->>'target_id');
   IF declared IS NULL THEN RETURN NULL; END IF;
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
     OR jsonb_array_length(material->'binding'->'evidence') NOT BETWEEN 1 AND 12 THEN RETURN NULL; END IF;
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
     THEN RETURN NULL; END IF;
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
     IF NOT FOUND THEN RETURN NULL; END IF;
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
     IF NOT FOUND THEN RETURN NULL; END IF;
     IF r.assessment_evidence_id IS NOT NULL AND EXISTS(SELECT 1 FROM rag_assessment_source_evidence se WHERE se.id=r.assessment_evidence_id AND se.private_user_id IS NOT NULL AND (se.private_user_id::text IS DISTINCT FROM q->'ref'->>'user_id' OR se.private_epoch::text IS DISTINCT FROM q->'ref'->>'epoch' OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_user_epochs ue WHERE ue.user_id=se.private_user_id AND ue.epoch=se.private_epoch AND ue.enabled))) THEN RETURN NULL; END IF;
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
       OR (r.assessment_evidence_id IS NOT NULL AND (r.evidence_expires IS NULL OR r.evidence_expires<=t OR r.evidence_revoked IS NOT NULL)) THEN RETURN NULL; END IF;
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
       OR proof.id IS DISTINCT FROM r.assessment_evidence_id THEN RETURN NULL; END IF;
     prepared:=proof.signed_proof->'payload'->'prepared';
     computed_claim:=item_supply_internal.snapshot_hash(jsonb_build_object('profile',proof.profile_id,
       'spans',prepared->'spans','execution_scope',proof.execution_scope_json,'document_hash',proof.document_hash));
     IF proof.profile_id='sqlite-predicate-source-v1' THEN
       computed_claim:=item_supply_internal.snapshot_hash(jsonb_build_object('primary_claim_hash',computed_claim,
         'companions',prepared->'companions'));
     END IF;
     IF proof.claim_hash IS DISTINCT FROM computed_claim OR proof.profile_id IS DISTINCT FROM declared->>'profile_id'
       OR proof.execution_scope_json IS DISTINCT FROM declared->'execution_scope'
       OR proof.applicability IS DISTINCT FROM declared->>'applicability' THEN RETURN NULL; END IF;
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
     THEN RETURN NULL; END IF;
     claim_receipt:=jsonb_build_object('receipt_id',proof.claim_handle,'demand_hash',prepared->'demand'->>'demand_hash',
       'purpose','assessment_evidence','admission_receipt_id',b->>'admission_receipt_id',
       'claim_hash',proof.claim_hash,'scope',prepared->'demand'->'scope',
       'source_handle',proof.source_handle,'document_handle',proof.document_handle,
       'document_revision',proof.document_hash,'document_hash',proof.document_hash,'applicability',proof.applicability,
       'method','isolated_execution','primary_lineage_family',NULL,'independent_lineage_family',NULL,
       'independent_source_handle',NULL,'independent_document_handle',NULL,'independent_document_revision',NULL,
       'independent_document_hash',NULL,'independent_lineage_verified',false,'execution_receipt_id',proof.execution_handle,
       'execution_scope',proof.execution_scope_json,'verified',true,'revoked',false);
     IF item_supply_internal.snapshot_hash(claim_receipt) IS DISTINCT FROM e->>'claim_receipt_hash' THEN RETURN NULL; END IF;
     FOR claim IN SELECT value FROM jsonb_array_elements(material->'exact_claims') WHERE value->>'claim_receipt_id'=proof.claim_handle LOOP
       IF claim->'binding' IS DISTINCT FROM b OR claim->'scope' IS DISTINCT FROM b->'scope'
         OR claim->>'claim_hash' IS DISTINCT FROM proof.claim_hash OR claim->>'applicability' IS DISTINCT FROM proof.applicability
         OR claim->'execution_scope' IS DISTINCT FROM proof.execution_scope_json THEN RETURN NULL; END IF;
     END LOOP;
     deadline:=LEAST(deadline,proof.expires_at);
     PERFORM 1 FROM grounding_active_corpora active WHERE active.subject_id=v.subject_id
       AND active.corpus_version_id=v.id AND active.generation=(e->>'active_generation')::integer FOR SHARE;
     IF NOT FOUND THEN RETURN NULL; END IF;
   END LOOP;

 END LOOP;
 RETURN CASE WHEN clock_timestamp()<deadline THEN deadline ELSE NULL END;
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.incremental_shared_source_current(request jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE deadline timestamptz;
BEGIN
 deadline:=item_supply_internal.incremental_shared_source_deadline(request);
 RETURN COALESCE(deadline>clock_timestamp(),false);
END $$;


CREATE OR REPLACE FUNCTION item_supply_internal.assert_incremental_shared_current(lease jsonb,artifact uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a tutor_item_supply_shared_generation_artifacts%ROWTYPE; c record; snapshot jsonb; t timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' OR current_setting('session_replication_role')<>'origin' THEN
  RAISE EXCEPTION '588 original owner read committed sandbox required'; END IF;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=artifact FOR SHARE;
 SELECT co.*,j.root_id INTO c FROM tutor_item_supply_shared_job_controls co
  JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id WHERE co.job_id=(lease->>'job_id')::uuid FOR UPDATE OF co;
 IF NOT FOUND OR a.id IS NULL THEN RAISE EXCEPTION '588 original artifact/control required'; END IF;
 snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 t:=clock_timestamp();
 IF c.root_id IS DISTINCT FROM a.root_id OR c.state IS DISTINCT FROM 'leased'
  OR c.lease_owner IS DISTINCT FROM lease->>'lease_owner' OR c.lease_generation::text IS DISTINCT FROM lease->>'generation'
  OR c.state_version::text IS DISTINCT FROM lease->>'state_version' OR lease->'profile' IS DISTINCT FROM snapshot
  OR c.lease_expires_at IS NULL OR c.lease_expires_at<=t OR c.parent_deadline<=t
  OR lease->>'visibility' IS DISTINCT FROM 'public' OR lease->'owner_id' IS DISTINCT FROM 'null'::jsonb
  OR lease->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
  OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
  OR item_supply_internal.controlled_counterexample_held(c.job_id) IS DISTINCT FROM false
  OR NOT (a.job_id=c.job_id OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations b
    WHERE b.job_id=c.job_id AND b.generation_artifact_id=a.id AND b.root_id=a.root_id))
  OR item_supply_internal.incremental_shared_source_current(a.request_json) IS DISTINCT FROM true THEN
  RAISE EXCEPTION '588 current original source root lease adoption required'; END IF;
END $$;

ALTER TABLE tutor_item_supply_shared_incremental_role_events ADD COLUMN IF NOT EXISTS logical_action_hash text NOT NULL
 CHECK(logical_action_hash ~ '^[0-9a-f]{64}$');
CREATE UNIQUE INDEX IF NOT EXISTS shared_incremental_logical_action_event
 ON tutor_item_supply_shared_incremental_role_events(logical_action_hash,event_kind) WHERE event_kind IN ('started','committed');

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_incremental_role_event()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a tutor_item_supply_shared_generation_artifacts%ROWTYPE; r tutor_item_supply_shared_reservations%ROWTYPE;
 start_row tutor_item_supply_shared_incremental_role_events%ROWTYPE; scope_row tutor_item_supply_shared_incremental_role_events%ROWTYPE;
 p jsonb:=NEW.payload_json; report jsonb; run jsonb; bound jsonb; expected_round integer;
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',NEW.generation_artifact_id);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id FOR SHARE;
 SELECT * INTO r FROM tutor_item_supply_shared_reservations WHERE id=NEW.review_reservation_id FOR SHARE;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id
    AND cp.stage='validating' AND cp.status='completed')
  AND item_supply_internal.shared_continuation_validation_inherited(NEW.job_id) IS DISTINCT FROM true THEN
  RAISE EXCEPTION '588 role action requires actual validation or original current applicability'; END IF;
 bound:=p->'binding';
 WITH RECURSIVE ancestry AS (
  SELECT parent_artifact_id AS id FROM tutor_item_supply_shared_revision_lineage WHERE child_artifact_id=a.id
  UNION SELECT l.parent_artifact_id FROM tutor_item_supply_shared_revision_lineage l JOIN ancestry h ON l.child_artifact_id=h.id
 ) SELECT COALESCE(max((rr.payload_json->>'bundle_version')::integer),0)+1 INTO expected_round
 FROM tutor_item_supply_shared_pipeline_receipts rr JOIN ancestry h ON h.id=rr.generation_artifact_id WHERE rr.artifact_kind='review_bundle';
 IF r.id IS NULL OR r.job_id IS DISTINCT FROM NEW.job_id OR r.root_id IS DISTINCT FROM a.root_id
  OR r.lease_generation::text IS DISTINCT FROM p->'lease'->>'generation'
  OR NEW.job_id::text IS DISTINCT FROM p->'lease'->>'job_id'
  OR r.reservation_key IS DISTINCT FROM 'review.'||replace(a.id::text,'-','')
  OR bound->>'candidate_key' IS DISTINCT FROM a.item_id::text OR bound->>'version_key' IS DISTINCT FROM a.version_id::text
  OR bound->>'source_hash' IS DISTINCT FROM a.source_hash OR bound->>'content_hash' IS DISTINCT FROM a.content_hash
  OR bound->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(a)
  OR bound->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
  OR p->'logical_action'->>'artifact_id' IS DISTINCT FROM a.id::text
  OR p->'logical_action'->>'source_hash' IS DISTINCT FROM a.source_hash
  OR p->'logical_action'->>'policy_hash' IS DISTINCT FROM bound->>'policy_hash'
  OR p->'logical_action'->>'role' IS DISTINCT FROM NEW.role
  OR p->'logical_action'->>'review_round' IS DISTINCT FROM expected_round::text
  OR item_supply_internal.snapshot_hash(p->'logical_action') IS DISTINCT FROM NEW.logical_action_hash THEN
  RAISE EXCEPTION '588 original logical action reservation binding required'; END IF;
 SELECT * INTO scope_row FROM tutor_item_supply_shared_incremental_role_events
  WHERE review_reservation_id=NEW.review_reservation_id AND role=NEW.role AND event_kind='scope_prepared' FOR SHARE;
 SELECT * INTO start_row FROM tutor_item_supply_shared_incremental_role_events
  WHERE generation_artifact_id=a.id AND role=NEW.role AND event_kind='started' FOR SHARE;
 IF NEW.event_kind='scope_prepared' THEN
  IF start_row.id IS NOT NULL OR p->'subject'->'source' IS DISTINCT FROM a.source_json
   OR p->'subject'->'binding' IS DISTINCT FROM bound
   OR p->'scope'->>'schema_version' IS DISTINCT FROM 'item_supply_role_review_scope_v1'
   OR p->'scope'->>'scope_id' IS DISTINCT FROM NEW.id::text OR p->'scope'->>'role' IS DISTINCT FROM NEW.role
   OR p->'scope'->>'request_input_hash' IS DISTINCT FROM NEW.input_hash
   OR p->'scope'->>'subject_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'subject')
   OR p->'scope'->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(p->'subject',NEW.role)
   OR p->'scope'->'cross_role_observed_hard_findings_required' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION '588 prospective exact original review scope required'; END IF;
 ELSIF NEW.event_kind='started' THEN
  IF start_row.id IS NOT NULL OR p->>'input_hash' IS DISTINCT FROM NEW.input_hash
   OR (NEW.role IN ('curriculum','difficulty','technical','ambiguity','security','adversarial') AND (
    scope_row.id IS NULL OR scope_row.input_hash IS DISTINCT FROM NEW.input_hash
    OR scope_row.payload_json->'binding' IS DISTINCT FROM bound OR EXISTS(
     SELECT 1 FROM tutor_item_supply_shared_incremental_role_events e WHERE e.id=scope_row.id
      AND e.xmin::text::bigint=txid_current()%4294967296))) THEN
   RAISE EXCEPTION '588 committed prospective scope before dispatch required'; END IF;
 ELSE
  report:=COALESCE(p->'report',p->'result'); run:=report->'run';
  IF start_row.id IS NULL OR start_row.id::text IS DISTINCT FROM p->>'started_event_id'
   OR start_row.review_reservation_id IS DISTINCT FROM NEW.review_reservation_id
   OR start_row.job_id IS DISTINCT FROM NEW.job_id OR start_row.input_hash IS DISTINCT FROM NEW.input_hash
   OR start_row.logical_action_hash IS DISTINCT FROM NEW.logical_action_hash
   OR start_row.payload_json->'binding' IS DISTINCT FROM bound
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events e WHERE e.id=start_row.id
      AND e.xmin::text::bigint=txid_current()%4294967296)
   OR item_supply_internal.snapshot_hash(report) IS DISTINCT FROM COALESCE(p->>'report_hash',p->>'result_hash')
   OR (NEW.role IN ('curriculum','difficulty','technical','ambiguity','security','adversarial') AND (
    report->>'role' IS DISTINCT FROM NEW.role OR report->'binding' IS DISTINCT FROM bound
    OR run->>'input_hash' IS DISTINCT FROM NEW.input_hash
    OR run->'provider_identity' IS DISTINCT FROM start_row.payload_json->'provider_identity'
    OR run->>'profile_hash' IS DISTINCT FROM bound->>'profile_hash'
    OR run->>'run_id' IS NULL OR run->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb)) THEN
   RAISE EXCEPTION '588 committed result must bind prior TOP original dispatch'; END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS enforce_shared_incremental_role_event ON tutor_item_supply_shared_incremental_role_events;
CREATE TRIGGER enforce_shared_incremental_role_event BEFORE INSERT ON tutor_item_supply_shared_incremental_role_events
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_incremental_role_event();
DROP TRIGGER IF EXISTS immutable_shared_incremental_role_event ON tutor_item_supply_shared_incremental_role_events;
CREATE TRIGGER immutable_shared_incremental_role_event BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_incremental_role_events
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
DROP TRIGGER IF EXISTS immutable_shared_incremental_coverage ON tutor_item_supply_shared_incremental_coverages;
CREATE TRIGGER immutable_shared_incremental_coverage BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_incremental_coverages
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

CREATE OR REPLACE FUNCTION item_supply_internal.incremental_material_failure(r jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT r->>'verdict' IS DISTINCT FROM 'approved' OR EXISTS(SELECT 1 FROM jsonb_array_elements(r->'findings') f
  WHERE f->'blocking'='true'::jsonb OR f->>'severity' IN ('major','critical')
   OR f->>'safe_code' IN ('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit'))
$$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_incremental_direct_revision(p jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_incremental_local_diff(parent jsonb,child jsonb,allowed jsonb)
RETURNS void LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE path text; paths text[];
BEGIN
 paths:=item_supply_internal.incremental_changed_paths(parent,child);
 IF item_supply_internal.revision_substantive_hash(parent)=item_supply_internal.revision_substantive_hash(child)
  OR parent->'blueprint' IS DISTINCT FROM child->'blueprint'
  OR parent->'public'->>'item_key' IS DISTINCT FROM child->'public'->>'item_key'
  OR parent->'public'->>'version'=child->'public'->>'version' THEN
  RAISE EXCEPTION '588 same logical item substantive child required'; END IF;
 FOREACH path IN ARRAY paths LOOP
  IF path IN ('/public/version','/private/version') THEN CONTINUE; END IF;
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(allowed) a WHERE path=a OR starts_with(path,a||'/')) THEN
   RAISE EXCEPTION '588 author diff outside original instruction'; END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_incremental_coverage(p jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE b jsonb:=p->'coverage'; parent tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 child tutor_item_supply_shared_generation_artifacts%ROWTYPE; lineage tutor_item_supply_shared_revision_lineage%ROWTYPE;
 prep tutor_item_supply_shared_revision_preparations%ROWTYPE; old tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 entry jsonb; report jsonb; original jsonb; subject jsonb; scope jsonb; previous jsonb; paths text[];
 role_name text; roles text[]; runs text[]:='{}'; identities text[]:='{}'; run jsonb; i integer:=0;
BEGIN
 IF b->'impact'->>'rule_version'='committed-same-child-v1' THEN
  PERFORM item_supply_internal.assert_shared_committed_same_child_coverage(p); RETURN;
 END IF;
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',(p->>'artifact_id')::uuid);
 SELECT * INTO child FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO parent FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'parent_artifact_id')::uuid FOR SHARE;
 SELECT * INTO lineage FROM tutor_item_supply_shared_revision_lineage WHERE parent_artifact_id=parent.id AND child_artifact_id=child.id FOR SHARE;
 SELECT * INTO prep FROM tutor_item_supply_shared_revision_preparations WHERE id=lineage.preparation_id FOR SHARE;
 SELECT * INTO old FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(prep.payload_json->>'review_receipt_id')::uuid FOR SHARE;
 IF old.id IS NULL AND prep.investigation_receipt_id IS NOT NULL THEN
  SELECT r.* INTO old FROM tutor_item_supply_shared_pipeline_receipts r
   JOIN tutor_item_supply_shared_review_investigation_receipts inv ON inv.id=prep.investigation_receipt_id
   WHERE r.id=(inv.payload_json->>'review_receipt_id')::uuid FOR SHARE OF r;
 END IF;
 IF parent.id IS NULL OR lineage.id IS NULL OR prep.id IS NULL OR old.id IS NULL
  OR parent.root_id IS DISTINCT FROM child.root_id OR old.generation_artifact_id IS DISTINCT FROM parent.id
  OR old.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(old.payload_json)
  OR b->>'schema_version' IS DISTINCT FROM 'item_supply_review_coverage_v1'
  OR item_supply_internal.snapshot_hash(b) IS DISTINCT FROM p->>'coverage_hash'
  OR b->'binding'->>'source_hash' IS DISTINCT FROM child.source_hash
  OR b->'binding'->>'content_hash' IS DISTINCT FROM child.content_hash
  OR b->'binding'->>'candidate_key' IS DISTINCT FROM child.item_id::text
  OR b->'binding'->>'version_key' IS DISTINCT FROM child.version_id::text
  OR b->'binding'->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
  OR b->'binding'->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(child)
  OR b->'binding'->>'policy_hash' IS DISTINCT FROM old.payload_json->'binding'->>'policy_hash'
  OR jsonb_array_length(b->'entries') IS DISTINCT FROM 6
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations r WHERE r.id=(p->>'reservation_id')::uuid
    AND r.job_id=(p->'lease'->>'job_id')::uuid AND r.root_id=child.root_id
    AND r.reservation_key='review.'||replace(child.id::text,'-','')) THEN
  RAISE EXCEPTION '588 original incremental lineage coverage binding required'; END IF;
 PERFORM item_supply_internal.assert_incremental_local_diff(parent.source_json,child.source_json,b->'impact'->'allowed_paths');
 IF b->'impact'->'changed_paths' IS DISTINCT FROM to_jsonb(ARRAY(SELECT path FROM unnest(item_supply_internal.incremental_changed_paths(parent.source_json,child.source_json))
    WITH ORDINALITY changed(path,n) WHERE path NOT IN ('/public/version','/private/version') ORDER BY n))
  OR b->'impact'->>'rule_version' IS DISTINCT FROM 'finite-impact-v2'
  OR b->'impact'->'machine_validation_required' IS DISTINCT FROM 'true'::jsonb
  OR b->'impact'->'coverage_rebuild_required' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION '588 coverage requires actual host diff and current machine evidence'; END IF;
 IF b->'impact'->'allowed_paths' IS DISTINCT FROM COALESCE(prep.payload_json->'instruction'->'allowed_paths',prep.payload_json->'context'->'local_revision_paths') THEN
  RAISE EXCEPTION '588 exact owner-issued local patch scope required'; END IF;
 SELECT array_agg(e->>'role' ORDER BY n) INTO roles FROM jsonb_array_elements(b->'entries') WITH ORDINALITY q(e,n);
 IF roles IS DISTINCT FROM ARRAY['curriculum','difficulty','technical','ambiguity','security','adversarial']::text[] THEN
  RAISE EXCEPTION '588 six distinct effective roles required'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(b->'entries') LOOP
  role_name:=entry->>'role'; original:=entry->'original'; report:=original->'report'; subject:=original->'subject'; scope:=original->'scope';
  SELECT value INTO previous FROM jsonb_array_elements(item_supply_internal.incremental_reports(old.payload_json)) WHERE value->>'role'=role_name;
  IF previous IS NULL OR b->'impact'->'original_report_hashes'->>i IS DISTINCT FROM item_supply_internal.snapshot_hash(previous)
   OR report->>'role' IS DISTINCT FROM role_name OR report->'binding' IS DISTINCT FROM subject->'binding' THEN
   RAISE EXCEPTION '588 exact prior role report identity required'; END IF;
  IF entry->>'mode'='fresh' THEN
   IF NOT (b->'impact'->'required_roles' @> jsonb_build_array(role_name))
    OR subject->'source' IS DISTINCT FROM child.source_json OR report->'binding' IS DISTINCT FROM b->'binding'
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events e
      WHERE e.generation_artifact_id=child.id AND e.role=role_name AND e.event_kind='committed'
       AND e.payload_json->'report'=report AND e.xmin::text::bigint<>txid_current()%4294967296) THEN
    RAISE EXCEPTION '588 fresh role requires prior TOP original provider report'; END IF;
  ELSIF entry->>'mode'='original_applicable' THEN
   IF report IS DISTINCT FROM previous OR item_supply_internal.incremental_material_failure(report)
    OR b->'impact'->'required_roles' @> jsonb_build_array(role_name)
    OR NOT (b->'impact'->'reusable_roles' @> jsonb_build_array(role_name))
    OR scope IS NULL OR scope='null'::jsonb
    OR scope->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(subject,role_name)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events e
      JOIN tutor_item_supply_shared_generation_artifacts a ON a.id=e.generation_artifact_id
      JOIN tutor_item_supply_shared_incremental_role_events done ON done.generation_artifact_id=e.generation_artifact_id
        AND done.role=e.role AND done.event_kind='committed'
      WHERE e.event_kind='scope_prepared' AND e.role=role_name AND e.payload_json->'scope'=scope
       AND e.payload_json->'subject'=subject AND a.source_json=subject->'source' AND done.payload_json->'report'=report)
    OR scope->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(
       (SELECT e.payload_json->'subject' FROM tutor_item_supply_shared_incremental_role_events e
         WHERE e.generation_artifact_id=child.id AND e.event_kind='scope_prepared' LIMIT 1),role_name) THEN
    RAISE EXCEPTION '588 original report applicability not authenticated'; END IF;
  ELSIF entry->>'mode'='committed_same_action' THEN
   IF NOT (b->'impact'->'required_roles' @> jsonb_build_array(role_name))
    OR subject->'source' IS DISTINCT FROM child.source_json
    OR ((report->'binding')-'profile_hash') IS DISTINCT FROM ((b->'binding')-'profile_hash')
    OR entry->'committed_action'->'original' IS DISTINCT FROM original
    OR entry->'committed_action'->'target_binding' IS DISTINCT FROM b->'binding'
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events e
      WHERE e.generation_artifact_id=child.id AND e.role=role_name AND e.event_kind='committed'
       AND e.logical_action_hash=entry->'committed_action'->>'logical_action_hash'
       AND e.payload_json->'report'=report AND e.payload_json->'subject'=subject
       AND e.payload_json->'lease'->'profile'->>'profile_key_hash'=p->'lease'->'profile'->>'profile_key_hash'
       AND e.xmin::text::bigint<>txid_current()%4294967296) THEN
    RAISE EXCEPTION '588 original committed logical role action and same recipe required'; END IF;
  ELSE RAISE EXCEPTION '588 unsupported effective report mode'; END IF;
  run:=report->'run';
  IF run->>'run_id'=ANY(runs) OR run->'provider_identity'->>'identity'=ANY(identities)
   OR run->'provider_identity'->>'identity'=b->>'author_identity' THEN
   RAISE EXCEPTION '588 original independent providers required'; END IF;
  runs:=array_append(runs,run->>'run_id'); identities:=array_append(identities,run->'provider_identity'->>'identity');
  i:=i+1;
 END LOOP;
 PERFORM item_supply_internal.assert_shared_blind_applicability(b->'blind_solve',child.id);
 run:=item_supply_internal.incremental_blind_original(b->'blind_solve')->'run';
 IF run->>'run_id'=ANY(runs) OR run->'provider_identity'->>'identity'=ANY(identities)
  OR run->'provider_identity'->>'identity'=b->>'author_identity'
 THEN
  RAISE EXCEPTION '588 distinct original committed blind evidence required'; END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_incremental_coverage()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.id::text IS DISTINCT FROM NEW.payload_json->'coverage'->>'bundle_id'
  OR NEW.generation_artifact_id::text IS DISTINCT FROM NEW.payload_json->>'artifact_id'
  OR NEW.parent_artifact_id::text IS DISTINCT FROM NEW.payload_json->>'parent_artifact_id'
  OR NEW.review_reservation_id::text IS DISTINCT FROM NEW.payload_json->>'reservation_id'
  OR NEW.job_id::text IS DISTINCT FROM NEW.payload_json->'lease'->>'job_id'
  OR NEW.coverage_hash IS DISTINCT FROM NEW.payload_json->>'coverage_hash' THEN
  RAISE EXCEPTION '588 immutable coverage columns must match actual payload'; END IF;
 PERFORM item_supply_internal.assert_shared_incremental_coverage(NEW.payload_json);
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS shared_incremental_coverage_insert ON tutor_item_supply_shared_incremental_coverages;
CREATE TRIGGER shared_incremental_coverage_insert BEFORE INSERT ON tutor_item_supply_shared_incremental_coverages
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_incremental_coverage();
CREATE OR REPLACE FUNCTION item_supply_internal.persist_shared_incremental_coverage(p jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE id uuid:=(p->'coverage'->>'bundle_id')::uuid;
BEGIN
 INSERT INTO tutor_item_supply_shared_incremental_coverages(id,generation_artifact_id,parent_artifact_id,review_reservation_id,job_id,payload_json,coverage_hash)
 VALUES(id,(p->>'artifact_id')::uuid,(p->>'parent_artifact_id')::uuid,(p->>'reservation_id')::uuid,(p->'lease'->>'job_id')::uuid,p,p->>'coverage_hash');
 RETURN id;
END $$;

ALTER TABLE tutor_item_supply_shared_revision_preparations ALTER COLUMN investigation_receipt_id DROP NOT NULL;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc
 WHERE oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()')),'missing') NOT IN ('62b65bb789737a33b41308a2fae2bc9137f6f3a820b03e8cf743dcfb98f53386','d83121fda9f8fd80690187269e414185c1bbce6f4bfb616d8b7c16e2feba118a') THEN
 RAISE EXCEPTION '588 original revision receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_native_revision_insert()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
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
  direct_permission boolean:=false; local_permission boolean:=false;
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
  direct_permission:=p->>'schema_version'='native_shared_revision_preparation_v2';
  local_permission:=p->'context'->>'schema_version'='native_revision_author_context_v5';
  IF direct_permission THEN PERFORM item_supply_internal.assert_incremental_direct_revision(p); END IF;
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
  IF (NOT direct_permission AND (investigation_row.id IS NULL OR investigation_prep.id IS NULL)) OR parent_artifact.id IS NULL
    OR parent_control.id IS NULL OR child_control.id IS NULL OR child_job.id IS NULL
    OR child_job.root_id IS DISTINCT FROM NEW.root_id OR parent_artifact.root_id IS DISTINCT FROM NEW.root_id
    OR (NOT direct_permission AND (investigation_row.root_id IS DISTINCT FROM NEW.root_id OR investigation_row.generation_artifact_id IS DISTINCT FROM NEW.parent_artifact_id))
    OR (NOT direct_permission AND ((NOT fresh_permission AND investigation_row.job_id IS DISTINCT FROM parent_control.job_id)))
    OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text OR p->>'parent_artifact_id' IS DISTINCT FROM NEW.parent_artifact_id::text
    OR p->'child_lease'->>'job_id' IS DISTINCT FROM NEW.child_job_id::text
    OR jsonb_typeof(context_payload) IS DISTINCT FROM 'object' OR jsonb_typeof(request_payload) IS DISTINCT FROM 'object'
    OR jsonb_typeof(context_payload->'problems') IS DISTINCT FROM 'array'
    OR jsonb_typeof(snapshot->'values') IS DISTINCT FROM 'object'
    OR (NOT direct_permission AND ((NOT source_permission AND p->'source_deadlines' IS DISTINCT FROM investigation_prep.payload_json->'source_deadlines')))
    OR child_job.parent_job_id IS DISTINCT FROM parent_control.job_id OR child_job.id=parent_control.job_id
    OR (NOT direct_permission AND (investigation_row.snapshot_hash IS DISTINCT FROM p->>'investigation_receipt_hash'))
    OR (NOT direct_permission AND (investigation_row.payload_json->>'safe_reason' IS DISTINCT FROM 'investigation_analysis_pending_revision_owner'))
    OR (NOT direct_permission AND (jsonb_typeof(investigation_row.payload_json->'report') IS DISTINCT FROM 'object'))
    OR (NOT direct_permission AND ((NOT fresh_permission AND (investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp))))
    OR (NOT direct_permission AND (EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts ir WHERE ir.id=investigation_row.id AND ir.xmin::text::bigint=(txid_current()%4294967296))))
    OR (NOT direct_permission AND (NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=investigation_row.settlement_id
      AND ss.reservation_id=investigation_row.reservation_id AND ss.settlement_key=investigation_prep.payload_json->>'reservation_key'
      AND ss.usage_state='unknown' AND ss.xmin::text::bigint<>(txid_current()%4294967296))))
    OR parent_control.state IS DISTINCT FROM 'leased' OR child_control.state IS DISTINCT FROM 'leased'
    OR parent_control.lease_expires_at IS NULL OR child_control.lease_expires_at IS NULL
    OR parent_control.lease_expires_at<=stamp OR child_control.lease_expires_at<=stamp
    OR parent_control.parent_deadline<=stamp OR child_control.parent_deadline<=stamp
    OR child_control.parent_deadline>parent_control.parent_deadline
    OR parent_control.lease_owner IS DISTINCT FROM p->'parent_lease'->>'lease_owner'
    OR parent_control.lease_generation::text IS DISTINCT FROM p->'parent_lease'->>'generation'
    OR parent_control.state_version::text IS DISTINCT FROM p->'parent_lease'->>'state_version'
    OR (NOT direct_permission AND ((NOT fresh_permission AND p->'parent_lease' IS DISTINCT FROM investigation_prep.payload_json->'lease')))
    OR snapshot IS DISTINCT FROM p->'child_lease'->'profile' OR request_payload->'profile' IS DISTINCT FROM snapshot
    OR snapshot->>'profile_hash' IS DISTINCT FROM p->'parent_lease'->'profile'->>'profile_hash'
    OR snapshot->'values' IS DISTINCT FROM p->'parent_lease'->'profile'->'values'
    OR (snapshot->'values'->>'discussion_rounds')::integer<2 OR (snapshot->'values'->>'revision_rounds')::integer<1
    OR p->'child_lease'->>'visibility' IS DISTINCT FROM 'public'
    OR p->'child_lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'child_lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR (p->>'deadline_at')::timestamptz<=stamp OR (p->>'deadline_at')::timestamptz>LEAST(
      CASE WHEN fresh_permission OR direct_permission THEN parent_control.lease_expires_at ELSE investigation_row.valid_until END,
      CASE WHEN fresh_permission OR direct_permission THEN parent_control.lease_expires_at ELSE investigation_prep.valid_until END,parent_control.lease_expires_at,child_control.lease_expires_at,child_control.parent_deadline,
      (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'))
    OR (NOT (persistent_permission OR m03_permission OR direct_permission OR local_permission) AND (EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=parent_artifact.id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.generation_artifact_id=parent_artifact.id AND rr.artifact_kind='admission_evaluation')
    OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe WHERE pe.version_id=parent_artifact.version_id))) THEN
    RAISE check_violation USING MESSAGE='revision current original investigation/child/source/history required';
  END IF;
  IF context_payload->>'schema_version' IS DISTINCT FROM (CASE WHEN direct_permission THEN 'native_revision_author_context_v4' WHEN local_permission THEN 'native_revision_author_context_v5'
      WHEN family_permission AND source_permission THEN 'native_revision_author_context_v3'
      WHEN family_permission THEN 'native_revision_author_context_v2' ELSE 'native_revision_author_context_v1' END)
    OR context_payload->>'purpose' IS DISTINCT FROM 'bounded_content_revision_not_admission'
    OR context_payload->'parent_source' IS DISTINCT FROM parent_artifact.source_json
    OR context_payload->>'parent_artifact_hash' IS DISTINCT FROM parent_artifact.artifact_hash
    OR p->>'parent_artifact_hash' IS DISTINCT FROM parent_artifact.artifact_hash
    OR p->>'parent_substantive_hash' IS DISTINCT FROM item_supply_internal.revision_substantive_hash(parent_artifact.source_json)
    OR context_payload->>'parent_artifact_id' IS DISTINCT FROM parent_artifact.id::text
    OR context_payload->>'parent_source_hash' IS DISTINCT FROM parent_artifact.source_hash
    OR context_payload->>'parent_content_hash' IS DISTINCT FROM parent_artifact.content_hash
    OR (NOT direct_permission AND (context_payload->>'parent_review_hash' IS DISTINCT FROM investigation_row.payload_json->>'review_receipt_hash'))
    OR (NOT direct_permission AND (context_payload->>'investigation_receipt_id' IS DISTINCT FROM investigation_row.id::text))
    OR (NOT direct_permission AND (context_payload->>'investigation_receipt_hash' IS DISTINCT FROM investigation_row.snapshot_hash))
    OR (NOT direct_permission AND (context_payload->>'investigation_report_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(investigation_row.payload_json->'report')))
    OR (NOT direct_permission AND (context_payload->>'policy_hash' IS DISTINCT FROM investigation_prep.payload_json->'request_payload'->'review_input'->'binding'->>'policy_hash'))
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
    OR (NOT (direct_permission OR local_permission) AND request_payload->>'item_key'=parent_artifact.source_json->'public'->>'item_key')
    OR ((direct_permission OR local_permission) AND request_payload->>'item_key' IS DISTINCT FROM parent_artifact.source_json->'public'->>'item_key')
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
    OR (NOT direct_permission AND (jsonb_array_length(context_payload->'problems') IS DISTINCT FROM jsonb_array_length(investigation_row.payload_json->'report'->'output'->'analyses'))) THEN
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
      OR (NOT (direct_permission OR local_permission) AND child_artifact.item_id=parent_artifact.item_id)
      OR ((direct_permission OR local_permission) AND child_artifact.item_id IS DISTINCT FROM parent_artifact.item_id) OR child_artifact.version_id=parent_artifact.version_id
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
    IF direct_permission OR local_permission THEN
      PERFORM item_supply_internal.assert_incremental_local_diff(parent_artifact.source_json,child_artifact.source_json,
        CASE WHEN direct_permission THEN p->'instruction'->'allowed_paths' ELSE context_payload->'local_revision_paths' END);
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
    IF (p->>'deadline_at')::timestamptz<=stamp OR (NOT direct_permission AND ((NOT fresh_permission AND (investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp))))
      OR parent_control.lease_expires_at<=stamp OR parent_control.parent_deadline<=stamp
      OR child_control.lease_expires_at<=stamp OR child_control.parent_deadline<=stamp
    THEN RAISE check_violation USING MESSAGE='525 final acceptance deadline expired'; END IF;
  END IF;
  RETURN NEW;
END $function$;

ALTER TABLE tutor_item_supply_shared_revision_preparations
 DROP CONSTRAINT IF EXISTS tutor_item_supply_shared_revision_preparations_payload_json_check;
ALTER TABLE tutor_item_supply_shared_revision_preparations
 ADD CONSTRAINT tutor_item_supply_shared_revision_preparations_payload_json_check CHECK(
 jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152 AND (
 (payload_json->>'schema_version'='native_shared_revision_preparation_v1' AND investigation_receipt_id IS NOT NULL)
 OR (payload_json->>'schema_version'='native_shared_revision_preparation_v2' AND investigation_receipt_id IS NULL
  AND payload_json->>'basis_kind'='direct_review' AND payload_json->>'review_receipt_id' IS NOT NULL)));

CREATE OR REPLACE FUNCTION item_supply_internal.require_shared_incremental_coverage(b jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE saved tutor_item_supply_shared_incremental_coverages%ROWTYPE;
BEGIN
 SELECT * INTO saved FROM tutor_item_supply_shared_incremental_coverages
  WHERE coverage_hash=item_supply_internal.snapshot_hash(b) AND payload_json->'coverage'=b FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION '588 original coverage receipt required'; END IF;
 PERFORM item_supply_internal.assert_shared_incremental_coverage(saved.payload_json);
END $$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('public.enforce_item_supply_shared_pipeline_artifact()')),'missing') NOT IN ('062595c5137f2d272d240331bfd0ae529c167141beca5609cc40b0c7f3c34272','8505199a0151b2f105e90b2da4d79f94b001d2de56d4b36685fb0dc4d552bb47') THEN RAISE EXCEPTION '588 original receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_pipeline_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body588$
DECLARE control record; facts public.tutor_item_supply_shared_generation_artifacts%ROWTYPE; root_facts record; reservation record;
  committed_evaluation boolean:=false; quality_profile text;
  scope jsonb; snapshot jsonb; material jsonb; source_receipt jsonb; expected_content text; expected_schema text; i integer;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared pipeline outside B1d';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.job_id FOR UPDATE;
  IF NOT FOUND OR control.state<>'leased' OR control.lease_generation<>NEW.lease_generation
    OR control.state_version<>NEW.lease_state_version OR control.lease_owner IS DISTINCT FROM NEW.lease_owner
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp()
    OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale shared pipeline lease';
  END IF;
  snapshot:=CASE WHEN control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN control.profile_snapshot_json->'profile' ELSE control.profile_snapshot_json END;
  quality_profile:=snapshot->>'profile_hash';
  IF TG_TABLE_NAME='tutor_item_supply_shared_pipeline_receipts' THEN
    committed_evaluation:=item_supply_internal.committed_child_evaluation_matches(to_jsonb(NEW))
      OR item_supply_internal.shared_adjudicated_evaluation_matches(to_jsonb(NEW));
    IF committed_evaluation THEN quality_profile:=item_supply_internal.incremental_binding(NEW.payload_json)->>'profile_hash'; END IF;
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_generation_artifacts' THEN
    SELECT b.snapshot_json,o.obligation_json,o.provider_key,r.canonical_key INTO root_facts
      FROM tutor_item_supply_shared_budget_roots r
      JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id
      JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id
      WHERE r.id=NEW.root_id AND b.id=NEW.blueprint_id FOR SHARE OF r,b,o;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline root unavailable'; END IF;
    scope:=root_facts.snapshot_json->'scope';
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id;
    IF NOT FOUND OR reservation.root_id<>NEW.root_id OR reservation.job_id<>NEW.job_id
      OR reservation.lease_generation<>NEW.lease_generation
      OR reservation.reservation_key IS DISTINCT FROM 'gen.' || replace(NEW.candidate_id::text,'-','')
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements
        WHERE reservation_id=NEW.reservation_id AND settlement_key='generation.' || replace(NEW.candidate_id::text,'-','')) THEN
      RAISE check_violation USING MESSAGE='shared pipeline reservation mismatch';
    END IF;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',NEW.source_json->'public'->>'item_key','version',NEW.source_json->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(NEW.source_json->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(NEW.source_json->'public'),
      'private_hash',item_supply_internal.snapshot_hash(NEW.source_json->'private')));
    IF scope->>'visibility' IS DISTINCT FROM 'public' OR scope->>'owner_ref' IS NOT NULL
      OR NEW.request_json->>'demand_binding' IS NOT NULL
      OR NEW.request_json->'profile' IS DISTINCT FROM snapshot
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(scope)
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM root_facts.obligation_json->>'scope_hash'
      OR item_supply_internal.snapshot_hash(root_facts.obligation_json) IS DISTINCT FROM root_facts.canonical_key
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'scope_hash' IS DISTINCT FROM NEW.request_json->>'scope_hash'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.source_json)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->'blueprint' IS DISTINCT FROM NEW.source_json->'blueprint'
      OR NEW.source_json->'public'->>'item_key' IS DISTINCT FROM NEW.request_json->>'item_key'
      OR NEW.source_json->'public'->>'version' IS DISTINCT FROM NEW.request_json->>'version'
      OR NEW.item_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('item',NEW.request_json->>'item_key')
      OR NEW.version_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('version',NEW.request_json->>'item_key' || '@' || (NEW.request_json->>'version'))
      OR item_supply_internal.shared_public_template_matches(NEW.request_json,NEW.source_json->'public',NEW.target_id) IS DISTINCT FROM true
      OR NEW.source_json->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope->>'knowledge_key'
      OR NEW.source_json->'blueprint'->>'language_id' IS DISTINCT FROM scope->>'language_id'
      OR NEW.source_json->'blueprint'->>'item_kind' IS DISTINCT FROM scope->>'item_kind'
      OR NEW.source_json->'blueprint'->>'purpose' IS DISTINCT FROM scope->>'purpose'
      OR NEW.source_json->'blueprint'->'required_capabilities' IS DISTINCT FROM scope->'required_capabilities'
      OR NOT (NEW.source_json->'blueprint'->'allowed_interactions' @> jsonb_build_array(scope->>'interaction'))
      OR scope->>'assessment_contract_version' IS DISTINCT FROM NEW.target_id
      OR scope->>'runtime_profile_id' IS DISTINCT FROM (CASE NEW.target_id
        WHEN 'python-state-update-v1' THEN 'python-stdout-v1' WHEN 'sqlite-predicate-order-v1' THEN 'sqlite-query-v1' ELSE 'static-exact-v1' END)
      OR NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
      OR NEW.receipt_json->'provider'->>'provider' IS DISTINCT FROM root_facts.provider_key
      OR NEW.receipt_json->'provider'->>'model' IS DISTINCT FROM NEW.receipt_json->'provider'->>'configured_model'
      OR NEW.receipt_json->'provider'->>'provider_version' IS DISTINCT FROM 'openai_compatible.v2'
      OR NEW.receipt_json->'provider'->>'prompt_version' IS DISTINCT FROM 'item_author.public_material.v2'
      OR jsonb_typeof(NEW.request_json->'materials') IS DISTINCT FROM 'array'
      OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array' THEN
      RAISE check_violation USING MESSAGE='shared pipeline generation identity mismatch';
    END IF;
    IF jsonb_array_length(NEW.request_json->'materials') NOT BETWEEN 1 AND 12
      OR jsonb_array_length(NEW.receipt_json->'sources')<>jsonb_array_length(NEW.request_json->'materials') THEN
      RAISE check_violation USING MESSAGE='shared pipeline source count mismatch';
    END IF;
    FOR i IN 0..jsonb_array_length(NEW.request_json->'materials')-1 LOOP
      material:=NEW.request_json->'materials'->i;
      source_receipt:=NEW.receipt_json->'sources'->i;
      IF material->'binding'->>'contract_version' IS DISTINCT FROM 'rag_public_course_binding_v1'
        OR material->'binding'->>'target_id' IS DISTINCT FROM NEW.target_id
        OR material->'binding'->>'target_definition_hash' IS DISTINCT FROM NEW.target_definition_hash
        OR material->'binding' ? 'draft' OR material->'binding' ? 'user_id'
        OR material->'access_request'->>'actor_id' IS DISTINCT FROM 'service.rag-public-course'
        OR source_receipt->>'mode' IS DISTINCT FROM 'current_authority'
        OR source_receipt->>'binding_digest' IS DISTINCT FROM material->'binding'->>'binding_digest'
        OR source_receipt->>'corpus_version_id' IS DISTINCT FROM material->'binding'->'evidence'->0->>'corpus_version_id'
        OR source_receipt->>'active_generation' IS DISTINCT FROM material->'binding'->'evidence'->0->>'active_generation'
        OR source_receipt->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
          'binding',material->'binding','access_request',material->'access_request','exact_claims',material->'exact_claims',
          'excerpt_hash',encode(digest(convert_to(material->>'excerpt','UTF8'),'sha256'),'hex'))) THEN
        RAISE check_violation USING MESSAGE='shared pipeline native source mismatch';
      END IF;
    END LOOP;
  ELSE
    SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id AND (committed_evaluation OR item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,NEW.generation_artifact_id,NEW.continuation_binding_hash));
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline generation unavailable'; END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN CASE WHEN item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_review_bundle_v3' ELSE 'item_supply_review_bundle_v2' END
      WHEN 'admission_evaluation' THEN CASE WHEN item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_admission_evaluation_v3' ELSE 'item_supply_admission_evaluation_v2' END END;
    IF NEW.artifact_kind='review_bundle' AND NEW.schema_version='item_supply_review_coverage_v1' THEN
      PERFORM item_supply_internal.require_shared_incremental_coverage(NEW.payload_json);
      expected_schema:='item_supply_review_coverage_v1';
    END IF;
    IF NEW.artifact_kind='blind_solve' AND NEW.schema_version IN ('item_supply_blind_rescore_applicability_v1','item_supply_committed_blind_applicability_v1') THEN
      PERFORM item_supply_internal.assert_shared_blind_applicability(NEW.payload_json,facts.id);
      expected_schema:=NEW.schema_version;
    END IF;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',item_supply_internal.incremental_binding(NEW.payload_json)->>'content_hash') IS DISTINCT FROM facts.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',item_supply_internal.incremental_binding(NEW.payload_json)->>'source_hash') IS DISTINCT FROM facts.source_hash
      OR (NEW.artifact_kind<>'validation' AND (
        item_supply_internal.incremental_binding(NEW.payload_json)->>'candidate_key' IS DISTINCT FROM facts.item_id::text
        OR item_supply_internal.incremental_binding(NEW.payload_json)->>'version_key' IS DISTINCT FROM facts.version_id::text
        OR item_supply_internal.incremental_binding(NEW.payload_json)->>'profile_hash' IS DISTINCT FROM quality_profile
        OR item_supply_internal.incremental_binding(NEW.payload_json)->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='shared pipeline receipt identity mismatch';
    END IF;
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_generation_artifacts' THEN
    PERFORM item_supply_internal.shared_generation_policy_hash(NEW::tutor_item_supply_shared_generation_artifacts);
  END IF;
  RETURN NEW;
END $body588$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.shared_evaluation_policy_matches(tutor_item_supply_shared_generation_artifacts,jsonb,jsonb)')),'missing') NOT IN ('db27337eb3d43b2510c27b6857e16adc7772d7745fe41826fc1705dd3290f58b','d570dc813ce26c3ce92d250a83b5fe1c25fa2fcf41f5d8fc5eea6aa13f509e1c') THEN RAISE EXCEPTION '588 original receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.shared_evaluation_policy_matches(g tutor_item_supply_shared_generation_artifacts, evaluation jsonb, review jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body588$
DECLARE policy text; expected_warnings jsonb;
BEGIN
 policy:=item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts);
 IF review->>'schema_version'='item_supply_review_coverage_v1' THEN
  PERFORM item_supply_internal.require_shared_incremental_coverage(review);
  IF evaluation->'binding' IS DISTINCT FROM review->'binding'
   OR review->'binding'->>'policy_hash' IS DISTINCT FROM policy
   OR evaluation->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR jsonb_typeof(item_supply_internal.incremental_blind_score(review->'blind_solve')->'passed') IS DISTINCT FROM 'boolean'
   OR (evaluation->>'disposition'='eligible_internal' AND EXISTS(
    SELECT 1 FROM jsonb_array_elements(item_supply_internal.incremental_reports(review)) r
      WHERE item_supply_internal.incremental_material_failure(r))) THEN RETURN false; END IF;
  IF policy='7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab' THEN
   RETURN evaluation->>'schema_version'='item_supply_admission_evaluation_v2'
    AND evaluation->>'policy_version'='autonomous_evidence_policy_v2'
    AND item_supply_internal.incremental_blind_score(review->'blind_solve')->'passed'='true'::jsonb AND NOT (evaluation ? 'diagnostic_warnings');
  END IF;
  RETURN policy='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
   AND evaluation->>'schema_version'='item_supply_admission_evaluation_v3'
   AND evaluation->>'policy_version'='autonomous_evidence_policy_v3'
   AND evaluation->'diagnostic_warnings'=CASE WHEN item_supply_internal.incremental_blind_score(review->'blind_solve')->'passed'='false'::jsonb
     THEN '["blind_solution_incorrect"]'::jsonb ELSE '[]'::jsonb END;
 END IF;

 IF jsonb_typeof(evaluation) IS DISTINCT FROM 'object' OR jsonb_typeof(review) IS DISTINCT FROM 'object'
   OR evaluation->'binding' IS DISTINCT FROM review->'binding'
   OR review->'blind_solve'->'binding' IS DISTINCT FROM review->'binding'
   OR review->'binding'->>'policy_hash' IS DISTINCT FROM policy
   OR review->'blind_solve'->>'state' IS DISTINCT FROM 'completed'
   OR review->'blind_solve'->>'mode' IS DISTINCT FROM 'public_only'
   OR jsonb_typeof(review->'blind_solve'->'score'->'passed') IS DISTINCT FROM 'boolean'
   OR review->>'state' IS DISTINCT FROM 'completed' OR review->>'mode' IS DISTINCT FROM 'peer_blind'
   OR review->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR evaluation->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN RETURN false; END IF;
 IF policy='7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab' THEN
   RETURN evaluation->>'schema_version'='item_supply_admission_evaluation_v2'
     AND evaluation->>'policy_version'='autonomous_evidence_policy_v2'
     AND review->>'schema_version'='item_supply_review_bundle_v2'
     AND review->>'policy_version'='autonomous_evidence_policy_v2'
     AND NOT (evaluation ? 'diagnostic_warnings');
 END IF;
 expected_warnings:=CASE WHEN review->'blind_solve'->'score'->'passed'='false'::jsonb
   THEN '["blind_solution_incorrect"]'::jsonb ELSE '[]'::jsonb END;
 RETURN (evaluation->>'schema_version'='item_supply_admission_evaluation_v3'
   AND evaluation->>'policy_version'='autonomous_evidence_policy_v3'
   AND review->>'schema_version'='item_supply_review_bundle_v3'
   AND review->>'policy_version'='autonomous_evidence_policy_v3'
   AND evaluation->'diagnostic_warnings'=expected_warnings) IS TRUE;
END $body588$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.revision_recheck_disputes(jsonb)')),'missing') NOT IN ('8bac9820a8693161607706d2ca307597e341cef5e273b35e7aecf8e81fe0c62e','a1b6573bf8e0aac56d0cab7ce0e48061bf74cea5809d172c3bb44af18112e421') THEN RAISE EXCEPTION '588 original receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.revision_recheck_disputes(bundle jsonb)
 RETURNS jsonb
 LANGUAGE sql
 IMMUTABLE STRICT
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $body588$
 WITH reports AS (
   SELECT report,report_order FROM jsonb_array_elements(item_supply_internal.incremental_reports(bundle)) WITH ORDINALITY AS rr(report,report_order)
 ), material AS (
   SELECT rr.report,rr.report_order,ff.finding,ff.finding_order-1 AS finding_index
   FROM reports rr CROSS JOIN LATERAL jsonb_array_elements(rr.report->'findings') WITH ORDINALITY AS ff(finding,finding_order)
   WHERE ff.finding->'blocking'='true'::jsonb OR ff.finding->>'severity' IN ('major','critical')
     OR ff.finding->>'safe_code' IN ('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit')
 ), disputes AS (
   SELECT mm.report,mm.report_order,mm.finding_index,item_supply_internal.snapshot_hash(mm.finding) AS finding_hash,
     mm.finding->>'safe_code' AS safe_code,CASE WHEN mm.report->>'schema_version'='item_supply_evidenced_review_report_v1'
       THEN mm.finding->'references' ELSE '[]'::jsonb END AS field_refs FROM material mm
   UNION ALL SELECT rr.report,rr.report_order,NULL::bigint,NULL::text,'report_requires_evidence','[]'::jsonb
     FROM reports rr WHERE rr.report->>'verdict'<>'approved' AND NOT EXISTS(SELECT 1 FROM material mm WHERE mm.report_order=rr.report_order)
 ) SELECT COALESCE(jsonb_agg(jsonb_build_object(
   'dispute_key',item_supply_internal.snapshot_hash(CASE WHEN dd.finding_index IS NULL
     THEN jsonb_build_array(item_supply_internal.snapshot_hash(bundle),item_supply_internal.snapshot_hash(dd.report))
     ELSE jsonb_build_array(item_supply_internal.snapshot_hash(bundle),item_supply_internal.snapshot_hash(dd.report),dd.finding_index,dd.finding_hash) END),
   'role',dd.report->>'role','report_hash',item_supply_internal.snapshot_hash(dd.report),'run_id',dd.report->'run'->>'run_id',
   'finding_index',dd.finding_index,'finding_hash',dd.finding_hash,'safe_code',dd.safe_code,'references',dd.field_refs)
   ORDER BY dd.report_order,dd.finding_index),'[]'::jsonb) FROM disputes dd
$body588$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_revision_recheck_insert()')),'missing') NOT IN ('52ad3eb3b44382b8cd30171a76fd5a94987664cf3708d90bd5122f332a2b74c3','96665ff2a10063cf5604e4cd0441ccbcaa83db45b8cb29672374c27fe181925a') THEN RAISE EXCEPTION '588 original receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_revision_recheck_insert()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $body588$
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
     WHERE ff.generation_artifact_id=artifact.id OR (NOT committed AND revision_prep.payload_json->'context'->>'schema_version' NOT IN ('native_revision_author_context_v4','native_revision_author_context_v5') AND ff.generation_artifact_id=lineage.parent_artifact_id
       AND (NOT m03_permission OR ff.id IS DISTINCT FROM (m03_grant->>'facts_receipt_id')::uuid)))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr
     WHERE (rr.generation_artifact_id=artifact.id OR (NOT committed AND revision_prep.payload_json->'context'->>'schema_version' NOT IN ('native_revision_author_context_v4','native_revision_author_context_v5') AND rr.generation_artifact_id=lineage.parent_artifact_id)) AND rr.artifact_kind='admission_evaluation')
   OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe
     JOIN tutor_item_supply_shared_generation_artifacts aa ON aa.version_id=pe.version_id
     WHERE aa.id=artifact.id OR (NOT committed AND aa.id=lineage.parent_artifact_id)) THEN
   RAISE check_violation USING MESSAGE='recheck exact current lineage/source/profile operation required';
 END IF;
 IF revision_prep.payload_json->>'schema_version'='native_shared_revision_preparation_v2' THEN
   IF p->'original_disputes' IS DISTINCT FROM (SELECT item_supply_internal.revision_recheck_disputes(rr.payload_json)
      FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=(revision_prep.payload_json->>'review_receipt_id')::uuid) THEN
    RAISE EXCEPTION '588 exact original direct-review disputes required'; END IF;
  ELSIF p->'original_disputes' IS DISTINCT FROM (SELECT ir.payload_json->'disputes'
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
   SELECT item_supply_internal.incremental_blind_original(bb.payload_json->'blind_solve')->'run'->>'run_id' AS run_id FROM bundles bb
   UNION SELECT pp->'run'->>'run_id' FROM bundles bb CROSS JOIN LATERAL jsonb_array_elements(item_supply_internal.incremental_reports(bb.payload_json)) pp
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
     OR (validation_row.job_id IS DISTINCT FROM NEW.job_id AND item_supply_internal.shared_validation_inherited_receipt_matches(NEW.job_id,artifact.id,validation_row.id) IS DISTINCT FROM true)
     OR blind_row.job_id IS DISTINCT FROM NEW.job_id OR review_row.job_id IS DISTINCT FROM NEW.job_id
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
     OR (validation_row.lease_generation IS DISTINCT FROM control_row.lease_generation AND item_supply_internal.shared_validation_inherited_receipt_matches(NEW.job_id,artifact.id,validation_row.id) IS DISTINCT FROM true)
     OR blind_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR review_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR (validation_row.lease_owner IS DISTINCT FROM control_row.lease_owner AND item_supply_internal.shared_validation_inherited_receipt_matches(NEW.job_id,artifact.id,validation_row.id) IS DISTINCT FROM true)
     OR blind_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR review_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR receipt->>'validation_receipt_id' IS DISTINCT FROM NEW.validation_receipt_id::text
     OR receipt->>'blind_receipt_id' IS DISTINCT FROM NEW.blind_receipt_id::text OR receipt->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
     OR receipt->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR receipt->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
     OR receipt->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
     OR jsonb_array_length(receipt->'entries') IS DISTINCT FROM jsonb_array_length(p->'original_disputes') THEN
     RAISE check_violation USING MESSAGE='recheck original committed new validation/blind/six receipts required';
   END IF;
   IF review_row.payload_json->>'schema_version'='item_supply_review_coverage_v1' THEN
     PERFORM item_supply_internal.require_shared_incremental_coverage(review_row.payload_json);
    END IF;
    SELECT array_agg(rr->>'role' ORDER BY rr->>'role') INTO roles FROM jsonb_array_elements(item_supply_internal.incremental_reports(review_row.payload_json)) rr;
   IF roles IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[] THEN
     RAISE check_violation USING MESSAGE='recheck all six peer-blind roles required';
   END IF;
   FOR provider_run IN SELECT blind_row.payload_json->'run' WHERE blind_row.payload_json->>'schema_version'='item_supply_blind_receipt_v2'
      UNION ALL SELECT rr->'run' FROM jsonb_array_elements(item_supply_internal.incremental_reports(review_row.payload_json)) rr
       WHERE review_row.payload_json->>'schema_version'<>'item_supply_review_coverage_v1'
        OR EXISTS(SELECT 1 FROM jsonb_array_elements(review_row.payload_json->'entries') e WHERE e->>'mode'='fresh' AND e->'original'->'report'=rr) LOOP
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
   IF reservation_row.id IS NULL OR reservation_row.root_id IS DISTINCT FROM NEW.root_id OR reservation_row.requests<>(CASE WHEN review_row.payload_json->>'schema_version'='item_supply_review_coverage_v1' THEN jsonb_array_length(review_row.payload_json->'impact'->'required_roles')+1 ELSE 7 END)
     OR reservation_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
       WHERE ra.reservation_namespace='shared' AND ra.reservation_id=reservation_row.id
         AND ra.resource_kind='output_tokens' AND ra.reserved_amount=reservation_row.requests*61440)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
       WHERE ra.reservation_namespace='shared' AND ra.reservation_id=reservation_row.id
         AND ra.resource_kind='output_tokens' AND ra.reserved_amount<>430080)
     OR usage_row.id IS NULL OR usage_row.usage_state IS DISTINCT FROM 'unknown'
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=usage_row.id AND ss.xmin::text::bigint=(txid_current()%4294967296)) THEN
     RAISE check_violation USING MESSAGE='recheck committed independent UNKNOWN review allocation required';
   END IF;
   IF item_supply_internal.shared_validation_inherited_receipt_matches(NEW.job_id,artifact.id,validation_row.id) THEN
    SELECT vp.* INTO validation_prep FROM tutor_item_supply_shared_validation_preparations vp
     JOIN tutor_item_supply_shared_validation_applicabilities app ON vp.id=(app.payload_json->>'preparation_id')::uuid
     WHERE app.job_id=NEW.job_id AND app.generation_artifact_id=artifact.id AND app.original_receipt_id=validation_row.id;
   ELSE
    SELECT * INTO validation_prep FROM tutor_item_supply_shared_validation_preparations vv
     WHERE vv.job_id=NEW.job_id AND vv.generation_artifact_id=artifact.id AND vv.lease_generation=control_row.lease_generation;
   END IF;
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
END $body588$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission(jsonb)')),'missing') NOT IN ('0c9da57c7aea17c5e7df7608391d76f47f20f701f7c8c5ca4a14eebd1077017d','7a2ef5a47cf905717220734131a3238b84940b44732aa456cb3267593d604bb4') THEN RAISE EXCEPTION '588 original receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_revision_readmission(p jsonb)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $body588$
DECLARE child tutor_item_supply_shared_generation_artifacts%ROWTYPE; parent tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE; rp tutor_item_supply_shared_revision_preparations%ROWTYPE;
 rr tutor_item_supply_shared_revision_recheck_receipts%ROWTYPE; prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE; vp tutor_item_supply_shared_validation_preparations%ROWTYPE;
 gp tutor_item_supply_shared_generation_policy_bindings%ROWTYPE;
 control_row record; stamp timestamptz; snapshot jsonb; f jsonb:=p->'facts_payload'; roles text[]; incremental_permission boolean:=false; m03_permission boolean:=false; m03_grant jsonb;
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
 incremental_permission:=peer.payload_json->>'schema_version'='item_supply_review_coverage_v1';
  IF incremental_permission THEN
   PERFORM item_supply_internal.require_shared_incremental_coverage(peer.payload_json);
   IF item_supply_internal.shared_evaluation_policy_matches(child,f->'evaluation',peer.payload_json) IS DISTINCT FROM true THEN
    RAISE EXCEPTION '588 incremental original policy/evaluation required'; END IF;
  END IF;
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
   OR peer.payload_json->>'schema_version' IS DISTINCT FROM (CASE WHEN incremental_permission THEN 'item_supply_review_coverage_v1' WHEN m03_permission THEN 'item_supply_review_bundle_v2' ELSE 'item_supply_review_bundle_v3' END)
   OR p->>'policy_hash' IS DISTINCT FROM (CASE WHEN incremental_permission THEN item_supply_internal.shared_generation_policy_hash(child) WHEN m03_permission THEN '7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab' ELSE '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' END)
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
 SELECT array_agg(role->>'role' ORDER BY role->>'role') INTO roles FROM jsonb_array_elements(item_supply_internal.incremental_reports(peer.payload_json)) role;
 IF roles IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(item_supply_internal.incremental_reports(peer.payload_json)) role
     WHERE (NOT incremental_permission OR EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'entries') e
       WHERE e->>'mode'='fresh' AND e->'original'->'report'=role)) AND (role->'binding' IS DISTINCT FROM p->'binding'
       OR role->'run'->>'run_id' IN (SELECT value#>>'{}' FROM jsonb_array_elements(prep.payload_json->'forbidden_run_ids'))))
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
   OR f->'evaluation'->>'schema_version' IS DISTINCT FROM (CASE WHEN m03_permission OR (incremental_permission AND gp.policy_hash='7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab') THEN 'item_supply_admission_evaluation_v2' ELSE 'item_supply_admission_evaluation_v3' END)
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
   OR gp.policy_hash IS DISTINCT FROM (CASE WHEN incremental_permission THEN item_supply_internal.shared_generation_policy_hash(child) WHEN m03_permission THEN '7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab' ELSE '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' END)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(rp.payload_json->'source_deadlines') source_bound
     WHERE (source_bound.value->>'retained_until')::timestamptz IS NULL
       OR (source_bound.value->>'retained_until')::timestamptz<=stamp) THEN
   RAISE check_violation USING MESSAGE='normal readmission final current bound/controlled/policy expired';
 END IF;
END $body588$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_committed_review_frame(p jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE frame jsonb:=p->'normal_committed_frame'; rr tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',(p->>'artifact_id')::uuid);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(frame->>'review_receipt_id')::uuid FOR SHARE;
 SELECT * INTO vr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(frame->>'validation_receipt_id')::uuid FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(frame->>'blind_receipt_id')::uuid FOR SHARE;
 IF frame->>'schema_version' IS DISTINCT FROM 'normal_committed_review_frame_v1'
  OR frame->'execution_lease' IS DISTINCT FROM p->'lease' OR rr.id IS NULL OR vr.id IS NULL OR br.id IS NULL
  OR rr.artifact_kind IS DISTINCT FROM 'review_bundle' OR vr.artifact_kind IS DISTINCT FROM 'validation' OR br.artifact_kind IS DISTINCT FROM 'blind_solve'
  OR rr.generation_artifact_id IS DISTINCT FROM a.id OR vr.generation_artifact_id IS DISTINCT FROM a.id OR br.generation_artifact_id IS DISTINCT FROM a.id
  OR (rr.job_id IS DISTINCT FROM vr.job_id AND item_supply_internal.shared_validation_inherited_receipt_matches((p->'lease'->>'job_id')::uuid,a.id,vr.id) IS DISTINCT FROM true)
  OR rr.job_id IS DISTINCT FROM br.job_id
  OR (rr.lease_generation IS DISTINCT FROM vr.lease_generation AND item_supply_internal.shared_validation_inherited_receipt_matches((p->'lease'->>'job_id')::uuid,a.id,vr.id) IS DISTINCT FROM true)
  OR rr.lease_generation IS DISTINCT FROM br.lease_generation
  OR rr.job_id::text IS DISTINCT FROM frame->>'original_job_id'
  OR rr.receipt_hash IS DISTINCT FROM frame->>'review_hash' OR vr.receipt_hash IS DISTINCT FROM frame->>'validation_hash'
  OR br.receipt_hash IS DISTINCT FROM frame->>'blind_hash' OR rr.payload_json->'blind_solve' IS DISTINCT FROM br.payload_json
  OR rr.id::text IS DISTINCT FROM p->>'review_receipt_id' OR rr.receipt_hash IS DISTINCT FROM p->>'review_receipt_hash'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.id IN(rr.id,vr.id,br.id)
      AND r.xmin::text::bigint=txid_current()%4294967296)
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations c
    WHERE c.job_id=(p->'lease'->>'job_id')::uuid AND c.generation_artifact_id=a.id
      AND c.binding_hash=frame->>'continuation_binding_hash' AND c.root_id=a.root_id) THEN
  RAISE EXCEPTION '588 immutable original quality DATA with fresh adopted control required'; END IF;
END $$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()')),'missing') NOT IN ('01d080fcdc204f3d9b42ebe1262038072f17c5e1a8c265aee5c46be3cd4ffa84','a54bcfa364c79497d9be7142f6115da65d276d8232f8aaeaa32c8524ac92883e') THEN RAISE EXCEPTION '588 original receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_review_investigation_insert()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $body588$
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
  quality_job uuid; quality_generation integer; quality_owner text; normal_permission boolean:=false; m03_permission boolean:=false;
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
  IF p ? 'normal_committed_frame' THEN
    PERFORM item_supply_internal.assert_normal_committed_review_frame(p);
    normal_permission:=true;
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
  IF (NOT (persistent_permission OR m03_permission OR normal_permission) AND (NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='validating' AND cp.status='completed')
    OR NOT (EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='generating' AND cp.status='completed')
      OR item_supply_internal.shared_continuation_generation_inherited(NEW.job_id))))
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id
      AND cp.stage IN ('investigating','revising','simulating','admitting') AND cp.status='completed') THEN
    RAISE check_violation USING MESSAGE='investigation original reviewing or investigating position required';
  END IF;
  SELECT * INTO artifact_row FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id FOR SHARE;
  SELECT * INTO review_row FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id FOR SHARE;
  quality_job:=CASE WHEN (persistent_permission OR m03_permission OR normal_permission) THEN review_row.job_id ELSE NEW.job_id END;
  quality_generation:=CASE WHEN (persistent_permission OR m03_permission OR normal_permission) THEN review_row.lease_generation ELSE NEW.lease_generation END;
  quality_owner:=CASE WHEN (persistent_permission OR m03_permission OR normal_permission) THEN review_row.lease_owner ELSE NEW.lease_owner END;
  IF artifact_row.id IS NULL OR review_row.id IS NULL OR artifact_row.root_id<>NEW.root_id
    OR review_row.job_id<>quality_job OR review_row.lease_generation<>quality_generation
    OR review_row.lease_owner IS DISTINCT FROM quality_owner OR review_row.artifact_kind<>'review_bundle'
    OR review_row.mode<>'live' OR review_row.generation_artifact_id<>artifact_row.id
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id AND rr.xmin::text::bigint=(txid_current()%4294967296))
    OR (NOT (m03_permission OR normal_permission) AND item_supply_internal.shared_stage_original_matches(quality_job,quality_generation,artifact_row.id,review_row.continuation_binding_hash) IS DISTINCT FROM true)
    OR (NOT (persistent_permission OR m03_permission OR normal_permission) AND p->>'continuation_binding_hash' IS DISTINCT FROM review_row.continuation_binding_hash)
    OR review_row.source_hash IS DISTINCT FROM artifact_row.source_hash OR review_row.content_hash IS DISTINCT FROM artifact_row.content_hash
    OR (NOT (persistent_permission OR m03_permission OR normal_permission) AND (EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=artifact_row.id)
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
    OR request_payload->>'schema_version' IS DISTINCT FROM (CASE WHEN normal_permission THEN 'native_shared_review_investigation_input_v2' WHEN persistent_permission THEN 'persistent_normal_investigation_input_v1' ELSE 'native_shared_review_investigation_input_v1' END)
    OR request_payload->>'purpose' IS DISTINCT FROM (CASE WHEN persistent_permission THEN 'same_item_substantive_repair' ELSE 'live_dispute_investigation' END)
    OR request_payload->>'authority' IS DISTINCT FROM 'original_shared_owner_required'
    OR request_payload->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
    OR request_payload->>'review_receipt_hash' IS DISTINCT FROM review_row.receipt_hash
    OR request_payload ?| ARRAY['bundle','blind_solve','score','answer','lease','budget']
    OR request_payload->'review_input'->'source' IS DISTINCT FROM artifact_row.source_json
    OR binding IS DISTINCT FROM review_row.payload_json->'binding'
    OR (CASE WHEN (persistent_permission OR m03_permission OR normal_permission) THEN request_payload->>'execution_profile_hash' ELSE binding->>'profile_hash' END) IS DISTINCT FROM snapshot->>'profile_hash'
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
    OR ((validation_row.job_id<>quality_job OR validation_row.lease_generation<>quality_generation)
      AND item_supply_internal.shared_validation_inherited_receipt_matches(NEW.job_id,artifact_row.id,validation_row.id) IS DISTINCT FROM true)
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
  IF normal_permission THEN PERFORM item_supply_internal.assert_normal_committed_review_frame(p); END IF;
  RETURN NEW;
END $body588$;

-- PRIVATE evidence is subordinate to the original 523/524 task, phase and bank.
-- This is not another aggregate review/admission authority.
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_incremental_events (
 id uuid PRIMARY KEY,user_id uuid NOT NULL,epoch bigint NOT NULL,scope_id uuid NOT NULL,
 pack_task_id uuid NOT NULL,slot_id uuid NOT NULL,root_id uuid NOT NULL,
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_private_generation_artifacts(id),
 job_id uuid NOT NULL,kind text NOT NULL CHECK(kind IN ('instruction','role_scope','started','committed','coverage','blind_rescore','blind_data')),
 action_key text NOT NULL,payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'),
 payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch),
 FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id),
 FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id),
 UNIQUE(user_id,epoch,scope_id,pack_task_id,slot_id,root_id,generation_artifact_id,kind,action_key)
);
REVOKE ALL ON tutor_item_supply_private_incremental_events FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_incremental_frame(frame jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r jsonb:=frame->'ref'; l jsonb:=frame->'lease'; a tutor_item_supply_private_generation_artifacts%ROWTYPE;
 c record; ph record; snapshot jsonb; review tutor_item_supply_private_native_quality_evidence%ROWTYPE;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_read_only')<>'off'
  OR current_setting('session_replication_role')<>'origin'
  OR frame->>'schema_version' IS DISTINCT FROM 'private_native_incremental_frame_v1' THEN
  RAISE EXCEPTION '588 original PRIVATE frame required'; END IF;
 PERFORM item_supply_internal.private_native_epoch((r->>'user_id')::uuid,(r->>'epoch')::bigint);
 IF item_supply_internal.private_pack_slot_current((r->>'pack_task_id')::uuid,(r->>'slot_id')::uuid,
   (r->>'business_item_id')::uuid,(r->>'root_id')::uuid,(r->>'user_id')::uuid,(r->>'epoch')::bigint,
   (r->>'scope_id')::uuid,(l->>'job_id')::uuid) IS DISTINCT FROM true THEN
  RAISE EXCEPTION '588 PRIVATE current original task slot root phase required'; END IF;
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal
  WHERE pack_task_id=(r->>'pack_task_id')::uuid AND user_id=(r->>'user_id')::uuid AND epoch=(r->>'epoch')::bigint
   AND scope_id=(r->>'scope_id')::uuid AND record_kind='phase'
   AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=l->>'job_id' FOR SHARE;
 SELECT co.*,j.root_id INTO c FROM tutor_item_supply_private_job_controls co
  JOIN tutor_item_supply_private_jobs j ON j.id=co.job_id AND j.user_id=co.user_id AND j.epoch=co.epoch
  WHERE co.job_id=(l->>'job_id')::uuid AND co.user_id=(r->>'user_id')::uuid AND co.epoch=(r->>'epoch')::bigint FOR SHARE OF co;
 SELECT * INTO a FROM tutor_item_supply_private_generation_artifacts WHERE id=(frame->>'artifact_id')::uuid
  AND user_id=(r->>'user_id')::uuid AND epoch=(r->>'epoch')::bigint AND scope_id=(r->>'scope_id')::uuid FOR SHARE;
 IF a.id IS NULL OR ph.id IS NULL OR c.job_id IS NULL THEN RAISE EXCEPTION '588 PRIVATE actual producer and current phase required'; END IF;
 snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 IF ph.payload_json->'ref' IS DISTINCT FROM r OR c.root_id::text IS DISTINCT FROM r->>'root_id' OR c.state IS DISTINCT FROM 'leased'
  OR c.lease_owner IS DISTINCT FROM l->>'lease_owner' OR c.lease_generation::text IS DISTINCT FROM l->>'generation'
  OR c.state_version::text IS DISTINCT FROM l->>'state_version' OR snapshot IS DISTINCT FROM l->'profile'
  OR c.lease_expires_at<=clock_timestamp() OR c.parent_deadline<=clock_timestamp()
  OR l->>'visibility' IS DISTINCT FROM 'private' OR l->>'owner_id' IS DISTINCT FROM r->>'user_id'
  OR l->>'owner_epoch' IS DISTINCT FROM r->>'epoch'
  OR a.mode IS DISTINCT FROM 'live' OR a.source_json IS DISTINCT FROM frame->'subject'->'source'
  OR a.source_json->'public'->>'kind' IS DISTINCT FROM 'knowledge_check'
  OR frame->'subject'->'finite_spec'->>'target_id' IS DISTINCT FROM 'python-kc-binding-v1'
  OR frame->'subject'->'binding'->>'version_key' IS DISTINCT FROM a.version_id::text
  OR frame->'subject'->'binding'->>'source_hash' IS DISTINCT FROM a.source_hash
  OR frame->'subject'->'binding'->>'content_hash' IS DISTINCT FROM a.content_hash
  OR frame->'subject'->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(frame->'subject'->'finite_spec')
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',r,'request',a.request_json,
    'source_receipts',a.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE EXCEPTION '588 PRIVATE current exact subject source policy lease required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current((r->>'mapping_receipt_id')::uuid,(r->>'user_id')::uuid,(r->>'epoch')::bigint);
 IF frame->>'parent_review_id' IS NOT NULL THEN
  SELECT * INTO review FROM tutor_item_supply_private_native_quality_evidence q
   WHERE q.id=(frame->>'parent_review_id')::uuid AND q.user_id=(r->>'user_id')::uuid AND q.epoch=(r->>'epoch')::bigint
    AND q.scope_id=(r->>'scope_id')::uuid AND q.pack_task_id=(r->>'pack_task_id')::uuid
    AND q.slot_id=(r->>'slot_id')::uuid AND q.root_id=(r->>'root_id')::uuid AND q.kind='review'
    AND q.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  IF review.id IS NULL THEN RAISE EXCEPTION '588 original committed PRIVATE parent review required'; END IF;
 END IF;
 RETURN jsonb_build_object('artifact',to_jsonb(a),'phase',ph.payload_json,'parent_review',review.payload_json);
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.private_incremental_committed_action(frame jsonb,stage text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r jsonb:=frame->'ref'; started tutor_item_supply_private_incremental_events%ROWTYPE;
 done tutor_item_supply_private_incremental_events%ROWTYPE; scope jsonb; action text; old_subject jsonb;
BEGIN
 PERFORM item_supply_internal.assert_private_incremental_frame(frame);
 action:=item_supply_internal.snapshot_hash(jsonb_build_object('domain','private_native_incremental_action_v1',
   'ref',r,'artifact_id',frame->>'artifact_id','stage',stage));
 SELECT * INTO started FROM tutor_item_supply_private_incremental_events e
  WHERE e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid
   AND e.pack_task_id=(r->>'pack_task_id')::uuid AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid
   AND e.generation_artifact_id=(frame->>'artifact_id')::uuid AND e.action_key=stage AND e.kind='started' FOR SHARE;
 SELECT * INTO done FROM tutor_item_supply_private_incremental_events e
  WHERE e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid
   AND e.pack_task_id=(r->>'pack_task_id')::uuid AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid
   AND e.generation_artifact_id=(frame->>'artifact_id')::uuid AND e.action_key=stage AND e.kind='committed' FOR SHARE;
 IF started.id IS NULL THEN RETURN '{"state":"unstarted"}'::jsonb; END IF;
 IF done.id IS NULL THEN RETURN '{"state":"unknown"}'::jsonb; END IF;
 old_subject:=done.payload_json->'frame'->'subject';
 IF done.payload_json->'data'->>'claim_id' IS DISTINCT FROM started.id::text
  OR started.payload_json->'frame'->'subject' IS DISTINCT FROM old_subject
  OR done.payload_json->'frame'->'ref' IS DISTINCT FROM r
  OR old_subject->'source' IS DISTINCT FROM frame->'subject'->'source'
  OR item_supply_internal.incremental_primary_dependency(old_subject,'technical') IS DISTINCT FROM
     item_supply_internal.incremental_primary_dependency(frame->'subject','technical')
  OR done.payload_json->'frame'->'lease'->'profile'->>'profile_key_hash' IS DISTINCT FROM frame->'lease'->'profile'->>'profile_key_hash'
  OR ((old_subject->'binding')-'profile_hash') IS DISTINCT FROM ((frame->'subject'->'binding')-'profile_hash')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.id IN(started.id,done.id)
     AND e.xmin::text::bigint=txid_current()%4294967296) THEN
  RAISE EXCEPTION '588 PRIVATE completed same-action original semantic recipe required'; END IF;
 SELECT e.payload_json->'data'->'scope' INTO scope FROM tutor_item_supply_private_incremental_events e
  WHERE e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid
   AND e.generation_artifact_id=(frame->>'artifact_id')::uuid AND e.kind='role_scope'
   AND e.payload_json->'data'->'scope'->>'role'=stage AND e.payload_json->'frame'->'subject'=old_subject FOR SHARE;
 RETURN jsonb_build_object('state','completed','result',done.payload_json->'data'->'result','subject',old_subject,
  'lease',done.payload_json->'frame'->'lease','scope',scope,'logical_action_hash',action);
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_incremental_evidence_v1(operation text,frame jsonb,data jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE origin jsonb; r jsonb:=frame->'ref'; s jsonb:=frame->'subject'; a jsonb; parent jsonb;
 row tutor_item_supply_private_incremental_events%ROWTYPE; started tutor_item_supply_private_incremental_events%ROWTYPE;
 done tutor_item_supply_private_incremental_events%ROWTYPE; wanted jsonb; report jsonb; finding jsonb; scope jsonb;
 event_kind_value text; key text; role text; id uuid; evidence jsonb; ids jsonb; old jsonb; path text; result jsonb;
BEGIN
 origin:=item_supply_internal.assert_private_incremental_frame(frame); a:=origin->'artifact'; parent:=origin->'parent_review';
 IF operation='stage_lookup' THEN RETURN item_supply_internal.private_incremental_committed_action(frame,data->>'stage'); END IF;
 IF operation IN ('verify_committed_role','verify_committed_blind') THEN
  wanted:=data->'applicability';
  role:=CASE WHEN operation='verify_committed_blind' THEN 'blind' ELSE wanted->'original'->'report'->>'role' END;
  result:=item_supply_internal.private_incremental_committed_action(frame,role);
  IF result->>'state' IS DISTINCT FROM 'completed' OR wanted->>'logical_action_hash' IS DISTINCT FROM result->>'logical_action_hash'
   OR wanted->'target_binding' IS DISTINCT FROM s->'binding'
   OR (operation='verify_committed_role' AND (wanted->'original'->'report' IS DISTINCT FROM result->'result'
     OR wanted->'original'->'subject' IS DISTINCT FROM result->'subject' OR wanted->'original'->'scope' IS DISTINCT FROM result->'scope'))
   OR (operation='verify_committed_blind' AND (wanted->'original_blind' IS DISTINCT FROM result->'result'
     OR wanted->'original_subject' IS DISTINCT FROM result->'subject')) THEN
   RAISE EXCEPTION '588 PRIVATE same-action applicability requires actual immutable committed result'; END IF;
  RETURN '{}'::jsonb;
 ELSIF operation='verify_committed_subject' THEN
  FOR role IN SELECT DISTINCT e.action_key FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
   AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.generation_artifact_id=(frame->>'artifact_id')::uuid
   AND e.kind='committed' AND e.payload_json->'frame'->'subject'=data->'subject' LOOP
   result:=item_supply_internal.private_incremental_committed_action(frame,role);
   IF result->>'state'='completed' THEN RETURN '{}'::jsonb; END IF;
  END LOOP;
  RAISE EXCEPTION '588 PRIVATE original committed same-action subject required';
 END IF;

 -- The stable business action excludes physical lease/profile/reservation identity.
 PERFORM pg_advisory_xact_lock(hashtext(r->>'user_id'),hashtext((frame->>'artifact_id')||':'||COALESCE(data->>'stage',data->>'role','evidence')));
 IF operation IN ('verify_original','subject_context','actionable_finding') THEN
  evidence:=data->'evidence'; wanted:=COALESCE(evidence->'subject',data->'subject');
  IF evidence IS NOT NULL THEN
   report:=evidence->'report';
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(item_supply_internal.incremental_reports(parent->'bundle')) rr WHERE rr=report)
    OR report->'binding' IS DISTINCT FROM wanted->'binding' THEN
    RAISE EXCEPTION '588 original parent effective report required'; END IF;
  END IF;
  SELECT to_jsonb(g) INTO old FROM tutor_item_supply_private_generation_artifacts g
   WHERE g.user_id=(r->>'user_id')::uuid AND g.epoch=(r->>'epoch')::bigint AND g.scope_id=(r->>'scope_id')::uuid
    AND g.source_json=wanted->'source' AND g.version_id::text=wanted->'binding'->>'version_key' FOR SHARE;
  IF old IS NULL THEN RAISE EXCEPTION '588 PRIVATE original subject authentication required'; END IF;
  IF operation='subject_context' THEN
   SELECT q.payload_json->'spec' INTO result FROM tutor_item_supply_private_native_quality_evidence q
    WHERE q.user_id=(r->>'user_id')::uuid AND q.epoch=(r->>'epoch')::bigint AND q.scope_id=(r->>'scope_id')::uuid
     AND q.pack_task_id=(r->>'pack_task_id')::uuid AND q.slot_id=(r->>'slot_id')::uuid AND q.root_id=(r->>'root_id')::uuid
     AND q.kind='review' AND q.payload_json->'bundle'->'binding'=wanted->'binding';
   IF result IS NULL OR item_supply_internal.snapshot_hash(result) IS DISTINCT FROM wanted->>'specification_hash' THEN
    RAISE EXCEPTION '588 original finite subject specification required'; END IF;
   RETURN jsonb_build_object('spec',result,'request',old->'request_json');
  ELSIF operation='actionable_finding' THEN
   finding:=report->'findings'->(data->>'finding_index')::integer;
   IF finding IS NULL OR report->>'schema_version' IS DISTINCT FROM 'item_supply_evidenced_review_report_v1'
    OR NOT (finding->'blocking'='true'::jsonb OR finding->>'severity' IN ('major','critical')) THEN
    RAISE EXCEPTION '588 concrete original material finding required'; END IF;
   IF finding->>'safe_code' IN ('rubric_mismatch','adversarial_exploit','unique_answer','security','data_leakage')
    OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.user_id=(r->>'user_id')::uuid
     AND q.epoch=(r->>'epoch')::bigint AND q.scope_id=(r->>'scope_id')::uuid AND q.kind='investigation'
     AND q.version_id::text=wanted->'binding'->>'version_key' AND q.payload_json::text LIKE '%contested%') THEN
    RETURN '{"action":"investigate"}'::jsonb;
   END IF;
   FOR path IN SELECT jsonb_array_elements_text(data->'allowed_paths') LOOP
    IF path !~ '^/(public|private)/' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(finding->'references') ref
     WHERE (ref->>'pointer'='/source'||path OR starts_with('/source'||path,(ref->>'pointer')||'/'))
     AND ref->>'value_hash'=item_supply_internal.snapshot_hash(item_supply_internal.review_investigation_pointer_value(
       jsonb_build_object('source',wanted->'source'),ref->>'pointer'))) THEN
     RAISE EXCEPTION '588 PRIVATE original located actionable finding required'; END IF;
   END LOOP;
  END IF;
  RETURN '{}'::jsonb;
 END IF;
 IF operation IN ('verify_revision','verify_revision_origin') THEN
  IF operation='verify_revision_origin' THEN
   SELECT q.payload_json->'request' INTO old FROM tutor_item_supply_private_persistent_pack_journal q
    WHERE q.id=(data->>'phase_id')::uuid AND q.user_id=(r->>'user_id')::uuid AND q.epoch=(r->>'epoch')::bigint
     AND q.scope_id=(r->>'scope_id')::uuid AND q.pack_task_id=(r->>'pack_task_id')::uuid
     AND q.payload_hash=data->>'phase_hash' AND q.payload_json->'request'->>'schema_version'='private_native_direct_revision_phase_v1'
     AND q.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
   IF old IS NULL OR old->'ref' IS DISTINCT FROM r OR old->>'parent_review_id' IS DISTINCT FROM frame->>'parent_review_id'
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts g
     WHERE g.id=(data->>'artifact_id')::uuid AND g.user_id=(r->>'user_id')::uuid AND g.epoch=(r->>'epoch')::bigint
      AND g.scope_id=(r->>'scope_id')::uuid AND g.artifact_hash=data->>'artifact_hash'
      AND g.request_json=old->'request' AND g.xmin::text::bigint<>txid_current()%4294967296) THEN
    RAISE EXCEPTION '588 PRIVATE committed exact direct author origin required'; END IF;
  ELSE
   IF parent->'bundle'->'binding' IS DISTINCT FROM data->'parent'->'binding'
    OR r->>'parent_version_id' IS DISTINCT FROM data->'parent'->'binding'->>'version_key'
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal q
     WHERE q.pack_task_id=(r->>'pack_task_id')::uuid AND q.user_id=(r->>'user_id')::uuid AND q.epoch=(r->>'epoch')::bigint
      AND q.scope_id=(r->>'scope_id')::uuid AND q.payload_json->'request'->>'schema_version'='private_native_direct_revision_phase_v1'
      AND q.payload_json->'request'->'request'=a->'request_json' AND q.payload_json->'request'->'allowed_paths'=data->'allowed_paths'
      AND q.payload_json->'request'->'instruction_ids'=frame->'instruction_ids'
      AND q.payload_json->'request'->>'parent_review_id'=frame->>'parent_review_id') THEN
    RAISE EXCEPTION '588 PRIVATE original direct child edge required'; END IF;
   PERFORM item_supply_internal.assert_incremental_local_diff(data->'parent'->'source',s->'source',data->'allowed_paths');
   IF (SELECT jsonb_agg(e->'report' ORDER BY n) FROM jsonb_array_elements(data->'prior_evidence') WITH ORDINALITY x(e,n))
     IS DISTINCT FROM item_supply_internal.incremental_reports(parent->'bundle') THEN
    RAISE EXCEPTION '588 complete original effective parent roles required'; END IF;
  END IF;
  RETURN '{}'::jsonb;
 END IF;
 IF operation IN ('stage_claim','stage_complete','verify_stage') THEN
  role:=data->>'stage';
  IF role NOT IN ('blind','curriculum','difficulty','technical','ambiguity','security','adversarial')
   OR s->'binding'->>'profile_hash' IS DISTINCT FROM frame->'lease'->'profile'->>'profile_hash' THEN
   RAISE EXCEPTION '588 PRIVATE exact same profile logical stage required'; END IF;
  SELECT * INTO started FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
   AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.pack_task_id=(r->>'pack_task_id')::uuid
   AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid AND e.generation_artifact_id=(frame->>'artifact_id')::uuid
   AND e.kind='started' AND e.action_key=role FOR SHARE;
  SELECT * INTO done FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
   AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.pack_task_id=(r->>'pack_task_id')::uuid
   AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid AND e.generation_artifact_id=(frame->>'artifact_id')::uuid
   AND e.kind='committed' AND e.action_key=role FOR SHARE;
  IF done.id IS NOT NULL AND operation='stage_claim' THEN
   RETURN item_supply_internal.private_incremental_committed_action(frame,role);
  END IF;
  IF started.id IS NOT NULL AND started.payload_json->'frame'->'subject' IS DISTINCT FROM s THEN
   RAISE EXCEPTION '588 new controller cannot rebind old PRIVATE logical stage'; END IF;
  IF operation='stage_claim' AND done.id IS NOT NULL THEN
   IF EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.id IN(started.id,done.id)
    AND e.xmin::text::bigint=txid_current()%4294967296) THEN RAISE EXCEPTION '588 prior TOP result required'; END IF;
   RETURN jsonb_build_object('state','completed','result',done.payload_json->'data'->'result');
  ELSIF operation='stage_claim' THEN
   IF started.id IS NOT NULL THEN RAISE EXCEPTION '588 UNKNOWN started stage cannot replay in successor batch'; END IF;
   event_kind_value:='started';key:=role;
  ELSIF operation='verify_stage' THEN
   IF done.id IS NULL OR done.payload_json->'data'->'result' IS DISTINCT FROM data->'result'
    OR EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.id=done.id AND e.xmin::text::bigint=txid_current()%4294967296) THEN
    RAISE EXCEPTION '588 exact original committed PRIVATE result required'; END IF;
   RETURN '{}'::jsonb;
  ELSE
   result:=data->'result';
   IF started.id IS NULL OR done.id IS NOT NULL OR started.id::text IS DISTINCT FROM data->>'claim_id'
    OR EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.id=started.id AND e.xmin::text::bigint=txid_current()%4294967296)
    OR item_supply_internal.incremental_binding(result) IS DISTINCT FROM s->'binding'
    OR (role<>'blind' AND result->'run'->>'profile_hash' IS DISTINCT FROM s->'binding'->>'profile_hash')
    OR item_supply_internal.incremental_blind_original(result)->'run'->>'run_id' IS NULL
    OR item_supply_internal.incremental_blind_original(result)->'run'->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
    OR (role<>'blind' AND result->>'role' IS DISTINCT FROM role) THEN
    RAISE EXCEPTION '588 PRIVATE completion requires original prior TOP dispatch/run'; END IF;
   event_kind_value:='committed';key:=role;
  END IF;
 ELSIF operation IN ('role_scope_get','role_scope','verify_role_scope','initial_role_scopes','original_role_scopes') THEN
  IF operation='initial_role_scopes' THEN
   IF frame->>'parent_review_id' IS NOT NULL OR jsonb_array_length(data->'scopes') IS DISTINCT FROM 6 THEN
    RAISE EXCEPTION '588 prospective initial six scopes required'; END IF;
   FOR scope IN SELECT value FROM jsonb_array_elements(data->'scopes') LOOP
    PERFORM item_supply_internal.private_native_incremental_evidence_v1('role_scope',frame,jsonb_build_object('scope',scope));
   END LOOP;
   RETURN '{}'::jsonb;
  ELSIF operation='original_role_scopes' THEN
   SELECT COALESCE(jsonb_agg(e.payload_json->'data'->'scope'),'[]'::jsonb) INTO result
    FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint
     AND e.scope_id=(r->>'scope_id')::uuid AND e.pack_task_id=(r->>'pack_task_id')::uuid AND e.slot_id=(r->>'slot_id')::uuid
     AND e.kind='role_scope' AND e.payload_json->'frame'->>'review_id'=data->>'review_id'
     AND e.xmin::text::bigint<>txid_current()%4294967296;
   RETURN jsonb_build_object('scopes',result);
  END IF;
  scope:=data->'scope';role:=COALESCE(scope->>'role',data->>'role');
  SELECT * INTO row FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
   AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.generation_artifact_id=(frame->>'artifact_id')::uuid
   AND e.kind='role_scope' AND e.payload_json->'data'->'scope'->>'role'=role
   AND e.payload_json->'frame'->'subject'=COALESCE(data->'evidence'->'subject',s) FOR SHARE;
  IF operation='role_scope_get' THEN RETURN jsonb_build_object('scope',row.payload_json->'data'->'scope'); END IF;
  IF operation='verify_role_scope' THEN
   IF row.id IS NULL OR row.payload_json->'data'->'scope' IS DISTINCT FROM scope
    OR scope->>'request_input_hash' IS DISTINCT FROM data->'evidence'->'report'->'run'->>'input_hash' THEN
    RAISE EXCEPTION '588 PRIVATE original predispatch scope required'; END IF;
   RETURN '{}'::jsonb;
  END IF;
  IF scope->>'subject_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(s)
   OR scope->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(s,role)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
     AND e.epoch=(r->>'epoch')::bigint AND e.generation_artifact_id=(frame->>'artifact_id')::uuid AND e.kind IN('started','committed') AND e.action_key=role)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(frame->>'review_id')::uuid) THEN
   RAISE EXCEPTION '588 no retroactive PRIVATE scope'; END IF;
  event_kind_value:='role_scope';key:=role||'.'||item_supply_internal.snapshot_hash(s);
 ELSIF operation IN ('instruction','verify_instruction') THEN
  event_kind_value:='instruction';key:=item_supply_internal.snapshot_hash(data->'instruction');
  SELECT rr INTO report FROM jsonb_array_elements(item_supply_internal.incremental_reports(parent->'bundle')) rr
   WHERE item_supply_internal.snapshot_hash(rr)=data->'instruction'->>'original_report_hash';
  IF report IS NULL OR data->'instruction'->'parent_binding' IS DISTINCT FROM parent->'bundle'->'binding' THEN
   RAISE EXCEPTION '588 PRIVATE original instruction report required'; END IF;
  FOR finding IN SELECT value FROM jsonb_array_elements(report->'findings') LOOP
   IF data->'instruction'->'finding_hashes' @> jsonb_build_array(item_supply_internal.snapshot_hash(finding))
    AND (finding->>'safe_code' IN ('rubric_mismatch','adversarial_exploit','unique_answer','security','data_leakage')
      OR NOT (finding->'blocking'='true'::jsonb OR finding->>'severity' IN ('major','critical'))) THEN
    RAISE EXCEPTION '588 PRIVATE instruction needs investigation'; END IF;
  END LOOP;
  IF operation='verify_instruction' THEN
   IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.id=(data->>'id')::uuid
     AND e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid
     AND e.kind='instruction' AND e.action_key=key AND e.payload_json->'data'->'instruction'=data->'instruction') THEN
    RAISE EXCEPTION '588 PRIVATE immutable instruction not found'; END IF;
   RETURN '{}'::jsonb;
  END IF;
 ELSIF operation IN ('confidential_blind_capture','confidential_blind_get') THEN
  IF operation='confidential_blind_get' THEN
   SELECT e.payload_json INTO result FROM tutor_item_supply_private_native_quality_evidence e
    WHERE e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid
     AND e.pack_task_id=(r->>'pack_task_id')::uuid AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid
     AND e.kind='blind_data' AND e.payload_json->>'review_id'=data->>'review_id'
     AND item_supply_internal.snapshot_hash(e.payload_json->'blind')=data->>'blind_receipt_hash'
     AND e.xmin::text::bigint<>txid_current()%4294967296;
   RETURN jsonb_build_object('capture',result);
  END IF;
  wanted:=data->'capture';event_kind_value:='blind_data';key:=frame->>'review_id';
  IF wanted->>'schema_version' IS DISTINCT FROM 'private_native_confidential_blind_data_v1'
   OR wanted->'ref' IS DISTINCT FROM r OR wanted->>'artifact_id' IS DISTINCT FROM frame->>'artifact_id'
   OR wanted->>'review_id' IS DISTINCT FROM frame->>'review_id' OR wanted->'subject' IS DISTINCT FROM s
   OR wanted->>'answer_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(wanted->'answer')
   OR wanted->>'answer_hash' IS DISTINCT FROM wanted->'blind'->>'solution_hash'
   OR wanted->'blind'->'run'->>'output_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('answer',wanted->'answer'))
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
     AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.generation_artifact_id=(frame->>'artifact_id')::uuid
     AND e.kind='committed' AND e.action_key='blind' AND e.payload_json->'data'->'result'=wanted->'blind'
     AND e.xmin::text::bigint<>txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(frame->>'review_id')::uuid) THEN
   RAISE EXCEPTION '588 no retrospective PRIVATE confidential solve capture'; END IF;
  id:=gen_random_uuid();
  INSERT INTO tutor_item_supply_private_native_quality_evidence(id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,version_id,kind,job_id,payload_json,checked_at,valid_until)
  VALUES(id,(r->>'user_id')::uuid,(r->>'epoch')::bigint,(r->>'scope_id')::uuid,(r->>'pack_task_id')::uuid,
   (r->>'slot_id')::uuid,(r->>'root_id')::uuid,(a->>'version_id')::uuid,'blind_data',(frame->'lease'->>'job_id')::uuid,
   wanted,clock_timestamp(),LEAST((frame->'lease'->>'expires_at')::timestamptz,(frame->'lease'->>'parent_deadline')::timestamptz));
  RETURN jsonb_build_object('id',id);
 ELSIF operation='coverage' THEN
  PERFORM item_supply_internal.assert_private_incremental_coverage(frame,data->'coverage');
  event_kind_value:='coverage';key:=item_supply_internal.snapshot_hash(data->'coverage');
 ELSIF operation IN ('blind_rescore','verify_blind_rescore') THEN
  PERFORM item_supply_internal.assert_private_incremental_blind_rescore(frame,data->'rescore');
  event_kind_value:='blind_rescore';key:=item_supply_internal.snapshot_hash(data->'rescore');
  IF operation='verify_blind_rescore' THEN
   IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
    AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.kind=event_kind_value AND e.action_key=key
    AND e.payload_json->'data'->'rescore'=data->'rescore') THEN
    RAISE EXCEPTION '588 original PRIVATE rescore evidence required'; END IF;
   RETURN '{}'::jsonb;
  END IF;
 ELSE RAISE EXCEPTION '588 unsupported PRIVATE incremental operation'; END IF;
 SELECT * INTO row FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
  AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.pack_task_id=(r->>'pack_task_id')::uuid
  AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid AND e.generation_artifact_id=(frame->>'artifact_id')::uuid
  AND e.kind=event_kind_value AND e.action_key=key FOR SHARE;
 IF row.id IS NOT NULL THEN
  IF row.payload_json->'data' IS DISTINCT FROM data OR row.payload_json->'frame'->'subject' IS DISTINCT FROM s THEN
   RAISE EXCEPTION '588 PRIVATE immutable action differs'; END IF;
  RETURN jsonb_build_object('id',row.id);
 END IF;
 id:=gen_random_uuid();
 INSERT INTO tutor_item_supply_private_incremental_events(id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,generation_artifact_id,job_id,kind,action_key,payload_json)
 VALUES(id,(r->>'user_id')::uuid,(r->>'epoch')::bigint,(r->>'scope_id')::uuid,(r->>'pack_task_id')::uuid,(r->>'slot_id')::uuid,
  (r->>'root_id')::uuid,(frame->>'artifact_id')::uuid,(frame->'lease'->>'job_id')::uuid,event_kind_value,key,jsonb_build_object('frame',frame,'data',data));
 RETURN CASE WHEN operation='stage_claim' THEN jsonb_build_object('state','claimed','id',id) ELSE jsonb_build_object('id',id) END;
END $$;

DROP TRIGGER IF EXISTS private_incremental_epoch ON tutor_item_supply_private_incremental_events;
CREATE TRIGGER private_incremental_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_incremental_events
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS private_incremental_immutable ON tutor_item_supply_private_incremental_events;
CREATE TRIGGER private_incremental_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_private_incremental_events
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');
CREATE OR REPLACE FUNCTION item_supply_internal.purge_private_incremental_on_epoch_advance()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch<>OLD.epoch+1 OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
  RAISE EXCEPTION '588 original maintenance epoch permit required'; END IF;
 DELETE FROM tutor_item_supply_private_incremental_events WHERE user_id=OLD.user_id;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS a0000_private_incremental_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a0000_private_incremental_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN(NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION item_supply_internal.purge_private_incremental_on_epoch_advance();

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_incremental_blind_rescore(frame jsonb,b jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE origin jsonb; r jsonb:=frame->'ref'; s jsonb:=frame->'subject'; capture jsonb;
BEGIN
 origin:=item_supply_internal.assert_private_incremental_frame(frame);
 SELECT e.payload_json INTO capture FROM tutor_item_supply_private_native_quality_evidence e
  WHERE e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid
   AND e.pack_task_id=(r->>'pack_task_id')::uuid AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid
   AND e.kind='blind_data' AND e.payload_json->'blind'=b->'original_blind'
   AND e.payload_json->'subject'=b->'original_subject'
   AND e.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
 IF capture IS NULL OR b->>'schema_version' IS DISTINCT FROM 'item_supply_blind_rescore_applicability_v1'
  OR b->'target_binding' IS DISTINCT FROM s->'binding'
  OR b->>'target_validation_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(s->'validation_receipt')
  OR ((b->'original_subject'->'source'->'public')-'version') IS DISTINCT FROM ((s->'source'->'public')-'version')
  OR ((b->'original_subject'->'finite_spec')#-'{public_template,version}') IS DISTINCT FROM ((s->'finite_spec')#-'{public_template,version}')
  OR b->'score'->>'receipt_hash'=b->'original_blind'->'score'->>'receipt_hash'
  OR b->'score'->>'scorer_identity' IS DISTINCT FROM 'finite-static-blind-scorer'
  OR jsonb_typeof(b->'score'->'passed') IS DISTINCT FROM 'boolean'
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
    AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.generation_artifact_id=(frame->>'artifact_id')::uuid
    AND e.kind='started' AND e.action_key='blind' AND e.xmin::text::bigint<>txid_current()%4294967296) THEN
  RAISE EXCEPTION '588 PRIVATE original answer DATA and new bounded score required'; END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_incremental_coverage(frame jsonb,b jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE origin jsonb; r jsonb:=frame->'ref'; s jsonb:=frame->'subject'; parent jsonb;
 entry jsonb; report jsonb; previous jsonb; scope jsonb; paths jsonb; runs text[]:='{}';identities text[]:='{}';
 role_name text; run jsonb; i integer:=0; roles text[]; parent_source jsonb;
BEGIN
 origin:=item_supply_internal.assert_private_incremental_frame(frame);parent:=origin->'parent_review';
 IF b->>'schema_version' IS DISTINCT FROM 'item_supply_review_coverage_v1' OR b->'binding' IS DISTINCT FROM s->'binding'
  OR parent IS NULL OR parent='null'::jsonb OR b->'binding'->>'policy_hash' IS DISTINCT FROM parent->'bundle'->'binding'->>'policy_hash'
  OR item_supply_internal.incremental_binding(b->'blind_solve') IS DISTINCT FROM s->'binding'
  OR jsonb_array_length(b->'entries') IS DISTINCT FROM 6 THEN
  RAISE EXCEPTION '588 PRIVATE complete current child effective coverage required'; END IF;
 SELECT array_agg(e->>'role' ORDER BY n) INTO roles FROM jsonb_array_elements(b->'entries') WITH ORDINALITY q(e,n);
 IF roles IS DISTINCT FROM ARRAY['curriculum','difficulty','technical','ambiguity','security','adversarial']::text[] THEN
  RAISE EXCEPTION '588 PRIVATE six exact distinct effective roles required'; END IF;
 SELECT jsonb_agg(DISTINCT path ORDER BY path) INTO paths FROM tutor_item_supply_private_incremental_events e,
  LATERAL jsonb_array_elements_text(e.payload_json->'data'->'instruction'->'allowed_paths') path
  WHERE e.user_id=(r->>'user_id')::uuid AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid
   AND e.pack_task_id=(r->>'pack_task_id')::uuid AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid
   AND e.kind='instruction' AND frame->'instruction_ids' @> jsonb_build_array(e.id::text);
 IF paths IS NULL OR paths IS DISTINCT FROM b->'impact'->'allowed_paths' THEN
  RAISE EXCEPTION '588 original PRIVATE instructions define changed scope'; END IF;
 SELECT g.source_json INTO parent_source FROM tutor_item_supply_private_generation_artifacts g
  WHERE g.id=(parent->>'artifact_id')::uuid AND g.user_id=(r->>'user_id')::uuid AND g.epoch=(r->>'epoch')::bigint
   AND g.scope_id=(r->>'scope_id')::uuid AND g.version_id::text=r->>'parent_version_id' FOR SHARE;
 IF parent_source IS NULL OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal q
  WHERE q.pack_task_id=(r->>'pack_task_id')::uuid AND q.user_id=(r->>'user_id')::uuid AND q.epoch=(r->>'epoch')::bigint
   AND q.scope_id=(r->>'scope_id')::uuid AND q.payload_json->'request'->>'schema_version'='private_native_direct_revision_phase_v1'
   AND q.payload_json->'request'->'request'=origin->'artifact'->'request_json'
   AND q.payload_json->'request'->'instruction_ids'=frame->'instruction_ids' AND q.payload_json->'request'->'allowed_paths'=paths
   AND q.payload_json->'request'->>'parent_review_id'=frame->>'parent_review_id') THEN
  RAISE EXCEPTION '588 PRIVATE exact original direct child lineage required'; END IF;
 PERFORM item_supply_internal.assert_incremental_local_diff(parent_source,s->'source',paths);
 IF b->'impact'->'changed_paths' IS DISTINCT FROM to_jsonb(ARRAY(SELECT path FROM unnest(item_supply_internal.incremental_changed_paths(parent_source,s->'source'))
    WITH ORDINALITY changed(path,n) WHERE path NOT IN ('/public/version','/private/version') ORDER BY n))
  OR b->'impact'->>'rule_version' IS DISTINCT FROM 'finite-impact-v2'
  OR b->'impact'->>'child_subject_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(s)
  OR b->'impact'->'machine_validation_required' IS DISTINCT FROM 'true'::jsonb
  OR b->'impact'->'coverage_rebuild_required' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION '588 PRIVATE actual host diff and child machine evidence required'; END IF;
 -- Each effective original is authenticated against the actual parent's immutable
 -- review, not against an author-provided ancestry list.
 FOR entry IN SELECT value FROM jsonb_array_elements(b->'entries') LOOP
  role_name:=entry->>'role';report:=entry->'original'->'report';scope:=entry->'original'->'scope';
  SELECT rr INTO previous FROM jsonb_array_elements(item_supply_internal.incremental_reports(parent->'bundle')) rr WHERE rr->>'role'=role_name;
  IF previous IS NULL OR report->>'role' IS DISTINCT FROM role_name
   OR b->'impact'->'original_report_hashes'->>i IS DISTINCT FROM item_supply_internal.snapshot_hash(previous) THEN
   RAISE EXCEPTION '588 PRIVATE exact effective parent report hashes required'; END IF;
  IF entry->>'mode'='fresh' THEN
   IF NOT (b->'impact'->'required_roles' @> jsonb_build_array(role_name)) OR report->'binding' IS DISTINCT FROM b->'binding' THEN
    RAISE EXCEPTION '588 PRIVATE failed or changed roles need fresh bound report'; END IF;
   PERFORM item_supply_internal.private_native_incremental_evidence_v1('verify_stage',frame,jsonb_build_object('stage',role_name,'result',report));
  ELSIF entry->>'mode'='original_applicable' THEN
   IF report IS DISTINCT FROM previous OR item_supply_internal.incremental_material_failure(report)
    OR b->'impact'->'required_roles' @> jsonb_build_array(role_name) OR scope IS NULL OR scope='null'::jsonb
    OR scope->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(entry->'original'->'subject',role_name)
    OR scope->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(s,role_name)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=(r->>'user_id')::uuid
      AND e.epoch=(r->>'epoch')::bigint AND e.scope_id=(r->>'scope_id')::uuid AND e.pack_task_id=(r->>'pack_task_id')::uuid
      AND e.slot_id=(r->>'slot_id')::uuid AND e.root_id=(r->>'root_id')::uuid AND e.kind='role_scope'
      AND e.payload_json->'data'->'scope'=scope AND e.payload_json->'frame'->'subject'=entry->'original'->'subject') THEN
    RAISE EXCEPTION '588 PRIVATE original prospective scope/applicability required'; END IF;
  ELSIF entry->>'mode'='committed_same_action' THEN
   IF NOT (b->'impact'->'required_roles' @> jsonb_build_array(role_name))
    OR entry->'committed_action'->'original' IS DISTINCT FROM entry->'original' THEN
    RAISE EXCEPTION '588 required role must be original same logical action'; END IF;
   PERFORM item_supply_internal.private_native_incremental_evidence_v1('verify_committed_role',frame,
     jsonb_build_object('applicability',entry->'committed_action'));
  ELSE RAISE EXCEPTION '588 PRIVATE unsupported role coverage mode'; END IF;
  run:=report->'run';
  IF run->>'run_id'=ANY(runs) OR run->'provider_identity'->>'identity'=ANY(identities)
   OR run->'provider_identity'->>'identity'=b->>'author_identity' THEN RAISE EXCEPTION '588 PRIVATE provider independence required'; END IF;
  runs:=array_append(runs,run->>'run_id');identities:=array_append(identities,run->'provider_identity'->>'identity');i:=i+1;
 END LOOP;
 IF b->'blind_solve'->>'schema_version'='item_supply_committed_blind_applicability_v1' THEN
  PERFORM item_supply_internal.private_native_incremental_evidence_v1('verify_committed_blind',frame,jsonb_build_object('applicability',b->'blind_solve'));
 ELSE
  PERFORM item_supply_internal.private_native_incremental_evidence_v1('verify_stage',frame,jsonb_build_object('stage','blind','result',b->'blind_solve'));
 END IF;
 run:=item_supply_internal.incremental_blind_original(b->'blind_solve')->'run';
 IF run->>'run_id'=ANY(runs) OR run->'provider_identity'->>'identity'=ANY(identities)
  OR run->'provider_identity'->>'identity'=b->>'author_identity' THEN RAISE EXCEPTION '588 PRIVATE independent blind required'; END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_incremental_event()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE frame jsonb:=NEW.payload_json->'frame';data jsonb:=NEW.payload_json->'data';origin jsonb;r jsonb:=frame->'ref';
 aux record;start_row tutor_item_supply_private_incremental_events%ROWTYPE;scope_row tutor_item_supply_private_incremental_events%ROWTYPE;
BEGIN
 origin:=item_supply_internal.assert_private_incremental_frame(frame);
 IF NEW.user_id::text IS DISTINCT FROM r->>'user_id' OR NEW.epoch::text IS DISTINCT FROM r->>'epoch'
  OR NEW.scope_id::text IS DISTINCT FROM r->>'scope_id' OR NEW.pack_task_id::text IS DISTINCT FROM r->>'pack_task_id'
  OR NEW.slot_id::text IS DISTINCT FROM r->>'slot_id' OR NEW.root_id::text IS DISTINCT FROM r->>'root_id'
  OR NEW.generation_artifact_id::text IS DISTINCT FROM frame->>'artifact_id' OR NEW.job_id::text IS DISTINCT FROM frame->'lease'->>'job_id' THEN
  RAISE EXCEPTION '588 PRIVATE physical event scope matches original frame'; END IF;
 IF NEW.kind IN ('role_scope','started','committed','blind_data','coverage','blind_rescore') THEN
  SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal q
   WHERE q.id=(frame->>'review_id')::uuid AND q.pack_task_id=NEW.pack_task_id AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch
    AND q.scope_id=NEW.scope_id AND q.record_kind='private_attachment'
    AND q.payload_json->>'schema_version'='private_native_auxiliary_v1'
    AND q.payload_json->'request'->>'schema_version'='private_native_review_phase_v1'
    AND q.payload_json->'request'->>'artifact_id'=NEW.generation_artifact_id::text
    AND q.payload_json->'request'->'binding'=frame->'subject'->'binding' FOR SHARE;
  IF aux.id IS NULL THEN RAISE EXCEPTION '588 PRIVATE original review preparation required'; END IF;
 END IF;
 IF NEW.kind IN ('started','committed') THEN
  IF NEW.action_key IS DISTINCT FROM data->>'stage' OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal q
    WHERE q.id=aux.id AND q.xmin::text::bigint=txid_current()%4294967296) THEN
   RAISE EXCEPTION '588 PRIVATE prior TOP original prepared dispatch required'; END IF;
  SELECT * INTO scope_row FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch
   AND e.scope_id=NEW.scope_id AND e.generation_artifact_id=NEW.generation_artifact_id
   AND e.payload_json->'data'->'scope'->>'role'=NEW.action_key AND e.kind='role_scope'
   AND e.payload_json->'frame'->'subject'=frame->'subject' FOR SHARE;
  SELECT * INTO start_row FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch
   AND e.scope_id=NEW.scope_id AND e.generation_artifact_id=NEW.generation_artifact_id AND e.action_key=NEW.action_key AND e.kind='started' FOR SHARE;
  IF NEW.kind='started' THEN
   IF start_row.id IS NOT NULL OR (NEW.action_key<>'blind' AND (scope_row.id IS NULL OR EXISTS(
    SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.id=scope_row.id AND e.xmin::text::bigint=txid_current()%4294967296))) THEN
    RAISE EXCEPTION '588 PRIVATE no replay and original prospective scope required'; END IF;
  ELSE
   IF start_row.id IS NULL OR data->>'claim_id' IS DISTINCT FROM start_row.id::text
    OR start_row.payload_json->'frame'->'subject' IS DISTINCT FROM frame->'subject'
    OR EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.id=start_row.id AND e.xmin::text::bigint=txid_current()%4294967296)
    OR item_supply_internal.incremental_binding(data->'result') IS DISTINCT FROM frame->'subject'->'binding'
    OR (NEW.action_key<>'blind' AND (data->'result'->>'role' IS DISTINCT FROM NEW.action_key
      OR data->'result'->'run'->>'input_hash' IS DISTINCT FROM scope_row.payload_json->'data'->'scope'->>'request_input_hash')) THEN
    RAISE EXCEPTION '588 PRIVATE completion must bind original started actual input'; END IF;
  END IF;
 ELSIF NEW.kind='coverage' THEN
  PERFORM item_supply_internal.assert_private_incremental_coverage(frame,data->'coverage');
 ELSIF NEW.kind='blind_rescore' THEN
  PERFORM item_supply_internal.assert_private_incremental_blind_rescore(frame,data->'rescore');
 ELSIF NEW.kind='role_scope' THEN
  IF (data->'scope'->>'role')||'.'||item_supply_internal.snapshot_hash(frame->'subject') IS DISTINCT FROM NEW.action_key
   OR data->'scope'->>'subject_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(frame->'subject')
   OR data->'scope'->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(frame->'subject',data->'scope'->>'role')
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(frame->>'review_id')::uuid)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch
    AND e.generation_artifact_id=NEW.generation_artifact_id AND e.action_key=data->'scope'->>'role' AND e.kind IN ('started','committed')) THEN
   RAISE EXCEPTION '588 PRIVATE scope cannot retrofit old report'; END IF;
 ELSIF NEW.kind='blind_data' THEN
  IF data->'capture'->>'answer_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(data->'capture'->'answer')
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch
    AND e.scope_id=NEW.scope_id AND e.generation_artifact_id=NEW.generation_artifact_id AND e.kind='committed' AND e.action_key='blind'
    AND e.payload_json->'data'->'result'=data->'capture'->'blind' AND e.xmin::text::bigint<>txid_current()%4294967296) THEN
   RAISE EXCEPTION '588 PRIVATE capture requires actual committed blind result'; END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS private_incremental_insert ON tutor_item_supply_private_incremental_events;
CREATE TRIGGER private_incremental_insert BEFORE INSERT ON tutor_item_supply_private_incremental_events
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_incremental_event();

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_review_probe_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),action_key text NOT NULL CHECK(action_key ~ '^[0-9a-f]{64}$'),
 preparation_id uuid NOT NULL,job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id),
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id),
 review_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id),
 reservation_id uuid REFERENCES tutor_item_supply_shared_reservations(id),
 event_kind text NOT NULL CHECK(event_kind IN ('intent','prepared','started','completed')),
 CHECK((event_kind='intent')=(reservation_id IS NULL)),
 frame_json jsonb NOT NULL,payload_json jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(preparation_id,event_kind)
);
CREATE UNIQUE INDEX IF NOT EXISTS shared_review_probe_logical_once ON tutor_item_supply_shared_review_probe_events(action_key,event_kind)
 WHERE event_kind IN ('started','completed');
REVOKE ALL ON tutor_item_supply_shared_review_probe_events FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_review_probe_frame(frame jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE rr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 report jsonb; finding jsonb;
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(frame->'lease',(frame->>'artifact_id')::uuid);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(frame->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(frame->>'review_receipt_id')::uuid FOR SHARE;
 IF frame->>'schema_version' IS DISTINCT FROM 'native_review_probe_frame_v1'
  OR frame->>'root_id' IS DISTINCT FROM a.root_id::text OR rr.id IS NULL OR rr.artifact_kind IS DISTINCT FROM 'review_bundle'
  OR rr.generation_artifact_id IS DISTINCT FROM a.id OR frame->'binding' IS DISTINCT FROM rr.payload_json->'binding'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.id=rr.id AND r.xmin::text::bigint=txid_current()%4294967296)
  OR frame->>'action_key' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('artifact_id',frame->>'artifact_id',
   'review_receipt_id',frame->>'review_receipt_id','finding_key',frame->>'finding_key','query_hash',frame->>'query_hash')) THEN
  RAISE EXCEPTION '588 probe actual original review/identity required'; END IF;
 SELECT value INTO report FROM jsonb_array_elements(item_supply_internal.incremental_reports(rr.payload_json))
  WHERE item_supply_internal.snapshot_hash(value)=frame->>'report_hash';
 finding:=report->'findings'->(frame->>'finding_index')::integer;
 IF report IS NULL OR finding IS NULL OR finding->'blocking' IS DISTINCT FROM 'true'::jsonb
  OR finding->>'safe_code' IS DISTINCT FROM 'adversarial_exploit' OR jsonb_typeof(finding->'counterexample') IS DISTINCT FROM 'string'
  OR item_supply_internal.snapshot_hash(finding) IS DISTINCT FROM frame->>'finding_hash'
  OR frame->>'finding_key' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_array(
    rr.receipt_hash,frame->>'report_hash',(frame->>'finding_index')::integer,frame->>'finding_hash')) THEN
  RAISE EXCEPTION '588 probe exact original authenticated adversarial finding required'; END IF;
 RETURN finding;
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_review_probe_event()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE frame jsonb:=NEW.frame_json; data jsonb:=NEW.payload_json; finding jsonb;
 prepared tutor_item_supply_shared_review_probe_events%ROWTYPE; started tutor_item_supply_shared_review_probe_events%ROWTYPE;
 intent tutor_item_supply_shared_review_probe_events%ROWTYPE; source_request jsonb;
 reserve tutor_item_supply_shared_reservations%ROWTYPE; usage tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 terminal jsonb; k text; v jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' OR current_setting('session_replication_role')<>'origin' THEN
  RAISE EXCEPTION '588 original probe write transaction required'; END IF;
 IF NEW.action_key IS DISTINCT FROM frame->>'action_key' OR NEW.job_id::text IS DISTINCT FROM frame->'lease'->>'job_id'
  OR NEW.generation_artifact_id::text IS DISTINCT FROM frame->>'artifact_id'
  OR NEW.review_receipt_id::text IS DISTINCT FROM frame->>'review_receipt_id' THEN
  RAISE EXCEPTION '588 original probe columns/frame binding required'; END IF;
 SELECT * INTO prepared FROM tutor_item_supply_shared_review_probe_events WHERE preparation_id=NEW.preparation_id AND event_kind='prepared' FOR SHARE;
 SELECT * INTO started FROM tutor_item_supply_shared_review_probe_events WHERE action_key=NEW.action_key AND event_kind='started' FOR SHARE;
 IF NEW.event_kind<>'completed' THEN finding:=item_supply_internal.assert_shared_review_probe_frame(frame); END IF;
 IF NEW.event_kind='intent' THEN
  SELECT request_json INTO source_request FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NEW.reservation_id IS NOT NULL OR started.id IS NOT NULL OR prepared.id IS NOT NULL
   OR item_supply_internal.snapshot_keys(data,ARRAY['preparation_id','query','resources','deadline']) IS DISTINCT FROM true
   OR data->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text
   OR data->>'query' IS DISTINCT FROM item_supply_internal.original_review_counterexample_statement(finding->>'counterexample')
   OR item_supply_internal.snapshot_hash(jsonb_build_object('answer',data->'query')) IS DISTINCT FROM frame->>'query_hash'
   OR data->'resources' IS DISTINCT FROM '{"requests":0,"input_tokens":0,"output_tokens":0,"execution_seconds":10,"fetches":0,"candidates":0,"revision_rounds":0,"investigation_rounds":0}'::jsonb
   OR data->'resources'->>'execution_seconds' IS DISTINCT FROM '10'
   OR (data->>'deadline')::timestamptz<=clock_timestamp()
   OR (data->>'deadline')::timestamptz>LEAST((frame->'lease'->>'expires_at')::timestamptz,
     (frame->'lease'->>'parent_deadline')::timestamptz,(frame->'lease'->'profile'->>'parent_deadline_at')::timestamptz,
     item_supply_internal.incremental_shared_source_deadline(source_request))
   OR COALESCE((frame->'lease'->'profile'->'values'->>'stage_deadline_ms')::bigint>=10000,false) IS DISTINCT FROM true THEN
   RAISE EXCEPTION '588 original probe intent requires exact query current deadline and execution-only10 plan'; END IF;
 ELSIF NEW.event_kind='prepared' THEN
  SELECT * INTO intent FROM tutor_item_supply_shared_review_probe_events WHERE preparation_id=NEW.preparation_id AND event_kind='intent' FOR SHARE;
  IF intent.id IS NULL OR intent.reservation_id IS NOT NULL OR intent.action_key IS DISTINCT FROM NEW.action_key
   OR intent.frame_json IS DISTINCT FROM frame OR intent.payload_json IS DISTINCT FROM (data-'reservation_id')
   OR (intent.payload_json->>'deadline')::timestamptz<=clock_timestamp() THEN
   RAISE EXCEPTION '588 probe preparation requires same exact current intent before budget'; END IF;
  SELECT * INTO reserve FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id FOR SHARE;
  IF started.id IS NOT NULL OR data->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text
   OR data->>'reservation_id' IS DISTINCT FROM NEW.reservation_id::text OR reserve.job_id IS DISTINCT FROM NEW.job_id
   OR reserve.root_id::text IS DISTINCT FROM frame->>'root_id' OR reserve.lease_generation::text IS DISTINCT FROM frame->'lease'->>'generation'
   OR reserve.reservation_key IS DISTINCT FROM 'normal.review.probe.'||replace(NEW.preparation_id::text,'-','')
   OR data->>'query' IS NULL OR length(data->>'query') NOT BETWEEN 1 AND 48000 OR data->>'query' IS DISTINCT FROM item_supply_internal.original_review_counterexample_statement(finding->>'counterexample')
   OR item_supply_internal.snapshot_hash(jsonb_build_object('answer',data->'query')) IS DISTINCT FROM frame->>'query_hash'
   OR (data->>'deadline')::timestamptz<=clock_timestamp()
   OR (data->>'deadline')::timestamptz>(frame->'lease'->>'expires_at')::timestamptz
   OR (data->'resources')-'execution_seconds' IS DISTINCT FROM '{"requests":0,"input_tokens":0,"output_tokens":0,"fetches":0,"candidates":0,"revision_rounds":0,"investigation_rounds":0}'::jsonb
   OR (data->'resources'->>'execution_seconds')::integer IS DISTINCT FROM 10 THEN
   RAISE EXCEPTION '588 exact original query and execution-only probe reservation required'; END IF;
  FOR k,v IN SELECT key,value FROM jsonb_each(data->'resources') LOOP
   IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
     WHERE ra.reservation_namespace='shared' AND ra.reservation_id=reserve.id AND ra.resource_kind=k AND ra.reserved_amount=(v::text)::bigint) THEN
    RAISE EXCEPTION '588 original charged probe resource allocation required'; END IF;
  END LOOP;
 ELSIF NEW.event_kind='started' THEN
  IF started.id IS NOT NULL OR prepared.id IS NULL OR prepared.frame_json IS DISTINCT FROM frame
   OR prepared.reservation_id IS DISTINCT FROM NEW.reservation_id OR prepared.action_key IS DISTINCT FROM NEW.action_key
   OR (prepared.payload_json->>'deadline')::timestamptz<=clock_timestamp()
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_probe_events e WHERE e.id=prepared.id AND e.xmin::text::bigint=txid_current()%4294967296) THEN
   RAISE EXCEPTION '588 probe start requires original prior TOP preparation and unspent action'; END IF;
 ELSE
  SELECT * INTO usage FROM tutor_item_supply_shared_runtime_settlements u WHERE u.reservation_id=NEW.reservation_id
   AND u.settlement_key='normal.review.probe.'||replace(NEW.preparation_id::text,'-','') AND u.usage_state='known'
   AND u.receipt_hash=item_supply_internal.snapshot_hash(data) AND u.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  terminal:=data->'terminals'->0;
  IF prepared.id IS NULL OR started.id IS NULL OR usage.id IS NULL OR started.preparation_id IS DISTINCT FROM NEW.preparation_id
   OR started.frame_json IS DISTINCT FROM frame OR started.reservation_id IS DISTINCT FROM NEW.reservation_id
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_probe_events e WHERE e.id=started.id AND e.xmin::text::bigint=txid_current()%4294967296)
   OR data->>'schema_version' IS DISTINCT FROM 'native_review_probe_result_v1'
   OR data->>'purpose' IS DISTINCT FROM 'counterexample_verification_not_blind'
   OR data->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text OR data->>'reservation_id' IS DISTINCT FROM NEW.reservation_id::text
   OR data->>'action_key' IS DISTINCT FROM NEW.action_key OR data->>'query_hash' IS DISTINCT FROM frame->>'query_hash'
   OR data->>'finding_key' IS DISTINCT FROM frame->>'finding_key' OR jsonb_array_length(data->'terminals') IS DISTINCT FROM 1
   OR terminal->>'mode' IS DISTINCT FROM 'live' OR terminal->>'isolation' IS DISTINCT FROM 'approved_os_boundary'
   OR terminal->>'result_status' IS DISTINCT FROM 'success' OR terminal->>'scorer_status' NOT IN ('passed','failed')
   OR COALESCE(terminal->>'seal','')='' OR COALESCE(terminal->>'terminal_hash','') !~ '^[0-9a-f]{64}$'
   OR (data->'score'->>'passed')::boolean IS DISTINCT FROM (terminal->>'scorer_status'='passed')
   OR data->'score'->>'receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
     'binding',frame->'binding','terminal',terminal,'scorer',data->'score'->>'scorer_version')) THEN
   RAISE EXCEPTION '588 actual committed probe start terminal score known settlement required'; END IF;
  FOR k,v IN SELECT key,value FROM jsonb_each(data->'usage') LOOP
   IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts sa
    WHERE sa.settlement_id=usage.id AND sa.resource_kind=k AND sa.actual_amount=(v::text)::bigint) THEN
    RAISE EXCEPTION '588 original actual probe settlement amounts required'; END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS shared_review_probe_insert ON tutor_item_supply_shared_review_probe_events;
CREATE TRIGGER shared_review_probe_insert BEFORE INSERT ON tutor_item_supply_shared_review_probe_events
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_review_probe_event();
DROP TRIGGER IF EXISTS shared_review_probe_immutable ON tutor_item_supply_shared_review_probe_events;
CREATE TRIGGER shared_review_probe_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_review_probe_events
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
CREATE OR REPLACE FUNCTION item_supply_internal.shared_review_probe_event_v1(operation text,frame jsonb,data jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE prepared tutor_item_supply_shared_review_probe_events%ROWTYPE; started tutor_item_supply_shared_review_probe_events%ROWTYPE;
 done tutor_item_supply_shared_review_probe_events%ROWTYPE; pid uuid; reservation uuid; kind text;
BEGIN
 IF operation<>'complete' THEN PERFORM item_supply_internal.assert_shared_review_probe_frame(frame); END IF;
 PERFORM pg_advisory_xact_lock(hashtext('shared.review.probe'),hashtext(frame->>'action_key'));
 SELECT * INTO started FROM tutor_item_supply_shared_review_probe_events WHERE action_key=frame->>'action_key' AND event_kind='started' FOR SHARE;
 SELECT * INTO done FROM tutor_item_supply_shared_review_probe_events WHERE action_key=frame->>'action_key' AND event_kind='completed' FOR SHARE;
 IF operation='lookup' THEN
  IF done.id IS NOT NULL THEN RETURN jsonb_build_object('state','completed','result',done.payload_json); END IF;
  RETURN jsonb_build_object('state',CASE WHEN started.id IS NULL THEN 'unstarted' ELSE 'unknown' END);
 END IF;
 pid:=(data->>'preparation_id')::uuid;
 SELECT * INTO prepared FROM tutor_item_supply_shared_review_probe_events WHERE preparation_id=pid AND event_kind='prepared' FOR SHARE;
 IF operation='verify_start' THEN
  IF started.id IS NULL OR started.preparation_id IS DISTINCT FROM pid OR started.frame_json IS DISTINCT FROM frame
   OR done.id IS NOT NULL OR (prepared.payload_json->>'deadline')::timestamptz<=clock_timestamp()
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_probe_events e WHERE e.id=started.id AND e.xmin::text::bigint=txid_current()%4294967296) THEN
   RAISE EXCEPTION '588 probe prior TOP started once required'; END IF;
  RETURN '{"state":"started"}'::jsonb;
 END IF;
 IF operation='intent' THEN kind:='intent';reservation:=NULL;
 ELSIF operation='prepare' THEN kind:='prepared';reservation:=(data->>'reservation_id')::uuid;
 ELSIF operation='start' THEN kind:='started';reservation:=(data->>'reservation_id')::uuid;
 ELSIF operation='complete' THEN kind:='completed';reservation:=(data->>'reservation_id')::uuid;
 ELSE RAISE EXCEPTION '588 unknown probe operation'; END IF;
 INSERT INTO tutor_item_supply_shared_review_probe_events(action_key,preparation_id,job_id,generation_artifact_id,review_receipt_id,reservation_id,event_kind,frame_json,payload_json)
 VALUES(frame->>'action_key',pid,(frame->'lease'->>'job_id')::uuid,(frame->>'artifact_id')::uuid,(frame->>'review_receipt_id')::uuid,reservation,kind,frame,data);
 RETURN CASE WHEN kind='completed' THEN jsonb_build_object('state','completed','result',data) ELSE jsonb_build_object('state',kind) END;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.require_private_incremental_coverage(b jsonb,u uuid,e bigint,scope uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE saved tutor_item_supply_private_incremental_events%ROWTYPE;
BEGIN
 SELECT * INTO saved FROM tutor_item_supply_private_incremental_events x
  WHERE x.user_id=u AND x.epoch=e AND x.scope_id=scope AND x.kind='coverage'
   AND x.action_key=item_supply_internal.snapshot_hash(b) AND x.payload_json->'data'->'coverage'=b FOR SHARE;
 IF saved.id IS NULL THEN RAISE EXCEPTION '588 actual PRIVATE coverage receipt required'; END IF;
 PERFORM item_supply_internal.assert_private_incremental_coverage(saved.payload_json->'frame',b);
END $$;

-- Separate NEW confidential solve DATA. Legacy ephemeral DTOs are never stored.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_blind_solve_data (
 id uuid PRIMARY KEY,logical_action_hash text NOT NULL UNIQUE,
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id),
 job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id),
 review_reservation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_reservations(id),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=262144),
 data_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON tutor_item_supply_shared_blind_solve_data FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_blind_solve_data()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE start_row tutor_item_supply_shared_incremental_role_events%ROWTYPE; p jsonb:=NEW.payload_json;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE; retention timestamptz;
BEGIN
 SELECT * INTO start_row FROM tutor_item_supply_shared_incremental_role_events
  WHERE logical_action_hash=NEW.logical_action_hash AND event_kind='started' AND role='blind' FOR SHARE;
 IF start_row.id IS NULL THEN RAISE EXCEPTION '588 actual blind action start required'; END IF;
 PERFORM item_supply_internal.assert_incremental_shared_current(start_row.payload_json->'lease',NEW.generation_artifact_id);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id FOR SHARE;
 SELECT min(LEAST(policy.retention_until,capture.retention_until)) INTO retention
  FROM jsonb_array_elements(a.request_json->'materials') m,LATERAL jsonb_array_elements(m->'binding'->'evidence') e
  JOIN rag_source_reviews review ON review.id=(e->>'source_review_id')::uuid
  JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
  JOIN rag_registered_source_captures capture ON capture.id=review.registered_capture_id;
 IF start_row.generation_artifact_id IS DISTINCT FROM NEW.generation_artifact_id OR start_row.job_id IS DISTINCT FROM NEW.job_id
  OR start_row.review_reservation_id IS DISTINCT FROM NEW.review_reservation_id
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events e WHERE e.id=start_row.id AND e.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_incremental_role_events e WHERE e.logical_action_hash=NEW.logical_action_hash AND e.event_kind='committed')
  OR p->>'schema_version' IS DISTINCT FROM 'shared_confidential_blind_solve_data_v1'
  OR p->>'data_id' IS DISTINCT FROM NEW.id::text OR p->>'artifact_id' IS DISTINCT FROM a.id::text
  OR p->>'logical_action_hash' IS DISTINCT FROM NEW.logical_action_hash OR p->'binding' IS DISTINCT FROM start_row.payload_json->'binding'
  OR p->>'visibility' IS DISTINCT FROM 'shared_confidential' OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
  OR p->>'input_hash' IS DISTINCT FROM start_row.input_hash OR p->'run'->>'input_hash' IS DISTINCT FROM start_row.input_hash
  OR p->'run'->'provider_identity' IS DISTINCT FROM start_row.payload_json->'provider_identity'
  OR p->'run'->>'profile_hash' IS DISTINCT FROM p->'binding'->>'profile_hash'
  OR p->'run'->>'output_hash' IS DISTINCT FROM p->>'output_hash'
  OR p->>'output_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('answer',p->'answer'))
  OR p->>'answer_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'answer')
  OR jsonb_typeof(p->'answer') IS DISTINCT FROM 'string' OR length(p->>'answer') NOT BETWEEN 1 AND 48000
  OR retention IS NULL OR (p->>'valid_until')::timestamptz>retention OR (p->>'valid_until')::timestamptz<=clock_timestamp() THEN
  RAISE EXCEPTION '588 confidential blind DATA must bind original predispatch actual answer and retention'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS shared_blind_solve_data_insert ON tutor_item_supply_shared_blind_solve_data;
CREATE TRIGGER shared_blind_solve_data_insert BEFORE INSERT ON tutor_item_supply_shared_blind_solve_data
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_blind_solve_data();
DROP TRIGGER IF EXISTS shared_blind_solve_data_immutable ON tutor_item_supply_shared_blind_solve_data;
CREATE TRIGGER shared_blind_solve_data_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_blind_solve_data
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_blind_applicability(b jsonb,artifact uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE saved tutor_item_supply_shared_incremental_role_events%ROWTYPE;
 data_row tutor_item_supply_shared_blind_solve_data%ROWTYPE; a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 original jsonb; score jsonb; target jsonb:=item_supply_internal.incremental_binding(b);
BEGIN
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=artifact FOR SHARE;
 SELECT * INTO saved FROM tutor_item_supply_shared_incremental_role_events e WHERE e.generation_artifact_id=artifact
  AND e.role='blind_score' AND e.event_kind='committed'
  AND e.payload_json->'result'->'receipt'=CASE WHEN b->>'schema_version'='item_supply_committed_blind_applicability_v1' THEN b->'original_blind' ELSE b END
  AND e.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
 IF saved.id IS NULL THEN RAISE EXCEPTION '588 committed current score required'; END IF;
 SELECT * INTO data_row FROM tutor_item_supply_shared_blind_solve_data WHERE id=(saved.payload_json->'result'->'blind_solve_data'->>'data_id')::uuid
  AND data_hash=saved.payload_json->'result'->'blind_solve_data'->>'data_hash' FOR SHARE;
 original:=item_supply_internal.incremental_blind_original(b);score:=item_supply_internal.incremental_blind_score(b);
 IF data_row.id IS NULL OR (data_row.payload_json->>'valid_until')::timestamptz<=clock_timestamp()
  OR data_row.payload_json->'run' IS DISTINCT FROM original->'run' OR data_row.payload_json->>'answer_hash' IS DISTINCT FROM original->>'solution_hash'
  OR target->>'source_hash' IS DISTINCT FROM a.source_hash OR target->>'content_hash' IS DISTINCT FROM a.content_hash
  OR target->>'candidate_key' IS DISTINCT FROM a.item_id::text OR target->>'version_key' IS DISTINCT FROM a.version_id::text THEN
  RAISE EXCEPTION '588 authentic retained original solve and current child score required'; END IF;
 IF b->>'schema_version'='item_supply_committed_blind_applicability_v1' THEN
  IF b->>'logical_action_hash' IS DISTINCT FROM saved.logical_action_hash
   OR (item_supply_internal.incremental_binding(b->'original_blind')-'profile_hash') IS DISTINCT FROM (target-'profile_hash')
   OR b->'original_subject'->'source' IS DISTINCT FROM a.source_json THEN
   RAISE EXCEPTION '588 same logical blind action cannot rebind content'; END IF;
 ELSIF b->>'schema_version'='item_supply_blind_rescore_applicability_v1' THEN
  IF ((b->'original_subject'->'source'->'public')-'version') IS DISTINCT FROM ((a.source_json->'public')-'version')
   OR b->'score'->>'receipt_hash'=original->'score'->>'receipt_hash' THEN
   RAISE EXCEPTION '588 actual old public solve DATA needs distinct current score'; END IF;
 END IF;
END $$;


CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_review_adjudication_preparations (
 id uuid PRIMARY KEY,root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id),
 job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id),
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id),
 reservation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_reservations(id),
 previous_investigation_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_review_investigation_receipts(id),
 probe_receipt_id uuid NOT NULL,action_hash text NOT NULL UNIQUE,payload_json jsonb NOT NULL,valid_until timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_review_adjudication_events (
 id uuid PRIMARY KEY,preparation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_review_adjudication_preparations(id),
 action_hash text NOT NULL,event_kind text NOT NULL CHECK(event_kind IN ('started','committed')),
 payload_json jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(action_hash,event_kind)
);
REVOKE ALL ON tutor_item_supply_shared_review_adjudication_preparations,tutor_item_supply_shared_review_adjudication_events FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_review_adjudication(p jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE request jsonb:=p->'request';input jsonb:=p->'request_payload';original jsonb:=request->'original_input';
 rr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; previous tutor_item_supply_shared_review_investigation_receipts%ROWTYPE;
 probe tutor_item_supply_shared_review_probe_events%ROWTYPE;a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 reserve tutor_item_supply_shared_reservations%ROWTYPE;bound jsonb;k text;v jsonb;
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
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_review_adjudication()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE prep tutor_item_supply_shared_review_adjudication_preparations%ROWTYPE;
 started tutor_item_supply_shared_review_adjudication_events%ROWTYPE; usage tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 p jsonb:=NEW.payload_json;request jsonb;report jsonb;disposition jsonb;reference jsonb;i integer:=0;
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
   AND usage_state='unknown' AND xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  report:=p->'report';
  IF started.id IS NULL OR started.preparation_id IS DISTINCT FROM prep.id OR usage.id IS NULL
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_adjudication_events e WHERE e.id=started.id AND e.xmin::text::bigint=txid_current()%4294967296)
   OR p->>'schema_version' IS DISTINCT FROM 'native_shared_review_adjudication_receipt_v1'
   OR p->>'preparation_id' IS DISTINCT FROM prep.id::text OR p->>'request_hash' IS DISTINCT FROM prep.payload_json->>'request_hash'
   OR p->>'report_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(report)
   OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'historical_findings_changed' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION '588 adjudication actual committed original start and settlement required'; END IF;
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
END $$;
DROP TRIGGER IF EXISTS shared_review_adjudication_prepare ON tutor_item_supply_shared_review_adjudication_preparations;
CREATE TRIGGER shared_review_adjudication_prepare BEFORE INSERT ON tutor_item_supply_shared_review_adjudication_preparations
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_review_adjudication();
DROP TRIGGER IF EXISTS shared_review_adjudication_event ON tutor_item_supply_shared_review_adjudication_events;
CREATE TRIGGER shared_review_adjudication_event BEFORE INSERT ON tutor_item_supply_shared_review_adjudication_events
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_review_adjudication();
DROP TRIGGER IF EXISTS shared_review_adjudication_prepare_immutable ON tutor_item_supply_shared_review_adjudication_preparations;
CREATE TRIGGER shared_review_adjudication_prepare_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_review_adjudication_preparations
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
DROP TRIGGER IF EXISTS shared_review_adjudication_event_immutable ON tutor_item_supply_shared_review_adjudication_events;
CREATE TRIGGER shared_review_adjudication_event_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_review_adjudication_events
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

-- Owner-only confidential receivers; no PUBLIC execute or table access.
DO $acl588$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace ns ON ns.oid=p.pronamespace
 WHERE ns.nspname='item_supply_internal' AND p.proname=ANY(ARRAY['assert_incremental_direct_revision','assert_incremental_local_diff','assert_incremental_shared_current','assert_normal_committed_review_frame','assert_normal_revision_readmission','assert_private_incremental_blind_rescore','assert_private_incremental_coverage','assert_private_incremental_frame','assert_shared_blind_applicability','assert_shared_incremental_coverage','assert_shared_review_adjudication','assert_shared_review_probe_frame','enforce_development_execution_batch_caps_insert','enforce_native_revision_insert','enforce_private_incremental_event','enforce_revision_recheck_insert','enforce_shared_blind_solve_data','enforce_shared_incremental_coverage','enforce_shared_incremental_role_event','enforce_shared_review_adjudication','enforce_shared_review_investigation_insert','enforce_shared_review_probe_event','incremental_binding','incremental_blind_original','incremental_blind_score','incremental_changed_paths','incremental_material_failure','incremental_primary_dependency','incremental_reports','incremental_shared_source_current','persist_shared_incremental_coverage','private_native_incremental_evidence_v1','purge_private_incremental_on_epoch_advance','require_private_incremental_coverage','require_shared_incremental_coverage','revision_recheck_disputes','shared_evaluation_policy_matches','shared_review_probe_event_v1']::text[]) LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f.signature);
 END LOOP;
END $acl588$;
REVOKE ALL ON tutor_item_supply_shared_incremental_role_events,tutor_item_supply_shared_incremental_coverages,tutor_item_supply_development_execution_batch_caps FROM PUBLIC;

-- Lexical extraction only, never an execution/syntax/admission assertion. Match
-- the original owner's first complete SELECT/WITH statement, not a substring.
CREATE OR REPLACE FUNCTION item_supply_internal.original_review_counterexample_statement(counterexample text)
RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE statement text:=regexp_replace(counterexample,'^\s+','');
 i integer:=1; size integer; depth integer:=0; state text:='plain'; ch text; following text;
BEGIN
 IF counterexample IS NULL OR length(counterexample) NOT BETWEEN 1 AND 48000
  OR statement !~* '^(SELECT|WITH)\M' THEN
  RAISE EXCEPTION '588 probe requires initial complete original SELECT/WITH statement'; END IF;
 IF statement ~* '^WITH\M' AND statement !~* '^WITH\s+(RECURSIVE\s+)?([A-Za-z_]\w*|"(""|[^"])+")\s*(\([^;]*\)\s*)?AS\s+((NOT\s+)?MATERIALIZED\s*)?\(' THEN
  RAISE EXCEPTION '588 unsupported original CTE statement'; END IF;
 size:=length(statement);
 WHILE i<=size LOOP
  ch:=substr(statement,i,1);following:=substr(statement,i+1,1);
  IF state IN ('single','double','backtick') THEN
   IF (state='single' AND ch='''') OR (state='double' AND ch='"') OR (state='backtick' AND ch='`') THEN
    IF following=ch THEN i:=i+1; ELSE state:='plain'; END IF;
   END IF;
  ELSIF state='bracket' THEN
   IF ch=']' THEN state:='plain'; END IF;
  ELSIF state='line_comment' THEN
   IF ch=chr(10) THEN state:='plain'; END IF;
  ELSIF state='block_comment' THEN
   IF ch='*' AND following='/' THEN state:='plain';i:=i+1;END IF;
  ELSE
   IF ch='''' THEN state:='single';
   ELSIF ch='"' THEN state:='double';
   ELSIF ch='`' THEN state:='backtick';
   ELSIF ch='[' THEN state:='bracket';
   ELSIF ch='-' AND following='-' THEN state:='line_comment';i:=i+1;
   ELSIF ch='/' AND following='*' THEN state:='block_comment';i:=i+1;
   ELSIF ch='(' THEN depth:=depth+1;
   ELSIF ch=')' THEN
    depth:=depth-1;IF depth<0 THEN RAISE EXCEPTION '588 unbalanced original counterexample';END IF;
   ELSIF ch=';' THEN
    IF depth<>0 OR substr(statement,i+1) ~* '\m(SELECT|WITH)\M' THEN
     RAISE EXCEPTION '588 partial nested or ambiguous multiple original statements denied'; END IF;
    RETURN substr(statement,1,i);
   END IF;
  END IF;
  i:=i+1;
 END LOOP;
 RAISE EXCEPTION '588 incomplete original counterexample statement denied';
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.original_review_counterexample_statement(text) FROM PUBLIC;

ALTER TABLE tutor_item_supply_private_native_quality_evidence
 DROP CONSTRAINT IF EXISTS tutor_item_supply_private_native_quality_evidence_kind_check;
ALTER TABLE tutor_item_supply_private_native_quality_evidence
 ADD CONSTRAINT tutor_item_supply_private_native_quality_evidence_kind_check
 CHECK(kind IN ('validation','blind','review','admission','relation','investigation','normal','blind_data'));
CREATE UNIQUE INDEX IF NOT EXISTS private_confidential_blind_original_capture
 ON tutor_item_supply_private_native_quality_evidence(user_id,epoch,scope_id,pack_task_id,slot_id,root_id,(payload_json->>'review_id'))
 WHERE kind='blind_data';
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_confidential_blind_capture()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=NEW.payload_json;done tutor_item_supply_private_incremental_events%ROWTYPE;
BEGIN
 IF NEW.kind<>'blind_data' THEN RETURN NEW; END IF;
 SELECT * INTO done FROM tutor_item_supply_private_incremental_events e WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch
  AND e.scope_id=NEW.scope_id AND e.pack_task_id=NEW.pack_task_id AND e.slot_id=NEW.slot_id AND e.root_id=NEW.root_id
  AND e.generation_artifact_id=(p->>'artifact_id')::uuid AND e.kind='committed' AND e.action_key='blind'
  AND e.payload_json->'data'->'result'=p->'blind' AND e.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
 IF done.id IS NULL OR p->>'schema_version' IS DISTINCT FROM 'private_native_confidential_blind_data_v1'
  OR p->'ref' IS DISTINCT FROM done.payload_json->'frame'->'ref'
  OR p->>'review_id' IS DISTINCT FROM done.payload_json->'frame'->>'review_id'
  OR p->'subject' IS DISTINCT FROM done.payload_json->'frame'->'subject'
  OR NEW.version_id::text IS DISTINCT FROM p->'subject'->'binding'->>'version_key'
  OR p->>'answer_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'answer')
  OR p->>'answer_hash' IS DISTINCT FROM p->'blind'->>'solution_hash'
  OR p->'blind'->'run'->>'output_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('answer',p->'answer'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'review_id')::uuid AND q.kind='review') THEN
  RAISE EXCEPTION '588 PRIVATE confined actual solve capture cannot backfill historical reports'; END IF;
 PERFORM item_supply_internal.assert_private_incremental_frame(done.payload_json->'frame');
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS a001_private_confidential_blind_capture ON tutor_item_supply_private_native_quality_evidence;
CREATE TRIGGER a001_private_confidential_blind_capture BEFORE INSERT ON tutor_item_supply_private_native_quality_evidence
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_confidential_blind_capture();
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_confidential_blind_capture() FROM PUBLIC;

-- A new decision over immutable same-version DATA is not a fabricated child or
-- a rewritten review. The historical UNIQUE(review_receipt_id) remains enforced
-- for every legacy facts row; only the explicit adjudicated successor is separate.
ALTER TABLE tutor_item_supply_shared_admission_facts DROP CONSTRAINT IF EXISTS tutor_item_supply_shared_admission_facts_review_receipt_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS shared_legacy_facts_review_once ON tutor_item_supply_shared_admission_facts(review_receipt_id)
 WHERE payload_json->>'schema_version'<>'issued_shared_admission_facts_v2';
CREATE UNIQUE INDEX IF NOT EXISTS shared_adjudicated_facts_once ON tutor_item_supply_shared_admission_facts((payload_json->>'adjudication_receipt_id'))
 WHERE payload_json->>'schema_version'='issued_shared_admission_facts_v2';
CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_adjudicated_facts(n tutor_item_supply_shared_admission_facts)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.shared_adjudicated_evaluation_matches(n jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE f tutor_item_supply_shared_admission_facts%ROWTYPE;
BEGIN
 IF n->>'artifact_kind'<>'admission_evaluation' THEN RETURN false; END IF;
 SELECT * INTO f FROM tutor_item_supply_shared_admission_facts WHERE job_id=(n->>'job_id')::uuid
  AND generation_artifact_id=(n->>'generation_artifact_id')::uuid AND payload_json->>'schema_version'='issued_shared_admission_facts_v2'
  AND payload_json->'evaluation'=n->'payload_json' FOR SHARE;
 IF f.id IS NULL THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_shared_adjudicated_facts(f);
 RETURN f.lease_owner=n->>'lease_owner' AND f.lease_generation::text=n->>'lease_generation'
  AND f.lease_state_version::text=n->>'lease_state_version' AND f.continuation_binding_hash=n->>'continuation_binding_hash';
END $$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('public.enforce_item_supply_shared_admission_facts()')),'missing') NOT IN ('93a806a714bf7c0bf65a683e89eef03f6a3460ca204cf2913fc5eceaa12ce17f','5df0e1524e586ec186e5b23d3bdf9925d9035948187633a20b287c8fe1dc091b') THEN RAISE EXCEPTION '588 original shared facts receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_admission_facts() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body588$
DECLARE p jsonb:=NEW.payload_json; a public.tutor_item_supply_shared_generation_artifacts%ROWTYPE; c record; prep record; v record; b record; r record;
  usage record; reservation record; budget jsonb; snapshot jsonb; t timestamptz; kind text; rid uuid;
  action jsonb; quality_job uuid:=NEW.job_id; quality_generation integer:=NEW.lease_generation;
  quality_owner text:=NEW.lease_owner; quality_profile text:=NEW.profile_hash; quality_continuation text:=NEW.continuation_binding_hash;
  validation_job uuid;validation_generation integer;validation_owner text;validation_profile text;validation_continuation text;
  validation_app record;
BEGIN
  IF NEW.payload_json->>'schema_version'='issued_shared_admission_facts_v2' THEN
    PERFORM item_supply_internal.assert_shared_adjudicated_facts(NEW);RETURN NEW;
  END IF;
  action:=item_supply_internal.committed_child_admission_for_job(NEW.job_id);
  IF action IS NOT NULL THEN
    IF p->'lease' IS DISTINCT FROM action->'lease' OR NEW.generation_artifact_id::text IS DISTINCT FROM action->>'artifact_id'
      OR NEW.id::text IS DISTINCT FROM action->>'admission_id' OR NEW.continuation_binding_hash IS NOT NULL
      OR p->'ambiguity' IS DISTINCT FROM action->'ambiguity' OR p->'review_budget' IS DISTINCT FROM action->'quality'->'review_budget'
      OR p->'evidence'->'binding' IS DISTINCT FROM action->'quality'->'binding'
      OR item_supply_internal.normal_revision_readmission_matches(NEW.generation_artifact_id,NEW.id,item_supply_internal.snapshot_hash(p)) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='547 exact normal permission and historical quality required'; END IF;
    quality_job:=(action->'quality'->'review_lease'->>'job_id')::uuid;
    quality_generation:=(action->'quality'->'review_lease'->>'generation')::integer;
    quality_owner:=action->'quality'->'review_lease'->>'lease_owner';
    quality_profile:=action->'quality'->'binding'->>'profile_hash';
    quality_continuation:=action->'quality'->>'historical_continuation_hash';
  END IF;
  validation_job:=quality_job;validation_generation:=quality_generation;validation_owner:=quality_owner;
  validation_profile:=quality_profile;validation_continuation:=quality_continuation;
  IF p ? 'validation_applicability_id' OR p ? 'validation_applicability_hash' THEN
   IF action IS NOT NULL OR NOT (p ?& ARRAY['validation_applicability_id','validation_applicability_hash'])
    OR item_supply_internal.shared_validation_inherited_receipt_matches(NEW.job_id,NEW.generation_artifact_id,NEW.validation_receipt_id) IS DISTINCT FROM true THEN
    RAISE EXCEPTION '588 resumed facts require explicit current original validation applicability pair'; END IF;
   SELECT * INTO validation_app FROM tutor_item_supply_shared_validation_applicabilities x WHERE x.job_id=NEW.job_id
    AND x.generation_artifact_id=NEW.generation_artifact_id AND x.original_receipt_id=NEW.validation_receipt_id
    AND x.id::text=p->>'validation_applicability_id' AND x.applicability_hash=p->>'validation_applicability_hash' FOR SHARE;
   IF validation_app.id IS NULL THEN RAISE EXCEPTION '588 exact issued validation applicability row and hash required'; END IF;
   PERFORM item_supply_internal.assert_shared_validation_applicability(validation_app.payload_json);
   IF validation_app.payload_json->'lease' IS DISTINCT FROM p->'lease'
    OR (p->>'valid_until')::timestamptz>(validation_app.payload_json->>'valid_until')::timestamptz
    OR validation_app.payload_json->>'preparation_id' IS DISTINCT FROM NEW.validation_preparation_id::text THEN
    RAISE EXCEPTION '588 exact original validation DATA applicability must match new facts'; END IF;
   validation_job:=(validation_app.payload_json->'producer_lease'->>'job_id')::uuid;
   validation_generation:=(validation_app.payload_json->'producer_lease'->>'generation')::integer;
   validation_owner:=validation_app.payload_json->'producer_lease'->>'lease_owner';
   validation_profile:=validation_app.payload_json->'producer_lease'->'profile'->>'profile_hash';
   SELECT x.continuation_binding_hash INTO validation_continuation FROM tutor_item_supply_shared_pipeline_receipts x WHERE x.id=NEW.validation_receipt_id;
  END IF;
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared facts B1d only';
  END IF;
  SELECT co.*,j.root_id,pr.profile_hash INTO c FROM tutor_item_supply_shared_job_controls co
    JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id
    JOIN tutor_item_supply_parameter_profiles pr ON pr.id=co.profile_id
    WHERE co.job_id=NEW.job_id FOR SHARE OF co;
  t:=clock_timestamp();
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared facts current job missing'; END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.profile_hash<>NEW.profile_hash
    OR c.lease_owner IS DISTINCT FROM NEW.lease_owner OR c.lease_generation<>NEW.lease_generation
    OR c.state_version<>NEW.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR p->'lease'->'profile' IS DISTINCT FROM snapshot
    OR (p->>'checked_at')::timestamptz>t OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz)
    OR (p->>'checked_at')::timestamptz>=(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts current lease expired or mismatched';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id OR a.item_id<>NEW.item_id OR a.version_id<>NEW.version_id
    OR a.source_hash<>NEW.source_hash OR a.content_hash<>NEW.content_hash
    OR (CASE WHEN action IS NOT NULL THEN NEW.generation_artifact_id::text=action->>'artifact_id'
      ELSE item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,
      NEW.generation_artifact_id,NEW.continuation_binding_hash) END) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared facts original generation/adoption mismatch';
  END IF;
  IF p->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v1'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->>'receipt_id' IS DISTINCT FROM NEW.id::text OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text
    OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text OR p->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR p->>'item_id' IS DISTINCT FROM NEW.item_id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
    OR p->>'continuation_binding_hash' IS DISTINCT FROM NEW.continuation_binding_hash
    OR p->'lease'->>'visibility' IS DISTINCT FROM 'public' OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
    OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
    OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
    OR p->>'target_id' IS DISTINCT FROM a.target_id OR p->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR a.target_id NOT IN ('python-state-update-v1','sqlite-predicate-order-v1','python-kc-binding-v1')
    OR p->'evidence'->'binding'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'evidence'->'binding'->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR p->'evidence'->'binding'->>'candidate_key' IS DISTINCT FROM NEW.item_id::text
    OR p->'evidence'->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
    OR p->'evidence'->'binding'->>'profile_hash' IS DISTINCT FROM quality_profile
    OR p->'evaluation'->'binding' IS DISTINCT FROM p->'evidence'->'binding'
    OR p->'evaluation'->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'evidence') THEN
    RAISE check_violation USING MESSAGE='shared facts payload identity mismatch';
  END IF;
  SELECT * INTO prep FROM tutor_item_supply_shared_validation_preparations WHERE id=NEW.validation_preparation_id;
  IF NOT FOUND OR prep.job_id<>validation_job OR prep.lease_generation<>validation_generation
    OR prep.generation_artifact_id<>a.id OR prep.profile_hash<>validation_profile
    OR p->>'validation_preparation_id' IS DISTINCT FROM prep.id::text
    OR p->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'spec')
    OR p->>'inputs_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'inputs')
    OR p->>'public_task_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'public_task_hash'
    OR p->>'instance_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'instance_hash'
    OR p->>'scorer_version' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'scorer_version'
    OR p->>'runtime_profile_hash' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'runtime_profile_hash' THEN
    RAISE check_violation USING MESSAGE='shared facts finite preparation mismatch';
  END IF;
  FOR kind,rid IN SELECT * FROM (VALUES ('validation',NEW.validation_receipt_id),
      ('blind_solve',NEW.blind_receipt_id),('review_bundle',NEW.review_receipt_id)) AS stages(kind,rid) LOOP
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO r
      FROM tutor_item_supply_shared_pipeline_receipts s WHERE s.id=rid;
    IF NOT FOUND OR r.same_transaction OR r.job_id<>(CASE WHEN kind='validation' THEN validation_job ELSE quality_job END)
      OR r.lease_generation<>(CASE WHEN kind='validation' THEN validation_generation ELSE quality_generation END)
      OR r.lease_owner<>(CASE WHEN kind='validation' THEN validation_owner ELSE quality_owner END) OR r.generation_artifact_id<>a.id OR r.mode<>'live'
      OR r.item_id<>NEW.item_id OR r.version_id<>NEW.version_id OR r.source_hash<>NEW.source_hash OR r.content_hash<>NEW.content_hash
      OR r.artifact_kind<>kind OR r.continuation_binding_hash IS DISTINCT FROM (CASE WHEN kind='validation' THEN validation_continuation ELSE quality_continuation END) THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed exact stages required';
    END IF;
    IF kind='validation' THEN
      v:=r;
      IF p->>'validation_receipt_id' IS DISTINCT FROM r.id::text OR p->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR p->'evidence'->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts validation receipt mismatch';
      END IF;
    ELSIF kind='blind_solve' THEN
      b:=r;
      IF p->>'blind_receipt_id' IS DISTINCT FROM r.id::text OR p->>'blind_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts blind receipt mismatch';
      END IF;
    ELSE
      IF p->>'review_receipt_id' IS DISTINCT FROM r.id::text OR p->>'review_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR r.payload_json->'blind_solve' IS DISTINCT FROM b.payload_json THEN
        RAISE check_violation USING MESSAGE='shared facts review receipt mismatch';
      END IF;
    END IF;
  END LOOP;
  FOR kind,budget IN SELECT * FROM (VALUES ('validation',p->'validation_budget'),('review',p->'review_budget')) AS budgets(kind,budget) LOOP
    IF kind='validation' AND a.target_id='python-kc-binding-v1' THEN
      IF budget IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='static facts have no execution budget'; END IF;
      CONTINUE;
    END IF;
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=(budget->>'reservation_id')::uuid;
    IF NOT FOUND OR reservation.job_id<>(CASE WHEN kind='validation' THEN validation_job ELSE quality_job END) OR reservation.root_id<>NEW.root_id
      OR reservation.lease_generation<>(CASE WHEN kind='validation' THEN validation_generation ELSE quality_generation END) OR reservation.reservation_key IS DISTINCT FROM budget->>'settlement_key'
      OR reservation.reservation_key<>(CASE WHEN kind='review' THEN 'review.'||replace(a.id::text,'-','') ELSE prep.reservation_key END) THEN
      RAISE check_violation USING MESSAGE='shared facts reservation identity mismatch';
    END IF;
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO usage
      FROM tutor_item_supply_shared_runtime_settlements s WHERE s.id=(budget->>'settlement_id')::uuid;
    IF NOT FOUND OR usage.same_transaction OR usage.reservation_id<>reservation.id
      OR usage.settlement_key<>reservation.reservation_key OR usage.usage_state IS DISTINCT FROM budget->>'usage_state'
      OR usage.receipt_hash IS DISTINCT FROM budget->>'receipt_hash'
      OR usage.usage_state<>(CASE WHEN kind='review' THEN 'unknown' ELSE 'known' END) THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed usage required';
    END IF;
    IF kind='review' AND (budget->'actual' IS DISTINCT FROM 'null'::jsonb OR budget->'receipt_hash' IS DISTINCT FROM 'null'::jsonb) THEN
      RAISE check_violation USING MESSAGE='unknown provider usage cannot become zero';
    END IF;
  END LOOP;
  IF p->'ambiguity'->'plan'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'ambiguity'->'plan'->>'specification_hash' IS DISTINCT FROM p->>'specification_hash'
    OR p->'ambiguity'->'plan'->>'inputs_hash' IS DISTINCT FROM p->>'inputs_hash'
    OR (p->'ambiguity'->>'parent_deadline_at')::timestamptz<(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts finite interpretation mismatch';
  END IF;
  IF a.target_id='python-kc-binding-v1' THEN
    IF p->'validation_terminals' IS DISTINCT FROM '[]'::jsonb OR p->'blind_terminals' IS DISTINCT FROM '[]'::jsonb
      OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'static_options'
      OR p->'evidence'->'runner_available' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_isolated' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_receipt_hash' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE check_violation USING MESSAGE='static facts cannot claim OS execution';
    END IF;
  ELSIF jsonb_array_length(p->'validation_terminals') NOT BETWEEN 1 AND 32
    OR jsonb_array_length(p->'blind_terminals')<>1 OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'sealed_pair'
    OR p->'evidence'->>'execution_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(v.payload_json->'execution_evidence') THEN
    RAISE check_violation USING MESSAGE='runtime facts original terminal projection missing';
  END IF;
  IF p->'target_proof'<>'null'::jsonb AND (p->'target_proof'->>'claim_scope' IS DISTINCT FROM 'per_item_registered_target_not_inventory'
    OR p->'target_proof'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'target_proof'->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR p->'evidence'->>'coverage_proof_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'target_proof')) THEN
    RAISE check_violation USING MESSAGE='shared facts per-item proof mismatch';
  END IF;
  SELECT * INTO r FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.review_receipt_id;
  IF item_supply_internal.shared_evaluation_policy_matches(a::tutor_item_supply_shared_generation_artifacts,p->'evaluation',r.payload_json) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared facts exact frozen policy/warning mismatch';
  END IF;
  RETURN NEW;
END $body588$;

-- Current PRIVATE direct-author preparation, using original immutable instructions.
CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_direct_preparation(task uuid,job uuid,reservation uuid,p jsonb,deadline timestamptz)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r jsonb:=p->'ref'; parent tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 a tutor_item_supply_private_generation_artifacts%ROWTYPE; instruction tutor_item_supply_private_incremental_events%ROWTYPE;
 origin jsonb; id text; paths jsonb; texts text[]:='{}'; behavior text;
BEGIN
 SELECT * INTO parent FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'parent_review_id')::uuid
  AND q.user_id=(r->>'user_id')::uuid AND q.epoch=(r->>'epoch')::bigint AND q.scope_id=(r->>'scope_id')::uuid
  AND q.pack_task_id=task AND q.slot_id=(r->>'slot_id')::uuid AND q.root_id=(r->>'root_id')::uuid
  AND q.kind='review' AND q.version_id=(p->>'parent_version_id')::uuid AND q.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_private_generation_artifacts g WHERE g.id=(parent.payload_json->>'artifact_id')::uuid
  AND g.user_id=(r->>'user_id')::uuid AND g.epoch=(r->>'epoch')::bigint AND g.scope_id=(r->>'scope_id')::uuid FOR SHARE;
 IF parent.id IS NULL OR a.id IS NULL OR p->'lease'->>'job_id' IS DISTINCT FROM job::text
  OR r->>'pack_task_id' IS DISTINCT FROM task::text OR r->>'parent_version_id' IS DISTINCT FROM parent.version_id::text
  OR jsonb_typeof(p->'instruction_ids') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'instruction_ids') NOT BETWEEN 1 AND 6
  OR (SELECT count(DISTINCT x) FROM jsonb_array_elements_text(p->'instruction_ids') x)<>jsonb_array_length(p->'instruction_ids')
  OR parent.payload_json->'spec'->>'target_id' IS DISTINCT FROM 'python-kc-binding-v1'
  OR a.source_json->'public'->>'kind' IS DISTINCT FROM 'knowledge_check'
  OR p->'request'->>'item_key' IS DISTINCT FROM a.request_json->>'item_key'
  OR p->'request'->'blueprint' IS DISTINCT FROM a.request_json->'blueprint'
  OR p->'request'->'materials' IS DISTINCT FROM a.request_json->'materials'
  OR p->'request'->>'version'=a.request_json->>'version'
  OR p->'request'->'profile' IS DISTINCT FROM p->'lease'->'profile' THEN
  RAISE EXCEPTION '588 PRIVATE direct original same static item preparation required'; END IF;
 FOR id IN SELECT jsonb_array_elements_text(p->'instruction_ids') LOOP
  SELECT * INTO instruction FROM tutor_item_supply_private_incremental_events e WHERE e.id=id::uuid
   AND e.user_id=parent.user_id AND e.epoch=parent.epoch AND e.scope_id=parent.scope_id
   AND e.pack_task_id=parent.pack_task_id AND e.slot_id=parent.slot_id AND e.root_id=parent.root_id
   AND e.generation_artifact_id=a.id AND e.kind='instruction'
   AND e.payload_json->'frame'->>'parent_review_id'=parent.id::text
   AND e.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  IF instruction.id IS NULL THEN RAISE EXCEPTION '588 PRIVATE original prior TOP instruction required'; END IF;
  origin:=instruction.payload_json->'frame';
  PERFORM item_supply_internal.assert_private_incremental_frame(jsonb_set(jsonb_set(origin,'{lease}',p->'lease'),'{ref}',r));
  FOR behavior IN SELECT jsonb_array_elements_text(instruction.payload_json->'data'->'instruction'->'expected_behaviors') LOOP
   texts:=array_append(texts,behavior);
  END LOOP;
 END LOOP;
 SELECT jsonb_agg(DISTINCT path ORDER BY path) INTO paths FROM tutor_item_supply_private_incremental_events e,
  LATERAL jsonb_array_elements_text(e.payload_json->'data'->'instruction'->'allowed_paths') path
  WHERE p->'instruction_ids' @> jsonb_build_array(e.id::text) AND e.kind='instruction';
 IF paths IS DISTINCT FROM p->'allowed_paths'
  OR item_supply_internal.snapshot_hash(to_jsonb(array_to_string(texts,E'\n'))) IS DISTINCT FROM p->>'directive_hash' THEN
  RAISE EXCEPTION '588 PRIVATE author exact authenticated path scope and directive required'; END IF;
END $$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.private_pack_prepare_auxiliary(uuid,uuid,uuid,uuid,jsonb,timestamp with time zone)')),'missing') NOT IN ('175703160e35c6789525fd7017238ff6e304d0f052f21e963ecbc30a9765f202','0f4141d2275d188bab9ed508f3bfc246c0b02e09ebb46c84c2191905684c52dd') THEN
  RAISE EXCEPTION '588 original private_pack_prepare_auxiliary changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.private_pack_prepare_auxiliary(task uuid, preparation uuid, job uuid, reservation uuid, payload jsonb, deadline timestamp with time zone)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE t record;ph record;b record;stamp timestamptz;
BEGIN
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task AND record_kind='task' FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 original PRIVATE task required'; END IF;
 PERFORM item_supply_internal.private_native_epoch(t.user_id,t.epoch);
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=task AND record_kind='phase'
  AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=job::text;
 IF ph.id IS NULL OR item_supply_internal.private_pack_slot_current(task,(ph.payload_json->>'slot_id')::uuid,
  (ph.payload_json->>'business_item_id')::uuid,(ph.payload_json->>'root_id')::uuid,t.user_id,t.epoch,t.scope_id,job) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 current PRIVATE phase required'; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_reservations WHERE id=reservation AND user_id=t.user_id AND epoch=t.epoch AND job_id=job FOR SHARE;
 stamp:=clock_timestamp();
 IF b.id IS NULL OR jsonb_typeof(payload) IS DISTINCT FROM 'object' OR octet_length(payload::text)>4194304
  OR deadline<=stamp OR deadline>(ph.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='524 original finite reservation/deadline required'; END IF;
 IF payload->>'schema_version'='private_native_direct_revision_phase_v1' THEN
  PERFORM item_supply_internal.assert_private_direct_preparation(task,job,reservation,payload,deadline);
 END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal
  (id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(preparation,task,t.user_id,t.epoch,t.scope_id,'private_attachment','private.aux.'||preparation::text,t.intent_hash,
  jsonb_build_object('schema_version','private_native_auxiliary_v1','job_id',job,'reservation_id',reservation,'request',payload,'valid_until',deadline));
END $function$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_private_native_quality_insert()')),'missing') NOT IN ('9552d64c69a87b268e451edab877b1fcf1bf10de8808fab4060dc329256a97e1','2ef24a7eabd40f0625287091d3ab5708a88d3c4df09d2ced94fdbeb1fdea85d1') THEN
  RAISE EXCEPTION '588 original enforce_private_native_quality_insert changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_quality_insert()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE ph record;v record;a record;p jsonb:=NEW.payload_json;ref jsonb;b jsonb;rr jsonb;effective boolean:=false;stage record;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal
  WHERE pack_task_id=NEW.pack_task_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1'
  AND payload_json->>'job_id'=NEW.job_id::text;
 ref:=ph.payload_json->'ref';
 IF ph.id IS NULL OR ref->>'slot_id' IS DISTINCT FROM NEW.slot_id::text OR ref->>'root_id' IS DISTINCT FROM NEW.root_id::text
  OR item_supply_internal.private_pack_slot_current(NEW.pack_task_id,NEW.slot_id,(ref->>'business_item_id')::uuid,
   NEW.root_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality requires current original private fixed-slot phase'; END IF;
 SELECT g.* INTO a FROM tutor_item_supply_private_generation_artifacts g JOIN tutor_item_supply_private_jobs j
  ON j.id=g.job_id AND j.user_id=g.user_id AND j.epoch=g.epoch
  WHERE g.version_id=NEW.version_id AND g.user_id=NEW.user_id AND g.epoch=NEW.epoch
  AND g.scope_id=NEW.scope_id AND j.root_id=NEW.root_id;
 -- Source locks BEFORE the existing private-version bank lock. Even direct SQL
 -- may not invert the original C/source→bank order on a native path.
 IF a.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',ref,'request',a.request_json,'source_receipts',a.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality current source before bank required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_versions WHERE id=NEW.version_id AND user_id=NEW.user_id
  AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR SHARE;
 IF v.id IS NULL OR a.id IS NULL OR a.mode IS DISTINCT FROM 'live' OR a.source_json->'public' IS DISTINCT FROM v.public_json
  OR a.source_json->'private' IS DISTINCT FROM v.private_json OR a.version_id IS DISTINCT FROM v.id OR a.candidate_id IS DISTINCT FROM v.candidate_id THEN
  RAISE check_violation USING MESSAGE='524 actual original private generation/version required'; END IF;
 IF NEW.kind='validation' THEN
  IF p->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2'
   OR p->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR p->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash' THEN
   RAISE check_violation USING MESSAGE='524 original candidate validation required'; END IF;
 ELSIF NEW.kind='blind' THEN
  IF item_supply_internal.incremental_binding(p)->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR item_supply_internal.incremental_binding(p)->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR item_supply_internal.incremental_binding(p)->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR item_supply_internal.incremental_blind_original(p)->'run'->'provider_identity'->>'identity' IS NULL THEN
   RAISE check_violation USING MESSAGE='524 original bound blind run required'; END IF;
 ELSIF NEW.kind IN('review','admission') THEN
  IF p->'ref' IS DISTINCT FROM ref OR ((p->'lease') - 'state_version'::text) IS DISTINCT FROM ((ph.payload_json->'lease') - 'state_version'::text) THEN
   RAISE check_violation USING MESSAGE='524 PRIVATE review/ref/lease binding required'; END IF;
  b:=p->'bundle';effective:=b->>'schema_version'='item_supply_review_coverage_v1';
  IF effective THEN PERFORM item_supply_internal.require_private_incremental_coverage(b,NEW.user_id,NEW.epoch,NEW.scope_id); END IF;
  IF b->>'mode' IS DISTINCT FROM 'peer_blind' OR b->>'state' IS DISTINCT FROM 'completed'
   OR b->>'publication_enabled' IS DISTINCT FROM 'false' OR jsonb_array_length(item_supply_internal.incremental_reports(b)) IS DISTINCT FROM 6
   OR b->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR b->'binding'->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR b->'binding'->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR (SELECT count(DISTINCT r->>'role') FROM jsonb_array_elements(item_supply_internal.incremental_reports(b)) r)<>6
   OR (SELECT array_agg(r->>'role' ORDER BY r->>'role') FROM jsonb_array_elements(item_supply_internal.incremental_reports(b)) r)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
   OR (SELECT count(DISTINCT r->'run'->'provider_identity'->>'identity') FROM jsonb_array_elements(item_supply_internal.incremental_reports(b)) r)<>6
   OR (SELECT count(DISTINCT r->'run'->>'run_id') FROM jsonb_array_elements(item_supply_internal.incremental_reports(b)) r)<>6 THEN
   RAISE check_violation USING MESSAGE='524 full independent six-peer bundle required'; END IF;
  FOR rr IN SELECT value FROM jsonb_array_elements(item_supply_internal.incremental_reports(b)) LOOP
   IF (NOT effective AND rr->'binding' IS DISTINCT FROM b->'binding')
    OR rr->'run'->'provider_identity'->>'identity' IN(b->>'author_identity',item_supply_internal.incremental_blind_original(b->'blind_solve')->'run'->'provider_identity'->>'identity')
    OR rr->'run'->>'run_id'=item_supply_internal.incremental_blind_original(b->'blind_solve')->'run'->>'run_id' THEN
    RAISE check_violation USING MESSAGE='524 peer/author/blind independence required'; END IF;
  END LOOP;
  IF NEW.kind='admission' THEN
   IF p->>'schema_version' IS DISTINCT FROM 'private_native_quality_v1' OR p->>'receipt_id' IS DISTINCT FROM NEW.id::text
    OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text
    OR p->'source'->'public' IS DISTINCT FROM a.source_json->'public' OR p->'source'->'private' IS DISTINCT FROM a.source_json->'private'
    OR p->'request' IS DISTINCT FROM a.request_json OR p->'source_receipts' IS DISTINCT FROM a.receipt_json->'sources'
    OR p->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR p->'evaluation'->>'publication_enabled' IS DISTINCT FROM 'false'
    OR p->'evaluation'->'binding' IS DISTINCT FROM b->'binding' OR p->'evidence'->'binding' IS DISTINCT FROM b->'binding'
    OR item_supply_internal.private_native_source_current(p) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='524 original private full-risk/current-source admission required'; END IF;
   FOR stage IN SELECT * FROM (VALUES ('validation',p->>'validation_receipt_id',p->'validation'),
    ('blind',p->>'blind_receipt_id',b->'blind_solve')) x(kind,id,payload) LOOP
    PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=stage.id::uuid
     AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id AND q.pack_task_id=NEW.pack_task_id
     AND q.slot_id=NEW.slot_id AND q.version_id=NEW.version_id AND q.kind=stage.kind AND q.payload_json=stage.payload
     AND q.xmin::text::bigint<>(txid_current()%4294967296);
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 committed exact private validation/blind required'; END IF;
   END LOOP;
   PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'review_receipt_id')::uuid
    AND q.kind='review' AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id
    AND q.pack_task_id=NEW.pack_task_id AND q.slot_id=NEW.slot_id AND q.version_id=NEW.version_id
    AND q.payload_json->'bundle'=b AND q.payload_json->'spec'=p->'spec' AND q.payload_json->'ambiguity'=p->'ambiguity'
    AND q.xmin::text::bigint<>(txid_current()%4294967296);
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 committed exact private six-peer review required'; END IF;
   IF ref->>'parent_version_id' IS NOT NULL THEN
    PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'normal_readmission_id')::uuid
     AND q.kind='normal' AND q.version_id=NEW.version_id AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch
     AND q.scope_id=NEW.scope_id AND q.pack_task_id=NEW.pack_task_id AND q.slot_id=NEW.slot_id
     AND q.payload_json->>'parent_version_id'=ref->>'parent_version_id'
     AND q.payload_json->>'child_artifact_id'=p->>'generation_artifact_id'
     AND q.payload_json->>'validation_id'=p->>'validation_receipt_id'
     AND q.payload_json->>'blind_id'=p->>'blind_receipt_id' AND q.payload_json->>'review_id'=p->>'review_receipt_id'
     AND q.payload_json->'evaluation'=p->'evaluation' AND q.payload_json->'evidence'=p->'evidence'
     AND q.payload_json->'machine_hashes'=p->'machine_hashes'
     AND q.payload_json->>'clause_proof_hash'=p->>'clause_proof_hash';
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 independent PRIVATE normal child re-admission required'; END IF;
   ELSIF p->>'normal_readmission_id' IS NOT NULL THEN
    RAISE check_violation USING MESSAGE='524 PRIVATE normal cannot relabel initial version'; END IF;
  END IF;
 ELSIF NEW.kind IN('investigation','normal','relation') THEN
  IF p->'ref' IS DISTINCT FROM ref THEN RAISE check_violation USING MESSAGE='524 private auxiliary exact ref required'; END IF;
  -- Dedicated type-specific receipts must be issued only after a committed
  -- original reservation and bounded PRIVATE phase, not JSON capability restore.
  IF NEW.kind='investigation' THEN PERFORM item_supply_internal.assert_private_native_investigation(NEW); END IF;
  IF NEW.kind='normal' THEN PERFORM item_supply_internal.assert_private_native_normal(NEW); END IF;
  IF NEW.kind='relation' THEN PERFORM item_supply_internal.assert_private_native_relation(NEW); END IF;
 END IF;
 IF NEW.kind IN('blind','review') THEN PERFORM item_supply_internal.assert_private_native_review_stage(NEW); END IF;
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',a.request_json,
  'source_receipts',a.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality source stale after native bank wait'; END IF;
 stamp:=clock_timestamp();
 IF NEW.checked_at>stamp OR NEW.valid_until<=stamp
  OR (NEW.kind<>'relation' AND NEW.valid_until>(ph.payload_json->>'valid_until')::timestamptz)
  OR (NEW.kind='relation' AND NEW.valid_until>NEW.checked_at+interval '7 days') THEN
  RAISE check_violation USING MESSAGE='524 quality stale after lock wait'; END IF;
 RETURN NEW;
END $function$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_private_native_review_stage(tutor_item_supply_private_native_quality_evidence)')),'missing') NOT IN ('b4b914a87823d4419ed0a4f20b25dad31a3fc11a859cab06a4eb0d9ec21002d8','cb5beaaae05635b030420f341e185f47d3d9875c2fc3c3f189a2db61a67defc5') THEN
  RAISE EXCEPTION '588 original assert_private_native_review_stage changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_review_stage(n tutor_item_supply_private_native_quality_evidence)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE aux record;r record;s record;g record;binding jsonb;request jsonb;
BEGIN
 binding:=CASE WHEN n.kind='blind' THEN item_supply_internal.incremental_binding(n.payload_json) ELSE n.payload_json->'bundle'->'binding' END;
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=n.pack_task_id AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND payload_json->>'job_id'=n.job_id::text AND payload_json->'request'->>'schema_version'='private_native_review_phase_v1'
  AND payload_json->'request'->'binding'=binding AND xmin::text::bigint<>(txid_current()%4294967296);
 request:=aux.payload_json->'request';
 SELECT * INTO r FROM tutor_item_supply_private_reservations WHERE id=(aux.payload_json->>'reservation_id')::uuid
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND root_id=n.root_id AND job_id=n.job_id;
 SELECT * INTO s FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=r.id AND user_id=n.user_id AND epoch=n.epoch
  AND settlement_key='private.native.review.'||replace(aux.id::text,'-','') AND usage_state='unknown' AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO g FROM tutor_item_supply_private_generation_artifacts WHERE id=(request->>'artifact_id')::uuid AND version_id=n.version_id
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id;
 IF aux.id IS NULL OR r.id IS NULL OR s.id IS NULL OR g.id IS NULL OR r.requests<>7
  OR (binding->>'version_key',binding->>'candidate_key',binding->>'source_hash',binding->>'content_hash',binding->>'policy_hash',binding->>'profile_hash') IS DISTINCT FROM
    (n.version_id::text,g.candidate_id::text,g.receipt_json->>'source_hash',g.receipt_json->>'content_hash',
     item_supply_internal.snapshot_hash(request->'policy'),request->'lease'->'profile'->>'profile_hash')
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence v WHERE v.kind='validation' AND v.version_id=n.version_id AND v.user_id=n.user_id AND v.epoch=n.epoch AND v.scope_id=n.scope_id AND v.pack_task_id=n.pack_task_id AND v.slot_id=n.slot_id AND v.job_id=n.job_id AND v.payload_json=request->'validation' AND v.xmin::text::bigint<>(txid_current()%4294967296)) THEN
  RAISE check_violation USING MESSAGE='524 review/blind need committed exact original7 preparation validation settlement'; END IF;
 IF n.kind='review' AND (n.id<>aux.id OR n.payload_json->>'reservation_id' IS DISTINCT FROM r.id::text
  OR n.payload_json->'policy' IS DISTINCT FROM request->'policy' OR n.payload_json->'spec' IS DISTINCT FROM request->'spec'
  OR n.payload_json->>'artifact_id' IS DISTINCT FROM g.id::text) THEN
  RAISE check_violation USING MESSAGE='524 review issued actual original preparation required'; END IF;
END $function$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_private_native_publication_insert()')),'missing') NOT IN ('06f877d61c5ff4ca8f4d04e53217c5f54695cfd5890e615ed660b7330263a380','95003c873681cc7a6f3b72e966b1be82471616c489eb2199f419bd06ed1c7871') THEN
  RAISE EXCEPTION '588 original enforce_private_native_publication_insert changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_publication_insert()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE q record;v record;prev record;p jsonb:=NEW.payload_json;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=NEW.quality_id AND kind='admission'
  AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND pack_task_id=NEW.pack_task_id
  AND slot_id=NEW.slot_id AND root_id=NEW.root_id AND version_id=NEW.version_id;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 exact private original admission required'; END IF;
 IF q.payload_json->'bundle'->>'schema_version'='item_supply_review_coverage_v1' THEN
  PERFORM item_supply_internal.require_private_incremental_coverage(q.payload_json->'bundle',NEW.user_id,NEW.epoch,NEW.scope_id);
 END IF;
 IF NEW.state='published' AND item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 PRIVATE source before bank required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_versions WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR UPDATE;
 SELECT * INTO prev FROM tutor_item_supply_private_native_publications WHERE version_id=NEW.version_id
  AND user_id=NEW.user_id AND epoch=NEW.epoch ORDER BY state_version DESC LIMIT 1;
 IF prev.id IS NULL THEN
  IF NEW.state IS DISTINCT FROM 'published' OR NEW.state_version<>1 OR NEW.predecessor_id IS NOT NULL
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_publication_v1' OR p->>'publication_id' IS DISTINCT FROM NEW.id::text
   OR p->>'quality_id' IS DISTINCT FROM q.id::text OR p->>'quality_hash' IS DISTINCT FROM q.payload_hash
   OR p->'ref' IS DISTINCT FROM q.payload_json->'ref' OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
   OR p->>'item_handle' IS DISTINCT FROM ('lip:v2:'||v.id::text) OR p->>'exercise_version_id' IS DISTINCT FROM NEW.exercise_version_id::text
   OR p->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(q.payload_json->'source')
   OR p->>'content_hash' IS DISTINCT FROM q.payload_json->'bundle'->'binding'->>'content_hash'
   OR NEW.content_json->>'item_handle' IS DISTINCT FROM ('lip:v2:'||v.id::text)
   OR NEW.content_json->>'version_id' IS DISTINCT FROM NEW.version_id::text
   OR NEW.content_json->>'content_hash' IS DISTINCT FROM p->>'content_hash'
   OR NEW.content_json->>'actual_public_task_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(v.public_json)
   OR NEW.content_json->>'actual_fixture_hash' IS DISTINCT FROM q.payload_json->'ambiguity'->'plan'->>'instance_hash'
   OR split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2) NOT IN('trace','diagnose','repair','counterexample')
   OR NEW.content_json->>'decision_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'domain','decision','semantics',jsonb_build_object('version','native-finite-semantic-v1','profile','kc',
       'decision',split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2))))
   OR NEW.content_json->>'answer_leakage_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'domain','contextual-solution','semantics',jsonb_build_object('version','native-finite-semantic-v1','profile','kc',
       'decision',split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2))))
   OR NEW.content_json->>'author_id' IS DISTINCT FROM item_supply_internal.native_type_actor(q.payload_json->'bundle'->>'author_identity')::text
   OR v.public_json IS DISTINCT FROM q.payload_json->'source'->'public' OR v.private_json IS DISTINCT FROM q.payload_json->'source'->'private'
   OR item_supply_internal.private_pack_slot_current(NEW.pack_task_id,NEW.slot_id,
    (q.payload_json->'ref'->>'business_item_id')::uuid,NEW.root_id,NEW.user_id,NEW.epoch,NEW.scope_id,q.job_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='524 exact live original private publication required'; END IF;
  PERFORM 1 FROM tutor_exercise_versions x JOIN tutor_exercise_private_rubrics r ON r.exercise_version_id=x.id
   WHERE x.id=NEW.exercise_version_id AND x.source_kind='registered_author'
   AND x.content_hash=p->>'exercise_content_hash' AND r.rubric_hash=p->>'rubric_hash'
   AND x.exercise_key=q.payload_json->'source'->'public'->>'item_key'
   AND x.version=q.payload_json->'source'->'public'->>'version';
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 actual original private materialization required'; END IF;
  stamp:=clock_timestamp();
  IF (p->>'checked_at')::timestamptz>stamp OR stamp>=q.valid_until
   OR (p->>'producer_valid_until')::timestamptz IS DISTINCT FROM q.valid_until
   OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='524 private publication stale after wait'; END IF;
 ELSE
  IF NEW.state NOT IN('quarantined','retired') OR prev.state<>'published' OR NEW.state_version<>prev.state_version+1
   OR NEW.predecessor_id IS DISTINCT FROM prev.id OR NEW.quality_id IS DISTINCT FROM prev.quality_id
   OR NEW.payload_json IS DISTINCT FROM prev.payload_json OR NEW.exercise_version_id IS DISTINCT FROM prev.exercise_version_id
   OR NEW.content_json IS DISTINCT FROM prev.content_json THEN
   RAISE check_violation USING MESSAGE='524 immutable private publication terminal CAS required'; END IF;
 END IF;
 RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_incremental_normal(n tutor_item_supply_private_native_quality_evidence)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body588$
DECLARE p jsonb:=n.payload_json;aux record;prep jsonb;parent_review record;parent_artifact record;
 child record;v record;br record;peer record;j record;cv record;pv record;stamp timestamptz;binding jsonb;ev jsonb;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(n.user_id,n.epoch);
 IF n.kind IS DISTINCT FROM 'normal' OR p->>'schema_version' IS DISTINCT FROM 'private_native_incremental_readmission_v1'
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','instruction_ids','allowed_paths','coverage_hash',
   'revision_preparation_id','revision_request_hash','child_artifact_id','child_artifact_hash','parent_version_id','parent_review_id','parent_review_hash',
   'parent_substantive_hash','child_substantive_hash','validation_id','validation_hash','blind_id','blind_hash',
   'review_id','review_hash','policy','evidence','machine_hashes','clause_proof_hash','evaluation','source_hash','content_hash']) IS DISTINCT FROM true
  OR EXISTS(SELECT 1 FROM jsonb_each(p) x WHERE x.value='null'::jsonb)
  OR p->>'parent_version_id' IS DISTINCT FROM p->'ref'->>'parent_version_id'
  OR p->>'parent_version_id'=n.version_id::text
  OR (SELECT count(DISTINCT x) FROM unnest(ARRAY[p->>'validation_id',p->>'blind_id',p->>'review_id',p->>'parent_review_id']) x)<>4
  OR jsonb_array_length(p->'machine_hashes') NOT BETWEEN 1 AND 16 THEN
  RAISE EXCEPTION '588 direct PRIVATE normal exact complete nonnull chain required'; END IF;
 SELECT * INTO parent_review FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'parent_review_id')::uuid
  AND q.kind='review' AND q.user_id=n.user_id AND q.epoch=n.epoch AND q.scope_id=n.scope_id
  AND q.pack_task_id=n.pack_task_id AND q.slot_id=n.slot_id AND q.root_id=n.root_id
  AND q.version_id=(p->>'parent_version_id')::uuid AND q.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal q WHERE q.id=(p->>'revision_preparation_id')::uuid
  AND q.pack_task_id=n.pack_task_id AND q.user_id=n.user_id AND q.epoch=n.epoch AND q.scope_id=n.scope_id
  AND q.record_kind='private_attachment' AND q.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND q.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
 prep:=aux.payload_json->'request';
 IF parent_review.id IS NULL OR aux.id IS NULL OR parent_review.payload_hash IS DISTINCT FROM p->>'parent_review_hash'
  OR parent_review.payload_json->'spec'->>'target_id' IS DISTINCT FROM 'python-kc-binding-v1'
  OR prep->>'schema_version' IS DISTINCT FROM 'private_native_direct_revision_phase_v1'
  OR prep->'ref' IS DISTINCT FROM p->'ref' OR prep->>'parent_review_id' IS DISTINCT FROM parent_review.id::text
  OR prep->'instruction_ids' IS DISTINCT FROM p->'instruction_ids' OR prep->'allowed_paths' IS DISTINCT FROM p->'allowed_paths' THEN
  RAISE EXCEPTION '588 direct PRIVATE actual original prior TOP revision preparation required'; END IF;
 SELECT * INTO child FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'child_artifact_id')::uuid
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND version_id=n.version_id
  AND mode='live' AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO parent_artifact FROM tutor_item_supply_private_generation_artifacts
  WHERE id=(parent_review.payload_json->>'artifact_id')::uuid AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id
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
 PERFORM item_supply_internal.require_private_incremental_coverage(peer.payload_json->'bundle',n.user_id,n.epoch,n.scope_id);
 PERFORM item_supply_internal.assert_incremental_local_diff(parent_artifact.source_json,child.source_json,p->'allowed_paths');
 IF p->>'coverage_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(peer.payload_json->'bundle')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(item_supply_internal.incremental_reports(peer.payload_json->'bundle')) report
    WHERE item_supply_internal.incremental_material_failure(report))
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(ev->'probes') x WHERE x->'passed' IS DISTINCT FROM 'true') THEN
  RAISE EXCEPTION '588 PRIVATE child complete effective quality cannot mask unresolved findings'; END IF;
 -- Preparation deadline was consumed by the original writer at child creation;
 -- old producer expiry alone does NOT revoke historically lawful new content.
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',p->'ref','request',child.request_json,
  'source_receipts',child.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 fresh source authorization for PRIVATE normal required'; END IF;
 stamp:=clock_timestamp();
 IF n.checked_at>stamp OR stamp>=n.valid_until THEN RAISE check_violation USING MESSAGE='524 normal stale after source/receipt waits'; END IF;
END $body588$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_private_native_normal(tutor_item_supply_private_native_quality_evidence)')),'missing') NOT IN ('8b10d051605ff18865b26ec3d7afea0ec6c23e3279aba645cc2366e8b281ac82','e8ce712d411e0ac7e5a6aa3660f9046b249b8b9f684aa4b5f608b081a9fe63ac') THEN RAISE EXCEPTION '588 original private normal receiver changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_normal(n tutor_item_supply_private_native_quality_evidence)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE p jsonb:=n.payload_json;invest record;aux record;prep jsonb;parent_review record;parent_artifact record;
 child record;v record;br record;peer record;j record;cv record;pv record;stamp timestamptz;binding jsonb;ev jsonb;r1 jsonb;
BEGIN
 IF p->>'schema_version'='private_native_incremental_readmission_v1' THEN
  PERFORM item_supply_internal.assert_private_incremental_normal(n); RETURN;
 END IF;
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
END $function$;

-- Import original immutable machine DATA using authenticated new same-version
-- facts/current authority. This projection grants no IO and rewrites no old lease.
CREATE OR REPLACE FUNCTION item_supply_internal.shared_adjudicated_import_action(lease jsonb,artifact uuid,validation uuid,evidence uuid,specification text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE f tutor_item_supply_shared_admission_facts%ROWTYPE; old_validation tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 prep tutor_item_supply_shared_validation_preparations%ROWTYPE; actual tutor_item_supply_shared_validation_evidence%ROWTYPE;
BEGIN
 SELECT * INTO f FROM tutor_item_supply_shared_admission_facts x WHERE x.generation_artifact_id=artifact
  AND x.payload_json->>'schema_version'='issued_shared_admission_facts_v2' AND x.payload_json->'lease'=lease
  AND x.validation_receipt_id=validation AND x.payload_json->'evaluation'->>'disposition'='eligible_internal'
  AND x.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
 IF f.id IS NULL THEN
  SELECT * INTO f FROM tutor_item_supply_shared_admission_facts x WHERE x.generation_artifact_id=artifact
   AND x.payload_json->>'schema_version'='issued_shared_admission_facts_v1' AND x.payload_json->'lease'=lease
   AND x.validation_receipt_id=validation AND x.payload_json->'evaluation'->>'disposition'='eligible_internal'
   AND x.xmin::text::bigint<>txid_current()%4294967296
   AND item_supply_internal.shared_validation_inherited_receipt_matches(x.job_id,artifact,validation)
   AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_validation_applicabilities app WHERE app.job_id=x.job_id
    AND app.generation_artifact_id=artifact AND app.original_receipt_id=validation
    AND app.id::text=x.payload_json->>'validation_applicability_id'
    AND app.applicability_hash=x.payload_json->>'validation_applicability_hash') FOR SHARE;
  IF f.id IS NULL THEN RETURN NULL; END IF;
  PERFORM item_supply_internal.assert_incremental_shared_current(lease,artifact);
 ELSE
  PERFORM item_supply_internal.assert_shared_adjudicated_facts(f);
 END IF;
 SELECT * INTO old_validation FROM tutor_item_supply_shared_pipeline_receipts WHERE id=validation FOR SHARE;
 SELECT * INTO prep FROM tutor_item_supply_shared_validation_preparations WHERE id=f.validation_preparation_id FOR SHARE;
 SELECT * INTO actual FROM tutor_item_supply_shared_validation_evidence WHERE id=evidence AND preparation_id=prep.id FOR SHARE;
 IF prep.id IS NULL OR actual.id IS NULL OR actual.payload_json->'validation' IS DISTINCT FROM old_validation.payload_json
  OR f.payload_json->>'specification_hash' IS DISTINCT FROM specification
  OR item_supply_internal.snapshot_hash(prep.payload_json->'spec') IS DISTINCT FROM specification THEN
  RAISE EXCEPTION '588 same-version import exact original machine evidence required'; END IF;
 RETURN jsonb_build_object('lease',lease,'artifact_id',artifact,'quality',jsonb_build_object(
  'validation_receipt_id',validation,'validation_evidence_id',evidence,'specification_hash',specification,
  'validation_lease',prep.payload_json->'lease'));
END $$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('enforce_learning_item_native_validation_import()')),'missing') NOT IN ('262346250b49d1dd49b073175d0162738aa8c9fd85d0bb7dfdea10b5d4784e68','c54b5ca1c95016aea64320c4fc401878cd11563daf78f7f5b4742d72f36dcb63') THEN RAISE EXCEPTION '588 original enforce_learning_item_native_validation_import changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION public.enforce_learning_item_native_validation_import()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE r record; p record; e record; a record; v record; c record; j record;
  lease jsonb:=NEW.native_import_lease_json; snapshot jsonb; scope jsonb; terminal jsonb;
  action jsonb; quality_profile jsonb; current_job uuid;
BEGIN
  IF NEW.schema_version='learning_item_validation_v1' THEN RETURN NEW; END IF;
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NEW.schema_version<>'candidate_validation_v2' THEN
    RAISE check_violation USING MESSAGE='native bank import is B1d V2 only';
  END IF;
  action:=item_supply_internal.committed_child_admission_for_job((lease->>'job_id')::uuid);
  IF action IS NULL THEN
   action:=item_supply_internal.shared_adjudicated_import_action(lease,NEW.native_generation_artifact_id,
    NEW.native_validation_receipt_id,NEW.native_validation_evidence_id,NEW.native_specification_hash);
  END IF;
  quality_profile:=lease->'profile';
  IF action IS NOT NULL THEN
    IF lease IS DISTINCT FROM action->'lease' OR NEW.native_generation_artifact_id::text IS DISTINCT FROM action->>'artifact_id'
     OR NEW.native_validation_receipt_id::text IS DISTINCT FROM action->'quality'->>'validation_receipt_id'
     OR NEW.native_validation_evidence_id::text IS DISTINCT FROM action->'quality'->>'validation_evidence_id'
     OR NEW.native_specification_hash IS DISTINCT FROM action->'quality'->>'specification_hash' THEN
      RAISE check_violation USING MESSAGE='547 original committed validation and fresh import capability required'; END IF;
    quality_profile:=action->'quality'->'validation_lease'->'profile';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO r
    FROM tutor_item_supply_shared_pipeline_receipts x WHERE id=NEW.native_validation_receipt_id;
  IF NOT FOUND OR r.same_transaction OR r.artifact_kind<>'validation' OR r.mode<>'live' OR r.publication_enabled
    OR r.schema_version<>'candidate_validation_v2' OR r.payload_json IS DISTINCT FROM NEW.receipt_json
    OR r.receipt_hash IS DISTINCT FROM NEW.receipt_hash OR r.version_id IS DISTINCT FROM NEW.version_id
    OR r.content_hash IS DISTINCT FROM NEW.content_hash OR r.generation_artifact_id IS DISTINCT FROM NEW.native_generation_artifact_id
    OR r.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
    OR r.payload_json->>'source_hash' IS DISTINCT FROM r.source_hash
    OR r.payload_json->>'content_hash' IS DISTINCT FROM r.content_hash THEN
    RAISE check_violation USING MESSAGE='native bank requires exact committed shared V2 validation';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO e
    FROM tutor_item_supply_shared_validation_evidence x WHERE id=NEW.native_validation_evidence_id;
  IF NOT FOUND OR e.same_transaction OR e.publication_enabled
    OR e.payload_json->'validation' IS DISTINCT FROM NEW.receipt_json THEN
    RAISE check_violation USING MESSAGE='native bank committed evidence mismatch';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO p
    FROM tutor_item_supply_shared_validation_preparations x WHERE id=e.preparation_id;
  IF NOT FOUND OR p.same_transaction OR p.job_id IS DISTINCT FROM r.job_id OR p.lease_generation IS DISTINCT FROM r.lease_generation
    OR p.generation_artifact_id IS DISTINCT FROM r.generation_artifact_id OR p.item_id IS DISTINCT FROM r.item_id
    OR p.version_id IS DISTINCT FROM r.version_id OR p.source_hash IS DISTINCT FROM r.source_hash
    OR p.content_hash IS DISTINCT FROM r.content_hash OR p.profile_hash IS DISTINCT FROM quality_profile->>'profile_hash'
    OR r.artifact_key IS DISTINCT FROM 'validation.'||replace(p.id::text,'-','')
    OR NEW.native_specification_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(p.payload_json->'spec')
    OR p.payload_json->'inputs'->>'specification_hash' IS DISTINCT FROM NEW.native_specification_hash THEN
    RAISE check_violation USING MESSAGE='native bank exact finite preparation required';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=r.generation_artifact_id;
  SELECT * INTO v FROM tutor_learning_item_versions WHERE id=NEW.version_id;
  IF a.id IS NULL OR v.id IS NULL OR a.item_id IS DISTINCT FROM v.item_id OR a.version_id IS DISTINCT FROM v.id
    OR a.source_hash IS DISTINCT FROM v.source_hash OR a.content_hash IS DISTINCT FROM v.content_hash
    OR NEW.item_handle IS DISTINCT FROM v.handle
    OR v.public_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'public')
    OR v.private_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'private')
    OR v.blueprint_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'blueprint')
    OR p.payload_json->'request' IS DISTINCT FROM a.request_json
    OR p.payload_json->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR a.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
    OR v.creator_identity IS DISTINCT FROM 'native.author.'||replace(a.receipt_json->'provider'->>'run_id','-','')
    OR (action IS NULL AND item_supply_internal.shared_stage_original_matches(r.job_id,r.lease_generation,a.id,r.continuation_binding_hash) IS DISTINCT FROM true) THEN
    RAISE check_violation USING MESSAGE='native bank original immutable content mismatch';
  END IF;
  current_job:=CASE WHEN action IS NULL THEN r.job_id ELSE (lease->>'job_id')::uuid END;
  SELECT * INTO j FROM tutor_item_supply_shared_jobs WHERE id=current_job;
  SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=current_job FOR UPDATE;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  IF j.root_id IS DISTINCT FROM a.root_id OR c.job_id IS NULL OR c.state<>'leased'
    OR c.lease_generation IS DISTINCT FROM (CASE WHEN action IS NULL THEN r.lease_generation ELSE (lease->>'generation')::integer END) OR c.lease_expires_at IS NULL
    OR c.lease_expires_at<=clock_timestamp() OR c.parent_deadline<=clock_timestamp()
    OR lease->>'visibility' IS DISTINCT FROM 'public' OR lease->>'job_id' IS DISTINCT FROM current_job::text
    OR lease->>'generation' IS DISTINCT FROM c.lease_generation::text
    OR lease->>'state_version' IS DISTINCT FROM c.state_version::text
    OR lease->>'lease_owner' IS DISTINCT FROM c.lease_owner OR lease->'profile' IS DISTINCT FROM snapshot
    OR p.payload_json->'lease'->'profile' IS DISTINCT FROM quality_profile
    OR (action IS NOT NULL AND p.payload_json->'lease' IS DISTINCT FROM action->'quality'->'validation_lease') THEN
    RAISE check_violation USING MESSAGE='native bank current operation lease required';
  END IF;
  scope:=p.payload_json->'spec'->'coverage_blueprint'->'scope';
  IF a.source_json->'public'->>'kind'='knowledge_check' THEN
    IF NEW.receipt_json->>'mode' IS DISTINCT FROM 'static'
      OR NEW.receipt_json IS DISTINCT FROM p.payload_json->'inputs'->'static_facts'->'validation'
      OR NEW.receipt_json->'execution_evidence' IS DISTINCT FROM 'null'::jsonb
      OR e.reservation_id IS NOT NULL OR e.payload_json->'terminals' IS DISTINCT FROM '[]'::jsonb THEN
      RAISE check_violation USING MESSAGE='native bank actual static proof required';
    END IF;
  ELSE
    IF a.source_json->'public'->>'kind' NOT IN ('code','sql') OR NEW.receipt_json->>'mode' IS DISTINCT FROM 'live'
      OR NEW.receipt_json->'legacy_receipt' IS DISTINCT FROM 'null'::jsonb
      OR NEW.receipt_json->'execution_evidence'->>'mode' IS DISTINCT FROM 'live'
      OR NEW.receipt_json->'execution_evidence'->>'isolation' IS DISTINCT FROM 'approved_os_boundary'
      OR NEW.receipt_json->'execution_evidence'->>'runtime_profile_id' IS DISTINCT FROM v.runtime_profile_key
      OR NEW.receipt_json->'execution_evidence'->>'scorer_version' IS DISTINCT FROM scope->>'scorer_version'
      OR e.reservation_id IS NULL OR jsonb_typeof(e.payload_json->'terminals') IS DISTINCT FROM 'array'
      OR jsonb_array_length(e.payload_json->'terminals')<1 THEN
      RAISE check_violation USING MESSAGE='native bank execution binding required';
    END IF;
    FOR terminal IN SELECT value FROM jsonb_array_elements(e.payload_json->'terminals') LOOP
      IF terminal->>'lock_fingerprint' IS DISTINCT FROM scope->>'runtime_profile_hash'
        OR terminal->>'run_id' IS DISTINCT FROM NEW.receipt_json->'execution_evidence'->>'run_id'
        OR terminal->>'mode' IS DISTINCT FROM 'live' OR terminal->>'isolation' IS DISTINCT FROM 'approved_os_boundary' THEN
        RAISE check_violation USING MESSAGE='native bank stored terminal binding mismatch';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $function$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('enforce_learning_item_native_publication_proof()')),'missing') NOT IN ('2968c704081ddb8f336edb62212d0b06c2c47f3fb084e22992ccba10b8f5ea08','648e7d1d28c0b45efcc5379269650d75f07d55eda853373fbe3fc5fee8d6a7ad') THEN RAISE EXCEPTION '588 original enforce_learning_item_native_publication_proof changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION public.enforce_learning_item_native_publication_proof()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE p jsonb:=NEW.proof_json; f record; e record; g public.tutor_item_supply_shared_generation_artifacts%ROWTYPE; v record; c record; snapshot jsonb; t timestamptz;
  clause_data jsonb; validation_app record;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NEW.publication_txid<>txid_current() THEN
    RAISE check_violation USING MESSAGE='native publication isolated caller transaction required';
  END IF;
  SELECT * INTO f FROM tutor_item_supply_shared_admission_facts WHERE id=NEW.facts_receipt_id FOR SHARE;
  IF f.payload_json->>'schema_version'='issued_shared_admission_facts_v2' THEN
   PERFORM item_supply_internal.assert_shared_adjudicated_facts(f::tutor_item_supply_shared_admission_facts);
  ELSIF f.payload_json ? 'validation_applicability_id' OR f.payload_json ? 'validation_applicability_hash' THEN
   SELECT * INTO validation_app FROM tutor_item_supply_shared_validation_applicabilities app WHERE app.job_id=f.job_id
    AND app.generation_artifact_id=f.generation_artifact_id AND app.original_receipt_id=f.validation_receipt_id
    AND app.id::text=f.payload_json->>'validation_applicability_id'
    AND app.applicability_hash=f.payload_json->>'validation_applicability_hash' FOR SHARE;
   IF validation_app.id IS NULL OR validation_app.payload_json->'lease' IS DISTINCT FROM f.payload_json->'lease' THEN
    RAISE EXCEPTION '588 resumed publication requires exact original issued validation applicability'; END IF;
   PERFORM item_supply_internal.assert_shared_validation_applicability(validation_app.payload_json);
  END IF;
  SELECT * INTO e FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.evaluation_receipt_id FOR SHARE;
  SELECT * INTO g FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  SELECT r.*,v1.handle,v1.content_hash AS version_content_hash,v1.risk_tier INTO v
    FROM tutor_learning_item_validation_receipts r JOIN tutor_learning_item_versions v1 ON v1.id=r.version_id
    WHERE r.id=(p->>'bank_validation_id')::uuid AND r.version_id=NEW.version_id;
  IF f.id IS NULL OR e.id IS NULL OR g.id IS NULL OR v.id IS NULL THEN
    RAISE check_violation USING MESSAGE='native publication typed authority missing';
  END IF;
  IF f.version_id<>NEW.version_id OR f.generation_artifact_id<>g.id OR g.version_id<>NEW.version_id
    OR e.generation_artifact_id<>g.id OR e.job_id<>f.job_id OR e.lease_generation<>f.lease_generation
    OR e.artifact_kind<>'admission_evaluation' OR e.schema_version IS DISTINCT FROM (CASE WHEN item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_admission_evaluation_v3' ELSE 'item_supply_admission_evaluation_v2' END)
    OR e.payload_json IS DISTINCT FROM f.payload_json->'evaluation'
    OR e.payload_json->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR e.payload_json->>'policy_version' IS DISTINCT FROM (CASE WHEN item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'autonomous_evidence_policy_v3' ELSE 'autonomous_evidence_policy_v2' END)
    OR e.payload_json->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR f.payload_json->'target_proof' IS NULL OR f.payload_json->'target_proof'='null'::jsonb
    OR v.schema_version<>'candidate_validation_v2' OR v.passed IS NOT NULL
    OR v.native_generation_artifact_id<>g.id OR v.native_validation_receipt_id<>f.validation_receipt_id
    OR v.receipt_hash IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR v.native_specification_hash IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR e.payload_json->'binding'->>'risk_tier' IS DISTINCT FROM v.risk_tier
    OR p->>'proof_id' IS DISTINCT FROM NEW.id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'item_handle' IS DISTINCT FROM v.handle OR p->>'content_hash' IS DISTINCT FROM v.version_content_hash
    OR p->>'source_hash' IS DISTINCT FROM g.source_hash OR p->>'content_hash' IS DISTINCT FROM g.content_hash
    OR p->>'generation_artifact_id' IS DISTINCT FROM g.id::text
    OR p->>'facts_receipt_id' IS DISTINCT FROM f.id::text OR p->>'facts_hash' IS DISTINCT FROM f.payload_hash
    OR p->>'evaluation_receipt_id' IS DISTINCT FROM e.id::text OR p->>'evaluation_hash' IS DISTINCT FROM e.receipt_hash
    OR p->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f.payload_json->'evidence')
    OR p->>'evidence_hash' IS DISTINCT FROM e.payload_json->>'evidence_hash'
    OR p->>'validation_receipt_id' IS DISTINCT FROM f.validation_receipt_id::text
    OR p->>'validation_hash' IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR p->>'review_receipt_id' IS DISTINCT FROM f.review_receipt_id::text
    OR p->>'review_hash' IS DISTINCT FROM f.payload_json->>'review_receipt_hash'
    OR p->'lease' IS DISTINCT FROM f.payload_json->'lease'
    OR p->>'specification_hash' IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR p->>'target_id' IS DISTINCT FROM g.target_id OR p->>'target_definition_hash' IS DISTINCT FROM g.target_definition_hash
    OR p->'materials' IS DISTINCT FROM g.request_json->'materials'
    OR p->'source_receipts' IS DISTINCT FROM g.receipt_json->'sources'
    OR p->'runtime'->>'runtime_profile_hash' IS DISTINCT FROM f.payload_json->>'runtime_profile_hash'
    OR p->'runtime'->>'scorer_version' IS DISTINCT FROM f.payload_json->>'scorer_version'
    OR p->>'policy_hash' IS DISTINCT FROM e.payload_json->'binding'->>'policy_hash'
    OR p->>'materialization_id' IS DISTINCT FROM NEW.materialization_id::text
    OR p->>'publication_event_id' IS DISTINCT FROM NEW.publication_event_id::text
    OR p->>'runner_material_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.runner_material_json)
    OR p->>'origin' IS DISTINCT FROM 'native_internal_b1d'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'inventory_ready' IS DISTINCT FROM 'false'::jsonb OR p->>'family_independence_status' IS DISTINCT FROM 'pending' THEN
    RAISE check_violation USING MESSAGE='native publication exact V2 provenance mismatch';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('clause_id',m->>'clause_id','clause_hash',m->>'clause_hash',
    'interpretation_hash',m->>'interpretation_hash') ORDER BY n) INTO clause_data
    FROM jsonb_array_elements(f.payload_json->'target_proof'->'mappings') WITH ORDINALITY AS clauses(m,n);
  IF p->'clauses' IS DISTINCT FROM clause_data OR jsonb_array_length(clause_data)<>3 THEN
    RAISE check_violation USING MESSAGE='native publication target clauses missing';
  END IF;
  IF v.risk_tier='high' AND (jsonb_array_length(e.payload_json->'bundle_hashes')<2
      OR jsonb_array_length(f.payload_json->'evidence'->'risk_evidence')=0) THEN
    RAISE check_violation USING MESSAGE='native high risk requires actual V2 adapters and independent bundle';
  END IF;
  IF g.target_id='python-kc-binding-v1' THEN
    IF p->'runtime'->'runtime_lock' IS DISTINCT FROM 'null'::jsonb
      OR p->'runtime'->'runner_version' IS DISTINCT FROM 'null'::jsonb
      OR f.payload_json->'validation_terminals' IS DISTINCT FROM '[]'::jsonb THEN
      RAISE check_violation USING MESSAGE='native static publication cannot claim OS authority';
    END IF;
  ELSIF jsonb_typeof(p->'runtime'->'runtime_lock') IS DISTINCT FROM 'object'
      OR jsonb_array_length(f.payload_json->'validation_terminals')=0 THEN
    RAISE check_violation USING MESSAGE='native runtime publication requires actual sealed evidence';
  END IF;
  SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=f.job_id FOR SHARE;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.id IS NULL OR c.state<>'leased' OR c.lease_owner<>f.lease_owner OR c.lease_generation<>f.lease_generation
    OR c.state_version<>f.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM p->'lease'->'profile' OR (p->>'checked_at')::timestamptz>t
    OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(f.payload_json->>'valid_until')::timestamptz) THEN
    RAISE check_violation USING MESSAGE='native publication current facts/lease expired';
  END IF;
  IF p->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts) THEN
    RAISE check_violation USING MESSAGE='native publication frozen generation policy mismatch';
  END IF;
  RETURN NEW;
END $function$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.deny_revision_admission_without_discharge()')),'missing') NOT IN ('c95c1e10e96c968e4b6377440bcf4fefd23c16271d4640e1940badc8aef10d9b','4c68bcf39443dd453623da828839c5dfce3cfa7767e1e8a658062b5a35faec88') THEN RAISE EXCEPTION '588 original deny_revision_admission_without_discharge changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION item_supply_internal.deny_revision_admission_without_discharge()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE artifact_job uuid; normal_fact uuid; exact_hash text; facts tutor_item_supply_shared_admission_facts%ROWTYPE;
BEGIN
  SELECT a.job_id INTO artifact_job FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=NEW.generation_artifact_id;
  -- Controlled ancestry is unconditionally held BEFORE any normal permission.
  IF artifact_job IS NOT NULL AND item_supply_internal.controlled_counterexample_held(artifact_job) IS DISTINCT FROM false THEN
    RAISE check_violation USING MESSAGE='controlled experiment ancestry held';
  END IF;
  IF artifact_job IS NOT NULL AND item_supply_internal.native_revision_descendant(artifact_job) THEN
    IF TG_TABLE_NAME='tutor_item_supply_shared_admission_facts' THEN
      normal_fact:=NEW.id; exact_hash:=item_supply_internal.snapshot_hash(NEW.payload_json);
    ELSIF TG_TABLE_NAME='tutor_learning_item_native_publication_proofs' THEN
      normal_fact:=NEW.facts_receipt_id;
      SELECT f.payload_hash INTO exact_hash FROM tutor_item_supply_shared_admission_facts f
        WHERE f.id=normal_fact AND f.generation_artifact_id=NEW.generation_artifact_id;
    ELSE
      RAISE check_violation USING MESSAGE='normal readmission unknown receiver';
    END IF;
    SELECT * INTO facts FROM tutor_item_supply_shared_admission_facts f WHERE f.id=normal_fact;
    IF TG_TABLE_NAME='tutor_item_supply_shared_admission_facts' THEN facts:=NEW; END IF;
    IF facts.payload_json->>'schema_version'='issued_shared_admission_facts_v2' THEN
      PERFORM item_supply_internal.assert_shared_adjudicated_facts(facts);
      SELECT f.id,f.payload_hash INTO normal_fact,exact_hash FROM tutor_item_supply_shared_admission_facts f
       WHERE f.id=(facts.payload_json->>'same_version_predecessor_id')::uuid
        AND f.generation_artifact_id=NEW.generation_artifact_id;
    END IF;
    IF item_supply_internal.normal_revision_readmission_matches(NEW.generation_artifact_id,normal_fact,exact_hash) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='revision historical blocker discharge owner pending';
    END IF;
  END IF;
  RETURN NEW;
END $function$;

DO $acl588$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='item_supply_internal' AND p.proname IN (
   'assert_private_direct_preparation','assert_private_incremental_normal','shared_adjudicated_import_action') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f.signature);
 END LOOP;
END $acl588$;

-- Exact original validation DATA applicability for partial-quality cold owners.
-- No synthetic checkpoint, budget settlement, provider capability or old expiry edit.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_validation_applicabilities (
 id uuid PRIMARY KEY,root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id),
 job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id),
 generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id),
 original_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id),
 logical_action_hash text NOT NULL CHECK(logical_action_hash ~ '^[0-9a-f]{64}$'),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
 applicability_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(job_id,generation_artifact_id)
);
REVOKE ALL ON tutor_item_supply_shared_validation_applicabilities FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_validation_applicability(p jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a tutor_item_supply_shared_generation_artifacts%ROWTYPE;v tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 prep tutor_item_supply_shared_validation_preparations%ROWTYPE;e tutor_item_supply_shared_validation_evidence%ROWTYPE;
 usage tutor_item_supply_shared_runtime_settlements%ROWTYPE;provenance jsonb;
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',(p->>'artifact_id')::uuid);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO v FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'validation_receipt_id')::uuid FOR SHARE;
 SELECT * INTO prep FROM tutor_item_supply_shared_validation_preparations WHERE id=(p->>'preparation_id')::uuid FOR SHARE;
 SELECT * INTO e FROM tutor_item_supply_shared_validation_evidence WHERE id=(p->>'evidence_id')::uuid AND preparation_id=prep.id FOR SHARE;
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','applicability_id','root_id','lease','artifact_id','artifact_hash',
  'validation_receipt_id','validation_hash','preparation_id','preparation_hash','evidence_id','evidence_hash',
  'specification_hash','inputs_hash','logical_action_hash','continuation_binding_hash','producer_lease','provenance_hash','valid_until','publication_enabled']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'shared_validation_applicability_v1'
  OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
  OR (p->>'valid_until')::timestamptz<=clock_timestamp()
  OR (p->>'valid_until')::timestamptz>LEAST((p->'lease'->>'expires_at')::timestamptz,
    (p->'lease'->>'parent_deadline')::timestamptz,(p->'lease'->'profile'->>'parent_deadline_at')::timestamptz)
  OR a.id IS NULL OR v.id IS NULL OR prep.id IS NULL OR e.id IS NULL
  OR a.root_id::text IS DISTINCT FROM p->>'root_id' OR a.artifact_hash IS DISTINCT FROM p->>'artifact_hash'
  OR item_supply_internal.shared_continuation_generation_inherited((p->'lease'->>'job_id')::uuid) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations c
    WHERE c.job_id=(p->'lease'->>'job_id')::uuid AND c.generation_artifact_id=a.id AND c.root_id=a.root_id
     AND c.binding_hash=p->>'continuation_binding_hash')
  OR v.artifact_kind IS DISTINCT FROM 'validation' OR v.mode IS DISTINCT FROM 'live' OR v.publication_enabled
  OR v.schema_version IS DISTINCT FROM 'candidate_validation_v2' OR v.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
  OR v.generation_artifact_id IS DISTINCT FROM a.id OR prep.root_id IS DISTINCT FROM a.root_id
  OR (v.item_id,v.version_id,v.source_hash,v.content_hash) IS DISTINCT FROM (a.item_id,a.version_id,a.source_hash,a.content_hash)
  OR v.receipt_hash IS DISTINCT FROM p->>'validation_hash' OR v.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(v.payload_json)
  OR v.artifact_key IS DISTINCT FROM 'validation.'||replace(prep.id::text,'-','')
  OR prep.job_id IS DISTINCT FROM v.job_id OR prep.lease_generation IS DISTINCT FROM v.lease_generation
  OR prep.generation_artifact_id IS DISTINCT FROM a.id OR prep.payload_hash IS DISTINCT FROM p->>'preparation_hash'
  OR prep.source_hash IS DISTINCT FROM a.source_hash OR prep.content_hash IS DISTINCT FROM a.content_hash
  OR prep.payload_json->'request' IS DISTINCT FROM a.request_json OR prep.payload_json->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
  OR item_supply_internal.snapshot_hash(prep.payload_json->'spec') IS DISTINCT FROM p->>'specification_hash'
  OR item_supply_internal.snapshot_hash(prep.payload_json->'inputs') IS DISTINCT FROM p->>'inputs_hash'
  OR prep.payload_json->'inputs'->>'specification_hash' IS DISTINCT FROM p->>'specification_hash'
  OR p->'producer_lease' IS DISTINCT FROM prep.payload_json->'lease'
  OR e.payload_hash IS DISTINCT FROM p->>'evidence_hash' OR e.payload_json->'validation' IS DISTINCT FROM v.payload_json
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts x WHERE x.id=v.id AND x.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_validation_preparations x WHERE x.id=prep.id AND x.xmin::text::bigint=txid_current()%4294967296)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_validation_evidence x WHERE x.id=e.id AND x.xmin::text::bigint=txid_current()%4294967296)
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=v.job_id AND cp.lease_generation=v.lease_generation
    AND cp.stage='validating' AND cp.status='completed' AND cp.receipt_hash=v.receipt_hash AND cp.xmin::text::bigint<>txid_current()%4294967296)
  OR p->>'logical_action_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
    'domain','shared_validation_applicability_action_v1','artifact_id',a.id,'specification_hash',p->>'specification_hash','inputs_hash',p->>'inputs_hash')) THEN
  RAISE EXCEPTION '588 validation applicability requires original committed machine evidence and fresh adopted authority'; END IF;
 IF e.reservation_id IS NOT NULL THEN
  SELECT * INTO usage FROM tutor_item_supply_shared_runtime_settlements u WHERE u.reservation_id=e.reservation_id
   AND u.settlement_key=prep.reservation_key AND u.usage_state='known'
   AND u.receipt_hash=item_supply_internal.snapshot_hash(jsonb_build_object('receipts',e.payload_json->'terminals'))
   AND u.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  IF usage.id IS NULL OR jsonb_array_length(e.payload_json->'terminals') NOT BETWEEN 1 AND 32 THEN
   RAISE EXCEPTION '588 original execution validation must have known actual terminal settlement'; END IF;
 ELSIF a.target_id IS DISTINCT FROM 'python-kc-binding-v1' OR v.payload_json->>'mode' IS DISTINCT FROM 'static'
   OR e.payload_json->'terminals' IS DISTINCT FROM '[]'::jsonb THEN
  RAISE EXCEPTION '588 only actual static KC validation is reservation-free';
 END IF;
 provenance:=jsonb_build_object('validation_receipt_id',v.id,'validation_hash',v.receipt_hash,'preparation_id',prep.id,
  'preparation_hash',prep.payload_hash,'evidence_id',e.id,'evidence_hash',e.payload_hash,'producer_lease',prep.payload_json->'lease');
 IF p->>'provenance_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(provenance) THEN
  RAISE EXCEPTION '588 exact original validation provenance DATA required'; END IF;
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_shared_validation_applicability()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.id::text IS DISTINCT FROM NEW.payload_json->>'applicability_id'
  OR NEW.root_id::text IS DISTINCT FROM NEW.payload_json->>'root_id'
  OR NEW.job_id::text IS DISTINCT FROM NEW.payload_json->'lease'->>'job_id'
  OR NEW.generation_artifact_id::text IS DISTINCT FROM NEW.payload_json->>'artifact_id'
  OR NEW.original_receipt_id::text IS DISTINCT FROM NEW.payload_json->>'validation_receipt_id'
  OR NEW.logical_action_hash IS DISTINCT FROM NEW.payload_json->>'logical_action_hash' THEN
  RAISE EXCEPTION '588 validation applicability exact immutable columns required'; END IF;
 PERFORM item_supply_internal.assert_shared_validation_applicability(NEW.payload_json); RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS shared_validation_applicability_insert ON tutor_item_supply_shared_validation_applicabilities;
CREATE TRIGGER shared_validation_applicability_insert BEFORE INSERT ON tutor_item_supply_shared_validation_applicabilities
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_shared_validation_applicability();
DROP TRIGGER IF EXISTS shared_validation_applicability_immutable ON tutor_item_supply_shared_validation_applicabilities;
CREATE TRIGGER shared_validation_applicability_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_validation_applicabilities
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
CREATE OR REPLACE FUNCTION item_supply_internal.persist_shared_validation_applicability(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE n tutor_item_supply_shared_validation_applicabilities%ROWTYPE;
BEGIN
 PERFORM item_supply_internal.assert_shared_validation_applicability(p);
 SELECT * INTO n FROM tutor_item_supply_shared_validation_applicabilities x
  WHERE x.job_id=(p->'lease'->>'job_id')::uuid AND x.generation_artifact_id=(p->>'artifact_id')::uuid FOR SHARE;
 IF n.id IS NOT NULL THEN
  IF (n.payload_json-'applicability_id') IS DISTINCT FROM (p-'applicability_id') THEN
   RAISE EXCEPTION '588 immutable validation applicability cannot rebind current authority or original DATA'; END IF;
  RETURN to_jsonb(n);
 END IF;
 INSERT INTO tutor_item_supply_shared_validation_applicabilities(id,root_id,job_id,generation_artifact_id,original_receipt_id,logical_action_hash,payload_json)
 VALUES((p->>'applicability_id')::uuid,(p->>'root_id')::uuid,(p->'lease'->>'job_id')::uuid,(p->>'artifact_id')::uuid,
  (p->>'validation_receipt_id')::uuid,p->>'logical_action_hash',p) RETURNING * INTO n;
 RETURN to_jsonb(n);
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.shared_continuation_validation_inherited(operation_job uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT current_database()='aearn_b1d_sandbox_20261001' AND EXISTS(
  SELECT 1 FROM tutor_item_supply_shared_validation_applicabilities x
   JOIN tutor_item_supply_shared_job_controls c ON c.job_id=x.job_id
   JOIN tutor_item_supply_shared_candidate_continuations adoption ON adoption.job_id=x.job_id AND adoption.generation_artifact_id=x.generation_artifact_id
   JOIN tutor_item_supply_shared_generation_artifacts a ON a.id=x.generation_artifact_id
  WHERE x.job_id=operation_job AND c.state='leased' AND c.lease_expires_at>clock_timestamp() AND c.parent_deadline>clock_timestamp()
   AND x.payload_json->'lease'->>'lease_owner'=c.lease_owner
   AND x.payload_json->'lease'->>'generation'=c.lease_generation::text
   AND x.payload_json->'lease'->>'state_version'=c.state_version::text
   AND x.payload_json->'lease'->'profile'=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END
   AND (x.payload_json->>'valid_until')::timestamptz>clock_timestamp()
   AND x.payload_json->>'continuation_binding_hash'=adoption.binding_hash AND x.root_id=adoption.root_id
   AND x.payload_json->>'artifact_hash'=a.artifact_hash AND item_supply_internal.shared_continuation_generation_inherited(operation_job)
   AND item_supply_internal.incremental_shared_source_current(a.request_json)
 );
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.shared_validation_inherited_receipt_matches(operation_job uuid,artifact uuid,receipt uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT item_supply_internal.shared_continuation_validation_inherited(operation_job) AND EXISTS(
  SELECT 1 FROM tutor_item_supply_shared_validation_applicabilities x WHERE x.job_id=operation_job
   AND x.generation_artifact_id=artifact AND x.original_receipt_id=receipt);
$$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_validation_applicability(jsonb),
 item_supply_internal.enforce_shared_validation_applicability(),item_supply_internal.persist_shared_validation_applicability(jsonb),
 item_supply_internal.shared_continuation_validation_inherited(uuid),
 item_supply_internal.shared_validation_inherited_receipt_matches(uuid,uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_shared_committed_same_child_coverage(p jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE b jsonb:=p->'coverage';subject jsonb:=p->'target_subject';a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 app tutor_item_supply_shared_validation_applicabilities%ROWTYPE;prep tutor_item_supply_shared_validation_preparations%ROWTYPE;
 validation tutor_item_supply_shared_pipeline_receipts%ROWTYPE;done tutor_item_supply_shared_incremental_role_events%ROWTYPE;
 scope_row tutor_item_supply_shared_incremental_role_events%ROWTYPE;entry jsonb;original jsonb;report jsonb;scope jsonb;run jsonb;
 i integer:=0;roles text[];runs text[]:='{}';identities text[]:='{}';role_name text;
 required jsonb:='["curriculum","difficulty","technical","ambiguity","security","adversarial"]'::jsonb;
BEGIN
 PERFORM item_supply_internal.assert_incremental_shared_current(p->'lease',(p->>'artifact_id')::uuid);
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO app FROM tutor_item_supply_shared_validation_applicabilities x WHERE x.job_id=(p->'lease'->>'job_id')::uuid
  AND x.generation_artifact_id=a.id FOR SHARE;
 IF app.id IS NULL THEN RAISE EXCEPTION '588 same-child quality requires explicit original validation applicability'; END IF;
 PERFORM item_supply_internal.assert_shared_validation_applicability(app.payload_json);
 SELECT * INTO prep FROM tutor_item_supply_shared_validation_preparations WHERE id=(app.payload_json->>'preparation_id')::uuid FOR SHARE;
 SELECT * INTO validation FROM tutor_item_supply_shared_pipeline_receipts WHERE id=app.original_receipt_id FOR SHARE;
 SELECT array_agg(x->>'role' ORDER BY n) INTO roles FROM jsonb_array_elements(b->'entries') WITH ORDINALITY e(x,n);
 IF p->>'parent_artifact_id' IS DISTINCT FROM a.id::text OR p->>'artifact_id' IS DISTINCT FROM a.id::text
  OR b->>'schema_version' IS DISTINCT FROM 'item_supply_review_coverage_v1'
  OR b->>'mode' IS DISTINCT FROM 'peer_blind' OR b->>'state' IS DISTINCT FROM 'completed'
  OR b->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
  OR b->'impact'->>'rule_version' IS DISTINCT FROM 'committed-same-child-v1'
  OR b->'impact'->>'parent_subject_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(subject)
  OR b->'impact'->>'child_subject_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(subject)
  OR b->'impact'->'changed_paths' IS DISTINCT FROM '[]'::jsonb OR b->'impact'->'allowed_paths' IS DISTINCT FROM '[]'::jsonb
  OR b->'impact'->'reusable_roles' IS DISTINCT FROM '[]'::jsonb OR b->'impact'->'failed_roles' IS DISTINCT FROM '[]'::jsonb
  OR b->'impact'->'uncertain_roles' IS DISTINCT FROM '[]'::jsonb
  OR b->'impact'->'affected_roles' IS DISTINCT FROM required OR b->'impact'->'required_roles' IS DISTINCT FROM required
  OR b->'impact'->'machine_validation_required' IS DISTINCT FROM 'true'::jsonb
  OR b->'impact'->'coverage_rebuild_required' IS DISTINCT FROM 'true'::jsonb
  OR jsonb_array_length(b->'entries') IS DISTINCT FROM 6 OR roles IS DISTINCT FROM ARRAY['curriculum','difficulty','technical','ambiguity','security','adversarial']::text[]
  OR jsonb_array_length(b->'impact'->'original_report_hashes') IS DISTINCT FROM 6
  OR jsonb_array_length(b->'impact'->'original_scope_hashes') IS DISTINCT FROM 6
  OR p->>'coverage_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(b)
  OR subject->'source' IS DISTINCT FROM a.source_json OR subject->'binding' IS DISTINCT FROM b->'binding'
  OR subject->'finite_spec' IS DISTINCT FROM prep.payload_json->'spec'
  OR subject->'validation_receipt' IS DISTINCT FROM validation.payload_json
  OR subject->>'specification_hash' IS DISTINCT FROM app.payload_json->>'specification_hash'
  OR b->'binding'->>'candidate_key' IS DISTINCT FROM a.item_id::text OR b->'binding'->>'version_key' IS DISTINCT FROM a.version_id::text
  OR b->'binding'->>'source_hash' IS DISTINCT FROM a.source_hash OR b->'binding'->>'content_hash' IS DISTINCT FROM a.content_hash
  OR b->'binding'->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
  OR b->'binding'->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(a)
  OR b->>'author_identity' IS DISTINCT FROM (a.receipt_json->'provider'->>'provider')||'.item_author'
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations r WHERE r.id=(p->>'reservation_id')::uuid
    AND r.job_id=(p->'lease'->>'job_id')::uuid AND r.root_id=a.root_id AND r.lease_generation::text=p->'lease'->>'generation'
    AND r.reservation_key='review.'||replace(a.id::text,'-','')) THEN
  RAISE EXCEPTION '588 explicit same-child coverage must match actual current source validation and six logical actions'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(b->'entries') LOOP
  role_name:=entry->>'role';original:=entry->'original';report:=original->'report';scope:=original->'scope';
  SELECT * INTO done FROM tutor_item_supply_shared_incremental_role_events e WHERE e.generation_artifact_id=a.id
   AND e.role=role_name AND e.event_kind='committed' AND e.payload_json->'report'=report
   AND e.payload_json->'subject'=original->'subject' AND e.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  SELECT * INTO scope_row FROM tutor_item_supply_shared_incremental_role_events e WHERE e.review_reservation_id=done.review_reservation_id
   AND e.role=role_name AND e.event_kind='scope_prepared' AND e.payload_json->'scope'=scope
   AND e.payload_json->'subject'=original->'subject' AND e.xmin::text::bigint<>txid_current()%4294967296 FOR SHARE;
  IF done.id IS NULL OR scope_row.id IS NULL OR report->>'role' IS DISTINCT FROM role_name
   OR report->'binding' IS DISTINCT FROM original->'subject'->'binding'
   OR original->'subject'->'source' IS DISTINCT FROM a.source_json
   OR ((report->'binding')-'profile_hash') IS DISTINCT FROM ((b->'binding')-'profile_hash')
   OR scope->>'request_input_hash' IS DISTINCT FROM report->'run'->>'input_hash'
   OR scope->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(subject,role_name)
   OR scope->>'primary_dependency_hash' IS DISTINCT FROM item_supply_internal.incremental_primary_dependency(original->'subject',role_name)
   OR done.payload_json->'lease'->'profile'->>'profile_key_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_key_hash'
   OR b->'impact'->'original_report_hashes'->>i IS DISTINCT FROM item_supply_internal.snapshot_hash(report)
   OR b->'impact'->'original_scope_hashes'->>i IS DISTINCT FROM item_supply_internal.snapshot_hash(scope) THEN
   RAISE EXCEPTION '588 same-child coverage requires actual original committed role scope input and semantic recipe'; END IF;
  IF entry->>'mode'='fresh' THEN
   IF report->'binding' IS DISTINCT FROM b->'binding' OR original->'subject' IS DISTINCT FROM subject
    OR done.job_id::text IS DISTINCT FROM p->'lease'->>'job_id' THEN
    RAISE EXCEPTION '588 fresh role must use new current lease subject'; END IF;
  ELSIF entry->>'mode'='committed_same_action' THEN
   IF entry->'committed_action'->'original' IS DISTINCT FROM original
    OR entry->'committed_action'->'target_binding' IS DISTINCT FROM b->'binding'
    OR entry->'committed_action'->>'logical_action_hash' IS DISTINCT FROM done.logical_action_hash THEN
    RAISE EXCEPTION '588 same-child original committed role applicability required'; END IF;
  ELSE RAISE EXCEPTION '588 same-child coverage cannot pretend revision or original_applicable'; END IF;
  run:=report->'run';
  IF run->>'run_id'=ANY(runs) OR run->'provider_identity'->>'identity'=ANY(identities)
   OR run->'provider_identity'->>'identity'=b->>'author_identity' THEN
   RAISE EXCEPTION '588 same-child independent original roles required'; END IF;
  runs:=array_append(runs,run->>'run_id');identities:=array_append(identities,run->'provider_identity'->>'identity');i:=i+1;
 END LOOP;
 PERFORM item_supply_internal.assert_shared_blind_applicability(b->'blind_solve',a.id);
 run:=item_supply_internal.incremental_blind_original(b->'blind_solve')->'run';
 IF item_supply_internal.incremental_binding(b->'blind_solve') IS DISTINCT FROM b->'binding'
  OR run->>'run_id'=ANY(runs) OR run->'provider_identity'->>'identity'=ANY(identities)
  OR run->'provider_identity'->>'identity'=b->>'author_identity' THEN
  RAISE EXCEPTION '588 same-child distinct blind and original score applicability required'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_committed_same_child_coverage(jsonb) FROM PUBLIC;

-- Only the precise original probe intent may enter 490 execution-only funding.
-- It is pre-budget DATA, never a validation preparation or an HTTP/token grant.
CREATE OR REPLACE FUNCTION item_supply_internal.shared_review_probe_intent_for_reservation(job uuid,root uuid,generation integer,reservation_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE intent tutor_item_supply_shared_review_probe_events%ROWTYPE;finding jsonb;
BEGIN
 SELECT * INTO intent FROM tutor_item_supply_shared_review_probe_events e WHERE e.event_kind='intent'
  AND e.job_id=job AND e.frame_json->>'root_id'=root::text AND e.frame_json->'lease'->>'generation'=generation::text
  AND reservation_key='normal.review.probe.'||replace(e.preparation_id::text,'-','') FOR SHARE;
 IF intent.id IS NULL THEN RETURN NULL; END IF;
 finding:=item_supply_internal.assert_shared_review_probe_frame(intent.frame_json);
 IF intent.reservation_id IS NOT NULL OR (intent.payload_json->>'deadline')::timestamptz<=clock_timestamp()
  OR intent.payload_json->>'preparation_id' IS DISTINCT FROM intent.preparation_id::text
  OR intent.payload_json->>'query' IS DISTINCT FROM item_supply_internal.original_review_counterexample_statement(finding->>'counterexample')
  OR intent.payload_json->'resources' IS DISTINCT FROM '{"requests":0,"input_tokens":0,"output_tokens":0,"execution_seconds":10,"fetches":0,"candidates":0,"revision_rounds":0,"investigation_rounds":0}'::jsonb
  OR intent.payload_json->'resources'->>'execution_seconds' IS DISTINCT FROM '10'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_probe_events e WHERE
    (e.action_key=intent.action_key AND e.event_kind IN ('started','completed'))
    OR (e.preparation_id=intent.preparation_id AND e.event_kind='prepared')) THEN
  RAISE EXCEPTION '588 probe execution funding needs exact current unspent intent'; END IF;
 RETURN to_jsonb(intent);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.shared_review_probe_intent_for_reservation(uuid,uuid,integer,text) FROM PUBLIC;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('enforce_item_supply_shared_execution_header()')),'missing') NOT IN ('0fa02716cb0daa895f6a140fe40ef2e9abde3543202c5ba5576088a304dcdd69','d34f5bc0f673c280cd1023ce3ba564143c7d9443b9ad4628d043c59003150b00') THEN RAISE EXCEPTION '588 original enforce_item_supply_shared_execution_header changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_execution_header()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE p tutor_item_supply_shared_validation_preparations; probe_intent jsonb;
BEGIN
  IF starts_with(NEW.reservation_key,'normal.review.probe.') THEN
    probe_intent:=item_supply_internal.shared_review_probe_intent_for_reservation(NEW.job_id,NEW.root_id,NEW.lease_generation,NEW.reservation_key);
    IF probe_intent IS NULL OR NEW.requests<>0 OR NEW.tokens<>0 OR NEW.resources<>0 THEN
      RAISE check_violation USING MESSAGE='588 exact probe intent admits only zero HTTP token resource header'; END IF;
    RETURN NEW;
  END IF;
  IF NEW.requests>0 AND NEW.tokens>0 THEN RETURN NEW; END IF;
  SELECT * INTO p FROM tutor_item_supply_shared_validation_preparations WHERE job_id=NEW.job_id
    AND root_id=NEW.root_id AND lease_generation=NEW.lease_generation AND reservation_key=NEW.reservation_key;
  IF NOT FOUND OR p.resources_json IS NULL OR NEW.requests<>0 OR NEW.tokens<>0 OR NEW.resources<>0
    OR item_supply_internal.shared_validation_current(p) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='zero header requires current shared execution preparation';
  END IF;
  RETURN NEW;
END $function$;

DO $pin588$ BEGIN
 IF COALESCE((SELECT encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('enforce_item_supply_shared_execution_allocation()')),'missing') NOT IN ('fa00c132fc77b26250a2b383489cee05429562e4074f4326749b2bbc5b2c397e','3f5d5d56232f2b50b1c219b1cdd1e59c45baa6c831f4c8acca73e7c3961265a1') THEN RAISE EXCEPTION '588 original enforce_item_supply_shared_execution_allocation changed'; END IF;
END $pin588$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_execution_allocation()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'item_supply_internal', 'pg_temp'
AS $function$
DECLARE r record; p tutor_item_supply_shared_validation_preparations; probe_intent jsonb;
BEGIN
  IF NEW.reservation_namespace<>'shared' THEN RETURN NEW; END IF;
  SELECT * INTO r FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id;
  IF FOUND AND starts_with(r.reservation_key,'normal.review.probe.') THEN
    probe_intent:=item_supply_internal.shared_review_probe_intent_for_reservation(r.job_id,r.root_id,r.lease_generation,r.reservation_key);
    IF probe_intent IS NULL OR r.requests<>0 OR r.tokens<>0 OR r.resources<>0
      OR NOT (probe_intent->'payload_json'->'resources' ? NEW.resource_kind)
      OR NEW.reserved_amount IS DISTINCT FROM (probe_intent->'payload_json'->'resources'->>NEW.resource_kind)::bigint THEN
      RAISE check_violation USING MESSAGE='588 exact original probe intent execution allocation required'; END IF;
    RETURN NEW;
  END IF;
  IF NOT FOUND OR r.requests>0 OR r.tokens>0 THEN RETURN NEW; END IF;
  SELECT * INTO p FROM tutor_item_supply_shared_validation_preparations WHERE job_id=r.job_id AND reservation_key=r.reservation_key;
  IF NOT FOUND OR item_supply_internal.shared_validation_current(p) IS DISTINCT FROM true
    OR NEW.reserved_amount IS DISTINCT FROM (p.resources_json->>NEW.resource_kind)::bigint THEN
    RAISE check_violation USING MESSAGE='shared execution allocation mismatch';
  END IF;
  RETURN NEW;
END $function$;
