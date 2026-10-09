-- P3 additive item-supply runtime authority. Caller owns bootstrap transaction.
-- No provider, broker, publication, scoring or Gate wiring is enabled here.

CREATE TABLE IF NOT EXISTS tutor_item_supply_runtime_global_limits (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dimension_kind text NOT NULL CHECK (dimension_kind IN ('system','provider','window','pool')),
  dimension_key text NOT NULL CHECK (dimension_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  resource_kind text NOT NULL CHECK (resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  cap_amount bigint NOT NULL CHECK (cap_amount>0),
  CHECK (window_end>window_start),
  UNIQUE(dimension_kind,dimension_key,resource_kind,window_start),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_runtime_user_limits (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  resource_kind text NOT NULL CHECK (resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  cap_amount bigint NOT NULL CHECK (cap_amount>0),
  CHECK (window_end>window_start),
  UNIQUE(user_id,epoch,resource_kind,window_start),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch)
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_obligations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  canonical_key text NOT NULL UNIQUE CHECK (canonical_key ~ '^[0-9a-f]{64}$'),
  obligation_json jsonb NOT NULL CHECK (jsonb_typeof(obligation_json)='object' AND octet_length(obligation_json::text)<=131072 AND obligation_json->>'schema_version'='coverage_obligation_v1' AND obligation_json->>'visibility'='public' AND obligation_json->>'owner_id' IS NULL),
  runtime_contract_hash text NOT NULL CHECK (runtime_contract_hash ~ '^[0-9a-f]{64}$'),
  pool_class text NOT NULL CHECK (pool_class IN ('base','enhancement')),
  provider_key text NOT NULL CHECK (provider_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_obligations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  root_id uuid NOT NULL,
  canonical_key text NOT NULL CHECK (canonical_key ~ '^[0-9a-f]{64}$'),
  obligation_json jsonb NOT NULL CHECK (jsonb_typeof(obligation_json)='object' AND octet_length(obligation_json::text)<=131072 AND obligation_json->>'schema_version'='coverage_obligation_v1' AND obligation_json->>'visibility'='private'),
  runtime_contract_hash text NOT NULL CHECK (runtime_contract_hash ~ '^[0-9a-f]{64}$'),
  pool_class text NOT NULL CHECK (pool_class IN ('base','enhancement')),
  provider_key text NOT NULL CHECK (provider_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE(user_id,epoch,canonical_key), UNIQUE(root_id,user_id,epoch,scope_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(root_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_budget_roots(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_parameter_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_key_hash text NOT NULL CHECK (profile_key_hash ~ '^[0-9a-f]{64}$'),
  profile_version integer NOT NULL CHECK (profile_version>=1),
  profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('warmup','proposed','canary','stable','frozen','blocked')),
  profile_json jsonb NOT NULL CHECK (jsonb_typeof(profile_json)='object' AND octet_length(profile_json::text)<=131072 AND profile_json->>'schema_version'='execution_parameter_profile_v1'),
  UNIQUE(profile_key_hash,profile_version), UNIQUE(profile_hash),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_job_controls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
  profile_id uuid NOT NULL REFERENCES tutor_item_supply_parameter_profiles(id) ON DELETE RESTRICT,
  state text NOT NULL CHECK (state IN ('queued','leased','generating','validating','reviewing','investigating','revising','simulating','admitting','retry_wait','preparing','blocked','completed','cancelled','superseded')),
  state_version integer NOT NULL DEFAULT 1 CHECK (state_version>=1),
  priority integer NOT NULL CHECK (priority BETWEEN 0 AND 1000),
  aging_seconds integer NOT NULL CHECK (aging_seconds BETWEEN 1 AND 86400),
  available_at timestamptz NOT NULL,
  parent_deadline timestamptz NOT NULL,
  lease_owner text, lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation>=0), lease_expires_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count>=0),
  breaker_open boolean NOT NULL DEFAULT false,
  profile_snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(profile_snapshot_json)='object' AND octet_length(profile_snapshot_json::text)<=131072),
  CHECK ((state='leased' AND lease_owner IS NOT NULL AND lease_generation>0 AND lease_expires_at IS NOT NULL) OR (state<>'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_job_controls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  job_id uuid NOT NULL, profile_id uuid NOT NULL REFERENCES tutor_item_supply_parameter_profiles(id) ON DELETE RESTRICT,
  state text NOT NULL CHECK (state IN ('queued','leased','generating','validating','reviewing','investigating','revising','simulating','admitting','retry_wait','preparing','blocked','completed','cancelled','superseded')),
  state_version integer NOT NULL DEFAULT 1 CHECK(state_version>=1), priority integer NOT NULL CHECK(priority BETWEEN 0 AND 1000),
  aging_seconds integer NOT NULL CHECK(aging_seconds BETWEEN 1 AND 86400), available_at timestamptz NOT NULL, parent_deadline timestamptz NOT NULL,
  lease_owner text, lease_generation integer NOT NULL DEFAULT 0 CHECK(lease_generation>=0), lease_expires_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count>=0), breaker_open boolean NOT NULL DEFAULT false,
  profile_snapshot_json jsonb NOT NULL CHECK(jsonb_typeof(profile_snapshot_json)='object' AND octet_length(profile_snapshot_json::text)<=131072),
  CHECK ((state='leased' AND lease_owner IS NOT NULL AND lease_generation>0 AND lease_expires_at IS NOT NULL) OR (state<>'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)),
  UNIQUE(job_id,user_id,epoch,scope_id), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
  stage text NOT NULL CHECK(stage IN ('generating','validating','reviewing','investigating','revising','simulating','admitting')),
  attempt integer NOT NULL CHECK(attempt>0), status text NOT NULL CHECK(status IN ('completed','failed','blocked')),
  lease_generation integer NOT NULL CHECK(lease_generation>0), receipt_hash text NOT NULL CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
  safe_reason text NOT NULL CHECK(safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'), UNIQUE(job_id,stage,attempt), created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  job_id uuid NOT NULL, stage text NOT NULL CHECK(stage IN ('generating','validating','reviewing','investigating','revising','simulating','admitting')),
  attempt integer NOT NULL CHECK(attempt>0), status text NOT NULL CHECK(status IN ('completed','failed','blocked')),
  lease_generation integer NOT NULL CHECK(lease_generation>0), receipt_hash text NOT NULL CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
  safe_reason text NOT NULL CHECK(safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'), UNIQUE(job_id,stage,attempt),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(id,user_id,epoch), UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_runtime_global_reservation_amounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), reservation_namespace text NOT NULL CHECK(reservation_namespace IN ('shared','private')),
  reservation_id uuid NOT NULL, limit_id uuid NOT NULL REFERENCES tutor_item_supply_runtime_global_limits(id) ON DELETE RESTRICT,
  resource_kind text NOT NULL CHECK(resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  reserved_amount bigint NOT NULL CHECK(reserved_amount>=0), UNIQUE(reservation_namespace,reservation_id,limit_id), created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_runtime_reservation_amounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL, limit_id uuid NOT NULL REFERENCES tutor_item_supply_private_runtime_user_limits(id) ON DELETE RESTRICT,
  resource_kind text NOT NULL CHECK(resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  reserved_amount bigint NOT NULL CHECK(reserved_amount>=0), UNIQUE(reservation_id,limit_id), created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch), UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_runtime_settlements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), reservation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
  sequence integer NOT NULL CHECK(sequence>0), settlement_key text NOT NULL CHECK(settlement_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  usage_state text NOT NULL CHECK(usage_state IN ('known','unknown')), cost_amount numeric CHECK(cost_amount>=0), receipt_hash text CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
  CHECK((usage_state='unknown' AND receipt_hash IS NULL) OR (usage_state='known' AND receipt_hash IS NOT NULL)),
  UNIQUE(reservation_id,sequence), UNIQUE(reservation_id,settlement_key), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_runtime_settlement_amounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), settlement_id uuid NOT NULL REFERENCES tutor_item_supply_shared_runtime_settlements(id) ON DELETE RESTRICT,
  resource_kind text NOT NULL CHECK(resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  actual_amount bigint NOT NULL CHECK(actual_amount>=0), UNIQUE(settlement_id,resource_kind), created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_runtime_settlements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL, sequence integer NOT NULL CHECK(sequence>0), settlement_key text NOT NULL CHECK(settlement_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  usage_state text NOT NULL CHECK(usage_state IN ('known','unknown')), cost_amount numeric CHECK(cost_amount>=0), receipt_hash text CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
  CHECK((usage_state='unknown' AND receipt_hash IS NULL) OR (usage_state='known' AND receipt_hash IS NOT NULL)),
  UNIQUE(reservation_id,sequence), UNIQUE(reservation_id,settlement_key), created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch), UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_runtime_settlement_amounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  settlement_id uuid NOT NULL, resource_kind text NOT NULL CHECK(resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  actual_amount bigint NOT NULL CHECK(actual_amount>=0), UNIQUE(settlement_id,resource_kind), created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch), UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(settlement_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_runtime_settlements(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Anonymous cumulative resource facts survive a confirmed private payload purge.
-- INSERT validates live source facts; there is intentionally no private FK and
-- no owner/epoch/scope/content/hash/client-key/provider-body column or JSON.
CREATE TABLE IF NOT EXISTS tutor_item_supply_runtime_global_usage_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reservation_namespace text NOT NULL CHECK(reservation_namespace IN ('shared','private')),
  reservation_id uuid NOT NULL,
  settlement_id uuid NOT NULL,
  sequence integer NOT NULL CHECK(sequence>0),
  resource_kind text NOT NULL CHECK(resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  usage_state text NOT NULL CHECK(usage_state IN ('known','unknown')),
  actual_amount bigint,
  CHECK((usage_state='known' AND actual_amount IS NOT NULL AND actual_amount>=0) OR (usage_state='unknown' AND actual_amount IS NULL)),
  UNIQUE(reservation_namespace,reservation_id,sequence,resource_kind),
  UNIQUE(settlement_id,resource_kind),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_profile_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), profile_id uuid NOT NULL REFERENCES tutor_item_supply_parameter_profiles(id) ON DELETE RESTRICT,
  observation_key text NOT NULL CHECK(observation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'), observation_json jsonb NOT NULL CHECK(jsonb_typeof(observation_json)='object' AND octet_length(observation_json::text)<=131072),
  UNIQUE(profile_id,observation_key), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_profile_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), profile_id uuid NOT NULL REFERENCES tutor_item_supply_parameter_profiles(id) ON DELETE RESTRICT,
  event_key text NOT NULL CHECK(event_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'), action text NOT NULL CHECK(action IN ('hold','propose','commit','rollback','freeze')),
  event_json jsonb NOT NULL CHECK(jsonb_typeof(event_json)='object' AND octet_length(event_json::text)<=131072), UNIQUE(profile_id,event_key), created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION enforce_item_supply_runtime_private_user_limit() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE active_epoch bigint; active_enabled boolean;
BEGIN
  IF TG_OP='DELETE' THEN
    IF item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE check_violation USING MESSAGE='private runtime deletion requires maintenance capability';
  END IF;
  IF TG_OP='UPDATE' THEN RAISE check_violation USING MESSAGE='immutable runtime limit'; END IF;
  PERFORM 1 FROM users WHERE id=NEW.user_id AND deleted_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='stale supply epoch'; END IF;
  SELECT epoch,enabled INTO active_epoch,active_enabled FROM tutor_item_supply_user_epochs WHERE user_id=NEW.user_id FOR SHARE;
  IF active_epoch IS NULL OR NOT active_enabled OR active_epoch<>NEW.epoch THEN RAISE check_violation USING MESSAGE='stale supply epoch'; END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_runtime_private_user_limit() FROM PUBLIC;

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_runtime_user_limits;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_runtime_user_limits FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_private_user_limit();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'tutor_item_supply_private_obligations','tutor_item_supply_private_job_controls','tutor_item_supply_private_checkpoints',
    'tutor_item_supply_private_runtime_reservation_amounts','tutor_item_supply_private_runtime_settlements','tutor_item_supply_private_runtime_settlement_amounts'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_epoch ON %I', table_name);
    EXECUTE format('CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch()', table_name);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION enforce_item_supply_runtime_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' AND TG_NARGS>0 AND TG_ARGV[0]='private' THEN
    IF item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
  END IF;
  RAISE check_violation USING MESSAGE='immutable item supply runtime fact';
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_runtime_immutable() FROM PUBLIC;

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'tutor_item_supply_runtime_global_limits','tutor_item_supply_shared_obligations','tutor_item_supply_parameter_profiles',
    'tutor_item_supply_shared_checkpoints','tutor_item_supply_runtime_global_reservation_amounts',
    'tutor_item_supply_shared_runtime_settlements','tutor_item_supply_shared_runtime_settlement_amounts',
    'tutor_item_supply_profile_observations','tutor_item_supply_profile_events','tutor_item_supply_runtime_global_usage_facts'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_runtime_immutable ON %I', table_name);
    EXECUTE format('CREATE TRIGGER supply_runtime_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable()', table_name);
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY[
    'tutor_item_supply_private_obligations','tutor_item_supply_private_checkpoints','tutor_item_supply_private_runtime_reservation_amounts',
    'tutor_item_supply_private_runtime_settlements','tutor_item_supply_private_runtime_settlement_amounts'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_runtime_immutable ON %I', table_name);
    EXECUTE format('CREATE TRIGGER supply_runtime_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable(''private'')', table_name);
  END LOOP;
END $$;

-- Complete eight-resource accounting represents unused resources with explicit
-- zero reservations; the unchanged 440 envelope still requires actual work.
DO $$
DECLARE constraint_row record;
BEGIN
  -- Discover the original automatic CHECK names without depending on PG's
  -- identifier truncation; no unrelated cap/identity constraint is removed.
  FOR constraint_row IN SELECT conrelid::regclass AS table_name,conname FROM pg_constraint
    WHERE conrelid IN ('tutor_item_supply_runtime_global_reservation_amounts'::regclass,'tutor_item_supply_private_runtime_reservation_amounts'::regclass)
      AND contype='c' AND pg_get_constraintdef(oid) = 'CHECK ((reserved_amount > 0))'
  LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',constraint_row.table_name,constraint_row.conname);
  END LOOP;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_item_supply_runtime_global_reservation_amounts'::regclass AND conname='supply_runtime_reserved_nonnegative') THEN
    ALTER TABLE tutor_item_supply_runtime_global_reservation_amounts ADD CONSTRAINT supply_runtime_reserved_nonnegative CHECK(reserved_amount>=0);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_item_supply_private_runtime_reservation_amounts'::regclass AND conname='supply_runtime_reserved_nonnegative') THEN
    ALTER TABLE tutor_item_supply_private_runtime_reservation_amounts ADD CONSTRAINT supply_runtime_reserved_nonnegative CHECK(reserved_amount>=0);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_item_supply_runtime_usage_fact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE source_fact record;
BEGIN
  IF NEW.reservation_namespace='shared' THEN
    SELECT s.reservation_id,s.sequence,s.usage_state,a.actual_amount INTO source_fact
      FROM tutor_item_supply_shared_runtime_settlements s
      LEFT JOIN tutor_item_supply_shared_runtime_settlement_amounts a ON a.settlement_id=s.id AND a.resource_kind=NEW.resource_kind
      WHERE s.id=NEW.settlement_id FOR SHARE OF s;
  ELSE
    SELECT s.reservation_id,s.sequence,s.usage_state,a.actual_amount INTO source_fact
      FROM tutor_item_supply_private_runtime_settlements s
      LEFT JOIN tutor_item_supply_private_runtime_settlement_amounts a ON a.settlement_id=s.id AND a.resource_kind=NEW.resource_kind
      WHERE s.id=NEW.settlement_id FOR SHARE OF s;
  END IF;
  IF NOT FOUND OR source_fact.reservation_id IS DISTINCT FROM NEW.reservation_id OR source_fact.sequence IS DISTINCT FROM NEW.sequence
    OR source_fact.usage_state IS DISTINCT FROM NEW.usage_state OR source_fact.actual_amount IS DISTINCT FROM NEW.actual_amount
    OR (NEW.usage_state='known' AND source_fact.actual_amount IS NULL) THEN
    RAISE check_violation USING MESSAGE='anonymous runtime usage source mismatch';
  END IF;
  IF NEW.reservation_namespace='shared' THEN
    PERFORM 1 FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id FOR SHARE;
  ELSE
    PERFORM 1 FROM tutor_item_supply_private_reservations WHERE id=NEW.reservation_id FOR SHARE;
  END IF;
  IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts
      WHERE reservation_namespace=NEW.reservation_namespace AND reservation_id=NEW.reservation_id AND resource_kind=NEW.resource_kind) THEN
    RAISE check_violation USING MESSAGE='anonymous runtime usage reservation mismatch';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_runtime_usage_fact() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_runtime_usage_fact ON tutor_item_supply_runtime_global_usage_facts;
CREATE TRIGGER supply_runtime_usage_fact BEFORE INSERT ON tutor_item_supply_runtime_global_usage_facts
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_usage_fact();

-- Retain existing detailed usage facts when upgrading the additive ledger.
-- Copy only present actual children (including explicit zero) or unknown NULL;
-- absent resource facts never become invented zero usage. Source guards remain
-- active, and no private owner/scope/hash is projected into this shared table.
DO $$
DECLARE namespace text;
BEGIN
  FOREACH namespace IN ARRAY ARRAY['shared','private'] LOOP
    EXECUTE format(
      'INSERT INTO tutor_item_supply_runtime_global_usage_facts(reservation_namespace,reservation_id,settlement_id,sequence,resource_kind,usage_state,actual_amount)
       SELECT %L,s.reservation_id,s.id,s.sequence,allocation.resource_kind,s.usage_state,actual.actual_amount
       FROM %I s JOIN (SELECT DISTINCT reservation_id,resource_kind FROM tutor_item_supply_runtime_global_reservation_amounts WHERE reservation_namespace=%L) allocation ON allocation.reservation_id=s.reservation_id
       LEFT JOIN %I actual ON actual.settlement_id=s.id AND actual.resource_kind=allocation.resource_kind
       WHERE s.usage_state=''unknown'' OR actual.actual_amount IS NOT NULL
       ON CONFLICT DO NOTHING',
      namespace,'tutor_item_supply_'||namespace||'_runtime_settlements',namespace,
      'tutor_item_supply_'||namespace||'_runtime_settlement_amounts');
  END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_supply_shared_runtime_claim ON tutor_item_supply_shared_job_controls(state,available_at,priority,created_at);
CREATE INDEX IF NOT EXISTS idx_supply_private_runtime_claim ON tutor_item_supply_private_job_controls(user_id,epoch,state,available_at,priority,created_at);
CREATE INDEX IF NOT EXISTS idx_supply_global_limit_active ON tutor_item_supply_runtime_global_limits(dimension_kind,dimension_key,resource_kind,window_start,window_end);

-- Extend the accepted maintenance purge without changing schema 440 history.
CREATE OR REPLACE FUNCTION purge_item_supply_private(target_user uuid, deleting boolean DEFAULT false)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE new_epoch bigint;
BEGIN
  PERFORM 1 FROM users WHERE id=target_user AND deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='supply user unavailable'; END IF;
  INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(target_user) ON CONFLICT DO NOTHING;
  INSERT INTO item_supply_internal.reset_permits VALUES(txid_current(),target_user);
  UPDATE tutor_item_supply_user_epochs SET epoch=epoch+1,enabled=NOT deleting,updated_at=now() WHERE user_id=target_user RETURNING epoch INTO new_epoch;
  UPDATE tutor_item_supply_private_job_controls SET state='cancelled',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL WHERE user_id=target_user AND state NOT IN ('completed','cancelled','superseded');
  UPDATE tutor_item_supply_private_jobs SET state='cancelled',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL,terminal_at=now() WHERE user_id=target_user AND state NOT IN ('completed','failed','cancelled');
  UPDATE tutor_item_supply_private_bindings SET state='invalidated',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  UPDATE tutor_item_supply_private_subscriptions SET state='cancelled',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  DELETE FROM tutor_item_supply_private_runtime_settlement_amounts WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_runtime_settlements WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_runtime_reservation_amounts WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_checkpoints WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_job_controls WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_obligations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_runtime_user_limits WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_subscriptions WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_result_items WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_bindings WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_cache WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_results WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_demands WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_publication_refs WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_admissions WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_proofs WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_observations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_evidence WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_usage_events WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_reservations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_job_events WHERE user_id=target_user;
  LOOP
    DELETE FROM tutor_item_supply_private_jobs j WHERE j.user_id=target_user AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_jobs c WHERE c.parent_job_id=j.id);
    EXIT WHEN NOT FOUND;
  END LOOP;
  DELETE FROM tutor_item_supply_private_budget_windows WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_budget_roots WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_staging WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_versions WHERE user_id=target_user;
  LOOP
    DELETE FROM tutor_item_supply_private_candidates c WHERE c.user_id=target_user AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates child WHERE child.parent_candidate_id=c.id);
    EXIT WHEN NOT FOUND;
  END LOOP;
  DELETE FROM tutor_item_supply_private_materials WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_scopes WHERE user_id=target_user;
  DELETE FROM item_supply_internal.reset_permits WHERE transaction_id=txid_current() AND user_id=target_user;
  RETURN new_epoch;
END $$;
REVOKE ALL ON FUNCTION purge_item_supply_private(uuid,boolean) FROM PUBLIC;

-- Guarded constraints upgrade an already loaded 450 without touching 440.
DO $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_item_supply_private_runtime_user_limits'::regclass AND conname='supply_runtime_limit_owner_resource') THEN
    ALTER TABLE tutor_item_supply_private_runtime_user_limits ADD CONSTRAINT supply_runtime_limit_owner_resource UNIQUE(id,user_id,epoch,resource_kind);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_item_supply_private_runtime_reservation_amounts'::regclass AND conname='supply_runtime_allocation_owner_resource') THEN
    ALTER TABLE tutor_item_supply_private_runtime_reservation_amounts ADD CONSTRAINT supply_runtime_allocation_owner_resource
      FOREIGN KEY(limit_id,user_id,epoch,resource_kind) REFERENCES tutor_item_supply_private_runtime_user_limits(id,user_id,epoch,resource_kind) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_item_supply_shared_runtime_settlements'::regclass AND conname='supply_runtime_unknown_cost') THEN
    ALTER TABLE tutor_item_supply_shared_runtime_settlements ADD CONSTRAINT supply_runtime_unknown_cost CHECK(usage_state<>'unknown' OR cost_amount IS NULL);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_item_supply_private_runtime_settlements'::regclass AND conname='supply_runtime_unknown_cost') THEN
    ALTER TABLE tutor_item_supply_private_runtime_settlements ADD CONSTRAINT supply_runtime_unknown_cost CHECK(usage_state<>'unknown' OR cost_amount IS NULL);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.runtime_values(value jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='object' THEN
    item_supply_internal.snapshot_keys(value, ARRAY['connection_timeout_ms','first_token_timeout_ms','stream_idle_timeout_ms','request_timeout_ms','stage_deadline_ms','parent_deadline_ms','discussion_rounds','revision_rounds','investigation_rounds'])
    AND CASE WHEN NOT EXISTS(
      SELECT 1 FROM jsonb_each(value) e WHERE jsonb_typeof(e.value)<>'number' OR e.value::text !~ '^[1-9][0-9]*$') THEN
      NOT EXISTS(SELECT 1 FROM jsonb_each(value) e WHERE e.value::numeric > CASE
        WHEN e.key IN ('connection_timeout_ms','first_token_timeout_ms','stream_idle_timeout_ms','request_timeout_ms') THEN 86400000
        WHEN e.key='stage_deadline_ms' THEN 604800000
        WHEN e.key='parent_deadline_ms' THEN 2592000000
        ELSE 64 END)
      AND (value->>'connection_timeout_ms')::numeric <= (value->>'request_timeout_ms')::numeric
      AND (value->>'first_token_timeout_ms')::numeric <= (value->>'request_timeout_ms')::numeric
      AND (value->>'stream_idle_timeout_ms')::numeric <= (value->>'request_timeout_ms')::numeric
      AND (value->>'request_timeout_ms')::numeric <= (value->>'stage_deadline_ms')::numeric
      AND (value->>'stage_deadline_ms')::numeric <= (value->>'parent_deadline_ms')::numeric
    ELSE false END
  ELSE false END
$$;

CREATE OR REPLACE FUNCTION item_supply_internal.runtime_snapshot_keys(value jsonb, required text[], optional text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='object' THEN value ?& required AND NOT EXISTS(
    SELECT 1 FROM jsonb_object_keys(value) k WHERE NOT k=ANY(required || optional)) ELSE false END
$$;

CREATE OR REPLACE FUNCTION enforce_item_supply_runtime_snapshot() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE snapshot jsonb; profile record; authority record; field_name text; parameter_name text;
BEGIN
  IF TG_TABLE_NAME IN ('tutor_item_supply_shared_obligations','tutor_item_supply_private_obligations') THEN
    snapshot := NEW.obligation_json;
    IF NOT item_supply_internal.snapshot_keys(snapshot, ARRAY['schema_version','blueprint_hash','scope_hash','objective_hash','purpose','runtime_contract_hash','visibility','policy_version','owner_id'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY[]::text[])
      OR NEW.canonical_key IS DISTINCT FROM item_supply_internal.snapshot_hash(snapshot)
      OR NEW.runtime_contract_hash IS DISTINCT FROM snapshot->>'runtime_contract_hash' THEN
      RAISE check_violation USING MESSAGE='invalid runtime obligation snapshot';
    END IF;
    IF TG_TABLE_NAME='tutor_item_supply_shared_obligations' THEN
      SELECT r.canonical_key,r.policy_class,b.blueprint_hash,item_supply_internal.snapshot_hash(b.snapshot_json->'scope') AS scope_hash,b.objective_hash,b.policy_version,b.snapshot_json->'scope'->>'purpose' AS purpose,b.snapshot_json->'scope' AS scope_json
        INTO authority FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id WHERE r.id=NEW.root_id;
      IF NOT FOUND OR authority.canonical_key IS DISTINCT FROM NEW.canonical_key OR authority.policy_class NOT IN (NEW.pool_class,snapshot->>'policy_version')
        OR snapshot->>'blueprint_hash' IS DISTINCT FROM authority.blueprint_hash OR snapshot->>'scope_hash' IS DISTINCT FROM authority.scope_hash
        OR snapshot->>'objective_hash' IS DISTINCT FROM authority.objective_hash OR snapshot->>'policy_version' IS DISTINCT FROM authority.policy_version
        OR snapshot->>'purpose' IS DISTINCT FROM authority.purpose OR snapshot->'owner_id' IS DISTINCT FROM 'null'::jsonb THEN
        RAISE check_violation USING MESSAGE='shared runtime obligation binding mismatch';
      END IF;
    ELSE
      SELECT r.canonical_key,r.policy_class,s.scope_hash,s.objective_hash,s.snapshot_json->>'purpose' AS purpose,s.snapshot_json AS scope_json
        INTO authority FROM tutor_item_supply_private_budget_roots r JOIN tutor_item_supply_private_scopes s ON s.id=r.scope_id AND s.user_id=r.user_id AND s.epoch=r.epoch
        WHERE r.id=NEW.root_id AND r.user_id=NEW.user_id AND r.epoch=NEW.epoch AND r.scope_id=NEW.scope_id;
      IF NOT FOUND OR authority.canonical_key IS DISTINCT FROM NEW.canonical_key OR authority.policy_class NOT IN (NEW.pool_class,snapshot->>'policy_version')
        OR snapshot->>'owner_id' IS DISTINCT FROM NEW.user_id::text OR snapshot->>'scope_hash' IS DISTINCT FROM authority.scope_hash
        OR snapshot->>'objective_hash' IS DISTINCT FROM authority.objective_hash OR snapshot->>'purpose' IS DISTINCT FROM authority.purpose THEN
        RAISE check_violation USING MESSAGE='private runtime obligation binding mismatch';
      END IF;
    END IF;
    IF NEW.runtime_contract_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'runtime_profile_id',authority.scope_json->'runtime_profile_id','runtime_profile_hash',authority.scope_json->'runtime_profile_hash',
      'required_capabilities',authority.scope_json->'required_capabilities','assessment_contract_version',authority.scope_json->'assessment_contract_version',
      'scorer_version',authority.scope_json->'scorer_version','assistance_policy_hash',authority.scope_json->'assistance_policy_hash')) THEN
      RAISE check_violation USING MESSAGE='runtime contract authority mismatch';
    END IF;
  ELSIF TG_TABLE_NAME='tutor_item_supply_parameter_profiles' THEN
    snapshot := NEW.profile_json;
    IF NOT item_supply_internal.runtime_snapshot_keys(snapshot, ARRAY['schema_version','profile_key','version','state','initial','current','last_stable','floor','ceiling','measurement_window_started_at','measurement_window_ended_at','change_reason','trusted_initial_evidence','cooldown_until','parent_version'], ARRAY['rollback_count'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY['profile_key','initial','current','last_stable','floor','ceiling','trusted_initial_evidence'])
      OR NOT item_supply_internal.runtime_snapshot_keys(snapshot->'profile_key', ARRAY['provider','model_version','agent_role','item_kind','risk_tier','difficulty','input_size_bucket','runtime'], ARRAY['provider_version','prompt_version','validator_version','output_size_bucket','load_bucket','complexity_version'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot->'profile_key', ARRAY[]::text[])
      OR NOT item_supply_internal.snapshot_strings(snapshot->'trusted_initial_evidence')
      OR NEW.profile_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(snapshot)
      OR NEW.profile_key_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(snapshot->'profile_key')
      OR snapshot->>'schema_version' IS DISTINCT FROM 'execution_parameter_profile_v1'
      OR snapshot->'version' IS DISTINCT FROM to_jsonb(NEW.profile_version) OR snapshot->>'state' IS DISTINCT FROM NEW.state THEN
      RAISE check_violation USING MESSAGE='invalid runtime profile snapshot';
    END IF;
    FOREACH field_name IN ARRAY ARRAY['initial','current','last_stable','floor','ceiling'] LOOP
      IF NOT item_supply_internal.runtime_values(snapshot->field_name) THEN RAISE check_violation USING MESSAGE='invalid runtime profile parameters'; END IF;
    END LOOP;
    FOR parameter_name IN SELECT jsonb_object_keys(snapshot->'floor') LOOP
      FOREACH field_name IN ARRAY ARRAY['initial','current','last_stable'] LOOP
        IF (snapshot->field_name->>parameter_name)::bigint < (snapshot->'floor'->>parameter_name)::bigint
          OR (snapshot->field_name->>parameter_name)::bigint > (snapshot->'ceiling'->>parameter_name)::bigint THEN
          RAISE check_violation USING MESSAGE='runtime profile value outside bounds';
        END IF;
      END LOOP;
    END LOOP;
    IF jsonb_array_length(snapshot->'trusted_initial_evidence') NOT BETWEEN 1 AND 16
      OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(snapshot->'trusted_initial_evidence') e
        WHERE e !~ '^[a-z0-9][a-z0-9._:-]{0,159}$')
      OR (SELECT count(*) FROM jsonb_array_elements_text(snapshot->'trusted_initial_evidence'))
        <> (SELECT count(DISTINCT e) FROM jsonb_array_elements_text(snapshot->'trusted_initial_evidence') e) THEN
      RAISE check_violation USING MESSAGE='invalid runtime initial evidence references';
    END IF;
  ELSIF TG_TABLE_NAME='tutor_item_supply_profile_observations' THEN
    snapshot := NEW.observation_json;
    SELECT * INTO profile FROM tutor_item_supply_parameter_profiles WHERE id=NEW.profile_id;
    IF NOT item_supply_internal.runtime_snapshot_keys(snapshot, ARRAY['schema_version','profile_key_hash','profile_version','provider_version','model_version','runtime_version','load_bucket','mode','completed','right_censored','quality_score','coverage_score','baseline_quality_score','baseline_coverage_score','scorer_blocked','safety_blocked','values_used','actual_request_ms','actual_stage_ms','actual_discussion_rounds','actual_revision_rounds','actual_investigation_rounds','observed_at'], ARRAY['observation_key','prompt_version','validator_version','output_size_bucket','complexity_version','comparison_key','termination','timeout_parameter','qualified_yield_score','first_review_passed','final_review_passed','unresolved_issues','retry_count','usage_tokens','actual_connection_ms','actual_first_token_ms','actual_stream_idle_ms','actual_parent_ms','discussion_tail_contributions','revision_tail_contributions','investigation_tail_contributions'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY['values_used','discussion_tail_contributions','revision_tail_contributions','investigation_tail_contributions']) OR NOT item_supply_internal.runtime_values(snapshot->'values_used')
      OR snapshot->>'schema_version' IS DISTINCT FROM 'parameter_calibration_observation_v1'
      OR snapshot->>'profile_key_hash' IS DISTINCT FROM profile.profile_key_hash OR snapshot->'profile_version' IS DISTINCT FROM to_jsonb(profile.profile_version) THEN
      RAISE check_violation USING MESSAGE='invalid runtime profile observation';
    END IF;
    FOREACH field_name IN ARRAY ARRAY['discussion_tail_contributions','revision_tail_contributions','investigation_tail_contributions'] LOOP
      IF snapshot ? field_name THEN
        IF jsonb_typeof(snapshot->field_name) IS DISTINCT FROM 'array' THEN RAISE check_violation USING MESSAGE='invalid runtime contribution array'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->field_name) e WHERE jsonb_typeof(e)<>'number') THEN RAISE check_violation USING MESSAGE='invalid runtime contribution value'; END IF;
      END IF;
    END LOOP;
  ELSE
    snapshot := NEW.event_json;
    IF NOT item_supply_internal.runtime_snapshot_keys(snapshot, ARRAY['action','reason','parameter','proposed','next_state','cooldown_until'], ARRAY['source_profile_hash','policy_hash','evaluated_at','rollback_count'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY['proposed'])
      OR snapshot->>'action' IS DISTINCT FROM NEW.action
      OR COALESCE(snapshot->>'reason','') !~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
      OR (snapshot->'proposed' IS DISTINCT FROM 'null'::jsonb AND NOT item_supply_internal.runtime_values(snapshot->'proposed')) THEN
      RAISE check_violation USING MESSAGE='invalid runtime profile event';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_runtime_snapshot() FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_runtime_control() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE profile record; namespace_private boolean := TG_TABLE_NAME='tutor_item_supply_private_job_controls'; completed_count integer;
  snapshot jsonb; envelope jsonb; deadline_cap timestamptz; ancestor_deadline timestamptz; expected_values jsonb;
BEGIN
  IF TG_OP='DELETE' THEN
    IF namespace_private THEN
      IF item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
    END IF;
    RAISE check_violation USING MESSAGE='runtime control deletion denied';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (to_jsonb(NEW)-ARRAY['state','state_version','available_at','lease_owner','lease_generation','lease_expires_at','attempt_count','breaker_open','updated_at'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','state_version','available_at','lease_owner','lease_generation','lease_expires_at','attempt_count','breaker_open','updated_at']) THEN
      RAISE check_violation USING MESSAGE='runtime control identity and profile are frozen';
    END IF;
    IF OLD.state IN ('completed','cancelled','superseded') AND NEW.state IS DISTINCT FROM OLD.state THEN RAISE check_violation USING MESSAGE='terminal runtime control cannot restart'; END IF;
    IF NEW.state_version NOT IN (OLD.state_version,OLD.state_version+1) OR NEW.lease_generation NOT IN (OLD.lease_generation,OLD.lease_generation+1)
      OR NEW.attempt_count NOT IN (OLD.attempt_count,OLD.attempt_count+1)
      OR (NEW.state IS DISTINCT FROM OLD.state AND NEW.state_version<>OLD.state_version+1) THEN RAISE check_violation USING MESSAGE='invalid runtime control generation'; END IF;
    IF NEW.lease_generation=OLD.lease_generation+1 THEN
      IF NEW.state<>'leased' OR NEW.state_version<>OLD.state_version+1 OR NEW.attempt_count<>OLD.attempt_count+1
        OR OLD.state IN ('completed','cancelled','superseded') OR (OLD.state='leased' AND OLD.lease_expires_at>clock_timestamp()) THEN
        RAISE check_violation USING MESSAGE='invalid runtime lease claim';
      END IF;
    ELSIF (NEW.state='leased' AND OLD.state<>'leased') OR (NEW.lease_owner IS DISTINCT FROM OLD.lease_owner AND NEW.lease_owner IS NOT NULL)
      OR NEW.attempt_count<>OLD.attempt_count THEN RAISE check_violation USING MESSAGE='runtime lease generation required'; END IF;
    IF OLD.state='leased' AND NEW.state='leased' AND NEW.lease_generation=OLD.lease_generation
      AND NEW.lease_expires_at>OLD.lease_expires_at AND OLD.lease_expires_at<=clock_timestamp() THEN
      RAISE check_violation USING MESSAGE='expired runtime lease cannot be renewed';
    END IF;
  ELSE
    IF NEW.state NOT IN ('queued','preparing') OR NEW.state_version<>1 OR NEW.lease_generation<>0 OR NEW.attempt_count<>0 OR NEW.breaker_open THEN
      RAISE check_violation USING MESSAGE='runtime control must start queued or preparing';
    END IF;
  END IF;
  SELECT * INTO profile FROM tutor_item_supply_parameter_profiles WHERE id=NEW.profile_id;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='runtime control profile unavailable'; END IF;
  envelope := NEW.profile_snapshot_json;
  IF envelope->>'schema_version'='item_supply_job_snapshot_v1' THEN
    IF NOT item_supply_internal.snapshot_keys(envelope, ARRAY['schema_version','profile','retry_policy'])
      OR NOT item_supply_internal.snapshot_scalars(envelope, ARRAY['profile','retry_policy']) THEN RAISE check_violation USING MESSAGE='invalid runtime job snapshot'; END IF;
    IF envelope->'retry_policy' IS DISTINCT FROM 'null'::jsonb THEN
      IF NOT item_supply_internal.snapshot_keys(envelope->'retry_policy', ARRAY['schema_version','max_transient_attempts','initial_backoff_ms','maximum_backoff_ms'])
        OR NOT item_supply_internal.snapshot_scalars(envelope->'retry_policy', ARRAY[]::text[])
        OR envelope->'retry_policy'->>'schema_version' IS DISTINCT FROM 'item_supply_retry_policy_v1' THEN
        RAISE check_violation USING MESSAGE='invalid runtime retry snapshot';
      END IF;
    ELSIF TG_OP='INSERT' AND NEW.state<>'preparing' THEN RAISE check_violation USING MESSAGE='missing runtime retry configuration'; END IF;
    snapshot := envelope->'profile';
  ELSE snapshot := envelope;
  END IF;
  expected_values := CASE WHEN profile.state='frozen' THEN profile.profile_json->'last_stable' ELSE profile.profile_json->'current' END;
  IF NOT item_supply_internal.runtime_snapshot_keys(snapshot, ARRAY['profile_key_hash','profile_version','profile_hash','values','bound_at'], ARRAY['parent_deadline_at'])
    OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY['values'])
    OR snapshot->>'profile_hash' IS DISTINCT FROM profile.profile_hash
    OR snapshot->>'profile_key_hash' IS DISTINCT FROM profile.profile_key_hash
    OR snapshot->'profile_version' IS DISTINCT FROM to_jsonb(profile.profile_version)
    OR snapshot->'values' IS DISTINCT FROM expected_values
    OR NEW.lease_expires_at>NEW.parent_deadline THEN RAISE check_violation USING MESSAGE='runtime control profile binding mismatch'; END IF;
  deadline_cap := (snapshot->>'bound_at')::timestamptz + (expected_values->>'parent_deadline_ms')::bigint * interval '1 millisecond';
  IF snapshot ? 'parent_deadline_at' THEN
    IF (snapshot->>'parent_deadline_at')::timestamptz>deadline_cap THEN RAISE check_violation USING MESSAGE='runtime snapshot deadline exceeds profile'; END IF;
    deadline_cap := (snapshot->>'parent_deadline_at')::timestamptz;
  END IF;
  IF namespace_private THEN
    SELECT c.parent_deadline INTO ancestor_deadline FROM tutor_item_supply_private_jobs j JOIN tutor_item_supply_private_job_controls c ON c.job_id=j.parent_job_id WHERE j.id=NEW.job_id;
  ELSE
    SELECT c.parent_deadline INTO ancestor_deadline FROM tutor_item_supply_shared_jobs j JOIN tutor_item_supply_shared_job_controls c ON c.job_id=j.parent_job_id WHERE j.id=NEW.job_id;
  END IF;
  IF NEW.parent_deadline IS DISTINCT FROM LEAST(deadline_cap,ancestor_deadline) OR NEW.parent_deadline<=(snapshot->>'bound_at')::timestamptz THEN
    RAISE check_violation USING MESSAGE='runtime ancestor deadline binding mismatch';
  END IF;
  IF namespace_private THEN
    PERFORM 1 FROM tutor_item_supply_private_jobs j JOIN tutor_item_supply_private_obligations o
      ON o.root_id=j.root_id AND o.user_id=j.user_id AND o.epoch=j.epoch AND o.scope_id=j.scope_id
      WHERE j.id=NEW.job_id AND j.user_id=NEW.user_id AND j.epoch=NEW.epoch AND j.scope_id=NEW.scope_id;
  ELSE
    PERFORM 1 FROM tutor_item_supply_shared_jobs j JOIN tutor_item_supply_shared_obligations o ON o.root_id=j.root_id WHERE j.id=NEW.job_id;
  END IF;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='runtime control obligation unavailable'; END IF;
  IF NEW.state='completed' THEN
    IF namespace_private THEN
      SELECT count(DISTINCT stage) INTO completed_count FROM tutor_item_supply_private_checkpoints WHERE job_id=NEW.job_id AND status='completed';
    ELSE
      SELECT count(DISTINCT stage) INTO completed_count FROM tutor_item_supply_shared_checkpoints WHERE job_id=NEW.job_id AND status='completed';
    END IF;
    IF completed_count<>7 OR OLD.state<>'leased' OR OLD.lease_expires_at<=clock_timestamp() THEN
      RAISE check_violation USING MESSAGE='runtime completion requires live complete checkpoints';
    END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_runtime_control() FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_runtime_checkpoint() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE control record;
BEGIN
  IF TG_TABLE_NAME='tutor_item_supply_shared_checkpoints' THEN
    SELECT * INTO control FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.job_id FOR UPDATE;
  ELSE
    SELECT * INTO control FROM tutor_item_supply_private_job_controls WHERE job_id=NEW.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
  END IF;
  IF NOT FOUND OR control.state<>'leased' OR control.lease_generation<>NEW.lease_generation
    OR control.lease_expires_at<=clock_timestamp() OR control.parent_deadline<=clock_timestamp() THEN RAISE check_violation USING MESSAGE='runtime checkpoint lease stale'; END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_runtime_checkpoint() FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_runtime_amount() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE parent_state text; limit_resource text;
BEGIN
  IF TG_TABLE_NAME='tutor_item_supply_runtime_global_reservation_amounts' THEN
    SELECT resource_kind INTO limit_resource FROM tutor_item_supply_runtime_global_limits WHERE id=NEW.limit_id;
    IF limit_resource IS DISTINCT FROM NEW.resource_kind THEN RAISE check_violation USING MESSAGE='runtime resource binding mismatch'; END IF;
    IF NEW.reservation_namespace='shared' THEN PERFORM 1 FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id FOR SHARE;
    ELSE PERFORM 1 FROM tutor_item_supply_private_reservations WHERE id=NEW.reservation_id FOR SHARE; END IF;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='runtime reservation unavailable'; END IF;
  ELSE
    IF TG_TABLE_NAME='tutor_item_supply_shared_runtime_settlement_amounts' THEN
      SELECT usage_state INTO parent_state FROM tutor_item_supply_shared_runtime_settlements WHERE id=NEW.settlement_id FOR SHARE;
    ELSE
      SELECT usage_state INTO parent_state FROM tutor_item_supply_private_runtime_settlements WHERE id=NEW.settlement_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR SHARE;
    END IF;
    IF parent_state IS DISTINCT FROM 'known' THEN RAISE check_violation USING MESSAGE='unknown usage cannot have actual amounts'; END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_runtime_amount() FROM PUBLIC;

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_obligations','tutor_item_supply_private_obligations','tutor_item_supply_parameter_profiles','tutor_item_supply_profile_observations','tutor_item_supply_profile_events'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_runtime_snapshot ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_runtime_snapshot BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_snapshot()',table_name);
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_job_controls','tutor_item_supply_private_job_controls'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_runtime_control ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_runtime_control BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_control()',table_name);
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_checkpoints','tutor_item_supply_private_checkpoints'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_runtime_checkpoint ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_runtime_checkpoint BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_checkpoint()',table_name);
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_runtime_global_reservation_amounts','tutor_item_supply_shared_runtime_settlement_amounts','tutor_item_supply_private_runtime_settlement_amounts'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_runtime_amount ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_runtime_amount BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_amount()',table_name);
  END LOOP;
END $$;
