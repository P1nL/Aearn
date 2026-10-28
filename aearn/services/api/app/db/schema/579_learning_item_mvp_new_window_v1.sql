-- New explicit MVP current supply/delivery observations: at most600s, never renewal.
-- Frozen<=578. Ten existing functions and three existing CHECKs, no new objects/rows.
-- StrictV2 windows, source/grant/resource/session/epoch/current and all real consumers stay.
-- All thirteen targets preflight before mutation; caller owns isolated transaction/lock.
DO $window579$
DECLARE actual record; verified record; target record; original_check record; final_check record;
 saved jsonb; definition text; check_definition text; table_id oid; matches bigint;
 expected_columns smallint[]; actual_columns smallint[]; new_columns smallint[];
 functions_before jsonb:='[]'::jsonb; checks_before jsonb:='[]'::jsonb;
 old_public_exposure constant text := $old_public_exposure579$
DECLARE s record; w record; watermark bigint; n bigint; records jsonb; t timestamptz;
BEGIN
  PERFORM item_supply_internal.native_exposure_lock(u,e);
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE check_violation USING MESSAGE='type exposure requires read committed';
  END IF;
  SELECT * INTO s FROM tutor_item_supply_type_exposure_snapshots WHERE id=sid AND user_id=u AND epoch=e;
  SELECT * INTO w FROM tutor_item_supply_native_exposure_watermarks WHERE id=s.original_watermark_id AND user_id=u AND epoch=e;
  SELECT COALESCE(max(sequence),0),count(*) INTO watermark,n FROM tutor_item_supply_native_exposure_inbox WHERE user_id=u AND epoch=e;
  t:=clock_timestamp();
  IF s.id IS NULL OR w.id IS NULL OR NOT(s.checked_at<=t AND t<s.valid_until)
    OR w.watermark<>watermark OR w.payload_json->>'origin_count' IS DISTINCT FROM n::text
    OR item_supply_internal.native_exposure_hooks_current() IS DISTINCT FROM true
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_births WHERE id=w.birth_id AND user_id=u AND epoch=e)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_inbox i
      LEFT JOIN tutor_item_supply_native_exposure_events ev ON ev.inbox_id=i.id AND ev.user_id=i.user_id AND ev.epoch=i.epoch
      WHERE i.user_id=u AND i.epoch=e AND i.kind<>'metadata' AND ev.id IS NULL) THEN
    RAISE check_violation USING MESSAGE='type exposure current original ledger required';
  END IF;
  -- Historical immutable content is independent of current publishability.
  SELECT COALESCE(jsonb_agg(jsonb_build_object('event_id',i.id,'item_handle',ev.binding_json->>'item_handle',
      'content_hash',ev.binding_json->>'content_hash','family_id',ev.binding_json->>'family_id',
      'semantic_signature',ev.binding_json->>'semantic_signature','kind',i.kind,'content',f.content_json)
      ORDER BY i.sequence),'[]'::jsonb) INTO records
    FROM tutor_item_supply_native_exposure_events ev
    JOIN tutor_item_supply_native_exposure_inbox i ON i.id=ev.inbox_id AND i.user_id=ev.user_id AND i.epoch=ev.epoch
    JOIN tutor_item_supply_native_content_facts f ON f.user_id=ev.user_id AND f.epoch=ev.epoch
      AND f.version_id=ev.version_id AND f.proof_id=ev.proof_id
    JOIN tutor_learning_item_native_publication_proofs p ON p.id=f.proof_id AND p.version_id=f.version_id AND p.proof_hash=f.proof_hash
    WHERE ev.user_id=u AND ev.epoch=e;
  IF NOT item_supply_internal.snapshot_keys(s.snapshot_json,ARRAY['schema_version','learner_id','epoch',
      'collector_version','watermark','completeness_receipt_hash','observed_at','valid_until','records'])
    OR jsonb_array_length(records)<>(SELECT count(*) FROM tutor_item_supply_native_exposure_events WHERE user_id=u AND epoch=e)
    OR s.snapshot_json->'records' IS DISTINCT FROM records
    OR s.snapshot_json->>'schema_version' IS DISTINCT FROM 'complete_exposure_v2'
    OR s.snapshot_json->>'learner_id' IS DISTINCT FROM u::text OR s.snapshot_json->>'epoch' IS DISTINCT FROM e::text
    OR s.snapshot_json->>'watermark' IS DISTINCT FROM watermark::text
    OR s.snapshot_json->>'collector_version' IS DISTINCT FROM 'native-type-exposure-v2'
    OR (s.snapshot_json->>'observed_at')::timestamptz IS DISTINCT FROM s.checked_at
    OR (s.snapshot_json->>'valid_until')::timestamptz IS DISTINCT FROM s.valid_until
    OR s.snapshot_json->>'completeness_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(
      jsonb_build_object('original_watermark_id',w.id,'original_receipt_hash',w.payload_hash,'records',records)) THEN
    RAISE check_violation USING MESSAGE='type exposure exact content manifest required';
  END IF;
  RETURN s.snapshot_json;
END $old_public_exposure579$;
 new_public_exposure constant text := $new_public_exposure579$
DECLARE s record; w record; watermark bigint; n bigint; records jsonb; t timestamptz;
BEGIN
  PERFORM item_supply_internal.native_exposure_lock(u,e);
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE check_violation USING MESSAGE='type exposure requires read committed';
  END IF;
  SELECT * INTO s FROM tutor_item_supply_type_exposure_snapshots WHERE id=sid AND user_id=u AND epoch=e;
  SELECT * INTO w FROM tutor_item_supply_native_exposure_watermarks WHERE id=s.original_watermark_id AND user_id=u AND epoch=e;
  SELECT COALESCE(max(sequence),0),count(*) INTO watermark,n FROM tutor_item_supply_native_exposure_inbox WHERE user_id=u AND epoch=e;
  t:=clock_timestamp();
  IF s.id IS NULL OR w.id IS NULL OR NOT(s.checked_at<=t AND t<s.valid_until)
    OR w.watermark<>watermark OR w.payload_json->>'origin_count' IS DISTINCT FROM n::text
    OR item_supply_internal.native_exposure_hooks_current() IS DISTINCT FROM true
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_births WHERE id=w.birth_id AND user_id=u AND epoch=e)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_inbox i
      LEFT JOIN tutor_item_supply_native_exposure_events ev ON ev.inbox_id=i.id AND ev.user_id=i.user_id AND ev.epoch=i.epoch
      WHERE i.user_id=u AND i.epoch=e AND i.kind<>'metadata' AND ev.id IS NULL) THEN
    RAISE check_violation USING MESSAGE='type exposure current original ledger required';
  END IF;
  -- Historical immutable content is independent of current publishability.
  SELECT COALESCE(jsonb_agg(jsonb_build_object('event_id',i.id,'item_handle',ev.binding_json->>'item_handle',
      'content_hash',ev.binding_json->>'content_hash','family_id',ev.binding_json->>'family_id',
      'semantic_signature',ev.binding_json->>'semantic_signature','kind',i.kind,'content',f.content_json)
      ORDER BY i.sequence),'[]'::jsonb) INTO records
    FROM tutor_item_supply_native_exposure_events ev
    JOIN tutor_item_supply_native_exposure_inbox i ON i.id=ev.inbox_id AND i.user_id=ev.user_id AND i.epoch=ev.epoch
    JOIN tutor_item_supply_native_content_facts f ON f.user_id=ev.user_id AND f.epoch=ev.epoch
      AND f.version_id=ev.version_id AND f.proof_id=ev.proof_id
    JOIN tutor_learning_item_native_publication_proofs p ON p.id=f.proof_id AND p.version_id=f.version_id AND p.proof_hash=f.proof_hash
    WHERE ev.user_id=u AND ev.epoch=e;
  IF NOT item_supply_internal.snapshot_keys(s.snapshot_json,ARRAY['schema_version','learner_id','epoch',
      'collector_version','watermark','completeness_receipt_hash','observed_at','valid_until','records'])
    OR jsonb_array_length(records)<>(SELECT count(*) FROM tutor_item_supply_native_exposure_events WHERE user_id=u AND epoch=e)
    OR s.snapshot_json->'records' IS DISTINCT FROM records
    OR s.snapshot_json->>'schema_version' IS DISTINCT FROM 'complete_exposure_v2'
    OR s.snapshot_json->>'learner_id' IS DISTINCT FROM u::text OR s.snapshot_json->>'epoch' IS DISTINCT FROM e::text
    OR s.snapshot_json->>'watermark' IS DISTINCT FROM watermark::text
    OR (s.snapshot_json->>'collector_version' IS DISTINCT FROM 'native-type-exposure-v2'
      AND s.snapshot_json->>'collector_version' IS DISTINCT FROM 'native-type-exposure-mvp-v1')
    OR (s.snapshot_json->>'observed_at')::timestamptz IS DISTINCT FROM s.checked_at
    OR (s.snapshot_json->>'valid_until')::timestamptz IS DISTINCT FROM s.valid_until
    OR s.snapshot_json->>'completeness_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(
      jsonb_build_object('original_watermark_id',w.id,'original_receipt_hash',w.payload_hash,'records',records)) THEN
    RAISE check_violation USING MESSAGE='type exposure exact content manifest required';
  END IF;
  RETURN s.snapshot_json;
END $new_public_exposure579$;
 old_private_exposure constant text := $old_private_exposure579$
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
END $old_private_exposure579$;
 new_private_exposure constant text := $new_private_exposure579$
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
  OR (s.payload_json->>'collector_version' IS DISTINCT FROM 'private-native-union-v1'
   AND s.payload_json->>'collector_version' IS DISTINCT FROM 'private-native-union-mvp-v1')
  OR ((s.payload_json->>'collector_version'='private-native-union-mvp-v1') IS TRUE)
   IS DISTINCT FROM ((pub->>'collector_version'='native-type-exposure-mvp-v1') IS TRUE)
  OR s.payload_json->>'learner_id' IS DISTINCT FROM u::text OR s.payload_json->>'epoch' IS DISTINCT FROM e::text
  OR s.payload_json->'records' IS DISTINCT FROM records
  OR s.payload_json->>'completeness_receipt_hash' IS DISTINCT FROM expected
  OR (s.payload_json->>'watermark')::bigint IS DISTINCT FROM w+(pub->>'watermark')::bigint
  OR s.checked_at>stamp OR stamp>=s.valid_until OR s.valid_until>(pub->>'valid_until')::timestamptz
  OR (s.payload_json->>'observed_at')::timestamptz IS DISTINCT FROM s.checked_at
  OR (s.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM s.valid_until THEN
  RAISE check_violation USING MESSAGE='524 exact fresh union exposure required'; END IF;
 RETURN s.payload_json;
END $new_private_exposure579$;
 old_effect constant text := $old_effect579$
DECLARE elig record; reserved record; mapping record; original record; scoped record;
  exposure jsonb; selected jsonb; pair jsonb; b jsonb; c jsonb; spec jsonb;
  native_clauses jsonb; requested_clauses jsonb; mapped_clauses jsonb; field text; t timestamptz; sid uuid; is_mvp boolean;
BEGIN
  PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,NEW.epoch);
  PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans a
    ON a.track_id=s.track_id AND a.user_id=s.user_id AND a.revision_id=s.revision_id
    WHERE s.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch FOR SHARE OF s,a;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='type exposure active original scope required'; END IF;
  exposure:=item_supply_internal.type_exposure_current(NEW.exposure_snapshot_id,NEW.user_id,NEW.epoch);
  SELECT * INTO elig FROM tutor_item_supply_native_eligibility WHERE id=NEW.eligibility_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
  is_mvp:=(elig.snapshot_json->>'schema_version'='pack_snapshot_mvp_v1'
    AND elig.snapshot_json->>'relation_validation'='not_asserted_for_mvp'
    AND elig.snapshot_json->'relationship_receipt_hashes'='[]'::jsonb
    AND cardinality(elig.relation_receipt_ids)=0) IS TRUE;
  t:=clock_timestamp();
  IF elig.id IS NULL OR elig.exposure_snapshot_id IS DISTINCT FROM NEW.exposure_snapshot_id OR elig.txid<>txid_current()
    OR NOT(elig.checked_at<=t AND t<elig.valid_until)
    OR (elig.snapshot_json->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp)
    OR elig.snapshot_json->'request'->>'storage_scope_id' IS DISTINCT FROM NEW.scope_id::text
    OR elig.snapshot_json->>'exposure_receipt_hash' IS DISTINCT FROM exposure->>'completeness_receipt_hash'
    OR elig.snapshot_json->>'exposure_watermark' IS DISTINCT FROM exposure->>'watermark' THEN
    RAISE check_violation USING MESSAGE='type exposure native current eligibility required';
  END IF;
  -- Private consumption contexts remain bound to actual496; shared li content
  -- remains public. No scope.visibility=content.visibility condition is valid.
  SELECT * INTO mapping FROM tutor_item_supply_finite_course_mappings
    WHERE id=elig.mapping_receipt_id AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND practice_scope_id=NEW.scope_id AND receipt_json->'pack_request'=elig.snapshot_json->'request' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='type exposure exact496 learner mapping required'; END IF;
  PERFORM 1 FROM tutor_learning_plan_sessions WHERE id=mapping.session_id AND user_id=NEW.user_id
    AND status='confirmed' AND confirmed_track_id=mapping.track_id AND current_draft_id=mapping.draft_id FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='type exposure confirmed mapping draft stale'; END IF;
  SELECT jsonb_agg(jsonb_build_array(m->0,m->1) ORDER BY n),
    jsonb_agg(jsonb_build_object('clause_id',m->2,'clause_hash',m->3) ORDER BY n)
    INTO requested_clauses,mapped_clauses
    FROM jsonb_array_elements(elig.snapshot_json->'request'->'clause_mapping') WITH ORDINALITY AS clauses(m,n);
  selected:=elig.snapshot_json->'selected';
  IF jsonb_array_length(selected)<>5
    OR (SELECT count(DISTINCT (x->'type_evidence'->'content'->>'version_id')) FROM jsonb_array_elements(selected) x)<>5
    OR (SELECT count(DISTINCT (x->'type_evidence'->'content'->>'item_handle')) FROM jsonb_array_elements(selected) x)<>5
    OR (SELECT count(DISTINCT (x->'type_evidence'->'content'->>'content_hash')) FROM jsonb_array_elements(selected) x)<>5
    OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='practice')<>2
    OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='assessment')<>2
    OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='remediation')<>1 THEN
    RAISE check_violation USING MESSAGE='type exposure exact 221 required';
  END IF;
  SELECT jsonb_agg(x->'type_evidence'->'content' ORDER BY x->'type_evidence'->'content'->>'version_id') INTO pair
    FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='assessment';
  IF item_supply_internal.type_content_clone(pair->0,pair->1) THEN
    RAISE check_violation USING MESSAGE='type exposure assessment clone';
  END IF;
  IF NOT is_mvp THEN
  PERFORM item_supply_internal.type_relation_required(pair->0,pair->1,
    selected->0->'type_evidence'->>'profile',elig.request_hash,NEW.user_id,NEW.epoch,
    elig.mapping_receipt_id,elig.relation_receipt_ids);
  END IF;
  FOR b IN SELECT value FROM jsonb_array_elements(pair) LOOP
    FOR c IN SELECT value->'content' FROM jsonb_array_elements(exposure->'records')
      UNION ALL SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(selected)
        WHERE value->'member'->>'slot'<>'assessment' LOOP
      IF item_supply_internal.type_content_clone(b,c) THEN
        RAISE check_violation USING MESSAGE='type exposure assessment exposed or cloned';
      END IF;
      IF NOT is_mvp THEN
      PERFORM item_supply_internal.type_relation_required(b,c,
        selected->0->'type_evidence'->>'profile',elig.request_hash,NEW.user_id,NEW.epoch,
        elig.mapping_receipt_id,elig.relation_receipt_ids);
      END IF;
    END LOOP;
  END LOOP;
  -- Durable native proofs must still be the latest publication, not merely FKs.
  FOR b IN SELECT value FROM jsonb_array_elements(selected) LOOP
    sid:=(CASE b->'member'->>'slot' WHEN 'practice' THEN mapping.practice_scope_id
      WHEN 'assessment' THEN mapping.assessment_scope_id ELSE mapping.remediation_scope_id END);
    SELECT * INTO scoped FROM tutor_item_supply_private_scopes WHERE id=sid AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND track_id=mapping.track_id AND revision_id=mapping.revision_id AND knowledge_key=mapping.knowledge_key FOR SHARE;
    IF NOT FOUND OR b->>'storage_scope_id' IS DISTINCT FROM sid::text
      OR b->'candidate'->'scope' IS DISTINCT FROM scoped.snapshot_json
      OR b->'candidate'->>'slot' IS DISTINCT FROM b->'member'->>'slot' THEN
      RAISE check_violation USING MESSAGE='type exposure exact496 sub-scope required';
    END IF;
    PERFORM 1 FROM tutor_learning_item_versions WHERE id=(b->'type_evidence'->'content'->>'version_id')::uuid FOR SHARE;
    SELECT p.id,p.version_id,p.materialization_id,p.publication_event_id,p.proof_json->'clauses' AS clauses_json,
      prep.payload_json->'spec' AS spec_json INTO original FROM tutor_item_supply_native_content_facts f
      JOIN tutor_learning_item_native_publication_proofs p ON p.id=f.proof_id AND p.proof_hash=f.proof_hash AND p.version_id=f.version_id
      JOIN tutor_item_supply_shared_admission_facts af ON af.id=p.facts_receipt_id AND af.version_id=p.version_id
      JOIN tutor_item_supply_shared_validation_preparations prep ON prep.id=af.validation_preparation_id
      JOIN LATERAL(SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=f.version_id ORDER BY state_version DESC LIMIT 1) pe
        ON pe.id=p.publication_event_id AND pe.state='published'
      WHERE f.user_id=NEW.user_id AND f.epoch=NEW.epoch AND f.content_json=b->'type_evidence'->'content'
        AND f.version_id=(b->'type_evidence'->'content'->>'version_id')::uuid;
    IF NOT FOUND OR b->>'version_id' IS DISTINCT FROM original.version_id::text
      OR b->>'proof_id' IS DISTINCT FROM original.id::text
      OR b->>'publication_id' IS DISTINCT FROM original.publication_event_id::text
      OR b->>'materialization_id' IS DISTINCT FROM original.materialization_id::text THEN
      RAISE check_violation USING MESSAGE='type exposure original native publication stale';
    END IF;
    SELECT jsonb_agg(jsonb_build_array(upper(m->>'clause_id'),m->>'clause_hash') ORDER BY n)
      INTO native_clauses FROM jsonb_array_elements(original.clauses_json) WITH ORDINALITY AS clauses(m,n);
    IF jsonb_array_length(original.clauses_json) IS DISTINCT FROM 3
      OR native_clauses IS DISTINCT FROM requested_clauses
      OR b->'candidate'->'clauses' IS DISTINCT FROM mapped_clauses
      OR b->'candidate'->'proof'->'clauses' IS DISTINCT FROM mapped_clauses THEN
      RAISE check_violation USING MESSAGE='type exposure exact original and mapped clauses required';
    END IF;
    -- A real publication/content FK is not permission to relabel its actual
    -- assessment as practice (or substitute a different course's statement).
    spec:=original.spec_json;
    IF b->'member'->>'slot' IS DISTINCT FROM spec->'allocation'->>'slot'
      OR b->'member'->>'purpose' IS DISTINCT FROM spec->'allocation'->>'purpose'
      OR b->'member'->>'purpose' IS DISTINCT FROM scoped.snapshot_json->>'purpose'
      OR b->'member'->>'family_id' IS DISTINCT FROM spec->'allocation'->>'family_id'
      OR b->'member'->>'allocation_variant_id' IS DISTINCT FROM spec->'allocation'->>'variant_id'
      OR spec->>'target_id' IS DISTINCT FROM elig.snapshot_json->'request'->>'target_id'
      OR spec->>'target_definition_hash' IS DISTINCT FROM elig.snapshot_json->'request'->>'target_definition_hash'
      OR b->'candidate'->>'visibility' IS DISTINCT FROM 'public'
      OR b->'owner_id' IS DISTINCT FROM 'null'::jsonb OR b->'epoch' IS DISTINCT FROM 'null'::jsonb
      OR b->'candidate'->>'item_handle' IS DISTINCT FROM b->'type_evidence'->'content'->>'item_handle'
      OR b->'candidate'->>'content_hash' IS DISTINCT FROM b->'type_evidence'->'content'->>'content_hash' THEN
      RAISE check_violation USING MESSAGE='type exposure original statement slot purpose required';
    END IF;
    FOREACH field IN ARRAY ARRAY['language_id','subject_id','subject_version','required_facets','required_capabilities',
        'runtime_profile_id','runtime_profile_hash','scorer_version','assistance_policy_hash','assessment_contract_version'] LOOP
      IF spec->'coverage_blueprint'->'scope'->field IS DISTINCT FROM scoped.snapshot_json->field THEN
        RAISE check_violation USING MESSAGE='type exposure original statement scope required';
      END IF;
    END LOOP;
  END LOOP;
  IF TG_TABLE_NAME='tutor_item_supply_type_exposure_reservations' THEN
    IF NEW.bindings_json IS DISTINCT FROM pair OR NEW.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.request_json)
      OR NEW.request_json->'bindings' IS DISTINCT FROM pair
      OR NEW.request_json->>'mapping_receipt_id' IS DISTINCT FROM elig.mapping_receipt_id::text
      OR NEW.request_json->'candidate_version_ids' IS DISTINCT FROM to_jsonb(elig.candidate_version_ids)
      OR NEW.request_json->'relation_receipt_ids' IS DISTINCT FROM to_jsonb(elig.relation_receipt_ids)
      OR NEW.request_json->>'pack_request_hash' IS DISTINCT FROM elig.request_hash
      OR NEW.request_json->'selected_version_ids' IS DISTINCT FROM (SELECT jsonb_agg(x->'type_evidence'->'content'->>'version_id'
        ORDER BY x->'type_evidence'->'content'->>'version_id') FROM jsonb_array_elements(selected) x) THEN
      RAISE check_violation USING MESSAGE='type exposure exact reservation binding required';
    END IF;
  ELSE
    SELECT * INTO reserved FROM tutor_item_supply_type_exposure_reservations
      WHERE id=NEW.reservation_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    IF reserved.id IS NULL OR reserved.bindings_json IS DISTINCT FROM pair OR NEW.delivery_txid<>txid_current()
      OR reserved.request_json->>'mapping_receipt_id' IS DISTINCT FROM elig.mapping_receipt_id::text
      OR reserved.request_json->'candidate_version_ids' IS DISTINCT FROM to_jsonb(elig.candidate_version_ids)
      OR (NOT is_mvp AND reserved.request_json->'relation_receipt_ids' IS DISTINCT FROM to_jsonb(elig.relation_receipt_ids))
      OR reserved.request_json->>'pack_request_hash' IS DISTINCT FROM elig.request_hash
      OR reserved.request_json->'selected_version_ids' IS DISTINCT FROM (SELECT jsonb_agg(x->'type_evidence'->'content'->>'version_id'
        ORDER BY x->'type_evidence'->'content'->>'version_id') FROM jsonb_array_elements(selected) x)
      OR NEW.binding_json->>'version_id' IS DISTINCT FROM NEW.version_id::text
      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='practice'
        AND x->'type_evidence'->'content'=NEW.binding_json)
      OR NEW.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('reservation_id',reserved.id,'binding',NEW.binding_json)) THEN
      RAISE check_violation USING MESSAGE='type exposure exact same transaction practice required';
    END IF;
  END IF;
  -- Recheck time after all row-lock waits, not the earlier transaction clock.
  t:=clock_timestamp();
  IF t>=elig.valid_until OR t>=(exposure->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='type exposure expired after lock wait';
  END IF;
  RETURN NEW;
END $old_effect579$;
 new_effect constant text := $new_effect579$
DECLARE elig record; reserved record; mapping record; original record; scoped record;
  exposure jsonb; selected jsonb; pair jsonb; b jsonb; c jsonb; spec jsonb;
  native_clauses jsonb; requested_clauses jsonb; mapped_clauses jsonb; field text; t timestamptz; sid uuid; is_mvp boolean;
BEGIN
  PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,NEW.epoch);
  PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans a
    ON a.track_id=s.track_id AND a.user_id=s.user_id AND a.revision_id=s.revision_id
    WHERE s.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch FOR SHARE OF s,a;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='type exposure active original scope required'; END IF;
  exposure:=item_supply_internal.type_exposure_current(NEW.exposure_snapshot_id,NEW.user_id,NEW.epoch);
  SELECT * INTO elig FROM tutor_item_supply_native_eligibility WHERE id=NEW.eligibility_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
  is_mvp:=(elig.snapshot_json->>'schema_version'='pack_snapshot_mvp_v1'
    AND elig.snapshot_json->>'relation_validation'='not_asserted_for_mvp'
    AND elig.snapshot_json->'relationship_receipt_hashes'='[]'::jsonb
    AND cardinality(elig.relation_receipt_ids)=0) IS TRUE;
  t:=clock_timestamp();
  IF elig.id IS NULL OR elig.exposure_snapshot_id IS DISTINCT FROM NEW.exposure_snapshot_id OR elig.txid<>txid_current()
    OR NOT(elig.checked_at<=t AND t<elig.valid_until)
    OR (elig.snapshot_json->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp)
    OR (NOT is_mvp AND (exposure->>'collector_version'='native-type-exposure-mvp-v1') IS TRUE)
    OR elig.snapshot_json->'request'->>'storage_scope_id' IS DISTINCT FROM NEW.scope_id::text
    OR elig.snapshot_json->>'exposure_receipt_hash' IS DISTINCT FROM exposure->>'completeness_receipt_hash'
    OR elig.snapshot_json->>'exposure_watermark' IS DISTINCT FROM exposure->>'watermark' THEN
    RAISE check_violation USING MESSAGE='type exposure native current eligibility required';
  END IF;
  -- Private consumption contexts remain bound to actual496; shared li content
  -- remains public. No scope.visibility=content.visibility condition is valid.
  SELECT * INTO mapping FROM tutor_item_supply_finite_course_mappings
    WHERE id=elig.mapping_receipt_id AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND practice_scope_id=NEW.scope_id AND receipt_json->'pack_request'=elig.snapshot_json->'request' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='type exposure exact496 learner mapping required'; END IF;
  PERFORM 1 FROM tutor_learning_plan_sessions WHERE id=mapping.session_id AND user_id=NEW.user_id
    AND status='confirmed' AND confirmed_track_id=mapping.track_id AND current_draft_id=mapping.draft_id FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='type exposure confirmed mapping draft stale'; END IF;
  SELECT jsonb_agg(jsonb_build_array(m->0,m->1) ORDER BY n),
    jsonb_agg(jsonb_build_object('clause_id',m->2,'clause_hash',m->3) ORDER BY n)
    INTO requested_clauses,mapped_clauses
    FROM jsonb_array_elements(elig.snapshot_json->'request'->'clause_mapping') WITH ORDINALITY AS clauses(m,n);
  selected:=elig.snapshot_json->'selected';
  IF jsonb_array_length(selected)<>5
    OR (SELECT count(DISTINCT (x->'type_evidence'->'content'->>'version_id')) FROM jsonb_array_elements(selected) x)<>5
    OR (SELECT count(DISTINCT (x->'type_evidence'->'content'->>'item_handle')) FROM jsonb_array_elements(selected) x)<>5
    OR (SELECT count(DISTINCT (x->'type_evidence'->'content'->>'content_hash')) FROM jsonb_array_elements(selected) x)<>5
    OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='practice')<>2
    OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='assessment')<>2
    OR (SELECT count(*) FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='remediation')<>1 THEN
    RAISE check_violation USING MESSAGE='type exposure exact 221 required';
  END IF;
  SELECT jsonb_agg(x->'type_evidence'->'content' ORDER BY x->'type_evidence'->'content'->>'version_id') INTO pair
    FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='assessment';
  IF item_supply_internal.type_content_clone(pair->0,pair->1) THEN
    RAISE check_violation USING MESSAGE='type exposure assessment clone';
  END IF;
  IF NOT is_mvp THEN
  PERFORM item_supply_internal.type_relation_required(pair->0,pair->1,
    selected->0->'type_evidence'->>'profile',elig.request_hash,NEW.user_id,NEW.epoch,
    elig.mapping_receipt_id,elig.relation_receipt_ids);
  END IF;
  FOR b IN SELECT value FROM jsonb_array_elements(pair) LOOP
    FOR c IN SELECT value->'content' FROM jsonb_array_elements(exposure->'records')
      UNION ALL SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(selected)
        WHERE value->'member'->>'slot'<>'assessment' LOOP
      IF item_supply_internal.type_content_clone(b,c) THEN
        RAISE check_violation USING MESSAGE='type exposure assessment exposed or cloned';
      END IF;
      IF NOT is_mvp THEN
      PERFORM item_supply_internal.type_relation_required(b,c,
        selected->0->'type_evidence'->>'profile',elig.request_hash,NEW.user_id,NEW.epoch,
        elig.mapping_receipt_id,elig.relation_receipt_ids);
      END IF;
    END LOOP;
  END LOOP;
  -- Durable native proofs must still be the latest publication, not merely FKs.
  FOR b IN SELECT value FROM jsonb_array_elements(selected) LOOP
    sid:=(CASE b->'member'->>'slot' WHEN 'practice' THEN mapping.practice_scope_id
      WHEN 'assessment' THEN mapping.assessment_scope_id ELSE mapping.remediation_scope_id END);
    SELECT * INTO scoped FROM tutor_item_supply_private_scopes WHERE id=sid AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND track_id=mapping.track_id AND revision_id=mapping.revision_id AND knowledge_key=mapping.knowledge_key FOR SHARE;
    IF NOT FOUND OR b->>'storage_scope_id' IS DISTINCT FROM sid::text
      OR b->'candidate'->'scope' IS DISTINCT FROM scoped.snapshot_json
      OR b->'candidate'->>'slot' IS DISTINCT FROM b->'member'->>'slot' THEN
      RAISE check_violation USING MESSAGE='type exposure exact496 sub-scope required';
    END IF;
    PERFORM 1 FROM tutor_learning_item_versions WHERE id=(b->'type_evidence'->'content'->>'version_id')::uuid FOR SHARE;
    SELECT p.id,p.version_id,p.materialization_id,p.publication_event_id,p.proof_json->'clauses' AS clauses_json,
      prep.payload_json->'spec' AS spec_json INTO original FROM tutor_item_supply_native_content_facts f
      JOIN tutor_learning_item_native_publication_proofs p ON p.id=f.proof_id AND p.proof_hash=f.proof_hash AND p.version_id=f.version_id
      JOIN tutor_item_supply_shared_admission_facts af ON af.id=p.facts_receipt_id AND af.version_id=p.version_id
      JOIN tutor_item_supply_shared_validation_preparations prep ON prep.id=af.validation_preparation_id
      JOIN LATERAL(SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=f.version_id ORDER BY state_version DESC LIMIT 1) pe
        ON pe.id=p.publication_event_id AND pe.state='published'
      WHERE f.user_id=NEW.user_id AND f.epoch=NEW.epoch AND f.content_json=b->'type_evidence'->'content'
        AND f.version_id=(b->'type_evidence'->'content'->>'version_id')::uuid;
    IF NOT FOUND OR b->>'version_id' IS DISTINCT FROM original.version_id::text
      OR b->>'proof_id' IS DISTINCT FROM original.id::text
      OR b->>'publication_id' IS DISTINCT FROM original.publication_event_id::text
      OR b->>'materialization_id' IS DISTINCT FROM original.materialization_id::text THEN
      RAISE check_violation USING MESSAGE='type exposure original native publication stale';
    END IF;
    SELECT jsonb_agg(jsonb_build_array(upper(m->>'clause_id'),m->>'clause_hash') ORDER BY n)
      INTO native_clauses FROM jsonb_array_elements(original.clauses_json) WITH ORDINALITY AS clauses(m,n);
    IF jsonb_array_length(original.clauses_json) IS DISTINCT FROM 3
      OR native_clauses IS DISTINCT FROM requested_clauses
      OR b->'candidate'->'clauses' IS DISTINCT FROM mapped_clauses
      OR b->'candidate'->'proof'->'clauses' IS DISTINCT FROM mapped_clauses THEN
      RAISE check_violation USING MESSAGE='type exposure exact original and mapped clauses required';
    END IF;
    -- A real publication/content FK is not permission to relabel its actual
    -- assessment as practice (or substitute a different course's statement).
    spec:=original.spec_json;
    IF b->'member'->>'slot' IS DISTINCT FROM spec->'allocation'->>'slot'
      OR b->'member'->>'purpose' IS DISTINCT FROM spec->'allocation'->>'purpose'
      OR b->'member'->>'purpose' IS DISTINCT FROM scoped.snapshot_json->>'purpose'
      OR b->'member'->>'family_id' IS DISTINCT FROM spec->'allocation'->>'family_id'
      OR b->'member'->>'allocation_variant_id' IS DISTINCT FROM spec->'allocation'->>'variant_id'
      OR spec->>'target_id' IS DISTINCT FROM elig.snapshot_json->'request'->>'target_id'
      OR spec->>'target_definition_hash' IS DISTINCT FROM elig.snapshot_json->'request'->>'target_definition_hash'
      OR b->'candidate'->>'visibility' IS DISTINCT FROM 'public'
      OR b->'owner_id' IS DISTINCT FROM 'null'::jsonb OR b->'epoch' IS DISTINCT FROM 'null'::jsonb
      OR b->'candidate'->>'item_handle' IS DISTINCT FROM b->'type_evidence'->'content'->>'item_handle'
      OR b->'candidate'->>'content_hash' IS DISTINCT FROM b->'type_evidence'->'content'->>'content_hash' THEN
      RAISE check_violation USING MESSAGE='type exposure original statement slot purpose required';
    END IF;
    FOREACH field IN ARRAY ARRAY['language_id','subject_id','subject_version','required_facets','required_capabilities',
        'runtime_profile_id','runtime_profile_hash','scorer_version','assistance_policy_hash','assessment_contract_version'] LOOP
      IF spec->'coverage_blueprint'->'scope'->field IS DISTINCT FROM scoped.snapshot_json->field THEN
        RAISE check_violation USING MESSAGE='type exposure original statement scope required';
      END IF;
    END LOOP;
  END LOOP;
  IF TG_TABLE_NAME='tutor_item_supply_type_exposure_reservations' THEN
    IF NEW.bindings_json IS DISTINCT FROM pair OR NEW.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.request_json)
      OR NEW.request_json->'bindings' IS DISTINCT FROM pair
      OR NEW.request_json->>'mapping_receipt_id' IS DISTINCT FROM elig.mapping_receipt_id::text
      OR NEW.request_json->'candidate_version_ids' IS DISTINCT FROM to_jsonb(elig.candidate_version_ids)
      OR NEW.request_json->'relation_receipt_ids' IS DISTINCT FROM to_jsonb(elig.relation_receipt_ids)
      OR NEW.request_json->>'pack_request_hash' IS DISTINCT FROM elig.request_hash
      OR NEW.request_json->'selected_version_ids' IS DISTINCT FROM (SELECT jsonb_agg(x->'type_evidence'->'content'->>'version_id'
        ORDER BY x->'type_evidence'->'content'->>'version_id') FROM jsonb_array_elements(selected) x) THEN
      RAISE check_violation USING MESSAGE='type exposure exact reservation binding required';
    END IF;
  ELSE
    SELECT * INTO reserved FROM tutor_item_supply_type_exposure_reservations
      WHERE id=NEW.reservation_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    IF reserved.id IS NULL OR reserved.bindings_json IS DISTINCT FROM pair OR NEW.delivery_txid<>txid_current()
      OR reserved.request_json->>'mapping_receipt_id' IS DISTINCT FROM elig.mapping_receipt_id::text
      OR reserved.request_json->'candidate_version_ids' IS DISTINCT FROM to_jsonb(elig.candidate_version_ids)
      OR (NOT is_mvp AND reserved.request_json->'relation_receipt_ids' IS DISTINCT FROM to_jsonb(elig.relation_receipt_ids))
      OR reserved.request_json->>'pack_request_hash' IS DISTINCT FROM elig.request_hash
      OR reserved.request_json->'selected_version_ids' IS DISTINCT FROM (SELECT jsonb_agg(x->'type_evidence'->'content'->>'version_id'
        ORDER BY x->'type_evidence'->'content'->>'version_id') FROM jsonb_array_elements(selected) x)
      OR NEW.binding_json->>'version_id' IS DISTINCT FROM NEW.version_id::text
      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(selected) x WHERE x->'member'->>'slot'='practice'
        AND x->'type_evidence'->'content'=NEW.binding_json)
      OR NEW.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('reservation_id',reserved.id,'binding',NEW.binding_json)) THEN
      RAISE check_violation USING MESSAGE='type exposure exact same transaction practice required';
    END IF;
  END IF;
  -- Recheck time after all row-lock waits, not the earlier transaction clock.
  t:=clock_timestamp();
  IF t>=elig.valid_until OR t>=(exposure->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='type exposure expired after lock wait';
  END IF;
  RETURN NEW;
END $new_effect579$;
 old_eligibility constant text := $old_eligibility579$
DECLARE el record; p jsonb;s jsonb;m jsonb;ex jsonb;c jsonb;other jsonb;pc jsonb;pub record;q record;role jsonb;t timestamptz;is_mvp boolean;
BEGIN
 SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=eid;
 IF NOT FOUND OR el.txid<>txid_current() THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(el.user_id,el.epoch);
 m:=item_supply_internal.private_native_mapping_current(el.mapping_id,el.user_id,el.epoch);
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);
 p:=el.payload_json;s:=p->'snapshot';
 is_mvp:=(s->>'schema_version'='pack_snapshot_mvp_v1'
  AND s->>'relation_validation'='not_asserted_for_mvp'
  AND s->'relationship_receipt_hashes'='[]'::jsonb
  AND p->'relations'='[]'::jsonb) IS TRUE;
 IF m IS NULL OR ex IS NULL OR p->>'schema_version' IS DISTINCT FROM 'private_native_eligibility_v1'
  OR (p->>'mapping_id',p->>'exposure_id') IS DISTINCT FROM (el.mapping_id::text,el.exposure_snapshot_id::text)
  OR (s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp) OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR p->>'inputs_hash' IS DISTINCT FROM s->>'inputs_hash' OR s->>'authority_status' IS DISTINCT FROM 'trusted_caller_computation_only'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_typeof(s->'selected') IS DISTINCT FROM 'array' OR jsonb_array_length(s->'selected')<>5
  OR jsonb_typeof(p->'versions') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'versions')<>5
  OR (NOT is_mvp AND (jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations') NOT BETWEEN 1 AND 16))
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
 IF (SELECT count(DISTINCT slot_evidence.slot_id) FROM tutor_item_supply_private_native_quality_evidence slot_evidence WHERE slot_evidence.id IN
   (SELECT (selected_proof.value->>'proof_id')::uuid FROM jsonb_array_elements(s->'selected') AS selected_proof(value)))<>5 THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(s->'selected') WHERE value->>'version_id'<>c->>'version_id'
    UNION SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other)
    OR (NOT is_mvp AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,el.user_id,el.epoch,el.pack_task_id) IS DISTINCT FROM true) THEN RETURN false; END IF;
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
END $old_eligibility579$;
 new_eligibility constant text := $new_eligibility579$
DECLARE el record; p jsonb;s jsonb;m jsonb;ex jsonb;c jsonb;other jsonb;pc jsonb;pub record;q record;role jsonb;t timestamptz;is_mvp boolean;
BEGIN
 SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=eid;
 IF NOT FOUND OR el.txid<>txid_current() THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(el.user_id,el.epoch);
 m:=item_supply_internal.private_native_mapping_current(el.mapping_id,el.user_id,el.epoch);
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);
 p:=el.payload_json;s:=p->'snapshot';
 is_mvp:=(s->>'schema_version'='pack_snapshot_mvp_v1'
  AND s->>'relation_validation'='not_asserted_for_mvp'
  AND s->'relationship_receipt_hashes'='[]'::jsonb
  AND p->'relations'='[]'::jsonb) IS TRUE;
 IF m IS NULL OR ex IS NULL OR p->>'schema_version' IS DISTINCT FROM 'private_native_eligibility_v1'
  OR (p->>'mapping_id',p->>'exposure_id') IS DISTINCT FROM (el.mapping_id::text,el.exposure_snapshot_id::text)
  OR (s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp)
  OR (NOT is_mvp AND (ex->>'collector_version'='private-native-union-mvp-v1') IS TRUE) OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR p->>'inputs_hash' IS DISTINCT FROM s->>'inputs_hash' OR s->>'authority_status' IS DISTINCT FROM 'trusted_caller_computation_only'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_typeof(s->'selected') IS DISTINCT FROM 'array' OR jsonb_array_length(s->'selected')<>5
  OR jsonb_typeof(p->'versions') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'versions')<>5
  OR (NOT is_mvp AND (jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations') NOT BETWEEN 1 AND 16))
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
 IF (SELECT count(DISTINCT slot_evidence.slot_id) FROM tutor_item_supply_private_native_quality_evidence slot_evidence WHERE slot_evidence.id IN
   (SELECT (selected_proof.value->>'proof_id')::uuid FROM jsonb_array_elements(s->'selected') AS selected_proof(value)))<>5 THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(s->'selected') WHERE value->>'version_id'<>c->>'version_id'
    UNION SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other)
    OR (NOT is_mvp AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,el.user_id,el.epoch,el.pack_task_id) IS DISTINCT FROM true) THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 -- Lock waits must not carry an old clock/source/exposure observation forward.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  SELECT payload_json INTO pc FROM tutor_item_supply_private_native_quality_evidence WHERE id=(c->>'proof_id')::uuid;
  IF item_supply_internal.private_native_source_current(pc) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND el.valid_until<=el.checked_at+(CASE WHEN is_mvp THEN interval '600 seconds' ELSE interval '30 seconds' END)
  AND (s->>'checked_at')::timestamptz=el.checked_at AND (s->>'valid_until')::timestamptz=el.valid_until;
END $new_eligibility579$;
 old_union constant text := $old_union579$

DECLARE r record;el record;m jsonb;ex jsonb;p jsonb;s jsonb;c jsonb;other jsonb;original jsonb;proof record;t timestamptz;is_mvp boolean;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_status';
 IF NOT FOUND THEN RETURN false; END IF;
 p:=r.payload_json;s:=p->'snapshot';
 is_mvp:=(s->>'schema_version'='pack_snapshot_mvp_v1'
  AND s->>'relation_validation'='not_asserted_for_mvp'
  AND s->'relationship_receipt_hashes'='[]'::jsonb
  AND p->'relations'='[]'::jsonb) IS TRUE;
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
 IF m IS NULL OR ex IS NULL OR (s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp)
  OR el.snapshot_json->>'schema_version' IS DISTINCT FROM s->>'schema_version'
  OR (is_mvp AND (el.snapshot_json->>'relation_validation' IS DISTINCT FROM 'not_asserted_for_mvp'
   OR el.snapshot_json->'relationship_receipt_hashes' IS DISTINCT FROM '[]'::jsonb
   OR cardinality(el.relation_receipt_ids) IS DISTINCT FROM 0)) OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_array_length(s->'selected')<>5 OR jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations')>16
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='remediation')<>1
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
   -- exposure requires a genuine PRIVATE four-role batch for THIS actual pair (legacy only).
   IF NOT is_mvp AND other->>'item_handle' LIKE 'lip:v2:%' AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,r.user_id,r.epoch::bigint,r.pack_task_id) IS DISTINCT FROM true THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND (p->>'checked_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz
  AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '120 seconds';
END 
$old_union579$;
 new_union constant text := $new_union579$

DECLARE r record;el record;m jsonb;ex jsonb;p jsonb;s jsonb;c jsonb;other jsonb;original jsonb;proof record;t timestamptz;is_mvp boolean;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_status';
 IF NOT FOUND THEN RETURN false; END IF;
 p:=r.payload_json;s:=p->'snapshot';
 is_mvp:=(s->>'schema_version'='pack_snapshot_mvp_v1'
  AND s->>'relation_validation'='not_asserted_for_mvp'
  AND s->'relationship_receipt_hashes'='[]'::jsonb
  AND p->'relations'='[]'::jsonb) IS TRUE;
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
 IF m IS NULL OR ex IS NULL OR (s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp)
  OR (NOT is_mvp AND (ex->>'collector_version'='private-native-union-mvp-v1') IS TRUE)
  OR el.snapshot_json->>'schema_version' IS DISTINCT FROM s->>'schema_version'
  OR (is_mvp AND (el.snapshot_json->>'relation_validation' IS DISTINCT FROM 'not_asserted_for_mvp'
   OR el.snapshot_json->'relationship_receipt_hashes' IS DISTINCT FROM '[]'::jsonb
   OR cardinality(el.relation_receipt_ids) IS DISTINCT FROM 0)) OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_array_length(s->'selected')<>5 OR jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations')>16
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='remediation')<>1
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
   -- exposure requires a genuine PRIVATE four-role batch for THIS actual pair (legacy only).
   IF NOT is_mvp AND other->>'item_handle' LIKE 'lip:v2:%' AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,r.user_id,r.epoch::bigint,r.pack_task_id) IS DISTINCT FROM true THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND (p->>'checked_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz
  AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+(CASE WHEN is_mvp THEN interval '600 seconds' ELSE interval '120 seconds' END);
END 
$new_union579$;
 old_private_consumer constant text := $old_private_consumer579$
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
  SELECT value INTO selected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') WHERE value->>'version_id'=r.version_id::text AND value->'member'->>'slot'=CASE WHEN p->'request'->>'purpose'='remediation' THEN 'remediation' ELSE 'practice' END;
  SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO protected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE c->'member'->>'slot'='assessment';
  IF selected IS NULL OR selected IS DISTINCT FROM p->'selected' OR p->'content' IS DISTINCT FROM selected->'type_evidence'->'content'
   OR protected IS DISTINCT FROM res.payload_json->'protected'
   OR p->>'pack_request_hash' IS DISTINCT FROM res.payload_json->>'pack_request_hash'
   OR p->>'pack_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(el.payload_json->'snapshot'->'request')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE NOT EXISTS
      (SELECT 1 FROM jsonb_array_elements_text(res.payload_json->'versions') v WHERE v.value=c->>'version_id')) THEN RETURN false; END IF;
  creation:=p;q:=p->'request';
  IF (q->>'purpose'<>'knowledge_check' OR p->>'parent_artifact_id' IS NOT NULL) AND item_supply_internal.private_native_successor_creation_current(r.id) IS DISTINCT FROM true THEN RETURN false; END IF;
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
   IS DISTINCT FROM (r.user_id::text,r.version_id::text,'learning_item','knowledge_check',CASE WHEN creation->>'parent_artifact_id' IS NOT NULL AND q->>'purpose' IN('remediation','transfer_check') THEN q->>'purpose' ELSE 'knowledge_check' END,m->'frozen_node'->>'knowledge_key',m->'frozen_node'->>'track_id')
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
END $old_private_consumer579$;
 new_private_consumer constant text := $new_private_consumer579$
DECLARE r record;b record;a record;el record;res record;pub record;m jsonb;creation jsonb;q jsonb;p jsonb;current_pub jsonb;selected jsonb;protected jsonb;t timestamptz;is_mvp boolean;
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
  SELECT value INTO selected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') WHERE value->>'version_id'=r.version_id::text AND value->'member'->>'slot'=CASE WHEN p->'request'->>'purpose'='remediation' THEN 'remediation' ELSE 'practice' END;
  SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO protected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE c->'member'->>'slot'='assessment';
  IF selected IS NULL OR selected IS DISTINCT FROM p->'selected' OR p->'content' IS DISTINCT FROM selected->'type_evidence'->'content'
   OR protected IS DISTINCT FROM res.payload_json->'protected'
   OR p->>'pack_request_hash' IS DISTINCT FROM res.payload_json->>'pack_request_hash'
   OR p->>'pack_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(el.payload_json->'snapshot'->'request')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE NOT EXISTS
      (SELECT 1 FROM jsonb_array_elements_text(res.payload_json->'versions') v WHERE v.value=c->>'version_id')) THEN RETURN false; END IF;
  creation:=p;q:=p->'request';
  IF (q->>'purpose'<>'knowledge_check' OR p->>'parent_artifact_id' IS NOT NULL) AND item_supply_internal.private_native_successor_creation_current(r.id) IS DISTINCT FROM true THEN RETURN false; END IF;
 ELSE
  IF r.mode NOT IN('current','cancel') OR r.action NOT IN('request_hint','request_direct_answer','respond','cancel')
   OR (r.mode='cancel') IS DISTINCT FROM (r.action='cancel')
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_action_v1' OR p->>'action' IS DISTINCT FROM r.action
   OR p->>'artifact_id' IS DISTINCT FROM r.artifact_id::text OR p->>'artifact_version' IS DISTINCT FROM r.artifact_version::text THEN RETURN false; END IF;
  SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=r.artifact_id AND user_id=r.user_id AND epoch=r.epoch AND version_id=r.version_id AND scope_id=r.scope_id AND pack_task_id=r.pack_task_id;
  IF NOT FOUND OR p->>'creation_receipt_id' IS DISTINCT FROM b.creation_receipt_id::text THEN RETURN false; END IF;
  SELECT payload_json INTO creation FROM tutor_item_supply_private_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';q:=creation->'request';
  -- Historical eligibility is policy DATA only; fresh action/source checks remain below.
  SELECT eligibility.* INTO el FROM tutor_item_supply_private_native_eligibility eligibility
   JOIN tutor_item_supply_private_native_consumer_receipts origin ON origin.eligibility_id=eligibility.id
   WHERE origin.id=b.creation_receipt_id AND origin.user_id=r.user_id AND origin.epoch=r.epoch
    AND eligibility.user_id=r.user_id AND eligibility.epoch=r.epoch;
  SELECT * INTO a FROM tutor_learning_artifacts WHERE id=r.artifact_id AND user_id=r.user_id AND version=r.artifact_version AND owner_kind='learning_item'
    AND owner_id=r.version_id AND artifact_kind='knowledge_check' AND state IN('pending','ready','active') AND active_attempt_id IS NULL;
  IF NOT FOUND OR item_supply_internal.native_consumer_frozen_artifact_matches(q,a) IS DISTINCT FROM true THEN RETURN false; END IF;
 END IF;
 is_mvp:=(el.payload_json->'snapshot'->>'schema_version'='pack_snapshot_mvp_v1' AND el.payload_json->'snapshot'->>'relation_validation'='not_asserted_for_mvp' AND el.payload_json->'snapshot'->'relationship_receipt_hashes'='[]'::jsonb AND el.payload_json->'relations'='[]'::jsonb) IS TRUE;
 m:=item_supply_internal.private_native_mapping_current((creation->>'mapping_id')::uuid,r.user_id,r.epoch);
 IF m IS NULL OR (q->>'user_id',q->>'owner_id',q->>'owner_kind',q->>'artifact_kind',q->>'purpose',q->>'knowledge_key',q->>'learning_track_id')
   IS DISTINCT FROM (r.user_id::text,r.version_id::text,'learning_item','knowledge_check',CASE WHEN creation->>'parent_artifact_id' IS NOT NULL AND q->>'purpose' IN('remediation','transfer_check') THEN q->>'purpose' ELSE 'knowledge_check' END,m->'frozen_node'->>'knowledge_key',m->'frozen_node'->>'track_id')
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
 RETURN r.checked_at<=t AND t<r.valid_until AND r.valid_until<=r.checked_at+(CASE WHEN is_mvp THEN interval '600 seconds' ELSE interval '30 seconds' END);
END $new_private_consumer579$;
 old_public_consumer constant text := $old_public_consumer579$

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
$old_public_consumer579$;
 new_public_consumer constant text := $new_public_consumer579$

DECLARE r record; m record; n record; d record; el record; a record; binding record;
 p jsonb; original jsonb; q jsonb; selected jsonb; t timestamptz; consumption jsonb; is_mvp boolean:=false;
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
   is_mvp:=(el.snapshot_json->>'schema_version'='pack_snapshot_mvp_v1' AND el.snapshot_json->>'relation_validation'='not_asserted_for_mvp' AND el.snapshot_json->'relationship_receipt_hashes'='[]'::jsonb AND cardinality(el.relation_receipt_ids)=0) IS TRUE;
   IF p->'current_consumption' ? 'window_policy' AND
    (p->'current_consumption'->>'window_policy' IS DISTINCT FROM 'mvp_600_seconds_v1' OR NOT is_mvp) THEN RETURN false; END IF;
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
   -- This linked creation marker is immutable policy DATA, never its old deadline.
   is_mvp:=(original->'current_consumption'->>'window_policy'='mvp_600_seconds_v1') IS TRUE;
   IF p->'current_consumption' ? 'window_policy' AND
    (p->'current_consumption'->>'window_policy' IS DISTINCT FROM 'mvp_600_seconds_v1' OR NOT is_mvp) THEN RETURN false; END IF;
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
$new_public_consumer579$;
 old_clearance constant text := $old_clearance579$
DECLARE p jsonb:=NEW.payload_json;el record;un record;stamp timestamptz;
BEGIN
 IF p->>'schema_version' IS DISTINCT FROM 'private_native_public_fallback_clearance_v1' THEN RETURN NEW; END IF;
 IF NEW.record_kind<>'private_attachment' OR (NEW.pack_task_id::text,NEW.user_id::text,NEW.epoch::text,NEW.scope_id::text)
  IS DISTINCT FROM (p->'task_ref'->>'pack_task_id',p->'task_ref'->>'user_id',p->'task_ref'->>'epoch',p->'task_ref'->>'scope_id')
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','task_ref','run_id','stage','selected_version_id','reservation_id','public_eligibility_id','union_receipt_id','checked_at','valid_until','txid']) IS DISTINCT FROM true
  OR p->>'txid' IS DISTINCT FROM txid_current()::text THEN
  RAISE check_violation USING MESSAGE='529 clearance exact PRIVATE task coordinates/transaction required'; END IF;
 PERFORM item_supply_internal.assert_private_native_public_fallback_frame(p-ARRAY['checked_at','valid_until','txid']);
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid;
 SELECT * INTO un FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'union_receipt_id')::uuid;
 stamp:=clock_timestamp();
 IF COALESCE((p->>'checked_at')::timestamptz<=stamp AND stamp<(p->>'valid_until')::timestamptz,false) IS DISTINCT FROM true
  OR (p->>'valid_until')::timestamptz>LEAST(el.valid_until,(un.payload_json->>'valid_until')::timestamptz,(p->>'checked_at')::timestamptz+interval '30 seconds') THEN
  RAISE check_violation USING MESSAGE='529 clearance fresh observation bounds required'; END IF;
 RETURN NEW;
END $old_clearance579$;
 new_clearance constant text := $new_clearance579$
DECLARE p jsonb:=NEW.payload_json;el record;un record;stamp timestamptz;
BEGIN
 IF p->>'schema_version' IS DISTINCT FROM 'private_native_public_fallback_clearance_v1' THEN RETURN NEW; END IF;
 IF NEW.record_kind<>'private_attachment' OR (NEW.pack_task_id::text,NEW.user_id::text,NEW.epoch::text,NEW.scope_id::text)
  IS DISTINCT FROM (p->'task_ref'->>'pack_task_id',p->'task_ref'->>'user_id',p->'task_ref'->>'epoch',p->'task_ref'->>'scope_id')
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','task_ref','run_id','stage','selected_version_id','reservation_id','public_eligibility_id','union_receipt_id','checked_at','valid_until','txid']) IS DISTINCT FROM true
  OR p->>'txid' IS DISTINCT FROM txid_current()::text THEN
  RAISE check_violation USING MESSAGE='529 clearance exact PRIVATE task coordinates/transaction required'; END IF;
 PERFORM item_supply_internal.assert_private_native_public_fallback_frame(p-ARRAY['checked_at','valid_until','txid']);
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid;
 SELECT * INTO un FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'union_receipt_id')::uuid;
 stamp:=clock_timestamp();
 IF COALESCE((p->>'checked_at')::timestamptz<=stamp AND stamp<(p->>'valid_until')::timestamptz,false) IS DISTINCT FROM true
  OR (p->>'valid_until')::timestamptz>LEAST(el.valid_until,(un.payload_json->>'valid_until')::timestamptz,(p->>'checked_at')::timestamptz+(CASE WHEN (el.snapshot_json->>'schema_version'='pack_snapshot_mvp_v1' AND el.snapshot_json->>'relation_validation'='not_asserted_for_mvp' AND el.snapshot_json->'relationship_receipt_hashes'='[]'::jsonb AND cardinality(el.relation_receipt_ids)=0) IS TRUE THEN interval '600 seconds' ELSE interval '30 seconds' END)) THEN
  RAISE check_violation USING MESSAGE='529 clearance fresh observation bounds required'; END IF;
 RETURN NEW;
END $new_clearance579$;
 old_clearance_record constant text := $old_clearance_record579$
DECLARE task record;el record;un record;rid uuid:=gen_random_uuid();stamp timestamptz;deadline timestamptz;
BEGIN
 PERFORM item_supply_internal.assert_private_native_public_fallback_frame(p);
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->'task_ref'->>'pack_task_id')::uuid AND record_kind='task';
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid;
 SELECT * INTO un FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'union_receipt_id')::uuid;
 stamp:=clock_timestamp();deadline:=LEAST(el.valid_until,(un.payload_json->>'valid_until')::timestamptz,stamp+interval '30 seconds');
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(rid,task.id,task.user_id,task.epoch,task.scope_id,'private_attachment','fallback.clearance.'||replace((p->>'run_id'),'-','')||'.'||replace(rid::text,'-',''),task.intent_hash,
  p||jsonb_build_object('checked_at',stamp,'valid_until',deadline,'txid',txid_current()));
 PERFORM item_supply_internal.assert_private_native_public_fallback_frame(p);
 RETURN rid;
END $old_clearance_record579$;
 new_clearance_record constant text := $new_clearance_record579$
DECLARE task record;el record;un record;rid uuid:=gen_random_uuid();stamp timestamptz;deadline timestamptz;
BEGIN
 PERFORM item_supply_internal.assert_private_native_public_fallback_frame(p);
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->'task_ref'->>'pack_task_id')::uuid AND record_kind='task';
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid;
 SELECT * INTO un FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'union_receipt_id')::uuid;
 stamp:=clock_timestamp();deadline:=LEAST(el.valid_until,(un.payload_json->>'valid_until')::timestamptz,stamp+(CASE WHEN (el.snapshot_json->>'schema_version'='pack_snapshot_mvp_v1' AND el.snapshot_json->>'relation_validation'='not_asserted_for_mvp' AND el.snapshot_json->'relationship_receipt_hashes'='[]'::jsonb AND cardinality(el.relation_receipt_ids)=0) IS TRUE THEN interval '600 seconds' ELSE interval '30 seconds' END));
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(rid,task.id,task.user_id,task.epoch,task.scope_id,'private_attachment','fallback.clearance.'||replace((p->>'run_id'),'-','')||'.'||replace(rid::text,'-',''),task.intent_hash,
  p||jsonb_build_object('checked_at',stamp,'valid_until',deadline,'txid',txid_current()));
 PERFORM item_supply_internal.assert_private_native_public_fallback_frame(p);
 RETURN rid;
END $new_clearance_record579$;
 old_fallback_creation constant text := $old_fallback_creation579$
DECLARE task record;clearance record;delivery record;stamp timestamptz;
BEGIN
 IF (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='task' AND user_id=creator.user_id AND epoch=creator.epoch
  AND payload_json->'ref'->>'mapping_receipt_id'=creator.mapping_id::text
  AND item_supply_internal.private_native_task_enhancement(id,user_id,epoch::bigint,scope_id))>1 THEN
  RAISE check_violation USING MESSAGE='529 ambiguous same-mapping PRIVATE task cannot select fallback'; END IF;
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='task' AND user_id=creator.user_id AND epoch=creator.epoch
  AND payload_json->'ref'->>'mapping_receipt_id'=creator.mapping_id::text
  AND item_supply_internal.private_native_task_enhancement(id,user_id,epoch::bigint,scope_id);
 IF task.id IS NULL THEN RETURN true; END IF; -- original curated/base-only unchanged
 stamp:=clock_timestamp();
 IF creator.mode<>'create' OR creator.txid<>txid_current() OR required_stage NOT IN('prepare','create')
  OR COALESCE(creator.checked_at<=stamp AND stamp<creator.valid_until
    AND creator.valid_until<=creator.checked_at+interval '30 seconds',false) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT * INTO delivery FROM tutor_item_supply_type_exposure_deliveries WHERE id=creator.delivery_id AND user_id=creator.user_id
  AND epoch=creator.epoch AND version_id=creator.version_id AND delivery_txid=txid_current()
  AND delivery_key='teaching-artifact:'||creator.run_id::text;
 IF delivery.id IS NULL THEN RETURN false; END IF;
 FOR clearance IN SELECT * FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=task.id AND user_id=task.user_id AND epoch=task.epoch
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_public_fallback_clearance_v1'
  AND payload_json->>'run_id'=creator.run_id::text AND payload_json->>'selected_version_id'=creator.version_id::text
  AND payload_json->>'reservation_id'=delivery.reservation_id::text AND payload_json->>'stage'=required_stage
  AND payload_json->>'txid'=txid_current()::text
  AND (payload_json->>'checked_at')::timestamptz<=clock_timestamp() AND (payload_json->>'valid_until')::timestamptz>clock_timestamp() LOOP
  PERFORM item_supply_internal.assert_private_native_public_fallback_frame(clearance.payload_json-ARRAY['checked_at','valid_until','txid']);
  stamp:=clock_timestamp();
  IF (clearance.payload_json->>'checked_at')::timestamptz<=stamp AND stamp<(clearance.payload_json->>'valid_until')::timestamptz
   AND creator.checked_at<=stamp AND stamp<creator.valid_until THEN RETURN true; END IF;
 END LOOP;
 RETURN false;
END $old_fallback_creation579$;
 new_fallback_creation constant text := $new_fallback_creation579$
DECLARE task record;clearance record;delivery record;stamp timestamptz;policy_snapshot jsonb;policy_relations uuid[];
BEGIN
 IF (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='task' AND user_id=creator.user_id AND epoch=creator.epoch
  AND payload_json->'ref'->>'mapping_receipt_id'=creator.mapping_id::text
  AND item_supply_internal.private_native_task_enhancement(id,user_id,epoch::bigint,scope_id))>1 THEN
  RAISE check_violation USING MESSAGE='529 ambiguous same-mapping PRIVATE task cannot select fallback'; END IF;
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='task' AND user_id=creator.user_id AND epoch=creator.epoch
  AND payload_json->'ref'->>'mapping_receipt_id'=creator.mapping_id::text
  AND item_supply_internal.private_native_task_enhancement(id,user_id,epoch::bigint,scope_id);
 IF task.id IS NULL THEN RETURN true; END IF; -- original curated/base-only unchanged
 SELECT eligibility.snapshot_json,eligibility.relation_receipt_ids INTO policy_snapshot,policy_relations
  FROM tutor_item_supply_type_exposure_deliveries deliveries JOIN tutor_item_supply_native_eligibility eligibility
   ON eligibility.id=deliveries.eligibility_id AND eligibility.user_id=deliveries.user_id AND eligibility.epoch=deliveries.epoch
  WHERE deliveries.id=creator.delivery_id AND deliveries.user_id=creator.user_id AND deliveries.epoch=creator.epoch
   AND deliveries.version_id=creator.version_id;
 stamp:=clock_timestamp();
 IF creator.mode<>'create' OR creator.txid<>txid_current() OR required_stage NOT IN('prepare','create')
  OR COALESCE(creator.checked_at<=stamp AND stamp<creator.valid_until
    AND creator.valid_until<=creator.checked_at+(CASE WHEN (policy_snapshot->>'schema_version'='pack_snapshot_mvp_v1' AND policy_snapshot->>'relation_validation'='not_asserted_for_mvp' AND policy_snapshot->'relationship_receipt_hashes'='[]'::jsonb AND cardinality(policy_relations)=0) IS TRUE THEN interval '600 seconds' ELSE interval '30 seconds' END),false) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT * INTO delivery FROM tutor_item_supply_type_exposure_deliveries WHERE id=creator.delivery_id AND user_id=creator.user_id
  AND epoch=creator.epoch AND version_id=creator.version_id AND delivery_txid=txid_current()
  AND delivery_key='teaching-artifact:'||creator.run_id::text;
 IF delivery.id IS NULL THEN RETURN false; END IF;
 FOR clearance IN SELECT * FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=task.id AND user_id=task.user_id AND epoch=task.epoch
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_public_fallback_clearance_v1'
  AND payload_json->>'run_id'=creator.run_id::text AND payload_json->>'selected_version_id'=creator.version_id::text
  AND payload_json->>'reservation_id'=delivery.reservation_id::text AND payload_json->>'stage'=required_stage
  AND payload_json->>'txid'=txid_current()::text
  AND (payload_json->>'checked_at')::timestamptz<=clock_timestamp() AND (payload_json->>'valid_until')::timestamptz>clock_timestamp() LOOP
  PERFORM item_supply_internal.assert_private_native_public_fallback_frame(clearance.payload_json-ARRAY['checked_at','valid_until','txid']);
  stamp:=clock_timestamp();
  IF (clearance.payload_json->>'checked_at')::timestamptz<=stamp AND stamp<(clearance.payload_json->>'valid_until')::timestamptz
   AND creator.checked_at<=stamp AND stamp<creator.valid_until THEN RETURN true; END IF;
 END LOOP;
 RETURN false;
END $new_fallback_creation579$;
 old_public_exposure_check constant text := $old_public_exposure_check579$CHECK (((valid_until > checked_at) AND (valid_until <= (checked_at + '00:02:00'::interval))))$old_public_exposure_check579$;
 new_public_exposure_check constant text := $new_public_exposure_check579$CHECK (((valid_until > checked_at) AND (((valid_until <= (checked_at + '00:02:00'::interval)) OR (((snapshot_json ->> 'collector_version'::text) = 'native-type-exposure-mvp-v1'::text) AND ((snapshot_json ->> 'schema_version'::text) = 'complete_exposure_v2'::text) AND (valid_until <= (checked_at + '00:10:00'::interval)))) IS TRUE)))$new_public_exposure_check579$;
 old_private_exposure_check constant text := $old_private_exposure_check579$CHECK (((valid_until > checked_at) AND (valid_until <= (checked_at + '00:02:00'::interval))))$old_private_exposure_check579$;
 new_private_exposure_check constant text := $new_private_exposure_check579$CHECK (((valid_until > checked_at) AND (((valid_until <= (checked_at + '00:02:00'::interval)) OR (((payload_json ->> 'collector_version'::text) = 'private-native-union-mvp-v1'::text) AND ((payload_json ->> 'schema_version'::text) = 'complete_exposure_v2'::text) AND (valid_until <= (checked_at + '00:10:00'::interval)))) IS TRUE)))$new_private_exposure_check579$;
 old_public_consumer_check constant text := $old_public_consumer_check579$CHECK (((valid_until > checked_at) AND (valid_until <= (checked_at + '00:00:30'::interval))))$old_public_consumer_check579$;
 new_public_consumer_check constant text := $new_public_consumer_check579$CHECK (((valid_until > checked_at) AND (((valid_until <= (checked_at + '00:00:30'::interval)) OR ((((payload_json -> 'current_consumption'::text) ->> 'window_policy'::text) = 'mvp_600_seconds_v1'::text) AND (valid_until <= (checked_at + '00:10:00'::interval)))) IS TRUE)))$new_public_consumer_check579$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001' THEN
  RAISE check_violation USING MESSAGE='579 original isolated writable transaction required'; END IF;
 LOCK TABLE public.tutor_item_supply_type_exposure_snapshots,
  public.tutor_item_supply_private_native_exposure_snapshots,
  public.tutor_item_supply_native_consumer_receipts IN ACCESS EXCLUSIVE MODE;
 FOR target IN SELECT * FROM (VALUES
  ('item_supply_internal.type_exposure_current(uuid,uuid,bigint)','item_supply_internal','type_exposure_current','pg_catalog.jsonb',ARRAY['sid','u','e']::text[],ARRAY['pg_catalog.uuid','pg_catalog.uuid','pg_catalog.int8']::text[],old_public_exposure,new_public_exposure),
  ('item_supply_internal.private_native_exposure_current(uuid,uuid,bigint)','item_supply_internal','private_native_exposure_current','pg_catalog.jsonb',ARRAY['sid','u','e']::text[],ARRAY['pg_catalog.uuid','pg_catalog.uuid','pg_catalog.int8']::text[],old_private_exposure,new_private_exposure),
  ('public.enforce_type_exposure_effect_insert()','public','enforce_type_exposure_effect_insert','pg_catalog.trigger',NULL::text[],NULL::text[],old_effect,new_effect),
  ('item_supply_internal.private_native_eligibility_current(uuid)','item_supply_internal','private_native_eligibility_current','pg_catalog.bool',ARRAY['eid']::text[],ARRAY['pg_catalog.uuid']::text[],old_eligibility,new_eligibility),
  ('item_supply_internal.private_native_base_union_current(uuid)','item_supply_internal','private_native_base_union_current','pg_catalog.bool',ARRAY['rid']::text[],ARRAY['pg_catalog.uuid']::text[],old_union,new_union),
  ('item_supply_internal.private_native_consumer_current(uuid)','item_supply_internal','private_native_consumer_current','pg_catalog.bool',ARRAY['rid']::text[],ARRAY['pg_catalog.uuid']::text[],old_private_consumer,new_private_consumer),
  ('item_supply_internal.native_consumer_receipt_current(uuid)','item_supply_internal','native_consumer_receipt_current','pg_catalog.bool',ARRAY['receipt_id']::text[],ARRAY['pg_catalog.uuid']::text[],old_public_consumer,new_public_consumer),
  ('item_supply_internal.enforce_private_native_public_fallback_clearance()','item_supply_internal','enforce_private_native_public_fallback_clearance','pg_catalog.trigger',NULL::text[],NULL::text[],old_clearance,new_clearance),
  ('item_supply_internal.private_native_public_fallback_record(jsonb)','item_supply_internal','private_native_public_fallback_record','pg_catalog.uuid',ARRAY['p']::text[],ARRAY['pg_catalog.jsonb']::text[],old_clearance_record,new_clearance_record),
  ('item_supply_internal.private_native_public_fallback_for_creation(tutor_item_supply_native_consumer_receipts,text)','item_supply_internal','private_native_public_fallback_for_creation','pg_catalog.bool',ARRAY['creator','required_stage']::text[],ARRAY['public.tutor_item_supply_native_consumer_receipts','pg_catalog.text']::text[],old_fallback_creation,new_fallback_creation)
 ) AS targets(signature,namespace,name,retval,names,types,old_body,new_body) LOOP
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure(target.signature);
  IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM target.namespace::regnamespace
   OR actual.proname IS DISTINCT FROM target.name OR actual.prokind<>'f'
   OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
   OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u'
   OR actual.prorettype IS DISTINCT FROM target.retval::regtype
   OR actual.pronargs<>COALESCE(cardinality(target.names),0)
   OR actual.proargtypes IS DISTINCT FROM COALESCE((SELECT string_agg(pg_catalog.to_regtype(v)::oid::text,' ' ORDER BY n)
     FROM unnest(target.types) WITH ORDINALITY args(v,n)),'')::oidvector
   OR actual.proargnames IS DISTINCT FROM target.names
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
   OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  THEN RAISE check_violation USING MESSAGE='579 original receiver identity/attributes changed',DETAIL=target.signature; END IF;
  IF actual.prosrc IS DISTINCT FROM target.old_body AND actual.prosrc IS DISTINCT FROM target.new_body
  THEN RAISE check_violation USING MESSAGE='579 original receiver body changed',DETAIL=target.signature; END IF;
  definition:=pg_catalog.pg_get_functiondef(actual.oid);
  IF length(definition)-length(replace(definition,actual.prosrc,''))<>length(actual.prosrc)
  THEN RAISE check_violation USING MESSAGE='579 original receiver definition framing changed',DETAIL=target.signature; END IF;
  functions_before:=functions_before||jsonb_build_array(jsonb_build_object('signature',target.signature,
   'attributes',to_jsonb(actual),'definition',definition,'new_body',target.new_body));
 END LOOP;
 FOR target IN SELECT * FROM (VALUES
  ('tutor_item_supply_type_exposure_snapshots','snapshot_json',old_public_exposure_check,new_public_exposure_check),
  ('tutor_item_supply_private_native_exposure_snapshots','payload_json',old_private_exposure_check,new_private_exposure_check),
  ('tutor_item_supply_native_consumer_receipts','payload_json',old_public_consumer_check,new_public_consumer_check)
 ) AS targets(table_name,json_column,old_definition,new_definition) LOOP
  table_id:=pg_catalog.to_regclass('public.'||target.table_name);
  IF table_id IS NULL OR (SELECT count(*) FROM pg_catalog.pg_attribute a WHERE a.attrelid=table_id AND NOT a.attisdropped
    AND a.attname IN('checked_at','valid_until') AND a.atttypid='pg_catalog.timestamptz'::regtype AND a.attnotnull)<>2
   OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid=table_id AND a.attname=target.json_column
    AND NOT a.attisdropped AND a.atttypid='pg_catalog.jsonb'::regtype AND a.attnotnull)
  THEN RAISE check_violation USING MESSAGE='579 original window columns changed',DETAIL=target.table_name; END IF;
  SELECT count(*) INTO matches FROM pg_catalog.pg_constraint c WHERE c.conrelid=table_id AND c.contype='c'
   AND pg_catalog.pg_get_constraintdef(c.oid) IN(target.old_definition,target.new_definition);
  IF matches<>1 THEN RAISE check_violation USING MESSAGE='579 unique exact window CHECK required',DETAIL=target.table_name; END IF;
  SELECT c.* INTO original_check FROM pg_catalog.pg_constraint c WHERE c.conrelid=table_id AND c.contype='c'
   AND pg_catalog.pg_get_constraintdef(c.oid) IN(target.old_definition,target.new_definition);
  check_definition:=pg_catalog.pg_get_constraintdef(original_check.oid);
  SELECT array_agg(a.attnum ORDER BY a.attnum) INTO new_columns FROM pg_catalog.pg_attribute a WHERE a.attrelid=table_id
   AND a.attname IN('checked_at','valid_until',target.json_column) AND NOT a.attisdropped;
  SELECT array_agg(a.attnum ORDER BY a.attnum) INTO expected_columns FROM pg_catalog.pg_attribute a WHERE a.attrelid=table_id
   AND (a.attname IN('checked_at','valid_until') OR (check_definition=target.new_definition AND a.attname=target.json_column)) AND NOT a.attisdropped;
  SELECT array_agg(v ORDER BY v) INTO actual_columns FROM unnest(original_check.conkey) keys(v);
  IF original_check.connamespace IS DISTINCT FROM 'public'::regnamespace OR original_check.conrelid<>table_id
   OR original_check.contypid<>0 OR original_check.conindid<>0 OR original_check.conparentid<>0
   OR original_check.condeferrable OR original_check.condeferred OR NOT original_check.convalidated
   OR NOT original_check.conislocal OR original_check.coninhcount<>0 OR original_check.connoinherit
   OR actual_columns IS DISTINCT FROM expected_columns OR original_check.confrelid<>0
   OR original_check.confkey IS NOT NULL OR original_check.conexclop IS NOT NULL OR original_check.confdelsetcols IS NOT NULL
   OR original_check.conpfeqop IS NOT NULL OR original_check.conppeqop IS NOT NULL OR original_check.conffeqop IS NOT NULL
   OR original_check.confupdtype<>' ' OR original_check.confdeltype<>' ' OR original_check.confmatchtype<>' '
  THEN RAISE check_violation USING MESSAGE='579 original window CHECK attributes changed',DETAIL=target.table_name; END IF;
  checks_before:=checks_before||jsonb_build_array(jsonb_build_object('table_name',target.table_name,
   'attributes',to_jsonb(original_check),'definition',check_definition,'new_definition',target.new_definition,'new_columns',new_columns));
 END LOOP;
 -- ALL THIRTEEN TARGETS PREFLIGHTED; exact-new replay still passed full metadata.
 FOR saved IN SELECT value FROM jsonb_array_elements(functions_before) LOOP
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=(saved->'attributes'->>'oid')::oid;
  IF NOT FOUND OR to_jsonb(actual) IS DISTINCT FROM saved->'attributes'
  THEN RAISE check_violation USING MESSAGE='579 receiver changed after preflight',DETAIL=saved->>'signature'; END IF;
  IF actual.prosrc IS DISTINCT FROM saved->>'new_body' THEN
   EXECUTE replace(saved->>'definition',actual.prosrc,saved->>'new_body');
  END IF;
  SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
  IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
   OR verified.prosrc IS DISTINCT FROM saved->>'new_body'
  THEN RAISE check_violation USING MESSAGE='579 receiver metadata/OID/owner/ACL or body changed',DETAIL=saved->>'signature'; END IF;
 END LOOP;
 FOR saved IN SELECT value FROM jsonb_array_elements(checks_before) LOOP
  SELECT c.* INTO original_check FROM pg_catalog.pg_constraint c WHERE c.oid=(saved->'attributes'->>'oid')::oid;
  IF NOT FOUND OR to_jsonb(original_check) IS DISTINCT FROM saved->'attributes'
  THEN RAISE check_violation USING MESSAGE='579 window CHECK changed after preflight'; END IF;
  IF saved->>'definition' IS DISTINCT FROM saved->>'new_definition' THEN
   EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I',saved->>'table_name',original_check.conname);
   EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s',saved->>'table_name',original_check.conname,saved->>'new_definition');
  END IF;
  SELECT c.* INTO final_check FROM pg_catalog.pg_constraint c WHERE c.conrelid=original_check.conrelid AND c.conname=original_check.conname;
  SELECT array_agg(v ORDER BY v) INTO actual_columns FROM unnest(final_check.conkey) keys(v);
  SELECT array_agg(v::smallint ORDER BY v::smallint) INTO new_columns FROM jsonb_array_elements_text(saved->'new_columns') cols(v);
  IF final_check.oid IS NULL OR (to_jsonb(final_check)-ARRAY['oid','conbin','conkey']) IS DISTINCT FROM (to_jsonb(original_check)-ARRAY['oid','conbin','conkey'])
   OR actual_columns IS DISTINCT FROM new_columns
   OR pg_catalog.pg_get_constraintdef(final_check.oid) IS DISTINCT FROM saved->>'new_definition'
   OR ((saved->>'definition'=saved->>'new_definition') IS DISTINCT FROM (final_check.oid=original_check.oid))
  THEN RAISE check_violation USING MESSAGE='579 window CHECK final definition/attributes changed'; END IF;
 END LOOP;
END;
$window579$;
