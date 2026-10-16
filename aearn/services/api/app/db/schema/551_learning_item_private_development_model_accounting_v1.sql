-- Prospective isolated PRIVATE accounting only; not dispatch/source authority.
-- Installed fragments <=550 and all old usage/windows/UNKNOWN remain untouched.
CREATE TABLE IF NOT EXISTS tutor_item_supply_development_private_global_limit_modes (
 global_limit_id uuid PRIMARY KEY REFERENCES tutor_item_supply_runtime_global_limits(id) ON DELETE RESTRICT,
 mode text NOT NULL DEFAULT 'accounting_only' CHECK(mode='accounting_only'),
 authorization_key text NOT NULL DEFAULT 'development-unlimited-model-calls-20261010'
   CHECK(authorization_key='development-unlimited-model-calls-20261010'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- Above is SHARED anonymous mode classification, not a PRIVATE mapping. It must
-- survive reset alongside original global allocation/usage facts.
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_development_model_accounting_batches (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, root_id uuid NOT NULL,
 window_id uuid NOT NULL UNIQUE,
 provider_key text NOT NULL CHECK(provider_key='deepseek'),
 model text NOT NULL CHECK(model='deepseek-flash'),
 authorization_key text NOT NULL CHECK(authorization_key='development-unlimited-model-calls-20261010'),
 global_limit_ids uuid[] NOT NULL CHECK(array_ndims(global_limit_ids)=1 AND cardinality(global_limit_ids)=32 AND array_position(global_limit_ids,NULL) IS NULL),
 user_limit_ids uuid[] NOT NULL CHECK(array_ndims(user_limit_ids)=1 AND cardinality(user_limit_ids)=8 AND array_position(user_limit_ids,NULL) IS NULL),
 started_at timestamptz NOT NULL, valid_until timestamptz NOT NULL,
 mode text NOT NULL DEFAULT 'accounting_only' CHECK(mode='accounting_only'),
 cumulative_caps_enforced boolean NOT NULL DEFAULT false CHECK(cumulative_caps_enforced=false),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(valid_until>started_at AND valid_until<=started_at+interval '2 hours'),
 UNIQUE(id,user_id,epoch,scope_id,root_id,window_id),
 FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(root_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_budget_roots(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(root_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_obligations(root_id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(window_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_budget_windows(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_development_model_accounting_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, root_id uuid NOT NULL, window_id uuid NOT NULL,
 job_id uuid NOT NULL UNIQUE, batch_id uuid NOT NULL, parent_job_id uuid,
 lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
 lease_generation integer NOT NULL CHECK(lease_generation=1),
 lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
 profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
 parent_deadline timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(batch_id,user_id,epoch,scope_id,root_id,window_id) REFERENCES tutor_item_supply_private_development_model_accounting_batches(id,user_id,epoch,scope_id,root_id,window_id) ON DELETE RESTRICT,
 FOREIGN KEY(job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_job_controls(job_id,user_id,epoch,scope_id) ON DELETE RESTRICT,
 FOREIGN KEY(parent_job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_development_global_mode_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE gl tutor_item_supply_runtime_global_limits%ROWTYPE;
BEGIN
 SELECT * INTO gl FROM tutor_item_supply_runtime_global_limits g WHERE g.id=NEW.global_limit_id;
 IF current_database()<>'aearn_b1d_sandbox_20261001'
   OR NEW.mode IS DISTINCT FROM 'accounting_only'
   OR NEW.authorization_key IS DISTINCT FROM 'development-unlimited-model-calls-20261010'
   OR gl.id IS NULL OR gl.cap_amount IS DISTINCT FROM 1 OR gl.window_end<=clock_timestamp()
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_limits g WHERE g.id=NEW.global_limit_id AND g.xmin::text::bigint=(txid_current()%4294967296))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts a WHERE a.limit_id=NEW.global_limit_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_batches b WHERE NEW.global_limit_id=ANY(b.global_limit_ids)) THEN
   RAISE check_violation USING MESSAGE='551 anonymous mode requires fresh isolated nominal global limit';
 END IF;
 RETURN NEW;
END $$;

-- Original namespace lock/current epoch + active plan, immutable exact closure
-- and a fresh clock AFTER every row read. No permission comes from a locator.
CREATE OR REPLACE FUNCTION item_supply_internal.private_development_accounting_batch_current(
 b tutor_item_supply_private_development_model_accounting_batches) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE rr tutor_item_supply_private_budget_roots%ROWTYPE;
 oo tutor_item_supply_private_obligations%ROWTYPE;
 ww tutor_item_supply_private_budget_windows%ROWTYPE;
 active_epoch bigint; active_enabled boolean; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001'
   OR b.authorization_key IS DISTINCT FROM 'development-unlimited-model-calls-20261010'
   OR b.provider_key IS DISTINCT FROM 'deepseek' OR b.model IS DISTINCT FROM 'deepseek-flash'
   OR b.mode IS DISTINCT FROM 'accounting_only' OR b.cumulative_caps_enforced IS DISTINCT FROM false THEN
   RAISE check_violation USING MESSAGE='551 explicit isolated PRIVATE accounting only';
 END IF;
 PERFORM 1 FROM users u WHERE u.id=b.user_id AND u.deleted_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='551 PRIVATE user unavailable'; END IF;
 SELECT e.epoch,e.enabled INTO active_epoch,active_enabled FROM tutor_item_supply_user_epochs e WHERE e.user_id=b.user_id FOR SHARE;
 IF active_epoch IS DISTINCT FROM b.epoch OR active_enabled IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='551 PRIVATE epoch stale'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
   ON (p.track_id,p.user_id,p.revision_id)=(s.track_id,s.user_id,s.revision_id)
   WHERE s.id=b.scope_id AND s.user_id=b.user_id AND s.epoch=b.epoch FOR SHARE OF s,p;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='551 PRIVATE scope stale'; END IF;
 SELECT * INTO rr FROM tutor_item_supply_private_budget_roots r WHERE r.id=b.root_id AND r.user_id=b.user_id AND r.epoch=b.epoch AND r.scope_id=b.scope_id;
 SELECT * INTO oo FROM tutor_item_supply_private_obligations o WHERE o.root_id=b.root_id AND o.user_id=b.user_id AND o.epoch=b.epoch AND o.scope_id=b.scope_id;
 SELECT * INTO ww FROM tutor_item_supply_private_budget_windows w WHERE w.id=b.window_id AND w.user_id=b.user_id AND w.epoch=b.epoch AND w.scope_id=b.scope_id AND w.root_id=b.root_id;
 IF rr.id IS NULL OR oo.id IS NULL OR ww.id IS NULL
   OR rr.canonical_key IS DISTINCT FROM oo.canonical_key
   OR oo.obligation_json->>'visibility' IS DISTINCT FROM 'private'
   OR oo.obligation_json->>'owner_id' IS DISTINCT FROM b.user_id::text
   OR oo.pool_class IS DISTINCT FROM 'enhancement' OR oo.provider_key IS DISTINCT FROM b.provider_key
   OR ww.pool_key IS DISTINCT FROM oo.pool_class OR ww.provider_key IS DISTINCT FROM b.provider_key
   OR ww.window_start IS DISTINCT FROM b.started_at OR ww.window_end IS DISTINCT FROM b.valid_until
   OR ww.request_cap IS DISTINCT FROM 1 OR ww.token_cap IS DISTINCT FROM 1 OR ww.resource_cap IS DISTINCT FROM 1
   OR cardinality(b.global_limit_ids) IS DISTINCT FROM 32
   OR (SELECT count(DISTINCT v) FROM unnest(b.global_limit_ids) v)<>32
   OR cardinality(b.user_limit_ids) IS DISTINCT FROM 8
   OR (SELECT count(DISTINCT v) FROM unnest(b.user_limit_ids) v)<>8 THEN
   RAISE check_violation USING MESSAGE='551 PRIVATE canonical batch closure invalid'; END IF;
 IF (SELECT count(*) FROM tutor_item_supply_runtime_global_limits g
       JOIN tutor_item_supply_development_private_global_limit_modes m ON m.global_limit_id=g.id
       WHERE g.id=ANY(b.global_limit_ids) AND g.cap_amount=1
         AND g.window_start=b.started_at AND g.window_end=b.valid_until
         AND m.mode='accounting_only' AND m.authorization_key=b.authorization_key
         AND ((g.dimension_kind IN ('system','window') AND g.dimension_key='item-supply')
           OR (g.dimension_kind='pool' AND g.dimension_key='enhancement')
           OR (g.dimension_kind='provider' AND g.dimension_key=b.provider_key)))<>32
   OR (SELECT count(DISTINCT (g.dimension_kind,g.resource_kind)) FROM tutor_item_supply_runtime_global_limits g WHERE g.id=ANY(b.global_limit_ids))<>32
   OR (SELECT count(*) FROM tutor_item_supply_private_runtime_user_limits u
       WHERE u.id=ANY(b.user_limit_ids) AND u.user_id=b.user_id AND u.epoch=b.epoch
         AND u.cap_amount=1 AND u.window_start=b.started_at AND u.window_end=b.valid_until)<>8
   OR (SELECT count(DISTINCT u.resource_kind) FROM tutor_item_supply_private_runtime_user_limits u WHERE u.id=ANY(b.user_limit_ids))<>8 THEN
   RAISE check_violation USING MESSAGE='551 PRIVATE exact 32 global and 8 user closure required'; END IF;
 stamp:=clock_timestamp();
 IF b.started_at IS NULL OR b.valid_until IS NULL OR b.started_at>stamp OR b.valid_until<=stamp
   OR b.valid_until<=b.started_at OR b.valid_until>b.started_at+interval '2 hours' THEN
   RAISE check_violation USING MESSAGE='551 PRIVATE batch final operation deadline expired'; END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_development_accounting_batch_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 PERFORM item_supply_internal.private_development_accounting_batch_current(NEW);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_budget_windows w WHERE w.id=NEW.window_id AND w.xmin::text::bigint=(txid_current()%4294967296))
   OR (SELECT count(*) FROM tutor_item_supply_runtime_global_limits g WHERE g.id=ANY(NEW.global_limit_ids) AND g.xmin::text::bigint=(txid_current()%4294967296))<>32
   OR (SELECT count(*) FROM tutor_item_supply_development_private_global_limit_modes m WHERE m.global_limit_id=ANY(NEW.global_limit_ids) AND m.xmin::text::bigint=(txid_current()%4294967296))<>32
   OR (SELECT count(*) FROM tutor_item_supply_private_runtime_user_limits u WHERE u.id=ANY(NEW.user_limit_ids) AND u.xmin::text::bigint=(txid_current()%4294967296))<>8
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.window_id=NEW.window_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts a WHERE a.limit_id=ANY(NEW.global_limit_ids))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_runtime_reservation_amounts a WHERE a.limit_id=ANY(NEW.user_limit_ids))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.global_limit_ids && NEW.global_limit_ids OR b.user_limit_ids && NEW.user_limit_ids)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_batches b WHERE b.global_limit_ids && NEW.global_limit_ids) THEN
   RAISE check_violation USING MESSAGE='551 PRIVATE batch requires fresh atomic unspent nominal rows'; END IF;
 -- Full closure/final clock again after freshness checks.
 PERFORM item_supply_internal.private_development_accounting_batch_current(NEW);
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_development_accounting_job_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE b tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 j tutor_item_supply_private_jobs%ROWTYPE;
 c tutor_item_supply_private_job_controls%ROWTYPE;
 p tutor_item_supply_parameter_profiles%ROWTYPE;
 pc tutor_item_supply_private_job_controls%ROWTYPE;
 snapshot jsonb; stamp timestamptz;
BEGIN
 SELECT * INTO b FROM tutor_item_supply_private_development_model_accounting_batches bd WHERE bd.id=NEW.batch_id;
 IF b.id IS NULL THEN RAISE check_violation USING MESSAGE='551 PRIVATE accounting batch required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(b);
 SELECT * INTO j FROM tutor_item_supply_private_jobs jj WHERE jj.id=NEW.job_id AND jj.user_id=NEW.user_id AND jj.epoch=NEW.epoch AND jj.scope_id=NEW.scope_id;
 SELECT * INTO c FROM tutor_item_supply_private_job_controls cc WHERE cc.job_id=NEW.job_id AND cc.user_id=NEW.user_id AND cc.epoch=NEW.epoch AND cc.scope_id=NEW.scope_id FOR UPDATE;
 SELECT * INTO p FROM tutor_item_supply_parameter_profiles pp WHERE pp.id=c.profile_id;
 snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 stamp:=clock_timestamp();
 IF j.id IS NULL OR c.id IS NULL OR p.id IS NULL
   OR (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.root_id,NEW.window_id) IS DISTINCT FROM (b.user_id,b.epoch,b.scope_id,b.root_id,b.window_id)
   OR j.root_id IS DISTINCT FROM b.root_id OR j.parent_job_id IS DISTINCT FROM NEW.parent_job_id
   OR c.state IS DISTINCT FROM 'leased' OR c.breaker_open IS DISTINCT FROM false
   OR c.attempt_count IS DISTINCT FROM 1 OR c.lease_generation IS DISTINCT FROM 1
   OR c.lease_owner IS DISTINCT FROM NEW.lease_owner OR c.lease_generation IS DISTINCT FROM NEW.lease_generation
   OR c.state_version::bigint IS DISTINCT FROM NEW.lease_state_version
   OR c.lease_expires_at IS NULL OR c.lease_expires_at<=stamp OR c.parent_deadline<=stamp
   OR NEW.parent_deadline IS DISTINCT FROM c.parent_deadline OR NEW.parent_deadline>b.valid_until
   OR snapshot->>'profile_hash' IS DISTINCT FROM NEW.profile_hash OR p.profile_hash IS DISTINCT FROM NEW.profile_hash
   OR snapshot->>'profile_key_hash' IS DISTINCT FROM p.profile_key_hash
   OR (snapshot->>'parent_deadline_at')::timestamptz IS DISTINCT FROM NEW.parent_deadline
   OR p.profile_json->'profile_key'->>'provider' IS DISTINCT FROM b.provider_key
   OR p.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM b.model
   OR (j.created_at<b.started_at AND NOT EXISTS(
       SELECT 1 FROM tutor_item_supply_private_jobs jx,tutor_item_supply_private_development_model_accounting_batches bx
       WHERE jx.id=NEW.job_id AND bx.id=NEW.batch_id AND jx.xmin::text=bx.xmin::text))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal ph
       WHERE ph.user_id=NEW.user_id AND ph.epoch=NEW.epoch
         AND ph.payload_json->>'schema_version'='private_native_phase_v1'
         AND ph.payload_json->>'job_id'=NEW.job_id::text) THEN
   RAISE check_violation USING MESSAGE='551 PRIVATE fresh first-claimed unspent original job required'; END IF;
 IF NEW.parent_job_id IS NOT NULL THEN
   SELECT * INTO pc FROM tutor_item_supply_private_job_controls cc WHERE cc.job_id=NEW.parent_job_id AND cc.user_id=NEW.user_id AND cc.epoch=NEW.epoch AND cc.scope_id=NEW.scope_id FOR SHARE;
   IF pc.id IS NULL OR pc.state IS DISTINCT FROM 'leased' OR pc.lease_expires_at IS NULL
     OR pc.lease_expires_at<=clock_timestamp() OR pc.parent_deadline<NEW.parent_deadline
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_jobs pm
       WHERE pm.job_id=NEW.parent_job_id AND pm.batch_id=NEW.batch_id AND pm.user_id=NEW.user_id
         AND pm.epoch=NEW.epoch AND pm.scope_id=NEW.scope_id AND pm.root_id=NEW.root_id AND pm.window_id=NEW.window_id
         AND pm.lease_generation=pc.lease_generation AND pm.lease_owner=pc.lease_owner
         AND pm.profile_hash=CASE WHEN pc.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
           THEN pc.profile_snapshot_json->'profile'->>'profile_hash' ELSE pc.profile_snapshot_json->>'profile_hash' END) THEN
     RAISE check_violation USING MESSAGE='551 PRIVATE child requires same-batch current actual parent'; END IF;
 END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(b);
 stamp:=clock_timestamp();
 IF stamp>=c.lease_expires_at OR stamp>=NEW.parent_deadline
   OR (NEW.parent_job_id IS NOT NULL AND stamp>=pc.lease_expires_at) THEN
   RAISE check_violation USING MESSAGE='551 PRIVATE mapping final lease deadline expired'; END IF;
 RETURN NEW;
END $$;

-- Runs INSIDE original 450 epoch advance, before any old FK target deletion.
-- This is not a callable independent purger; ordinary writes remain denied.
CREATE OR REPLACE FUNCTION item_supply_internal.purge_private_development_accounting_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch<>OLD.epoch+1
   OR item_supply_internal.permitted(OLD.user_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='551 original same-user epoch maintenance permit required'; END IF;
 PERFORM 1 FROM users u WHERE u.id=OLD.user_id AND u.deleted_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='551 original maintenance user lock required'; END IF;
 DELETE FROM tutor_item_supply_private_development_model_accounting_jobs WHERE user_id=OLD.user_id AND epoch<=OLD.epoch;
 DELETE FROM tutor_item_supply_private_development_model_accounting_batches WHERE user_id=OLD.user_id AND epoch<=OLD.epoch;
 RETURN NEW;
END $$;

REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_development_global_mode_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.private_development_accounting_batch_current(tutor_item_supply_private_development_model_accounting_batches) FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_development_accounting_batch_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_development_accounting_job_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.purge_private_development_accounting_on_epoch_advance() FROM PUBLIC;
DROP TRIGGER IF EXISTS private_development_global_mode_insert ON tutor_item_supply_development_private_global_limit_modes;
CREATE TRIGGER private_development_global_mode_insert BEFORE INSERT ON tutor_item_supply_development_private_global_limit_modes
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_development_global_mode_insert();
DROP TRIGGER IF EXISTS private_development_global_mode_immutable ON tutor_item_supply_development_private_global_limit_modes;
CREATE TRIGGER private_development_global_mode_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_development_private_global_limit_modes
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable();
DROP TRIGGER IF EXISTS private_development_accounting_batch_insert ON tutor_item_supply_private_development_model_accounting_batches;
CREATE TRIGGER private_development_accounting_batch_insert BEFORE INSERT ON tutor_item_supply_private_development_model_accounting_batches
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_development_accounting_batch_insert();
DROP TRIGGER IF EXISTS private_development_accounting_job_insert ON tutor_item_supply_private_development_model_accounting_jobs;
CREATE TRIGGER private_development_accounting_job_insert BEFORE INSERT ON tutor_item_supply_private_development_model_accounting_jobs
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_development_accounting_job_insert();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['tutor_item_supply_private_development_model_accounting_jobs','tutor_item_supply_private_development_model_accounting_batches'] LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS supply_epoch ON %I',t);
   EXECUTE format('CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch()',t);
   EXECUTE format('DROP TRIGGER IF EXISTS private_development_accounting_immutable ON %I',t);
   EXECUTE format('CREATE TRIGGER private_development_accounting_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable(''private'')',t);
 END LOOP;
END $$;
DROP TRIGGER IF EXISTS a000_private_development_accounting_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a000_private_development_accounting_epoch_purge BEFORE UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN(NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION item_supply_internal.purge_private_development_accounting_on_epoch_advance();
