-- PRIVATE native pack authority. Eight PRIVATE tables; 523 owns the ONE task journal.
-- No commits, provider/DB operator IO, GUC grants or shared receipt mode relabel.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
 RAISE check_violation USING MESSAGE='524 B1d only'; END IF; END $$;
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_quality_evidence (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
 pack_task_id uuid NOT NULL, slot_id uuid NOT NULL, root_id uuid NOT NULL, version_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN('validation','blind','review','admission','relation','investigation','normal')),
 job_id uuid NOT NULL, payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
 payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 checked_at timestamptz NOT NULL, valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(id,user_id,epoch,scope_id),
 FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(job_id,user_id,epoch) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(root_id,user_id,epoch) REFERENCES tutor_item_supply_private_budget_roots(id,user_id,epoch) ON DELETE RESTRICT
);

-- Receiver definitions follow all tables.
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_publications (
 id uuid PRIMARY KEY,user_id uuid NOT NULL,epoch bigint NOT NULL,scope_id uuid NOT NULL,
 pack_task_id uuid NOT NULL,slot_id uuid NOT NULL,root_id uuid NOT NULL,version_id uuid NOT NULL,
 quality_id uuid NOT NULL,state text NOT NULL CHECK(state IN('published','quarantined','retired')),
 state_version integer NOT NULL CHECK(state_version>0),predecessor_id uuid,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
 payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
 content_json jsonb NOT NULL CHECK(jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=16384),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(id,user_id,epoch,scope_id),UNIQUE(version_id,state_version,user_id,epoch),
 FOREIGN KEY(quality_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_quality_evidence(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(predecessor_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_publications(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_exposure_origins (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),sequence bigserial NOT NULL UNIQUE,user_id uuid NOT NULL,epoch bigint NOT NULL,
 artifact_id uuid NOT NULL REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,version_id uuid NOT NULL,
 origin_table text NOT NULL CHECK(origin_table IN('tutor_item_supply_private_native_artifact_bindings','tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts')),
 origin_id uuid NOT NULL,kind text NOT NULL CHECK(kind IN('shown','hint','direct_answer','attempted','transfer')),
 binding_hash text NOT NULL CHECK(binding_hash ~ '^[0-9a-f]{64}$'),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(user_id,epoch,origin_table,origin_id),UNIQUE(id,user_id,epoch),
 FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_exposure_snapshots (
 id uuid PRIMARY KEY,user_id uuid NOT NULL,epoch bigint NOT NULL,public_snapshot_id uuid NOT NULL,
 private_watermark bigint NOT NULL CHECK(private_watermark>=0),private_count integer NOT NULL CHECK(private_count BETWEEN 0 AND 4096),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=8388608),
 payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 checked_at timestamptz NOT NULL,valid_until timestamptz NOT NULL CHECK(valid_until>checked_at AND valid_until<=checked_at+interval '30 seconds'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(id,user_id,epoch),
 FOREIGN KEY(public_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_type_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_eligibility (
 id uuid PRIMARY KEY,user_id uuid NOT NULL,epoch bigint NOT NULL,scope_id uuid NOT NULL,pack_task_id uuid NOT NULL,
 mapping_id uuid NOT NULL,exposure_snapshot_id uuid NOT NULL,payload_json jsonb NOT NULL
 CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
 payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 checked_at timestamptz NOT NULL,valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),txid bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(id,user_id,epoch,scope_id),
 FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(mapping_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_private_native_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_assessment_reservations (
 id uuid PRIMARY KEY,user_id uuid NOT NULL,epoch bigint NOT NULL,scope_id uuid NOT NULL,pack_task_id uuid NOT NULL,
 operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 3 AND 160),eligibility_id uuid NOT NULL,
 exposure_snapshot_id uuid NOT NULL,base_reservation_id uuid NOT NULL,base_scope_id uuid NOT NULL,payload_json jsonb NOT NULL
 CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576),
 payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(id,user_id,epoch,scope_id),UNIQUE(user_id,epoch,operation_key),
 FOREIGN KEY(eligibility_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_eligibility(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_private_native_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(base_reservation_id,user_id,epoch,base_scope_id) REFERENCES tutor_item_supply_type_exposure_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_consumer_receipts (
 id uuid PRIMARY KEY,user_id uuid NOT NULL,epoch bigint NOT NULL,scope_id uuid NOT NULL,pack_task_id uuid NOT NULL,
 mode text NOT NULL CHECK(mode IN('create','current','cancel')),action text CHECK(action IN('request_hint','request_direct_answer','respond','cancel')),
 run_id uuid REFERENCES tutor_runs(id) ON DELETE RESTRICT,artifact_id uuid REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
 artifact_version integer,version_id uuid NOT NULL,reservation_id uuid,eligibility_id uuid,exposure_snapshot_id uuid,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576),
 payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
 checked_at timestamptz NOT NULL,valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),txid bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(id,user_id,epoch,scope_id),
 FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_assessment_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(eligibility_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_eligibility(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_private_native_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT,
 CHECK((mode='create' AND action IS NULL AND artifact_id IS NULL AND run_id IS NOT NULL AND reservation_id IS NOT NULL AND eligibility_id IS NOT NULL AND exposure_snapshot_id IS NOT NULL)
 OR(mode IN('current','cancel') AND artifact_id IS NOT NULL AND artifact_version IS NOT NULL AND action IS NOT NULL AND (mode='cancel')=(action='cancel')))
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_native_artifact_bindings (
 artifact_id uuid PRIMARY KEY REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,user_id uuid NOT NULL,epoch bigint NOT NULL,
 scope_id uuid NOT NULL,pack_task_id uuid NOT NULL,version_id uuid NOT NULL,creation_receipt_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(artifact_id,user_id,epoch),
 FOREIGN KEY(creation_receipt_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_consumer_receipts(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT
);

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
REVOKE ALL ON FUNCTION item_supply_internal.private_native_source_current(jsonb) FROM PUBLIC;


CREATE OR REPLACE FUNCTION item_supply_internal.private_native_epoch(u uuid,e bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 PERFORM item_supply_internal.native_exposure_lock(u,e);
 IF current_setting('transaction_isolation')<>'read committed' OR NOT EXISTS(
  SELECT 1 FROM tutor_item_supply_user_epochs WHERE user_id=u AND epoch=e AND enabled) THEN
  RAISE check_violation USING MESSAGE='524 current private epoch/read committed required'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_epoch(uuid,bigint) FROM PUBLIC;

-- B523 owns the task and exact logical slots. This is a READ-ONLY private receiver.
CREATE OR REPLACE FUNCTION item_supply_internal.private_pack_slot_current(
 task uuid,slot uuid,item uuid,root uuid,u uuid,e bigint,scope uuid,job uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE t record;c record;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task
  AND user_id=u AND epoch=e AND scope_id=scope AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(t.payload_json->'slots') s
  WHERE s->>'slot_id'=slot::text AND s->>'logical_item_id'=item::text) THEN RETURN false; END IF;
 SELECT j.root_id,j.scope_id,c.* INTO c FROM tutor_item_supply_private_jobs j JOIN tutor_item_supply_private_job_controls c
  ON c.job_id=j.id AND c.user_id=j.user_id AND c.epoch=j.epoch
  WHERE j.id=job AND j.user_id=u AND j.epoch=e AND j.root_id=root AND j.scope_id=scope FOR SHARE OF j,c;
 IF NOT FOUND OR c.state NOT IN('leased','generating','validating','reviewing','investigating','revising','simulating','admitting') THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal ph
  WHERE ph.pack_task_id=task AND ph.user_id=u AND ph.epoch=e AND ph.scope_id=scope AND ph.record_kind='phase'
  AND ph.payload_json->>'schema_version'='private_native_phase_v1' AND ph.payload_json->>'root_id'=root::text
  AND ph.payload_json->>'job_id'=job::text AND ph.payload_json->>'slot_id'=slot::text
  AND ph.payload_json->>'business_item_id'=item::text
  AND ph.payload_json->'lease'->>'generation'=c.lease_generation::text
  AND ph.payload_json->'lease'->>'lease_owner'=c.lease_owner
  AND (ph.payload_json->>'valid_until')::timestamptz>clock_timestamp()) THEN RETURN false; END IF;
 stamp:=clock_timestamp();
 RETURN c.lease_expires_at>stamp AND c.parent_deadline>stamp;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_slot_current(uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_mapping_current(mid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE m record;n jsonb;s record;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO m FROM tutor_item_supply_finite_course_mappings WHERE id=mid AND user_id=u AND epoch=e FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 private original mapping missing'; END IF;
 n:=m.receipt_json->'frozen_node';
 PERFORM 1 FROM tutor_track_active_plans p JOIN tutor_track_plan_nodes node
 ON node.revision_id=p.revision_id AND node.track_id=p.track_id AND node.user_id=p.user_id
 WHERE p.user_id=u AND p.track_id=(n->>'track_id')::uuid AND p.revision_id=(n->>'revision_id')::uuid
 AND node.id=(n->>'node_id')::uuid AND node.knowledge_key=n->>'knowledge_key'
 AND node.title IS NOT DISTINCT FROM n->>'title' AND node.description IS NOT DISTINCT FROM n->>'description'
 AND node.is_core::text IS NOT DISTINCT FROM n->>'is_core' AND node.prerequisite_keys_json IS NOT DISTINCT FROM n->'prerequisite_keys'
 AND node.required_capabilities_json IS NOT DISTINCT FROM n->'required_capabilities'
 AND node.catalog_knowledge_key IS NOT DISTINCT FROM n->>'catalog_knowledge_key' FOR SHARE OF p,node;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 current actual goal missing'; END IF;
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
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 current original confirmed plan required'; END IF;
 RETURN m.receipt_json;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_mapping_current(uuid,uuid,bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_publication_current(v uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE pub record;q record;latest record;version record;mat jsonb;mapping jsonb;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE version_id=v AND user_id=u AND epoch=e
 AND state='published' ORDER BY state_version LIMIT 1;
 SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=pub.quality_id AND user_id=u AND epoch=e AND kind='admission';
 IF pub.id IS NULL OR q.id IS NULL OR q.payload_json->>'schema_version'<>'private_native_quality_v1'
  OR pub.payload_json->>'quality_hash'<>q.payload_hash
  OR NOT(q.checked_at<=(pub.payload_json->>'checked_at')::timestamptz AND (pub.payload_json->>'checked_at')::timestamptz<q.valid_until)
  OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 private historical quality/current source required'; END IF;
 -- Old producer is HISTORY, not a current lease requirement.
 SELECT * INTO version FROM tutor_item_supply_private_versions WHERE id=v AND user_id=u AND epoch=e FOR SHARE;
 SELECT * INTO latest FROM tutor_item_supply_private_native_publications WHERE version_id=v AND user_id=u AND epoch=e ORDER BY state_version DESC LIMIT 1;
 IF latest.state IS DISTINCT FROM 'published' OR latest.id IS DISTINCT FROM pub.id
  OR version.handle IS DISTINCT FROM pub.payload_json->>'item_handle'
  OR version.public_json IS DISTINCT FROM q.payload_json->'source'->'public'
  OR version.private_json IS DISTINCT FROM q.payload_json->'source'->'private' THEN
  RAISE check_violation USING MESSAGE='524 private content retired or identity changed'; END IF;
 PERFORM 1 FROM tutor_exercise_versions x JOIN tutor_exercise_private_rubrics r ON r.exercise_version_id=x.id
 WHERE x.id=pub.exercise_version_id AND x.source_kind='registered_author'
 AND x.content_hash=pub.payload_json->>'exercise_content_hash' AND r.rubric_hash=pub.payload_json->>'rubric_hash';
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 actual original exercise/rubric missing'; END IF;
 mapping:=item_supply_internal.private_native_mapping_current((q.payload_json->'ref'->>'mapping_receipt_id')::uuid,u,e);
 IF mapping->>'target_definition_hash' IS DISTINCT FROM q.payload_json->'spec'->>'target_definition_hash'
  OR q.payload_json->'source'->'blueprint'->>'knowledge_key' IS DISTINCT FROM 'finite.'||(mapping->>'target_id')
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(mapping->'pack_request'->'demands') d
    WHERE d->>'slot'=q.payload_json->'ref'->>'slot' AND d->>'storage_scope_id'=q.payload_json->'ref'->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 private exact finite goal bridge required'; END IF;
 IF item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 source stale after bank wait'; END IF;
 RETURN pub.payload_json;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_publication_current(uuid,uuid,bigint) FROM PUBLIC;

-- ONE B523 journal; PRIVATE phases reuse original private job/root/reservation owners.
CREATE OR REPLACE FUNCTION item_supply_internal.private_pack_bind_phase(r jsonb,l jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE t record;j record;c record;prior record;entry jsonb;rid uuid:=gen_random_uuid();stamp timestamptz;deadline timestamptz;p jsonb;
BEGIN
 PERFORM item_supply_internal.private_native_epoch((r->>'user_id')::uuid,(r->>'epoch')::bigint);
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(r->>'pack_task_id')::uuid
  AND pack_task_id=id AND record_kind='task' AND user_id=(r->>'user_id')::uuid
  AND epoch=(r->>'epoch')::bigint AND scope_id=(r->>'scope_id')::uuid FOR SHARE;
 SELECT s INTO entry FROM jsonb_array_elements(t.payload_json->'slots') s
  WHERE s->>'slot_id'=r->>'slot_id' AND s->>'logical_item_id'=r->>'business_item_id';
 IF t.id IS NULL OR entry IS NULL OR l->>'visibility' IS DISTINCT FROM 'private'
  OR l->>'owner_id' IS DISTINCT FROM r->>'user_id' OR l->>'owner_epoch' IS DISTINCT FROM r->>'epoch' THEN
  RAISE check_violation USING MESSAGE='524 original fixed PRIVATE task/slot/lease required'; END IF;
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=(l->>'job_id')::uuid AND user_id=t.user_id
  AND epoch=t.epoch AND scope_id=t.scope_id AND root_id=(r->>'root_id')::uuid FOR SHARE;
 SELECT * INTO c FROM tutor_item_supply_private_job_controls WHERE job_id=j.id AND user_id=t.user_id AND epoch=t.epoch FOR SHARE;
 stamp:=clock_timestamp();deadline:=LEAST(c.lease_expires_at,c.parent_deadline,(l->>'expires_at')::timestamptz,(l->>'parent_deadline')::timestamptz,
  (l->'profile'->>'bound_at')::timestamptz+(l->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF j.id IS NULL OR c.state NOT IN('leased','generating','validating','reviewing','investigating','revising','simulating','admitting') OR c.lease_owner IS DISTINCT FROM l->>'lease_owner'
  OR c.lease_generation::text IS DISTINCT FROM l->>'generation' OR deadline IS NULL OR stamp>=deadline THEN
  RAISE check_violation USING MESSAGE='524 current original PRIVATE job control required'; END IF;
 -- Each PRIVATE domain root is fixed for this task, including after technical expiry.
 SELECT * INTO prior FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=t.id
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1;
 IF prior.id IS NOT NULL AND prior.payload_json->>'root_id' IS DISTINCT FROM r->>'root_id' THEN
  RAISE check_violation USING MESSAGE='524 PRIVATE canonical root cannot reroll'; END IF;
 p:=jsonb_build_object('schema_version','private_native_phase_v1','root_id',r->>'root_id','job_id',l->>'job_id',
  'slot_id',r->>'slot_id','business_item_id',r->>'business_item_id','goal_scope_id',r->>'goal_scope_id',
  'ref',r,'lease',l,'valid_until',deadline);
 PERFORM item_supply_internal.assert_private_native_phase(p,t.user_id,t.epoch,t.scope_id,t.id);
 PERFORM item_supply_internal.private_native_mapping_current((r->>'mapping_receipt_id')::uuid,t.user_id,t.epoch);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_finite_course_mappings m,
  LATERAL jsonb_array_elements(m.receipt_json->'pack_request'->'demands') d
  WHERE m.id=(r->>'mapping_receipt_id')::uuid AND m.user_id=t.user_id AND m.epoch=t.epoch
  AND d->>'slot'=r->>'slot' AND d->>'storage_scope_id'=r->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 real role goal scope required, not copied storage scope'; END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal
  (id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(rid,t.id,t.user_id,t.epoch,t.scope_id,'phase','private.phase.'||j.id::text,t.intent_hash,p)
 ON CONFLICT(user_id,epoch,operation_key,record_kind) DO NOTHING RETURNING id INTO rid;
 IF rid IS NULL THEN SELECT id INTO rid FROM tutor_item_supply_private_persistent_pack_journal
  WHERE user_id=t.user_id AND epoch=t.epoch AND operation_key='private.phase.'||j.id::text AND record_kind='phase'
  AND payload_hash=item_supply_internal.snapshot_hash(p);
  IF rid IS NULL THEN RAISE check_violation USING MESSAGE='524 private phase identity conflict'; END IF; END IF;
 RETURN rid;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_bind_phase(jsonb,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_pack_prepare_auxiliary(
 task uuid,preparation uuid,job uuid,reservation uuid,payload jsonb,deadline timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
 INSERT INTO tutor_item_supply_private_persistent_pack_journal
  (id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(preparation,task,t.user_id,t.epoch,t.scope_id,'private_attachment','private.aux.'||preparation::text,t.intent_hash,
  jsonb_build_object('schema_version','private_native_auxiliary_v1','job_id',job,'reservation_id',reservation,'request',payload,'valid_until',deadline));
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_prepare_auxiliary(uuid,uuid,uuid,uuid,jsonb,timestamptz) FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.private_pack_auxiliary_committed(task uuid,preparation uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p record;
BEGIN
 SELECT * INTO p FROM tutor_item_supply_private_persistent_pack_journal WHERE id=preparation AND pack_task_id=task
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND xmin::text::bigint<>(txid_current()%4294967296);
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(p.user_id,p.epoch);
 RETURN clock_timestamp()<(p.payload_json->>'valid_until')::timestamptz;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_auxiliary_committed(uuid,uuid) FROM PUBLIC;

-- PRIVATE reset child order precedes523 a00z and the original502/440 owners.
CREATE OR REPLACE FUNCTION item_supply_internal.purge_private_native_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE owned_exercises uuid[];
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch<>OLD.epoch+1
  OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 original maintenance epoch permit required'; END IF;
 SELECT array_agg(DISTINCT exercise_version_id) INTO owned_exercises FROM tutor_item_supply_private_native_publications WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_consumer_receipts WHERE user_id=OLD.user_id AND mode<>'create';
 DELETE FROM tutor_item_supply_private_native_artifact_bindings WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_consumer_receipts WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_assessment_reservations WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_eligibility WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_exposure_snapshots WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_exposure_origins WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_publications WHERE user_id=OLD.user_id;
 -- Quality still proves PRIVATE ownership while original immutable guards check
 -- the actual maintenance permit. Any foreign/public dependency aborts reset.
 DELETE FROM tutor_exercise_private_rubrics WHERE exercise_version_id=ANY(owned_exercises);
 DELETE FROM tutor_exercise_versions WHERE id=ANY(owned_exercises);
 DELETE FROM tutor_item_supply_private_native_quality_evidence WHERE user_id=OLD.user_id;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_private_native_on_epoch_advance() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a000_private_native_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN(NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION item_supply_internal.purge_private_native_on_epoch_advance();
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY[
 'tutor_item_supply_private_native_quality_evidence','tutor_item_supply_private_native_publications',
 'tutor_item_supply_private_native_exposure_origins','tutor_item_supply_private_native_exposure_snapshots',
 'tutor_item_supply_private_native_eligibility','tutor_item_supply_private_native_assessment_reservations',
 'tutor_item_supply_private_native_consumer_receipts','tutor_item_supply_private_native_artifact_bindings'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS private_native_immutable ON %I',t);
 EXECUTE format('CREATE TRIGGER private_native_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(%L)',t,'private');
 END LOOP; END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_quality_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE ph record;v record;a record;p jsonb:=NEW.payload_json;ref jsonb;b jsonb;rr jsonb;stage record;stamp timestamptz;
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
  OR a.source_json->'private' IS DISTINCT FROM v.private_json OR v.handle IS DISTINCT FROM 'lip:v2:'||NEW.version_id::text THEN
  RAISE check_violation USING MESSAGE='524 actual original private generation/version required'; END IF;
 IF NEW.kind='validation' THEN
  IF p->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2'
   OR p->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR p->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash' THEN
   RAISE check_violation USING MESSAGE='524 original candidate validation required'; END IF;
 ELSIF NEW.kind='blind' THEN
  IF p->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR p->'binding'->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR p->'binding'->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR p->'run'->'provider_identity'->>'identity' IS NULL THEN
   RAISE check_violation USING MESSAGE='524 original bound blind run required'; END IF;
 ELSIF NEW.kind IN('review','admission') THEN
  IF p->'ref' IS DISTINCT FROM ref OR (p->'lease'-'state_version') IS DISTINCT FROM (ph.payload_json->'lease'-'state_version') THEN
   RAISE check_violation USING MESSAGE='524 PRIVATE review/ref/lease binding required'; END IF;
  b:=p->'bundle';
  IF b->>'mode' IS DISTINCT FROM 'peer_blind' OR b->>'state' IS DISTINCT FROM 'completed'
   OR b->>'publication_enabled' IS DISTINCT FROM 'false' OR jsonb_array_length(b->'reports') IS DISTINCT FROM 6
   OR b->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR b->'binding'->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR b->'binding'->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR (SELECT count(DISTINCT r->>'role') FROM jsonb_array_elements(b->'reports') r)<>6
   OR (SELECT array_agg(r->>'role' ORDER BY r->>'role') FROM jsonb_array_elements(b->'reports') r)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
   OR (SELECT count(DISTINCT r->'run'->'provider_identity'->>'identity') FROM jsonb_array_elements(b->'reports') r)<>6
   OR (SELECT count(DISTINCT r->'run'->>'run_id') FROM jsonb_array_elements(b->'reports') r)<>6 THEN
   RAISE check_violation USING MESSAGE='524 full independent six-peer bundle required'; END IF;
  FOR rr IN SELECT value FROM jsonb_array_elements(b->'reports') LOOP
   IF rr->'binding' IS DISTINCT FROM b->'binding'
    OR rr->'run'->'provider_identity'->>'identity' IN(b->>'author_identity',b->'blind_solve'->'run'->'provider_identity'->>'identity')
    OR rr->'run'->>'run_id'=b->'blind_solve'->'run'->>'run_id' THEN
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_quality_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_quality_insert ON tutor_item_supply_private_native_quality_evidence;
CREATE TRIGGER private_native_quality_insert BEFORE INSERT ON tutor_item_supply_private_native_quality_evidence
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_quality_insert();

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_publication_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE q record;v record;prev record;p jsonb:=NEW.payload_json;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=NEW.quality_id AND kind='admission'
  AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND pack_task_id=NEW.pack_task_id
  AND slot_id=NEW.slot_id AND root_id=NEW.root_id AND version_id=NEW.version_id;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 exact private original admission required'; END IF;
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
   OR p->>'item_handle' IS DISTINCT FROM v.handle OR p->>'exercise_version_id' IS DISTINCT FROM NEW.exercise_version_id::text
   OR p->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(q.payload_json->'source')
   OR p->>'content_hash' IS DISTINCT FROM q.payload_json->'bundle'->'binding'->>'content_hash'
   OR NEW.content_json->>'item_handle' IS DISTINCT FROM v.handle
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_publication_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_publication_insert ON tutor_item_supply_private_native_publications;
CREATE TRIGGER private_native_publication_insert BEFORE INSERT ON tutor_item_supply_private_native_publications
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_publication_insert();

-- PRIVATE storage scope is the single original assessment-wallet scope; source
-- blueprint domain/purpose belongs to the actual mapped ROLE goal, never a copy.
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_generation_goal_current(g jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE ph record;m jsonb;d jsonb;ref jsonb;bp jsonb:=g->'source_json'->'blueprint';
BEGIN
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=(g->>'user_id')::uuid
  AND epoch=(g->>'epoch')::bigint AND scope_id=(g->>'scope_id')::uuid AND record_kind='phase'
  AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=g->>'job_id';
 IF NOT FOUND OR g->>'mode' IS DISTINCT FROM 'live' THEN RETURN false; END IF;
 ref:=ph.payload_json->'ref';
 IF item_supply_internal.private_pack_slot_current(ph.pack_task_id,(ref->>'slot_id')::uuid,
  (ref->>'business_item_id')::uuid,(ref->>'root_id')::uuid,ph.user_id,ph.epoch,ph.scope_id,(g->>'job_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
 m:=item_supply_internal.private_native_mapping_current((ref->>'mapping_receipt_id')::uuid,ph.user_id,ph.epoch);
 SELECT value INTO d FROM jsonb_array_elements(m->'pack_request'->'demands')
  WHERE value->>'slot'=ref->>'slot' AND value->>'storage_scope_id'=ref->>'goal_scope_id';
 IF d IS NULL OR bp->>'knowledge_key' IS DISTINCT FROM 'finite.'||(m->>'target_id')
  OR bp->>'language_id' IS DISTINCT FROM d->'demand'->'scope'->>'language_id'
  OR bp->>'item_kind' IS DISTINCT FROM d->'demand'->'scope'->>'item_kind'
  OR bp->>'purpose' IS DISTINCT FROM d->'demand'->'scope'->>'purpose'
  OR g->'request_json'->>'item_key' NOT LIKE 'private-native.%'
  OR g->'source_json'->'public'->>'item_key' IS DISTINCT FROM g->'request_json'->>'item_key'
  OR g->'request_json'->'blueprint' IS DISTINCT FROM bp THEN RETURN false; END IF;
 RETURN item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,
  'request',g->'request_json','source_receipts',g->'receipt_json'->'sources'));
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_generation_goal_current(jsonb) FROM PUBLIC;

DO $generation_guard524$ DECLARE p record; BEGIN
 SELECT f.*,l.lanname INTO p FROM pg_proc f JOIN pg_language l ON l.oid=f.prolang
  WHERE f.oid='enforce_item_supply_pipeline_artifact()'::regprocedure;
 IF p.prokind<>'f' OR p.lanname<>'plpgsql' OR NOT p.prosecdef OR p.prorettype<>'trigger'::regtype
  OR p.pronargs<>0 OR p.proretset OR p.proisstrict OR p.provolatile<>'v'
  OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') NOT IN('4c61f09a5cdb6eeb1c7748bdbc023f487110da92146499e698493842b754edb1','a94d5166719e553151a2f644c0631ce370d838b32287c9a2e20d73f5d3cda7d9') THEN
  RAISE check_violation USING MESSAGE='524 unknown original470 pipeline receiver'; END IF;
END $generation_guard524$;
CREATE OR REPLACE FUNCTION enforce_item_supply_pipeline_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE control record; generation_facts record; version_facts record; scope_facts jsonb; scope_hash text; source_snapshot jsonb; expected_content text; expected_schema text;
BEGIN
  IF NEW.mode='synthetic' AND current_database() NOT IN ('aearn_b1b_fixture_20260930','aearn_b1d_sandbox_20261001') THEN
    RAISE check_violation USING MESSAGE='synthetic pipeline outside fixture';
  END IF;
  IF current_database()='aearn_b1d_sandbox_20261001' AND NOT EXISTS(
    SELECT 1 FROM users WHERE id=NEW.user_id AND display_name=('sandbox.p6.'||NEW.user_id::text) AND deleted_at IS NULL) THEN
    RAISE check_violation USING MESSAGE='synthetic sandbox actor required';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_private_job_controls
    WHERE job_id=NEW.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
  IF NOT FOUND OR control.lease_generation<>NEW.lease_generation OR control.state_version<>NEW.lease_state_version
    OR control.state NOT IN ('leased','generating','validating','reviewing','investigating','revising','simulating','admitting')
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp() OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale pipeline artifact lease';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_generation_artifacts' THEN
    source_snapshot:=NEW.source_json;
    SELECT public_json,private_json,candidate_id INTO version_facts FROM tutor_item_supply_private_versions
      WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    SELECT snapshot_json,tutor_item_supply_private_scopes.scope_hash INTO scope_facts,scope_hash FROM tutor_item_supply_private_scopes
      WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',source_snapshot->'public'->>'item_key','version',source_snapshot->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(source_snapshot->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(source_snapshot->'public'),
      'private_hash',item_supply_internal.snapshot_hash(source_snapshot->'private')));
    IF version_facts.candidate_id IS DISTINCT FROM NEW.candidate_id
      OR version_facts.public_json IS DISTINCT FROM source_snapshot->'public'
      OR version_facts.private_json IS DISTINCT FROM source_snapshot->'private'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(source_snapshot)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM scope_hash
      OR (NEW.mode='live' AND (
        NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
        OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array'
        OR jsonb_array_length(NEW.receipt_json->'sources')=0
        OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.receipt_json->'sources') AS s
                  WHERE s->>'mode' IS DISTINCT FROM 'current_authority')))
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.receipt_json->>'candidate_id'
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM NEW.receipt_json->>'scope_hash'
      OR NEW.request_json->'blueprint' IS DISTINCT FROM source_snapshot->'blueprint'
      OR ((source_snapshot->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope_facts->>'knowledge_key'
        OR source_snapshot->'blueprint'->>'language_id' IS DISTINCT FROM scope_facts->>'language_id'
        OR source_snapshot->'blueprint'->>'item_kind' IS DISTINCT FROM scope_facts->>'item_kind'
        OR source_snapshot->'blueprint'->>'purpose' IS DISTINCT FROM scope_facts->>'purpose')
       AND item_supply_internal.private_native_generation_goal_current(to_jsonb(NEW)) IS DISTINCT FROM true) THEN
      RAISE check_violation USING MESSAGE='pipeline source identity mismatch';
    END IF;
  ELSE
    SELECT source_hash,mode,candidate_id,version_id INTO generation_facts
      FROM tutor_item_supply_private_generation_artifacts
      WHERE id=NEW.generation_artifact_id AND user_id=NEW.user_id AND epoch=NEW.epoch
        AND scope_id=NEW.scope_id AND job_id=NEW.job_id AND version_id=NEW.version_id
        AND content_hash=NEW.content_hash;
    IF NOT FOUND OR generation_facts.mode IS DISTINCT FROM NEW.mode THEN
      RAISE check_violation USING MESSAGE='pipeline generation identity mismatch';
    END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN 'item_supply_review_bundle_v2'
      WHEN 'admission_evaluation' THEN 'item_supply_admission_evaluation_v2' END;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',NEW.payload_json->'binding'->>'content_hash') IS DISTINCT FROM NEW.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',NEW.payload_json->'binding'->>'source_hash') IS DISTINCT FROM generation_facts.source_hash
      OR (NEW.payload_json ? 'binding' AND (
        NEW.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM generation_facts.candidate_id::text
        OR NEW.payload_json->'binding'->>'version_key' IS DISTINCT FROM generation_facts.version_id::text))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='pipeline receipt identity mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_pipeline_artifact() FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.capture_private_native_exposure_origin() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE b record;p record;k text;origin uuid;aid uuid;
BEGIN
 aid:=CASE WHEN TG_TABLE_NAME='tutor_item_supply_private_native_artifact_bindings' THEN NEW.artifact_id ELSE NEW.artifact_id END;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=aid AND user_id=NEW.user_id;
 IF NOT FOUND THEN RETURN NEW; END IF;
 PERFORM item_supply_internal.private_native_epoch(b.user_id,b.epoch);
 IF TG_TABLE_NAME='tutor_item_supply_private_native_artifact_bindings' THEN k:='shown';origin:=NEW.artifact_id;
 ELSIF TG_TABLE_NAME='tutor_knowledge_check_assistance_receipts' THEN
  k:=CASE NEW.assistance_kind WHEN 'hint' THEN 'hint' WHEN 'direct_answer' THEN 'direct_answer' ELSE NULL END;origin:=NEW.id;
 ELSE
  k:=CASE WHEN NEW.event_kind='created' THEN 'shown'
   WHEN NEW.action_kind='request_hint' THEN 'hint' WHEN NEW.action_kind='request_direct_answer' THEN 'direct_answer'
   WHEN NEW.action_kind='respond' THEN 'attempted' ELSE NULL END;origin:=NEW.id;
 END IF;
 IF k IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO p FROM tutor_item_supply_private_native_publications WHERE version_id=b.version_id AND user_id=b.user_id
  AND epoch=b.epoch AND state='published' ORDER BY state_version LIMIT 1;
 IF p.id IS NULL THEN RAISE check_violation USING MESSAGE='524 private exposure actual historical content required'; END IF;
 INSERT INTO tutor_item_supply_private_native_exposure_origins(user_id,epoch,artifact_id,version_id,origin_table,origin_id,kind,binding_hash)
 VALUES(b.user_id,b.epoch,aid,b.version_id,TG_TABLE_NAME,origin,k,item_supply_internal.snapshot_hash(p.content_json)) ON CONFLICT DO NOTHING;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.capture_private_native_exposure_origin() FROM PUBLIC;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tutor_item_supply_private_native_artifact_bindings',
 'tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS a001_private_native_exposure_capture ON %I',t);
 EXECUTE format('CREATE TRIGGER a001_private_native_exposure_capture AFTER INSERT ON %I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.capture_private_native_exposure_origin()',t);
 END LOOP; END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_exposure_origin_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE b record;p record;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 IF pg_trigger_depth()<2 THEN RAISE check_violation USING MESSAGE='524 private exposure concrete original trigger only'; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=NEW.artifact_id
  AND user_id=NEW.user_id AND epoch=NEW.epoch AND version_id=NEW.version_id;
 SELECT * INTO p FROM tutor_item_supply_private_native_publications WHERE version_id=NEW.version_id AND user_id=NEW.user_id
  AND epoch=NEW.epoch AND state='published' ORDER BY state_version LIMIT 1;
 IF b.artifact_id IS NULL OR p.id IS NULL OR NEW.binding_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(p.content_json) THEN
  RAISE check_violation USING MESSAGE='524 private original exposure identity required'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_exposure_origin_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_exposure_origin_insert ON tutor_item_supply_private_native_exposure_origins;
CREATE TRIGGER private_native_exposure_origin_insert BEFORE INSERT ON tutor_item_supply_private_native_exposure_origins
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_exposure_origin_insert();
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_exposure_hooks_current() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT item_supply_internal.native_exposure_hooks_current() AND count(*)=3 FROM pg_trigger t
 WHERE t.tgname='a001_private_native_exposure_capture' AND NOT t.tgisinternal AND t.tgenabled='O'
 AND t.tgtype=5 AND t.tgfoid='item_supply_internal.capture_private_native_exposure_origin()'::regprocedure
 AND t.tgrelid IN('tutor_item_supply_private_native_artifact_bindings'::regclass,
 'tutor_learning_artifact_events'::regclass,'tutor_knowledge_check_assistance_receipts'::regclass);
$$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_exposure_hooks_current() FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_exposure_current(sid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE s record;pub jsonb;records jsonb;n bigint;w bigint;expected text;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 IF item_supply_internal.private_native_exposure_hooks_current() IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 complete private exposure hooks required'; END IF;
 -- Unknown historical private bindings/artifacts cannot be relabelled empty.
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_bindings WHERE user_id=u AND epoch=e)
  OR EXISTS(SELECT 1 FROM tutor_learning_artifacts a JOIN tutor_item_supply_private_versions v ON v.id=a.owner_id
   AND v.user_id=a.user_id AND v.epoch=e WHERE a.user_id=u AND a.owner_kind='learning_item'
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_artifact_bindings b WHERE b.artifact_id=a.id AND b.user_id=u AND b.epoch=e)) THEN
  RAISE check_violation USING MESSAGE='524 historical private exposure unproven'; END IF;
 SELECT * INTO s FROM tutor_item_supply_private_native_exposure_snapshots WHERE id=sid AND user_id=u AND epoch=e;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 exact private exposure snapshot required'; END IF;
 pub:=item_supply_internal.type_exposure_current(s.public_snapshot_id,u,e);
 SELECT count(*),COALESCE(max(sequence),0) INTO n,w FROM tutor_item_supply_private_native_exposure_origins WHERE user_id=u AND epoch=e;
 IF pub IS NULL OR n<>s.private_count OR w<>s.private_watermark THEN
  RAISE check_violation USING MESSAGE='524 private/public exposure watermark changed'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_artifact_bindings b WHERE b.user_id=u AND b.epoch=e
  AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_exposure_origins o WHERE o.user_id=u AND o.epoch=e
   AND o.origin_table='tutor_item_supply_private_native_artifact_bindings' AND o.origin_id=b.artifact_id AND o.kind='shown')) THEN
  RAISE check_violation USING MESSAGE='524 private shown origin incomplete'; END IF;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('event_id',o.id,'item_handle',p.content_json->>'item_handle',
  'content_hash',p.content_json->>'content_hash','family_id',q.payload_json->'spec'->'allocation'->>'family_id',
  'semantic_signature',q.payload_json->'spec'->>'family_definition_hash','kind',o.kind,'content',p.content_json) ORDER BY o.sequence),'[]'::jsonb)
 INTO records FROM tutor_item_supply_private_native_exposure_origins o
 JOIN tutor_item_supply_private_native_publications p ON p.version_id=o.version_id AND p.user_id=o.user_id AND p.epoch=o.epoch AND p.state_version=1
 JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id AND q.user_id=p.user_id AND q.epoch=p.epoch
 WHERE o.user_id=u AND o.epoch=e AND o.binding_hash=item_supply_internal.snapshot_hash(p.content_json);
 IF jsonb_array_length(records)<>n THEN RAISE check_violation USING MESSAGE='524 private historical content incomplete'; END IF;
 records:=pub->'records'||records;
 expected:=item_supply_internal.snapshot_hash(jsonb_build_object('public',pub->>'completeness_receipt_hash',
  'private_watermark',w,'private_count',n,'records',records));
 stamp:=clock_timestamp();
 IF s.payload_json->>'schema_version' IS DISTINCT FROM 'complete_exposure_v2'
  OR s.payload_json->>'collector_version' IS DISTINCT FROM 'private-native-union-v1'
  OR s.payload_json->>'learner_id' IS DISTINCT FROM u::text OR s.payload_json->>'epoch' IS DISTINCT FROM e::text
  OR s.payload_json->'records' IS DISTINCT FROM records
  OR s.payload_json->>'completeness_receipt_hash' IS DISTINCT FROM expected
  OR (s.payload_json->>'watermark')::bigint IS DISTINCT FROM w+(pub->>'watermark')::bigint
  OR s.checked_at>stamp OR stamp>=s.valid_until OR s.valid_until>(pub->>'valid_until')::timestamptz
  OR (s.payload_json->>'observed_at')::timestamptz IS DISTINCT FROM s.checked_at
  OR (s.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM s.valid_until THEN
  RAISE check_violation USING MESSAGE='524 exact fresh union exposure required'; END IF;
 RETURN s.payload_json;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_exposure_current(uuid,uuid,bigint) FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_exposure_snapshot_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 PERFORM item_supply_internal.private_native_exposure_current(NEW.id,NEW.user_id,NEW.epoch); RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_exposure_snapshot_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_exposure_snapshot_insert ON tutor_item_supply_private_native_exposure_snapshots;
CREATE TRIGGER private_native_exposure_snapshot_insert AFTER INSERT ON tutor_item_supply_private_native_exposure_snapshots
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_exposure_snapshot_insert();

DO $capture_guard524$ DECLARE p record; BEGIN
 SELECT f.*,l.lanname INTO p FROM pg_proc f JOIN pg_language l ON l.oid=f.prolang WHERE f.oid='capture_native_exposure_origin()'::regprocedure;
 IF p.prokind<>'f' OR p.lanname<>'plpgsql' OR NOT p.prosecdef OR p.prorettype<>'trigger'::regtype OR p.pronargs<>0
  OR p.proretset OR p.proisstrict OR p.provolatile<>'v'
  OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') NOT IN(
   'b5a94a16fbd2c471e012056580127a273c5aa297b59ec07066105a4421add26f','38493786a5bf3b8133cc6f10749b61fa0c9d76cc594d08f8c43c791648e40bd7') THEN
  RAISE check_violation USING MESSAGE='524 unknown original502 exposure capture'; END IF;
END $capture_guard524$;
CREATE OR REPLACE FUNCTION capture_native_exposure_origin() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE e bigint; a record; b record; v uuid; k text; coordinates jsonb; raw jsonb:=to_jsonb(NEW); slot text; revision uuid;
BEGIN
  -- Tracking must not change the behavior of ordinary V1 owners. Disabled/reset
  -- epochs cannot acquire a new completeness proof; their existing history is unknown.
  INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(NEW.user_id) ON CONFLICT DO NOTHING;
  SELECT epoch INTO e FROM tutor_item_supply_user_epochs WHERE user_id=NEW.user_id AND enabled;
  IF NOT FOUND THEN RETURN NEW; END IF;
  PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,e);
  k:='untracked'; coordinates:='{}'::jsonb;
  IF TG_TABLE_NAME IN ('tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts') THEN
    SELECT x.*,s.active_plan_revision_id INTO a FROM tutor_learning_artifacts x
      JOIN tutor_teaching_sessions s ON s.id=x.teaching_session_id AND s.user_id=x.user_id
      WHERE x.id=NEW.artifact_id AND x.user_id=NEW.user_id;
    IF FOUND THEN
      IF a.owner_kind='learning_item' THEN v:=a.owner_id; END IF;
      coordinates:=jsonb_build_object('track_id',a.learning_track_id,'revision_id',a.active_plan_revision_id,'knowledge_key',a.knowledge_key);
      IF TG_TABLE_NAME='tutor_knowledge_check_assistance_receipts' THEN k:=raw->>'assistance_kind';
      ELSE k:=CASE WHEN raw->>'event_kind'='created' AND raw->>'state' IN ('ready','active','running','completed','failed') THEN 'shown'
        WHEN raw->>'event_kind'='created' THEN 'untracked'
        WHEN raw->>'action_kind'='request_hint' THEN 'hint'
        WHEN raw->>'action_kind'='request_direct_answer' THEN 'direct_answer'
        WHEN raw->>'action_kind' IN ('respond','run') THEN 'attempted'
        WHEN raw->>'event_kind' IN ('state_changed','attempt_linked','terminal') OR raw->>'action_kind'='cancel' THEN 'metadata'
        ELSE 'untracked' END;
      END IF;
    END IF;
  ELSIF TG_TABLE_NAME='tutor_exercise_attempts' THEN
    SELECT version_id INTO v FROM tutor_learning_item_practice_materializations WHERE exercise_version_id=NEW.exercise_version_id;
    k:='attempted'; coordinates:=jsonb_build_object('track_id',NEW.track_id,'revision_id',NEW.plan_revision_id,'knowledge_key',NEW.knowledge_key);
  ELSE
    IF TG_TABLE_NAME='tutor_exercise_hint_receipts' THEN
      SELECT * INTO b FROM tutor_lesson_gate_bindings WHERE id=NEW.gate_binding_id AND user_id=NEW.user_id;
      IF FOUND THEN
        SELECT version_id INTO v FROM tutor_learning_item_practice_materializations WHERE exercise_version_id=b.exercise_version_id;
        SELECT active_plan_revision_id INTO revision FROM tutor_lesson_documents WHERE id=b.document_id;
      END IF;
      k:='hint';
    ELSE
      SELECT version_id INTO v FROM tutor_learning_item_practice_materializations WHERE exercise_version_id=NEW.exercise_version_id;
      SELECT active_plan_revision_id INTO revision FROM tutor_lesson_documents WHERE id=NEW.document_id;
      -- Binding is not delivery. No existing durable Gate view event proves shown.
      k:='untracked';
    END IF;
    coordinates:=jsonb_build_object('track_id',NEW.track_id,'revision_id',revision,'knowledge_key',NEW.knowledge_key);
  END IF;
  -- PRIVATE is recorded in its OWN original-event ledger. Public metadata is
  -- permitted only after a checked PRIVATE binding and captured real event.
  IF TG_TABLE_NAME IN ('tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts')
    AND EXISTS(SELECT 1 FROM tutor_item_supply_private_native_artifact_bindings pb
      WHERE pb.artifact_id=a.id AND pb.user_id=NEW.user_id AND pb.epoch=e AND pb.version_id=v) THEN
    IF k<>'metadata' AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_exposure_origins po
      WHERE po.user_id=NEW.user_id AND po.epoch=e AND po.artifact_id=a.id AND po.version_id=v
        AND po.origin_table=TG_TABLE_NAME AND po.origin_id=NEW.id AND po.kind=k) THEN
      RAISE check_violation USING MESSAGE='524 private exposure must be recorded before public metadata';
    END IF;
    v:=NULL;k:='metadata';
  END IF;
  -- V1 sources are recorded as unknown, not blocked or relabelled native.
  IF k='shown' AND EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs WHERE version_id=v) THEN
    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_watermarks w WHERE w.user_id=NEW.user_id AND w.epoch=e
      AND w.watermark=(SELECT COALESCE(max(sequence),0) FROM tutor_item_supply_native_exposure_inbox WHERE user_id=NEW.user_id AND epoch=e)) THEN
      RAISE check_violation USING MESSAGE='native delivery requires current complete exposure watermark';
    END IF;
    SELECT p.payload_json->'spec'->'allocation'->>'slot' INTO slot
      FROM tutor_learning_item_native_publication_proofs n
      JOIN tutor_learning_item_validation_receipts vr ON vr.id=(n.proof_json->>'bank_validation_id')::uuid
      JOIN tutor_item_supply_shared_validation_evidence ev ON ev.id=vr.native_validation_evidence_id
      JOIN tutor_item_supply_shared_validation_preparations p ON p.id=ev.preparation_id WHERE n.version_id=v;
    IF slot IS DISTINCT FROM 'practice' THEN
      RAISE check_violation USING MESSAGE='native non-practice delivery requires independent purpose owner';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_deliveries d
      JOIN tutor_item_supply_private_scopes s ON s.id=d.scope_id AND s.user_id=d.user_id AND s.epoch=d.epoch
      JOIN LATERAL(SELECT state FROM tutor_learning_item_publication_events WHERE version_id=d.version_id ORDER BY state_version DESC LIMIT 1) pe ON pe.state='published'
      WHERE d.user_id=NEW.user_id AND d.epoch=e AND d.version_id=v AND d.delivery_txid=txid_current() AND d.delivery_kind='practice'
        AND s.track_id::text=coordinates->>'track_id' AND s.revision_id::text=coordinates->>'revision_id'
        AND s.knowledge_key=coordinates->>'knowledge_key') AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_type_exposure_deliveries d
      JOIN tutor_item_supply_private_scopes s ON s.id=d.scope_id AND s.user_id=d.user_id AND s.epoch=d.epoch
      JOIN tutor_item_supply_native_eligibility ne ON ne.id=d.eligibility_id AND ne.user_id=d.user_id AND ne.epoch=d.epoch
      JOIN tutor_item_supply_type_exposure_snapshots es ON es.id=d.exposure_snapshot_id AND es.user_id=d.user_id AND es.epoch=d.epoch
      JOIN LATERAL(SELECT state FROM tutor_learning_item_publication_events WHERE version_id=d.version_id ORDER BY state_version DESC LIMIT 1) pe ON pe.state='published'
      WHERE d.user_id=NEW.user_id AND d.epoch=e AND d.version_id=v AND d.delivery_txid=txid_current() AND d.delivery_kind='practice'
        AND ne.txid=txid_current() AND ne.exposure_snapshot_id=es.id AND clock_timestamp()<ne.valid_until
        AND es.checked_at<=clock_timestamp() AND clock_timestamp()<es.valid_until
        AND item_supply_internal.type_exposure_current(es.id,NEW.user_id,e) IS NOT NULL
        AND s.track_id::text=coordinates->>'track_id' AND s.revision_id::text=coordinates->>'revision_id'
        AND s.knowledge_key=coordinates->>'knowledge_key') THEN
      RAISE check_violation USING MESSAGE='native assessment must be reserved before practice delivery';
    END IF;
  END IF;
  INSERT INTO tutor_item_supply_native_exposure_inbox(user_id,epoch,origin_table,origin_id,version_id,kind,origin_scope_json,origin_hash)
    VALUES(NEW.user_id,e,TG_TABLE_NAME,NEW.id,v,k,coordinates,item_supply_internal.snapshot_hash(raw)) ON CONFLICT DO NOTHING;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION capture_native_exposure_origin() FROM PUBLIC;

-- B523 calls this BEFORE INSERT for exactly private_native_phase_v1. It does
-- not read an already-inserted phase or call private_pack_bind_phase recursively.
CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_phase(
 p jsonb,u uuid,e bigint,scope uuid,task uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE t record;j record;c record;o record;prior record;s jsonb;r jsonb:=p->'ref';l jsonb:=p->'lease';m jsonb;
 frozen jsonb;retry jsonb;deadline timestamptz;stamp timestamptz;role text;windows integer;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','root_id','job_id','slot_id','business_item_id','goal_scope_id','ref','lease','valid_until']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(r,ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(l,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_phase_v1'
  OR jsonb_typeof(r) IS DISTINCT FROM 'object' OR jsonb_typeof(l) IS DISTINCT FROM 'object'
  OR (r->>'pack_task_id',r->>'user_id',r->>'epoch',r->>'scope_id') IS DISTINCT FROM (task::text,u::text,e::text,scope::text)
  OR (p->>'root_id',p->>'job_id',p->>'slot_id',p->>'business_item_id',p->>'goal_scope_id')
   IS DISTINCT FROM (r->>'root_id',l->>'job_id',r->>'slot_id',r->>'business_item_id',r->>'goal_scope_id')
  OR (l->>'visibility',l->>'owner_id',l->>'owner_epoch') IS DISTINCT FROM ('private',u::text,e::text) THEN
  RAISE check_violation USING MESSAGE='524 exact PRIVATE phase schema/frame/namespace required'; END IF;
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task
  AND record_kind='task' AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 SELECT value INTO s FROM jsonb_array_elements(t.payload_json->'slots') WHERE value->>'slot_id'=r->>'slot_id'
  AND value->>'logical_item_id'=r->>'business_item_id';
 role:=CASE WHEN s->>'slot' IN('practice-1','practice-2') THEN 'practice'
  WHEN s->>'slot' IN('assessment-1','assessment-2') THEN 'assessment'
  WHEN s->>'slot'='guided-remediation' THEN 'remediation' END;
 IF t.id IS NULL OR s IS NULL OR role IS NULL OR role IS DISTINCT FROM r->>'slot'
  OR item_supply_internal.private_native_task_enhancement(task,u,e,scope) IS DISTINCT FROM true
  OR t.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM r->>'mapping_receipt_id' THEN
  RAISE check_violation USING MESSAGE='524 actual fixed PRIVATE task/business role required'; END IF;
 m:=item_supply_internal.private_native_mapping_current((r->>'mapping_receipt_id')::uuid,u,e);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_finite_course_mappings x,
  LATERAL jsonb_array_elements(x.receipt_json->'pack_request'->'demands') d WHERE x.id=(r->>'mapping_receipt_id')::uuid
  AND x.user_id=u AND x.epoch=e AND x.assessment_scope_id=scope AND d->>'slot'=role
  AND d->>'storage_scope_id'=r->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 real goal_scope distinct from assessment storage required'; END IF;
 SELECT * INTO j FROM tutor_item_supply_private_jobs WHERE id=(l->>'job_id')::uuid AND user_id=u AND epoch=e
  AND scope_id=scope AND root_id=(r->>'root_id')::uuid FOR SHARE;
 SELECT * INTO o FROM tutor_item_supply_private_obligations WHERE root_id=j.root_id AND user_id=u AND epoch=e AND scope_id=scope;
 SELECT * INTO c FROM tutor_item_supply_private_job_controls WHERE job_id=j.id AND user_id=u AND epoch=e AND scope_id=scope FOR SHARE;
 frozen:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 retry:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
  THEN c.profile_snapshot_json->'retry_policy' ELSE 'null'::jsonb END;
 deadline:=LEAST(c.lease_expires_at,c.parent_deadline,(frozen->>'bound_at')::timestamptz+
  (frozen->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF j.id IS NULL OR o.root_id IS NULL OR c.state IS DISTINCT FROM 'leased'
  OR (l->>'lease_owner',l->>'generation',l->>'state_version')
   IS DISTINCT FROM (c.lease_owner,c.lease_generation::text,c.state_version::text)
  OR (l->>'expires_at')::timestamptz IS DISTINCT FROM c.lease_expires_at
  OR (l->>'parent_deadline')::timestamptz IS DISTINCT FROM c.parent_deadline
  OR l->'profile' IS DISTINCT FROM frozen OR l->'retry_policy' IS DISTINCT FROM retry
  OR (p->>'valid_until')::timestamptz IS DISTINCT FROM deadline THEN
  RAISE check_violation USING MESSAGE='524 original PRIVATE issuer control/profile/finite deadline required'; END IF;
 SELECT * INTO prior FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=task AND user_id=u AND epoch=e
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1;
 IF prior.id IS NOT NULL AND prior.payload_json->>'root_id' IS DISTINCT FROM r->>'root_id' THEN
  RAISE check_violation USING MESSAGE='524 fixed PRIVATE canonical root required'; END IF;
 stamp:=clock_timestamp();
 SELECT count(*) INTO windows FROM tutor_item_supply_private_budget_windows w WHERE w.root_id=j.root_id AND w.user_id=u AND w.epoch=e
  AND w.scope_id=scope AND w.pool_key=o.pool_class AND w.provider_key=o.provider_key AND w.window_start<=stamp AND w.window_end>=deadline;
 IF windows<>1 OR deadline IS NULL OR stamp>=deadline THEN
  RAISE check_violation USING MESSAGE='524 current original PRIVATE resource window required after locks'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_phase(jsonb,uuid,bigint,uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_normal(
 n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=n.job_id AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'blind_id')::uuid AND kind='blind'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=n.job_id AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'review_id')::uuid AND kind='review'
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND pack_task_id=n.pack_task_id AND slot_id=n.slot_id
  AND root_id=n.root_id AND version_id=n.version_id AND job_id=n.job_id AND xmin::text::bigint<>(txid_current()%4294967296) FOR SHARE;
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_normal(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_investigation(
 n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=n.payload_json;a record;peer record;aux record;settled record;report jsonb;finding jsonb;ds jsonb:='[]'::jsonb;
 material boolean;idx integer;rh text;fh text;key text;analysis jsonb;d jsonb;ref jsonb;leaf jsonb;path text[];cnt integer;stamp timestamptz;
BEGIN
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
 IF n.checked_at>stamp OR stamp>=n.valid_until OR stamp>=(aux.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='524 PRIVATE investigation late after receipt waits'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_investigation(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC;

-- The original writer materializes private gold in its existing exercise/rubric
-- tables. Reset must remove ONLY those owned rows, not leave unowned private gold.
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_exercise_purge_allowed(exercise uuid) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM tutor_exercise_versions x JOIN tutor_item_supply_private_native_quality_evidence q
  ON x.exercise_key=q.payload_json->'source'->'public'->>'item_key'
  AND x.version=q.payload_json->'source'->'public'->>'version'
  JOIN tutor_item_supply_user_epochs ep ON ep.user_id=q.user_id AND ep.epoch=q.epoch+1
  WHERE x.id=exercise AND x.source_kind='registered_author' AND x.exercise_key LIKE 'private-native.%'
   AND q.kind='admission' AND item_supply_internal.permitted(q.user_id))
  AND NOT EXISTS(SELECT 1 FROM tutor_learning_item_practice_materializations m WHERE m.exercise_version_id=exercise)
  AND NOT EXISTS(SELECT 1 FROM tutor_exercise_attempts a WHERE a.exercise_version_id=exercise)
  AND NOT EXISTS(SELECT 1 FROM tutor_lesson_gate_bindings b WHERE b.exercise_version_id=exercise);
$$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_exercise_purge_allowed(uuid) FROM PUBLIC;
DO $private_material_guard524$ DECLARE p record;BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid='enforce_tutor_practice_shared_immutable()'::regprocedure;
 IF p.prosecdef OR p.prokind<>'f' OR p.prorettype<>'trigger'::regtype OR p.pronargs<>0 OR p.proretset
  OR p.proisstrict OR p.provolatile<>'v' OR p.proconfig IS NOT NULL
  OR encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') NOT IN('3d722868488f2cede65d9610f3396945024161dda4c9108681ce9775d2304a7f','d9682b76d27be7d189d7c8afff27550c5ab9c1f345f0b47f7d749e7371e48577') THEN
  RAISE check_violation USING MESSAGE='524 unknown original practice shared immutability receiver'; END IF;
END $private_material_guard524$;
CREATE OR REPLACE FUNCTION enforce_tutor_practice_shared_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('tutor_exercise_versions','tutor_exercise_private_rubrics')
    AND item_supply_internal.private_native_exercise_purge_allowed(CASE WHEN TG_TABLE_NAME='tutor_exercise_versions' THEN (to_jsonb(OLD)->>'id')::uuid ELSE (to_jsonb(OLD)->>'exercise_version_id')::uuid END) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Practice shared authority rows are immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

-- Current consumers never depend on the historical producer's lease or creation
-- snapshot interval. Fresh creation DOES require whole-pack/exposure protection.
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_clone(a jsonb,b jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM unnest(ARRAY['item_handle','content_hash','actual_public_task_hash','decision_signature','answer_leakage_signature']) k
 WHERE a->>k=b->>k);
$$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_clone(jsonb,jsonb) FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_relation_current(ids jsonb,m jsonb,a jsonb,b jsonb,u uuid,e bigint,task uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE bh text; contents jsonb; r record; report jsonb;
BEGIN
 SELECT jsonb_agg(v ORDER BY item_supply_internal.snapshot_hash(v)) INTO contents FROM (VALUES(a),(b)) c(v);
 bh:=item_supply_internal.snapshot_hash(jsonb_build_object('policy_version','item_supply_type_evidence_v2','profile','kc',
 'request_hash',item_supply_internal.snapshot_hash(m->'pack_request'),'contents',contents));
 FOR r IN SELECT q.* FROM tutor_item_supply_private_native_quality_evidence q
 WHERE q.id IN(SELECT value::uuid FROM jsonb_array_elements_text(ids)) AND q.kind='relation' AND q.user_id=u AND q.epoch=e AND q.pack_task_id=task LOOP
  IF r.payload_json->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(m->'pack_request')
   OR r.payload_json->>'mapping_hash' IS DISTINCT FROM m->>'mapping_hash' OR NOT(r.checked_at<=clock_timestamp() AND clock_timestamp()<r.valid_until)
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.payload_json->'items') i WHERE i->'content'=a)
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.payload_json->'items') i WHERE i->'content'=b)
   OR jsonb_array_length(r.payload_json->'reports')<>4 THEN CONTINUE; END IF;
  IF (SELECT array_agg(x->>'role' ORDER BY x->>'role') FROM jsonb_array_elements(r.payload_json->'reports') x)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','technical']::text[]
   OR (SELECT count(DISTINCT x->>'actor_id') FROM jsonb_array_elements(r.payload_json->'reports') x)<>4
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(r.payload_json->'reports') x WHERE x->>'actor_id' IN(a->>'author_id',b->>'author_id')) THEN CONTINUE; END IF;
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.payload_json->'reports') x WHERE
   (SELECT count(*) FROM jsonb_array_elements(x->'judgments') j WHERE j->>'binding_hash'=bh AND j->>'conclusion'='nonredundant')<>1)
   THEN RETURN true; END IF;
 END LOOP;
 RETURN false;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_relation_current(jsonb,jsonb,jsonb,jsonb,uuid,bigint,uuid) FROM PUBLIC;
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_eligibility_current(eid uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE el record; p jsonb;s jsonb;m jsonb;ex jsonb;c jsonb;other jsonb;pc jsonb;pub record;q record;role jsonb;t timestamptz;
BEGIN
 SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=eid;
 IF NOT FOUND OR el.txid<>txid_current() THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(el.user_id,el.epoch);
 m:=item_supply_internal.private_native_mapping_current(el.mapping_id,el.user_id,el.epoch);
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);
 p:=el.payload_json;s:=p->'snapshot';
 IF m IS NULL OR ex IS NULL OR p->>'schema_version' IS DISTINCT FROM 'private_native_eligibility_v1'
  OR (p->>'mapping_id',p->>'exposure_id') IS DISTINCT FROM (el.mapping_id::text,el.exposure_snapshot_id::text)
  OR s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR p->>'inputs_hash' IS DISTINCT FROM s->>'inputs_hash' OR s->>'authority_status' IS DISTINCT FROM 'trusted_caller_computation_only'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_typeof(s->'selected') IS DISTINCT FROM 'array' OR jsonb_array_length(s->'selected')<>5
  OR jsonb_typeof(p->'versions') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'versions')<>5
  OR jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations') NOT BETWEEN 1 AND 16
  OR (SELECT count(DISTINCT v) FROM jsonb_array_elements_text(p->'versions') v)<>5
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='remediation')<>1 THEN RETURN false; END IF;
 -- Acquire ALL original source fences before ANY selected-version bank lock.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=(c->>'proof_id')::uuid AND kind='admission'
   AND user_id=el.user_id AND epoch=el.epoch AND scope_id=el.scope_id AND pack_task_id=el.pack_task_id AND version_id=(c->>'version_id')::uuid;
  IF NOT FOUND OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  pc:=item_supply_internal.private_native_publication_current((c->>'version_id')::uuid,el.user_id,el.epoch);
  SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE id=(c->>'publication_id')::uuid AND payload_json=pc;
  SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=pub.quality_id;
  SELECT value INTO role FROM jsonb_array_elements(m->'pack_request'->'demands') WHERE value->>'slot'=c->'member'->>'slot';
  IF pub.id IS NULL OR q.id IS NULL OR role IS NULL OR q.pack_task_id<>el.pack_task_id OR q.scope_id<>el.scope_id
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(p->'versions') v WHERE v.value=c->>'version_id')
   OR (c->>'owner_id',c->>'epoch',c->>'storage_scope_id',c->>'proof_id',c->>'materialization_id') IS DISTINCT FROM
     (el.user_id::text,el.epoch::text,role->>'storage_scope_id',q.id::text,pc->>'materialization_id')
   OR c->>'original_publication_hash' IS DISTINCT FROM pub.payload_hash
   OR c->>'original_materialization_hash' IS DISTINCT FROM pc->>'materialization_hash'
   OR c->>'original_proof_hash' IS DISTINCT FROM q.payload_json->>'clause_proof_hash'
   OR c->'type_evidence'->'content' IS DISTINCT FROM pub.content_json
   OR c->'type_evidence'->>'profile' IS DISTINCT FROM 'kc'
   OR c->'type_evidence'->>'course_mapping_hash' IS DISTINCT FROM m->>'mapping_hash'
   OR c->'type_evidence'->>'objective_hash' IS DISTINCT FROM role->'demand'->>'objective_hash'
   OR c->'type_evidence'->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(role->'demand'->'scope')
   OR c->'candidate'->'scope' IS DISTINCT FROM role->'demand'->'scope'
   OR c->'candidate'->>'visibility' IS DISTINCT FROM 'private'
   OR c->'candidate'->>'owner_ref' IS DISTINCT FROM role->'demand'->'scope'->>'owner_ref'
   OR c->'candidate'->>'item_handle' IS DISTINCT FROM pc->>'item_handle'
   OR c->'candidate'->>'content_hash' IS DISTINCT FROM pc->>'content_hash'
   OR c->'member'->>'slot' IS DISTINCT FROM q.payload_json->'ref'->>'slot'
   OR c->'member'->>'candidate_content_hash' IS DISTINCT FROM pc->>'content_hash'
OR c->'member'->>'actual_public_task_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(q.payload_json->'source'->'public')
   OR c->'member'->>'course_mapping_hash' IS DISTINCT FROM m->>'mapping_hash'
   OR (c->>'valid_until')::timestamptz<el.valid_until THEN RETURN false; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT q.slot_id) FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id IN
   (SELECT (c->>'proof_id')::uuid FROM jsonb_array_elements(s->'selected') c))<>5 THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(s->'selected') WHERE value->>'version_id'<>c->>'version_id'
    UNION SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other)
    OR item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,el.user_id,el.epoch,el.pack_task_id) IS DISTINCT FROM true THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 -- Lock waits must not carry an old clock/source/exposure observation forward.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  SELECT payload_json INTO pc FROM tutor_item_supply_private_native_quality_evidence WHERE id=(c->>'proof_id')::uuid;
  IF item_supply_internal.private_native_source_current(pc) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND el.valid_until<=el.checked_at+interval '30 seconds'
  AND (s->>'checked_at')::timestamptz=el.checked_at AND (s->>'valid_until')::timestamptz=el.valid_until;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_eligibility_current(uuid) FROM PUBLIC;
CREATE OR REPLACE FUNCTION enforce_private_native_eligibility_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF item_supply_internal.private_native_eligibility_current(NEW.id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 whole PRIVATE original current pack required'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_private_native_eligibility_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_eligibility_insert ON tutor_item_supply_private_native_eligibility;
CREATE TRIGGER private_native_eligibility_insert AFTER INSERT ON tutor_item_supply_private_native_eligibility FOR EACH ROW EXECUTE FUNCTION enforce_private_native_eligibility_insert();
CREATE OR REPLACE FUNCTION enforce_private_native_reservation_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE el record; protected jsonb; versions jsonb; task record;
BEGIN
 SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=NEW.eligibility_id;
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id AND record_kind='task';
 SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO protected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE c->'member'->>'slot'='assessment';
 SELECT jsonb_agg(to_jsonb(c->>'version_id') ORDER BY c->>'version_id') INTO versions FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c;
 IF el.id IS NULL OR task.id IS NULL OR (el.user_id,el.epoch,el.scope_id,el.pack_task_id,el.exposure_snapshot_id)
   IS DISTINCT FROM (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.pack_task_id,NEW.exposure_snapshot_id)
  OR NEW.payload_json->>'mapping_id' IS DISTINCT FROM el.mapping_id::text
  OR NEW.payload_json->'protected' IS DISTINCT FROM protected
  OR NEW.payload_json->>'binding_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.payload_json-ARRAY['relations','binding_hash'])
  OR (SELECT jsonb_agg(value ORDER BY value) FROM jsonb_array_elements(NEW.payload_json->'versions')) IS DISTINCT FROM versions
  OR NEW.payload_json->>'pack_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(el.payload_json->'snapshot'->'request')
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_type_exposure_reservations b JOIN tutor_item_supply_finite_course_mappings m ON m.id=el.mapping_id
    WHERE b.id=NEW.base_reservation_id AND b.user_id=NEW.user_id AND b.epoch=NEW.epoch AND b.scope_id=NEW.base_scope_id
      AND b.scope_id=m.practice_scope_id AND b.request_json->>'mapping_receipt_id'=m.id::text)
  OR item_supply_internal.private_native_eligibility_current(el.id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 exact retained PRIVATE assessment protection required'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_private_native_reservation_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_reservation_insert ON tutor_item_supply_private_native_assessment_reservations;
CREATE TRIGGER private_native_reservation_insert BEFORE INSERT ON tutor_item_supply_private_native_assessment_reservations FOR EACH ROW EXECUTE FUNCTION enforce_private_native_reservation_insert();
CREATE UNIQUE INDEX IF NOT EXISTS private_native_create_run ON tutor_item_supply_private_native_consumer_receipts(user_id,epoch,run_id) WHERE mode='create';
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_consumer_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;b record;a record;el record;res record;pub record;m jsonb;creation jsonb;q jsonb;p jsonb;current_pub jsonb;selected jsonb;protected jsonb;t timestamptz;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE id=rid;
 IF NOT FOUND OR r.txid<>txid_current() OR current_setting('transaction_isolation')<>'read committed' THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(r.user_id,r.epoch);
 PERFORM item_supply_internal.native_exposure_lock(r.user_id,r.epoch);
 p:=r.payload_json;
 IF r.mode='create' THEN
  SELECT * INTO res FROM tutor_item_supply_private_native_assessment_reservations WHERE id=r.reservation_id;
  SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=r.eligibility_id;
  IF res.id IS NULL OR el.id IS NULL OR (res.user_id,res.epoch,res.scope_id,res.pack_task_id) IS DISTINCT FROM (r.user_id,r.epoch,r.scope_id,r.pack_task_id)
   OR (el.user_id,el.epoch,el.scope_id,el.pack_task_id,el.exposure_snapshot_id) IS DISTINCT FROM (r.user_id,r.epoch,r.scope_id,r.pack_task_id,r.exposure_snapshot_id)
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_creation_v1'
   OR p->>'mapping_id' IS DISTINCT FROM el.mapping_id::text OR res.payload_json->>'mapping_id' IS DISTINCT FROM el.mapping_id::text
   OR item_supply_internal.private_native_eligibility_current(el.id) IS DISTINCT FROM true THEN RETURN false; END IF;
  SELECT value INTO selected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') WHERE value->>'version_id'=r.version_id::text AND value->'member'->>'slot'='practice';
  SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO protected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE c->'member'->>'slot'='assessment';
  IF selected IS NULL OR selected IS DISTINCT FROM p->'selected' OR p->'content' IS DISTINCT FROM selected->'type_evidence'->'content'
   OR protected IS DISTINCT FROM res.payload_json->'protected'
   OR p->>'pack_request_hash' IS DISTINCT FROM res.payload_json->>'pack_request_hash'
   OR p->>'pack_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(el.payload_json->'snapshot'->'request')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE NOT EXISTS
      (SELECT 1 FROM jsonb_array_elements_text(res.payload_json->'versions') v WHERE v.value=c->>'version_id')) THEN RETURN false; END IF;
  creation:=p;q:=p->'request';
 ELSE
  IF r.mode NOT IN('current','cancel') OR r.action NOT IN('request_hint','request_direct_answer','respond','cancel')
   OR (r.mode='cancel') IS DISTINCT FROM (r.action='cancel')
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_action_v1' OR p->>'action' IS DISTINCT FROM r.action
   OR p->>'artifact_id' IS DISTINCT FROM r.artifact_id::text OR p->>'artifact_version' IS DISTINCT FROM r.artifact_version::text THEN RETURN false; END IF;
  SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=r.artifact_id AND user_id=r.user_id AND epoch=r.epoch AND version_id=r.version_id AND scope_id=r.scope_id AND pack_task_id=r.pack_task_id;
  IF NOT FOUND OR p->>'creation_receipt_id' IS DISTINCT FROM b.creation_receipt_id::text THEN RETURN false; END IF;
  SELECT payload_json INTO creation FROM tutor_item_supply_private_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';q:=creation->'request';
  SELECT * INTO a FROM tutor_learning_artifacts WHERE id=r.artifact_id AND user_id=r.user_id AND version=r.artifact_version AND owner_kind='learning_item'
    AND owner_id=r.version_id AND artifact_kind='knowledge_check' AND state IN('pending','ready','active') AND active_attempt_id IS NULL;
  IF NOT FOUND OR item_supply_internal.native_consumer_frozen_artifact_matches(q,a) IS DISTINCT FROM true THEN RETURN false; END IF;
 END IF;
 m:=item_supply_internal.private_native_mapping_current((creation->>'mapping_id')::uuid,r.user_id,r.epoch);
 IF m IS NULL OR (q->>'user_id',q->>'owner_id',q->>'owner_kind',q->>'artifact_kind',q->>'purpose',q->>'knowledge_key',q->>'learning_track_id')
   IS DISTINCT FROM (r.user_id::text,r.version_id::text,'learning_item','knowledge_check','knowledge_check',m->'frozen_node'->>'knowledge_key',m->'frozen_node'->>'track_id')
  OR (r.mode='create' AND q->>'turn_id' IS DISTINCT FROM r.run_id::text)
  OR item_supply_internal.native_consumer_teaching_request_current(q,(m->'frozen_node'->>'revision_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF r.mode='cancel' THEN
  -- Only exact still-owned original KC/CAS; no content/source/current-pack right.
  RETURN r.action='cancel' AND r.checked_at<=clock_timestamp() AND clock_timestamp()<r.valid_until;
 END IF;
 current_pub:=item_supply_internal.private_native_publication_current(r.version_id,r.user_id,r.epoch);
 SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE id=(current_pub->>'publication_id')::uuid;
 IF pub.id IS NULL OR pub.pack_task_id<>r.pack_task_id OR pub.scope_id<>r.scope_id OR creation->'content' IS DISTINCT FROM pub.content_json
  OR q->>'owner_version' IS DISTINCT FROM pub.state_version::text
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(q->'source_references') x WHERE x->>'kind'='exercise_version'
    AND x->>'reference_id'=pub.exercise_version_id::text AND x->>'content_hash'=current_pub->>'exercise_content_hash') THEN RETURN false; END IF;
 IF r.mode='create' AND (item_supply_internal.private_native_eligibility_current(el.id) IS DISTINCT FROM true
  OR item_supply_internal.private_native_request_matches(q,pub.id) IS DISTINCT FROM true) THEN RETURN false; END IF;
 t:=clock_timestamp();
 RETURN r.checked_at<=t AND t<r.valid_until AND r.valid_until<=r.checked_at+interval '30 seconds';
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_consumer_current(uuid) FROM PUBLIC;
CREATE OR REPLACE FUNCTION enforce_private_native_consumer_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN IF item_supply_internal.private_native_consumer_current(NEW.id) IS DISTINCT FROM true THEN
 RAISE check_violation USING MESSAGE='524 exact PRIVATE current/create/cancel issuer required'; END IF; RETURN NEW; END $$;
REVOKE ALL ON FUNCTION enforce_private_native_consumer_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_consumer_insert ON tutor_item_supply_private_native_consumer_receipts;
CREATE TRIGGER private_native_consumer_insert AFTER INSERT ON tutor_item_supply_private_native_consumer_receipts FOR EACH ROW EXECUTE FUNCTION enforce_private_native_consumer_insert();
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_artifact_owner_matches(a tutor_learning_artifacts,prior jsonb,historical boolean) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;b record;creation jsonb;
BEGIN
 IF a.owner_kind<>'learning_item' OR a.artifact_kind<>'knowledge_check' OR a.active_attempt_id IS NOT NULL THEN RETURN false; END IF;
 IF prior IS NULL THEN
  SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE mode='create' AND user_id=a.user_id AND run_id=a.turn_id AND version_id=a.owner_id AND txid=txid_current();
  RETURN FOUND AND item_supply_internal.native_consumer_frozen_artifact_matches(r.payload_json->'request',a)
   AND r.payload_json->'request'->'presentation'=a.presentation_json AND r.payload_json->'request'->'allowed_actions'=a.allowed_actions_json
   AND r.payload_json->'request'->>'state'=a.state AND item_supply_internal.private_native_consumer_current(r.id);
 END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=a.id AND user_id=a.user_id AND version_id=a.owner_id;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(b.user_id,b.epoch);
 SELECT payload_json INTO creation FROM tutor_item_supply_private_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';
 IF item_supply_internal.native_consumer_frozen_artifact_matches(creation->'request',a) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF historical THEN RETURN true; END IF;
 IF a.version<>(prior->>'version')::integer+1 THEN RETURN false; END IF;
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE artifact_id=a.id AND artifact_version=(prior->>'version')::integer
  AND user_id=a.user_id AND epoch=b.epoch AND version_id=a.owner_id AND txid=txid_current()
  AND ((a.state='cancelled' AND mode='cancel' AND action='cancel') OR(a.state IN('active','completed') AND mode='current' AND action IN('request_hint','request_direct_answer','respond')))
  ORDER BY created_at DESC,id DESC LIMIT 1;
 IF NOT FOUND THEN RETURN false; END IF;
 IF r.mode='cancel' AND (to_jsonb(a)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json'])
  IS DISTINCT FROM (prior-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json']) THEN RETURN false; END IF;
 IF r.mode='current' AND ((r.action='respond' AND a.state<>'completed') OR(r.action<>'respond' AND a.state<>'active')) THEN RETURN false; END IF;
 IF r.mode='current' AND (to_jsonb(a)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json','presentation_json'])
  IS DISTINCT FROM (prior-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json','presentation_json']) THEN RETURN false; END IF;
 IF r.action='request_hint' AND ((a.presentation_json-'revealed_hint_levels') IS DISTINCT FROM (prior->'presentation_json'-'revealed_hint_levels')
  OR a.allowed_actions_json IS DISTINCT FROM prior->'allowed_actions_json') THEN RETURN false; END IF;
 RETURN item_supply_internal.private_native_consumer_current(r.id);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) FROM PUBLIC;
CREATE OR REPLACE FUNCTION enforce_private_native_binding_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a tutor_learning_artifacts;r record;
BEGIN
 SELECT * INTO a FROM tutor_learning_artifacts WHERE id=NEW.artifact_id AND user_id=NEW.user_id AND owner_id=NEW.version_id;
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE id=NEW.creation_receipt_id AND mode='create';
 IF a.id IS NULL OR r.id IS NULL OR pg_trigger_depth()<2 OR a.version<>1
  OR (r.user_id,r.epoch,r.scope_id,r.pack_task_id,r.version_id,r.run_id) IS DISTINCT FROM (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.pack_task_id,NEW.version_id,a.turn_id)
  OR item_supply_internal.private_native_artifact_owner_matches(a,NULL,false) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 binding requires original actual PRIVATE Artifact capture'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_private_native_binding_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_binding_insert ON tutor_item_supply_private_native_artifact_bindings;
CREATE TRIGGER private_native_binding_insert BEFORE INSERT ON tutor_item_supply_private_native_artifact_bindings FOR EACH ROW EXECUTE FUNCTION enforce_private_native_binding_insert();
CREATE OR REPLACE FUNCTION capture_private_native_artifact_binding() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;
BEGIN
 IF NEW.owner_kind='learning_item' AND EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications WHERE version_id=NEW.owner_id AND user_id=NEW.user_id) THEN
  SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE mode='create' AND user_id=NEW.user_id AND version_id=NEW.owner_id AND run_id=NEW.turn_id AND txid=txid_current();
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 original PRIVATE Artifact creation receipt missing'; END IF;
  INSERT INTO tutor_item_supply_private_native_artifact_bindings(artifact_id,user_id,epoch,scope_id,pack_task_id,version_id,creation_receipt_id)
  VALUES(NEW.id,NEW.user_id,r.epoch,r.scope_id,r.pack_task_id,r.version_id,r.id);
 END IF; RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION capture_private_native_artifact_binding() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_artifact_binding_capture ON tutor_learning_artifacts;
CREATE TRIGGER a000_private_native_artifact_binding_capture AFTER INSERT ON tutor_learning_artifacts FOR EACH ROW EXECUTE FUNCTION capture_private_native_artifact_binding();

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_request_matches(q jsonb,pub uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE v jsonb; c jsonb; presentation jsonb;options jsonb;hints jsonb;actions jsonb;response text;n integer;
BEGIN
 SELECT quality.payload_json->'source'->'public' INTO v FROM tutor_item_supply_private_native_publications p
 JOIN tutor_item_supply_private_native_quality_evidence quality ON quality.id=p.quality_id WHERE p.id=pub;
 c:=v->'content';
 IF v IS NULL OR v->>'kind'<>'knowledge_check' OR v->>'purpose'<>'knowledge_check' THEN RETURN false; END IF;
 -- PRIVATE identity is the concrete version/publication namespace, never a
 -- fabricated visibility field in the original LearningItemPublicV1 schema.
 response:=CASE c->>'response_kind' WHEN 'single_choice' THEN 'single_select' WHEN 'multiple_choice' THEN 'multi_select' ELSE c->>'response_kind' END;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('value',x->>'option_id','label',x->>'label') ORDER BY ord),'[]'::jsonb) INTO options FROM jsonb_array_elements(c->'options') WITH ORDINALITY a(x,ord);
 SELECT COALESCE(jsonb_agg(jsonb_build_object('level',(x->>'level')::integer,'label',CASE x->>'level' WHEN '1' THEN '方向' WHEN '2' THEN '概念' WHEN '3' THEN '结构' END,'markdown',x->>'markdown') ORDER BY ord),'[]'::jsonb) INTO hints FROM jsonb_array_elements(v->'hints') WITH ORDINALITY a(x,ord);
 n:=jsonb_array_length(options);
 presentation:=jsonb_build_object('type','knowledge_check_v1','response_kind',response,'prompt_markdown',c->>'prompt_markdown','options',options,
 'minimum_selections',CASE WHEN response='ordering' THEN n ELSE 1 END,'maximum_selections',CASE WHEN response IN('multi_select','ordering') THEN n ELSE 1 END,
 'maximum_text_length',2000,'hints',hints,'revealed_hint_levels','[]'::jsonb,'answer_locked',false,'outcome',NULL,'assistance_kind',NULL,
 'evaluation_markdown','','response_receipt_id',NULL,'remediation_handle',NULL,'transfer_handle',NULL);
 actions:=CASE WHEN jsonb_array_length(hints)>0 THEN '["request_hint","request_direct_answer","respond","cancel"]'::jsonb ELSE '["request_direct_answer","respond","cancel"]'::jsonb END;
 RETURN (q->>'title',q->>'instruction_markdown',q->>'difficulty',q->>'purpose',q->>'artifact_kind',q->>'blocking') IS NOT DISTINCT FROM
 (v->>'title',v->>'instruction_markdown',v->>'difficulty','knowledge_check','knowledge_check','true')
 AND q->'presentation'=presentation AND q->'allowed_actions'=actions AND q->>'state'='active'
 AND EXISTS(SELECT 1 FROM tutor_teaching_session_checkpoints cp,jsonb_array_elements(q->'source_references') ref
   WHERE cp.id=(q->>'checkpoint_id')::uuid AND cp.user_id=(q->>'user_id')::uuid
     AND ref->>'kind'='teaching_checkpoint' AND ref->>'reference_id'=cp.id::text
     AND ref->>'reference_version'=q->>'owner_context_version' AND ref->>'content_hash'=cp.source_hash);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_request_matches(jsonb,uuid) FROM PUBLIC;

-- Additive PRIVATE branch on EFFECTIVE230/521; curated/public bodies unchanged.
DO $upgrade_private_artifact$
DECLARE f record;definition text;changed text;
 old_frame constant text:=$frame_old$  ELSIF NEW.owner_kind='learning_item' THEN$frame_old$;
 new_frame constant text:=$frame_new$  ELSIF NEW.owner_kind='learning_item' AND EXISTS(SELECT 1 FROM tutor_item_supply_private_versions pv WHERE pv.id=NEW.owner_id AND pv.user_id=NEW.user_id) THEN
    IF NEW.owner_context_version IS DISTINCT FROM authority_session_version
      OR item_supply_internal.private_native_artifact_owner_matches(
        NEW,CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) ELSE NULL END,historical_supersession) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='524 PRIVATE Artifact exact original authority required';
    END IF;
  ELSIF NEW.owner_kind='learning_item' THEN
    IF EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs n WHERE n.version_id=NEW.owner_id)
      AND item_supply_internal.private_native_public_artifact_union(NEW,CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) ELSE NULL END) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='524 native PUBLIC delivery needs current complete union';
    END IF;$frame_new$;
BEGIN
 SELECT p.*,l.lanname,encode(digest(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') AS body_hash INTO f
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='public' AND p.proname='enforce_tutor_learning_artifact_owner_scope' AND p.pronargs=0;
 IF NOT FOUND OR f.lanname<>'plpgsql' OR f.prosecdef OR f.provolatile<>'v' OR f.proisstrict OR f.proconfig IS NOT NULL OR f.prorettype<>'trigger'::regtype OR f.prokind<>'f' THEN
  RAISE check_violation USING MESSAGE='524 original Artifact receiver properties changed'; END IF;
 IF f.body_hash='70a066f41f2bf240c2214cf728742f9bcd4a7b58954dd8e6e16d154b99591a0c' THEN RETURN; END IF;
 IF f.body_hash<>'a14181e7c43aacf9cb3d7ea9cbaaaca16a8aa4dfbc53e73994945edbb4457af1' THEN RAISE check_violation USING MESSAGE='524 effective230/521 receiver fingerprint changed'; END IF;
 definition:=replace(pg_get_functiondef(f.oid),E'\r\n',E'\n');
 IF position(old_frame IN definition)=0 THEN RAISE check_violation USING MESSAGE='524 original Artifact exact branch missing'; END IF;
 changed:=replace(definition,old_frame,new_frame);EXECUTE changed;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=f.oid AND encode(digest(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex')='70a066f41f2bf240c2214cf728742f9bcd4a7b58954dd8e6e16d154b99591a0c') THEN
  RAISE check_violation USING MESSAGE='524 resulting PRIVATE Artifact receiver fingerprint changed'; END IF;
END $upgrade_private_artifact$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_relation(n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb;aux record;reserve record;settled record;request jsonb;report jsonb;pair jsonb;item jsonb;leftc jsonb;rightc jsonb;contents jsonb;bh text;
BEGIN
 p:=n.payload_json;
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'preparation_id')::uuid AND pack_task_id=n.pack_task_id
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND record_kind='private_attachment'
  AND payload_json->>'schema_version'='private_native_auxiliary_v1' AND xmin::text::bigint<>(txid_current()%4294967296);
 request:=aux.payload_json->'request';
 SELECT * INTO reserve FROM tutor_item_supply_private_reservations WHERE id=(p->>'reservation_id')::uuid AND user_id=n.user_id AND epoch=n.epoch
  AND scope_id=n.scope_id AND root_id=n.root_id AND job_id=n.job_id AND lease_generation=(p->'lease'->>'generation')::integer;
 SELECT * INTO settled FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=reserve.id AND user_id=n.user_id AND epoch=n.epoch
  AND settlement_key='private.relation.'||replace(aux.id::text,'-','') AND usage_state='unknown' AND xmin::text::bigint<>(txid_current()%4294967296);
 IF aux.id IS NULL OR reserve.id IS NULL OR settled.id IS NULL OR reserve.requests<>4
  OR request->>'schema_version' IS DISTINCT FROM 'private_native_relation_phase_v1'
  OR request->'ref' IS DISTINCT FROM p->'ref' OR request->'lease' IS DISTINCT FROM p->'lease'
  OR request->'payload' IS DISTINCT FROM (p-ARRAY['schema_version','reports','preparation_id','reservation_id','ref','lease'])||jsonb_build_object('schema_version','private_native_relation_preparation_v1')
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_relation_v1'
  OR jsonb_typeof(p->'reports') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'reports')<>4
  OR jsonb_typeof(p->'pairs') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'pairs') NOT BETWEEN 1 AND 120
  OR jsonb_typeof(p->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'items') NOT BETWEEN 2 AND 16
  OR (SELECT count(DISTINCT r->>'actor_id') FROM jsonb_array_elements(p->'reports') r)<>4
  OR (SELECT count(DISTINCT r->'run'->>'run_id') FROM jsonb_array_elements(p->'reports') r)<>4
  OR (SELECT array_agg(r->>'role' ORDER BY r->>'role') FROM jsonb_array_elements(p->'reports') r) IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','technical']::text[] THEN
  RAISE check_violation USING MESSAGE='524 relation needs committed original four-call preparation/settlement'; END IF;
 FOR pair IN SELECT value FROM jsonb_array_elements(p->'pairs') LOOP
  SELECT value->'content' INTO leftc FROM jsonb_array_elements(p->'items') WHERE value->>'version_id'=pair->>'left_version_id';
  SELECT value->'content' INTO rightc FROM jsonb_array_elements(p->'items') WHERE value->>'version_id'=pair->>'right_version_id';
  SELECT jsonb_agg(v ORDER BY item_supply_internal.snapshot_hash(v)) INTO contents FROM (VALUES(leftc),(rightc)) c(v);
  bh:=item_supply_internal.snapshot_hash(jsonb_build_object('policy_version','item_supply_type_evidence_v2','profile','kc','request_hash',p->>'request_hash','contents',contents));
  IF leftc IS NULL OR rightc IS NULL OR leftc->>'version_id'=rightc->>'version_id' OR pair->>'binding_hash' IS DISTINCT FROM bh THEN
   RAISE check_violation USING MESSAGE='524 relation exact actual pair binding required'; END IF;
 END LOOP;
 FOR report IN SELECT value FROM jsonb_array_elements(p->'reports') LOOP
  IF report->>'actor_id' IS DISTINCT FROM item_supply_internal.native_type_actor(report->'run'->'provider_identity'->>'identity')::text
   OR report->'run'->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
   OR report->'run'->>'prompt_version' IS DISTINCT FROM 'native-content-relation-v1'
   OR (report->'run'->>'max_output_tokens')::integer<>61440
   OR (report->'run'->>'timeout_seconds')::numeric*1000>(p->'lease'->'profile'->'values'->>'request_timeout_ms')::numeric
   OR (report->>'checked_at')::timestamptz>(aux.payload_json->>'valid_until')::timestamptz
   OR (report->>'valid_until')::timestamptz<>n.valid_until
   OR jsonb_array_length(report->'judgments')<>jsonb_array_length(p->'pairs')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'items') i WHERE i->'content'->>'author_id'=report->>'actor_id') THEN
   RAISE check_violation USING MESSAGE='524 relation original independent role/profile interval required'; END IF;
  FOR pair IN SELECT value FROM jsonb_array_elements(p->'pairs') LOOP
   IF (SELECT count(*) FROM jsonb_array_elements(report->'judgments') j WHERE j->>'binding_hash'=pair->>'binding_hash' AND j->>'conclusion' IN('nonredundant','uncertain','conflict'))<>1 THEN
    RAISE check_violation USING MESSAGE='524 relation every actual pair needs four-role judgment'; END IF;
  END LOOP;
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_relation(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_review_stage(n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE aux record;r record;s record;g record;binding jsonb;request jsonb;
BEGIN
 binding:=CASE WHEN n.kind='blind' THEN n.payload_json->'binding' ELSE n.payload_json->'bundle'->'binding' END;
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_review_stage(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_task_enhancement(task uuid,u uuid,e bigint,scope uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE t record;expected jsonb;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task AND user_id=u AND epoch=e AND scope_id=scope AND record_kind='task' FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF t.payload_json->>'enhancement'='prefer_private' THEN RETURN true; END IF;
 -- No unchecked private_status JSON may upgrade an old base_only header.
 IF NOT EXISTS(SELECT 1 FROM pg_trigger tr JOIN pg_proc fn ON fn.oid=tr.tgfoid
   WHERE tr.tgrelid='tutor_item_supply_private_persistent_pack_journal'::regclass
    AND tr.tgname='a000_private_enhancement_intent_insert' AND tr.tgenabled='O' AND NOT tr.tgisinternal
    AND fn.oid=to_regprocedure('item_supply_internal.enforce_private_enhancement_intent_insert()')
    AND fn.prosecdef AND fn.provolatile='v' AND encode(sha256(convert_to(replace(fn.prosrc,E'\r\n',E'\n'),'UTF8')),'hex')='ef3585fc5071432277cc03a8c207d07f536727f9e8b073c3ddb93afe4465b2bf') THEN RETURN false; END IF;
 expected:=jsonb_build_object('schema_version','private_enhancement_intent_v1','pack_task_id',task,'user_id',u,'epoch',e,'scope_id',scope,
  'public_task_id',t.payload_json->'ref'->'public_task_id','previous_enhancement','base_only','enhancement','prefer_private');
 RETURN t.payload_json->>'enhancement'='base_only' AND EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal i WHERE i.pack_task_id=task AND i.user_id=u AND i.epoch=e AND i.scope_id=scope
   AND i.record_kind='private_status' AND i.intent_hash=t.intent_hash AND i.payload_json=expected
   AND i.operation_key='enhancement.intent.'||replace(task::text,'-','')||'.prefer_private');
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_task_enhancement(uuid,uuid,bigint,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_base_union_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;el record;m jsonb;ex jsonb;p jsonb;s jsonb;c jsonb;other jsonb;original jsonb;proof record;t timestamptz;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_status';
 IF NOT FOUND THEN RETURN false; END IF;
 p:=r.payload_json;s:=p->'snapshot';
 IF p->>'schema_version' IS DISTINCT FROM 'private_native_base_union_v1' OR (p->>'txid')::bigint<>txid_current() THEN RETURN false; END IF;
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
 -- Complete source set FIRST, before any of the PUBLIC version bank locks.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  IF item_supply_internal.native_consumer_source_current((c->>'proof_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
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
  IF item_supply_internal.native_consumer_source_current((c->>'proof_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND (p->>'checked_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz
  AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '30 seconds';
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_base_union_current(uuid) FROM PUBLIC;
CREATE OR REPLACE FUNCTION enforce_private_native_base_union_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.record_kind='private_status' AND NEW.payload_json->>'schema_version'='private_native_base_union_v1'
  AND item_supply_internal.private_native_base_union_current(NEW.id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 fresh whole-base union authorization required'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_private_native_base_union_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_base_union_insert ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER private_native_base_union_insert AFTER INSERT ON tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION enforce_private_native_base_union_insert();

-- Safety receiver only: no new PUBLIC quality system or API rollout.
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_public_artifact_union(a tutor_learning_artifacts,prior jsonb) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE e bigint;r record;
BEGIN
 -- Ongoing PUBLIC content/cancel has its own original521 owner; it cannot select
 -- another assessment. The union is mandatory for NEW selected practice delivery.
 IF prior IS NOT NULL THEN RETURN true; END IF;
 SELECT epoch INTO e FROM tutor_item_supply_user_epochs WHERE user_id=a.user_id AND enabled;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_exposure_origins WHERE user_id=a.user_id AND epoch=e) THEN RETURN true; END IF;
 FOR r IN SELECT j.* FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=a.user_id AND j.epoch=e
  AND j.record_kind='private_status' AND j.payload_json->>'schema_version'='private_native_base_union_v1'
  AND j.payload_json->>'txid'=txid_current()::text AND j.payload_json->'snapshot'->'request'->>'track_id'=a.learning_track_id::text LOOP
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(r.payload_json->'snapshot'->'selected') c WHERE c->>'version_id'=a.owner_id::text AND c->'member'->>'slot'='practice')
   AND item_supply_internal.private_native_base_union_current(r.id) THEN RETURN true; END IF;
 END LOOP;
 RETURN false;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_public_artifact_union(tutor_learning_artifacts,jsonb) FROM PUBLIC;
CREATE OR REPLACE FUNCTION enforce_private_native_public_union_reservation() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;el record;contents jsonb;expected jsonb;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_exposure_origins WHERE user_id=NEW.user_id AND epoch=NEW.epoch) THEN RETURN NEW; END IF;
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=NEW.eligibility_id AND txid=txid_current();
 FOR r IN SELECT j.* FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=NEW.user_id AND j.epoch=NEW.epoch AND j.record_kind='private_status'
  AND j.payload_json->>'schema_version'='private_native_base_union_v1' AND j.payload_json->>'txid'=txid_current()::text LOOP
  SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO contents FROM jsonb_array_elements(r.payload_json->'snapshot'->'selected') c;
  SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO expected FROM jsonb_array_elements(el.snapshot_json->'selected') c;
  IF el.id IS NOT NULL AND contents=expected AND el.snapshot_json->'request'=r.payload_json->'snapshot'->'request'
   AND item_supply_internal.private_native_base_union_current(r.id) THEN RETURN NEW; END IF;
 END LOOP;
 RAISE check_violation USING MESSAGE='524 native PUBLIC assessment must include actual PRIVATE exposures';
END $$;
REVOKE ALL ON FUNCTION enforce_private_native_public_union_reservation() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_native_public_union_reservation ON tutor_item_supply_type_exposure_reservations;
CREATE TRIGGER private_native_public_union_reservation BEFORE INSERT ON tutor_item_supply_type_exposure_reservations FOR EACH ROW EXECUTE FUNCTION enforce_private_native_public_union_reservation();

CREATE OR REPLACE FUNCTION enforce_private_enhancement_wait_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=NEW.payload_json;c record;ph record;q record;
BEGIN
 IF NEW.record_kind<>'private_status' OR p->>'schema_version' NOT IN('private_enhancement_wait_v1','private_enhancement_wait_end_v1','private_enhancement_failure_v1') THEN RETURN NEW; END IF;
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch::bigint);
 IF item_supply_internal.private_native_task_enhancement(NEW.pack_task_id,NEW.user_id,NEW.epoch::bigint,NEW.scope_id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 actual same-task PRIVATE consumer wait required'; END IF;
 IF p->>'schema_version'='private_enhancement_wait_v1' THEN
  SELECT * INTO c FROM tutor_item_supply_private_job_controls WHERE job_id=(p->>'job_id')::uuid AND user_id=NEW.user_id AND epoch=NEW.epoch;
  SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=NEW.pack_task_id AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=p->>'job_id';
  IF c.job_id IS NULL OR ph.id IS NULL OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','job_id','base_union_id','checked_at','valid_until']) IS DISTINCT FROM true
   OR item_supply_internal.private_native_base_union_current((p->>'base_union_id')::uuid) IS DISTINCT FROM true
   OR (p->>'checked_at')::timestamptz>clock_timestamp() OR (p->>'valid_until')::timestamptz<=clock_timestamp()
   OR (p->>'valid_until')::timestamptz>c.parent_deadline
   OR (p->>'valid_until')::timestamptz>(ph.payload_json->'lease'->'profile'->>'bound_at')::timestamptz+
      (ph.payload_json->'lease'->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond' THEN
   RAISE check_violation USING MESSAGE='524 wait window needs original finite profile/current whole base'; END IF;
 ELSIF p->>'schema_version'='private_enhancement_wait_end_v1' THEN
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','reason']) IS DISTINCT FROM true OR p->>'reason' IS DISTINCT FROM 'consumer_cancelled' THEN
   RAISE check_violation USING MESSAGE='524 closed consumer wait end, not business cancellation'; END IF;
 ELSE
  -- A committed veto is a normal-loop input, not a business terminal outcome.
  -- Neither a fixed number of rereviews nor a technical phase/window expiry
  -- grants failure fallback. V1 has no concrete lawful terminal issuer/receipt;
  -- fail closed until a separately reviewed versioned receiver binds that chain.
  -- Real consumer wait expiration / explicit wait cancellation above is separate.
  RAISE check_violation USING MESSAGE='524 failure fallback requires a versioned lawful terminal owner; review veto is not terminal';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_private_enhancement_wait_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_enhancement_wait_insert ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER private_enhancement_wait_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION enforce_private_enhancement_wait_insert();





















