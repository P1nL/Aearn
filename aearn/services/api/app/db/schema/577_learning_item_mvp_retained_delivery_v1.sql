-- MVP delivery retains the original PUBLIC reservation, not its relation authority.
-- Frozen <=576. One existing-function prosrc predicate changes; no new objects or row changes.
-- Fresh reservation binding and strict-v2 delivery keep exact relation-ID equality.
-- The original isolated caller owns the transaction and installer serialization.
DO $patch577$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old577$
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
END $old577$;
 new_body constant text := $new577$
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
END $new577$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001' THEN
  RAISE check_violation USING MESSAGE='577 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p
  WHERE p.oid=pg_catalog.to_regprocedure('public.enforce_type_exposure_effect_insert()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'public'::regnamespace
  OR actual.proname IS DISTINCT FROM 'enforce_type_exposure_effect_insert' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype
  OR actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector
  OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
 THEN RAISE check_violation USING MESSAGE='577 original exposure receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='577 original exposure receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='577 original exposure receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='577 exposure receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch577$;
