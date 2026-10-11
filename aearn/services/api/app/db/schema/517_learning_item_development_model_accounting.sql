-- STAGED/REGISTERED ONLY. Isolated developer model accounting, NOT dispatch authority.
-- Nominal cap=1 satisfies legacy positive CHECKs; no infinity or execution grant.
-- Original 508--516, sources, leases, once, receipts, UNKNOWN and publication holds remain unchanged.
CREATE TABLE IF NOT EXISTS tutor_item_supply_development_model_accounting_batches (
 id uuid PRIMARY KEY,
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 window_id uuid NOT NULL UNIQUE,
 provider_key text NOT NULL CHECK(provider_key='deepseek'),
 model text NOT NULL CHECK(model='deepseek-flash'),
 authorization_key text NOT NULL CHECK(authorization_key='development-unlimited-model-calls-20261010'),
 global_limit_ids uuid[] NOT NULL CHECK(array_ndims(global_limit_ids)=1 AND cardinality(global_limit_ids)=32
   AND array_position(global_limit_ids,NULL) IS NULL),
 started_at timestamptz NOT NULL,
 valid_until timestamptz NOT NULL,
 mode text NOT NULL DEFAULT 'accounting_only' CHECK(mode='accounting_only'),
 cumulative_caps_enforced boolean NOT NULL DEFAULT false CHECK(cumulative_caps_enforced=false),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(valid_until>started_at AND valid_until<=started_at+interval '2 hours'),
 FOREIGN KEY(window_id,root_id) REFERENCES tutor_item_supply_shared_budget_windows(id,root_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_development_model_accounting_jobs (
 job_id uuid PRIMARY KEY REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
 batch_id uuid NOT NULL REFERENCES tutor_item_supply_development_model_accounting_batches(id) ON DELETE RESTRICT,
 parent_job_id uuid REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
 lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
 lease_generation integer NOT NULL CHECK(lease_generation=1),
 lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
 profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
 parent_deadline timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_development_model_accounting_batch_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE root_row tutor_item_supply_shared_budget_roots%ROWTYPE;
 obligation_row tutor_item_supply_shared_obligations%ROWTYPE;
 window_row tutor_item_supply_shared_budget_windows%ROWTYPE;
 limit_row tutor_item_supply_runtime_global_limits%ROWTYPE;
 stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001'
   OR NEW.authorization_key IS DISTINCT FROM 'development-unlimited-model-calls-20261010'
   OR NEW.provider_key IS DISTINCT FROM 'deepseek' OR NEW.model IS DISTINCT FROM 'deepseek-flash'
   OR NEW.mode IS DISTINCT FROM 'accounting_only' OR NEW.cumulative_caps_enforced IS DISTINCT FROM false THEN
   RAISE check_violation USING MESSAGE='isolated explicit development accounting only';
 END IF;
 SELECT * INTO root_row FROM tutor_item_supply_shared_budget_roots rr WHERE rr.id=NEW.root_id;
 SELECT * INTO obligation_row FROM tutor_item_supply_shared_obligations oo WHERE oo.root_id=NEW.root_id;
 SELECT * INTO window_row FROM tutor_item_supply_shared_budget_windows ww WHERE ww.id=NEW.window_id;
 stamp:=clock_timestamp();
 IF root_row.id IS NULL OR obligation_row.id IS NULL OR window_row.id IS NULL
   OR root_row.canonical_key IS DISTINCT FROM obligation_row.canonical_key
   OR obligation_row.obligation_json->>'visibility' IS DISTINCT FROM 'public'
   OR obligation_row.obligation_json->>'owner_id' IS NOT NULL
   OR obligation_row.provider_key IS DISTINCT FROM NEW.provider_key
   OR window_row.root_id IS DISTINCT FROM NEW.root_id OR window_row.pool_key IS DISTINCT FROM obligation_row.pool_class
   OR window_row.provider_key IS DISTINCT FROM NEW.provider_key
   OR window_row.window_start IS DISTINCT FROM NEW.started_at OR window_row.window_end IS DISTINCT FROM NEW.valid_until
   OR window_row.request_cap IS DISTINCT FROM 1 OR window_row.token_cap IS DISTINCT FROM 1 OR window_row.resource_cap IS DISTINCT FROM 1
   OR NEW.started_at>stamp OR NEW.valid_until<=stamp OR NEW.valid_until>NEW.started_at+interval '2 hours'
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_budget_windows wx WHERE wx.id=NEW.window_id
     AND wx.xmin::text::bigint=(txid_current()%4294967296))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rs WHERE rs.window_id=NEW.window_id)
   OR cardinality(NEW.global_limit_ids) IS DISTINCT FROM 32
   OR (SELECT count(DISTINCT gi) FROM unnest(NEW.global_limit_ids) gi)<>32
   OR EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_batches bb WHERE bb.global_limit_ids && NEW.global_limit_ids)
   OR (SELECT count(*) FROM tutor_item_supply_runtime_global_limits gl WHERE gl.id=ANY(NEW.global_limit_ids)
     AND gl.xmin::text::bigint=(txid_current()%4294967296))<>32
   OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ga WHERE ga.limit_id=ANY(NEW.global_limit_ids)) THEN
   RAISE check_violation USING MESSAGE='development batch requires new canonical root-bound ledger rows';
 END IF;
 FOR limit_row IN SELECT * FROM tutor_item_supply_runtime_global_limits gg WHERE gg.id=ANY(NEW.global_limit_ids) LOOP
   IF limit_row.cap_amount IS DISTINCT FROM 1 OR limit_row.window_start IS DISTINCT FROM NEW.started_at
     OR limit_row.window_end IS DISTINCT FROM NEW.valid_until
     OR NOT ((limit_row.dimension_kind IN ('system','window') AND limit_row.dimension_key='item-supply')
       OR (limit_row.dimension_kind='pool' AND limit_row.dimension_key=obligation_row.pool_class)
       OR (limit_row.dimension_kind='provider' AND limit_row.dimension_key=NEW.provider_key))
     OR limit_row.resource_kind NOT IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds') THEN
     RAISE check_violation USING MESSAGE='development exact four-dimension eight-resource closure required';
   END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM (VALUES ('system','item-supply'),('window','item-supply'),
      ('pool',obligation_row.pool_class),('provider',NEW.provider_key)) AS dd(kind,key)
   CROSS JOIN unnest(ARRAY['requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds']) AS kk(resource)
   WHERE NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_limits gx WHERE gx.id=ANY(NEW.global_limit_ids)
     AND gx.dimension_kind=dd.kind AND gx.dimension_key=dd.key AND gx.resource_kind=kk.resource)) THEN
   RAISE check_violation USING MESSAGE='development global resource tuple missing';
 END IF;
 IF clock_timestamp()>=NEW.valid_until THEN RAISE check_violation USING MESSAGE='development batch already expired'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_development_model_accounting_job_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE batch_row tutor_item_supply_development_model_accounting_batches%ROWTYPE;
 job_row tutor_item_supply_shared_jobs%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 profile_row tutor_item_supply_parameter_profiles%ROWTYPE;
 parent_row tutor_item_supply_shared_job_controls%ROWTYPE;
 snapshot jsonb; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='development accounting isolated DB only'; END IF;
 SELECT * INTO batch_row FROM tutor_item_supply_development_model_accounting_batches bd WHERE bd.id=NEW.batch_id FOR SHARE;
 SELECT * INTO job_row FROM tutor_item_supply_shared_jobs jj WHERE jj.id=NEW.job_id;
 SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR UPDATE;
 SELECT * INTO profile_row FROM tutor_item_supply_parameter_profiles pp WHERE pp.id=control_row.profile_id;
 snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 stamp:=clock_timestamp();
 IF batch_row.id IS NULL OR job_row.id IS NULL OR control_row.id IS NULL OR profile_row.id IS NULL
   OR batch_row.authorization_key IS DISTINCT FROM 'development-unlimited-model-calls-20261010'
   OR batch_row.mode IS DISTINCT FROM 'accounting_only' OR batch_row.cumulative_caps_enforced IS DISTINCT FROM false
   OR batch_row.provider_key IS DISTINCT FROM 'deepseek' OR batch_row.model IS DISTINCT FROM 'deepseek-flash'
   OR batch_row.started_at>stamp OR batch_row.valid_until<=stamp
   OR job_row.root_id IS DISTINCT FROM batch_row.root_id OR job_row.parent_job_id IS DISTINCT FROM NEW.parent_job_id
   OR control_row.state IS DISTINCT FROM 'leased' OR control_row.breaker_open IS DISTINCT FROM false
   OR control_row.attempt_count IS DISTINCT FROM 1 OR control_row.lease_generation IS DISTINCT FROM 1
   OR control_row.lease_owner IS DISTINCT FROM NEW.lease_owner OR control_row.lease_generation IS DISTINCT FROM NEW.lease_generation
   OR control_row.state_version::bigint IS DISTINCT FROM NEW.lease_state_version
   OR control_row.lease_expires_at IS NULL OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
   OR NEW.parent_deadline IS DISTINCT FROM control_row.parent_deadline OR NEW.parent_deadline>batch_row.valid_until
   OR snapshot->>'profile_hash' IS DISTINCT FROM NEW.profile_hash OR profile_row.profile_hash IS DISTINCT FROM NEW.profile_hash
   OR snapshot->>'profile_key_hash' IS DISTINCT FROM profile_row.profile_key_hash
   OR (snapshot->>'parent_deadline_at')::timestamptz IS DISTINCT FROM NEW.parent_deadline
   OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM batch_row.provider_key
   OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM batch_row.model
   OR (job_row.created_at<batch_row.started_at AND NOT EXISTS(
     SELECT 1 FROM tutor_item_supply_shared_jobs jx,tutor_item_supply_development_model_accounting_batches bx
     WHERE jx.id=NEW.job_id AND bx.id=NEW.batch_id AND jx.xmin::text=bx.xmin::text))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rs WHERE rs.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_counterexample_preparations cp WHERE cp.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints ck WHERE ck.job_id=NEW.job_id) THEN
   RAISE check_violation USING MESSAGE='development mapping requires original fresh first-claimed unspent public job';
 END IF;
 IF NEW.parent_job_id IS NOT NULL THEN
   SELECT * INTO parent_row FROM tutor_item_supply_shared_job_controls pc WHERE pc.job_id=NEW.parent_job_id FOR SHARE;
   IF parent_row.id IS NULL OR parent_row.state IS DISTINCT FROM 'leased' OR parent_row.lease_expires_at IS NULL
     OR parent_row.lease_expires_at<=clock_timestamp() OR parent_row.parent_deadline<NEW.parent_deadline
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_jobs pm
       JOIN tutor_item_supply_shared_jobs pj ON pj.id=pm.job_id
       WHERE pm.job_id=NEW.parent_job_id AND pm.batch_id=NEW.batch_id AND pj.root_id=batch_row.root_id
         AND pm.lease_generation=parent_row.lease_generation AND pm.lease_owner=parent_row.lease_owner) THEN
     RAISE check_violation USING MESSAGE='development child requires actual current parent of same original batch';
   END IF;
 END IF;
 IF clock_timestamp()>=batch_row.valid_until OR clock_timestamp()>=control_row.lease_expires_at
   OR clock_timestamp()>=NEW.parent_deadline THEN RAISE check_violation USING MESSAGE='development mapping final operation deadline expired'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_development_model_accounting_batch_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_development_model_accounting_job_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS development_model_accounting_batch_insert ON tutor_item_supply_development_model_accounting_batches;
CREATE TRIGGER development_model_accounting_batch_insert BEFORE INSERT ON tutor_item_supply_development_model_accounting_batches
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_development_model_accounting_batch_insert();
DROP TRIGGER IF EXISTS development_model_accounting_job_insert ON tutor_item_supply_development_model_accounting_jobs;
CREATE TRIGGER development_model_accounting_job_insert BEFORE INSERT ON tutor_item_supply_development_model_accounting_jobs
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_development_model_accounting_job_insert();
DROP TRIGGER IF EXISTS development_model_accounting_batch_immutable ON tutor_item_supply_development_model_accounting_batches;
CREATE TRIGGER development_model_accounting_batch_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_development_model_accounting_batches
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable();
DROP TRIGGER IF EXISTS development_model_accounting_job_immutable ON tutor_item_supply_development_model_accounting_jobs;
CREATE TRIGGER development_model_accounting_job_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_development_model_accounting_jobs
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable();

