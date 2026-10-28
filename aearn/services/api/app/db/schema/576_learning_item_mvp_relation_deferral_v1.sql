-- Explicit MVP relation deferral: four existing bodies and two existing CHECKs only.
-- Frozen <=575; caller owns isolated READ COMMITTED transaction and installer lock.
-- All six targets preflight before any mutation. Function OIDs/metadata survive;
-- only the two named CHECK OIDs may change, once, when replacing their predicates.
-- No historical rows, authority, outer envelopes, TTLs, triggers or grants change.
DO $mvp576$
DECLARE
 actual record; verified record; target record; column_row record;
 original_check record; final_check record; saved jsonb; definition text;
 table_id oid; snapshot_column smallint; relations_column smallint; matches bigint;
 expected_columns smallint[]; final_columns smallint[]; check_definition text;
 functions_before jsonb := '[]'::jsonb; checks_before jsonb := '[]'::jsonb;
 old_effect constant text := $old_effect576$
DECLARE elig record; reserved record; mapping record; original record; scoped record;
  exposure jsonb; selected jsonb; pair jsonb; b jsonb; c jsonb; spec jsonb;
  native_clauses jsonb; requested_clauses jsonb; mapped_clauses jsonb; field text; t timestamptz; sid uuid;
BEGIN
  PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,NEW.epoch);
  PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans a
    ON a.track_id=s.track_id AND a.user_id=s.user_id AND a.revision_id=s.revision_id
    WHERE s.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch FOR SHARE OF s,a;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='type exposure active original scope required'; END IF;
  exposure:=item_supply_internal.type_exposure_current(NEW.exposure_snapshot_id,NEW.user_id,NEW.epoch);
  SELECT * INTO elig FROM tutor_item_supply_native_eligibility WHERE id=NEW.eligibility_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
  t:=clock_timestamp();
  IF elig.id IS NULL OR elig.exposure_snapshot_id IS DISTINCT FROM NEW.exposure_snapshot_id OR elig.txid<>txid_current()
    OR NOT(elig.checked_at<=t AND t<elig.valid_until)
    OR elig.snapshot_json->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2'
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
  PERFORM item_supply_internal.type_relation_required(pair->0,pair->1,
    selected->0->'type_evidence'->>'profile',elig.request_hash,NEW.user_id,NEW.epoch,
    elig.mapping_receipt_id,elig.relation_receipt_ids);
  FOR b IN SELECT value FROM jsonb_array_elements(pair) LOOP
    FOR c IN SELECT value->'content' FROM jsonb_array_elements(exposure->'records')
      UNION ALL SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(selected)
        WHERE value->'member'->>'slot'<>'assessment' LOOP
      IF item_supply_internal.type_content_clone(b,c) THEN
        RAISE check_violation USING MESSAGE='type exposure assessment exposed or cloned';
      END IF;
      PERFORM item_supply_internal.type_relation_required(b,c,
        selected->0->'type_evidence'->>'profile',elig.request_hash,NEW.user_id,NEW.epoch,
        elig.mapping_receipt_id,elig.relation_receipt_ids);
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
      OR reserved.request_json->'relation_receipt_ids' IS DISTINCT FROM to_jsonb(elig.relation_receipt_ids)
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
END $old_effect576$;
 new_effect constant text := $new_effect576$
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
      OR reserved.request_json->'relation_receipt_ids' IS DISTINCT FROM to_jsonb(elig.relation_receipt_ids)
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
END $new_effect576$;
 old_eligibility constant text := $old_eligibility576$
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
END $old_eligibility576$;
 new_eligibility constant text := $new_eligibility576$
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
 IF (SELECT count(DISTINCT q.slot_id) FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id IN
   (SELECT (c->>'proof_id')::uuid FROM jsonb_array_elements(s->'selected') c))<>5 THEN RETURN false; END IF;
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
END $new_eligibility576$;
 old_union constant text := $old_union576$

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
   -- exposure requires a genuine PRIVATE four-role batch for THIS actual pair.
   IF other->>'item_handle' LIKE 'lip:v2:%' AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,r.user_id,r.epoch::bigint,r.pack_task_id) IS DISTINCT FROM true THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND (p->>'checked_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz
  AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '120 seconds';
END 
$old_union576$;
 new_union constant text := $new_union576$

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
$new_union576$;
 old_repair constant text := $old_repair576$
BEGIN
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal r,jsonb_array_elements(NEW.payload_json->'snapshot'->'selected') s
  WHERE r.user_id=NEW.user_id AND r.epoch=NEW.epoch AND r.pack_task_id=NEW.pack_task_id AND r.record_kind='private_status'
   AND r.payload_json->>'schema_version'='private_native_relation_repair_required_v1' AND r.payload_json->>'parent_version_id'=s->>'version_id') THEN
  RAISE check_violation USING MESSAGE='527 failed relation head needs real same-slot substantive child'; END IF;
 RETURN NEW;
END $old_repair576$;
 new_repair constant text := $new_repair576$
BEGIN
 -- This exact snapshot defers relations, not the AFTER eligibility current guard.
 IF (NEW.payload_json->'snapshot'->>'schema_version'='pack_snapshot_mvp_v1'
  AND NEW.payload_json->'snapshot'->>'relation_validation'='not_asserted_for_mvp'
  AND NEW.payload_json->'snapshot'->'relationship_receipt_hashes'='[]'::jsonb
  AND NEW.payload_json->'relations'='[]'::jsonb) IS TRUE THEN RETURN NEW; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal r,jsonb_array_elements(NEW.payload_json->'snapshot'->'selected') s
  WHERE r.user_id=NEW.user_id AND r.epoch=NEW.epoch AND r.pack_task_id=NEW.pack_task_id AND r.record_kind='private_status'
   AND r.payload_json->>'schema_version'='private_native_relation_repair_required_v1' AND r.payload_json->>'parent_version_id'=s->>'version_id') THEN
  RAISE check_violation USING MESSAGE='527 failed relation head needs real same-slot substantive child'; END IF;
 RETURN NEW;
END $new_repair576$;
 old_snapshot_check constant text := $old_snapshot_check576$CHECK (((jsonb_typeof(snapshot_json) = 'object'::text) AND (octet_length((snapshot_json)::text) <= 2097152) AND ((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_v2'::text)))$old_snapshot_check576$;
 new_snapshot_check constant text := $new_snapshot_check576$CHECK (((jsonb_typeof(snapshot_json) = 'object'::text) AND (octet_length((snapshot_json)::text) <= 2097152) AND ((((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_v2'::text) OR (((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_mvp_v1'::text) AND ((snapshot_json ->> 'relation_validation'::text) = 'not_asserted_for_mvp'::text) AND ((snapshot_json -> 'relationship_receipt_hashes'::text) = '[]'::jsonb))) IS TRUE)))$new_snapshot_check576$;
 old_relations_check constant text := $old_relations_check576$CHECK (((cardinality(relation_receipt_ids) >= 1) AND (cardinality(relation_receipt_ids) <= 16)))$old_relations_check576$;
 new_relations_check constant text := $new_relations_check576$CHECK ((((((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_v2'::text) AND (cardinality(relation_receipt_ids) >= 1) AND (cardinality(relation_receipt_ids) <= 16)) OR (((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_mvp_v1'::text) AND ((snapshot_json ->> 'relation_validation'::text) = 'not_asserted_for_mvp'::text) AND ((snapshot_json -> 'relationship_receipt_hashes'::text) = '[]'::jsonb) AND (cardinality(relation_receipt_ids) = 0))) IS TRUE))$new_relations_check576$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001' THEN
  RAISE check_violation USING MESSAGE='576 original isolated writable transaction required'; END IF;
 LOCK TABLE public.tutor_item_supply_native_eligibility IN ACCESS EXCLUSIVE MODE;

 -- Fixed four-function ABI/body preflight. No mutation or early replay return here.
 FOR target IN SELECT * FROM (VALUES
  ('public.enforce_type_exposure_effect_insert()','public','enforce_type_exposure_effect_insert','pg_catalog.trigger',NULL::text[],old_effect,new_effect),
  ('item_supply_internal.private_native_eligibility_current(uuid)','item_supply_internal','private_native_eligibility_current','pg_catalog.bool',ARRAY['eid']::text[],old_eligibility,new_eligibility),
  ('item_supply_internal.private_native_base_union_current(uuid)','item_supply_internal','private_native_base_union_current','pg_catalog.bool',ARRAY['rid']::text[],old_union,new_union),
  ('item_supply_internal.enforce_private_native_repair_head_selection()','item_supply_internal','enforce_private_native_repair_head_selection','pg_catalog.trigger',NULL::text[],old_repair,new_repair)
 ) AS targets(signature,namespace,name,retval,names,old_body,new_body) LOOP
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure(target.signature);
  IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM target.namespace::regnamespace
   OR actual.proname IS DISTINCT FROM target.name OR actual.prokind<>'f'
   OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
   OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u'
   OR actual.prorettype IS DISTINCT FROM target.retval::regtype
   OR actual.pronargs<>COALESCE(cardinality(target.names),0)
   OR actual.proargtypes IS DISTINCT FROM (CASE WHEN target.names IS NULL THEN ''::oidvector
    ELSE ('pg_catalog.uuid'::regtype::oid::text)::oidvector END)
   OR actual.proargnames IS DISTINCT FROM target.names
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
   OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  THEN RAISE check_violation USING MESSAGE='576 original function identity/attributes changed',DETAIL=target.signature; END IF;
  IF actual.prosrc IS DISTINCT FROM target.old_body AND actual.prosrc IS DISTINCT FROM target.new_body
  THEN RAISE check_violation USING MESSAGE='576 original function body changed',DETAIL=target.signature; END IF;
  definition:=pg_catalog.pg_get_functiondef(actual.oid);
  IF length(definition)-length(replace(definition,actual.prosrc,''))<>length(actual.prosrc)
  THEN RAISE check_violation USING MESSAGE='576 original function definition framing changed',DETAIL=target.signature; END IF;
  functions_before:=functions_before||jsonb_build_array(jsonb_build_object(
   'signature',target.signature,'attributes',to_jsonb(actual),'definition',definition,'new_body',target.new_body));
 END LOOP;

 -- Two physical columns and two unique, exact old/new CHECKs, still pre-mutation.
 table_id:=pg_catalog.to_regclass('public.tutor_item_supply_native_eligibility');
 SELECT a.* INTO column_row FROM pg_catalog.pg_attribute a WHERE a.attrelid=table_id AND a.attname='snapshot_json' AND NOT a.attisdropped;
 IF NOT FOUND OR column_row.atttypid IS DISTINCT FROM 'pg_catalog.jsonb'::regtype OR NOT column_row.attnotnull
 THEN RAISE check_violation USING MESSAGE='576 original eligibility snapshot column changed'; END IF;
 snapshot_column:=column_row.attnum;
 SELECT a.* INTO column_row FROM pg_catalog.pg_attribute a WHERE a.attrelid=table_id AND a.attname='relation_receipt_ids' AND NOT a.attisdropped;
 IF NOT FOUND OR column_row.atttypid IS DISTINCT FROM 'pg_catalog.uuid[]'::regtype OR NOT column_row.attnotnull
 THEN RAISE check_violation USING MESSAGE='576 original eligibility relations column changed'; END IF;
 relations_column:=column_row.attnum;
 FOR target IN SELECT * FROM (VALUES
  ('tutor_item_supply_native_eligibility_snapshot_json_check',old_snapshot_check,new_snapshot_check,ARRAY[snapshot_column],ARRAY[snapshot_column]),
  ('tutor_item_supply_native_eligibility_relation_receipt_ids_check',old_relations_check,new_relations_check,ARRAY[relations_column],ARRAY[snapshot_column,relations_column])
 ) AS targets(name,old_definition,new_definition,old_columns,new_columns) LOOP
  SELECT count(*) INTO matches FROM pg_catalog.pg_constraint c WHERE c.conrelid=table_id AND c.contype='c'
   AND pg_catalog.pg_get_constraintdef(c.oid) IN(target.old_definition,target.new_definition);
  SELECT c.* INTO original_check FROM pg_catalog.pg_constraint c WHERE c.conrelid=table_id AND c.conname=target.name;
  IF NOT FOUND OR matches<>1
  THEN RAISE check_violation USING MESSAGE='576 unique original eligibility CHECK required',DETAIL=target.name; END IF;
  check_definition:=pg_catalog.pg_get_constraintdef(original_check.oid);
  IF check_definition IS DISTINCT FROM target.old_definition AND check_definition IS DISTINCT FROM target.new_definition
  THEN RAISE check_violation USING MESSAGE='576 original eligibility CHECK definition changed',DETAIL=target.name; END IF;
  expected_columns:=(CASE WHEN check_definition=target.old_definition THEN target.old_columns ELSE target.new_columns END);
  IF original_check.contype<>'c' OR original_check.connamespace IS DISTINCT FROM 'public'::regnamespace
   OR original_check.conrelid<>table_id OR original_check.contypid<>0 OR original_check.conindid<>0 OR original_check.conparentid<>0
   OR original_check.condeferrable OR original_check.condeferred OR NOT original_check.convalidated
   OR NOT original_check.conislocal OR original_check.coninhcount<>0 OR original_check.connoinherit
   OR original_check.conkey IS DISTINCT FROM expected_columns OR original_check.confrelid<>0
   OR original_check.confkey IS NOT NULL OR original_check.conexclop IS NOT NULL OR original_check.confdelsetcols IS NOT NULL
   OR original_check.conpfeqop IS NOT NULL OR original_check.conppeqop IS NOT NULL OR original_check.conffeqop IS NOT NULL
   OR original_check.confupdtype<>' ' OR original_check.confdeltype<>' ' OR original_check.confmatchtype<>' '
  THEN RAISE check_violation USING MESSAGE='576 original eligibility CHECK attributes changed',DETAIL=target.name; END IF;
  checks_before:=checks_before||jsonb_build_array(jsonb_build_object('name',target.name,
   'attributes',to_jsonb(original_check),'definition',check_definition,'new_definition',target.new_definition,'new_columns',target.new_columns));
 END LOOP;

 -- ALL SIX TARGETS PREFLIGHTED. The caller's transaction makes this atomic.
 FOR saved IN SELECT value FROM jsonb_array_elements(functions_before) LOOP
  SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=(saved->'attributes'->>'oid')::oid;
  IF NOT FOUND OR to_jsonb(actual) IS DISTINCT FROM saved->'attributes'
  THEN RAISE check_violation USING MESSAGE='576 function changed after preflight',DETAIL=saved->>'signature'; END IF;
  IF actual.prosrc IS DISTINCT FROM saved->>'new_body' THEN
   EXECUTE replace(saved->>'definition',actual.prosrc,saved->>'new_body');
  END IF;
  SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
  IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
   OR verified.prosrc IS DISTINCT FROM saved->>'new_body'
  THEN RAISE check_violation USING MESSAGE='576 function metadata/OID/owner/ACL or body changed',DETAIL=saved->>'signature'; END IF;
 END LOOP;
 FOR saved IN SELECT value FROM jsonb_array_elements(checks_before) LOOP
  SELECT c.* INTO original_check FROM pg_catalog.pg_constraint c WHERE c.oid=(saved->'attributes'->>'oid')::oid;
  IF NOT FOUND OR to_jsonb(original_check) IS DISTINCT FROM saved->'attributes'
  THEN RAISE check_violation USING MESSAGE='576 eligibility CHECK changed after preflight',DETAIL=saved->>'name'; END IF;
  IF saved->>'definition' IS DISTINCT FROM saved->>'new_definition' THEN
   EXECUTE format('ALTER TABLE public.tutor_item_supply_native_eligibility DROP CONSTRAINT %I',saved->>'name');
   EXECUTE format('ALTER TABLE public.tutor_item_supply_native_eligibility ADD CONSTRAINT %I %s',saved->>'name',saved->>'new_definition');
  END IF;
  SELECT c.* INTO final_check FROM pg_catalog.pg_constraint c WHERE c.conrelid=table_id AND c.conname=saved->>'name';
  SELECT array_agg(v::smallint ORDER BY n) INTO final_columns FROM jsonb_array_elements_text(saved->'new_columns') WITH ORDINALITY AS cols(v,n);
  IF final_check.oid IS NULL OR (to_jsonb(final_check)-ARRAY['oid','conbin','conkey']) IS DISTINCT FROM (to_jsonb(original_check)-ARRAY['oid','conbin','conkey'])
   OR final_check.conkey IS DISTINCT FROM final_columns
   OR pg_catalog.pg_get_constraintdef(final_check.oid) IS DISTINCT FROM saved->>'new_definition'
   OR ((saved->>'definition'=saved->>'new_definition') IS DISTINCT FROM (final_check.oid=original_check.oid))
  THEN RAISE check_violation USING MESSAGE='576 eligibility CHECK final definition/attributes changed',DETAIL=saved->>'name'; END IF;
 END LOOP;
END;
$mvp576$;
