-- C12: PUBLIC content is learning_item_public_v1, not a visibility tag.
-- PUBLIC namespace comes from the exact original immutable publication proof lease.
-- Selected-forward only: final549 predecessor or this exact replacement body.
-- All other current/source/TOP/owner/expiry predicates and historical rows remain.
-- Caller owns the isolated transaction; no business writes, grants or commit.
DO $fix557$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old557$

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
$old557$;
 new_body constant text := $new557$

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
   JOIN tutor_learning_item_public_contents pub ON pub.version_id=v.id
   AND pub.schema_version='learning_item_public_v1'
   AND pub.public_json->>'schema_version'='learning_item_public_v1'
   AND proof.proof_json->'lease'->>'visibility'='public'
   AND proof.proof_json->'lease'->'owner_id'='null'::jsonb
   AND proof.proof_json->'lease'->'owner_epoch'='null'::jsonb
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
$new557$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='557 original isolated writable transaction required'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.native_consumer_receipt_current(uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'native_consumer_receipt_current'
  OR actual.lanname IS DISTINCT FROM 'plpgsql' OR actual.prokind<>'f'
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM
   pg_catalog.format('%s','pg_catalog.uuid'::regtype::oid)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['receipt_id']
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='557 original consumer receiver identity/attributes changed'; END IF;
 -- Preserve actual owner and full ACL, never replace them with guessed metadata.
 IF EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(actual.proacl,
       pg_catalog.acldefault('f',actual.proowner))) AS privilege
     WHERE privilege.grantee=0 AND privilege.privilege_type='EXECUTE')
 THEN RAISE check_violation USING MESSAGE='557 original consumer receiver PUBLIC privilege changed'; END IF;
 -- Idempotency is exact-body only, after every identity/attribute/ACL guard.
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='557 original consumer receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='557 original consumer receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.*,l.lanname INTO verified FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='557 consumer receiver metadata/OID/owner/ACL or PUBLIC contract body changed'; END IF;
END $fix557$;
