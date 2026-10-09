-- Install scope is chosen by main (initially B1d). These triggers are NOT
-- intrinsically database-name-gated and do not change any public feature flag.
-- Closed owner inbox + native exposures only; no Attempt/Gate/scoring writes.
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_exposure_births (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch=1), collector_version text NOT NULL CHECK(collector_version='native-exposure-v1'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(user_id,epoch), UNIQUE(id,user_id,epoch)
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_exposure_inbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, epoch bigint NOT NULL CHECK(epoch>=1),
  origin_table text NOT NULL CHECK(origin_table IN ('tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts',
    'tutor_exercise_attempts','tutor_exercise_hint_receipts','tutor_lesson_gate_bindings')),
  origin_id uuid NOT NULL, version_id uuid REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK(kind IN ('shown','hint','direct_answer','attempted','metadata','untracked')),
  origin_scope_json jsonb NOT NULL CHECK(jsonb_typeof(origin_scope_json)='object' AND octet_length(origin_scope_json::text)<=2048),
  origin_hash text NOT NULL CHECK(origin_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,origin_table,origin_id), UNIQUE(id,user_id,epoch)
);
CREATE INDEX IF NOT EXISTS native_exposure_inbox_owner ON tutor_item_supply_native_exposure_inbox(user_id,epoch,sequence);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_exposure_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), inbox_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1), version_id uuid NOT NULL,
  proof_id uuid NOT NULL REFERENCES tutor_learning_item_native_publication_proofs(id) ON DELETE RESTRICT,
  binding_json jsonb NOT NULL CHECK(jsonb_typeof(binding_json)='object' AND octet_length(binding_json::text)<=8192),
  binding_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(binding_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(inbox_id,user_id,epoch) REFERENCES tutor_item_supply_native_exposure_inbox(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_exposure_watermarks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1),
  birth_id uuid NOT NULL, watermark bigint NOT NULL CHECK(watermark>=0),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4096),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(user_id,epoch,payload_hash), UNIQUE(id,user_id,epoch),
  FOREIGN KEY(birth_id,user_id,epoch) REFERENCES tutor_item_supply_native_exposure_births(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_exposure_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  operation_key text NOT NULL CHECK(operation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'), watermark_id uuid NOT NULL,
  bindings_json jsonb NOT NULL CHECK(jsonb_typeof(bindings_json)='array' AND jsonb_array_length(bindings_json)=2
    AND octet_length(bindings_json::text)<=16384),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(user_id,epoch,operation_key), UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(watermark_id,user_id,epoch) REFERENCES tutor_item_supply_native_exposure_watermarks(id,user_id,epoch) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_exposure_deliveries (
  id uuid PRIMARY KEY, user_id uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, reservation_id uuid NOT NULL,
  version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  delivery_key text NOT NULL CHECK(delivery_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  binding_json jsonb NOT NULL CHECK(jsonb_typeof(binding_json)='object' AND octet_length(binding_json::text)<=8192),
  delivery_kind text NOT NULL DEFAULT 'practice' CHECK(delivery_kind='practice'),
  delivery_txid bigint NOT NULL DEFAULT txid_current(), created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,delivery_key),
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_native_exposure_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION item_supply_internal.native_exposure_lock(u uuid, e bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  PERFORM 1 FROM users WHERE id=u AND deleted_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native exposure owner unavailable'; END IF;
  PERFORM 1 FROM tutor_item_supply_user_epochs WHERE user_id=u AND epoch=e AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native exposure epoch stale'; END IF;
  PERFORM pg_advisory_xact_lock(hashtext('native-exposure'),hashtext(u::text));
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.native_exposure_lock(uuid,bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION capture_native_exposure_birth() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(NEW.id) ON CONFLICT DO NOTHING;
  INSERT INTO tutor_item_supply_native_exposure_births(user_id,epoch,collector_version)
    VALUES(NEW.id,1,'native-exposure-v1');
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION capture_native_exposure_birth() FROM PUBLIC;
DROP TRIGGER IF EXISTS native_exposure_birth_capture ON users;
CREATE TRIGGER native_exposure_birth_capture AFTER INSERT ON users FOR EACH ROW EXECUTE FUNCTION capture_native_exposure_birth();

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
        AND s.knowledge_key=coordinates->>'knowledge_key') THEN
      RAISE check_violation USING MESSAGE='native assessment must be reserved before practice delivery';
    END IF;
  END IF;
  INSERT INTO tutor_item_supply_native_exposure_inbox(user_id,epoch,origin_table,origin_id,version_id,kind,origin_scope_json,origin_hash)
    VALUES(NEW.user_id,e,TG_TABLE_NAME,NEW.id,v,k,coordinates,item_supply_internal.snapshot_hash(raw)) ON CONFLICT DO NOTHING;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION capture_native_exposure_origin() FROM PUBLIC;
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts','tutor_exercise_attempts',
    'tutor_exercise_hint_receipts','tutor_lesson_gate_bindings'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS native_exposure_origin_capture ON %I',t);
    EXECUTE format('CREATE TRIGGER native_exposure_origin_capture AFTER INSERT ON %I FOR EACH ROW EXECUTE FUNCTION capture_native_exposure_origin()',t);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.native_exposure_hooks_current() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT count(*)=6 FROM pg_trigger WHERE NOT tgisinternal AND tgenabled IN ('O','A') AND (
    (tgrelid='users'::regclass AND tgname='native_exposure_birth_capture' AND tgfoid='capture_native_exposure_birth()'::regprocedure)
    OR (tgrelid=ANY(ARRAY['tutor_learning_artifact_events'::regclass,'tutor_knowledge_check_assistance_receipts'::regclass,
      'tutor_exercise_attempts'::regclass,'tutor_exercise_hint_receipts'::regclass,'tutor_lesson_gate_bindings'::regclass])
      AND tgname='native_exposure_origin_capture' AND tgfoid='capture_native_exposure_origin()'::regprocedure))
$$;
REVOKE ALL ON FUNCTION item_supply_internal.native_exposure_hooks_current() FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_native_exposure_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record; p jsonb; b jsonb; prior jsonb; max_sequence bigint; n bigint; records jsonb;
BEGIN
  PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,NEW.epoch);
  IF TG_TABLE_NAME IN ('tutor_item_supply_native_exposure_births','tutor_item_supply_native_exposure_inbox') THEN
    IF pg_trigger_depth()<2 THEN RAISE check_violation USING MESSAGE='exposure origin is concrete owner trigger only'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_native_exposure_events' THEN
    SELECT * INTO r FROM tutor_item_supply_native_exposure_inbox WHERE id=NEW.inbox_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
    IF NOT FOUND OR r.version_id IS DISTINCT FROM NEW.version_id OR r.kind IN ('metadata','untracked') THEN
      RAISE check_violation USING MESSAGE='native exposure exact original event required';
    END IF;
    b:=NEW.binding_json;
  ELSIF TG_TABLE_NAME='tutor_item_supply_native_exposure_watermarks' THEN
    SELECT COALESCE(max(sequence),0),count(*) INTO max_sequence,n FROM tutor_item_supply_native_exposure_inbox WHERE user_id=NEW.user_id AND epoch=NEW.epoch;
    SELECT COALESCE(jsonb_agg(jsonb_build_object('event_id',i.id,'item_handle',e.binding_json->>'item_handle',
      'content_hash',e.binding_json->>'content_hash','family_id',e.binding_json->>'family_id',
      'semantic_signature',e.binding_json->>'semantic_signature','kind',i.kind) ORDER BY i.sequence),'[]'::jsonb) INTO records
      FROM tutor_item_supply_native_exposure_events e JOIN tutor_item_supply_native_exposure_inbox i
      ON i.id=e.inbox_id AND i.user_id=e.user_id AND i.epoch=e.epoch WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch;
    IF item_supply_internal.native_exposure_hooks_current() IS DISTINCT FROM true OR NEW.watermark<>max_sequence
      OR NEW.payload_json->>'watermark' IS DISTINCT FROM max_sequence::text OR NEW.payload_json->>'origin_count' IS DISTINCT FROM n::text
      OR NEW.payload_json->>'user_id' IS DISTINCT FROM NEW.user_id::text OR NEW.payload_json->>'epoch' IS DISTINCT FROM NEW.epoch::text
      OR NEW.payload_json->>'birth_id' IS DISTINCT FROM NEW.birth_id::text OR NEW.payload_json->>'collector_version' IS DISTINCT FROM 'native-exposure-v1'
      OR NEW.payload_json->>'records_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(records)
      OR EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_inbox i LEFT JOIN tutor_item_supply_native_exposure_events e ON e.inbox_id=i.id
        WHERE i.user_id=NEW.user_id AND i.epoch=NEW.epoch AND i.kind<>'metadata' AND e.id IS NULL) THEN
      RAISE check_violation USING MESSAGE='native exposure completeness unproven';
    END IF;
    RETURN NEW;
  ELSE
    PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans a
      ON a.track_id=s.track_id AND a.user_id=s.user_id AND a.revision_id=s.revision_id
      WHERE s.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch FOR SHARE OF s,a;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native exposure active scope required'; END IF;
    IF TG_TABLE_NAME='tutor_item_supply_native_exposure_reservations' THEN
      SELECT * INTO r FROM tutor_item_supply_native_exposure_watermarks WHERE id=NEW.watermark_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
      SELECT COALESCE(max(sequence),0) INTO max_sequence FROM tutor_item_supply_native_exposure_inbox WHERE user_id=NEW.user_id AND epoch=NEW.epoch;
      IF r.id IS NULL OR r.watermark<>max_sequence OR NEW.bindings_json->0->>'family_id'=NEW.bindings_json->1->>'family_id' THEN
        RAISE check_violation USING MESSAGE='native assessment current complete watermark required';
      END IF;
      FOR b IN SELECT value FROM jsonb_array_elements(NEW.bindings_json) LOOP
        IF b->>'allocation_slot' IS DISTINCT FROM 'assessment' OR EXISTS(
          SELECT 1 FROM tutor_item_supply_native_exposure_events e WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch
          AND (e.binding_json->>'family_id'=b->>'family_id' OR e.binding_json->>'content_hash'=b->>'content_hash'
            OR e.binding_json->>'semantic_signature'=b->>'semantic_signature')) THEN
          RAISE check_violation USING MESSAGE='assessment identity already exposed';
        END IF;
        PERFORM item_supply_internal.native_exposure_binding_check(b,true);
      END LOOP;
      RETURN NEW;
    END IF;
    b:=NEW.binding_json;
    SELECT COALESCE(max(sequence),0) INTO max_sequence FROM tutor_item_supply_native_exposure_inbox WHERE user_id=NEW.user_id AND epoch=NEW.epoch;
    IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_watermarks WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND watermark=max_sequence)
      OR item_supply_internal.native_exposure_hooks_current() IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='native delivery requires current complete exposure watermark';
    END IF;
    SELECT bindings_json INTO prior FROM tutor_item_supply_native_exposure_reservations
      WHERE id=NEW.reservation_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    IF prior IS NULL OR NEW.delivery_txid<>txid_current() OR b->>'allocation_slot' IS DISTINCT FROM 'practice'
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(prior) x WHERE x->>'family_id'=b->>'family_id'
        OR x->>'semantic_signature'=b->>'semantic_signature' OR x->>'version_id'=b->>'version_id') THEN
      RAISE check_violation USING MESSAGE='native practice cannot expose reserved assessment';
    END IF;
    FOR p IN SELECT value FROM jsonb_array_elements(prior) LOOP
      PERFORM item_supply_internal.native_exposure_binding_check(p,true);
      IF EXISTS(SELECT 1 FROM tutor_item_supply_native_exposure_events e WHERE e.user_id=NEW.user_id AND e.epoch=NEW.epoch
        AND (e.binding_json->>'family_id'=p->>'family_id' OR e.binding_json->>'semantic_signature'=p->>'semantic_signature')) THEN
        RAISE check_violation USING MESSAGE='native reservation already contaminated';
      END IF;
    END LOOP;
  END IF;
  IF b->>'version_id' IS DISTINCT FROM NEW.version_id::text THEN
    RAISE check_violation USING MESSAGE='native exposure version mismatch';
  END IF;
  PERFORM item_supply_internal.native_exposure_binding_check(b,TG_TABLE_NAME='tutor_item_supply_native_exposure_deliveries');
  IF TG_TABLE_NAME='tutor_item_supply_native_exposure_events' THEN
    IF b->>'proof_id' IS DISTINCT FROM NEW.proof_id::text THEN
      RAISE check_violation USING MESSAGE='native exposure proof mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_native_exposure_insert() FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.native_exposure_binding_check(b jsonb, require_current boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE n record; spec jsonb;
BEGIN
  SELECT p.*,v.handle,v.content_hash INTO n FROM tutor_learning_item_native_publication_proofs p
    JOIN tutor_learning_item_versions v ON v.id=p.version_id WHERE p.id=(b->>'proof_id')::uuid;
  IF NOT FOUND OR n.version_id::text IS DISTINCT FROM b->>'version_id' OR n.handle IS DISTINCT FROM b->>'item_handle'
    OR n.content_hash IS DISTINCT FROM b->>'content_hash' OR n.proof_hash IS DISTINCT FROM b->>'proof_hash'
    OR n.proof_json->>'specification_hash' IS DISTINCT FROM b->>'specification_hash' THEN
    RAISE check_violation USING MESSAGE='native exposure publication proof mismatch';
  END IF;
  SELECT prep.payload_json->'spec' INTO spec FROM tutor_learning_item_validation_receipts v
    JOIN tutor_item_supply_shared_validation_evidence e ON e.id=v.native_validation_evidence_id
    JOIN tutor_item_supply_shared_validation_preparations prep ON prep.id=e.preparation_id WHERE v.id=(n.proof_json->>'bank_validation_id')::uuid;
  IF spec IS NULL OR item_supply_internal.snapshot_hash(spec) IS DISTINCT FROM b->>'specification_hash'
    OR spec->'allocation'->>'family_id' IS DISTINCT FROM b->>'family_id'
    OR spec->'allocation'->>'slot' IS DISTINCT FROM b->>'allocation_slot'
    OR spec->>'family_definition_hash' IS DISTINCT FROM b->>'family_definition_hash'
    OR b->>'semantic_signature' IS DISTINCT FROM b->>'family_definition_hash' THEN
    RAISE check_violation USING MESSAGE='native exposure family must come from immutable spec';
  END IF;
  IF require_current THEN
    PERFORM 1 FROM tutor_learning_item_versions WHERE id=n.version_id FOR SHARE;
  END IF;
  IF require_current AND NOT EXISTS(SELECT 1 FROM (
    SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=n.version_id ORDER BY state_version DESC LIMIT 1) p
    WHERE p.id=n.publication_event_id AND p.state='published') THEN
    RAISE check_violation USING MESSAGE='native exposure publication no longer current';
  END IF;
END $$;

-- Called by main's existing reset owner ONLY after epoch fencing and creation of
-- item_supply_internal.reset_permits, before it deletes private scopes/users.
CREATE OR REPLACE FUNCTION item_supply_internal.purge_native_exposure_private(target_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF item_supply_internal.permitted(target_user) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='native exposure purge requires existing maintenance capability';
  END IF;
  DELETE FROM tutor_item_supply_native_exposure_deliveries WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_native_exposure_reservations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_native_exposure_watermarks WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_native_exposure_events WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_native_exposure_inbox WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_native_exposure_births WHERE user_id=target_user;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_native_exposure_private(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.native_exposure_binding_check(jsonb,boolean) FROM PUBLIC;

-- The existing 470 reset owner establishes its permit and advances the epoch
-- before deleting private parents. Keep that owner/440 BEFORE guard unchanged;
-- clear these FK children immediately after the advance, including deleting=true.
-- Do not call native_exposure_lock here: deletion deliberately disables NEW.
-- Purging the old birth does NOT create a complete start for the new epoch.
CREATE OR REPLACE FUNCTION purge_native_exposure_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
    OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='native exposure reset requires permitted epoch advance';
  END IF;
  PERFORM item_supply_internal.purge_native_exposure_private(NEW.user_id);
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION purge_native_exposure_on_epoch_advance() FROM PUBLIC;
DROP TRIGGER IF EXISTS native_exposure_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER native_exposure_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
  FOR EACH ROW WHEN (OLD.epoch < NEW.epoch) EXECUTE FUNCTION purge_native_exposure_on_epoch_advance();

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['tutor_item_supply_native_exposure_births','tutor_item_supply_native_exposure_inbox',
    'tutor_item_supply_native_exposure_events','tutor_item_supply_native_exposure_watermarks',
    'tutor_item_supply_native_exposure_reservations','tutor_item_supply_native_exposure_deliveries'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS native_exposure_insert ON %I',t);
    EXECUTE format('CREATE TRIGGER native_exposure_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_native_exposure_insert()',t);
    EXECUTE format('DROP TRIGGER IF EXISTS native_exposure_immutable ON %I',t);
    EXECUTE format('CREATE TRIGGER native_exposure_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''private'')',t);
  END LOOP;
END $$;
