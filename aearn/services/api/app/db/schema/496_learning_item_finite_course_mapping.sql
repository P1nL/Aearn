-- Private frozen D mapping only. No source issuance, wallet or ready authority.
-- Main integrates manifest/inventory/export. Caller owns bootstrap transaction.
CREATE UNIQUE INDEX IF NOT EXISTS rag_d_finite_binding_scope
  ON rag_plan_material_bindings(id,user_id,session_id,draft_id,selection_handle,selection_digest,
                               node_id,goal_hash,binding_digest);

CREATE TABLE IF NOT EXISTS tutor_item_supply_finite_course_mappings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  track_id uuid NOT NULL, revision_id uuid NOT NULL, node_id uuid NOT NULL,
  knowledge_key text NOT NULL, session_id uuid NOT NULL, draft_id uuid NOT NULL,
  selection_handle text NOT NULL, selection_digest text NOT NULL CHECK(selection_digest ~ '^[0-9a-f]{64}$'),
  assessment_binding_id uuid NOT NULL, binding_digest text NOT NULL CHECK(binding_digest ~ '^[0-9a-f]{64}$'),
  goal_hash text NOT NULL CHECK(goal_hash ~ '^[0-9a-f]{64}$'),
  mapping_hash text NOT NULL CHECK(mapping_hash ~ '^[0-9a-f]{64}$'),
  practice_scope_id uuid NOT NULL, practice_demand_id uuid NOT NULL,
  assessment_scope_id uuid NOT NULL, assessment_demand_id uuid NOT NULL,
  remediation_scope_id uuid NOT NULL, remediation_demand_id uuid NOT NULL,
  receipt_json jsonb NOT NULL CHECK(jsonb_typeof(receipt_json)='object'
    AND octet_length(receipt_json::text)<=131072
    AND receipt_json->>'schema_version'='finite_course_mapping_v1'),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(receipt_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,mapping_hash), UNIQUE(id,user_id,epoch),
  FOREIGN KEY(user_id) REFERENCES tutor_item_supply_user_epochs(user_id) ON DELETE RESTRICT,
  FOREIGN KEY(node_id,revision_id,track_id,user_id)
    REFERENCES tutor_track_plan_nodes(id,revision_id,track_id,user_id) ON DELETE RESTRICT,
  FOREIGN KEY(revision_id,track_id,user_id,knowledge_key)
    REFERENCES tutor_track_plan_nodes(revision_id,track_id,user_id,knowledge_key) ON DELETE RESTRICT,
  FOREIGN KEY(session_id,user_id) REFERENCES tutor_learning_plan_sessions(id,user_id) ON DELETE RESTRICT,
  FOREIGN KEY(selection_handle,draft_id,session_id,user_id,selection_digest)
    REFERENCES rag_material_selections(handle,draft_id,session_id,user_id,selection_digest) ON DELETE RESTRICT,
  FOREIGN KEY(assessment_binding_id,user_id,session_id,draft_id,selection_handle,selection_digest,
              knowledge_key,goal_hash,binding_digest)
    REFERENCES rag_plan_material_bindings(id,user_id,session_id,draft_id,selection_handle,selection_digest,
                                         node_id,goal_hash,binding_digest) ON DELETE RESTRICT,
  FOREIGN KEY(practice_scope_id,user_id,epoch)
    REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(assessment_scope_id,user_id,epoch)
    REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(remediation_scope_id,user_id,epoch)
    REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(practice_demand_id,user_id,epoch,practice_scope_id)
    REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(assessment_demand_id,user_id,epoch,assessment_scope_id)
    REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(remediation_demand_id,user_id,epoch,remediation_scope_id)
    REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS finite_course_mapping_owner
  ON tutor_item_supply_finite_course_mappings(user_id,epoch,track_id,revision_id,node_id);

CREATE OR REPLACE FUNCTION enforce_finite_course_mapping_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE n jsonb; pack jsonb; sub jsonb; s record; d record; i integer; sid uuid; did uuid;
BEGIN
  PERFORM id FROM users WHERE id=NEW.user_id AND deleted_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping owner unavailable'; END IF;
  PERFORM user_id FROM tutor_item_supply_user_epochs
    WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping epoch stale'; END IF;
  PERFORM p.track_id FROM tutor_track_active_plans p JOIN tutor_track_plan_revisions r
    ON (r.id,r.track_id,r.user_id)=(p.revision_id,p.track_id,p.user_id)
    WHERE p.track_id=NEW.track_id AND p.user_id=NEW.user_id AND p.revision_id=NEW.revision_id
      AND r.status='active' FOR SHARE OF p,r;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping revision stale'; END IF;
  PERFORM id FROM tutor_learning_plan_sessions WHERE id=NEW.session_id AND user_id=NEW.user_id
    AND status='confirmed' AND confirmed_track_id=NEW.track_id AND current_draft_id=NEW.draft_id FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping confirmed draft stale'; END IF;
  PERFORM id FROM rag_plan_material_bindings WHERE id=NEW.assessment_binding_id AND purpose='assessment_evidence' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping requires assessment binding'; END IF;
  n := NEW.receipt_json->'frozen_node'; pack := NEW.receipt_json->'pack_request';
  PERFORM id FROM tutor_track_plan_nodes WHERE id=NEW.node_id AND user_id=NEW.user_id
    AND track_id=NEW.track_id AND revision_id=NEW.revision_id AND knowledge_key=NEW.knowledge_key
    AND title IS NOT DISTINCT FROM n->>'title' AND description IS NOT DISTINCT FROM n->>'description'
    AND is_core::text IS NOT DISTINCT FROM n->>'is_core'
    AND prerequisite_keys_json IS NOT DISTINCT FROM n->'prerequisite_keys'
    AND required_capabilities_json IS NOT DISTINCT FROM n->'required_capabilities'
    AND catalog_knowledge_key IS NOT DISTINCT FROM n->>'catalog_knowledge_key' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping original node mismatch'; END IF;
  PERFORM id FROM tutor_learning_plan_drafts WHERE id=NEW.draft_id AND user_id=NEW.user_id
    AND session_id=NEW.session_id AND draft_version::text IS NOT DISTINCT FROM n->>'draft_version'
    AND content_hash IS NOT DISTINCT FROM n->>'draft_content_hash'
    AND source_run_id::text IS NOT DISTINCT FROM n->>'source_run_id'
    AND source_input_revision::text IS NOT DISTINCT FROM n->>'source_input_revision' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping original draft mismatch'; END IF;
  PERFORM r.id FROM tutor_track_plan_revisions r JOIN tutor_learning_tracks t
    ON (t.id,t.user_id)=(r.track_id,r.user_id)
    WHERE r.id=NEW.revision_id AND r.track_id=NEW.track_id AND r.user_id=NEW.user_id
      AND r.content_hash IS NOT DISTINCT FROM n->>'plan_content_hash'
      AND t.language_id IS NOT DISTINCT FROM n->>'language_id' FOR SHARE OF r,t;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='finite mapping original plan mismatch'; END IF;
  IF (NEW.receipt_json->>'receipt_id',NEW.receipt_json->>'mapping_hash',n->>'user_id',n->>'epoch',
      n->>'track_id',n->>'revision_id',n->>'node_id',n->>'knowledge_key',n->>'session_id',n->>'draft_id',
      n->>'selection_handle',n->>'selection_digest',n->>'assessment_binding_id',n->>'assessment_binding_digest',n->>'goal_hash')
    IS DISTINCT FROM (NEW.id::text,NEW.mapping_hash,NEW.user_id::text,NEW.epoch::text,NEW.track_id::text,
      NEW.revision_id::text,NEW.node_id::text,NEW.knowledge_key,NEW.session_id::text,NEW.draft_id::text,
      NEW.selection_handle,NEW.selection_digest,NEW.assessment_binding_id::text,NEW.binding_digest,NEW.goal_hash)
    OR (pack->>'learner_id',pack->>'epoch',pack->>'track_id',pack->>'revision_id',pack->>'node_id',pack->>'course_mapping_hash',pack->>'storage_scope_id')
      IS DISTINCT FROM (NEW.user_id::text,NEW.epoch::text,NEW.track_id::text,NEW.revision_id::text,NEW.node_id::text,
                        NEW.mapping_hash,NEW.practice_scope_id::text)
    OR jsonb_array_length(pack->'demands') IS DISTINCT FROM 3
    OR jsonb_array_length(pack->'clause_mapping') IS DISTINCT FROM 3
    OR jsonb_array_length(NEW.receipt_json->'stored_demands') IS DISTINCT FROM 3 THEN
    RAISE check_violation USING MESSAGE='finite mapping snapshot identity mismatch';
  END IF;
  FOR i IN 0..2 LOOP
    sid := CASE i WHEN 0 THEN NEW.practice_scope_id WHEN 1 THEN NEW.assessment_scope_id ELSE NEW.remediation_scope_id END;
    did := CASE i WHEN 0 THEN NEW.practice_demand_id WHEN 1 THEN NEW.assessment_demand_id ELSE NEW.remediation_demand_id END;
    sub := pack->'demands'->i;
    SELECT * INTO s FROM tutor_item_supply_private_scopes WHERE id=sid AND user_id=NEW.user_id AND epoch=NEW.epoch FOR SHARE;
    IF NOT FOUND OR (s.track_id,s.revision_id,s.knowledge_key) IS DISTINCT FROM (NEW.track_id,NEW.revision_id,NEW.knowledge_key)
      OR s.snapshot_json IS DISTINCT FROM sub->'demand'->'scope'
      OR s.snapshot_json IS DISTINCT FROM sub->'blueprint'->'scope'
      OR s.objective_hash IS DISTINCT FROM sub->'demand'->>'objective_hash'
      OR s.objective_hash IS DISTINCT FROM sub->'blueprint'->>'objective_hash' THEN
      RAISE check_violation USING MESSAGE='finite mapping original scope mismatch';
    END IF;
    SELECT * INTO d FROM tutor_item_supply_private_demands WHERE id=did AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=sid FOR SHARE;
    IF NOT FOUND OR d.snapshot_json IS DISTINCT FROM sub->'demand'
      OR sub->>'storage_scope_id' IS DISTINCT FROM sid::text
      OR sub->>'mapping_receipt_hash' IS DISTINCT FROM NEW.mapping_hash
      OR sub->>'slot' IS DISTINCT FROM (ARRAY['practice','assessment','remediation'])[i+1]
      OR NEW.receipt_json->'stored_demands'->i IS DISTINCT FROM jsonb_build_object(
        'slot',sub->>'slot','scope_id',sid::text,'demand_id',did::text) THEN
      RAISE check_violation USING MESSAGE='finite mapping original demand mismatch';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS finite_course_mapping_insert ON tutor_item_supply_finite_course_mappings;
CREATE TRIGGER finite_course_mapping_insert BEFORE INSERT ON tutor_item_supply_finite_course_mappings
  FOR EACH ROW EXECUTE FUNCTION enforce_finite_course_mapping_insert();
DROP TRIGGER IF EXISTS finite_course_mapping_immutable ON tutor_item_supply_finite_course_mappings;
CREATE TRIGGER finite_course_mapping_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_finite_course_mappings
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

-- No downstream mapping children exist. 495 has no FK to this receipt, so the
-- two AFTER hooks commute. Both run before original 470 deletes scope parents.
CREATE OR REPLACE FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
    OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='finite mapping reset requires original permitted epoch advance';
  END IF;
  DELETE FROM tutor_item_supply_finite_course_mappings WHERE user_id=NEW.user_id;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance() FROM PUBLIC;
DROP TRIGGER IF EXISTS finite_course_mapping_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER finite_course_mapping_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
  FOR EACH ROW WHEN (OLD.epoch < NEW.epoch)
  EXECUTE FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance();
