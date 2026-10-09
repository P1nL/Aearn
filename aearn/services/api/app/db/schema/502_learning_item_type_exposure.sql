-- Explicit V2 sidecar. Original495 bytes/family rules and event capture retained.
-- No Gate/Artifact/Attempt writes. Main registers private lifecycle and manifest.
CREATE TABLE IF NOT EXISTS tutor_item_supply_type_exposure_snapshots (
  id uuid PRIMARY KEY, user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1),
  original_watermark_id uuid NOT NULL, snapshot_json jsonb NOT NULL
    CHECK(jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=8388608),
  snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(snapshot_json)) STORED,
  checked_at timestamptz NOT NULL, valid_until timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK(valid_until>checked_at AND valid_until<=checked_at+interval '30 seconds'),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(original_watermark_id,user_id,epoch)
    REFERENCES tutor_item_supply_native_exposure_watermarks(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_type_exposure_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  operation_key text NOT NULL CHECK(operation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  request_json jsonb NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=1048576),
  eligibility_id uuid NOT NULL, exposure_snapshot_id uuid NOT NULL,
  bindings_json jsonb NOT NULL CHECK(jsonb_typeof(bindings_json)='array' AND jsonb_array_length(bindings_json)=2
    AND octet_length(bindings_json::text)<=16384),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,operation_key), UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(eligibility_id,user_id,epoch) REFERENCES tutor_item_supply_native_eligibility(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_type_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_type_exposure_deliveries (
  id uuid PRIMARY KEY, user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL, version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  delivery_key text NOT NULL CHECK(delivery_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  binding_json jsonb NOT NULL CHECK(jsonb_typeof(binding_json)='object' AND octet_length(binding_json::text)<=8192),
  eligibility_id uuid NOT NULL, exposure_snapshot_id uuid NOT NULL,
  delivery_kind text NOT NULL DEFAULT 'practice' CHECK(delivery_kind='practice'),
  delivery_txid bigint NOT NULL DEFAULT txid_current(), created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,delivery_key),
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id)
    REFERENCES tutor_item_supply_type_exposure_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(eligibility_id,user_id,epoch) REFERENCES tutor_item_supply_native_eligibility(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_type_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION item_supply_internal.type_exposure_current(sid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.type_exposure_current(uuid,uuid,bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.type_content_clone(a jsonb,b jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
  SELECT EXISTS(SELECT 1 FROM unnest(ARRAY['item_handle','content_hash','actual_public_task_hash',
    'decision_signature','answer_leakage_signature']) k WHERE a->>k=b->>k)
$$;
REVOKE ALL ON FUNCTION item_supply_internal.type_content_clone(jsonb,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_type_exposure_snapshot_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE t timestamptz;
BEGIN
  PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,NEW.epoch);
  t:=clock_timestamp();
  IF NOT(NEW.checked_at<=t AND t<NEW.valid_until) THEN
    RAISE check_violation USING MESSAGE='type exposure snapshot expired';
  END IF;
  RETURN NEW;
END $$;
-- AFTER insertion lets the same exact current helper reconstruct every record.
CREATE OR REPLACE FUNCTION validate_type_exposure_snapshot_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  PERFORM item_supply_internal.type_exposure_current(NEW.id,NEW.user_id,NEW.epoch);
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_type_exposure_snapshot_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION validate_type_exposure_snapshot_insert() FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_type_exposure_effect_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;
REVOKE ALL ON FUNCTION enforce_type_exposure_effect_insert() FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.purge_type_exposure_private(target_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF item_supply_internal.permitted(target_user) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='type exposure purge requires original reset permit';
  END IF;
  DELETE FROM tutor_item_supply_type_exposure_deliveries WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_type_exposure_reservations WHERE user_id=target_user;
  -- 501 eligibility names502 by UUID only, not a reverse/forward FK.
  -- Its owning a02 trigger purges501 after these FK children are gone.
  DELETE FROM tutor_item_supply_type_exposure_snapshots WHERE user_id=target_user;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_type_exposure_private(uuid) FROM PUBLIC;
CREATE OR REPLACE FUNCTION purge_type_exposure_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
    OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='type exposure reset requires original epoch permit';
  END IF;
  PERFORM item_supply_internal.purge_type_exposure_private(NEW.user_id);
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION purge_type_exposure_on_epoch_advance() FROM PUBLIC;
-- Alphabetical AFTER trigger order: this runs before501 and original495 purge.
DROP TRIGGER IF EXISTS a01_native_type_exposure_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a01_native_type_exposure_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
  FOR EACH ROW WHEN (OLD.epoch<NEW.epoch) EXECUTE FUNCTION purge_type_exposure_on_epoch_advance();
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['tutor_item_supply_type_exposure_snapshots','tutor_item_supply_type_exposure_reservations','tutor_item_supply_type_exposure_deliveries'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS type_exposure_immutable ON %I',t);
    EXECUTE format('CREATE TRIGGER type_exposure_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''private'')',t);
    EXECUTE format('DROP TRIGGER IF EXISTS type_exposure_insert ON %I',t);
    IF t='tutor_item_supply_type_exposure_snapshots' THEN
      EXECUTE format('CREATE TRIGGER type_exposure_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_type_exposure_snapshot_insert()',t);
    ELSE
      EXECUTE format('CREATE TRIGGER type_exposure_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_type_exposure_effect_insert()',t);
    END IF;
  END LOOP;
END $$;
DROP TRIGGER IF EXISTS type_exposure_validate ON tutor_item_supply_type_exposure_snapshots;
CREATE TRIGGER type_exposure_validate AFTER INSERT ON tutor_item_supply_type_exposure_snapshots
  FOR EACH ROW EXECUTE FUNCTION validate_type_exposure_snapshot_insert();

-- Single additive predicate in ORIGINAL capture. Never duplicate/synthesize inbox.
-- Fail closed on unexpected installed495 body. Supports same-fragment replay and
-- ordered bootstrap (495 reinstalls original body,502 re-adds explicit sidecar).
DO $bridge$
DECLARE body text; definition text; patched text;
  old_branch text := $old$    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_deliveries d
      JOIN tutor_item_supply_private_scopes s ON s.id=d.scope_id AND s.user_id=d.user_id AND s.epoch=d.epoch
      JOIN LATERAL(SELECT state FROM tutor_learning_item_publication_events WHERE version_id=d.version_id ORDER BY state_version DESC LIMIT 1) pe ON pe.state='published'
      WHERE d.user_id=NEW.user_id AND d.epoch=e AND d.version_id=v AND d.delivery_txid=txid_current() AND d.delivery_kind='practice'
        AND s.track_id::text=coordinates->>'track_id' AND s.revision_id::text=coordinates->>'revision_id'
        AND s.knowledge_key=coordinates->>'knowledge_key') THEN
$old$;
  new_branch text := $new$    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_deliveries d
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
$new$;
BEGIN
  SELECT prosrc INTO body FROM pg_proc WHERE oid='capture_native_exposure_origin()'::regprocedure;
  IF encode(sha256(convert_to(body,'UTF8')),'hex')='4a55f68d0ead5fbcec0b21f33e844568777727216338243885766c5a22528d0a' THEN
    patched:=replace(body,old_branch,new_branch);
    IF encode(sha256(convert_to(patched,'UTF8')),'hex') IS DISTINCT FROM 'b5a94a16fbd2c471e012056580127a273c5aa297b59ec07066105a4421add26f' THEN
      RAISE check_violation USING MESSAGE='502 exact delivery predicate replacement required';
    END IF;
    SELECT pg_get_functiondef('capture_native_exposure_origin()'::regprocedure) INTO definition;
    EXECUTE replace(definition,old_branch,new_branch);
  ELSIF encode(sha256(convert_to(body,'UTF8')),'hex') IS DISTINCT FROM 'b5a94a16fbd2c471e012056580127a273c5aa297b59ec07066105a4421add26f' THEN
    RAISE check_violation USING MESSAGE='502 requires exact original or reviewed additive495 capture body';
  END IF;
  SELECT prosrc INTO body FROM pg_proc WHERE oid='capture_native_exposure_origin()'::regprocedure;
  IF encode(sha256(convert_to(body,'UTF8')),'hex') IS DISTINCT FROM 'b5a94a16fbd2c471e012056580127a273c5aa297b59ec07066105a4421add26f' THEN
    RAISE check_violation USING MESSAGE='502 installed capture body mismatch';
  END IF;
END $bridge$;

-- Validate actual immutable501 review coverage, not caller pack-complete JSON.
-- Stable exact content judgments may be reused across fresh exposure watermarks.
--501 alone checks the original live lease at prepare/run/commit and freezes the
--new evidence deadline (original current source/retention bounds, at most7days).
--Consumption checks that immutable deadline, NOT a still-active producer lease;
--current source/runtime/mapping/epoch authority remains with the concrete owner.
--Never renew a persisted report or substitute the fresh30-second exposure TTL.
CREATE OR REPLACE FUNCTION item_supply_internal.type_relation_required(
  a jsonb,b jsonb,profile text,req_hash text,u uuid,e bigint,mapping_id uuid,ids uuid[]) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE binding text; contents jsonb; batch record; n integer;
BEGIN
  SELECT jsonb_agg(x ORDER BY item_supply_internal.snapshot_hash(x)) INTO contents
    FROM jsonb_array_elements(jsonb_build_array(a,b)) x;
  binding:=item_supply_internal.snapshot_hash(jsonb_build_object('policy_version','item_supply_type_evidence_v2',
    'profile',profile,'request_hash',req_hash,'contents',contents));
  SELECT count(*) INTO n FROM tutor_item_supply_native_relation_batches rb,
    LATERAL jsonb_array_elements(rb.payload_json->'pairs') p
    WHERE rb.id=ANY(ids) AND rb.user_id=u AND rb.epoch=e AND rb.mapping_receipt_id=mapping_id
      AND rb.request_hash=req_hash AND p->>'binding_hash'=binding;
  IF n<>1 THEN RAISE check_violation USING MESSAGE='type exposure exact original relation coverage required'; END IF;
  SELECT rb.* INTO batch FROM tutor_item_supply_native_relation_batches rb
    WHERE rb.id=ANY(ids) AND rb.user_id=u AND rb.epoch=e AND rb.mapping_receipt_id=mapping_id
      AND rb.request_hash=req_hash AND EXISTS(SELECT 1 FROM jsonb_array_elements(rb.payload_json->'pairs') p
        WHERE p->>'binding_hash'=binding
          AND ((p->>'left_version_id'=a->>'version_id' AND p->>'right_version_id'=b->>'version_id')
            OR (p->>'left_version_id'=b->>'version_id' AND p->>'right_version_id'=a->>'version_id')))
      AND rb.payload_json->'contents' @> jsonb_build_array(a,b) FOR SHARE;
  IF batch.id IS NULL OR clock_timestamp()>=batch.valid_until OR jsonb_array_length(batch.payload_json->'reports')<>4
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(batch.payload_json->'reports') r
      WHERE (r->>'checked_at')::timestamptz>clock_timestamp() OR clock_timestamp()>=(r->>'valid_until')::timestamptz
        OR (SELECT count(*) FROM jsonb_array_elements(r->'judgments') j
          WHERE j->>'binding_hash'=binding AND j->>'conclusion'='nonredundant')<>1) THEN
    RAISE check_violation USING MESSAGE='type exposure missing stale conflict or uncertain relation';
  END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.type_relation_required(jsonb,jsonb,text,text,uuid,bigint,uuid,uuid[]) FROM PUBLIC;
