-- Prospective explicit PUBLIC whole-base fallback on original521/230 writers.
-- Requires reviewed523-528; zero tables/columns; existing PRIVATE journal only.
-- This does NOT grant private publication, score, Gate or business termination.
DO $require_reviewed_527$
DECLARE original record;
BEGIN
 SELECT p.*,l.lanname,encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') AS body_hash INTO original
 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid=to_regprocedure('item_supply_internal.assert_private_native_historical_investigation(tutor_item_supply_private_native_quality_evidence,uuid)');
 IF original.oid IS NULL OR original.lanname<>'plpgsql' OR NOT original.prosecdef OR original.provolatile<>'v'
  OR original.proisstrict OR original.prokind<>'f' OR original.prorettype<>'void'::regtype
  OR original.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  OR original.body_hash<>'49d8d824d22601fba1aad9170a324e6251285318e61b232261b556cf69f95957' THEN
  RAISE check_violation USING MESSAGE='529 reviewed frozen527 baseline must be installed first'; END IF;
END $require_reviewed_527$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_public_fallback_frame(p jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE task public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 unionrow record;el record;res record;prior record;m jsonb;s jsonb;public_bindings jsonb;union_bindings jsonb;ids jsonb;protected jsonb;stamp timestamptz;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','task_ref','run_id','stage','selected_version_id','reservation_id','public_eligibility_id','union_receipt_id']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_public_fallback_clearance_v1'
  OR COALESCE(p->>'stage' IN('advertise','prepare','create'),false) IS DISTINCT FROM true
  OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE check_violation USING MESSAGE='529 exact explicit fallback frame/transaction required'; END IF;
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->'task_ref'->>'pack_task_id')::uuid
  AND record_kind='task' AND payload_json->'ref'=p->'task_ref';
 IF task.id IS NULL OR item_supply_internal.private_native_task_enhancement(task.id,task.user_id,task.epoch::bigint,task.scope_id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='529 original same PRIVATE intent task required'; END IF;
 PERFORM item_supply_internal.private_native_epoch(task.user_id,task.epoch::bigint);
 -- A veto, quality/source deny or technical phase expiry is NEVER an end_wait.
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal ended WHERE ended.pack_task_id=task.id
  AND ended.user_id=task.user_id AND ended.epoch=task.epoch AND ended.scope_id=task.scope_id AND ended.record_kind='private_status'
  AND ((ended.payload_json->>'schema_version'='private_enhancement_wait_end_v1' AND ended.payload_json->>'reason'='consumer_cancelled')
   OR (ended.payload_json->>'schema_version'='private_enhancement_wait_v1' AND (ended.payload_json->>'valid_until')::timestamptz<=clock_timestamp()))) THEN
  RAISE check_violation USING MESSAGE='529 genuine consumer wait end/timeout required, not first veto'; END IF;
 SELECT * INTO unionrow FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'union_receipt_id')::uuid
  AND pack_task_id=task.id AND user_id=task.user_id AND epoch=task.epoch AND scope_id=task.scope_id AND record_kind='private_status';
 -- Complete original source set is acquired BEFORE any original bank locks.
 IF unionrow.id IS NULL OR item_supply_internal.private_native_base_union_current(unionrow.id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='529 fresh original PRIVATE whole-base union required'; END IF;
 s:=unionrow.payload_json->'snapshot';
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid
  AND user_id=task.user_id AND epoch=task.epoch AND txid=txid_current()
  AND mapping_receipt_id=(task.payload_json->'ref'->>'mapping_receipt_id')::uuid;
 SELECT * INTO res FROM tutor_item_supply_type_exposure_reservations WHERE id=(p->>'reservation_id')::uuid
  AND user_id=task.user_id AND epoch=task.epoch
  AND operation_key='native-supply.'||replace(task.payload_json->'ref'->>'demand_id','-','');
 m:=item_supply_internal.private_native_mapping_current((task.payload_json->'ref'->>'mapping_receipt_id')::uuid,task.user_id,task.epoch::bigint);
 IF el.id IS NULL OR res.id IS NULL OR m IS NULL OR el.snapshot_json->'request' IS DISTINCT FROM s->'request'
  OR el.snapshot_json->'request' IS DISTINCT FROM m->'pack_request'
  OR res.request_json->>'mapping_receipt_id' IS DISTINCT FROM el.mapping_receipt_id::text
  OR res.request_json->>'pack_request_hash' IS DISTINCT FROM el.request_hash
  OR res.scope_id::text IS DISTINCT FROM s->'request'->>'storage_scope_id'
  OR jsonb_array_length(el.snapshot_json->'selected') IS DISTINCT FROM 5
  OR (SELECT count(*) FROM jsonb_array_elements(el.snapshot_json->'selected') c WHERE c->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(el.snapshot_json->'selected') c WHERE c->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(el.snapshot_json->'selected') c WHERE c->'member'->>'slot'='remediation')<>1 THEN
  RAISE check_violation USING MESSAGE='529 retained original502 whole PUBLIC five mapping required'; END IF;
 SELECT jsonb_agg(jsonb_build_array(c->>'version_id',c->>'publication_id',c->>'materialization_id',c->>'proof_id',c->'member',c->'type_evidence'->'content',c->'candidate'->'scope',c->'candidate'->'clauses',c->'candidate'->>'objective_hash',c->'candidate'->>'blueprint_hash') ORDER BY c->>'version_id') INTO public_bindings FROM jsonb_array_elements(el.snapshot_json->'selected') c;
 SELECT jsonb_agg(jsonb_build_array(c->>'version_id',c->>'publication_id',c->>'materialization_id',c->>'proof_id',c->'member',c->'type_evidence'->'content',c->'candidate'->'scope',c->'candidate'->'clauses',c->'candidate'->>'objective_hash',c->'candidate'->>'blueprint_hash') ORDER BY c->>'version_id') INTO union_bindings FROM jsonb_array_elements(s->'selected') c;
 SELECT jsonb_agg(c->>'version_id' ORDER BY c->>'version_id') INTO ids FROM jsonb_array_elements(s->'selected') c;
 SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO protected FROM jsonb_array_elements(s->'selected') c WHERE c->'member'->>'slot'='assessment';
 IF public_bindings IS DISTINCT FROM union_bindings OR (SELECT count(DISTINCT c->>'version_id') FROM jsonb_array_elements(s->'selected') c)<>5
  OR ids IS DISTINCT FROM res.request_json->'selected_version_ids'
  OR ids IS DISTINCT FROM (SELECT jsonb_agg(version_refs.value ORDER BY version_refs.value) FROM jsonb_array_elements_text(res.request_json->'candidate_version_ids') AS version_refs(value))
  OR protected IS DISTINCT FROM res.bindings_json OR protected IS DISTINCT FROM res.request_json->'bindings'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(s->'selected') c WHERE c->>'version_id'=p->>'selected_version_id'
    AND c->'member'->>'slot'='practice' AND c->'candidate'->>'visibility'='public'
    AND c->'candidate'->'owner_ref'='null'::jsonb AND c->'owner_id'='null'::jsonb AND c->'epoch'='null'::jsonb)
  OR item_supply_internal.type_exposure_current(el.exposure_snapshot_id,task.user_id,task.epoch::bigint) IS DISTINCT FROM
    (SELECT snapshot_json FROM tutor_item_supply_type_exposure_snapshots WHERE id=el.exposure_snapshot_id AND user_id=task.user_id AND epoch=task.epoch) THEN
  RAISE check_violation USING MESSAGE='529 exact fixed ownerless PUBLIC practice/base reservation required'; END IF;
 -- Original candidate/materializer remain the full session/CAS receivers. Bind
 -- the clearance to their actual run, track, revision, node and private goal.
 IF NOT EXISTS(SELECT 1 FROM tutor_run_teaching_scopes scopes JOIN tutor_runs runrow ON runrow.id=scopes.run_id
   AND runrow.user_id=scopes.user_id AND runrow.conversation_id=scopes.conversation_id
  JOIN tutor_track_plan_nodes node ON node.id=(m->'frozen_node'->>'node_id')::uuid AND node.user_id=scopes.user_id
   AND node.track_id=scopes.track_id AND node.revision_id=scopes.active_plan_revision_id AND node.knowledge_key=scopes.knowledge_key
  WHERE scopes.run_id=(p->>'run_id')::uuid AND scopes.user_id=task.user_id
   AND scopes.track_id=(m->'frozen_node'->>'track_id')::uuid AND scopes.knowledge_key=m->'frozen_node'->>'knowledge_key'
   AND scopes.active_plan_revision_id=(m->'frozen_node'->>'revision_id')::uuid) THEN
  RAISE check_violation USING MESSAGE='529 exact original run/track/revision/node/goal required'; END IF;
 FOR prior IN SELECT payload_json FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=task.user_id AND epoch=task.epoch
  AND record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_public_fallback_clearance_v1'
  AND payload_json->>'run_id'=p->>'run_id' LOOP
  IF (prior.payload_json->'task_ref',prior.payload_json->>'selected_version_id',prior.payload_json->>'reservation_id')
    IS DISTINCT FROM (p->'task_ref',p->>'selected_version_id',p->>'reservation_id') THEN
   RAISE check_violation USING MESSAGE='529 immutable run selected practice/task/reservation cannot change'; END IF;
 END LOOP;
 -- Re-read fences/time after original source/bank waits, not caller's old clock.
 IF item_supply_internal.private_native_base_union_current(unionrow.id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='529 union/source changed after wait'; END IF;
 stamp:=clock_timestamp();
 IF NOT(el.checked_at<=stamp AND stamp<el.valid_until) THEN
  RAISE check_violation USING MESSAGE='529 current PUBLIC eligibility expired after wait'; END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_public_fallback_frame(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_public_fallback_clearance() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_public_fallback_clearance() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_public_fallback_clearance ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER a000_private_native_public_fallback_clearance BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_public_fallback_clearance();

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_public_fallback_record(p jsonb) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_public_fallback_record(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_public_fallback_for_creation(
 creator tutor_item_supply_native_consumer_receipts,required_stage text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_public_fallback_for_creation(tutor_item_supply_native_consumer_receipts,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_native_public_fallback_consumer_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE incoming public.tutor_item_supply_native_consumer_receipts%ROWTYPE;
BEGIN
 incoming:=NEW;
 IF NEW.mode='create' AND item_supply_internal.private_native_public_fallback_for_creation(incoming,'prepare') IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='529 prefer-private PUBLIC creation requires explicit fresh fallback context'; END IF;
 RETURN NEW; -- original521 current consume/cancel owns ongoing actions unchanged.
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_native_public_fallback_consumer_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_native_public_fallback_consumer_insert ON tutor_item_supply_native_consumer_receipts;
CREATE TRIGGER a000_native_public_fallback_consumer_insert BEFORE INSERT ON tutor_item_supply_native_consumer_receipts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_native_public_fallback_consumer_insert();

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_native_public_fallback_artifact_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE creator public.tutor_item_supply_native_consumer_receipts%ROWTYPE;
BEGIN
 IF NEW.owner_kind<>'learning_item' THEN RETURN NEW; END IF;
 SELECT * INTO creator FROM tutor_item_supply_native_consumer_receipts WHERE mode='create' AND user_id=NEW.user_id
  AND run_id=NEW.turn_id AND version_id=NEW.owner_id AND txid=txid_current();
 IF creator.id IS NULL THEN RETURN NEW; END IF; -- original230/521 still rejects unchecked native owners.
 IF item_supply_internal.private_native_public_fallback_for_creation(creator,'create') IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='529 original Artifact writer requires fresh terminal fallback clearance'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_native_public_fallback_artifact_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_native_public_fallback_artifact_insert ON tutor_learning_artifacts;
CREATE TRIGGER a000_native_public_fallback_artifact_insert BEFORE INSERT ON tutor_learning_artifacts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_native_public_fallback_artifact_insert();
CREATE INDEX IF NOT EXISTS private_native_public_fallback_run ON tutor_item_supply_private_persistent_pack_journal
 (user_id,epoch,(payload_json->>'run_id')) WHERE record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_public_fallback_clearance_v1';

