-- Native KC only: private actual catalog versus public finite catalog.
-- Original 230 receiver remains the sole Artifact owner trigger/writer. No Run,
-- Attempt, Gate, mastery, global route flag or historical capability restoration.
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_consumer_receipts (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 epoch bigint NOT NULL CHECK(epoch>=1), mode text NOT NULL CHECK(mode IN ('create','consume','cancel')),
 run_id uuid REFERENCES tutor_runs(id) ON DELETE RESTRICT,
 artifact_id uuid REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
 artifact_version integer CHECK(artifact_version>=1),
 mapping_id uuid NOT NULL, version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
 delivery_id uuid REFERENCES tutor_item_supply_type_exposure_deliveries(id) ON DELETE RESTRICT,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=131072),
 payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 checked_at timestamptz NOT NULL, valid_until timestamptz NOT NULL,
 txid bigint NOT NULL DEFAULT txid_current(), created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(valid_until>checked_at AND valid_until<=checked_at+interval '30 seconds'),
 CHECK((mode='create' AND run_id IS NOT NULL AND artifact_id IS NULL AND artifact_version IS NULL AND delivery_id IS NOT NULL)
   OR (mode IN ('consume','cancel') AND run_id IS NULL AND artifact_id IS NOT NULL AND artifact_version IS NOT NULL AND delivery_id IS NULL)),
 UNIQUE(id,user_id,epoch),
 FOREIGN KEY(mapping_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS native_consumer_create_run ON tutor_item_supply_native_consumer_receipts(user_id,epoch,run_id) WHERE mode='create';
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_artifact_bindings (
 artifact_id uuid PRIMARY KEY REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, epoch bigint NOT NULL CHECK(epoch>=1),
 version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
 mapping_id uuid NOT NULL, creation_receipt_id uuid NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(mapping_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(creation_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_native_consumer_receipts(id,user_id,epoch) ON DELETE RESTRICT
);

-- Current DB source fences supplement (never replace) original concrete Python
-- RAG/spec/runtime checks. This bounded bridge accepts only registered D evidence.
CREATE OR REPLACE FUNCTION item_supply_internal.native_consumer_source_current(proof_id uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb; material jsonb; e jsonb; b jsonb; claim jsonb; t timestamptz; r record;
 deadline timestamptz := 'infinity'::timestamptz;
BEGIN
 SELECT proof_json INTO p FROM tutor_learning_item_native_publication_proofs WHERE id=proof_id;
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_source_current(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.native_consumer_teaching_request_current(q jsonb,revision uuid) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM tutor_run_teaching_scopes scopes
   JOIN tutor_teaching_sessions sessions ON sessions.id=scopes.teaching_session_id AND sessions.user_id=scopes.user_id
     AND sessions.conversation_id=scopes.conversation_id AND sessions.track_id=scopes.track_id AND sessions.knowledge_key=scopes.knowledge_key
   JOIN tutor_teaching_session_checkpoints checkpoint ON checkpoint.id=sessions.current_checkpoint_id AND checkpoint.teaching_session_id=sessions.id
     AND checkpoint.user_id=sessions.user_id AND checkpoint.conversation_id=sessions.conversation_id
   JOIN tutor_learning_tracks track ON track.id=sessions.track_id AND track.user_id=sessions.user_id AND track.version=sessions.track_version
   JOIN tutor_track_active_plans active ON active.track_id=sessions.track_id AND active.user_id=sessions.user_id AND active.revision_id=revision
   JOIN tutor_track_node_progress progress ON progress.track_id=sessions.track_id AND progress.user_id=sessions.user_id
     AND progress.knowledge_key=sessions.knowledge_key AND progress.version=sessions.progress_version
   JOIN tutor_lesson_assignments assignment ON assignment.id=sessions.lesson_assignment_id AND assignment.user_id=sessions.user_id
     AND assignment.track_id=sessions.track_id AND assignment.knowledge_key=sessions.knowledge_key AND assignment.status='active'
     AND assignment.assignment_version=sessions.assignment_version AND assignment.document_id=sessions.document_id
   WHERE scopes.run_id=(q->>'turn_id')::uuid AND scopes.user_id=(q->>'user_id')::uuid
     AND scopes.conversation_id=(q->>'conversation_id')::uuid AND scopes.teaching_session_id=(q->>'teaching_session_id')::uuid
     AND scopes.track_id=(q->>'learning_track_id')::uuid AND scopes.knowledge_key=q->>'knowledge_key'
     AND scopes.active_plan_revision_id=revision AND sessions.active_plan_revision_id=revision AND sessions.status IN ('active','paused')
     AND sessions.current_checkpoint_id=(q->>'checkpoint_id')::uuid AND sessions.version=(q->>'owner_context_version')::integer
     AND (scopes.track_version::text,scopes.progress_version::text,scopes.assignment_version::text)
       IS NOT DISTINCT FROM (q->>'track_version',q->>'progress_version',q->>'assignment_version')
     AND (sessions.track_version::text,sessions.progress_version::text,sessions.assignment_version::text)
       IS NOT DISTINCT FROM (q->>'track_version',q->>'progress_version',q->>'assignment_version')
     AND (scopes.checkpoint_id=checkpoint.id OR (checkpoint.source_run_id=scopes.run_id
       AND checkpoint.predecessor_checkpoint_id=scopes.checkpoint_id AND checkpoint.session_version=scopes.session_version+1)));
$$;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_teaching_request_current(jsonb,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.native_consumer_receipt_current(receipt_id uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
   -- Every selected native source is checked BEFORE any bank row lock.
   FOR consumption IN SELECT value FROM jsonb_array_elements(selected) LOOP
     IF item_supply_internal.native_consumer_source_current((consumption->>'proof_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
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
   IF item_supply_internal.native_consumer_source_current((original->>'proof_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
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
 -- All source locks have already been acquired before bank locks. Re-reading
 -- these fences rechecks time/revocation after a possible bank lock wait.
 IF r.mode='create' THEN
   FOR consumption IN SELECT value FROM jsonb_array_elements(selected) LOOP
     IF item_supply_internal.native_consumer_source_current((consumption->>'proof_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
   END LOOP;
 ELSE
   IF item_supply_internal.native_consumer_source_current(n.id) IS DISTINCT FROM true THEN RETURN false; END IF;
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_receipt_current(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.native_consumer_frozen_artifact_matches(q jsonb,a tutor_learning_artifacts) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT (q->>'user_id',q->>'conversation_id',q->>'turn_id',q->>'learning_track_id',q->>'knowledge_key',q->>'teaching_session_id',
   q->>'checkpoint_id',q->>'track_version',q->>'progress_version',q->>'assignment_version',q->>'owner_kind',q->>'owner_id',
   q->>'owner_version',q->>'owner_context_version',q->>'artifact_kind',q->>'purpose',q->>'difficulty',q->>'blocking',q->>'title',q->>'instruction_markdown')
 IS NOT DISTINCT FROM ((a).user_id::text,(a).conversation_id::text,(a).turn_id::text,(a).learning_track_id::text,(a).knowledge_key,(a).teaching_session_id::text,
   (a).checkpoint_id::text,(a).track_version::text,(a).progress_version::text,(a).assignment_version::text,(a).owner_kind,(a).owner_id::text,
   (a).owner_version::text,(a).owner_context_version::text,(a).artifact_kind,(a).purpose,(a).difficulty,(a).blocking::text,(a).title,(a).instruction_markdown)
 AND (a).owner_kind='learning_item' AND (a).artifact_kind='knowledge_check' AND (a).active_attempt_id IS NULL;
$$;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_frozen_artifact_matches(jsonb,tutor_learning_artifacts) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.native_artifact_owner_matches(a tutor_learning_artifacts,prior jsonb,historical boolean) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record; b record; creation jsonb;
BEGIN
 IF a.owner_kind<>'learning_item' OR a.artifact_kind<>'knowledge_check' OR a.active_attempt_id IS NOT NULL THEN RETURN false; END IF;
 IF prior IS NULL THEN
   SELECT * INTO r FROM tutor_item_supply_native_consumer_receipts
     WHERE mode='create' AND user_id=a.user_id AND run_id=a.turn_id AND version_id=a.owner_id AND txid=txid_current();
   RETURN FOUND AND item_supply_internal.native_consumer_frozen_artifact_matches(r.payload_json->'request',a)
     AND r.payload_json->'request'->'presentation'=a.presentation_json
     AND r.payload_json->'request'->'allowed_actions'=a.allowed_actions_json
     AND r.payload_json->'request'->>'state'=a.state
     AND item_supply_internal.native_consumer_receipt_current(r.id);
 END IF;
 SELECT bindings.* INTO b FROM tutor_item_supply_native_artifact_bindings bindings
   JOIN tutor_item_supply_user_epochs epoch ON epoch.user_id=bindings.user_id AND epoch.epoch=bindings.epoch AND epoch.enabled
   WHERE bindings.artifact_id=a.id AND bindings.user_id=a.user_id AND bindings.version_id=a.owner_id;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT payload_json INTO creation FROM tutor_item_supply_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';
 IF item_supply_internal.native_consumer_frozen_artifact_matches(creation->'request',a) IS DISTINCT FROM true THEN RETURN false; END IF;
 -- Only original 230's fully checked content-preserving supersession may use
 -- historical DATA alone. It has its own deferred terminal domain receipt.
 IF historical THEN RETURN true; END IF;
 IF a.version<>(prior->>'version')::integer+1 THEN RETURN false; END IF;
 SELECT * INTO r FROM tutor_item_supply_native_consumer_receipts
   WHERE artifact_id=a.id AND artifact_version=(prior->>'version')::integer AND user_id=a.user_id AND epoch=b.epoch
     AND mapping_id=b.mapping_id AND version_id=a.owner_id AND txid=txid_current()
     AND ((a.state='cancelled' AND mode='cancel' AND payload_json->>'action'='cancel')
       OR (a.state IN ('active','completed') AND mode='consume'
         AND payload_json->>'action' IN ('request_hint','request_direct_answer','respond')))
   ORDER BY created_at DESC,id DESC LIMIT 1;
 IF NOT FOUND THEN RETURN false; END IF;
 IF r.mode='cancel' AND (to_jsonb(a)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json'])
   IS DISTINCT FROM (prior-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json']) THEN RETURN false; END IF;
 IF r.mode='consume' AND ((r.payload_json->>'action'='respond' AND a.state<>'completed')
   OR (r.payload_json->>'action'<>'respond' AND a.state<>'active')) THEN RETURN false; END IF;
 RETURN item_supply_internal.native_consumer_receipt_current(r.id);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_native_consumer_receipt_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF item_supply_internal.native_consumer_receipt_current(NEW.id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native consumer requires exact original current transaction authority';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_native_consumer_receipt_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS native_consumer_receipt_insert ON tutor_item_supply_native_consumer_receipts;
CREATE TRIGGER native_consumer_receipt_insert AFTER INSERT ON tutor_item_supply_native_consumer_receipts
 FOR EACH ROW EXECUTE FUNCTION enforce_native_consumer_receipt_insert();

CREATE OR REPLACE FUNCTION enforce_native_artifact_binding_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a tutor_learning_artifacts; r record;
BEGIN
 SELECT * INTO a FROM tutor_learning_artifacts WHERE id=NEW.artifact_id AND user_id=NEW.user_id AND owner_id=NEW.version_id;
 SELECT * INTO r FROM tutor_item_supply_native_consumer_receipts WHERE id=NEW.creation_receipt_id
   AND user_id=NEW.user_id AND epoch=NEW.epoch AND mapping_id=NEW.mapping_id AND version_id=NEW.version_id AND mode='create';
 IF a.id IS NULL OR r.id IS NULL OR a.version<>1 OR r.run_id IS DISTINCT FROM a.turn_id
   OR item_supply_internal.native_consumer_frozen_artifact_matches(r.payload_json->'request',a) IS DISTINCT FROM true
   OR r.payload_json->'request'->'presentation' IS DISTINCT FROM a.presentation_json
   OR r.payload_json->'request'->'allowed_actions' IS DISTINCT FROM a.allowed_actions_json
   OR item_supply_internal.native_consumer_receipt_current(r.id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native consumer binding requires actual original Artifact';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_native_artifact_binding_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS native_artifact_binding_insert ON tutor_item_supply_native_artifact_bindings;
CREATE TRIGGER native_artifact_binding_insert BEFORE INSERT ON tutor_item_supply_native_artifact_bindings
 FOR EACH ROW EXECUTE FUNCTION enforce_native_artifact_binding_insert();

-- Sidecar capture only, never another Artifact writer or synthesized public li.
CREATE OR REPLACE FUNCTION capture_native_artifact_binding() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;
BEGIN
 IF NEW.owner_kind='learning_item' AND NEW.artifact_kind='knowledge_check'
   AND EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs proof
     WHERE proof.version_id=NEW.owner_id AND proof.proof_json->>'target_id'='python-kc-binding-v1')
   AND EXISTS(SELECT 1 FROM tutor_learning_item_practice_materializations mat
   JOIN tutor_exercise_versions e ON e.id=mat.exercise_version_id AND e.source_kind='registered_author'
   WHERE mat.version_id=NEW.owner_id) THEN
   SELECT * INTO r FROM tutor_item_supply_native_consumer_receipts WHERE mode='create' AND user_id=NEW.user_id
     AND run_id=NEW.turn_id AND version_id=NEW.owner_id AND txid=txid_current();
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native Artifact creation receipt missing'; END IF;
   INSERT INTO tutor_item_supply_native_artifact_bindings(artifact_id,user_id,epoch,version_id,mapping_id,creation_receipt_id)
     VALUES(NEW.id,NEW.user_id,r.epoch,r.version_id,r.mapping_id,r.id);
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION capture_native_artifact_binding() FROM PUBLIC;
DROP TRIGGER IF EXISTS native_artifact_binding_capture ON tutor_learning_artifacts;
CREATE TRIGGER native_artifact_binding_capture AFTER INSERT ON tutor_learning_artifacts
 FOR EACH ROW EXECUTE FUNCTION capture_native_artifact_binding();

DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['tutor_item_supply_native_consumer_receipts','tutor_item_supply_native_artifact_bindings'] LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS native_consumer_immutable ON %I',tab);
   EXECUTE format('CREATE TRIGGER native_consumer_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''private'')',tab);
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.purge_native_consumer_private(target_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF item_supply_internal.permitted(target_user) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native consumer purge requires original maintenance capability';
 END IF;
 DELETE FROM tutor_item_supply_native_consumer_receipts WHERE user_id=target_user AND mode<>'create';
 DELETE FROM tutor_item_supply_native_artifact_bindings WHERE user_id=target_user;
 DELETE FROM tutor_item_supply_native_consumer_receipts WHERE user_id=target_user;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_native_consumer_private(uuid) FROM PUBLIC;
CREATE OR REPLACE FUNCTION purge_native_consumer_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
   OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native consumer reset requires original permitted epoch advance';
 END IF;
 PERFORM item_supply_internal.purge_native_consumer_private(NEW.user_id);
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION purge_native_consumer_on_epoch_advance() FROM PUBLIC;
DROP TRIGGER IF EXISTS a00_native_consumer_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a00_native_consumer_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN (NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION purge_native_consumer_on_epoch_advance();

-- Exact effective230 prosrc/property guard. Neither 220 catalog resolver nor
-- its Attempt owner predicate is changed. Replay accepts only old or own body.
DO $upgrade$
DECLARE f record; original_definition text; changed_definition text;
 old_frame constant text := $old_frame$  ELSIF NEW.owner_kind='learning_item' THEN
    SELECT * INTO item_version_row
    FROM tutor_learning_item_versions
    WHERE id=NEW.owner_id
      AND knowledge_key=tutor_plan_catalog_knowledge_key(
        NEW.user_id, NEW.learning_track_id, session_row.active_plan_revision_id, NEW.knowledge_key
      );$old_frame$;
 new_frame constant text := $new_frame$  ELSIF NEW.owner_kind='learning_item' THEN
    -- A native publication cannot enter the curated equality fallback, even if
    -- a future original frozen catalog happens to equal its public finite key.
    IF EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs p
      JOIN tutor_learning_item_practice_materializations m ON m.id=p.materialization_id
      JOIN tutor_exercise_versions e ON e.id=m.exercise_version_id AND e.source_kind='registered_author'
      WHERE p.version_id=NEW.owner_id AND p.proof_json->>'target_id'='python-kc-binding-v1')
      AND item_supply_internal.native_artifact_owner_matches(
        NEW, CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) ELSE NULL END, historical_supersession) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='native Artifact exact original consumer authority required';
    END IF;
    SELECT * INTO item_version_row
    FROM tutor_learning_item_versions
    WHERE id=NEW.owner_id
      AND (knowledge_key=tutor_plan_catalog_knowledge_key(
        NEW.user_id, NEW.learning_track_id, session_row.active_plan_revision_id, NEW.knowledge_key
      ) OR item_supply_internal.native_artifact_owner_matches(
        NEW, CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) ELSE NULL END, historical_supersession));$new_frame$;
BEGIN
 SELECT p.*,l.lanname,encode(digest(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') AS body_hash
   INTO f FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
   WHERE n.nspname='public' AND p.proname='enforce_tutor_learning_artifact_owner_scope' AND p.pronargs=0;
 IF NOT FOUND OR f.lanname<>'plpgsql' OR f.prosecdef OR f.provolatile<>'v' OR f.proisstrict
   OR f.proconfig IS NOT NULL OR f.prorettype<>'trigger'::regtype OR f.prokind<>'f' THEN
   RAISE check_violation USING MESSAGE='native consumer receiver original properties changed';
 END IF;
 IF f.body_hash='a14181e7c43aacf9cb3d7ea9cbaaaca16a8aa4dfbc53e73994945edbb4457af1' THEN RETURN; END IF;
 IF f.body_hash<>'a8a9cf055295fb65aa35fed92698d3fa25f8c88bf518effce4e5d5ad81aa5cb2' THEN
   RAISE check_violation USING MESSAGE='native consumer receiver original fingerprint changed';
 END IF;
 original_definition:=replace(pg_get_functiondef(f.oid),E'\r\n',E'\n');
 IF position(old_frame IN original_definition)=0 THEN RAISE check_violation USING MESSAGE='native consumer receiver exact predicate missing'; END IF;
 changed_definition:=replace(original_definition,old_frame,new_frame);
 EXECUTE changed_definition;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=f.oid
   AND encode(digest(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex')='a14181e7c43aacf9cb3d7ea9cbaaaca16a8aa4dfbc53e73994945edbb4457af1') THEN
   RAISE check_violation USING MESSAGE='native consumer receiver resulting fingerprint changed';
 END IF;
END $upgrade$;




