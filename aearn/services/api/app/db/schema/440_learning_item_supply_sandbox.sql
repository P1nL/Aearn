-- P2-only item supply persistence. Caller owns the complete bootstrap transaction.
-- No runtime claim/controller, publication mutation, official score or IO.
CREATE SCHEMA IF NOT EXISTS item_supply_internal;
REVOKE ALL ON SCHEMA item_supply_internal FROM PUBLIC;
CREATE TABLE IF NOT EXISTS item_supply_internal.reset_permits (
  transaction_id bigint NOT NULL, user_id uuid NOT NULL,
  PRIMARY KEY (transaction_id,user_id)
);
REVOKE ALL ON item_supply_internal.reset_permits FROM PUBLIC;
CREATE TABLE IF NOT EXISTS tutor_item_supply_user_epochs (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL DEFAULT 1 CHECK (epoch>=1),
  enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_item_supply_teaching_session_owner') THEN
    ALTER TABLE tutor_teaching_sessions ADD CONSTRAINT uq_item_supply_teaching_session_owner UNIQUE(id,user_id);
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_item_supply_shared_version_hash') THEN
    ALTER TABLE tutor_learning_item_versions ADD CONSTRAINT uq_item_supply_shared_version_hash UNIQUE(id,content_hash);
  END IF;
END $$;

-- shared/matrices
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_matrices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  matrix_hash text NOT NULL CHECK (matrix_hash ~ '^[0-9a-f]{64}$'),
  snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=262144 AND (snapshot_json->>'version') IS NOT DISTINCT FROM 'item_supply_support_matrix_v1'),
  UNIQUE (matrix_hash),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id)
);

-- shared/policies
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_version text NOT NULL UNIQUE CHECK (policy_version='autonomous_evidence_policy_v2'),
  policy_hash text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
  policy_json jsonb NOT NULL CHECK (jsonb_typeof(policy_json)='object' AND octet_length(policy_json::text)<=262144 AND (policy_json->>'schema_version') IS NOT DISTINCT FROM 'autonomous_evidence_policy_v2'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id)
);

-- shared/blueprints
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_blueprints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  blueprint_hash text NOT NULL CHECK (blueprint_hash ~ '^[0-9a-f]{64}$'),
  objective_hash text NOT NULL CHECK (objective_hash ~ '^[0-9a-f]{64}$'),
  matrix_hash text NOT NULL CHECK (matrix_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL REFERENCES tutor_item_supply_shared_policies(policy_version),
  snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=262144 AND (snapshot_json->>'schema_version') IS NOT DISTINCT FROM 'coverage_blueprint_v1'),
  CONSTRAINT chk_item_supply_shared_blueprint_namespace CHECK ((snapshot_json->'scope'->>'visibility') IS NOT DISTINCT FROM 'public' AND snapshot_json->'scope'->>'owner_ref' IS NULL),
  UNIQUE (blueprint_hash),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (matrix_hash) REFERENCES tutor_item_supply_shared_matrices(matrix_hash) ON DELETE RESTRICT
);

-- shared/slots
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  blueprint_id uuid NOT NULL,
  clause_id text NOT NULL CHECK (clause_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  clause_hash text NOT NULL CHECK (clause_hash ~ '^[0-9a-f]{64}$'),
  slot text NOT NULL CHECK (slot IN ('practice','assessment','remediation')),
  required_count integer NOT NULL CHECK (required_count BETWEEN 1 AND 16),
  UNIQUE (blueprint_id,clause_id,slot),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (blueprint_id) REFERENCES tutor_item_supply_shared_blueprints(id) ON DELETE RESTRICT
);

-- private/scopes
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_scopes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  track_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  scope_hash text NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
  objective_hash text NOT NULL CHECK (objective_hash ~ '^[0-9a-f]{64}$'),
  snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=262144 AND (snapshot_json->>'schema_version') IS NOT DISTINCT FROM 'supply_scope_v1'),
  CONSTRAINT chk_item_supply_private_scope_namespace CHECK ((snapshot_json->>'visibility') IS NOT DISTINCT FROM 'private' AND (snapshot_json->>'owner_ref') IS NOT DISTINCT FROM ('user:'||user_id::text)),
  CONSTRAINT uq_item_supply_private_scope_contract UNIQUE (id,user_id,epoch,scope_hash,objective_hash),
  UNIQUE (user_id,epoch,scope_hash),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  FOREIGN KEY (revision_id,track_id,user_id,knowledge_key) REFERENCES tutor_track_plan_nodes(revision_id,track_id,user_id,knowledge_key) ON DELETE RESTRICT
);

-- private/materials
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_materials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  material_key text NOT NULL CHECK (material_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  content_text text NOT NULL CHECK (octet_length(content_text)<=262144),
  payload_hash text GENERATED ALWAYS AS (encode(digest((content_text)::text,'sha256'),'hex')) STORED,
  source_subject text,
  source_corpus uuid,
  source_document uuid,
  source_chunk uuid,
  source_receipt uuid,
  CHECK (num_nonnulls(source_subject,source_corpus,source_document,source_chunk,source_receipt) IN (0,5)),
  UNIQUE (user_id,epoch,material_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT
);

-- private/candidates
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  material_id uuid,
  candidate_key text NOT NULL CHECK (candidate_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  parent_candidate_id uuid,
  CHECK (parent_candidate_id IS NULL OR parent_candidate_id<>id),
  UNIQUE (user_id,epoch,candidate_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY (material_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_materials(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (parent_candidate_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_candidates(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/versions
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  version integer NOT NULL CHECK (version>=1),
  handle text NOT NULL UNIQUE DEFAULT ('lip:v2:'||gen_random_uuid()::text) CHECK (handle ~ '^lip:v2:[0-9a-f-]{36}$'),
  public_json jsonb NOT NULL CHECK (jsonb_typeof(public_json)='object' AND octet_length(public_json::text)<=262144 AND (public_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_public_v1'),
  private_json jsonb NOT NULL CHECK (jsonb_typeof(private_json)='object' AND octet_length(private_json::text)<=262144 AND (private_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_private_v1'),
  payload_hash text GENERATED ALWAYS AS (encode(digest((public_json::text || private_json::text)::text,'sha256'),'hex')) STORED,
  UNIQUE (candidate_id,version),
  UNIQUE (id,user_id,epoch,payload_hash),
  UNIQUE (id,user_id,epoch,payload_hash,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (candidate_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_candidates(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- shared/budget_roots
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_budget_roots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  blueprint_id uuid NOT NULL,
  canonical_key text NOT NULL CHECK (canonical_key ~ '^[0-9a-f]{64}$'),
  policy_class text NOT NULL CHECK (policy_class ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (canonical_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (blueprint_id) REFERENCES tutor_item_supply_shared_blueprints(id) ON DELETE RESTRICT
);

-- shared/budget_windows
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_budget_windows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id uuid NOT NULL,
  pool_key text NOT NULL CHECK (pool_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  provider_key text NOT NULL CHECK (provider_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  request_cap integer NOT NULL CHECK (request_cap>0),
  token_cap bigint NOT NULL CHECK (token_cap>0),
  resource_cap bigint NOT NULL CHECK (resource_cap>0),
  CHECK (window_end>window_start),
  UNIQUE (root_id,pool_key,provider_key,window_start),
  UNIQUE (id,root_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (root_id) REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT
);

-- shared/jobs
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id uuid NOT NULL,
  parent_job_id uuid,
  job_key text NOT NULL CHECK (job_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','claimed','running','completed','failed','cancelled')),
  state_version integer NOT NULL DEFAULT 1 CHECK (state_version>=1),
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation>=0),
  lease_owner text,
  lease_expires_at timestamptz,
  terminal_at timestamptz,
  CHECK (parent_job_id IS NULL OR parent_job_id<>id),
  CHECK ((state IN ('claimed','running') AND lease_generation>0 AND lease_owner IS NOT NULL AND length(lease_owner) BETWEEN 1 AND 160 AND lease_expires_at IS NOT NULL) OR (state NOT IN ('claimed','running') AND lease_owner IS NULL AND lease_expires_at IS NULL)),
  CHECK ((state IN ('completed','failed','cancelled')) = (terminal_at IS NOT NULL)),
  UNIQUE (root_id,job_key),
  UNIQUE (id,root_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (root_id) REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  FOREIGN KEY (parent_job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

-- shared/job_events
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_job_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL,
  event_key text NOT NULL CHECK (event_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  event_kind text NOT NULL CHECK (event_kind ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lease_generation integer NOT NULL CHECK (lease_generation>=0),
  state_version integer NOT NULL CHECK (state_version>=1),
  safe_reason text NOT NULL CHECK (safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (job_id,event_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (job_id) REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT
);

-- shared/reservations
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id uuid NOT NULL,
  window_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation>0),
  reservation_key text NOT NULL CHECK (reservation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  requests integer NOT NULL CHECK (requests>0),
  tokens bigint NOT NULL CHECK (tokens>0),
  resources bigint NOT NULL CHECK (resources>=0),
  UNIQUE (job_id,reservation_key),
  UNIQUE (id,job_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (window_id,root_id) REFERENCES tutor_item_supply_shared_budget_windows(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY (job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

-- shared/usage_events
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_usage_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reservation_id uuid NOT NULL,
  job_id uuid NOT NULL,
  settlement_key text NOT NULL CHECK (settlement_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  usage_state text NOT NULL CHECK (usage_state IN ('known','unknown')),
  input_tokens bigint CHECK (input_tokens>=0),
  output_tokens bigint CHECK (output_tokens>=0),
  resource_units bigint CHECK (resource_units>=0),
  cost_amount numeric CHECK (cost_amount>=0),
  CHECK ((usage_state='unknown' AND input_tokens IS NULL AND output_tokens IS NULL AND resource_units IS NULL AND cost_amount IS NULL) OR (usage_state='known' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND resource_units IS NOT NULL)),
  UNIQUE (reservation_id,settlement_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);

-- shared/evidence
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL,
  version_id uuid NOT NULL,
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version='item_supply_evidence_v2'),
  policy_version text NOT NULL REFERENCES tutor_item_supply_shared_policies(policy_version),
  evidence_key text NOT NULL CHECK (evidence_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  producer_identity text NOT NULL CHECK (producer_identity ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  source_subject text,
  source_corpus uuid,
  source_document uuid,
  source_chunk uuid,
  source_receipt uuid,
  CHECK (num_nonnulls(source_subject,source_corpus,source_document,source_chunk,source_receipt) IN (0,5)),
  UNIQUE (job_id,evidence_key),
  UNIQUE (id,version_id,item_hash,policy_version),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (job_id) REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
  FOREIGN KEY (version_id,item_hash) REFERENCES tutor_learning_item_versions(id,content_hash) ON DELETE RESTRICT
);

-- shared/observations
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL,
  schema_version text NOT NULL CHECK (schema_version='observation_v2'),
  origin text NOT NULL CHECK (origin IN ('simulation','deterministic_probe')),
  event_key text NOT NULL CHECK (event_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  event_kind text NOT NULL CHECK (event_kind ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  duration_ms integer CHECK (duration_ms>=0),
  UNIQUE (job_id,event_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (job_id) REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT
);

-- shared/proofs
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_proofs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id uuid NOT NULL,
  version_id uuid NOT NULL,
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL REFERENCES tutor_item_supply_shared_policies(policy_version),
  objective_hash text NOT NULL CHECK (objective_hash ~ '^[0-9a-f]{64}$'),
  scope_hash text NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
  environment_hash text NOT NULL CHECK (environment_hash ~ '^[0-9a-f]{64}$'),
  proof_key text NOT NULL CHECK (proof_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  proof_hash text GENERATED ALWAYS AS (encode(digest((objective_hash||scope_hash||item_hash||environment_hash||evidence_id::text||policy_version)::text,'sha256'),'hex')) STORED,
  UNIQUE (proof_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (evidence_id,version_id,item_hash,policy_version) REFERENCES tutor_item_supply_shared_evidence(id,version_id,item_hash,policy_version) ON DELETE RESTRICT
);

-- shared/admissions
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_admissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id uuid NOT NULL,
  version_id uuid NOT NULL,
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL REFERENCES tutor_item_supply_shared_policies(policy_version),
  schema_version text NOT NULL CHECK (schema_version='item_supply_admission_v2'),
  admission_key text NOT NULL CHECK (admission_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  decision text NOT NULL CHECK (decision IN ('blocked','evidence_pending')),
  safe_reason text NOT NULL CHECK (safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (admission_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (evidence_id,version_id,item_hash,policy_version) REFERENCES tutor_item_supply_shared_evidence(id,version_id,item_hash,policy_version) ON DELETE RESTRICT
);

-- private/budget_roots
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_budget_roots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  canonical_key text NOT NULL CHECK (canonical_key ~ '^[0-9a-f]{64}$'),
  policy_class text NOT NULL CHECK (policy_class ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (user_id,epoch,canonical_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT
);

-- private/budget_windows
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_budget_windows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  root_id uuid NOT NULL,
  pool_key text NOT NULL CHECK (pool_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  provider_key text NOT NULL CHECK (provider_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  request_cap integer NOT NULL CHECK (request_cap>0),
  token_cap bigint NOT NULL CHECK (token_cap>0),
  resource_cap bigint NOT NULL CHECK (resource_cap>0),
  CHECK (window_end>window_start),
  UNIQUE (root_id,pool_key,provider_key,window_start),
  UNIQUE (id,user_id,epoch,root_id),
  UNIQUE (id,user_id,epoch,root_id,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (root_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_budget_roots(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/jobs
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  root_id uuid NOT NULL,
  parent_job_id uuid,
  job_key text NOT NULL CHECK (job_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','claimed','running','completed','failed','cancelled')),
  state_version integer NOT NULL DEFAULT 1 CHECK (state_version>=1),
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation>=0),
  lease_owner text,
  lease_expires_at timestamptz,
  terminal_at timestamptz,
  CHECK (parent_job_id IS NULL OR parent_job_id<>id),
  CHECK ((state IN ('claimed','running') AND lease_generation>0 AND lease_owner IS NOT NULL AND length(lease_owner) BETWEEN 1 AND 160 AND lease_expires_at IS NOT NULL) OR (state NOT IN ('claimed','running') AND lease_owner IS NULL AND lease_expires_at IS NULL)),
  CHECK ((state IN ('completed','failed','cancelled')) = (terminal_at IS NOT NULL)),
  UNIQUE (root_id,job_key),
  UNIQUE (id,user_id,epoch,root_id),
  UNIQUE (id,user_id,epoch,root_id,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (root_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_budget_roots(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (parent_job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT
);

-- private/job_events
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_job_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  event_key text NOT NULL CHECK (event_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  event_kind text NOT NULL CHECK (event_kind ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lease_generation integer NOT NULL CHECK (lease_generation>=0),
  state_version integer NOT NULL CHECK (state_version>=1),
  safe_reason text NOT NULL CHECK (safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (job_id,event_key),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/reservations
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  root_id uuid NOT NULL,
  window_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation>0),
  reservation_key text NOT NULL CHECK (reservation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  requests integer NOT NULL CHECK (requests>0),
  tokens bigint NOT NULL CHECK (tokens>0),
  resources bigint NOT NULL CHECK (resources>=0),
  UNIQUE (job_id,reservation_key),
  UNIQUE (id,user_id,epoch,job_id),
  UNIQUE (id,user_id,epoch,job_id,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (window_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_budget_windows(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT
);

-- private/usage_events
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_usage_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  job_id uuid NOT NULL,
  settlement_key text NOT NULL CHECK (settlement_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  usage_state text NOT NULL CHECK (usage_state IN ('known','unknown')),
  input_tokens bigint CHECK (input_tokens>=0),
  output_tokens bigint CHECK (output_tokens>=0),
  resource_units bigint CHECK (resource_units>=0),
  cost_amount numeric CHECK (cost_amount>=0),
  CHECK ((usage_state='unknown' AND input_tokens IS NULL AND output_tokens IS NULL AND resource_units IS NULL AND cost_amount IS NULL) OR (usage_state='known' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND resource_units IS NOT NULL)),
  UNIQUE (reservation_id,settlement_key),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (reservation_id,user_id,epoch,job_id,scope_id) REFERENCES tutor_item_supply_private_reservations(id,user_id,epoch,job_id,scope_id) ON DELETE RESTRICT
);

-- private/evidence
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  version_id uuid NOT NULL,
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version='item_supply_evidence_v2'),
  policy_version text NOT NULL REFERENCES tutor_item_supply_shared_policies(policy_version),
  evidence_key text NOT NULL CHECK (evidence_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  producer_identity text NOT NULL CHECK (producer_identity ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  source_subject text,
  source_corpus uuid,
  source_document uuid,
  source_chunk uuid,
  source_receipt uuid,
  CHECK (num_nonnulls(source_subject,source_corpus,source_document,source_chunk,source_receipt) IN (0,5)),
  UNIQUE (job_id,evidence_key),
  UNIQUE (id,user_id,epoch,version_id,item_hash,policy_version),
  UNIQUE (id,user_id,epoch,version_id,item_hash,policy_version,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (version_id,user_id,epoch,item_hash,scope_id) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,payload_hash,scope_id) ON DELETE RESTRICT
);

-- private/observations
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  schema_version text NOT NULL CHECK (schema_version='observation_v2'),
  origin text NOT NULL CHECK (origin IN ('simulation','deterministic_probe','real_learner')),
  event_key text NOT NULL CHECK (event_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  event_kind text NOT NULL CHECK (event_kind ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  duration_ms integer CHECK (duration_ms>=0),
  collector_identity text,
  session_id uuid,
  actor_id uuid,
  terminal_receipt_id uuid,
  attempt_id uuid,
  CHECK ((origin='real_learner' AND collector_identity IS NOT NULL AND length(collector_identity) BETWEEN 1 AND 160 AND session_id IS NOT NULL AND actor_id IS NOT NULL AND actor_id=user_id AND terminal_receipt_id IS NOT NULL AND attempt_id IS NOT NULL) OR (origin<>'real_learner' AND num_nonnulls(collector_identity,session_id,actor_id,terminal_receipt_id,attempt_id)=0)),
  UNIQUE (job_id,event_key),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (session_id,user_id) REFERENCES tutor_teaching_sessions(id,user_id) ON DELETE RESTRICT,
  FOREIGN KEY (terminal_receipt_id,attempt_id,user_id) REFERENCES tutor_exercise_attempt_results(id,attempt_id,user_id) ON DELETE RESTRICT
);

-- private/proofs
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_proofs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  evidence_id uuid NOT NULL,
  version_id uuid NOT NULL,
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL REFERENCES tutor_item_supply_shared_policies(policy_version),
  objective_hash text NOT NULL CHECK (objective_hash ~ '^[0-9a-f]{64}$'),
  scope_hash text NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
  environment_hash text NOT NULL CHECK (environment_hash ~ '^[0-9a-f]{64}$'),
  proof_key text NOT NULL CHECK (proof_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  proof_hash text GENERATED ALWAYS AS (encode(digest((objective_hash||scope_hash||item_hash||environment_hash||evidence_id::text||policy_version)::text,'sha256'),'hex')) STORED,
  UNIQUE (user_id,epoch,proof_key),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  CONSTRAINT fk_item_supply_proof_exact_scope FOREIGN KEY (scope_id,user_id,epoch,scope_hash,objective_hash) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch,scope_hash,objective_hash) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (evidence_id,user_id,epoch,version_id,item_hash,policy_version,scope_id) REFERENCES tutor_item_supply_private_evidence(id,user_id,epoch,version_id,item_hash,policy_version,scope_id) ON DELETE RESTRICT
);

-- private/admissions
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_admissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  evidence_id uuid NOT NULL,
  version_id uuid NOT NULL,
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL REFERENCES tutor_item_supply_shared_policies(policy_version),
  schema_version text NOT NULL CHECK (schema_version='item_supply_admission_v2'),
  admission_key text NOT NULL CHECK (admission_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  decision text NOT NULL CHECK (decision IN ('blocked','evidence_pending')),
  safe_reason text NOT NULL CHECK (safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (user_id,epoch,admission_key),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (evidence_id,user_id,epoch,version_id,item_hash,policy_version,scope_id) REFERENCES tutor_item_supply_private_evidence(id,user_id,epoch,version_id,item_hash,policy_version,scope_id) ON DELETE RESTRICT
);

-- private/demands
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_demands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  request_key text NOT NULL CHECK (request_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=262144 AND (snapshot_json->>'schema_version') IS NOT DISTINCT FROM 'assessment_supply_demand_v1'),
  UNIQUE (user_id,epoch,request_key),
  UNIQUE (id,user_id,epoch,scope_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT
);

-- private/results
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  demand_id uuid NOT NULL,
  scope_id uuid NOT NULL,
  result_version integer NOT NULL CHECK (result_version>=1),
  status text NOT NULL CHECK (status IN ('gap','pending','failed','stale')),
  safe_reason text NOT NULL CHECK (safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (demand_id,result_version),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (demand_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/publication_refs
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_publication_refs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  version_id uuid NOT NULL,
  publication_event_id uuid NOT NULL,
  shared_version_id uuid NOT NULL,
  materialization_id uuid,
  materialization_hash text,
  CHECK (num_nonnulls(materialization_id,materialization_hash) IN (0,2)),
  UNIQUE (version_id,publication_event_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (version_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (publication_event_id,shared_version_id) REFERENCES tutor_learning_item_publication_events(id,version_id) ON DELETE RESTRICT,
  FOREIGN KEY (materialization_id,shared_version_id,materialization_hash) REFERENCES tutor_learning_item_practice_materializations(id,version_id,receipt_hash) ON DELETE RESTRICT
);

-- private/result_items
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_result_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  result_id uuid NOT NULL,
  scope_id uuid NOT NULL,
  proof_id uuid NOT NULL,
  publication_ref_id uuid NOT NULL,
  UNIQUE (result_id,proof_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (result_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_results(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (proof_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_proofs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (publication_ref_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_publication_refs(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/bindings
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  result_id uuid NOT NULL,
  version_id uuid NOT NULL,
  binding_key text NOT NULL CHECK (binding_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','invalidated')),
  state_version integer NOT NULL DEFAULT 1 CHECK (state_version>=1),
  UNIQUE (user_id,epoch,binding_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY (version_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (result_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_results(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/cache
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_cache (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  version_id uuid NOT NULL,
  cache_key text NOT NULL CHECK (cache_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  expires_at timestamptz NOT NULL,
  UNIQUE (user_id,epoch,cache_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY (version_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/staging
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_staging (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  stage_key text NOT NULL CHECK (stage_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  public_json jsonb NOT NULL CHECK (jsonb_typeof(public_json)='object' AND octet_length(public_json::text)<=262144 AND (public_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_public_v1'),
  private_json jsonb NOT NULL CHECK (jsonb_typeof(private_json)='object' AND octet_length(private_json::text)<=262144 AND (private_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_private_v1'),
  payload_hash text GENERATED ALWAYS AS (encode(digest((public_json::text||private_json::text)::text,'sha256'),'hex')) STORED,
  UNIQUE (candidate_id,stage_key),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (candidate_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_candidates(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- private/subscriptions
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  demand_id uuid NOT NULL,
  private_job_id uuid,
  shared_job_id uuid,
  CHECK (num_nonnulls(private_job_id,shared_job_id)=1),
  subscription_key text NOT NULL CHECK (subscription_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','cancelled')),
  state_version integer NOT NULL DEFAULT 1 CHECK (state_version>=1),
  UNIQUE (user_id,epoch,subscription_key),
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,user_id,epoch),
  UNIQUE (id,user_id,epoch,scope_id),
  FOREIGN KEY (demand_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (private_job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY (shared_job_id) REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT
);

-- Additive guards also cover a database that saw an earlier P2 bootstrap;
-- bootstrap is repeatable without dropping/replacing user or shared tables.
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='chk_item_supply_private_scope_namespace') THEN
    ALTER TABLE tutor_item_supply_private_scopes ADD CONSTRAINT chk_item_supply_private_scope_namespace
      CHECK ((snapshot_json->>'visibility') IS NOT DISTINCT FROM 'private'
        AND (snapshot_json->>'owner_ref') IS NOT DISTINCT FROM ('user:'||user_id::text));
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='uq_item_supply_private_scope_contract') THEN
    ALTER TABLE tutor_item_supply_private_scopes ADD CONSTRAINT uq_item_supply_private_scope_contract UNIQUE(id,user_id,epoch,scope_hash,objective_hash);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='chk_item_supply_shared_blueprint_namespace') THEN
    ALTER TABLE tutor_item_supply_shared_blueprints ADD CONSTRAINT chk_item_supply_shared_blueprint_namespace
      CHECK ((snapshot_json->'scope'->>'visibility') IS NOT DISTINCT FROM 'public'
        AND snapshot_json->'scope'->>'owner_ref' IS NULL);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='fk_item_supply_proof_exact_scope') THEN
    ALTER TABLE tutor_item_supply_private_proofs ADD CONSTRAINT fk_item_supply_proof_exact_scope
      FOREIGN KEY(scope_id,user_id,epoch,scope_hash,objective_hash)
      REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch,scope_hash,objective_hash) ON DELETE RESTRICT;
  END IF;
END $$;

-- Frozen shared snapshot shapes: a visibility check alone must not leave a
-- JSON side channel for owner mappings, private payload or private hashes.
-- Trusted public producers still own the provenance of permitted scalar values;
-- this structural fence does not issue current source/publication authority.
-- These frozen snapshots have scalar strings/bools/null/integers, not floats.
-- Match the Python canonical JSON contract (UTF-8, sorted ASCII schema keys,
-- compact separators), rather than hashing PostgreSQL's spaced jsonb text.
CREATE OR REPLACE FUNCTION item_supply_internal.canonical_snapshot(value jsonb)
RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE result text;
BEGIN
  IF jsonb_typeof(value)='object' THEN
    SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||item_supply_internal.canonical_snapshot(v),
      ',' ORDER BY key COLLATE "C"),'')||'}' INTO result FROM jsonb_each(value) e(key,v);
  ELSIF jsonb_typeof(value)='array' THEN
    SELECT '['||coalesce(string_agg(item_supply_internal.canonical_snapshot(v),',' ORDER BY n),'')||']'
      INTO result FROM jsonb_array_elements(value) WITH ORDINALITY e(v,n);
  ELSE result := value::text; END IF;
  RETURN result;
END $$;
CREATE OR REPLACE FUNCTION item_supply_internal.snapshot_hash(value jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT encode(digest(convert_to(item_supply_internal.canonical_snapshot(value),'UTF8'),'sha256'),'hex')
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.snapshot_keys(value jsonb, allowed text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='object' THEN
    value ?& allowed AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(value) k WHERE NOT k=ANY(allowed))
    ELSE false END
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.snapshot_scalars(value jsonb, nested text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='object' THEN NOT EXISTS(
    SELECT 1 FROM jsonb_each(value) e WHERE NOT e.key=ANY(nested) AND jsonb_typeof(e.value) IN ('object','array'))
    ELSE false END
$$;
CREATE OR REPLACE FUNCTION item_supply_internal.snapshot_strings(value jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='array' THEN NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(value) e WHERE jsonb_typeof(e)<>'string') ELSE false END
$$;
CREATE OR REPLACE FUNCTION enforce_item_supply_shared_snapshot() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE snapshot jsonb; entry jsonb;
BEGIN
  IF TG_TABLE_NAME='tutor_item_supply_shared_policies' THEN
    snapshot := NEW.policy_json;
    IF NEW.policy_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(snapshot) THEN
      RAISE check_violation USING MESSAGE='shared policy hash mismatch';
    END IF;
    IF NOT item_supply_internal.snapshot_keys(snapshot, ARRAY['schema_version','policy_version','publication_enabled','required_review_roles','risk_adapter_required','independent_second_bundle_required'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY['required_review_roles'])
      OR snapshot->'required_review_roles' IS DISTINCT FROM '["curriculum","difficulty","technical","ambiguity","security","adversarial"]'::jsonb
      OR snapshot->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
      OR snapshot->'risk_adapter_required' IS DISTINCT FROM 'true'::jsonb
      OR snapshot->'independent_second_bundle_required' IS DISTINCT FROM 'true'::jsonb
      OR snapshot->>'policy_version' IS DISTINCT FROM NEW.policy_version THEN
      RAISE check_violation USING MESSAGE='invalid shared policy snapshot';
    END IF;
  ELSIF TG_TABLE_NAME='tutor_item_supply_shared_blueprints' THEN
    snapshot := NEW.snapshot_json;
    IF NEW.blueprint_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(snapshot) THEN
      RAISE check_violation USING MESSAGE='shared blueprint hash mismatch';
    END IF;
    IF NOT item_supply_internal.snapshot_keys(snapshot, ARRAY['schema_version','scope','objective_hash','clauses','minimum','matrix_hash','policy_version'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY['scope','minimum','clauses'])
      OR NOT item_supply_internal.snapshot_keys(snapshot->'scope', ARRAY['schema_version','course_family','course_version','knowledge_key','language_id','subject_id','subject_version','required_facets','dialect','runtime_profile_id','runtime_profile_hash','item_kind','purpose','interaction','required_capabilities','assessment_contract_version','scorer_version','assistance_policy_hash','visibility','owner_ref'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot->'scope', ARRAY['required_facets','required_capabilities'])
      OR NOT item_supply_internal.snapshot_strings(snapshot->'scope'->'required_facets')
      OR NOT item_supply_internal.snapshot_strings(snapshot->'scope'->'required_capabilities')
      OR NOT item_supply_internal.snapshot_keys(snapshot->'minimum', ARRAY['policy_version','practice','assessment','remediation'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot->'minimum', ARRAY[]::text[])
      OR jsonb_typeof(snapshot->'clauses') IS DISTINCT FROM 'array'
      OR snapshot->>'objective_hash' IS DISTINCT FROM NEW.objective_hash
      OR snapshot->>'matrix_hash' IS DISTINCT FROM NEW.matrix_hash
      OR snapshot->>'policy_version' IS DISTINCT FROM NEW.policy_version THEN
      RAISE check_violation USING MESSAGE='invalid shared blueprint snapshot';
    END IF;
    FOR entry IN SELECT value FROM jsonb_array_elements(snapshot->'clauses') LOOP
      IF NOT item_supply_internal.snapshot_keys(entry, ARRAY['clause_id','clause_hash','prerequisite_clause_ids'])
        OR NOT item_supply_internal.snapshot_scalars(entry, ARRAY['prerequisite_clause_ids'])
        OR NOT item_supply_internal.snapshot_strings(entry->'prerequisite_clause_ids') THEN
        RAISE check_violation USING MESSAGE='invalid shared clause snapshot';
      END IF;
    END LOOP;
  ELSE
    snapshot := NEW.snapshot_json;
    IF NEW.matrix_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(snapshot) THEN
      RAISE check_violation USING MESSAGE='shared matrix hash mismatch';
    END IF;
    IF NOT item_supply_internal.snapshot_keys(snapshot, ARRAY['version','authority','gate_metadata_status','runtime_readiness','source_readiness','inventory_readiness','languages','public_course_languages','item_kinds','item_purposes','interactions','first_batch_slices'])
      OR NOT item_supply_internal.snapshot_scalars(snapshot, ARRAY['languages','public_course_languages','first_batch_slices','item_kinds','item_purposes','interactions'])
      OR NOT item_supply_internal.snapshot_strings(snapshot->'item_kinds')
      OR NOT item_supply_internal.snapshot_strings(snapshot->'item_purposes')
      OR NOT item_supply_internal.snapshot_strings(snapshot->'interactions')
      OR jsonb_typeof(snapshot->'languages') IS DISTINCT FROM 'array'
      OR jsonb_typeof(snapshot->'public_course_languages') IS DISTINCT FROM 'array'
      OR jsonb_typeof(snapshot->'first_batch_slices') IS DISTINCT FROM 'array'
      OR snapshot->>'authority' IS DISTINCT FROM 'declaration_only'
      OR snapshot->>'gate_metadata_status' IS DISTINCT FROM 'separate_p0_snapshot'
      OR snapshot->>'runtime_readiness' IS DISTINCT FROM 'not_evaluated'
      OR snapshot->>'source_readiness' IS DISTINCT FROM 'not_evaluated'
      OR snapshot->>'inventory_readiness' IS DISTINCT FROM 'not_evaluated' THEN
      RAISE check_violation USING MESSAGE='invalid shared matrix snapshot';
    END IF;
    FOR entry IN SELECT value FROM jsonb_array_elements(snapshot->'languages') LOOP
      IF NOT item_supply_internal.snapshot_keys(entry, ARRAY['language_id','display_name','aliases','current_public_course_language','capability_state','lesson_generation','grounding','exercise_generation','execution','tests','static_analysis','review_feedback','presentation','ux_disclosure','runner_key','source_trust_policy','enabled_for_public_selection','sandbox_boundary'])
        OR NOT item_supply_internal.snapshot_scalars(entry, ARRAY['aliases'])
        OR NOT item_supply_internal.snapshot_strings(entry->'aliases') THEN
        RAISE check_violation USING MESSAGE='invalid shared language snapshot';
      END IF;
    END LOOP;
    FOR entry IN SELECT value FROM jsonb_array_elements(snapshot->'public_course_languages') LOOP
      IF NOT item_supply_internal.snapshot_keys(entry, ARRAY['course_language_id','language_ids'])
        OR NOT item_supply_internal.snapshot_scalars(entry, ARRAY['language_ids'])
        OR NOT item_supply_internal.snapshot_strings(entry->'language_ids') THEN
        RAISE check_violation USING MESSAGE='invalid shared course snapshot';
      END IF;
    END LOOP;
    FOR entry IN SELECT value FROM jsonb_array_elements(snapshot->'first_batch_slices') LOOP
      IF NOT item_supply_internal.snapshot_keys(entry, ARRAY['slice_id','version','language_id','dialect','item_kind','item_purpose','interaction','content_contract_target','gate_contract_target','gate_adapter_status','acceptance_status'])
        OR NOT item_supply_internal.snapshot_scalars(entry, ARRAY[]::text[]) THEN
        RAISE check_violation USING MESSAGE='invalid shared slice snapshot';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_snapshot() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_snapshot ON tutor_item_supply_shared_matrices;
CREATE TRIGGER supply_snapshot BEFORE INSERT ON tutor_item_supply_shared_matrices
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_snapshot();
DROP TRIGGER IF EXISTS supply_snapshot ON tutor_item_supply_shared_policies;
CREATE TRIGGER supply_snapshot BEFORE INSERT ON tutor_item_supply_shared_policies
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_snapshot();
DROP TRIGGER IF EXISTS supply_snapshot ON tutor_item_supply_shared_blueprints;
CREATE TRIGGER supply_snapshot BEFORE INSERT ON tutor_item_supply_shared_blueprints
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_snapshot();

-- A protected DB capability, not a caller-settable GUC. Both privilege boundaries
-- are explicit: only the maintenance function can create transaction permits;
-- only its explicitly granted executor may invoke it. Schema owner is trusted.
CREATE OR REPLACE FUNCTION item_supply_internal.permitted(target_user uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT EXISTS(SELECT 1 FROM item_supply_internal.reset_permits
    WHERE transaction_id=txid_current() AND user_id=target_user)
$$;
REVOKE ALL ON FUNCTION item_supply_internal.permitted(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_epoch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.epoch<>1 OR NOT NEW.enabled THEN RAISE check_violation USING MESSAGE='invalid initial supply epoch'; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='UPDATE' AND item_supply_internal.permitted(OLD.user_id)
    AND NEW.user_id=OLD.user_id AND NEW.epoch=OLD.epoch+1 THEN RETURN NEW; END IF;
  RAISE check_violation USING MESSAGE='supply epoch is maintenance-owned';
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_epoch() FROM PUBLIC;
DROP TRIGGER IF EXISTS item_supply_epoch_guard ON tutor_item_supply_user_epochs;
CREATE TRIGGER item_supply_epoch_guard BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_user_epochs
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_epoch();

CREATE OR REPLACE FUNCTION enforce_item_supply_private_epoch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE active_epoch bigint; active_enabled boolean; node_facts jsonb; expected_scope_hash text; stored_scope record;
BEGIN
  IF TG_OP='DELETE' THEN
    IF item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE check_violation USING MESSAGE='private supply deletion requires maintenance capability';
  END IF;
  IF TG_OP='UPDATE' AND item_supply_internal.permitted(OLD.user_id) THEN RETURN NEW; END IF;
  PERFORM 1 FROM users WHERE id=NEW.user_id AND deleted_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='stale supply epoch'; END IF;
  SELECT epoch,enabled INTO active_epoch,active_enabled FROM tutor_item_supply_user_epochs
    WHERE user_id=NEW.user_id FOR SHARE;
  IF active_epoch IS NULL OR NOT active_enabled OR active_epoch<>NEW.epoch OR
    NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.user_id AND deleted_at IS NULL) THEN
    RAISE check_violation USING MESSAGE='stale supply epoch';
  END IF;
  -- The epoch fence is not a plan-revision fence. Lock/recheck the active
  -- pointer in every direct private write too, not just repository reads.
  IF TG_TABLE_NAME='tutor_item_supply_private_scopes' THEN
    PERFORM 1 FROM tutor_track_active_plans p
      WHERE p.track_id=NEW.track_id AND p.user_id=NEW.user_id AND p.revision_id=NEW.revision_id
      FOR SHARE OF p;
  ELSE
    PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
      ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
      WHERE s.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch
      FOR SHARE OF p;
  END IF;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='stale supply scope'; END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_scopes' THEN
    SELECT jsonb_build_object('id',n.id::text,'title',n.title,'description',n.description,
      'required_capabilities_json',n.required_capabilities_json,'prerequisite_keys_json',n.prerequisite_keys_json,
      'language_id',t.language_id) INTO node_facts
      FROM tutor_track_plan_nodes n JOIN tutor_learning_tracks t ON t.id=n.track_id AND t.user_id=n.user_id
      WHERE n.user_id=NEW.user_id AND n.track_id=NEW.track_id AND n.revision_id=NEW.revision_id
        AND n.knowledge_key=NEW.knowledge_key FOR SHARE OF n;
    IF node_facts IS NULL THEN RAISE check_violation USING MESSAGE='private supply node mismatch'; END IF;
    expected_scope_hash := item_supply_internal.snapshot_hash(jsonb_build_object('contract',NEW.snapshot_json,
      'track_id',NEW.track_id::text,'revision_id',NEW.revision_id::text,'node_id',node_facts->>'id'));
    IF NEW.scope_hash IS DISTINCT FROM expected_scope_hash
      OR NEW.objective_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(node_facts)
      OR NEW.snapshot_json->>'knowledge_key' IS DISTINCT FROM NEW.knowledge_key
      OR NEW.snapshot_json->>'language_id' IS DISTINCT FROM node_facts->>'language_id' THEN
      RAISE check_violation USING MESSAGE='private scope fingerprint mismatch';
    END IF;
  ELSIF TG_TABLE_NAME='tutor_item_supply_private_demands' THEN
    SELECT snapshot_json,objective_hash INTO stored_scope FROM tutor_item_supply_private_scopes
      WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
    IF NEW.demand_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.snapshot_json)
      OR NEW.snapshot_json->'scope' IS DISTINCT FROM stored_scope.snapshot_json
      OR NEW.snapshot_json->>'objective_hash' IS DISTINCT FROM stored_scope.objective_hash
      OR NEW.snapshot_json->>'learner_ref' IS DISTINCT FROM ('user:'||NEW.user_id::text) THEN
      RAISE check_violation USING MESSAGE='private demand fingerprint mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_private_epoch() FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' AND TG_ARGV[0]='private' THEN
    IF item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
  END IF;
  RAISE check_violation USING MESSAGE='immutable supply evidence';
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_immutable() FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_mutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    IF TG_ARGV[0]='private' THEN
      IF item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
    END IF;
    RAISE check_violation USING MESSAGE='supply deletion denied';
  END IF;
  IF TG_OP='INSERT' AND TG_ARGV[1]='jobs' THEN
    IF NEW.state<>'pending' OR NEW.state_version<>1 OR NEW.lease_generation<>0 THEN
      RAISE check_violation USING MESSAGE='supply job must start pending';
    END IF;
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (to_jsonb(NEW)-ARRAY['state','state_version','lease_generation','lease_owner','lease_expires_at','terminal_at','updated_at'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','state_version','lease_generation','lease_owner','lease_expires_at','terminal_at','updated_at'])
      OR NEW.state_version<>OLD.state_version+1 THEN RAISE check_violation USING MESSAGE='invalid supply CAS identity'; END IF;
    IF TG_ARGV[1]='jobs' THEN
      IF NOT ((OLD.state='pending' AND NEW.state IN ('claimed','failed','cancelled'))
        OR (OLD.state='claimed' AND NEW.state IN ('claimed','running','failed','cancelled'))
        OR (OLD.state='running' AND NEW.state IN ('running','completed','failed','cancelled'))) THEN
        RAISE check_violation USING MESSAGE='invalid job transition';
      END IF;
      IF (OLD.state IN ('completed','failed','cancelled')) OR NEW.lease_generation<OLD.lease_generation
        OR NEW.lease_generation>OLD.lease_generation+1 THEN RAISE check_violation USING MESSAGE='invalid job lifecycle'; END IF;
      IF NEW.lease_owner IS DISTINCT FROM OLD.lease_owner AND NEW.state IN ('claimed','running')
        AND NEW.lease_generation<>OLD.lease_generation+1 THEN RAISE check_violation USING MESSAGE='invalid lease generation'; END IF;
    ELSIF OLD.state<>'active' OR NEW.state='active' THEN
      RAISE check_violation USING MESSAGE='invalid supply binding lifecycle';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_mutable() FROM PUBLIC;

-- A composite FK alone permits a cycle inserted in a single statement. Reject
-- it before storing immutable lineage, so the authorized leaf-to-root purge is
-- total over all accepted candidates/jobs. UNION bounds even malformed ancestry.
CREATE OR REPLACE FUNCTION enforce_item_supply_lineage() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE parent_id uuid; cyclic boolean;
BEGIN
  IF TG_ARGV[0]='candidate' THEN parent_id := NEW.parent_candidate_id;
  ELSE parent_id := NEW.parent_job_id; END IF;
  IF parent_id IS NOT NULL THEN
    EXECUTE format('WITH RECURSIVE ancestors AS (
      SELECT id,%1$I AS parent_id FROM public.%2$I WHERE id=$1
      UNION SELECT p.id,p.%1$I FROM public.%2$I p JOIN ancestors a ON p.id=a.parent_id
    ) SELECT EXISTS(SELECT 1 FROM ancestors WHERE id=$2)',
      CASE WHEN TG_ARGV[0]='candidate' THEN 'parent_candidate_id' ELSE 'parent_job_id' END,
      TG_TABLE_NAME) INTO cyclic USING parent_id,NEW.id;
    IF cyclic OR parent_id=NEW.id THEN
      RAISE check_violation USING MESSAGE='invalid supply lineage';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_lineage() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_lineage ON tutor_item_supply_private_candidates;
CREATE TRIGGER supply_lineage AFTER INSERT ON tutor_item_supply_private_candidates
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_lineage('candidate');
DROP TRIGGER IF EXISTS supply_lineage ON tutor_item_supply_private_jobs;
CREATE TRIGGER supply_lineage AFTER INSERT ON tutor_item_supply_private_jobs
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_lineage('job');
DROP TRIGGER IF EXISTS supply_lineage ON tutor_item_supply_shared_jobs;
CREATE TRIGGER supply_lineage AFTER INSERT ON tutor_item_supply_shared_jobs
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_lineage('job');

CREATE OR REPLACE FUNCTION enforce_item_supply_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF NEW.origin='real_learner' AND NOT EXISTS(
    SELECT 1 FROM tutor_teaching_sessions s
      JOIN tutor_lesson_assignments la ON la.id=s.lesson_assignment_id AND la.user_id=s.user_id
        AND la.track_id=s.track_id AND la.knowledge_key=s.knowledge_key AND la.document_id=s.document_id
        AND la.assignment_version=s.assignment_version AND la.source_plan_revision_id=s.active_plan_revision_id
      JOIN tutor_exercise_attempts a
      ON a.user_id=s.user_id AND a.track_id=s.track_id AND a.knowledge_key=s.knowledge_key
      AND a.lesson_assignment_id=s.lesson_assignment_id AND a.document_id=s.document_id
      AND a.plan_revision_id=s.active_plan_revision_id
      JOIN tutor_exercise_attempt_results r ON r.attempt_id=a.id AND r.user_id=a.user_id
      JOIN tutor_item_supply_private_scopes ps ON ps.id=NEW.scope_id AND ps.user_id=NEW.user_id
        AND ps.epoch=NEW.epoch AND ps.track_id=a.track_id AND ps.revision_id=a.plan_revision_id
        AND ps.knowledge_key=a.knowledge_key
      WHERE s.id=NEW.session_id AND s.user_id=NEW.user_id AND a.id=NEW.attempt_id AND r.id=NEW.terminal_receipt_id
  ) THEN RAISE check_violation USING MESSAGE='observation authority mismatch'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_matrices;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_matrices FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_policies;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_policies FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_blueprints;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_blueprints FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_slots;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_slots FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_scopes;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_scopes FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_scopes;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_scopes FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_materials;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_materials FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_materials;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_materials FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_candidates;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_candidates FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_candidates;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_candidates FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_versions;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_versions FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_versions;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_versions FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_budget_roots;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_budget_roots FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_budget_windows;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_budget_windows FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_jobs;
CREATE TRIGGER supply_mutation BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_shared_jobs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_mutable('shared','jobs');
DROP TRIGGER IF EXISTS supply_updated_at ON tutor_item_supply_shared_jobs;
CREATE TRIGGER supply_updated_at BEFORE UPDATE ON tutor_item_supply_shared_jobs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_job_events;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_job_events FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_reservations;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_reservations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_usage_events;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_usage_events FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_evidence;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_evidence FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_observations;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_observations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_proofs;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_proofs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_admissions;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_admissions FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_budget_roots;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_budget_roots FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_budget_roots;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_budget_roots FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_budget_windows;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_budget_windows FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_budget_windows;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_budget_windows FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_jobs;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_jobs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_jobs;
CREATE TRIGGER supply_mutation BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_jobs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_mutable('private','jobs');
DROP TRIGGER IF EXISTS supply_updated_at ON tutor_item_supply_private_jobs;
CREATE TRIGGER supply_updated_at BEFORE UPDATE ON tutor_item_supply_private_jobs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_job_events;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_job_events FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_job_events;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_job_events FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_reservations;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_reservations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_reservations;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_reservations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_usage_events;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_usage_events FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_usage_events;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_usage_events FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_evidence;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_evidence FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_evidence;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_evidence FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_observations;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_observations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_observations;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_observations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_proofs;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_proofs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_proofs;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_proofs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_admissions;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_admissions FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_admissions;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_admissions FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_demands;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_demands FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_demands;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_demands FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_results;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_results FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_results;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_results FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_publication_refs;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_publication_refs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_publication_refs;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_publication_refs FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_result_items;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_result_items FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_result_items;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_result_items FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_bindings;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_bindings FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_bindings;
CREATE TRIGGER supply_mutation BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_bindings FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_mutable('private','bindings');
DROP TRIGGER IF EXISTS supply_updated_at ON tutor_item_supply_private_bindings;
CREATE TRIGGER supply_updated_at BEFORE UPDATE ON tutor_item_supply_private_bindings FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_cache;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_cache FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_cache;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_cache FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_staging;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_staging FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_staging;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_private_staging FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');

DROP TRIGGER IF EXISTS supply_epoch ON tutor_item_supply_private_subscriptions;
CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_subscriptions FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_private_subscriptions;
CREATE TRIGGER supply_mutation BEFORE INSERT OR UPDATE OR DELETE ON tutor_item_supply_private_subscriptions FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_mutable('private','subscriptions');
DROP TRIGGER IF EXISTS supply_updated_at ON tutor_item_supply_private_subscriptions;
CREATE TRIGGER supply_updated_at BEFORE UPDATE ON tutor_item_supply_private_subscriptions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS supply_real_observation ON tutor_item_supply_private_observations;
CREATE TRIGGER supply_real_observation BEFORE INSERT ON tutor_item_supply_private_observations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_observation();

CREATE OR REPLACE FUNCTION purge_item_supply_private(target_user uuid, deleting boolean DEFAULT false)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE new_epoch bigint;
BEGIN
  PERFORM 1 FROM users WHERE id=target_user AND deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='supply user unavailable'; END IF;
  INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(target_user) ON CONFLICT DO NOTHING;
  INSERT INTO item_supply_internal.reset_permits VALUES(txid_current(),target_user);
  UPDATE tutor_item_supply_user_epochs SET epoch=epoch+1,enabled=NOT deleting,updated_at=now()
    WHERE user_id=target_user RETURNING epoch INTO new_epoch;
  UPDATE tutor_item_supply_private_jobs SET state='cancelled',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL,terminal_at=now() WHERE user_id=target_user AND state NOT IN ('completed','failed','cancelled');
  UPDATE tutor_item_supply_private_bindings SET state='invalidated',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  UPDATE tutor_item_supply_private_subscriptions SET state='cancelled',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  -- Old request/worker epoch is invalid before any child is removed. Epoch row
  -- lock fences late writes until caller commits or rolls back the entire reset.
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
  -- Jobs self-reference; delete leaves to roots below.
  LOOP
    DELETE FROM tutor_item_supply_private_jobs j WHERE j.user_id=target_user AND NOT EXISTS
      (SELECT 1 FROM tutor_item_supply_private_jobs c WHERE c.parent_job_id=j.id);
    EXIT WHEN NOT FOUND;
  END LOOP;
  DELETE FROM tutor_item_supply_private_budget_windows WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_budget_roots WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_staging WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_versions WHERE user_id=target_user;
  LOOP
    DELETE FROM tutor_item_supply_private_candidates c WHERE c.user_id=target_user AND NOT EXISTS
      (SELECT 1 FROM tutor_item_supply_private_candidates child WHERE child.parent_candidate_id=c.id);
    EXIT WHEN NOT FOUND;
  END LOOP;
  DELETE FROM tutor_item_supply_private_materials WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_scopes WHERE user_id=target_user;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_jobs WHERE user_id=target_user) OR
    EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates WHERE user_id=target_user) THEN
    RAISE check_violation USING MESSAGE='supply lineage cleanup incomplete';
  END IF;
  DELETE FROM item_supply_internal.reset_permits WHERE transaction_id=txid_current() AND user_id=target_user;
  RETURN new_epoch;
END $$;
REVOKE ALL ON FUNCTION purge_item_supply_private(uuid,boolean) FROM PUBLIC;
