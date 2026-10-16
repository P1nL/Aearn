-- Same original task, append-only PRIVATE intent. SQL523 bytes remain frozen.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='526 B1d only'; END IF; END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_enhancement_intent_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE task record;p jsonb:=NEW.payload_json;m jsonb;
BEGIN
 IF NEW.record_kind<>'private_status' OR p->>'schema_version' IS DISTINCT FROM 'private_enhancement_intent_v1' THEN RETURN NEW; END IF;
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch::bigint);
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id AND pack_task_id=NEW.pack_task_id
  AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND record_kind='task' FOR SHARE;
 IF task.id IS NULL OR task.payload_json->>'enhancement' IS DISTINCT FROM 'base_only'
  OR NEW.intent_hash IS DISTINCT FROM task.intent_hash
  OR NEW.operation_key IS DISTINCT FROM 'enhancement.intent.'||replace(NEW.pack_task_id::text,'-','')||'.prefer_private'
  OR item_supply_internal.snapshot_keys(p,ARRAY['schema_version','pack_task_id','user_id','epoch','scope_id','public_task_id','previous_enhancement','enhancement']) IS DISTINCT FROM true
  OR (p->>'pack_task_id',p->>'user_id',p->>'epoch',p->>'scope_id',p->>'public_task_id',p->>'previous_enhancement',p->>'enhancement') IS DISTINCT FROM
    (task.id::text,task.user_id::text,task.epoch::text,task.scope_id::text,task.payload_json->'ref'->>'public_task_id','base_only','prefer_private') THEN
  RAISE check_violation USING MESSAGE='526 exact same-task append-only enhancement intent required'; END IF;
 m:=item_supply_internal.private_native_mapping_current((task.payload_json->'ref'->>'mapping_receipt_id')::uuid,task.user_id,task.epoch::bigint);
 IF m IS NULL THEN RAISE check_violation USING MESSAGE='526 original current confirmed goal required'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_enhancement_intent_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_enhancement_intent_insert ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER a000_private_enhancement_intent_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_enhancement_intent_insert();
