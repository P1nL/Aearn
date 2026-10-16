-- Original whole-pack CURRENT source permission; historical rows stay immutable.
-- Only original sandbox/exact case. PRIVATE transaction DATA, never a delivery permit.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
 THEN RAISE check_violation USING MESSAGE='549 original sandbox only'; END IF; END $$;
DO $pins549$ DECLARE wanted record; actual record; BEGIN
 FOR wanted IN SELECT * FROM (VALUES
 ('item_supply_internal.native_consumer_source_current(uuid)','359722666e8fda1f5027814dbbf6e148ff52511935eaeede4fde365e6b717165', '359722666e8fda1f5027814dbbf6e148ff52511935eaeede4fde365e6b717165'),
 ('item_supply_internal.private_native_mapping_current(uuid,uuid,bigint)','b20fd94bdf296edb36f16829c272999b7d0dd0024e482efc3da3da94d4631dc6', 'b20fd94bdf296edb36f16829c272999b7d0dd0024e482efc3da3da94d4631dc6'),
 ('item_supply_internal.enforce_persistent_pack_journal_insert()','6cb924d2b8a396cf2bb2c01f7315e659eadbc41bdcd0eea386190a5e8886580d', '6cb924d2b8a396cf2bb2c01f7315e659eadbc41bdcd0eea386190a5e8886580d'),
 ('item_supply_internal.assert_source_mapping_successor(jsonb)','4c67d2c7189bb7400af21402aba32be049b312bdb31332bffb77d7f8f832e206', '4c67d2c7189bb7400af21402aba32be049b312bdb31332bffb77d7f8f832e206'),
 ('item_supply_internal.native_consumer_receipt_current(uuid)','7226c8e4899cc8cfd1887da629c025cbdf67f678db4bd7b14fade44a6f9eabc0', 'eb3616249083a91c8d89c6b6ad91f7d4607bfdeda90a2cb1c31ce984bc38ae08'),
 ('item_supply_internal.private_native_base_union_current(uuid)','8b6251c2cb999d861dba7315d5bda24fb51103104df7aec358308f55709654bd', 'b5b4b4f744871db58434054ecf0fa6f1ab304d830d1eb41a68abba74fd673b7f')
 ) x(signature,body_hash,new_hash) LOOP
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(wanted.signature);
 IF NOT FOUND OR encode(sha256(convert_to(replace(actual.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') NOT IN(wanted.body_hash,wanted.new_hash)
 OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
 OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
 OR actual.prorettype<>to_regtype('pg_catalog.'||CASE WHEN wanted.signature LIKE '%assert_source_mapping_successor%' THEN 'void' WHEN wanted.signature LIKE '%enforce_persistent_pack_journal_insert%' THEN 'trigger' WHEN wanted.signature LIKE '%private_native_mapping_current%' THEN 'jsonb' ELSE 'bool' END)
 OR actual.provolatile<>'v' OR actual.proparallel<>'u'
 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
 THEN RAISE check_violation USING MESSAGE='549 unexpected installed receiver body or metadata'; END IF;
 END LOOP;
END $pins549$;
DO $newhelpers549$ DECLARE wanted record; actual record; BEGIN
 FOR wanted IN SELECT * FROM (VALUES
 ('item_supply_internal.current_pack_public_materials_current(jsonb,timestamptz)','84c7c80bbbf4782647672eb183041762fd00716baaa4bf383a7514a0f4372570','bool'),
 ('item_supply_internal.current_pack_source_receipts_match(jsonb,jsonb,timestamptz)','23cd052d0002f93d28a7977f1a83769d5f1b177bfcd72053c992e6845511c8b3','bool'),
 ('item_supply_internal.current_pack_source_origin_payload_current(jsonb,uuid,bigint,uuid)','e7345502149397176921d0d0ae68f24ee9af83241d3138389b6801848a221008','bool'),
 ('item_supply_internal.current_pack_source_origin_current(uuid,uuid,bigint,uuid)','6280d51f10b0b5cf8b4c438ff280e1fbec0f6b133b86456fbe041705c34bbe96','bool'),
 ('item_supply_internal.enforce_current_pack_source_origin_insert()','9f7459784d90c346a243cceca45209e1f867cd8725cf6486516814c5278825bd','trigger'),
 ('item_supply_internal.native_consumer_source_current(uuid,uuid,uuid,bigint,uuid)','e43a19bfd7cabf387a0916f5260bc08c448c2a431b19cc84c5dc5b8133df6ad8','bool'),
 ('item_supply_internal.native_consumer_source_context_current(uuid,jsonb,uuid,bigint,uuid)','6f32e405aec5c1f0601b664444944de2a10c174dc28b3ebc7851ecab08bbfc5d','bool')
) x(signature,body_hash,result_type) LOOP
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(wanted.signature);
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') IS DISTINCT FROM wanted.body_hash
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
  OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.'||wanted.result_type)
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[])
 THEN RAISE check_violation USING MESSAGE='549 unexpected existing current source helper'; END IF;
 END LOOP; END $newhelpers549$;
CREATE OR REPLACE FUNCTION item_supply_internal.current_pack_public_materials_current(materials jsonb,upper_bound timestamptz) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$

DECLARE p jsonb; material jsonb; e jsonb; b jsonb; claim jsonb; t timestamptz; r record;
 deadline timestamptz := 'infinity'::timestamptz;
BEGIN
 p:=jsonb_build_object('materials',materials);
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
         AND c.state='published' AND c.registry_digest=e->>'registry_digest'
         AND EXISTS(SELECT 1 FROM grounding_corpus_chunks ch WHERE ch.corpus_version_id=c.id
          AND ch.chunk_id=e->>'chunk_id' AND ch.document_id=b->>'document_handle'
          AND ch.document_hash=b->>'document_hash' AND ch.chunk_hash=e->>'approved_excerpt_hash'
          AND ch.content=material->>'excerpt') FOR SHARE OF a,c;
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
       root.delegation_id AS root_delegation_id,root.delegation_generation AS root_delegation_generation,
       root.policy_id AS root_policy,root.policy_generation AS root_generation,
       evidence.expires_at AS evidence_expires,evidence.revoked_at AS evidence_revoked,
       evidence.signed_proof AS evidence_signed_proof,evidence.proof_hash AS evidence_proof_hash
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
     -- Clock follows every possible lock wait; no entry-time deadline authority.
     t:=clock_timestamp();
     deadline:=LEAST(deadline,r.policy_retention,r.policy_expires,r.capture_retention,
       r.period_end,r.delegation_expires_at,r.evidence_expires);
     -- NEW factory access metadata is bound in full to its original signed C.
     IF r.evidence_signed_proof IS NULL OR r.evidence_proof_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(r.evidence_signed_proof)
       OR r.quality_evidence_hash IS DISTINCT FROM r.evidence_proof_hash OR r.review_receipt_hash IS DISTINCT FROM r.evidence_proof_hash
       OR (r.evidence_signed_proof->'payload'->'prepared')->>'profile_id' IS DISTINCT FROM 'python-binding-source-v1'
       OR material->'access_request' IS DISTINCT FROM jsonb_build_object('demand_hash',(r.evidence_signed_proof->'payload'->'prepared')->'demand'->>'demand_hash','scope',(r.evidence_signed_proof->'payload'->'prepared')->'demand'->'scope',
      'purpose','assessment_evidence','actor_id','service.rag-public-course','action','consume',
      'policy_id',(r.evidence_signed_proof->'payload'->'prepared')->'policy_id','policy_generation',(r.evidence_signed_proof->'payload'->'prepared')->'policy_generation','budget',(r.evidence_signed_proof->'payload'->'prepared')->'budget')
       OR r.policy_id IS DISTINCT FROM (r.evidence_signed_proof->'payload'->'prepared')->>'policy_id'
       OR r.policy_generation::text IS DISTINCT FROM (r.evidence_signed_proof->'payload'->'prepared')->>'policy_generation'
       OR r.root_id IS DISTINCT FROM (r.evidence_signed_proof->'payload'->'prepared')->'budget'->>'root_id'
       OR r.root_delegation_id IS DISTINCT FROM (r.evidence_signed_proof->'payload'->'prepared')->'budget'->>'delegation_id'
       OR r.root_delegation_generation::text IS DISTINCT FROM (r.evidence_signed_proof->'payload'->'prepared')->'budget'->>'generation'
       OR ((r.evidence_signed_proof->'payload'->'prepared')->'budget'->>'expires_at')::timestamptz>LEAST(r.period_end,r.delegation_expires_at)
       OR (r.source_handle,r.document_handle,r.document_hash) IS DISTINCT FROM
        ((r.evidence_signed_proof->'payload'->'prepared')->>'source_handle',(r.evidence_signed_proof->'payload'->'prepared')->>'document_handle',(r.evidence_signed_proof->'payload'->'prepared')->>'document_hash')
       OR COALESCE(((r.evidence_signed_proof->'payload'->'prepared')->>'prepared_at')::timestamptz<=t AND t<((r.evidence_signed_proof->'payload'->'prepared')->>'authority_expires_at')::timestamptz
        AND t<((r.evidence_signed_proof->'payload'->'prepared')->'budget'->>'expires_at')::timestamptz,false) IS DISTINCT FROM true
     THEN RETURN false; END IF;
     IF r.policy_enabled IS DISTINCT FROM true OR r.policy_revoked IS NOT NULL
       OR r.current_generation<>r.policy_generation OR r.capture_generation<>r.policy_generation OR r.admission_generation<>r.policy_generation
       OR r.policy_retention<=t OR r.policy_expires<=t OR r.capture_retention<=t OR r.cleared_at IS NOT NULL OR r.capture_body_available IS DISTINCT FROM true
       OR r.fetched_sha256<>r.document_hash OR r.admission_active IS DISTINCT FROM true OR r.admission_revoked IS NOT NULL
       OR NOT (b->>'purpose'=ANY(r.policy_usages) AND b->>'purpose'=ANY(r.admission_usages) AND b->>'purpose'=ANY(r.allowed_usages))
       OR r.status<>'reviewed' OR r.quality_code IS DISTINCT FROM 'QUALIFIED' OR r.reading_fit<>'suitable' OR r.version_fit<>'current' OR r.technical_status<>'correct'
       OR r.conflict_status<>'resolved' OR r.known_error<>'absent' OR r.root_enabled IS DISTINCT FROM true
       OR NOT(r.period_start<=t AND t<r.period_end AND t<r.delegation_expires_at)
       OR r.root_policy<>r.policy_id OR r.root_generation<>r.policy_generation
       OR (r.assessment_evidence_id IS NOT NULL AND (r.evidence_expires IS NULL OR r.evidence_expires<=t OR r.evidence_revoked IS NOT NULL)) THEN RETURN false; END IF;
     IF b->>'purpose'='assessment_evidence' THEN
       PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
         WHERE ad.receipt_handle=b->>'admission_receipt_id' AND cr.verification_receipt_hash=r.quality_evidence_hash
           AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash FOR SHARE OF cr,ad;
       IF NOT FOUND THEN RETURN false; END IF;
     END IF;
   END LOOP;
   -- The original C claim is signed/persisted; its coordinate digest is a
   -- ClaimEvidenceReceipt digest, NOT the signed-proof verification digest.
   IF jsonb_array_length(material->'exact_claims')<>1 OR jsonb_array_length(material->'binding'->'evidence')<>1
    OR item_supply_internal.snapshot_hash((material->'binding')-'binding_digest') IS DISTINCT FROM material->'binding'->>'binding_digest'
    OR encode(sha256(convert_to(material->>'excerpt','UTF8')),'hex') IS DISTINCT FROM material->'binding'->'evidence'->0->>'approved_excerpt_hash'
    OR material->'binding'->'evidence'->0->'binding' IS DISTINCT FROM material->'exact_claims'->0->'binding'
   THEN RETURN false; END IF;
   FOR claim IN SELECT value FROM jsonb_array_elements(material->'exact_claims') LOOP
     PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
       WHERE cr.receipt_handle=claim->>'claim_receipt_id' AND cr.claim_hash=claim->>'claim_hash'
         AND cr.demand_hash=claim->'binding'->>'demand_hash'
         AND cr.source_document_hash=claim->'binding'->>'document_hash'
         AND ad.receipt_handle=claim->'binding'->>'admission_receipt_id'
         AND cr.revoked_at IS NULL AND ad.active AND ad.revoked_at IS NULL
         AND cr.execution_scope_json=claim->'execution_scope' AND cr.applicability=claim->>'applicability'
         AND cr.scope_facets=ARRAY(SELECT jsonb_array_elements_text(claim->'scope'->'facets'))
         AND cr.subject_id=claim->'scope'->>'subject_id' AND cr.subject_version=claim->'scope'->>'subject_version'
         AND cr.verification_receipt_hash=r.quality_evidence_hash
         AND material->'binding'->'evidence'->0->>'claim_receipt_hash'=item_supply_internal.snapshot_hash(
          jsonb_build_object('receipt_id',cr.receipt_handle,'demand_hash',cr.demand_hash,'purpose','assessment_evidence',
           'admission_receipt_id',ad.receipt_handle,'claim_hash',cr.claim_hash,'scope',claim->'scope',
           'source_handle',claim->'binding'->>'source_handle','document_handle',claim->'binding'->>'document_handle',
           'document_revision',claim->'binding'->>'document_revision','document_hash',cr.source_document_hash,
           'applicability',cr.applicability,'method','isolated_execution','primary_lineage_family',NULL,
           'independent_lineage_family',NULL,'independent_source_handle',NULL,'independent_document_handle',NULL,
           'independent_document_revision',NULL,'independent_document_hash',NULL,'independent_lineage_verified',false,
           'execution_receipt_id',cr.execution_receipt_handle,'execution_scope',cr.execution_scope_json,'verified',true,'revoked',false))
       FOR SHARE OF cr,ad;
     IF NOT FOUND THEN RETURN false; END IF;
   END LOOP;
 END LOOP;
 RETURN clock_timestamp()<deadline AND upper_bound<=deadline;
END 
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.current_pack_source_receipts_match(materials jsonb,receipts jsonb,issued timestamptz) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$
DECLARE pair record; m jsonb;r jsonb;e jsonb;t timestamptz:=clock_timestamp(); BEGIN
 IF jsonb_typeof(materials) IS DISTINCT FROM 'array' OR jsonb_typeof(receipts) IS DISTINCT FROM 'array'
  OR jsonb_array_length(materials)<>jsonb_array_length(receipts) THEN RETURN false; END IF;
 FOR pair IN SELECT value,ordinality FROM jsonb_array_elements(materials) WITH ORDINALITY LOOP
  m:=pair.value;r:=receipts->((pair.ordinality-1)::integer);e:=m->'binding'->'evidence'->0;
  IF item_supply_internal.snapshot_keys(r,ARRAY['material_digest','binding_digest','corpus_version_id','active_generation','checked_at_iso','claim_receipt_hashes','mode']) IS DISTINCT FROM true
   OR r->>'mode' IS DISTINCT FROM 'current_authority'
   OR r->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
    'binding',m->'binding','access_request',m->'access_request','exact_claims',m->'exact_claims',
    'excerpt_hash',encode(sha256(convert_to(m->>'excerpt','UTF8')),'hex')))
   OR (r->>'binding_digest',r->>'corpus_version_id',r->>'active_generation') IS DISTINCT FROM
    (m->'binding'->>'binding_digest',e->>'corpus_version_id',e->>'active_generation')
   OR r->'claim_receipt_hashes' IS DISTINCT FROM jsonb_build_array(e->>'claim_receipt_hash')
   OR COALESCE(issued<=(r->>'checked_at_iso')::timestamptz AND (r->>'checked_at_iso')::timestamptz<=t,false) IS DISTINCT FROM true
  THEN RETURN false; END IF;
 END LOOP; RETURN true; END
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.current_pack_source_origin_payload_current(p jsonb,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$
DECLARE h tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 src tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 m tutor_item_supply_finite_course_mappings%ROWTYPE; header jsonb; selected jsonb; newest jsonb; part jsonb;
 proof record; old_e record; old_m jsonb; new_m jsonb; old_q jsonb;new_q jsonb;
 pair record; material_index integer; canonical_receipts jsonb; t timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
  OR current_setting('transaction_isolation')<>'read committed'
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','purpose','task_ref','source_successor_id','source_successor_hash',
   'selection_hash','mapping_hash','source_authorization_hash','selected','public_materials','course_materials','public_receipts','course_receipts',
   'issued_at','valid_until','capture_txid']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'current_pack_source_origin_v1'
  OR p->>'purpose' IS DISTINCT FROM 'whole_pack_current_source_only'
  OR (p->>'capture_txid')::bigint IS DISTINCT FROM txid_current()
  OR p->'task_ref'->>'pack_task_id' IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  OR p->'task_ref'->>'public_task_id' IS DISTINCT FROM '9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c'
  OR (p->'task_ref'->>'user_id')::uuid IS DISTINCT FROM u OR (p->'task_ref'->>'epoch')::bigint IS DISTINCT FROM e
  OR (p->'task_ref'->>'mapping_receipt_id')::uuid IS DISTINCT FROM mid
  OR p->>'source_successor_id' IS DISTINCT FROM '3fd36e85-711c-43c9-8350-46fdf4d57e72'
 THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->'task_ref'->>'pack_task_id')::uuid
  AND record_kind='task' AND user_id=u AND epoch=e AND scope_id=(p->'task_ref'->>'scope_id')::uuid FOR SHARE;
 IF NOT FOUND OR h.payload_json->'ref' IS DISTINCT FROM p->'task_ref' THEN RETURN false; END IF;
 SELECT * INTO src FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'source_successor_id')::uuid
  AND record_kind='source_mapping_successor' AND pack_task_id=h.id AND user_id=u AND epoch=e AND scope_id=h.scope_id FOR SHARE;
 IF NOT FOUND OR item_supply_internal.snapshot_hash(src.payload_json) IS DISTINCT FROM p->>'source_successor_hash'
  OR src.payload_json->'task_ref' IS DISTINCT FROM p->'task_ref'
  OR src.payload_json->'public_materials' IS DISTINCT FROM p->'public_materials'
  OR src.payload_json->'course_materials' IS DISTINCT FROM p->'course_materials'
  OR (p->>'valid_until')::timestamptz>(src.payload_json->>'valid_until')::timestamptz
 THEN RETURN false; END IF;
 -- Reuses the CURRENT confirmed actual-D/signed C/provenance verifier, not a revision cap.
 PERFORM item_supply_internal.assert_source_mapping_successor(src.payload_json);
 SELECT * INTO m FROM tutor_item_supply_finite_course_mappings WHERE id=mid AND user_id=u AND epoch=e FOR SHARE;
 IF NOT FOUND OR p->>'mapping_hash' IS DISTINCT FROM m.mapping_hash OR m.assessment_scope_id<>h.scope_id
  OR item_supply_internal.private_native_mapping_current(mid,u,e) IS NULL THEN RETURN false; END IF;
 SELECT payload_json INTO header FROM tutor_item_supply_shared_persistent_pack_journal
  WHERE public_task_id=(p->'task_ref'->>'public_task_id')::uuid AND record_kind='task' FOR SHARE;
 IF header IS NULL OR jsonb_typeof(p->'selected') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'selected')<>5
  OR jsonb_array_length(p->'public_materials')<>2 OR jsonb_array_length(p->'course_materials')<>1
  OR item_supply_internal.current_pack_public_materials_current(p->'public_materials',(p->>'valid_until')::timestamptz) IS DISTINCT FROM true
  OR item_supply_internal.current_pack_source_receipts_match(p->'public_materials',p->'public_receipts',(p->>'issued_at')::timestamptz) IS DISTINCT FROM true
  OR item_supply_internal.current_pack_source_receipts_match(p->'course_materials',p->'course_receipts',(p->>'issued_at')::timestamptz) IS DISTINCT FROM true
 THEN RETURN false; END IF;
 FOR pair IN SELECT * FROM (VALUES
  (0,'practice-1','36b07034-c81a-530a-90ac-c7f62a92a8dd'),
  (1,'practice-2','7a2898e0-c24e-5a33-9596-387a64dcdcaa'),
  (2,'assessment-1','2d8325e7-5cb5-56f1-a004-ecec3abd60e5'),
  (3,'assessment-2','8ba4ca51-e8f4-540a-b52a-eaec8a0a6764'),
  (4,'guided-remediation','a2b435f4-2d4e-5048-a1cc-c482f4ffa5fe')) x(ordinal,slot,version_id) LOOP
  selected:=p->'selected'->pair.ordinal;
  IF item_supply_internal.snapshot_keys(selected,ARRAY['slot','version','version_id','proof_id','proof_hash','published_at']) IS DISTINCT FROM true
   OR selected->>'slot' IS DISTINCT FROM pair.slot OR selected->>'version_id' IS DISTINCT FROM pair.version_id
   OR selected->'version'->>'slot' IS DISTINCT FROM pair.slot
   OR selected->'version'->'public_slot_id' IS DISTINCT FROM h.payload_json->'slots'->pair.ordinal->'public_slot_id'
  THEN RETURN false; END IF;
  SELECT payload_json INTO newest FROM tutor_item_supply_shared_persistent_pack_journal
   WHERE public_task_id=(p->'task_ref'->>'public_task_id')::uuid AND record_kind IN('version','qualified')
    AND payload_json->>'slot'=pair.slot ORDER BY (payload_json->>'revision_seq')::bigint DESC,created_at DESC,id DESC LIMIT 1;
  IF newest IS DISTINCT FROM selected->'version' OR newest->>'published_version_id' IS DISTINCT FROM pair.version_id THEN RETURN false; END IF;
  SELECT n.*,pe.occurred_at,g.root_id,g.candidate_id,g.job_id INTO proof FROM tutor_learning_item_native_publication_proofs n
   JOIN tutor_learning_item_publication_events pe ON pe.id=n.publication_event_id
   JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=n.generation_artifact_id
   JOIN LATERAL(SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=n.version_id
    ORDER BY state_version DESC LIMIT 1) latest ON latest.id=n.publication_event_id AND latest.state='published'
   WHERE n.id=(selected->>'proof_id')::uuid AND n.version_id=pair.version_id::uuid;
  IF NOT FOUND OR proof.proof_hash IS DISTINCT FROM selected->>'proof_hash'
   OR item_supply_internal.snapshot_hash((proof.proof_json)-'proof_hash') IS DISTINCT FROM proof.proof_hash
   OR proof.occurred_at IS DISTINCT FROM (selected->>'published_at')::timestamptz
   OR NOT((proof.proof_json->>'checked_at')::timestamptz<=proof.occurred_at AND proof.occurred_at<(proof.proof_json->>'valid_until')::timestamptz)
   OR proof.generation_artifact_id::text IS DISTINCT FROM newest->>'artifact_id'
   OR proof.root_id::text IS DISTINCT FROM newest->>'root_id' OR proof.candidate_id::text IS DISTINCT FROM newest->>'candidate_id'
   OR proof.proof_json->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(newest->'specification')
   OR item_supply_internal.controlled_counterexample_held(proof.job_id) IS DISTINCT FROM false
   OR jsonb_array_length(proof.proof_json->'materials')<>2 OR jsonb_array_length(proof.proof_json->'source_receipts')<>2
  THEN RETURN false; END IF;
  FOR material_index IN 0..1 LOOP
   old_m:=proof.proof_json->'materials'->material_index;new_m:=p->'public_materials'->material_index;
   -- Full per-position target/goal/demand/purpose/excerpt/applicability obligations.
   IF ((old_m->'binding')-'evidence'-'binding_digest') IS DISTINCT FROM ((new_m->'binding')-'evidence'-'binding_digest')
    OR ((old_m->'access_request')-'policy_id'-'policy_generation'-'budget')
     IS DISTINCT FROM ((new_m->'access_request')-'policy_id'-'policy_generation'-'budget')
    OR old_m->'excerpt' IS DISTINCT FROM new_m->'excerpt'
    OR old_m->'classification' IS DISTINCT FROM new_m->'classification'
    OR jsonb_array_length(old_m->'exact_claims')<>1 OR jsonb_array_length(old_m->'binding'->'evidence')<>1
    OR ((old_m->'exact_claims'->0)-'binding'-'claim_receipt_id'-'claim_hash')
     IS DISTINCT FROM ((new_m->'exact_claims'->0)-'binding'-'claim_receipt_id'-'claim_hash')
    OR ((old_m->'exact_claims'->0->'binding')-'document_handle'-'document_revision'-'document_hash'-'admission_receipt_id'-'claim_receipt_id')
     IS DISTINCT FROM ((new_m->'exact_claims'->0->'binding')-'document_handle'-'document_revision'-'document_hash'-'admission_receipt_id'-'claim_receipt_id')
    OR old_m->'binding'->'evidence'->0->>'approved_excerpt_hash' IS DISTINCT FROM new_m->'binding'->'evidence'->0->>'approved_excerpt_hash'
   THEN RETURN false; END IF;
   SELECT ev.*,rev.status,rev.quality_code,rev.reading_fit,rev.version_fit,rev.technical_status,rev.conflict_status,rev.known_error,
    rev.review_receipt_hash,rev.quality_evidence_hash,ad.active,ad.revoked_at AS admission_revoked,
    cr.revoked_at AS claim_revoked,cr.verification_receipt_hash INTO old_e
    FROM rag_assessment_source_evidence ev JOIN rag_source_reviews rev ON rev.assessment_evidence_id=ev.id
    JOIN rag_source_admissions ad ON ad.review_id=rev.id
    JOIN rag_source_claim_receipts cr ON cr.assessment_evidence_id=ev.id AND cr.admission_id=ad.id
    WHERE ev.claim_handle=old_m->'exact_claims'->0->>'claim_receipt_id' AND cr.receipt_handle=ev.claim_handle FOR SHARE OF ev,rev,ad,cr;
   IF NOT FOUND OR old_e.revoked_at IS NOT NULL OR old_e.admission_revoked IS NOT NULL OR old_e.claim_revoked IS NOT NULL
    OR old_e.active IS DISTINCT FROM true OR old_e.quality_code IS DISTINCT FROM 'QUALIFIED' OR (old_e.status,old_e.reading_fit,old_e.version_fit,old_e.technical_status,old_e.conflict_status,old_e.known_error)
     IS DISTINCT FROM ('reviewed','suitable','current','correct','resolved','absent')
    OR NOT(old_e.issued_at<=proof.occurred_at AND proof.occurred_at<old_e.expires_at)
    OR old_e.proof_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(old_e.signed_proof)
    OR old_e.verification_receipt_hash IS DISTINCT FROM old_e.proof_hash OR old_e.review_receipt_hash IS DISTINCT FROM old_e.proof_hash
    OR old_e.quality_evidence_hash IS DISTINCT FROM old_e.proof_hash
   THEN RETURN false; END IF;
   old_q:=old_e.signed_proof->'payload'->'prepared';
   -- OLD source-access permission is historical DATA valid at actual publication,
   -- not a current grant. Root/delegation/policy/expiry may only change through
   -- the independently verified NEW signed C, never through this continuity test.
   IF old_q->>'profile_id' IS DISTINCT FROM 'python-binding-source-v1'
    OR old_m->'access_request' IS DISTINCT FROM jsonb_build_object('demand_hash',old_q->'demand'->>'demand_hash','scope',old_q->'demand'->'scope',
      'purpose','assessment_evidence','actor_id','service.rag-public-course','action','consume',
      'policy_id',old_q->'policy_id','policy_generation',old_q->'policy_generation','budget',old_q->'budget')
    OR (old_e.capture_id::text,old_e.source_handle,old_e.document_handle,old_e.document_hash,
     old_e.policy_id,old_e.policy_generation::text,old_e.root_id,old_e.profile_id,old_e.service_key_id)
     IS DISTINCT FROM (old_q->>'capture_id',old_q->>'source_handle',old_q->>'document_handle',old_q->>'document_hash',
      old_q->>'policy_id',old_q->>'policy_generation',old_q->'budget'->>'root_id',old_q->>'profile_id',old_e.signed_proof->>'service_key_id')
    OR COALESCE((old_q->>'prepared_at')::timestamptz<=proof.occurred_at
     AND proof.occurred_at<(old_q->>'authority_expires_at')::timestamptz
     AND proof.occurred_at<(old_q->'budget'->>'expires_at')::timestamptz,false) IS DISTINCT FROM true
   THEN RETURN false; END IF;
   SELECT signed_proof->'payload'->'prepared' INTO new_q FROM rag_assessment_source_evidence
    WHERE claim_handle=new_m->'exact_claims'->0->>'claim_receipt_id' FOR SHARE;
   IF NOT FOUND OR new_m->'access_request' IS DISTINCT FROM jsonb_build_object('demand_hash',new_q->'demand'->>'demand_hash','scope',new_q->'demand'->'scope',
      'purpose','assessment_evidence','actor_id','service.rag-public-course','action','consume',
      'policy_id',new_q->'policy_id','policy_generation',new_q->'policy_generation','budget',new_q->'budget')
    OR (old_q->'profile_id',old_q->'source_handle',old_q->'license_id',old_q->'origin',old_q->'reading_level',old_q->'demand',old_q->'execution_scope')
     IS DISTINCT FROM (new_q->'profile_id',new_q->'source_handle',new_q->'license_id',new_q->'origin',new_q->'reading_level',new_q->'demand',new_q->'execution_scope')
    OR (SELECT jsonb_agg(jsonb_build_array(s->>'unit',s->>'sha256',(s->>'end_byte')::bigint-(s->>'start_byte')::bigint) ORDER BY ordinality)
     FROM jsonb_array_elements(old_q->'spans') WITH ORDINALITY x(s,ordinality))
     IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array(s->>'unit',s->>'sha256',(s->>'end_byte')::bigint-(s->>'start_byte')::bigint) ORDER BY ordinality)
      FROM jsonb_array_elements(new_q->'spans') WITH ORDINALITY x(s,ordinality))
   THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 IF item_supply_internal.snapshot_hash(jsonb_build_object('task',h.payload_json,'header',header,'selected',p->'selected'))
   IS DISTINCT FROM p->>'selection_hash' THEN RETURN false; END IF;
 SELECT jsonb_agg(r-'checked_at_iso' ORDER BY ordinal) INTO canonical_receipts FROM jsonb_array_elements((p->'public_receipts')||(p->'course_receipts')) WITH ORDINALITY x(r,ordinal);
 IF item_supply_internal.snapshot_hash(jsonb_build_object('purpose','whole_pack_current_source_only','mapping_hash',m.mapping_hash,
  'public_materials',p->'public_materials','course_materials',p->'course_materials','receipts',canonical_receipts)) IS DISTINCT FROM p->>'source_authorization_hash'
 THEN RETURN false; END IF;
 t:=clock_timestamp();
 RETURN COALESCE((p->>'issued_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz,false);
END
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.current_pack_source_origin_current(rid uuid,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$
DECLARE r tutor_item_supply_private_persistent_pack_journal%ROWTYPE; BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='current_pack_source_origin'
  AND pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND user_id=u AND epoch=e FOR SHARE;
 IF NOT FOUND OR r.scope_id::text IS DISTINCT FROM r.payload_json->'task_ref'->>'scope_id'
  OR r.intent_hash IS DISTINCT FROM r.payload_json->'task_ref'->>'intent_hash'
  OR (r.payload_json->>'capture_txid')::bigint IS DISTINCT FROM txid_current() THEN RETURN false; END IF;
 RETURN item_supply_internal.current_pack_source_origin_payload_current(r.payload_json,u,e,mid);
END
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_current_pack_source_origin_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$
BEGIN
 IF NEW.record_kind<>'current_pack_source_origin' THEN RETURN NEW; END IF;
 IF NEW.pack_task_id::text IS DISTINCT FROM NEW.payload_json->'task_ref'->>'pack_task_id'
  OR NEW.scope_id::text IS DISTINCT FROM NEW.payload_json->'task_ref'->>'scope_id'
  OR NEW.intent_hash IS DISTINCT FROM NEW.payload_json->'task_ref'->>'intent_hash'
  OR NEW.operation_key NOT LIKE 'current.source.%'
  OR item_supply_internal.current_pack_source_origin_payload_current(NEW.payload_json,NEW.user_id,NEW.epoch::bigint,
   (NEW.payload_json->'task_ref'->>'mapping_receipt_id')::uuid) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='549 original exact CURRENT source issuer required'; END IF;
 RETURN NEW; END
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.native_consumer_source_current(proof_id uuid,origin_id uuid,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$
DECLARE r jsonb;n record; BEGIN
 IF item_supply_internal.current_pack_source_origin_current(origin_id,u,e,mid) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT payload_json INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=origin_id AND record_kind='current_pack_source_origin';
 SELECT id,version_id,proof_hash INTO n FROM tutor_learning_item_native_publication_proofs WHERE id=proof_id;
 IF NOT FOUND THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM jsonb_array_elements(r->'selected') s WHERE s->>'proof_id'=n.id::text
  AND s->>'version_id'=n.version_id::text AND s->>'proof_hash'=n.proof_hash);
END
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.native_consumer_source_context_current(proof_id uuid,p jsonb,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$
BEGIN
 IF p->>'schema_version' IN('native_artifact_creation_current_source_v2','native_artifact_consumption_current_source_v2','private_native_base_union_current_source_v2') THEN
  IF p->>'source_mode' IS DISTINCT FROM 'current_pack_source_origin_v1'
   OR jsonb_typeof(p->'current_source_origin_id') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
  RETURN item_supply_internal.native_consumer_source_current(proof_id,(p->>'current_source_origin_id')::uuid,u,e,mid);
 END IF;
 -- Old mode remains exact and never guesses an origin from a UUID or successor.
 IF p ? 'source_mode' OR p ? 'current_source_origin_id' THEN RETURN false; END IF;
 RETURN item_supply_internal.native_consumer_source_current(proof_id);
END
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.native_consumer_receipt_current(receipt_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$

DECLARE r record; m record; n record; d record; el record; a record; binding record;
 p jsonb; original jsonb; q jsonb; selected jsonb; t timestamptz; consumption jsonb;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_native_consumer_receipts WHERE id=receipt_id;
 IF NOT FOUND OR r.txid<>txid_current() OR current_setting('transaction_isolation')<>'read committed' THEN RETURN false; END IF;
 PERFORM item_supply_internal.native_exposure_lock(r.user_id,r.epoch);
 SELECT mappings.*,nodes.catalog_knowledge_key,scopes.snapshot_json AS scope_json INTO m
   FROM tutor_item_supply_finite_course_mappings mappings
   JOIN tutor_track_plan_nodes nodes ON (nodes.id,nodes.revision_id,nodes.track_id,nodes.user_id)=
     (mappings.node_id,mappings.revision_id,mappings.track_id,mappings.user_id) AND nodes.knowledge_key=mappings.knowledge_key
   JOIN tutor_track_active_plans active ON (active.track_id,active.user_id,active.revision_id)=
     (mappings.track_id,mappings.user_id,mappings.revision_id)
   JOIN tutor_learning_plan_sessions sessions ON sessions.id=mappings.session_id AND sessions.user_id=mappings.user_id
     AND sessions.status='confirmed' AND sessions.confirmed_track_id=mappings.track_id AND sessions.current_draft_id=mappings.draft_id
   JOIN tutor_item_supply_private_scopes scopes ON scopes.id=mappings.practice_scope_id AND scopes.user_id=mappings.user_id
     AND scopes.epoch=mappings.epoch AND scopes.track_id=mappings.track_id AND scopes.revision_id=mappings.revision_id
     AND scopes.knowledge_key=mappings.knowledge_key
   WHERE mappings.id=r.mapping_id AND mappings.user_id=r.user_id AND mappings.epoch=r.epoch
   FOR SHARE OF mappings,nodes,active,sessions,scopes;
 IF NOT FOUND OR m.receipt_json->>'target_id' IS DISTINCT FROM 'python-kc-binding-v1'
   OR m.receipt_json->'frozen_node'->>'catalog_knowledge_key' IS DISTINCT FROM m.catalog_knowledge_key THEN RETURN false; END IF;
 p:=r.payload_json;
 IF p->>'schema_version'='native_artifact_creation_current_source_v2' THEN
  IF r.mode<>'create' OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','request','mapping_id','mapping_hash','goal_hash','catalog_key',
   'public_catalog_key','version_id','proof_id','publication_id','materialization_id','content_hash','scope_hash','objective_hash','current_consumption',
   'source_mode','current_source_origin_id']) IS DISTINCT FROM true THEN RETURN false; END IF;
 ELSIF p->>'schema_version'='native_artifact_consumption_current_source_v2' THEN
  IF r.mode<>'consume' OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','artifact_id','artifact_version','action','creation_receipt_id',
   'current_consumption','source_mode','current_source_origin_id']) IS DISTINCT FROM true THEN RETURN false; END IF;
 ELSIF p ? 'source_mode' OR p ? 'current_source_origin_id' THEN RETURN false;
 END IF;
 IF r.mode='create' THEN
   original:=p; q:=p->'request';
   IF item_supply_internal.native_consumer_teaching_request_current(q,m.revision_id) IS DISTINCT FROM true THEN RETURN false; END IF;
   SELECT deliveries.* INTO d FROM tutor_item_supply_type_exposure_deliveries deliveries
     WHERE deliveries.id=r.delivery_id AND deliveries.user_id=r.user_id AND deliveries.epoch=r.epoch
       AND deliveries.version_id=r.version_id AND deliveries.scope_id=m.practice_scope_id AND deliveries.delivery_txid=txid_current();
   IF NOT FOUND THEN RETURN false; END IF;
   SELECT * INTO el FROM tutor_item_supply_native_eligibility
     WHERE id=d.eligibility_id AND user_id=r.user_id AND epoch=r.epoch AND mapping_receipt_id=m.id AND txid=txid_current();
   IF NOT FOUND OR el.exposure_snapshot_id<>d.exposure_snapshot_id OR el.snapshot_json->'request' IS DISTINCT FROM m.receipt_json->'pack_request' THEN RETURN false; END IF;
   PERFORM item_supply_internal.type_exposure_current(d.exposure_snapshot_id,r.user_id,r.epoch);
   selected:=el.snapshot_json->'selected';
   IF jsonb_array_length(selected) IS DISTINCT FROM 5
     OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='practice')<>2
     OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='assessment')<>2
     OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='remediation')<>1 THEN RETURN false; END IF;
   IF p->>'schema_version'='native_artifact_creation_current_source_v2' THEN
    IF (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM jsonb_array_elements(selected) x)
     IS DISTINCT FROM (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM tutor_item_supply_private_persistent_pack_journal j,
      LATERAL jsonb_array_elements(j.payload_json->'selected') x WHERE j.id=(p->>'current_source_origin_id')::uuid AND j.record_kind='current_pack_source_origin')
    THEN RETURN false; END IF;
   END IF;
   -- Every selected native source is checked BEFORE any bank row lock.
   FOR consumption IN SELECT value FROM jsonb_array_elements(selected) LOOP
     IF item_supply_internal.native_consumer_source_context_current((consumption->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,m.id) IS DISTINCT FROM true THEN RETURN false; END IF;
   END LOOP;
   FOR consumption IN SELECT value FROM jsonb_array_elements(selected) LOOP
     PERFORM 1 FROM tutor_learning_item_versions v JOIN LATERAL (
       SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=v.id ORDER BY state_version DESC LIMIT 1) pe
       ON pe.id=(consumption->>'publication_id')::uuid AND pe.state='published'
       WHERE v.id=(consumption->>'version_id')::uuid FOR SHARE OF v;
     IF NOT FOUND THEN RETURN false; END IF;
     -- Separate statement after the version-lock wait sees current events.
     PERFORM 1 FROM (SELECT id,state FROM tutor_learning_item_publication_events
       WHERE version_id=(consumption->>'version_id')::uuid ORDER BY state_version DESC LIMIT 1) pe
       WHERE pe.id=(consumption->>'publication_id')::uuid AND pe.state='published';
     IF NOT FOUND THEN RETURN false; END IF;
   END LOOP;
   IF (q->>'turn_id',q->>'user_id',q->>'learning_track_id',q->>'knowledge_key',q->>'owner_id',q->>'owner_kind',q->>'artifact_kind')
     IS DISTINCT FROM (r.run_id::text,r.user_id::text,m.track_id::text,m.knowledge_key,r.version_id::text,'learning_item','knowledge_check')
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(selected) x WHERE x->>'version_id'=r.version_id::text
       AND x->'member'->>'slot'='practice' AND x->'type_evidence'->'content'=d.binding_json
       AND x->'candidate'->>'objective_hash'=p->>'objective_hash'
       AND item_supply_internal.snapshot_hash(x->'candidate'->'scope')=p->>'scope_hash') THEN RETURN false; END IF;
 ELSE
   SELECT * INTO binding FROM tutor_item_supply_native_artifact_bindings
     WHERE artifact_id=r.artifact_id AND user_id=r.user_id AND epoch=r.epoch AND mapping_id=r.mapping_id AND version_id=r.version_id;
   IF NOT FOUND OR p->>'creation_receipt_id' IS DISTINCT FROM binding.creation_receipt_id::text THEN RETURN false; END IF;
   SELECT payload_json INTO original FROM tutor_item_supply_native_consumer_receipts WHERE id=binding.creation_receipt_id AND mode='create';
   q:=original->'request';
   IF item_supply_internal.native_consumer_teaching_request_current(q,m.revision_id) IS DISTINCT FROM true THEN RETURN false; END IF;
   SELECT * INTO a FROM tutor_learning_artifacts WHERE id=r.artifact_id AND user_id=r.user_id AND version=r.artifact_version
     AND owner_kind='learning_item' AND owner_id=r.version_id AND artifact_kind='knowledge_check'
     AND state IN ('pending','ready','active') AND active_attempt_id IS NULL;
   IF NOT FOUND OR (a.learning_track_id,a.knowledge_key,a.turn_id,a.teaching_session_id)
     IS DISTINCT FROM (m.track_id,m.knowledge_key,(q->>'turn_id')::uuid,(q->>'teaching_session_id')::uuid)
     OR p->>'artifact_id' IS DISTINCT FROM a.id::text OR p->>'artifact_version' IS DISTINCT FROM a.version::text THEN RETURN false; END IF;
   IF r.mode='cancel' THEN
     RETURN p->>'action'='cancel' AND r.checked_at<=clock_timestamp() AND clock_timestamp()<r.valid_until;
   END IF;
   IF (p->>'action'=ANY(ARRAY['request_hint','request_direct_answer','respond'])) IS DISTINCT FROM true THEN RETURN false; END IF;
   -- Later content actions use fresh source/current owner, not delivery/exposure
   -- deadlines or producer lease renewal. Creation receipts are reference DATA.
   IF item_supply_internal.native_consumer_source_context_current((original->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,m.id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END IF;
 SELECT proof.*,v.knowledge_key,v.content_hash AS actual_content,v.item_kind,v.purpose,v.handle,
   pe.state_version AS publication_version,mat.receipt_hash AS materialization_hash,
   facts.content_json AS content_json INTO n
   FROM tutor_learning_item_native_publication_proofs proof
   JOIN tutor_learning_item_versions v ON v.id=proof.version_id
   JOIN tutor_learning_item_public_contents pub ON pub.version_id=v.id AND pub.public_json->>'visibility'='public'
   JOIN tutor_learning_item_practice_materializations mat ON mat.id=proof.materialization_id AND mat.version_id=v.id
     AND mat.item_handle=v.handle AND mat.content_hash=v.content_hash
   JOIN tutor_exercise_versions exercise ON exercise.id=mat.exercise_version_id AND exercise.source_kind='registered_author'
   JOIN tutor_item_supply_native_content_facts facts ON facts.version_id=v.id AND facts.proof_id=proof.id
     AND facts.proof_hash=proof.proof_hash AND facts.user_id=r.user_id AND facts.epoch=r.epoch
   JOIN LATERAL(SELECT id,state,state_version,occurred_at FROM tutor_learning_item_publication_events
     WHERE version_id=v.id ORDER BY state_version DESC LIMIT 1) pe ON pe.id=proof.publication_event_id AND pe.state='published'
   WHERE proof.id=(original->>'proof_id')::uuid AND proof.version_id=r.version_id
     AND pe.occurred_at>=(proof.proof_json->>'checked_at')::timestamptz AND pe.occurred_at<(proof.proof_json->>'valid_until')::timestamptz
   FOR SHARE OF v;
 IF NOT FOUND OR n.item_kind<>'knowledge_check' OR n.knowledge_key<>'finite.python-kc-binding-v1'
   OR (original->>'mapping_id',original->>'mapping_hash',original->>'goal_hash',original->>'catalog_key',original->>'public_catalog_key',
       original->>'version_id',original->>'publication_id',original->>'materialization_id',original->>'content_hash')
     IS DISTINCT FROM (m.id::text,m.mapping_hash,m.goal_hash,COALESCE(m.catalog_knowledge_key,m.knowledge_key),n.knowledge_key,
       r.version_id::text,n.publication_event_id::text,n.materialization_id::text,n.actual_content)
   OR q->>'owner_version' IS DISTINCT FROM n.publication_version::text THEN RETURN false; END IF;
 PERFORM 1 FROM (SELECT id,state FROM tutor_learning_item_publication_events
   WHERE version_id=r.version_id ORDER BY state_version DESC LIMIT 1) pe
   WHERE pe.id=n.publication_event_id AND pe.state='published';
 IF NOT FOUND THEN RETURN false; END IF;
 consumption:=p->'current_consumption';
 IF consumption->>'schema_version' IS DISTINCT FROM 'native_item_current_consumption_v1'
   OR consumption->>'mode' IS DISTINCT FROM 'current_read_transaction_data_only'
   OR (consumption->>'publication_proof_id',consumption->>'publication_proof_hash',consumption->>'version_id',
       consumption->>'content_hash',consumption->>'source_hash',consumption->>'specification_hash',consumption->>'materialization_hash',
       consumption->>'runtime_profile_hash',consumption->>'scorer_version')
     IS DISTINCT FROM (n.id::text,n.proof_hash,r.version_id::text,n.actual_content,n.proof_json->>'source_hash',
       n.proof_json->>'specification_hash',n.materialization_hash,m.scope_json->>'runtime_profile_hash',m.scope_json->>'scorer_version') THEN RETURN false; END IF;
 IF p->>'schema_version' IN('native_artifact_creation_current_source_v2','native_artifact_consumption_current_source_v2') THEN
  IF consumption->'current_source_receipt_hashes' IS DISTINCT FROM
   (SELECT jsonb_agg(item_supply_internal.snapshot_hash(x) ORDER BY ordinal) FROM tutor_item_supply_private_persistent_pack_journal j,
    LATERAL jsonb_array_elements(j.payload_json->'public_receipts') WITH ORDINALITY z(x,ordinal)
    WHERE j.id=(p->>'current_source_origin_id')::uuid AND j.record_kind='current_pack_source_origin') THEN RETURN false; END IF;
 END IF;
 -- All source locks have already been acquired before bank locks. Re-reading
 -- these fences rechecks time/revocation after a possible bank lock wait.
 IF r.mode='create' THEN
   FOR consumption IN SELECT value FROM jsonb_array_elements(selected) LOOP
     IF item_supply_internal.native_consumer_source_context_current((consumption->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,m.id) IS DISTINCT FROM true THEN RETURN false; END IF;
   END LOOP;
 ELSE
   IF item_supply_internal.native_consumer_source_context_current(n.id,p,r.user_id,r.epoch::bigint,m.id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END IF;
 consumption:=p->'current_consumption';
 t:=clock_timestamp();
 IF item_supply_internal.native_consumer_teaching_request_current(q,m.revision_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF NOT(r.checked_at<=t AND t<r.valid_until) OR (consumption->>'checked_at')::timestamptz>r.checked_at THEN RETURN false; END IF;
 IF r.mode='create' THEN
   IF NOT(el.checked_at<=t AND t<el.valid_until) THEN RETURN false; END IF;
   PERFORM item_supply_internal.type_exposure_current(d.exposure_snapshot_id,r.user_id,r.epoch);
 END IF;
 RETURN true;
END 
$current549$;
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_base_union_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $current549$

DECLARE r record;el record;m jsonb;ex jsonb;p jsonb;s jsonb;c jsonb;other jsonb;original jsonb;proof record;t timestamptz;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_status';
 IF NOT FOUND THEN RETURN false; END IF;
 p:=r.payload_json;s:=p->'snapshot';
 IF COALESCE(p->>'schema_version' IN('private_native_base_union_v1','private_native_base_union_current_source_v2'),false) IS DISTINCT FROM true OR (p->>'txid')::bigint<>txid_current() THEN RETURN false; END IF;
 IF p->>'schema_version'='private_native_base_union_current_source_v2' THEN
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_eligibility_id','exposure_snapshot_id','snapshot','relations','checked_at','valid_until','txid','source_mode','current_source_origin_id']) IS DISTINCT FROM true
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(p->>'current_source_origin_id')::uuid
    AND j.pack_task_id=r.pack_task_id AND j.user_id=r.user_id AND j.epoch=r.epoch AND j.scope_id=r.scope_id AND j.record_kind='current_pack_source_origin') THEN RETURN false; END IF;
 ELSIF p ? 'source_mode' OR p ? 'current_source_origin_id' THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(r.user_id,r.epoch::bigint);
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid AND user_id=r.user_id AND epoch=r.epoch AND txid=txid_current();
 IF NOT FOUND THEN RETURN false; END IF;
 m:=item_supply_internal.private_native_mapping_current(el.mapping_receipt_id,r.user_id,r.epoch::bigint);
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);
 IF m IS NULL OR ex IS NULL OR s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_array_length(s->'selected')<>5 OR jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations')>16
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') c WHERE c->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') c WHERE c->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') c WHERE c->'member'->>'slot'='remediation')<>1
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal task WHERE task.id=r.pack_task_id AND task.record_kind='task'
   AND task.user_id=r.user_id AND task.epoch=r.epoch AND task.scope_id=r.scope_id AND task.payload_json->'ref'->>'mapping_receipt_id'=el.mapping_receipt_id::text) THEN RETURN false; END IF;
 IF p->>'schema_version'='private_native_base_union_current_source_v2' THEN
  IF (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM jsonb_array_elements(s->'selected') x)
   IS DISTINCT FROM (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM tutor_item_supply_private_persistent_pack_journal j,
    LATERAL jsonb_array_elements(j.payload_json->'selected') x WHERE j.id=(p->>'current_source_origin_id')::uuid AND j.record_kind='current_pack_source_origin') THEN RETURN false; END IF;
 END IF;
 -- Complete source set FIRST, before any of the PUBLIC version bank locks.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  SELECT value INTO original FROM jsonb_array_elements(el.snapshot_json->'selected') WHERE value->>'version_id'=c->>'version_id';
  SELECT n.*,pe.state,pe.id AS peid INTO proof FROM tutor_learning_item_native_publication_proofs n
   JOIN tutor_learning_item_versions v ON v.id=n.version_id
   JOIN LATERAL(SELECT id,state,occurred_at FROM tutor_learning_item_publication_events WHERE version_id=v.id ORDER BY state_version DESC LIMIT 1) pe ON true
   WHERE n.id=(c->>'proof_id')::uuid AND n.version_id=(c->>'version_id')::uuid AND n.publication_event_id=pe.id AND pe.state='published'
    AND pe.occurred_at>=(n.proof_json->>'checked_at')::timestamptz AND pe.occurred_at<(n.proof_json->>'valid_until')::timestamptz FOR SHARE OF v;
  IF proof.id IS NULL OR original IS NULL OR (c->>'publication_id',c->>'materialization_id',c->>'proof_id',c->'type_evidence'->'content')
    IS DISTINCT FROM (original->>'publication_id',original->>'materialization_id',original->>'proof_id',original->'type_evidence'->'content')
   OR c->'owner_id' IS DISTINCT FROM 'null'::jsonb OR c->'epoch' IS DISTINCT FROM 'null'::jsonb OR c->'candidate'->>'visibility' IS DISTINCT FROM 'public'
   OR c->'candidate'->'scope' IS DISTINCT FROM original->'candidate'->'scope' OR c->'member' IS DISTINCT FROM original->'member' THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other) THEN RETURN false; END IF;
   -- Original501/502 already covers PUBLIC ledger pairs. Additional PRIVATE
   -- exposure requires a genuine PRIVATE four-role batch for THIS actual pair.
   IF other->>'item_handle' LIKE 'lip:v2:%' AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,r.user_id,r.epoch::bigint,r.pack_task_id) IS DISTINCT FROM true THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND (p->>'checked_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz
  AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '30 seconds';
END 
$current549$;
DO $kind549$ DECLARE d text; BEGIN
 SELECT pg_get_constraintdef(oid,true) INTO d FROM pg_constraint WHERE conrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass
 AND conname='tutor_item_supply_private_persistent_pack_jou_record_kind_check' AND contype='c' AND convalidated;
 IF d IS DISTINCT FROM 'CHECK (record_kind = ANY (ARRAY[''task''::text, ''phase''::text, ''pause''::text, ''stop''::text, ''private_attachment''::text, ''private_status''::text, ''prestart_proof''::text, ''prestart_binding''::text, ''explicit_recovery_approval''::text, ''explicit_recovery_binding''::text, ''committed_revision_execution''::text, ''source_mapping_successor''::text]))' AND d IS DISTINCT FROM 'CHECK (record_kind = ANY (ARRAY[''task''::text, ''phase''::text, ''pause''::text, ''stop''::text, ''private_attachment''::text, ''private_status''::text, ''prestart_proof''::text, ''prestart_binding''::text, ''explicit_recovery_approval''::text, ''explicit_recovery_binding''::text, ''committed_revision_execution''::text, ''source_mapping_successor''::text, ''current_pack_source_origin''::text]))'
 THEN RAISE check_violation USING MESSAGE='549 unexpected PRIVATE journal kind constraint'; END IF;
 IF d IS DISTINCT FROM 'CHECK (record_kind = ANY (ARRAY[''task''::text, ''phase''::text, ''pause''::text, ''stop''::text, ''private_attachment''::text, ''private_status''::text, ''prestart_proof''::text, ''prestart_binding''::text, ''explicit_recovery_approval''::text, ''explicit_recovery_binding''::text, ''committed_revision_execution''::text, ''source_mapping_successor''::text, ''current_pack_source_origin''::text]))' THEN
 ALTER TABLE public.tutor_item_supply_private_persistent_pack_journal DROP CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check;
 ALTER TABLE public.tutor_item_supply_private_persistent_pack_journal ADD CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check CHECK (record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text, 'committed_revision_execution'::text, 'source_mapping_successor'::text, 'current_pack_source_origin'::text]));
 END IF; END $kind549$;
CREATE OR REPLACE TRIGGER trg_current_pack_source_origin_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_current_pack_source_origin_insert();
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_public_materials_current(jsonb,timestamptz) FROM PUBLIC;
ALTER FUNCTION item_supply_internal.current_pack_public_materials_current(jsonb,timestamptz) OWNER TO aearn_b1d_runtime_20261001;
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_source_receipts_match(jsonb,jsonb,timestamptz) FROM PUBLIC;
ALTER FUNCTION item_supply_internal.current_pack_source_receipts_match(jsonb,jsonb,timestamptz) OWNER TO aearn_b1d_runtime_20261001;
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_source_origin_payload_current(jsonb,uuid,bigint,uuid) FROM PUBLIC;
ALTER FUNCTION item_supply_internal.current_pack_source_origin_payload_current(jsonb,uuid,bigint,uuid) OWNER TO aearn_b1d_runtime_20261001;
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_source_origin_current(uuid,uuid,bigint,uuid) FROM PUBLIC;
ALTER FUNCTION item_supply_internal.current_pack_source_origin_current(uuid,uuid,bigint,uuid) OWNER TO aearn_b1d_runtime_20261001;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_current_pack_source_origin_insert() FROM PUBLIC;
ALTER FUNCTION item_supply_internal.enforce_current_pack_source_origin_insert() OWNER TO aearn_b1d_runtime_20261001;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_source_current(uuid,uuid,uuid,bigint,uuid) FROM PUBLIC;
ALTER FUNCTION item_supply_internal.native_consumer_source_current(uuid,uuid,uuid,bigint,uuid) OWNER TO aearn_b1d_runtime_20261001;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_source_context_current(uuid,jsonb,uuid,bigint,uuid) FROM PUBLIC;
ALTER FUNCTION item_supply_internal.native_consumer_source_context_current(uuid,jsonb,uuid,bigint,uuid) OWNER TO aearn_b1d_runtime_20261001;
