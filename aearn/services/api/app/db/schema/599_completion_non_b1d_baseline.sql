SET LOCAL search_path=public,pg_catalog,pg_temp;
-- Independent completion_non_b1d_v1 first-install contract; not an old migration replay.
-- Caller holds its schema advisory lock in the sole transaction. No COMMIT/seed/import.
-- Existing SQL <=598, B1d identities and business authorization are not reused.
DO $preflight$
BEGIN
 IF current_database() NOT IN ('postgres','aearn_completion_b_test_20261026','aearn_completion_b_validation_20261027')
  OR NOT (SELECT rolsuper FROM pg_roles WHERE rolname=session_user) THEN
  RAISE EXCEPTION 'completion baseline: named database and schema installer required' USING ERRCODE='42501';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname IN('item_supply_internal','completion_baseline_internal'))
  OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND (c.relname LIKE 'tutor_item_supply_%' OR c.relname IN('rag_assessment_source_evidence','rag_actual_d_private_provenance','tutor_learning_item_native_publication_proofs')))
 THEN RAISE EXCEPTION 'completion baseline: unknown or partially installed state' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM pg_default_acl WHERE defaclrole=(SELECT oid FROM pg_roles WHERE rolname=session_user)) THEN
  RAISE EXCEPTION 'completion baseline: unknown installer default privileges' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pgcrypto' AND extversion='1.3') THEN
  RAISE EXCEPTION 'completion baseline: expected pgcrypto prerequisite missing' USING ERRCODE='23514'; END IF;
END $preflight$;
-- Roles are cluster objects: a second named database may reuse ONLY our exact
-- NOLOGIN schema role and non-privileged, non-member runtime/verifier roles.
DO $roles$
DECLARE r text; p record;
BEGIN
 FOREACH r IN ARRAY ARRAY['aearn_cb_schema_20261027','aearn_cb_runtime_20261027','aearn_cb_verifier_20261027'] LOOP
  SELECT * INTO p FROM pg_roles WHERE rolname=r;
  IF FOUND THEN
   IF shobj_description(p.oid,'pg_authid') IS DISTINCT FROM 'completion_non_b1d_v1 managed role' OR p.rolsuper OR p.rolcreatedb OR p.rolcreaterole OR p.rolreplication OR p.rolbypassrls
    OR p.rolinherit OR p.rolcanlogin IS DISTINCT FROM (r<>'aearn_cb_schema_20261027')
    OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=p.oid OR member=p.oid)
   THEN RAISE EXCEPTION 'completion baseline: incompatible preexisting role %',r USING ERRCODE='23514'; END IF;
  ELSE
   EXECUTE format('CREATE ROLE %I %s NOSUPERUSER NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',r,CASE WHEN r='aearn_cb_schema_20261027' THEN 'NOLOGIN' ELSE 'LOGIN' END);
  END IF;
  EXECUTE format('COMMENT ON ROLE %I IS %L',r,'completion_non_b1d_v1 managed role');
 END LOOP;
END $roles$;
CREATE SCHEMA item_supply_internal AUTHORIZATION aearn_cb_schema_20261027;
CREATE SCHEMA completion_baseline_internal AUTHORIZATION aearn_cb_schema_20261027;
REVOKE ALL ON SCHEMA item_supply_internal,completion_baseline_internal FROM PUBLIC;
GRANT USAGE ON SCHEMA item_supply_internal,completion_baseline_internal TO aearn_cb_runtime_20261027;
GRANT USAGE ON SCHEMA completion_baseline_internal TO aearn_cb_verifier_20261027;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO aearn_cb_schema_20261027,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

-- Exact pure snapshot algebra; no business authorization.
CREATE FUNCTION item_supply_internal.canonical_snapshot(value jsonb)
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

-- Exact pure snapshot algebra; no business authorization.
CREATE FUNCTION item_supply_internal.snapshot_hash(value jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT encode(digest(convert_to(item_supply_internal.canonical_snapshot(value),'UTF8'),'sha256'),'hex')
$$;

-- Exact pure snapshot algebra; no business authorization.
CREATE FUNCTION item_supply_internal.snapshot_keys(value jsonb, allowed text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='object' THEN
    value ?& allowed AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(value) k WHERE NOT k=ANY(allowed))
    ELSE false END
$$;

-- Exact pure snapshot algebra; no business authorization.
CREATE FUNCTION item_supply_internal.snapshot_scalars(value jsonb, nested text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='object' THEN NOT EXISTS(
    SELECT 1 FROM jsonb_each(value) e WHERE NOT e.key=ANY(nested) AND jsonb_typeof(e.value) IN ('object','array'))
    ELSE false END
$$;

-- Exact pure snapshot algebra; no business authorization.
CREATE FUNCTION item_supply_internal.snapshot_strings(value jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT CASE WHEN jsonb_typeof(value)='array' THEN NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(value) e WHERE jsonb_typeof(e)<>'string') ELSE false END
$$;

-- Exact pure snapshot algebra; no business authorization.
CREATE FUNCTION item_supply_internal.pipeline_generation_hash(source_payload jsonb, receipt_payload jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT item_supply_internal.snapshot_hash(jsonb_build_object('source',source_payload,'receipt',receipt_payload))
$$;

-- Exact pure snapshot algebra; no business authorization.
CREATE FUNCTION item_supply_internal.shared_generation_hash(source_payload jsonb, receipt_payload jsonb, request_payload jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT item_supply_internal.snapshot_hash(jsonb_build_object('source',source_payload,'receipt',receipt_payload,'request',request_payload))
$$;

CREATE TABLE completion_baseline_internal.installation_identity(
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 database_oid oid NOT NULL, database_name name NOT NULL,
 contract_id text NOT NULL CHECK(contract_id='completion_non_b1d_v1'),
 purpose text NOT NULL CHECK(purpose IN('runtime-purpose','storage-validation-purpose'))
);
INSERT INTO completion_baseline_internal.installation_identity(database_oid,database_name,contract_id,purpose)
 SELECT oid,datname,'completion_non_b1d_v1',CASE WHEN datname='aearn_completion_b_validation_20261027' THEN 'storage-validation-purpose' ELSE 'runtime-purpose' END
 FROM pg_database WHERE datname=current_database();
CREATE FUNCTION completion_baseline_internal.contract_identity()
RETURNS TABLE(database_oid oid,database_name name,contract_id text,purpose text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,completion_baseline_internal,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM completion_baseline_internal.installation_identity i
  JOIN pg_database d ON d.oid=i.database_oid AND d.datname=i.database_name
  WHERE d.datname=current_database() AND i.contract_id='completion_non_b1d_v1'
   AND ((i.purpose='runtime-purpose' AND d.datname IN('postgres','aearn_completion_b_test_20261026'))
    OR (i.purpose='storage-validation-purpose' AND d.datname='aearn_completion_b_validation_20261027')))
 THEN RAISE EXCEPTION 'completion baseline: protected database identity changed' USING ERRCODE='42501'; END IF;
 RETURN QUERY SELECT i.database_oid,i.database_name,i.contract_id,i.purpose FROM completion_baseline_internal.installation_identity i;
END $$;
CREATE TABLE item_supply_internal.reset_permits(transaction_id bigint NOT NULL,user_id uuid NOT NULL,PRIMARY KEY(transaction_id,user_id));
-- Empty absent a separately audited fixed validation receiver (600); no public DML.
CREATE TABLE completion_baseline_internal.validation_permits(transaction_id bigint PRIMARY KEY,user_id uuid NOT NULL,scope_id uuid NOT NULL);

SET LOCAL search_path=public,pg_catalog,item_supply_internal,completion_baseline_internal,pg_temp;
ALTER TABLE public.tutor_teaching_sessions ADD CONSTRAINT uq_completion_teaching_owner UNIQUE(id,user_id);
CREATE UNIQUE INDEX rag_d_finite_binding_scope ON public.rag_plan_material_bindings(id,user_id,session_id,draft_id,selection_handle,selection_digest,node_id,goal_hash,binding_digest);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_user_epochs (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL DEFAULT 1 CHECK (epoch>=1),
  enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_matrices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  matrix_hash text NOT NULL CHECK (matrix_hash ~ '^[0-9a-f]{64}$'),
  snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=262144 AND (snapshot_json->>'version') IS NOT DISTINCT FROM 'item_supply_support_matrix_v1'),
  UNIQUE (matrix_hash),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id)
);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_version text NOT NULL UNIQUE CHECK (policy_version='autonomous_evidence_policy_v2'),
  policy_hash text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
  policy_json jsonb NOT NULL CHECK (jsonb_typeof(policy_json)='object' AND octet_length(policy_json::text)<=262144 AND (policy_json->>'schema_version') IS NOT DISTINCT FROM 'autonomous_evidence_policy_v2'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id)
);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_blueprints (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_scopes (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_materials (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_candidates (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_versions (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_budget_roots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  blueprint_id uuid NOT NULL,
  canonical_key text NOT NULL CHECK (canonical_key ~ '^[0-9a-f]{64}$'),
  policy_class text NOT NULL CHECK (policy_class ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE (canonical_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (blueprint_id) REFERENCES tutor_item_supply_shared_blueprints(id) ON DELETE RESTRICT
);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_budget_windows (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_jobs (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id uuid NOT NULL,
  window_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation>0),
  reservation_key text NOT NULL CHECK (reservation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  requests integer NOT NULL CHECK(requests>=0),
  tokens bigint NOT NULL CHECK(tokens>=0),
  resources bigint NOT NULL CHECK (resources>=0),
  UNIQUE (job_id,reservation_key),
  UNIQUE (id,job_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id),
  FOREIGN KEY (window_id,root_id) REFERENCES tutor_item_supply_shared_budget_windows(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY (job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_budget_roots (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_budget_windows (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_jobs (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_job_events (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  scope_id uuid NOT NULL,
  root_id uuid NOT NULL,
  window_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation>0),
  reservation_key text NOT NULL CHECK (reservation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  requests integer NOT NULL CHECK(requests>=0),
  tokens bigint NOT NULL CHECK(tokens>=0),
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_usage_events (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_evidence (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_observations (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_proofs (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_admissions (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_demands (
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
  FOREIGN KEY (scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_results (
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
  FOREIGN KEY (demand_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_publication_refs (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_result_items (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_bindings (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_cache (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_staging (
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

-- Structural identity source 440_learning_item_supply_sandbox.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_subscriptions (
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

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_runtime_user_limits (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK (epoch>=1),
  resource_kind text NOT NULL CHECK (resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  cap_amount bigint NOT NULL CHECK ((cap_amount>0) OR (cap_amount=0 AND resource_kind IN('execution_seconds','fetches'))),
  CHECK (window_end>window_start),
  UNIQUE(user_id,epoch,resource_kind,window_start),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch)
);

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_obligations (
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
  UNIQUE(user_id,epoch,canonical_key),
  UNIQUE(root_id,user_id,epoch,scope_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(root_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_budget_roots(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_parameter_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_key_hash text NOT NULL CHECK (profile_key_hash ~ '^[0-9a-f]{64}$'),
  profile_version integer NOT NULL CHECK (profile_version>=1),
  profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('warmup','proposed','canary','stable','frozen','blocked')),
  profile_json jsonb NOT NULL CHECK (jsonb_typeof(profile_json)='object' AND octet_length(profile_json::text)<=131072 AND profile_json->>'schema_version'='execution_parameter_profile_v1'),
  UNIQUE(profile_key_hash,profile_version),
  UNIQUE(profile_hash),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_job_controls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  profile_id uuid NOT NULL REFERENCES tutor_item_supply_parameter_profiles(id) ON DELETE RESTRICT,
  state text NOT NULL CHECK (state IN ('queued','leased','generating','validating','reviewing','investigating','revising','simulating','admitting','retry_wait','preparing','blocked','completed','cancelled','superseded')),
  state_version integer NOT NULL DEFAULT 1 CHECK(state_version>=1),
  priority integer NOT NULL CHECK(priority BETWEEN 0 AND 1000),
  aging_seconds integer NOT NULL CHECK(aging_seconds BETWEEN 1 AND 86400),
  available_at timestamptz NOT NULL,
  parent_deadline timestamptz NOT NULL,
  lease_owner text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK(lease_generation>=0),
  lease_expires_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
  breaker_open boolean NOT NULL DEFAULT false,
  profile_snapshot_json jsonb NOT NULL CHECK(jsonb_typeof(profile_snapshot_json)='object' AND octet_length(profile_snapshot_json::text)<=131072),
  CHECK ((state='leased' AND lease_owner IS NOT NULL AND lease_generation>0 AND lease_expires_at IS NOT NULL) OR (state<>'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)),
  UNIQUE(job_id,user_id,epoch,scope_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  stage text NOT NULL CHECK(stage IN ('generating','validating','reviewing','investigating','revising','simulating','admitting')),
  attempt integer NOT NULL CHECK(attempt>0),
  status text NOT NULL CHECK(status IN ('completed','failed','blocked')),
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  receipt_hash text NOT NULL CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
  safe_reason text NOT NULL CHECK(safe_reason ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  UNIQUE(job_id,stage,attempt),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_runtime_reservation_amounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  limit_id uuid NOT NULL REFERENCES tutor_item_supply_private_runtime_user_limits(id) ON DELETE RESTRICT,
  resource_kind text NOT NULL CHECK(resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  reserved_amount bigint NOT NULL CHECK(reserved_amount>=0),
  UNIQUE(reservation_id,limit_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_runtime_settlements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  sequence integer NOT NULL CHECK(sequence>0),
  settlement_key text NOT NULL CHECK(settlement_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  usage_state text NOT NULL CHECK(usage_state IN ('known','unknown')),
  cost_amount numeric CHECK(cost_amount>=0),
  receipt_hash text CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
  CHECK((usage_state='unknown' AND receipt_hash IS NULL) OR (usage_state='known' AND receipt_hash IS NOT NULL)),
  UNIQUE(reservation_id,sequence),
  UNIQUE(reservation_id,settlement_key),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 450_learning_item_supply_runtime.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_runtime_settlement_amounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  settlement_id uuid NOT NULL,
  resource_kind text NOT NULL CHECK(resource_kind IN ('requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds')),
  actual_amount bigint NOT NULL CHECK(actual_amount>=0),
  UNIQUE(settlement_id,resource_kind),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,user_id,epoch),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(settlement_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_runtime_settlements(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 460_learning_item_supply_pipeline.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_generation_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  candidate_id uuid NOT NULL,
  version_id uuid NOT NULL,
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  mode text NOT NULL CHECK(mode IN ('live','synthetic')),
  source_json jsonb NOT NULL CHECK(jsonb_typeof(source_json)='object' AND octet_length(source_json::text)<=1048576 AND (source_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_source_v1'),
  request_json jsonb NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=1048576 AND (request_json->>'schema_version') IS NOT DISTINCT FROM 'item_generation_request_v2'),
  receipt_json jsonb NOT NULL CHECK(jsonb_typeof(receipt_json)='object' AND octet_length(receipt_json::text)<=65536),
  artifact_hash text GENERATED ALWAYS AS (item_supply_internal.pipeline_generation_hash(source_json,receipt_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_key),
  UNIQUE(id,user_id,epoch,scope_id,job_id,version_id,content_hash),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(candidate_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_candidates(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 460_learning_item_supply_pipeline.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_pipeline_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  generation_artifact_id uuid NOT NULL,
  version_id uuid NOT NULL,
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  artifact_kind text NOT NULL CHECK(artifact_kind IN ('validation','blind_solve','review_bundle','admission_evaluation')),
  schema_version text NOT NULL CHECK(length(schema_version) BETWEEN 1 AND 160),
  mode text NOT NULL CHECK(mode IN ('live','synthetic')),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576 AND (payload_json->>'schema_version') IS NOT DISTINCT FROM schema_version),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_kind,artifact_key),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,job_id,version_id,content_hash) ON DELETE RESTRICT
);

-- Structural identity source 470_learning_item_supply_sandbox_execution.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_execution_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  root_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version integer NOT NULL CHECK(lease_state_version>0),
  lease_owner text NOT NULL,
  profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
  generation_artifact_id uuid NOT NULL,
  version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  actor_namespace text NOT NULL CHECK(actor_namespace=('sandbox.p6.'||user_id::text)),
  reservation_key text NOT NULL CHECK(reservation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  resources_json jsonb NOT NULL CHECK(jsonb_typeof(resources_json)='object'),
  intent_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(resources_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,reservation_key),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,job_id,version_id,content_hash) ON DELETE RESTRICT
);

-- Structural identity source 470_learning_item_supply_sandbox_execution.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_sandbox_runs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  intent_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  origin text NOT NULL CHECK(origin IN ('simulation','deterministic_probe')),
  run_json jsonb NOT NULL CHECK(jsonb_typeof(run_json)='object' AND run_json->>'schema_version'='sandbox_run_v2'),
  terminal_json jsonb NOT NULL CHECK(jsonb_typeof(terminal_json)='object' AND octet_length(terminal_json::text)<=1048576),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(terminal_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(intent_id),
  UNIQUE(id,user_id,epoch,scope_id,origin),
  FOREIGN KEY(intent_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_execution_intents(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 470_learning_item_supply_sandbox_execution.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_sandbox_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  source_run uuid NOT NULL,
  origin text NOT NULL CHECK(origin IN ('simulation','deterministic_probe')),
  scenario text NOT NULL CHECK(scenario ~ '^[a-z][a-z0-9_]{0,79}$'),
  attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 1000000),
  observation_json jsonb NOT NULL CHECK(jsonb_typeof(observation_json)='object' AND octet_length(observation_json::text)<=131072),
  observation_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(observation_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(source_run,scenario,attempt),
  FOREIGN KEY(source_run,user_id,epoch,scope_id,origin) REFERENCES tutor_item_supply_private_sandbox_runs(id,user_id,epoch,scope_id,origin) ON DELETE RESTRICT
);

CREATE FUNCTION rag_actual_d_finite_storage_profile(profile text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE profile
    WHEN 'python-state-actual-d-source-v1' THEN 'python-state-source-v1'
    WHEN 'python-binding-actual-d-source-v1' THEN 'python-binding-source-v1'
    WHEN 'sqlite-predicate-actual-d-source-v1' THEN 'sqlite-predicate-source-v1'
    ELSE NULL END
$$;

CREATE FUNCTION rag_actual_d_finite_lifetime_allowed(
  signed_proof jsonb, profile_id text, issued_at timestamptz, expires_at timestamptz
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE p jsonb := signed_proof->'payload';
DECLARE q jsonb := p->'prepared';
DECLARE a jsonb := q->'actual_d';
DECLARE prepared_at timestamptz;
DECLARE authority_until timestamptz;
DECLARE companion jsonb;
BEGIN
  IF (p->>'format') IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3' OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS NULL OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS DISTINCT FROM profile_id OR
     (a->>'contract_version') IS DISTINCT FROM 'rag_actual_d_finite_source_scope_v1' OR
     (a->>'oracle_run_id') IS NULL OR
     (p->'terminal'->>'run_id') IS DISTINCT FROM a->>'oracle_run_id' OR
     (p->'terminal'->>'probe_name') IS DISTINCT FROM 'actual_d_finite_source_oracle' OR
     issued_at IS NULL OR expires_at IS NULL OR issued_at>=expires_at OR
     expires_at>issued_at+interval '168 hours' OR
     (p->>'issued_at') IS NULL OR (p->>'expires_at') IS NULL OR
     (p->>'issued_at')::timestamptz IS DISTINCT FROM issued_at OR
     (p->>'expires_at')::timestamptz IS DISTINCT FROM expires_at THEN RETURN false; END IF;
  PERFORM (a->>'oracle_run_id')::uuid;
  prepared_at := (q->>'prepared_at')::timestamptz;
  authority_until := (q->>'authority_expires_at')::timestamptz;
  IF prepared_at IS NULL OR authority_until IS NULL OR prepared_at>issued_at OR
     authority_until<expires_at OR authority_until>prepared_at+interval '168 hours' OR
     (q->'budget'->>'expires_at') IS NULL OR
     authority_until>(q->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
  IF profile_id='sqlite-predicate-source-v1' THEN
    IF jsonb_typeof(q->'companions') IS DISTINCT FROM 'array' OR
       jsonb_array_length(q->'companions')<>2 THEN RETURN false; END IF;
    FOR companion IN SELECT value FROM jsonb_array_elements(q->'companions') LOOP
      IF (companion->>'authority_expires_at') IS NULL OR
         (companion->'budget'->>'expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz<authority_until OR
         (companion->>'authority_expires_at')::timestamptz>prepared_at+interval '168 hours' OR
         (companion->>'authority_expires_at')::timestamptz IS DISTINCT FROM
           (companion->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
    END LOOP;
  ELSIF q ? 'companions' THEN RETURN false;
  END IF;
  RETURN true;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_parameter_value OR invalid_text_representation THEN
  RETURN false;
END $$;

CREATE FUNCTION rag_course_material_proof_lifetime_allowed(
  signed_proof jsonb, profile_id text, issued_at timestamptz, expires_at timestamptz
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE proof jsonb := signed_proof->'payload';
DECLARE prepared jsonb := proof->'prepared';
DECLARE prepared_at timestamptz;
DECLARE authority_expires_at timestamptz;
DECLARE companion jsonb;
BEGIN
  IF signed_proof->'payload'->>'format'='aearn.rag.actual-d-finite-source.v3' THEN
    RETURN rag_actual_d_finite_lifetime_allowed(signed_proof,profile_id,issued_at,expires_at);
  END IF;
  IF issued_at IS NULL OR expires_at IS NULL OR issued_at>=expires_at THEN RETURN false; END IF;
  IF proof->>'format'='aearn.rag.fresh-assessment-source.v1' THEN
    -- Preserve the historical signed schema's original bound, not currentness.
    RETURN expires_at<=issued_at+interval '24 hours';
  END IF;
  IF (proof->>'format') IS DISTINCT FROM 'aearn.rag.fresh-assessment-source.v2' OR
     profile_id NOT IN ('python-state-source-v1','python-binding-source-v1','sqlite-predicate-source-v1') OR
     (prepared->>'profile_id') IS DISTINCT FROM profile_id OR
     (proof->>'issued_at') IS NULL OR (proof->>'expires_at') IS NULL OR
     (proof->>'issued_at')::timestamptz IS DISTINCT FROM issued_at OR
     (proof->>'expires_at')::timestamptz IS DISTINCT FROM expires_at OR
     expires_at>issued_at+interval '168 hours' THEN RETURN false; END IF;
  prepared_at := (prepared->>'prepared_at')::timestamptz;
  authority_expires_at := (prepared->>'authority_expires_at')::timestamptz;
  IF prepared_at IS NULL OR authority_expires_at IS NULL OR
     prepared_at>issued_at OR authority_expires_at<expires_at OR
     authority_expires_at>prepared_at+interval '168 hours' OR
     (prepared->'budget'->>'expires_at') IS NULL OR
     authority_expires_at>(prepared->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
  IF profile_id='sqlite-predicate-source-v1' THEN
    IF jsonb_typeof(prepared->'companions') IS DISTINCT FROM 'array' OR
       jsonb_array_length(prepared->'companions')<>2 THEN RETURN false; END IF;
    FOR companion IN SELECT value FROM jsonb_array_elements(prepared->'companions') LOOP
      IF (companion->>'authority_expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz<authority_expires_at OR
         (companion->>'authority_expires_at')::timestamptz>prepared_at+interval '168 hours' OR
         (companion->'budget'->>'expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz IS DISTINCT FROM
           (companion->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
    END LOOP;
  END IF;
  RETURN true;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_parameter_value THEN
  RETURN false;
END $$;

-- Structural identity source 480_rag_assessment_execution_authority.sql; independent closed-business deployment policy below.
CREATE TABLE public.rag_assessment_source_evidence (
  id uuid PRIMARY KEY,
  capture_id uuid NOT NULL REFERENCES rag_registered_source_captures(id) ON DELETE RESTRICT,
  source_handle text NOT NULL CHECK (source_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  document_handle text NOT NULL UNIQUE CHECK (document_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  document_hash text NOT NULL CHECK (document_hash ~ '^[0-9a-f]{64}$'),
  policy_id text NOT NULL REFERENCES rag_registered_source_policies(policy_id) ON DELETE RESTRICT,
  policy_generation integer NOT NULL CHECK (policy_generation>=1),
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  profile_id text NOT NULL CHECK(profile_id IN('python-sum-print-source-v1','sqlite-filter-order-source-v1','python-sum-print-source-v2','python-state-source-v1','python-binding-source-v1','sqlite-predicate-source-v1')),
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  claim_hash text NOT NULL CHECK (claim_hash ~ '^[0-9a-f]{64}$'),
  execution_handle text NOT NULL UNIQUE CHECK (execution_handle ~ '^source-execution\.[0-9a-f]{32}$'),
  claim_handle text NOT NULL UNIQUE CHECK (claim_handle ~ '^source-claim\.[0-9a-f]{32}$'),
  service_key_id text NOT NULL CHECK (service_key_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  signed_proof jsonb NOT NULL CHECK (jsonb_typeof(signed_proof)='object'),
  proof_hash text NOT NULL CHECK (proof_hash ~ '^[0-9a-f]{64}$'),
  terminal_hash text NOT NULL CHECK (terminal_hash ~ '^[0-9a-f]{64}$'),
  issued_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CONSTRAINT rag_assessment_source_evidence_versioned_lifetime_check CHECK(rag_course_material_proof_lifetime_allowed(signed_proof,profile_id,issued_at,expires_at) IS TRUE),
  private_user_id uuid REFERENCES tutor_item_supply_user_epochs(user_id) ON DELETE RESTRICT,
  private_epoch bigint,
  CONSTRAINT rag_actual_d_private_owner_key UNIQUE(id,private_user_id,private_epoch),
  CONSTRAINT rag_assessment_source_evidence_capture_demand_key UNIQUE(capture_id,demand_hash),
  CONSTRAINT rag_actual_d_private_classification CHECK (
      (CASE WHEN signed_proof->'payload'->>'format'='aearn.rag.actual-d-finite-source.v3' THEN
        private_user_id IS NOT NULL AND private_epoch IS NOT NULL AND private_epoch>=1 AND
        (signed_proof->'payload'->'prepared'->'actual_d'->'draft'->>'user_id') IS NOT DISTINCT FROM private_user_id::text AND
        (signed_proof->'payload'->'prepared'->'actual_d'->>'user_epoch') IS NOT DISTINCT FROM private_epoch::text
      ELSE private_user_id IS NULL AND private_epoch IS NULL AND
        NOT (signed_proof->'payload'->'prepared' ? 'actual_d') END))
);

-- Structural identity source 481_learning_item_supply_admission_facts.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_admission_facts (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  lease_owner text NOT NULL,
  generation_artifact_id uuid NOT NULL,
  version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=1048576
    AND (payload_json->>'schema_version') IS NOT DISTINCT FROM 'issued_admission_facts_v1'
    AND (payload_json->>'publication_enabled') IS NOT DISTINCT FROM 'false'
    AND (payload_json->'coverage'->>'schema_version') IS NOT DISTINCT FROM 'pre_admission_coverage_receipt_v1'
    AND (payload_json->'ambiguity'->>'schema_version') IS NOT DISTINCT FROM 'task_ambiguity_receipt_v1'
    AND (payload_json->'coverage'->>'coverage_kind') IS NOT DISTINCT FROM 'candidate_target_mapping_not_inventory'),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  -- Only the existing reset-permit protected parent can remove this child.
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_p7_generation_exact ON public.tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,version_id);

CREATE UNIQUE INDEX idx_p7_facts_exact ON public.tutor_item_supply_private_admission_facts(id,user_id,epoch,scope_id,version_id);

CREATE UNIQUE INDEX idx_p7_evaluation_exact ON public.tutor_item_supply_private_pipeline_receipts(id,user_id,epoch,scope_id,version_id);

-- Structural identity source 485_learning_item_private_publication.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_materializations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  version_payload_hash text NOT NULL CHECK(version_payload_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=1048576
    AND payload_json->'materialization'->>'schema_version' IS NOT DISTINCT FROM 'private_practice_materialization_v1'),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL,
  UNIQUE(user_id,epoch,scope_id,version_id),
  UNIQUE(id,user_id,epoch,scope_id,version_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,version_payload_hash,scope_id)
    REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,payload_hash,scope_id) ON DELETE CASCADE
);

-- Structural identity source 485_learning_item_private_publication.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_publication_events (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  version_id uuid NOT NULL,
  generation_artifact_id uuid NOT NULL,
  facts_receipt_id uuid NOT NULL,
  evaluation_receipt_id uuid NOT NULL,
  materialization_id uuid NOT NULL,
  -- Expected proof, not an FK: insertion is materialization -> event -> proof.
  proof_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  version_payload_hash text NOT NULL CHECK(version_payload_hash ~ '^[0-9a-f]{64}$'),
  transition_key text NOT NULL CHECK(transition_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  predecessor_event_id uuid,
  state_version bigint NOT NULL CHECK(state_version>=1),
  state text NOT NULL CHECK(state IN ('published','quarantined','retired')),
  checked_at timestamptz NOT NULL,
  admission_valid_until timestamptz NOT NULL,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=65536
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'private_publication_receipt_v1'),
  request_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK((state='published' AND state_version=1 AND predecessor_event_id IS NULL AND checked_at<admission_valid_until)
    OR (state IN ('quarantined','retired') AND state_version>1 AND predecessor_event_id IS NOT NULL)),
  UNIQUE(user_id,epoch,scope_id,version_id,transition_key),
  UNIQUE(user_id,epoch,scope_id,version_id,state_version),
  UNIQUE(predecessor_event_id),
  UNIQUE(id,user_id,epoch,scope_id,version_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,version_payload_hash,scope_id)
    REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,payload_hash,scope_id) ON DELETE CASCADE,
  FOREIGN KEY(materialization_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_materializations(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(facts_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_admission_facts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(evaluation_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_pipeline_receipts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(predecessor_event_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_publication_events(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE
);

-- Structural identity source 485_learning_item_private_publication.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_publication_proofs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  version_id uuid NOT NULL,
  publication_id uuid NOT NULL,
  materialization_id uuid NOT NULL,
  generation_artifact_id uuid NOT NULL,
  facts_receipt_id uuid NOT NULL,
  evaluation_receipt_id uuid NOT NULL,
  demand_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  version_payload_hash text NOT NULL CHECK(version_payload_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=1048576
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'private_published_coverage_v1'
    AND jsonb_typeof(payload_json->'sources')='array'
    AND jsonb_array_length(payload_json->'sources') BETWEEN 1 AND 12
    AND jsonb_typeof(payload_json->'clauses')='array'
    AND jsonb_array_length(payload_json->'clauses') BETWEEN 1 AND 64),
  proof_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(publication_id),
  UNIQUE(id,user_id,epoch,scope_id,version_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,version_payload_hash,scope_id)
    REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,payload_hash,scope_id) ON DELETE CASCADE,
  FOREIGN KEY(publication_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_publication_events(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(materialization_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_materializations(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(facts_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_admission_facts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(evaluation_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_pipeline_receipts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(demand_id,user_id,epoch,scope_id)
    REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE CASCADE
);

-- Structural identity source 489_learning_item_shared_pipeline.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_generation_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  blueprint_id uuid NOT NULL REFERENCES tutor_item_supply_shared_blueprints(id) ON DELETE RESTRICT,
  job_id uuid NOT NULL,
  lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  reservation_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  item_id uuid NOT NULL,
  version_id uuid NOT NULL,
  target_id text NOT NULL CHECK(target_id IN ('python-state-update-v1','python-kc-binding-v1','sqlite-predicate-order-v1')),
  target_definition_hash text NOT NULL CHECK(target_definition_hash ~ '^[0-9a-f]{64}$'),
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  mode text NOT NULL DEFAULT 'live' CHECK(mode='live'),
  source_json jsonb NOT NULL CHECK(jsonb_typeof(source_json)='object' AND octet_length(source_json::text)<=1048576 AND (source_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_source_v1'),
  request_json jsonb NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=1048576 AND (request_json->>'schema_version') IS NOT DISTINCT FROM 'item_generation_request_v2'),
  receipt_json jsonb NOT NULL CHECK(jsonb_typeof(receipt_json)='object' AND octet_length(receipt_json::text)<=65536 AND (receipt_json->>'schema_version') IS NOT DISTINCT FROM 'item_generation_receipt_v2'),
  artifact_hash text GENERATED ALWAYS AS (item_supply_internal.shared_generation_hash(source_json,receipt_json,request_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_key),
  UNIQUE(job_id,candidate_id),
  UNIQUE(id,job_id,lease_generation,item_id,version_id,source_hash,content_hash),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);

-- Structural identity source 489_learning_item_shared_pipeline.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_pipeline_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
  lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  generation_artifact_id uuid NOT NULL,
  item_id uuid NOT NULL,
  version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  artifact_kind text NOT NULL CHECK(artifact_kind IN ('validation','blind_solve','review_bundle','admission_evaluation')),
  schema_version text NOT NULL CHECK(length(schema_version) BETWEEN 1 AND 160),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576 AND (payload_json->>'schema_version') IS NOT DISTINCT FROM schema_version),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  mode text NOT NULL DEFAULT 'live' CHECK(mode='live'),
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_kind,artifact_key),
  FOREIGN KEY(generation_artifact_id,job_id,lease_generation,item_id,version_id,source_hash,content_hash)
    REFERENCES tutor_item_supply_shared_generation_artifacts(id,job_id,lease_generation,item_id,version_id,source_hash,content_hash) ON DELETE RESTRICT,
  continuation_binding_hash text
);

-- Structural identity source 490_learning_item_shared_execution.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_validation_preparations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL,
  root_id uuid NOT NULL,
  lease_owner text NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
  generation_artifact_id uuid NOT NULL,
  item_id uuid NOT NULL,
  version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  reservation_key text CHECK(reservation_key ~ '^shared[.]execution[.][0-9a-f]{32}$'),
  resources_json jsonb,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,generation_artifact_id),
  UNIQUE(job_id,reservation_key),
  CHECK((resources_json IS NULL)=(reservation_key IS NULL)),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(generation_artifact_id,job_id,lease_generation,item_id,version_id,source_hash,content_hash)
    REFERENCES tutor_item_supply_shared_generation_artifacts(id,job_id,lease_generation,item_id,version_id,source_hash,content_hash) ON DELETE RESTRICT,
  continuation_binding_hash text
);

-- Structural identity source 490_learning_item_shared_execution.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_validation_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  preparation_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_validation_preparations(id) ON DELETE RESTRICT,
  reservation_id uuid REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Structural identity source 493_learning_item_shared_admission_facts.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_shared_admission_facts (
  id uuid PRIMARY KEY,
  root_id uuid NOT NULL,
  job_id uuid NOT NULL,
  lease_owner text NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
  generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  item_id uuid NOT NULL,
  version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  continuation_binding_hash text CHECK(continuation_binding_hash ~ '^[0-9a-f]{64}$'),
  validation_preparation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_validation_preparations(id) ON DELETE RESTRICT,
  validation_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  blind_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  review_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,generation_artifact_id),
  UNIQUE(review_receipt_id),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

-- Structural identity source 494_learning_item_native_publication.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_learning_item_native_publication_proofs (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  facts_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_admission_facts(id) ON DELETE RESTRICT,
  evaluation_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  materialization_id uuid NOT NULL REFERENCES tutor_learning_item_practice_materializations(id) DEFERRABLE INITIALLY DEFERRED,
  publication_event_id uuid NOT NULL UNIQUE REFERENCES tutor_learning_item_publication_events(id) DEFERRABLE INITIALLY DEFERRED,
  proof_json jsonb NOT NULL CHECK(jsonb_typeof(proof_json)='object' AND octet_length(proof_json::text)<=2097152
    AND (proof_json->>'schema_version') IS NOT DISTINCT FROM 'native_learning_item_publication_v1'),
  proof_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(proof_json)) STORED,
  runner_material_json jsonb NOT NULL CHECK(jsonb_typeof(runner_material_json)='object' AND octet_length(runner_material_json::text)<=2097152),
  publication_txid bigint NOT NULL DEFAULT txid_current(),
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Structural identity source 495_learning_item_native_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_exposure_births (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch=1),
  collector_version text NOT NULL CHECK(collector_version='native-exposure-v1'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch),
  UNIQUE(id,user_id,epoch)
);

-- Structural identity source 495_learning_item_native_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_exposure_inbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  origin_table text NOT NULL CHECK(origin_table IN ('tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts',
    'tutor_exercise_attempts','tutor_exercise_hint_receipts','tutor_lesson_gate_bindings')),
  origin_id uuid NOT NULL,
  version_id uuid REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK(kind IN ('shown','hint','direct_answer','attempted','metadata','untracked')),
  origin_scope_json jsonb NOT NULL CHECK(jsonb_typeof(origin_scope_json)='object' AND octet_length(origin_scope_json::text)<=2048),
  origin_hash text NOT NULL CHECK(origin_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,origin_table,origin_id),
  UNIQUE(id,user_id,epoch)
);

-- Structural identity source 495_learning_item_native_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_exposure_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  inbox_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  version_id uuid NOT NULL,
  proof_id uuid NOT NULL REFERENCES tutor_learning_item_native_publication_proofs(id) ON DELETE RESTRICT,
  binding_json jsonb NOT NULL CHECK(jsonb_typeof(binding_json)='object' AND octet_length(binding_json::text)<=8192),
  binding_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(binding_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(inbox_id,user_id,epoch) REFERENCES tutor_item_supply_native_exposure_inbox(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 495_learning_item_native_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_exposure_watermarks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  birth_id uuid NOT NULL,
  watermark bigint NOT NULL CHECK(watermark>=0),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4096),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,payload_hash),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(birth_id,user_id,epoch) REFERENCES tutor_item_supply_native_exposure_births(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 495_learning_item_native_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_exposure_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  operation_key text NOT NULL CHECK(operation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  watermark_id uuid NOT NULL,
  bindings_json jsonb NOT NULL CHECK(jsonb_typeof(bindings_json)='array' AND jsonb_array_length(bindings_json)=2
    AND octet_length(bindings_json::text)<=16384),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,operation_key),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(watermark_id,user_id,epoch) REFERENCES tutor_item_supply_native_exposure_watermarks(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 495_learning_item_native_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_exposure_deliveries (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  delivery_key text NOT NULL CHECK(delivery_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  binding_json jsonb NOT NULL CHECK(jsonb_typeof(binding_json)='object' AND octet_length(binding_json::text)<=8192),
  delivery_kind text NOT NULL DEFAULT 'practice' CHECK(delivery_kind='practice'),
  delivery_txid bigint NOT NULL DEFAULT txid_current(),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,delivery_key),
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_native_exposure_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 496_learning_item_finite_course_mapping.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_finite_course_mappings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  track_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  node_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  session_id uuid NOT NULL,
  draft_id uuid NOT NULL,
  selection_handle text NOT NULL,
  selection_digest text NOT NULL CHECK(selection_digest ~ '^[0-9a-f]{64}$'),
  assessment_binding_id uuid NOT NULL,
  binding_digest text NOT NULL CHECK(binding_digest ~ '^[0-9a-f]{64}$'),
  goal_hash text NOT NULL CHECK(goal_hash ~ '^[0-9a-f]{64}$'),
  mapping_hash text NOT NULL CHECK(mapping_hash ~ '^[0-9a-f]{64}$'),
  practice_scope_id uuid NOT NULL,
  practice_demand_id uuid NOT NULL,
  assessment_scope_id uuid NOT NULL,
  assessment_demand_id uuid NOT NULL,
  remediation_scope_id uuid NOT NULL,
  remediation_demand_id uuid NOT NULL,
  receipt_json jsonb NOT NULL CHECK(jsonb_typeof(receipt_json)='object'
    AND octet_length(receipt_json::text)<=131072
    AND receipt_json->>'schema_version'='finite_course_mapping_v1'),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(receipt_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,mapping_hash),
  UNIQUE(id,user_id,epoch),
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

-- Structural identity source 501_learning_item_native_type_evidence.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_content_facts (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  version_id uuid NOT NULL,
  proof_id uuid NOT NULL REFERENCES tutor_learning_item_native_publication_proofs(id) ON DELETE RESTRICT,
  proof_hash text NOT NULL CHECK(proof_hash ~ '^[0-9a-f]{64}$'),
  content_json jsonb NOT NULL CHECK(jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=16384),
  content_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(content_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,version_id,proof_id),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(user_id) REFERENCES tutor_item_supply_user_epochs(user_id) ON DELETE RESTRICT
);

-- Structural identity source 501_learning_item_native_type_evidence.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_relation_preparations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  mapping_receipt_id uuid NOT NULL,
  anchor_version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  root_id uuid NOT NULL,
  job_id uuid NOT NULL,
  reservation_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=262144),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
  evidence_valid_until timestamptz NOT NULL CHECK(evidence_valid_until>checked_at AND evidence_valid_until<=checked_at+interval '7 days'),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(mapping_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

-- Structural identity source 501_learning_item_native_type_evidence.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_relation_batches (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  mapping_receipt_id uuid NOT NULL,
  preparation_id uuid NOT NULL UNIQUE,
  root_id uuid NOT NULL,
  job_id uuid NOT NULL,
  reservation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(mapping_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(preparation_id,user_id,epoch) REFERENCES tutor_item_supply_native_relation_preparations(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

-- Structural identity source 501_learning_item_native_type_evidence.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_eligibility (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  mapping_receipt_id uuid NOT NULL,
  exposure_snapshot_id uuid NOT NULL,
  -- explicit502 owner verifies; NO forward FK
 request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  inputs_hash text NOT NULL CHECK(inputs_hash ~ '^[0-9a-f]{64}$'),
  snapshot_json jsonb NOT NULL CHECK (((jsonb_typeof(snapshot_json) = 'object'::text) AND (octet_length((snapshot_json)::text) <= 2097152) AND ((((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_v2'::text) OR (((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_mvp_v1'::text) AND ((snapshot_json ->> 'relation_validation'::text) = 'not_asserted_for_mvp'::text) AND ((snapshot_json -> 'relationship_receipt_hashes'::text) = '[]'::jsonb))) IS TRUE))),
  snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(snapshot_json)) STORED,
  candidate_version_ids uuid[] NOT NULL CHECK(cardinality(candidate_version_ids) BETWEEN 5 AND 16),
  relation_receipt_ids uuid[] NOT NULL CHECK ((((((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_v2'::text) AND (cardinality(relation_receipt_ids) >= 1) AND (cardinality(relation_receipt_ids) <= 16)) OR (((snapshot_json ->> 'schema_version'::text) = 'pack_snapshot_mvp_v1'::text) AND ((snapshot_json ->> 'relation_validation'::text) = 'not_asserted_for_mvp'::text) AND ((snapshot_json -> 'relationship_receipt_hashes'::text) = '[]'::jsonb) AND (cardinality(relation_receipt_ids) = 0))) IS TRUE)),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
  txid bigint NOT NULL CHECK(txid>0),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(mapping_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 502_learning_item_type_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_type_exposure_snapshots (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  original_watermark_id uuid NOT NULL,
  snapshot_json jsonb NOT NULL
    CHECK(jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=8388608),
  snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(snapshot_json)) STORED,
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK (((valid_until > checked_at) AND (((valid_until <= (checked_at + '00:02:00'::interval)) OR (((snapshot_json ->> 'collector_version'::text) = 'native-type-exposure-mvp-v1'::text) AND ((snapshot_json ->> 'schema_version'::text) = 'complete_exposure_v2'::text) AND (valid_until <= (checked_at + '00:10:00'::interval)))) IS TRUE))),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK(valid_until>checked_at AND valid_until<=checked_at+interval '30 seconds'),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(original_watermark_id,user_id,epoch)
    REFERENCES tutor_item_supply_native_exposure_watermarks(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 502_learning_item_type_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_type_exposure_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  operation_key text NOT NULL CHECK(operation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  request_json jsonb NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=1048576),
  eligibility_id uuid NOT NULL,
  exposure_snapshot_id uuid NOT NULL,
  bindings_json jsonb NOT NULL CHECK(jsonb_typeof(bindings_json)='array' AND jsonb_array_length(bindings_json)=2
    AND octet_length(bindings_json::text)<=16384),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,operation_key),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(eligibility_id,user_id,epoch) REFERENCES tutor_item_supply_native_eligibility(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_type_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 502_learning_item_type_exposure.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_type_exposure_deliveries (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  delivery_key text NOT NULL CHECK(delivery_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  binding_json jsonb NOT NULL CHECK(jsonb_typeof(binding_json)='object' AND octet_length(binding_json::text)<=8192),
  eligibility_id uuid NOT NULL,
  exposure_snapshot_id uuid NOT NULL,
  delivery_kind text NOT NULL DEFAULT 'practice' CHECK(delivery_kind='practice'),
  delivery_txid bigint NOT NULL DEFAULT txid_current(),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,delivery_key),
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id)
    REFERENCES tutor_item_supply_type_exposure_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(eligibility_id,user_id,epoch) REFERENCES tutor_item_supply_native_eligibility(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_type_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 504_rag_actual_d_private_provenance.sql; independent closed-business deployment policy below.
CREATE TABLE public.rag_actual_d_private_provenance (
  private_evidence_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  draft_id uuid NOT NULL,
  node_id text NOT NULL,
  goal_hash text NOT NULL CHECK(goal_hash ~ '^[0-9a-f]{64}$'),
  target_id text NOT NULL CHECK(target_id IN ('python-state-update-v1','python-kc-binding-v1','sqlite-predicate-order-v1')),
  public_evidence_id uuid NOT NULL REFERENCES rag_assessment_source_evidence(id) ON DELETE RESTRICT,
  corpus_id uuid NOT NULL,
  generation bigint NOT NULL CHECK(generation>=1),
  document_id text NOT NULL,
  document_hash text NOT NULL CHECK(document_hash ~ '^[0-9a-f]{64}$'),
  private_proof_hash text NOT NULL CHECK(private_proof_hash ~ '^[0-9a-f]{64}$'),
  public_proof_hash text NOT NULL CHECK(public_proof_hash ~ '^[0-9a-f]{64}$'),
  chunks_json jsonb NOT NULL CHECK(jsonb_typeof(chunks_json)='array' AND jsonb_array_length(chunks_json) BETWEEN 1 AND 16),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(private_evidence_id,user_id,epoch)
    REFERENCES rag_assessment_source_evidence(id,private_user_id,private_epoch) ON DELETE RESTRICT,
  FOREIGN KEY(corpus_id,document_id)
    REFERENCES grounding_corpus_documents(corpus_version_id,document_id) ON DELETE RESTRICT,
  CHECK(private_evidence_id<>public_evidence_id)
);

-- Structural identity source 521_learning_item_native_consumer_catalog_bridge.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_consumer_receipts (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  mode text NOT NULL CHECK(mode IN ('create','consume','cancel')),
  run_id uuid REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  artifact_id uuid REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
  artifact_version integer CHECK(artifact_version>=1),
  mapping_id uuid NOT NULL,
  version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  delivery_id uuid REFERENCES tutor_item_supply_type_exposure_deliveries(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=131072),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK (((valid_until > checked_at) AND (((valid_until <= (checked_at + '00:00:30'::interval)) OR ((((payload_json -> 'current_consumption'::text) ->> 'window_policy'::text) = 'mvp_600_seconds_v1'::text) AND (valid_until <= (checked_at + '00:10:00'::interval)))) IS TRUE))),
  txid bigint NOT NULL DEFAULT txid_current(),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK(valid_until>checked_at AND valid_until<=checked_at+interval '30 seconds'),
  CHECK((mode='create' AND run_id IS NOT NULL AND artifact_id IS NULL AND artifact_version IS NULL AND delivery_id IS NOT NULL)
   OR (mode IN ('consume','cancel') AND run_id IS NULL AND artifact_id IS NOT NULL AND artifact_version IS NOT NULL AND delivery_id IS NULL)),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(mapping_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 521_learning_item_native_consumer_catalog_bridge.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_native_artifact_bindings (
  artifact_id uuid PRIMARY KEY REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  mapping_id uuid NOT NULL,
  creation_receipt_id uuid NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(mapping_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(creation_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_native_consumer_receipts(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 523_learning_item_persistent_pack_runtime_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_persistent_pack_journal (
  id uuid PRIMARY KEY,
  pack_task_id uuid NOT NULL,
  user_id uuid NOT NULL,
  epoch integer NOT NULL CHECK(epoch>0),
  scope_id uuid NOT NULL,
  record_kind text NOT NULL CHECK(record_kind IN('task','phase','pause','stop','private_attachment','private_status','prestart_proof','prestart_binding','explicit_recovery_approval','explicit_recovery_binding','committed_revision_execution','source_mapping_successor','current_pack_source_origin')),
  operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 3 AND 200),
  intent_hash text NOT NULL CHECK(intent_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(id,user_id,epoch,scope_id),
  UNIQUE(user_id,epoch,operation_key,record_kind),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_quality_evidence (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  pack_task_id uuid NOT NULL,
  slot_id uuid NOT NULL,
  root_id uuid NOT NULL,
  version_id uuid NOT NULL,
  kind text NOT NULL CHECK(kind IN('validation','blind','review','admission','relation','investigation','normal','blind_data')),
  job_id uuid NOT NULL,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
  payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(root_id,user_id,epoch) REFERENCES tutor_item_supply_private_budget_roots(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_publications (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL,
  scope_id uuid NOT NULL,
  pack_task_id uuid NOT NULL,
  slot_id uuid NOT NULL,
  root_id uuid NOT NULL,
  version_id uuid NOT NULL,
  quality_id uuid NOT NULL,
  state text NOT NULL CHECK(state IN('published','quarantined','retired')),
  state_version integer NOT NULL CHECK(state_version>0),
  predecessor_id uuid,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
  payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  content_json jsonb NOT NULL CHECK(jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=16384),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(id,user_id,epoch,scope_id),
  UNIQUE(version_id,state_version,user_id,epoch),
  FOREIGN KEY(quality_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_quality_evidence(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(predecessor_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_publications(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_exposure_origins (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sequence bigserial NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL,
  artifact_id uuid NOT NULL REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
  version_id uuid NOT NULL,
  origin_table text NOT NULL CHECK(origin_table IN('tutor_item_supply_private_native_artifact_bindings','tutor_learning_artifact_events','tutor_knowledge_check_assistance_receipts')),
  origin_id uuid NOT NULL,
  kind text NOT NULL CHECK(kind IN('shown','hint','direct_answer','attempted','transfer')),
  binding_hash text NOT NULL CHECK(binding_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,epoch,origin_table,origin_id),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_exposure_snapshots (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL,
  public_snapshot_id uuid NOT NULL,
  private_watermark bigint NOT NULL CHECK(private_watermark>=0),
  private_count integer NOT NULL CHECK(private_count BETWEEN 0 AND 4096),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=8388608),
  payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK (((valid_until > checked_at) AND (((valid_until <= (checked_at + '00:02:00'::interval)) OR (((payload_json ->> 'collector_version'::text) = 'private-native-union-mvp-v1'::text) AND ((payload_json ->> 'schema_version'::text) = 'complete_exposure_v2'::text) AND (valid_until <= (checked_at + '00:10:00'::interval)))) IS TRUE))),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(id,user_id,epoch),
  FOREIGN KEY(public_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_type_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_eligibility (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL,
  scope_id uuid NOT NULL,
  pack_task_id uuid NOT NULL,
  mapping_id uuid NOT NULL,
  exposure_snapshot_id uuid NOT NULL,
  payload_json jsonb NOT NULL
 CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
  payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
  txid bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(mapping_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_private_native_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_assessment_reservations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL,
  scope_id uuid NOT NULL,
  pack_task_id uuid NOT NULL,
  operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 3 AND 160),
  eligibility_id uuid NOT NULL,
  exposure_snapshot_id uuid NOT NULL,
  base_reservation_id uuid NOT NULL,
  base_scope_id uuid NOT NULL,
  payload_json jsonb NOT NULL
 CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576),
  payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(id,user_id,epoch,scope_id),
  UNIQUE(user_id,epoch,operation_key),
  FOREIGN KEY(eligibility_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_eligibility(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_private_native_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(base_reservation_id,user_id,epoch,base_scope_id) REFERENCES tutor_item_supply_type_exposure_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_consumer_receipts (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL,
  scope_id uuid NOT NULL,
  pack_task_id uuid NOT NULL,
  mode text NOT NULL CHECK(mode IN('create','current','cancel')),
  action text CHECK(action IN('request_hint','request_direct_answer','respond','cancel')),
  run_id uuid REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  artifact_id uuid REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
  artifact_version integer,
  version_id uuid NOT NULL,
  reservation_id uuid,
  eligibility_id uuid,
  exposure_snapshot_id uuid,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576),
  payload_hash text GENERATED ALWAYS AS(item_supply_internal.snapshot_hash(payload_json)) STORED,
  checked_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
  txid bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(pack_task_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_persistent_pack_journal(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_assessment_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(eligibility_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_eligibility(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(exposure_snapshot_id,user_id,epoch) REFERENCES tutor_item_supply_private_native_exposure_snapshots(id,user_id,epoch) ON DELETE RESTRICT,
  CHECK((mode='create' AND action IS NULL AND artifact_id IS NULL AND run_id IS NOT NULL AND reservation_id IS NOT NULL AND eligibility_id IS NOT NULL AND exposure_snapshot_id IS NOT NULL)
 OR(mode IN('current','cancel') AND artifact_id IS NOT NULL AND artifact_version IS NOT NULL AND action IS NOT NULL AND (mode='cancel')=(action='cancel')))
);

-- Structural identity source 524_learning_item_private_native_pack_authority_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_native_artifact_bindings (
  artifact_id uuid PRIMARY KEY REFERENCES tutor_learning_artifacts(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL,
  scope_id uuid NOT NULL,
  pack_task_id uuid NOT NULL,
  version_id uuid NOT NULL,
  creation_receipt_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(artifact_id,user_id,epoch),
  FOREIGN KEY(creation_receipt_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_native_consumer_receipts(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch) ON DELETE RESTRICT
);

-- Structural identity source 551_learning_item_private_development_model_accounting_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_development_model_accounting_batches (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  root_id uuid NOT NULL,
  window_id uuid NOT NULL UNIQUE,
  provider_key text NOT NULL CHECK(provider_key='deepseek'),
  model text NOT NULL CHECK(model='deepseek-flash'),
  authorization_key text NOT NULL CHECK(authorization_key='development-unlimited-model-calls-20261010'),
  global_limit_ids uuid[] NOT NULL CHECK(array_ndims(global_limit_ids)=1 AND cardinality(global_limit_ids)=32 AND array_position(global_limit_ids,NULL) IS NULL),
  user_limit_ids uuid[] NOT NULL CHECK(array_ndims(user_limit_ids)=1 AND cardinality(user_limit_ids)=8 AND array_position(user_limit_ids,NULL) IS NULL),
  started_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL,
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

-- Structural identity source 551_learning_item_private_development_model_accounting_v1.sql; independent closed-business deployment policy below.
CREATE TABLE public.tutor_item_supply_private_development_model_accounting_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1),
  scope_id uuid NOT NULL,
  root_id uuid NOT NULL,
  window_id uuid NOT NULL,
  job_id uuid NOT NULL UNIQUE,
  batch_id uuid NOT NULL,
  parent_job_id uuid,
  lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
  lease_generation integer NOT NULL CHECK(lease_generation=1),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
  parent_deadline timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(batch_id,user_id,epoch,scope_id,root_id,window_id) REFERENCES tutor_item_supply_private_development_model_accounting_batches(id,user_id,epoch,scope_id,root_id,window_id) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_job_controls(job_id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(parent_job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT
);

-- Additional exact resource ownership guarantees (450 terminal structure).
ALTER TABLE public.tutor_item_supply_private_runtime_user_limits ADD CONSTRAINT supply_runtime_limit_owner_resource UNIQUE(id,user_id,epoch,resource_kind);
ALTER TABLE public.tutor_item_supply_private_runtime_reservation_amounts ADD CONSTRAINT supply_runtime_allocation_owner_resource
 FOREIGN KEY(limit_id,user_id,epoch,resource_kind) REFERENCES public.tutor_item_supply_private_runtime_user_limits(id,user_id,epoch,resource_kind) ON DELETE RESTRICT;
ALTER TABLE public.tutor_item_supply_private_runtime_settlements ADD CONSTRAINT supply_runtime_unknown_cost CHECK(usage_state<>'unknown' OR cost_amount IS NULL);
ALTER TABLE public.tutor_item_supply_private_runtime_reservation_amounts ADD CONSTRAINT supply_runtime_reserved_nonnegative CHECK(reserved_amount>=0);
-- Existing ordinary domains stay intact; private/native additions are closed by
-- explicit policy triggers, not by absent receiving functions.
ALTER TABLE public.tutor_knowledge_check_response_receipts
 ADD COLUMN private_native_version_id uuid, ADD COLUMN private_native_epoch bigint, ADD COLUMN private_native_scope_id uuid,
 ALTER COLUMN learning_item_version_id DROP NOT NULL,
 ADD CONSTRAINT chk_private_native_kc_response_domain CHECK(
 (learning_item_version_id IS NOT NULL AND num_nonnulls(private_native_version_id,private_native_epoch,private_native_scope_id)=0) OR
 (learning_item_version_id IS NULL AND num_nonnulls(private_native_version_id,private_native_epoch,private_native_scope_id)=3 AND private_native_epoch>=1)),
 ADD CONSTRAINT fk_private_native_kc_response_version FOREIGN KEY(private_native_version_id,user_id,private_native_epoch,private_native_scope_id)
 REFERENCES public.tutor_item_supply_private_versions(id,user_id,epoch,scope_id) ON DELETE RESTRICT;
ALTER TABLE public.rag_source_reviews ADD COLUMN assessment_evidence_id uuid REFERENCES public.rag_assessment_source_evidence(id) ON DELETE RESTRICT;
ALTER TABLE public.rag_source_claim_receipts ADD COLUMN assessment_evidence_id uuid REFERENCES public.rag_assessment_source_evidence(id) ON DELETE RESTRICT;

-- Preserved lifecycle receiver: 440_learning_item_supply_sandbox.sql
CREATE FUNCTION item_supply_internal.permitted(target_user uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT EXISTS(SELECT 1 FROM item_supply_internal.reset_permits
    WHERE transaction_id=txid_current() AND user_id=target_user)
$$;

-- Preserved lifecycle receiver: 440_learning_item_supply_sandbox.sql
CREATE FUNCTION enforce_item_supply_epoch() RETURNS trigger
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

-- Preserved lifecycle receiver: 440_learning_item_supply_sandbox.sql
CREATE FUNCTION enforce_item_supply_private_epoch() RETURNS trigger
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

-- Preserved lifecycle receiver: 440_learning_item_supply_sandbox.sql
CREATE FUNCTION enforce_item_supply_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' AND TG_ARGV[0]='private' THEN
    IF item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
  END IF;
  RAISE check_violation USING MESSAGE='immutable supply evidence';
END $$;

-- Preserved lifecycle receiver: 440_learning_item_supply_sandbox.sql
CREATE FUNCTION enforce_item_supply_shared_snapshot() RETURNS trigger
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

-- Preserved lifecycle receiver: 495_learning_item_native_exposure.sql
CREATE FUNCTION capture_native_exposure_birth() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(NEW.id) ON CONFLICT DO NOTHING;
  INSERT INTO tutor_item_supply_native_exposure_births(user_id,epoch,collector_version)
    VALUES(NEW.id,1,'native-exposure-v1');
  RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 495_learning_item_native_exposure.sql
CREATE FUNCTION item_supply_internal.native_exposure_lock(u uuid, e bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  PERFORM 1 FROM users WHERE id=u AND deleted_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native exposure owner unavailable'; END IF;
  PERFORM 1 FROM tutor_item_supply_user_epochs WHERE user_id=u AND epoch=e AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native exposure epoch stale'; END IF;
  PERFORM pg_advisory_xact_lock(hashtext('native-exposure'),hashtext(u::text));
END $$;

CREATE FUNCTION capture_native_exposure_origin() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE e bigint; a record; artifact_uuid uuid; b record; v uuid; k text; coordinates jsonb; raw jsonb:=to_jsonb(NEW); slot text; revision uuid;
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
      artifact_uuid:=a.id;
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
  -- Native consumer execution is outside this contract, including synthetic IDs.
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_versions WHERE id=v)
   OR EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs WHERE version_id=v)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=artifact_uuid AND user_id=NEW.user_id) THEN
    RAISE EXCEPTION 'completion baseline: P2/P7 native consumer denied' USING ERRCODE='42501';
  END IF;
  INSERT INTO tutor_item_supply_native_exposure_inbox(user_id,epoch,origin_table,origin_id,version_id,kind,origin_scope_json,origin_hash)
    VALUES(NEW.user_id,e,TG_TABLE_NAME,NEW.id,v,k,coordinates,item_supply_internal.snapshot_hash(raw)) ON CONFLICT DO NOTHING;
  RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 495_learning_item_native_exposure.sql
CREATE FUNCTION item_supply_internal.native_exposure_hooks_current() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT count(*)=6 FROM pg_trigger WHERE NOT tgisinternal AND tgenabled IN ('O','A') AND (
    (tgrelid='users'::regclass AND tgname='native_exposure_birth_capture' AND tgfoid='capture_native_exposure_birth()'::regprocedure)
    OR (tgrelid=ANY(ARRAY['tutor_learning_artifact_events'::regclass,'tutor_knowledge_check_assistance_receipts'::regclass,
      'tutor_exercise_attempts'::regclass,'tutor_exercise_hint_receipts'::regclass,'tutor_lesson_gate_bindings'::regclass])
      AND tgname='native_exposure_origin_capture' AND tgfoid='capture_native_exposure_origin()'::regprocedure))
$$;

-- Preserved lifecycle receiver: 495_learning_item_native_exposure.sql
CREATE FUNCTION item_supply_internal.purge_native_exposure_private(target_user uuid) RETURNS void
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

-- Preserved lifecycle receiver: 495_learning_item_native_exposure.sql
CREATE FUNCTION purge_native_exposure_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
    OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='native exposure reset requires permitted epoch advance';
  END IF;
  PERFORM item_supply_internal.purge_native_exposure_private(NEW.user_id);
  RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 496_learning_item_finite_course_mapping.sql
CREATE FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
    OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='finite mapping reset requires original permitted epoch advance';
  END IF;
  DELETE FROM tutor_item_supply_finite_course_mappings WHERE user_id=NEW.user_id;
  RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 501_learning_item_native_type_evidence.sql
CREATE FUNCTION item_supply_internal.purge_native_type_evidence_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
   OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native type reset requires original permitted epoch advance';
 END IF;
 DELETE FROM tutor_item_supply_native_eligibility WHERE user_id=NEW.user_id;
 DELETE FROM tutor_item_supply_native_relation_batches WHERE user_id=NEW.user_id;
 DELETE FROM tutor_item_supply_native_relation_preparations WHERE user_id=NEW.user_id;
 DELETE FROM tutor_item_supply_native_content_facts WHERE user_id=NEW.user_id;
 RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 502_learning_item_type_exposure.sql
CREATE FUNCTION item_supply_internal.purge_type_exposure_private(target_user uuid) RETURNS void
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

-- Preserved lifecycle receiver: 502_learning_item_type_exposure.sql
CREATE FUNCTION purge_type_exposure_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
    OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='type exposure reset requires original epoch permit';
  END IF;
  PERFORM item_supply_internal.purge_type_exposure_private(NEW.user_id);
  RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 521_learning_item_native_consumer_catalog_bridge.sql
CREATE FUNCTION item_supply_internal.purge_native_consumer_private(target_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF item_supply_internal.permitted(target_user) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native consumer purge requires original maintenance capability';
 END IF;
 -- Every receipt mode may be referenced by creation_receipt_id. Remove the
 -- same-user binding children first; immutable/FK/permit guards remain active.
 DELETE FROM tutor_item_supply_native_artifact_bindings WHERE user_id=target_user;
 DELETE FROM tutor_item_supply_native_consumer_receipts WHERE user_id=target_user;
END $$;

-- Preserved lifecycle receiver: 521_learning_item_native_consumer_catalog_bridge.sql
CREATE FUNCTION purge_native_consumer_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
   OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native consumer reset requires original permitted epoch advance';
 END IF;
 PERFORM item_supply_internal.purge_native_consumer_private(NEW.user_id);
 RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 523_learning_item_persistent_pack_runtime_v1.sql
CREATE FUNCTION item_supply_internal.purge_persistent_pack_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch<>OLD.epoch+1
  OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='523 original permitted epoch advance required'; END IF;
 -- SQL524 PRIVATE evidence/attachments must purge BEFORE this header trigger.
 DELETE FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=NEW.user_id AND record_kind<>'task';
 DELETE FROM tutor_item_supply_private_persistent_pack_journal WHERE user_id=NEW.user_id AND record_kind='task';
 RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 524_learning_item_private_native_pack_authority_v1.sql
CREATE FUNCTION item_supply_internal.purge_private_native_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE owned_exercises uuid[];
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch<>OLD.epoch+1
  OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 original maintenance epoch permit required'; END IF;
 SELECT array_agg(DISTINCT exercise_version_id) INTO owned_exercises FROM tutor_item_supply_private_native_publications WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_consumer_receipts WHERE user_id=OLD.user_id AND mode<>'create';
 DELETE FROM tutor_item_supply_private_native_artifact_bindings WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_consumer_receipts WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_assessment_reservations WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_eligibility WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_exposure_snapshots WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_exposure_origins WHERE user_id=OLD.user_id;
 DELETE FROM tutor_item_supply_private_native_publications WHERE user_id=OLD.user_id;
 -- Quality still proves PRIVATE ownership while original immutable guards check
 -- the actual maintenance permit. Any foreign/public dependency aborts reset.
 DELETE FROM tutor_exercise_private_rubrics WHERE exercise_version_id=ANY(owned_exercises);
 DELETE FROM tutor_exercise_versions WHERE id=ANY(owned_exercises);
 DELETE FROM tutor_item_supply_private_native_quality_evidence WHERE user_id=OLD.user_id;
 RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 503_rag_actual_d_private_lifecycle.sql
CREATE FUNCTION rag_actual_d_private_epoch(target_user uuid, expected_epoch bigint, nonblocking boolean)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE current_epoch bigint;
BEGIN
  PERFORM * FROM completion_baseline_internal.contract_identity();
  IF target_user IS NULL OR (expected_epoch IS NOT NULL AND expected_epoch<1) OR nonblocking IS NULL THEN
    RAISE check_violation USING MESSAGE='actual D private owner context invalid';
  END IF;
  IF nonblocking THEN
    PERFORM id FROM users WHERE id=target_user AND deleted_at IS NULL FOR SHARE NOWAIT;
  ELSE
    PERFORM id FROM users WHERE id=target_user AND deleted_at IS NULL FOR SHARE;
  END IF;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='actual D private active owner missing'; END IF;
  IF nonblocking THEN
    SELECT epoch INTO current_epoch FROM tutor_item_supply_user_epochs WHERE user_id=target_user AND enabled FOR SHARE NOWAIT;
  ELSE
    SELECT epoch INTO current_epoch FROM tutor_item_supply_user_epochs WHERE user_id=target_user AND enabled FOR SHARE;
  END IF;
  IF NOT FOUND OR (expected_epoch IS NOT NULL AND current_epoch IS DISTINCT FROM expected_epoch) THEN
    RAISE check_violation USING MESSAGE='actual D private epoch stale';
  END IF;
  IF item_supply_internal.permitted(target_user) THEN
    RAISE check_violation USING MESSAGE='actual D private reset in progress';
  END IF;
  RETURN current_epoch;
END $$;

-- Preserved lifecycle receiver: 503_rag_actual_d_private_lifecycle.sql
CREATE FUNCTION rag_actual_d_private_delete_allowed(evidence_id uuid) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM rag_assessment_source_evidence e JOIN tutor_item_supply_user_epochs u
    ON u.user_id=e.private_user_id WHERE e.id=evidence_id AND
    e.signed_proof->'payload'->>'format'='aearn.rag.actual-d-finite-source.v3' AND
    u.epoch>e.private_epoch AND item_supply_internal.permitted(e.private_user_id))
$$;

-- Preserved lifecycle receiver: 503_rag_actual_d_private_lifecycle.sql
CREATE FUNCTION rag_actual_d_private_purge(target_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE active_epoch bigint;
BEGIN
  PERFORM * FROM completion_baseline_internal.contract_identity();
  IF target_user IS NULL THEN RAISE check_violation USING MESSAGE='actual D private purge owner missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=target_user) THEN RETURN; END IF;
  SELECT epoch INTO active_epoch FROM tutor_item_supply_user_epochs WHERE user_id=target_user FOR SHARE;
  IF target_user IS NULL OR active_epoch IS NULL OR item_supply_internal.permitted(target_user) IS DISTINCT FROM true OR
    EXISTS (SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=target_user AND private_epoch>=active_epoch) THEN
    RAISE check_violation USING MESSAGE='actual D tail requires original permitted advanced epoch';
  END IF;
  IF EXISTS (SELECT 1 FROM rag_plan_material_bindings WHERE user_id=target_user) OR
     EXISTS (SELECT 1 FROM rag_material_semantic_reviews WHERE user_id=target_user) OR
     EXISTS (SELECT 1 FROM rag_material_selections WHERE user_id=target_user) THEN
    RAISE check_violation USING MESSAGE='actual D source purge requires original D children first';
  END IF;
  -- No DELETE on corpus/link history: invalid shared references are blocked at
  -- creation; an unexpected historical FK still denies/rolls back this purge.
  IF to_regclass('public.rag_actual_d_private_provenance') IS NOT NULL THEN
    EXECUTE 'DELETE FROM public.rag_actual_d_private_provenance WHERE user_id=$1 AND epoch<$2'
      USING target_user,active_epoch;
  END IF;
  DELETE FROM rag_source_claim_receipts c USING rag_assessment_source_evidence e
    WHERE c.assessment_evidence_id=e.id AND e.private_user_id=target_user AND e.private_epoch<active_epoch;
  DELETE FROM rag_source_admissions a USING rag_source_reviews r,rag_assessment_source_evidence e
    WHERE a.review_id=r.id AND r.assessment_evidence_id=e.id AND e.private_user_id=target_user AND e.private_epoch<active_epoch;
  DELETE FROM rag_source_reviews r USING rag_assessment_source_evidence e
    WHERE r.assessment_evidence_id=e.id AND e.private_user_id=target_user AND e.private_epoch<active_epoch;
  DELETE FROM rag_assessment_source_evidence WHERE private_user_id=target_user AND private_epoch<active_epoch;
  DELETE FROM item_supply_internal.reset_permits WHERE transaction_id=txid_current() AND user_id=target_user;
END $$;

-- Preserved lifecycle receiver: 527_learning_item_private_native_phase_continuation_v1.sql
CREATE FUNCTION item_supply_internal.purge_private_native_kc_on_epoch() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.epoch IS DISTINCT FROM OLD.epoch THEN
  IF item_supply_internal.permitted(OLD.user_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='527 real maintenance owner required for PRIVATE KC purge'; END IF;
  DELETE FROM tutor_knowledge_check_response_receipts WHERE user_id=OLD.user_id AND private_native_epoch=OLD.epoch;
 END IF;
 RETURN NEW;
END $$;

-- Preserved lifecycle receiver: 551_learning_item_private_development_model_accounting_v1.sql
CREATE FUNCTION item_supply_internal.purge_private_development_accounting_on_epoch_advance() RETURNS trigger
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

-- Preserved lifecycle receiver: 503_rag_actual_d_private_lifecycle.sql
CREATE FUNCTION item_supply_internal.assert_actual_d_private_reset_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=NEW.user_id AND private_epoch<NEW.epoch) OR
    item_supply_internal.permitted(NEW.user_id) THEN
    RAISE check_violation USING MESSAGE='actual D original reset tail incomplete';
  END IF;
  RETURN NULL;
END $$;

-- Preserved lifecycle receiver: 503_rag_actual_d_private_lifecycle.sql
CREATE FUNCTION rag_actual_d_private_reference_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE refs text[];
DECLARE e rag_assessment_source_evidence%ROWTYPE;
DECLARE owner_text text := to_jsonb(NEW)->>'user_id';
BEGIN
  SELECT array_agg(value #>> '{}') INTO refs FROM jsonb_path_query(to_jsonb(NEW),'$.** ? (@.type() == "string")') AS scalars(value);
  FOR e IN SELECT * FROM rag_assessment_source_evidence WHERE private_user_id IS NOT NULL AND
    ARRAY[id::text,document_handle,execution_handle,claim_handle,proof_hash,demand_hash,
      signed_proof->'payload'->>'review_id',signed_proof->'payload'->>'admission_id',
      signed_proof->'payload'->>'claim_id',signed_proof->'payload'->>'admission_handle'] && refs FOR SHARE LOOP
    IF owner_text IS NULL THEN
      RAISE check_violation USING MESSAGE='actual D private reference to shared corpus blocked';
    END IF;
    IF owner_text IS DISTINCT FROM e.private_user_id::text THEN
      RAISE check_violation USING MESSAGE='actual D private cross owner reference denied';
    END IF;
    PERFORM rag_actual_d_private_epoch(e.private_user_id,e.private_epoch,true);
  END LOOP;
  RETURN NEW;
END $$;

CREATE FUNCTION purge_item_supply_private(target_user uuid, deleting boolean DEFAULT false)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE new_epoch bigint;
BEGIN
  PERFORM * FROM completion_baseline_internal.contract_identity();
  PERFORM 1 FROM users WHERE id=target_user AND deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='supply user unavailable'; END IF;
  INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(target_user) ON CONFLICT DO NOTHING;
  INSERT INTO item_supply_internal.reset_permits VALUES(txid_current(),target_user);
  UPDATE tutor_item_supply_user_epochs SET epoch=epoch+1,enabled=NOT deleting,updated_at=now() WHERE user_id=target_user RETURNING epoch INTO new_epoch;
  UPDATE tutor_item_supply_private_job_controls SET state='cancelled',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL WHERE user_id=target_user AND state NOT IN ('completed','cancelled','superseded');
  UPDATE tutor_item_supply_private_jobs SET state='cancelled',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL,terminal_at=now() WHERE user_id=target_user AND state NOT IN ('completed','failed','cancelled');
  UPDATE tutor_item_supply_private_bindings SET state='invalidated',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  UPDATE tutor_item_supply_private_subscriptions SET state='cancelled',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  DELETE FROM tutor_item_supply_private_sandbox_observations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_sandbox_runs WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_execution_intents WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_pipeline_receipts WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_generation_artifacts WHERE user_id=target_user;
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
  -- Same original503 two-stage maintenance permit; no second purge capability.
  IF NOT EXISTS(SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=target_user) THEN
  DELETE FROM item_supply_internal.reset_permits WHERE transaction_id=txid_current() AND user_id=target_user;
  END IF;
  RETURN new_epoch;
END $$;

CREATE FUNCTION completion_baseline_internal.validation_allowed(u uuid,scope uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,completion_baseline_internal,pg_temp AS $$
 SELECT session_user='aearn_cb_verifier_20261027' AND current_setting('role') IN('none','aearn_cb_verifier_20261027')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() WHERE purpose='storage-validation-purpose')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.validation_permits p
   WHERE p.transaction_id=txid_current() AND p.user_id=u AND p.scope_id=scope)
$$;
CREATE FUNCTION completion_baseline_internal.enforce_closed_storage() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE r jsonb; u uuid; s uuid;
BEGIN
 PERFORM * FROM completion_baseline_internal.contract_identity();
 IF TG_TABLE_NAME='installation_identity' THEN
  RAISE EXCEPTION 'completion baseline: installation identity immutable' USING ERRCODE='42501';
 END IF;
 r:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 u:=(r->>'user_id')::uuid; s:=CASE WHEN TG_TABLE_NAME='tutor_item_supply_private_scopes' THEN (r->>'id')::uuid ELSE (r->>'scope_id')::uuid END;
 -- Maintenance permits authorize only UPDATE/DELETE within the original user TOP.
 IF TG_OP IN('UPDATE','DELETE') AND u IS NOT NULL AND item_supply_internal.permitted(u) THEN
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
 IF TG_OP='INSERT' AND TG_TABLE_NAME IN('tutor_item_supply_private_scopes','tutor_item_supply_private_materials',
    'tutor_item_supply_private_candidates','tutor_item_supply_private_versions','tutor_item_supply_private_persistent_pack_journal')
  AND completion_baseline_internal.validation_allowed(u,s) THEN RETURN NEW; END IF;
 -- The fixed validation receiver may retain only its one non-business SHARED matrix.
 IF TG_OP='INSERT' AND TG_TABLE_NAME='tutor_item_supply_shared_matrices'
  AND session_user='aearn_cb_verifier_20261027' AND current_setting('role') IN('none','aearn_cb_verifier_20261027')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.contract_identity() WHERE purpose='storage-validation-purpose')
  AND EXISTS(SELECT 1 FROM completion_baseline_internal.validation_permits WHERE transaction_id=txid_current()) THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'completion baseline: P2/P7 business storage denied: % %',TG_TABLE_NAME,TG_OP USING ERRCODE='42501';
END $$;
CREATE FUNCTION completion_baseline_internal.enforce_technical_origin() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE origin jsonb;
BEGIN
 PERFORM * FROM completion_baseline_internal.contract_identity();
 IF TG_OP='DELETE' AND item_supply_internal.permitted(OLD.user_id) THEN RETURN OLD; END IF;
 IF TG_OP<>'INSERT' OR pg_trigger_depth()<2 THEN
  RAISE EXCEPTION 'completion baseline: only concrete origin triggers may append technical audit' USING ERRCODE='42501'; END IF;
 PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,NEW.epoch);
 IF TG_TABLE_NAME='tutor_item_supply_native_exposure_births' THEN
  IF NEW.epoch<>1 OR NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.user_id AND deleted_at IS NULL) THEN
   RAISE EXCEPTION 'completion baseline: real new-user birth required' USING ERRCODE='23514'; END IF;
 ELSE
  CASE NEW.origin_table
   WHEN 'tutor_learning_artifact_events' THEN SELECT to_jsonb(t) INTO origin FROM tutor_learning_artifact_events t WHERE id=NEW.origin_id AND user_id=NEW.user_id;
   WHEN 'tutor_knowledge_check_assistance_receipts' THEN SELECT to_jsonb(t) INTO origin FROM tutor_knowledge_check_assistance_receipts t WHERE id=NEW.origin_id AND user_id=NEW.user_id;
   WHEN 'tutor_exercise_attempts' THEN SELECT to_jsonb(t) INTO origin FROM tutor_exercise_attempts t WHERE id=NEW.origin_id AND user_id=NEW.user_id;
   WHEN 'tutor_exercise_hint_receipts' THEN SELECT to_jsonb(t) INTO origin FROM tutor_exercise_hint_receipts t WHERE id=NEW.origin_id AND user_id=NEW.user_id;
   WHEN 'tutor_lesson_gate_bindings' THEN SELECT to_jsonb(t) INTO origin FROM tutor_lesson_gate_bindings t WHERE id=NEW.origin_id AND user_id=NEW.user_id;
   ELSE RAISE EXCEPTION 'completion baseline: unknown concrete origin' USING ERRCODE='23514';
  END CASE;
  IF origin IS NULL OR NEW.origin_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(origin) THEN
   RAISE EXCEPTION 'completion baseline: original event/hash mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION completion_baseline_internal.enforce_closed_native_consumer() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
DECLARE r jsonb:=to_jsonb(NEW); owner_uuid uuid;
BEGIN
 PERFORM * FROM completion_baseline_internal.contract_identity();
 IF TG_TABLE_NAME IN('rag_source_reviews','rag_source_claim_receipts') AND r->>'assessment_evidence_id' IS NOT NULL THEN
  RAISE EXCEPTION 'completion baseline: new source/assessment authority denied' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='rag_source_admissions' AND EXISTS(SELECT 1 FROM rag_source_reviews WHERE id=(r->>'review_id')::uuid AND assessment_evidence_id IS NOT NULL) THEN
  RAISE EXCEPTION 'completion baseline: source admission denied' USING ERRCODE='42501'; END IF;
 IF r->>'private_native_version_id' IS NOT NULL OR r->>'native_generation_artifact_id' IS NOT NULL
  OR r->>'schema_version'='candidate_validation_v2' THEN
  RAISE EXCEPTION 'completion baseline: native receiving domain denied' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='tutor_learning_artifacts' AND r->>'owner_kind'='learning_item' THEN owner_uuid:=(r->>'owner_id')::uuid;
 ELSIF TG_TABLE_NAME IN('tutor_learning_item_publication_events','tutor_learning_item_practice_materializations') THEN owner_uuid:=(r->>'version_id')::uuid;
 ELSIF TG_TABLE_NAME='tutor_knowledge_check_response_receipts' THEN owner_uuid:=(r->>'learning_item_version_id')::uuid; END IF;
 IF owner_uuid IS NOT NULL AND (EXISTS(SELECT 1 FROM tutor_item_supply_private_versions WHERE id=owner_uuid)
  OR EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs WHERE version_id=owner_uuid)) THEN
  RAISE EXCEPTION 'completion baseline: P2/P7 original consumer denied' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION completion_baseline_internal.enforce_source_evidence_closed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  IF TG_TABLE_NAME='rag_assessment_source_evidence' AND rag_actual_d_private_delete_allowed((to_jsonb(OLD)->>'id')::uuid) THEN RETURN OLD; END IF;
  IF TG_TABLE_NAME='rag_actual_d_private_provenance' AND item_supply_internal.permitted((to_jsonb(OLD)->>'user_id')::uuid)
    AND EXISTS(SELECT 1 FROM tutor_item_supply_user_epochs WHERE user_id=(to_jsonb(OLD)->>'user_id')::uuid AND epoch>(to_jsonb(OLD)->>'epoch')::bigint) THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'completion baseline: source facts cannot be issued or modified' USING ERRCODE='42501';
END $$;

DO $exact_base$
BEGIN
 IF pg_get_functiondef('public.rag_source_review_guard()'::regprocedure) IS DISTINCT FROM $expected$CREATE OR REPLACE FUNCTION public.rag_source_review_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE original_hash text;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'source review immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.registered_capture_id IS NOT NULL THEN
    SELECT capture.fetched_sha256 INTO original_hash
      FROM rag_registered_source_captures capture
      WHERE capture.id=NEW.registered_capture_id AND capture.cleared_at IS NULL
        AND capture.captured_body IS NOT NULL;
    SELECT policy.* INTO policy_row FROM rag_registered_source_policies policy
      JOIN rag_registered_source_captures capture ON capture.policy_id=policy.policy_id
        AND capture.generation=policy.generation
      WHERE capture.id=NEW.registered_capture_id;
    IF policy_row.policy_id IS NULL OR NEW.source_handle<>policy_row.source_handle OR
       NEW.subject_id<>policy_row.subject_id OR
       NEW.subject_version<>policy_row.subject_version OR
       NOT NEW.facets <@ policy_row.facets OR
       NEW.origin<>policy_row.origin OR NEW.reading_level<>policy_row.reading_level OR
       NEW.license_id<>policy_row.license_id OR
       NEW.policy_id<>policy_row.policy_id OR
       NEW.policy_generation<>policy_row.generation OR
       NEW.root_id<>policy_row.root_id OR
       NOT NEW.allowed_usages <@ policy_row.allowed_usages OR
       (NEW.immutable_history_allowed AND NOT policy_row.immutable_history_allowed) OR
       (NEW.status='reviewed' AND (policy_row.enabled IS NOT TRUE OR
            policy_row.revoked_at IS NOT NULL OR policy_row.expires_at<=clock_timestamp())) THEN
      RAISE EXCEPTION 'review source scope or permission mismatch' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT full_sha256 INTO original_hash FROM rag_candidate_captures
      WHERE id=NEW.candidate_capture_id AND capture_kind='full' AND cleared_at IS NULL;
  END IF;
  IF original_hash IS NULL OR original_hash<>NEW.document_hash THEN
    RAISE EXCEPTION 'review document hash mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $function$
$expected$ THEN
  RAISE EXCEPTION 'completion baseline: original deployed rag_source_review_guard changed' USING ERRCODE='23514';
 END IF;
END $exact_base$;

CREATE OR REPLACE FUNCTION public.rag_source_review_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE original_hash text;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
BEGIN
  -- Independent forward503 maintenance branch; original INSERT/UPDATE body unchanged.
  IF TG_OP='DELETE' AND rag_actual_d_private_delete_allowed(OLD.assessment_evidence_id) THEN RETURN OLD; END IF;
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'source review immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.registered_capture_id IS NOT NULL THEN
    SELECT capture.fetched_sha256 INTO original_hash
      FROM rag_registered_source_captures capture
      WHERE capture.id=NEW.registered_capture_id AND capture.cleared_at IS NULL
        AND capture.captured_body IS NOT NULL;
    SELECT policy.* INTO policy_row FROM rag_registered_source_policies policy
      JOIN rag_registered_source_captures capture ON capture.policy_id=policy.policy_id
        AND capture.generation=policy.generation
      WHERE capture.id=NEW.registered_capture_id;
    IF policy_row.policy_id IS NULL OR NEW.source_handle<>policy_row.source_handle OR
       NEW.subject_id<>policy_row.subject_id OR
       NEW.subject_version<>policy_row.subject_version OR
       NOT NEW.facets <@ policy_row.facets OR
       NEW.origin<>policy_row.origin OR NEW.reading_level<>policy_row.reading_level OR
       NEW.license_id<>policy_row.license_id OR
       NEW.policy_id<>policy_row.policy_id OR
       NEW.policy_generation<>policy_row.generation OR
       NEW.root_id<>policy_row.root_id OR
       NOT NEW.allowed_usages <@ policy_row.allowed_usages OR
       (NEW.immutable_history_allowed AND NOT policy_row.immutable_history_allowed) OR
       (NEW.status='reviewed' AND (policy_row.enabled IS NOT TRUE OR
            policy_row.revoked_at IS NOT NULL OR policy_row.expires_at<=clock_timestamp())) THEN
      RAISE EXCEPTION 'review source scope or permission mismatch' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT full_sha256 INTO original_hash FROM rag_candidate_captures
      WHERE id=NEW.candidate_capture_id AND capture_kind='full' AND cleared_at IS NULL;
  END IF;
  IF original_hash IS NULL OR original_hash<>NEW.document_hash THEN
    RAISE EXCEPTION 'review document hash mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $function$;

DO $exact_base$
BEGIN
 IF pg_get_functiondef('public.rag_source_admission_guard()'::regprocedure) IS DISTINCT FROM $expected$CREATE OR REPLACE FUNCTION public.rag_source_admission_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE reviewed rag_source_reviews%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'source admission deletion denied' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.active OR
       (to_jsonb(NEW)-'active'-'revoked_at') IS DISTINCT FROM
       (to_jsonb(OLD)-'active'-'revoked_at') THEN
      RAISE EXCEPTION 'source admission immutable or revoked' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO reviewed FROM rag_source_reviews WHERE id=NEW.review_id;
  IF NOT FOUND OR reviewed.status<>'reviewed' OR
     NOT NEW.allowed_usages <@ reviewed.allowed_usages OR
     NEW.policy_generation<>reviewed.policy_generation THEN
    RAISE EXCEPTION 'source review not admitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $function$
$expected$ THEN
  RAISE EXCEPTION 'completion baseline: original deployed rag_source_admission_guard changed' USING ERRCODE='23514';
 END IF;
END $exact_base$;

CREATE OR REPLACE FUNCTION public.rag_source_admission_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE reviewed rag_source_reviews%ROWTYPE;
BEGIN
  -- Independent forward503 maintenance branch; original INSERT/UPDATE body unchanged.
  IF TG_OP='DELETE' AND rag_actual_d_private_delete_allowed((SELECT assessment_evidence_id FROM rag_source_reviews WHERE id=OLD.review_id)) THEN RETURN OLD; END IF;
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'source admission deletion denied' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.active OR
       (to_jsonb(NEW)-'active'-'revoked_at') IS DISTINCT FROM
       (to_jsonb(OLD)-'active'-'revoked_at') THEN
      RAISE EXCEPTION 'source admission immutable or revoked' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO reviewed FROM rag_source_reviews WHERE id=NEW.review_id;
  IF NOT FOUND OR reviewed.status<>'reviewed' OR
     NOT NEW.allowed_usages <@ reviewed.allowed_usages OR
     NEW.policy_generation<>reviewed.policy_generation THEN
    RAISE EXCEPTION 'source review not admitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $function$;

DO $exact_base$
BEGIN
 IF pg_get_functiondef('public.rag_source_claim_guard()'::regprocedure) IS DISTINCT FROM $expected$CREATE OR REPLACE FUNCTION public.rag_source_claim_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE primary_review rag_source_reviews%ROWTYPE;
DECLARE secondary_review rag_source_reviews%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'claim receipt immutable' USING ERRCODE='23514';
  END IF;
  -- No execution verifier adapter is installed in C's default-off runtime.
  -- A text handle alone is not proof that a process was actually isolated/run.
  IF TG_TABLE_NAME='rag_source_claim_receipts' THEN
    IF NEW.method='isolated_execution' THEN
      RAISE EXCEPTION 'isolated execution verifier unavailable' USING ERRCODE='23514';
    END IF;
    SELECT review.* INTO primary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.admission_id AND admission.active FOR SHARE OF review,admission;
    SELECT review.* INTO secondary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.independent_admission_id AND admission.active FOR SHARE OF review,admission;
    IF primary_review.id IS NULL OR secondary_review.id IS NULL OR
       primary_review.document_hash<>NEW.source_document_hash OR
       secondary_review.document_hash<>NEW.independent_document_hash OR
       primary_review.lineage_family=secondary_review.lineage_family OR
       primary_review.subject_id<>NEW.subject_id OR
       secondary_review.subject_id<>NEW.subject_id OR
       primary_review.subject_version<>NEW.subject_version OR
       secondary_review.subject_version<>NEW.subject_version THEN
      RAISE EXCEPTION 'claim lineage or scope unverified' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $function$
$expected$ THEN
  RAISE EXCEPTION 'completion baseline: original deployed rag_source_claim_guard changed' USING ERRCODE='23514';
 END IF;
END $exact_base$;

CREATE OR REPLACE FUNCTION public.rag_source_claim_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE primary_review rag_source_reviews%ROWTYPE;
DECLARE secondary_review rag_source_reviews%ROWTYPE;
BEGIN
  -- Independent forward503 maintenance branch; original INSERT/UPDATE body unchanged.
  IF TG_OP='DELETE' AND TG_TABLE_NAME='rag_source_claim_receipts' AND rag_actual_d_private_delete_allowed(OLD.assessment_evidence_id) THEN RETURN OLD; END IF;
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'claim receipt immutable' USING ERRCODE='23514';
  END IF;
  -- No execution verifier adapter is installed in C's default-off runtime.
  -- A text handle alone is not proof that a process was actually isolated/run.
  IF TG_TABLE_NAME='rag_source_claim_receipts' THEN
    IF NEW.method='isolated_execution' THEN
      RAISE EXCEPTION 'isolated execution verifier unavailable' USING ERRCODE='23514';
    END IF;
    SELECT review.* INTO primary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.admission_id AND admission.active FOR SHARE OF review,admission;
    SELECT review.* INTO secondary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.independent_admission_id AND admission.active FOR SHARE OF review,admission;
    IF primary_review.id IS NULL OR secondary_review.id IS NULL OR
       primary_review.document_hash<>NEW.source_document_hash OR
       secondary_review.document_hash<>NEW.independent_document_hash OR
       primary_review.lineage_family=secondary_review.lineage_family OR
       primary_review.subject_id<>NEW.subject_id OR
       secondary_review.subject_id<>NEW.subject_id OR
       primary_review.subject_version<>NEW.subject_version OR
       secondary_review.subject_version<>NEW.subject_version THEN
      RAISE EXCEPTION 'claim lineage or scope unverified' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $function$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.check_execution_intent(intent_id uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.check_execution_intent' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_future_item_uuid(kind text, identity text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_future_item_uuid' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_validation_current(p tutor_item_supply_shared_validation_preparations)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_validation_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_continuation_generation_inherited(operation_job uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_continuation_generation_inherited' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_stage_original_matches(
  operation_job uuid, operation_generation integer, artifact_id uuid, adoption_hash text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_stage_original_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_publication_event_allowed(ev tutor_learning_item_publication_events)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_publication_event_allowed' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_materialization_allowed(m tutor_learning_item_practice_materializations)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_materialization_allowed' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_exposure_binding_check(b jsonb, require_current boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_exposure_binding_check' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION rag_actual_d_finite_source_scope_check(e rag_assessment_source_evidence)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: rag_actual_d_finite_source_scope_check' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_public_template_matches(
  request_payload jsonb, source_public jsonb, target_id text
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_public_template_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_type_actor(identity text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_type_actor' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.type_exposure_current(sid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.type_exposure_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.type_content_clone(a jsonb,b jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.type_content_clone' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.type_relation_required(
  a jsonb,b jsonb,profile text,req_hash text,u uuid,e bigint,mapping_id uuid,ids uuid[]) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.type_relation_required' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_generation_policy_hash(g tutor_item_supply_shared_generation_artifacts)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_generation_policy_hash' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_evaluation_policy_matches(g tutor_item_supply_shared_generation_artifacts, evaluation jsonb, review jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_evaluation_policy_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.review_investigation_pointer_value(document jsonb, pointer text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.review_investigation_pointer_value' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.revision_substantive_hash(source_payload jsonb)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.revision_substantive_hash' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_revision_descendant(operation_job uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_revision_descendant' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.revision_recheck_disputes(bundle jsonb)
 RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.revision_recheck_disputes' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.controlled_counterexample_held(operation_job uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.controlled_counterexample_held' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.controlled_case_execution_history_matches(
 operation_root uuid, original_job uuid, failed_job uuid, case_context_hash text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.controlled_case_execution_history_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_consumer_source_current(proof_id uuid,origin_id uuid,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_consumer_source_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_consumer_teaching_request_current(q jsonb,revision uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_consumer_teaching_request_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_consumer_receipt_current(receipt_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_consumer_receipt_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_consumer_frozen_artifact_matches(q jsonb,a tutor_learning_artifacts) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_consumer_frozen_artifact_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_artifact_owner_matches(a tutor_learning_artifacts,prior jsonb,historical boolean) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_artifact_owner_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_normal_revision_readmission(p jsonb)
 RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_normal_revision_readmission' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.normal_revision_readmission_matches(artifact uuid,facts uuid,exact_hash text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.normal_revision_readmission_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_persistent_pack_phase(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_persistent_pack_phase' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.persistent_relation_anchor_matches(p jsonb, anchor uuid, exact_root uuid, exact_job uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.persistent_relation_anchor_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_source_current(q jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_source_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_epoch(u uuid,e bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_epoch' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_pack_slot_current(
 task uuid,slot uuid,item uuid,root uuid,u uuid,e bigint,scope uuid,job uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_pack_slot_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_mapping_current(mid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_mapping_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_publication_current(v uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_publication_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_pack_bind_phase(r jsonb,l jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_pack_bind_phase' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_pack_prepare_auxiliary(task uuid, preparation uuid, job uuid, reservation uuid, payload jsonb, deadline timestamp with time zone)
 RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_pack_prepare_auxiliary' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_pack_auxiliary_committed(task uuid,preparation uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_pack_auxiliary_committed' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_generation_goal_current(g jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_generation_goal_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_exposure_hooks_current() RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_exposure_hooks_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_exposure_current(sid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_exposure_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_phase(
 p jsonb,u uuid,e bigint,scope uuid,task uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_phase' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_normal(n tutor_item_supply_private_native_quality_evidence)
 RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_normal' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_investigation(
 n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_investigation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_clone(a jsonb,b jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_clone' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_relation_current(ids jsonb,m jsonb,a jsonb,b jsonb,u uuid,e bigint,task uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_relation_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_eligibility_current(eid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_eligibility_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_consumer_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_consumer_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_artifact_owner_matches(a tutor_learning_artifacts,prior jsonb,historical boolean) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_artifact_owner_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_request_matches(q jsonb,pub uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_request_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_relation(n tutor_item_supply_private_native_quality_evidence) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_relation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_review_stage(n tutor_item_supply_private_native_quality_evidence)
 RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_review_stage' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_task_enhancement(task uuid,u uuid,e bigint,scope uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_task_enhancement' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_base_union_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_base_union_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_public_artifact_union(a tutor_learning_artifacts,prior jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_public_artifact_union' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_persistent_normal_repair(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_persistent_normal_repair' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.persistent_registered_family_revision_matches(p jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.persistent_registered_family_revision_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_resume_review(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_resume_review' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_resume_review(rid uuid,p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_resume_review' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_resume_current(rid uuid,job uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_resume_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_review_evidence_job(current_job uuid,review_id uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_review_evidence_job' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_historical_investigation(n tutor_item_supply_private_native_quality_evidence,resume uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_historical_investigation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_resume_investigation(iid uuid,resume uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_resume_investigation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_inherit_generation(p jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_inherit_generation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_successor_candidate(parent uuid,eligibility uuid,target uuid,purpose text,allow_run uuid DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_successor_candidate' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_successor_selected(action_receipt uuid,eligibility uuid,target uuid,purpose text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_successor_selected' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_successor_delivery_current(parent uuid,eligibility uuid,target uuid,purpose text,allow_run uuid DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_successor_delivery_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_successor_creation_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_successor_creation_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_relation_actual_content(v uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_relation_actual_content' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_relation_repair(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_relation_repair' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_request_relation_repair(rid uuid,p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_request_relation_repair' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_relation_repair_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_relation_repair_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_native_public_fallback_frame(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_native_public_fallback_frame' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_public_fallback_record(p jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_public_fallback_record' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_public_fallback_for_creation(
 creator tutor_item_supply_native_consumer_receipts,required_stage text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_public_fallback_for_creation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.public_normal_mapping_current(mid uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.public_normal_mapping_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.public_native_source_current(q jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.public_native_source_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_persistent_prestart_recovery(p jsonb,successor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_persistent_prestart_recovery' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_persistent_explicit_recovery(p jsonb,successor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_persistent_explicit_recovery' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_committed_revision_execution(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_committed_revision_execution' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.fresh_committed_revision_matches(p jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.fresh_committed_revision_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_revision_generation_output_current(output_preparation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_revision_generation_output_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.confirmed_source_successor_allowed(q jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.confirmed_source_successor_allowed' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_source_mapping_successor(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_source_mapping_successor' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.revision_source_successor_matches(p jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.revision_source_successor_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_committed_child_history(preparation uuid,artifact uuid,lineage_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_committed_child_history' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.committed_child_version_data_matches(version_data jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.committed_child_version_data_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_committed_child_recheck(binding jsonb,operation_lease jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_committed_child_recheck' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_normal_revision_readmission_v2(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_normal_revision_readmission_v2' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_committed_child_quality(q jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_committed_child_quality' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_committed_child_admission(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_committed_child_admission' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.committed_child_admission_for_job(operation_job uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.committed_child_admission_for_job' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_normal_revision_readmission_v3(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_normal_revision_readmission_v3' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.committed_child_evaluation_matches(r jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.committed_child_evaluation_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.current_pack_public_materials_current(materials jsonb,upper_bound timestamptz) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.current_pack_public_materials_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.current_pack_source_receipts_match(materials jsonb,receipts jsonb,issued timestamptz) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.current_pack_source_receipts_match' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.current_pack_source_origin_payload_current(p jsonb,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.current_pack_source_origin_payload_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.current_pack_source_origin_current(rid uuid,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.current_pack_source_origin_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.native_consumer_source_context_current(proof_id uuid,p jsonb,u uuid,e bigint,mid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.native_consumer_source_context_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_development_accounting_batch_current(
 b tutor_item_supply_private_development_model_accounting_batches) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_development_accounting_batch_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.m03_p2_normal_loop_for_job(job uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.m03_p2_normal_loop_for_job' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_m03_p2_investigation(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_m03_p2_investigation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_reports(b jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_reports' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_blind_original(b jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_blind_original' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_binding(b jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_binding' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_blind_score(b jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_blind_score' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_changed_paths(a jsonb,b jsonb,p text DEFAULT '')
RETURNS text[]
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_changed_paths' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_primary_dependency(s jsonb,role text)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_primary_dependency' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_shared_source_deadline(request jsonb) RETURNS timestamptz
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_shared_source_deadline' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_shared_source_current(request jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_shared_source_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_incremental_shared_current(lease jsonb,artifact uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_incremental_shared_current' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.incremental_material_failure(r jsonb)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.incremental_material_failure' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_incremental_direct_revision(p jsonb)
 RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_incremental_direct_revision' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_incremental_local_diff(parent jsonb,child jsonb,allowed jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_incremental_local_diff' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_shared_incremental_coverage(p jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_shared_incremental_coverage' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.persist_shared_incremental_coverage(p jsonb)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.persist_shared_incremental_coverage' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.require_shared_incremental_coverage(b jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.require_shared_incremental_coverage' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_normal_committed_review_frame(p jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_normal_committed_review_frame' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_incremental_frame(frame jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_incremental_frame' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_incremental_committed_action(frame jsonb,stage text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_incremental_committed_action' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.private_native_incremental_evidence_v1(operation text,frame jsonb,data jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.private_native_incremental_evidence_v1' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_incremental_blind_rescore(frame jsonb,b jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_incremental_blind_rescore' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_incremental_coverage(frame jsonb,b jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_incremental_coverage' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_shared_review_probe_frame(frame jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_shared_review_probe_frame' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_review_probe_event_v1(operation text,frame jsonb,data jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_review_probe_event_v1' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.require_private_incremental_coverage(b jsonb,u uuid,e bigint,scope uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.require_private_incremental_coverage' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_shared_blind_applicability(b jsonb,artifact uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_shared_blind_applicability' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_shared_review_adjudication(p jsonb)
 RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_shared_review_adjudication' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.original_review_counterexample_statement(counterexample text)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.original_review_counterexample_statement' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_shared_adjudicated_facts(n tutor_item_supply_shared_admission_facts)
 RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_shared_adjudicated_facts' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_adjudicated_evaluation_matches(n jsonb)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_adjudicated_evaluation_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_direct_preparation(task uuid,job uuid,reservation uuid,p jsonb,deadline timestamptz)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_direct_preparation' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_private_incremental_normal(n tutor_item_supply_private_native_quality_evidence)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_private_incremental_normal' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_adjudicated_import_action(lease jsonb,artifact uuid,validation uuid,evidence uuid,specification text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_adjudicated_import_action' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_shared_validation_applicability(p jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_shared_validation_applicability' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.persist_shared_validation_applicability(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.persist_shared_validation_applicability' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_continuation_validation_inherited(operation_job uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_continuation_validation_inherited' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_validation_inherited_receipt_matches(operation_job uuid,artifact uuid,receipt uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_validation_inherited_receipt_matches' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.assert_shared_committed_same_child_coverage(p jsonb)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.assert_shared_committed_same_child_coverage' USING ERRCODE='42501';
END $$;

-- Deliberate policy endpoint, NOT an unimplemented business receiver.
CREATE FUNCTION item_supply_internal.shared_review_probe_intent_for_reservation(job uuid,root uuid,generation integer,reservation_key text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'completion baseline: B1d/P2/P7 business receiver denied: item_supply_internal.shared_review_probe_intent_for_reservation' USING ERRCODE='42501';
END $$;

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_subscriptions
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_subscriptions
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_result_items
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_result_items
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_result_items
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_bindings
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_bindings
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_cache
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_cache
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_cache
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_results
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_results
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_results
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_demands
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_demands
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_demands
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_publication_refs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_publication_refs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_publication_refs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_admissions
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_admissions
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_admissions
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_proofs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_proofs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_proofs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_observations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_observations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_observations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_evidence
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_evidence
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_evidence
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_usage_events
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_usage_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_usage_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_reservations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_job_events
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_job_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_job_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_jobs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_jobs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_budget_windows
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_budget_windows
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_budget_windows
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_budget_roots
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_budget_roots
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_budget_roots
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_staging
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_staging
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_staging
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_versions
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_versions
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_versions
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_candidates
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_candidates
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_candidates
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_materials
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_materials
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_materials
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_scopes
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_scopes
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_scopes
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_settlement_amounts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_settlement_amounts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_settlement_amounts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_settlements
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_settlements
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_settlements
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_reservation_amounts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_reservation_amounts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_reservation_amounts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_checkpoints
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_checkpoints
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_checkpoints
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_job_controls
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_job_controls
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_obligations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_obligations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_obligations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_user_limits
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_runtime_user_limits
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_pipeline_receipts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_pipeline_receipts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_pipeline_receipts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_execution_intents
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_execution_intents
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_execution_intents
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_sandbox_runs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_sandbox_runs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_sandbox_runs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_sandbox_observations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_sandbox_observations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_sandbox_observations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_admission_facts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_admission_facts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_admission_facts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_materializations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_materializations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_materializations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_publication_events
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_publication_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_publication_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_publication_proofs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_publication_proofs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_publication_proofs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_deliveries
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_deliveries
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_deliveries
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_reservations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_snapshots
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_type_exposure_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_eligibility
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_eligibility
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_relation_batches
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_relation_batches
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_relation_preparations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_relation_preparations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_content_facts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_content_facts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_deliveries
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_deliveries
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_deliveries
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_reservations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_watermarks
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_watermarks
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_events
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_events
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_technical_origin BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_inbox
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_technical_origin();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_inbox
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_technical_origin BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_births
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_technical_origin();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_exposure_births
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_finite_course_mappings
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_finite_course_mappings
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_artifact_bindings
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_artifact_bindings
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_native_consumer_receipts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_native_consumer_receipts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_artifact_bindings
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_artifact_bindings
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_artifact_bindings
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_consumer_receipts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_consumer_receipts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_consumer_receipts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_assessment_reservations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_assessment_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_assessment_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_eligibility
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_eligibility
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_eligibility
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_exposure_snapshots
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_exposure_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_exposure_origins
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_exposure_origins
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_publications
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_publications
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_publications
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_quality_evidence
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_native_quality_evidence
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_native_quality_evidence
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_development_model_accounting_jobs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_development_model_accounting_jobs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_development_model_accounting_jobs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_development_model_accounting_batches
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_private_epoch BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_private_development_model_accounting_batches
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_private_epoch();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_private_development_model_accounting_batches
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('private');

CREATE TRIGGER completion_source_closed BEFORE INSERT OR UPDATE OR DELETE ON public.rag_assessment_source_evidence
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_source_evidence_closed();

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_jobs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_jobs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_policies
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_policies
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_parameter_profiles
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_parameter_profiles
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_reservations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_reservations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_learning_item_native_publication_proofs
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_learning_item_native_publication_proofs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_budget_roots
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_budget_roots
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_budget_windows
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_budget_windows
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_admission_facts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_admission_facts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_pipeline_receipts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_pipeline_receipts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_blueprints
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_blueprints
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_validation_preparations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_validation_preparations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_matrices
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_matrices
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER completion_source_closed BEFORE INSERT OR UPDATE OR DELETE ON public.rag_actual_d_private_provenance
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_source_evidence_closed();

CREATE TRIGGER a00_completion_business_closed BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_shared_validation_evidence
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER supply_immutable BEFORE UPDATE OR DELETE ON public.tutor_item_supply_shared_validation_evidence
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_immutable('shared');

CREATE TRIGGER supply_snapshot BEFORE INSERT ON public.tutor_item_supply_shared_matrices
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_shared_snapshot();

CREATE TRIGGER supply_snapshot BEFORE INSERT ON public.tutor_item_supply_shared_policies
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_shared_snapshot();

CREATE TRIGGER supply_snapshot BEFORE INSERT ON public.tutor_item_supply_shared_blueprints
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_shared_snapshot();

CREATE TRIGGER completion_identity_immutable BEFORE INSERT OR UPDATE OR DELETE ON completion_baseline_internal.installation_identity
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_storage();

CREATE TRIGGER item_supply_epoch_guard BEFORE INSERT OR UPDATE OR DELETE ON public.tutor_item_supply_user_epochs
 FOR EACH ROW EXECUTE FUNCTION public.enforce_item_supply_epoch();

CREATE TRIGGER native_exposure_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
  FOR EACH ROW WHEN (OLD.epoch < NEW.epoch) EXECUTE FUNCTION purge_native_exposure_on_epoch_advance();

CREATE TRIGGER finite_course_mapping_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
  FOR EACH ROW WHEN (OLD.epoch < NEW.epoch)
  EXECUTE FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance();

CREATE TRIGGER a02_native_type_evidence_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN (OLD.epoch<NEW.epoch) EXECUTE FUNCTION item_supply_internal.purge_native_type_evidence_on_epoch_advance();

CREATE TRIGGER a01_native_type_exposure_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
  FOR EACH ROW WHEN (OLD.epoch<NEW.epoch) EXECUTE FUNCTION purge_type_exposure_on_epoch_advance();

CREATE CONSTRAINT TRIGGER rag_actual_d_private_reset_complete AFTER UPDATE ON tutor_item_supply_user_epochs
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.epoch < NEW.epoch)
  EXECUTE FUNCTION item_supply_internal.assert_actual_d_private_reset_complete();

CREATE TRIGGER a00_native_consumer_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN (NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION purge_native_consumer_on_epoch_advance();

CREATE TRIGGER a00z_persistent_pack_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN(NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION item_supply_internal.purge_persistent_pack_on_epoch_advance();

CREATE TRIGGER a000_private_native_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN(NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION item_supply_internal.purge_private_native_on_epoch_advance();

CREATE TRIGGER a0000_private_native_kc_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.purge_private_native_kc_on_epoch();

CREATE TRIGGER a000_private_development_accounting_epoch_purge BEFORE UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN(NEW.epoch IS DISTINCT FROM OLD.epoch) EXECUTE FUNCTION item_supply_internal.purge_private_development_accounting_on_epoch_advance();

CREATE TRIGGER native_exposure_birth_capture AFTER INSERT ON public.users
 FOR EACH ROW EXECUTE FUNCTION public.capture_native_exposure_birth();

CREATE TRIGGER native_exposure_origin_capture AFTER INSERT ON public.tutor_learning_artifact_events
 FOR EACH ROW EXECUTE FUNCTION public.capture_native_exposure_origin();

CREATE TRIGGER native_exposure_origin_capture AFTER INSERT ON public.tutor_knowledge_check_assistance_receipts
 FOR EACH ROW EXECUTE FUNCTION public.capture_native_exposure_origin();

CREATE TRIGGER native_exposure_origin_capture AFTER INSERT ON public.tutor_exercise_attempts
 FOR EACH ROW EXECUTE FUNCTION public.capture_native_exposure_origin();

CREATE TRIGGER native_exposure_origin_capture AFTER INSERT ON public.tutor_exercise_hint_receipts
 FOR EACH ROW EXECUTE FUNCTION public.capture_native_exposure_origin();

CREATE TRIGGER native_exposure_origin_capture AFTER INSERT ON public.tutor_lesson_gate_bindings
 FOR EACH ROW EXECUTE FUNCTION public.capture_native_exposure_origin();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.rag_source_reviews
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.rag_source_claim_receipts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.rag_source_admissions
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.tutor_learning_artifacts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.tutor_knowledge_check_response_receipts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.tutor_learning_item_validation_receipts
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.tutor_learning_item_publication_events
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_completion_native_closed BEFORE INSERT OR UPDATE ON public.tutor_learning_item_practice_materializations
 FOR EACH ROW EXECUTE FUNCTION completion_baseline_internal.enforce_closed_native_consumer();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.rag_corpus_admission_links
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.grounding_corpus_versions
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.grounding_corpus_source_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.grounding_corpus_documents
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.grounding_corpus_chunks
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.grounding_corpus_events
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.grounding_active_corpora
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.rag_corpus_validation_receipts
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.rag_material_selections
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.rag_plan_material_bindings
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON public.tutor_item_supply_finite_course_mappings
 FOR EACH ROW EXECUTE FUNCTION public.rag_actual_d_private_reference_guard();

CREATE INDEX idx_supply_private_runtime_claim ON tutor_item_supply_private_job_controls(user_id,epoch,state,available_at,priority,created_at);

CREATE INDEX idx_item_supply_admission_facts_owner
  ON tutor_item_supply_private_admission_facts(user_id,epoch,scope_id,generation_artifact_id);

CREATE INDEX idx_p7_proof_demand
  ON tutor_item_supply_private_publication_proofs(user_id,epoch,scope_id,demand_id,version_id);

CREATE INDEX native_exposure_inbox_owner ON tutor_item_supply_native_exposure_inbox(user_id,epoch,sequence);

CREATE INDEX finite_course_mapping_owner
  ON tutor_item_supply_finite_course_mappings(user_id,epoch,track_id,revision_id,node_id);

CREATE INDEX rag_actual_d_private_owner ON rag_assessment_source_evidence(private_user_id,private_epoch)
  WHERE private_user_id IS NOT NULL;

CREATE INDEX rag_actual_d_provenance_owner ON rag_actual_d_private_provenance(user_id,epoch);

CREATE UNIQUE INDEX native_consumer_create_run ON tutor_item_supply_native_consumer_receipts(user_id,epoch,run_id) WHERE mode='create';

CREATE UNIQUE INDEX persistent_private_intent_once ON tutor_item_supply_private_persistent_pack_journal
 (user_id,epoch,scope_id,intent_hash) WHERE record_kind='task';

CREATE UNIQUE INDEX private_native_create_run ON tutor_item_supply_private_native_consumer_receipts(user_id,epoch,run_id) WHERE mode='create';

CREATE INDEX private_native_public_fallback_run ON tutor_item_supply_private_persistent_pack_journal
 (user_id,epoch,(payload_json->>'run_id')) WHERE record_kind='private_attachment' AND payload_json->>'schema_version'='private_native_public_fallback_clearance_v1';

CREATE UNIQUE INDEX private_confidential_blind_original_capture
 ON tutor_item_supply_private_native_quality_evidence(user_id,epoch,scope_id,pack_task_id,slot_id,root_id,(payload_json->>'review_id'))
 WHERE kind='blind_data';

CREATE UNIQUE INDEX shared_legacy_facts_review_once ON tutor_item_supply_shared_admission_facts(review_receipt_id)
 WHERE payload_json->>'schema_version'<>'issued_shared_admission_facts_v2';

CREATE UNIQUE INDEX shared_adjudicated_facts_once ON public.tutor_item_supply_shared_admission_facts USING btree (((payload_json ->> 'adjudication_receipt_id'::text))) WHERE (((payload_json ->> 'schema_version'::text) = 'issued_shared_admission_facts_v2'::text) AND (NOT (payload_json ? 'current_predecessor_facts_id'::text)));

CREATE UNIQUE INDEX shared_adjudicated_facts_current_successor_once ON public.tutor_item_supply_shared_admission_facts USING btree ((((payload_json ->> 'current_predecessor_facts_id'::text))::uuid)) WHERE (((payload_json ->> 'schema_version'::text) = 'issued_shared_admission_facts_v2'::text) AND (payload_json ? 'current_predecessor_facts_id'::text));

ALTER TABLE public.tutor_item_supply_private_subscriptions OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_subscriptions FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_subscriptions TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_result_items OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_result_items FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_result_items TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_bindings OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_bindings FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_bindings TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_cache OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_cache FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_cache TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_results OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_results FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_results TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_demands OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_demands FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_demands TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_publication_refs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_publication_refs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_publication_refs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_admissions OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_admissions FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_admissions TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_proofs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_proofs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_proofs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_observations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_observations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_observations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_evidence OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_evidence FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_evidence TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_usage_events OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_usage_events FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_usage_events TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_reservations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_reservations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_reservations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_job_events OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_job_events FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_job_events TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_jobs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_jobs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_jobs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_budget_windows OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_budget_windows FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_budget_windows TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_budget_roots OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_budget_roots FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_budget_roots TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_staging OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_staging FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_staging TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_versions OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_versions FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_versions TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_candidates OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_candidates FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_candidates TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_materials OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_materials FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_materials TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_scopes OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_scopes FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_scopes TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_runtime_settlement_amounts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_runtime_settlement_amounts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_runtime_settlement_amounts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_runtime_settlements OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_runtime_settlements FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_runtime_settlements TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_runtime_reservation_amounts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_runtime_reservation_amounts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_runtime_reservation_amounts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_checkpoints OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_checkpoints FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_checkpoints TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_job_controls OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_job_controls FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_job_controls TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_obligations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_obligations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_obligations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_runtime_user_limits OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_runtime_user_limits FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_runtime_user_limits TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_generation_artifacts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_generation_artifacts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_generation_artifacts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_pipeline_receipts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_pipeline_receipts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_pipeline_receipts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_execution_intents OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_execution_intents FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_execution_intents TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_sandbox_runs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_sandbox_runs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_sandbox_runs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_sandbox_observations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_sandbox_observations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_sandbox_observations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_admission_facts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_admission_facts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_admission_facts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_materializations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_materializations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_materializations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_publication_events OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_publication_events FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_publication_events TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_publication_proofs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_publication_proofs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_publication_proofs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_type_exposure_deliveries OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_type_exposure_deliveries FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_type_exposure_deliveries TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_type_exposure_reservations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_type_exposure_reservations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_type_exposure_reservations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_type_exposure_snapshots OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_type_exposure_snapshots FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_type_exposure_snapshots TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_eligibility OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_eligibility FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_eligibility TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_relation_batches OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_relation_batches FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_relation_batches TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_relation_preparations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_relation_preparations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_relation_preparations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_content_facts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_content_facts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_content_facts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_exposure_deliveries OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_exposure_deliveries FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_exposure_deliveries TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_exposure_reservations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_exposure_reservations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_exposure_reservations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_exposure_watermarks OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_exposure_watermarks FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_exposure_watermarks TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_exposure_events OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_exposure_events FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_exposure_events TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_exposure_inbox OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_exposure_inbox FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_exposure_inbox TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_exposure_births OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_exposure_births FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_exposure_births TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_finite_course_mappings OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_finite_course_mappings FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_finite_course_mappings TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_artifact_bindings OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_artifact_bindings FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_artifact_bindings TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_native_consumer_receipts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_native_consumer_receipts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_native_consumer_receipts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_artifact_bindings OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_artifact_bindings FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_artifact_bindings TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_consumer_receipts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_consumer_receipts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_consumer_receipts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_assessment_reservations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_assessment_reservations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_assessment_reservations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_eligibility OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_eligibility FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_eligibility TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_exposure_snapshots OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_exposure_snapshots FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_exposure_snapshots TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_exposure_origins OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_exposure_origins FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_exposure_origins TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_publications OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_publications FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_publications TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_native_quality_evidence OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_native_quality_evidence FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_native_quality_evidence TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_persistent_pack_journal OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_persistent_pack_journal FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_persistent_pack_journal TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_development_model_accounting_jobs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_development_model_accounting_jobs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_development_model_accounting_jobs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_private_development_model_accounting_batches OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_private_development_model_accounting_batches FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_private_development_model_accounting_batches TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_user_epochs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_user_epochs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_user_epochs TO aearn_cb_runtime_20261027;

ALTER TABLE public.rag_assessment_source_evidence OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.rag_assessment_source_evidence FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.rag_assessment_source_evidence TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_jobs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_jobs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_jobs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_policies OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_policies FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_policies TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_parameter_profiles OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_parameter_profiles FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_parameter_profiles TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_reservations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_reservations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_reservations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_learning_item_native_publication_proofs OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_learning_item_native_publication_proofs FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_learning_item_native_publication_proofs TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_budget_roots OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_budget_roots FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_budget_roots TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_budget_windows OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_budget_windows FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_budget_windows TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_generation_artifacts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_generation_artifacts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_generation_artifacts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_admission_facts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_admission_facts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_admission_facts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_pipeline_receipts OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_pipeline_receipts FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_pipeline_receipts TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_blueprints OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_blueprints FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_blueprints TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_validation_preparations OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_validation_preparations FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_validation_preparations TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_matrices OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_matrices FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_matrices TO aearn_cb_runtime_20261027;

ALTER TABLE public.rag_actual_d_private_provenance OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.rag_actual_d_private_provenance FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.rag_actual_d_private_provenance TO aearn_cb_runtime_20261027;

ALTER TABLE public.tutor_item_supply_shared_validation_evidence OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE public.tutor_item_supply_shared_validation_evidence FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT SELECT ON TABLE public.tutor_item_supply_shared_validation_evidence TO aearn_cb_runtime_20261027;

ALTER TABLE item_supply_internal.reset_permits OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE item_supply_internal.reset_permits FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER TABLE completion_baseline_internal.installation_identity OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE completion_baseline_internal.installation_identity FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER TABLE completion_baseline_internal.validation_permits OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON TABLE completion_baseline_internal.validation_permits FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.check_execution_intent(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.check_execution_intent(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
GRANT EXECUTE ON FUNCTION item_supply_internal.check_execution_intent(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.canonical_snapshot(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.canonical_snapshot(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.canonical_snapshot(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.snapshot_hash(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.snapshot_hash(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.snapshot_hash(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.snapshot_keys(jsonb,text[]) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.snapshot_keys(jsonb,text[]) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.snapshot_keys(jsonb,text[]) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.snapshot_scalars(jsonb,text[]) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.snapshot_scalars(jsonb,text[]) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.snapshot_scalars(jsonb,text[]) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.snapshot_strings(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.snapshot_strings(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.snapshot_strings(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.pipeline_generation_hash(jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.pipeline_generation_hash(jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.pipeline_generation_hash(jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_generation_hash(jsonb,jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_generation_hash(jsonb,jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_generation_hash(jsonb,jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION completion_baseline_internal.contract_identity() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.contract_identity() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION completion_baseline_internal.contract_identity() TO aearn_cb_runtime_20261027;

ALTER FUNCTION public.rag_actual_d_finite_storage_profile(text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_actual_d_finite_storage_profile(text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_course_material_proof_lifetime_allowed(jsonb,text,timestamptz,timestamptz) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_course_material_proof_lifetime_allowed(jsonb,text,timestamptz,timestamptz) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.permitted(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.permitted(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.enforce_item_supply_epoch() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.enforce_item_supply_epoch() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.enforce_item_supply_private_epoch() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.enforce_item_supply_private_epoch() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.enforce_item_supply_immutable() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.enforce_item_supply_immutable() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.enforce_item_supply_shared_snapshot() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.enforce_item_supply_shared_snapshot() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.capture_native_exposure_birth() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.capture_native_exposure_birth() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.native_exposure_lock(uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_exposure_lock(uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.native_exposure_hooks_current() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_exposure_hooks_current() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_exposure_hooks_current() TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.purge_native_exposure_private(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_native_exposure_private(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.purge_native_exposure_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.purge_native_exposure_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.purge_native_type_evidence_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_native_type_evidence_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.purge_type_exposure_private(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_type_exposure_private(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.purge_type_exposure_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.purge_type_exposure_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.purge_native_consumer_private(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_native_consumer_private(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.purge_native_consumer_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.purge_native_consumer_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.purge_persistent_pack_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_persistent_pack_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.purge_private_native_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_private_native_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_actual_d_private_epoch(uuid,bigint,boolean) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_actual_d_private_epoch(uuid,bigint,boolean) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION public.rag_actual_d_private_epoch(uuid,bigint,boolean) TO aearn_cb_runtime_20261027;

ALTER FUNCTION public.rag_actual_d_private_delete_allowed(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_actual_d_private_delete_allowed(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_actual_d_private_purge(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_actual_d_private_purge(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION public.rag_actual_d_private_purge(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.purge_private_native_kc_on_epoch() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_private_native_kc_on_epoch() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.purge_private_development_accounting_on_epoch_advance() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.purge_private_development_accounting_on_epoch_advance() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.assert_actual_d_private_reset_complete() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_actual_d_private_reset_complete() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_actual_d_private_reference_guard() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_actual_d_private_reference_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.capture_native_exposure_origin() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.capture_native_exposure_origin() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.purge_item_supply_private(uuid,boolean) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.purge_item_supply_private(uuid,boolean) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION public.purge_item_supply_private(uuid,boolean) TO aearn_cb_runtime_20261027;

ALTER FUNCTION completion_baseline_internal.validation_allowed(uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.validation_allowed(uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION completion_baseline_internal.enforce_closed_storage() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.enforce_closed_storage() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION completion_baseline_internal.enforce_technical_origin() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.enforce_technical_origin() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION completion_baseline_internal.enforce_closed_native_consumer() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.enforce_closed_native_consumer() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION completion_baseline_internal.enforce_source_evidence_closed() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION completion_baseline_internal.enforce_source_evidence_closed() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_source_review_guard() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_source_review_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_source_admission_guard() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_source_admission_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION public.rag_source_claim_guard() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_source_claim_guard() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.shared_future_item_uuid(text,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_future_item_uuid(text,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_future_item_uuid(text,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_validation_current(tutor_item_supply_shared_validation_preparations) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_validation_current(tutor_item_supply_shared_validation_preparations) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_validation_current(tutor_item_supply_shared_validation_preparations) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_continuation_generation_inherited(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_continuation_generation_inherited(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_continuation_generation_inherited(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_stage_original_matches(uuid,integer,uuid,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_stage_original_matches(uuid,integer,uuid,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_stage_original_matches(uuid,integer,uuid,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_publication_event_allowed(tutor_learning_item_publication_events) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_publication_event_allowed(tutor_learning_item_publication_events) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_publication_event_allowed(tutor_learning_item_publication_events) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_materialization_allowed(tutor_learning_item_practice_materializations) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_materialization_allowed(tutor_learning_item_practice_materializations) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_materialization_allowed(tutor_learning_item_practice_materializations) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_exposure_binding_check(jsonb,boolean) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_exposure_binding_check(jsonb,boolean) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_exposure_binding_check(jsonb,boolean) TO aearn_cb_runtime_20261027;

ALTER FUNCTION public.rag_actual_d_finite_source_scope_check(rag_assessment_source_evidence) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION public.rag_actual_d_finite_source_scope_check(rag_assessment_source_evidence) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

ALTER FUNCTION item_supply_internal.shared_public_template_matches(jsonb,jsonb,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_public_template_matches(jsonb,jsonb,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_public_template_matches(jsonb,jsonb,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_type_actor(text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_type_actor(text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_type_actor(text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.type_exposure_current(uuid,uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.type_exposure_current(uuid,uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.type_exposure_current(uuid,uuid,bigint) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.type_content_clone(jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.type_content_clone(jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.type_content_clone(jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.type_relation_required(jsonb,jsonb,text,text,uuid,bigint,uuid,uuid[]) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.type_relation_required(jsonb,jsonb,text,text,uuid,bigint,uuid,uuid[]) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.type_relation_required(jsonb,jsonb,text,text,uuid,bigint,uuid,uuid[]) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_generation_policy_hash(tutor_item_supply_shared_generation_artifacts) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_generation_policy_hash(tutor_item_supply_shared_generation_artifacts) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_generation_policy_hash(tutor_item_supply_shared_generation_artifacts) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_evaluation_policy_matches(tutor_item_supply_shared_generation_artifacts,jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_evaluation_policy_matches(tutor_item_supply_shared_generation_artifacts,jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_evaluation_policy_matches(tutor_item_supply_shared_generation_artifacts,jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.review_investigation_pointer_value(jsonb,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.review_investigation_pointer_value(jsonb,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.review_investigation_pointer_value(jsonb,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.revision_substantive_hash(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.revision_substantive_hash(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.revision_substantive_hash(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_revision_descendant(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_revision_descendant(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_revision_descendant(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.revision_recheck_disputes(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.revision_recheck_disputes(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.revision_recheck_disputes(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.controlled_counterexample_held(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.controlled_counterexample_held(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.controlled_counterexample_held(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.controlled_case_execution_history_matches(uuid,uuid,uuid,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.controlled_case_execution_history_matches(uuid,uuid,uuid,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.controlled_case_execution_history_matches(uuid,uuid,uuid,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_consumer_source_current(uuid,uuid,uuid,bigint,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_source_current(uuid,uuid,uuid,bigint,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_consumer_source_current(uuid,uuid,uuid,bigint,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_consumer_teaching_request_current(jsonb,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_teaching_request_current(jsonb,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_consumer_teaching_request_current(jsonb,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_consumer_receipt_current(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_receipt_current(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_consumer_receipt_current(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_consumer_frozen_artifact_matches(jsonb,tutor_learning_artifacts) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_frozen_artifact_matches(jsonb,tutor_learning_artifacts) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_consumer_frozen_artifact_matches(jsonb,tutor_learning_artifacts) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_normal_revision_readmission(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_normal_revision_readmission(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.normal_revision_readmission_matches(uuid,uuid,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.normal_revision_readmission_matches(uuid,uuid,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.normal_revision_readmission_matches(uuid,uuid,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_persistent_pack_phase(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_pack_phase(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_persistent_pack_phase(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.persistent_relation_anchor_matches(jsonb,uuid,uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.persistent_relation_anchor_matches(jsonb,uuid,uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.persistent_relation_anchor_matches(jsonb,uuid,uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_source_current(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_source_current(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_source_current(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_epoch(uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_epoch(uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_epoch(uuid,bigint) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_pack_slot_current(uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_slot_current(uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_pack_slot_current(uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_mapping_current(uuid,uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_mapping_current(uuid,uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_mapping_current(uuid,uuid,bigint) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_publication_current(uuid,uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_publication_current(uuid,uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_publication_current(uuid,uuid,bigint) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_pack_bind_phase(jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_bind_phase(jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_pack_bind_phase(jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_pack_prepare_auxiliary(uuid,uuid,uuid,uuid,jsonb,timestamp with time zone) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_prepare_auxiliary(uuid,uuid,uuid,uuid,jsonb,timestamp with time zone) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_pack_prepare_auxiliary(uuid,uuid,uuid,uuid,jsonb,timestamp with time zone) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_pack_auxiliary_committed(uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_pack_auxiliary_committed(uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_pack_auxiliary_committed(uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_generation_goal_current(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_generation_goal_current(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_generation_goal_current(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_exposure_hooks_current() OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_exposure_hooks_current() FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_exposure_hooks_current() TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_exposure_current(uuid,uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_exposure_current(uuid,uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_exposure_current(uuid,uuid,bigint) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_phase(jsonb,uuid,bigint,uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_phase(jsonb,uuid,bigint,uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_phase(jsonb,uuid,bigint,uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_normal(tutor_item_supply_private_native_quality_evidence) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_normal(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_normal(tutor_item_supply_private_native_quality_evidence) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_investigation(tutor_item_supply_private_native_quality_evidence) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_investigation(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_investigation(tutor_item_supply_private_native_quality_evidence) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_clone(jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_clone(jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_clone(jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_relation_current(jsonb,jsonb,jsonb,jsonb,uuid,bigint,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_relation_current(jsonb,jsonb,jsonb,jsonb,uuid,bigint,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_relation_current(jsonb,jsonb,jsonb,jsonb,uuid,bigint,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_eligibility_current(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_eligibility_current(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_eligibility_current(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_consumer_current(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_consumer_current(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_consumer_current(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_request_matches(jsonb,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_request_matches(jsonb,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_request_matches(jsonb,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_relation(tutor_item_supply_private_native_quality_evidence) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_relation(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_relation(tutor_item_supply_private_native_quality_evidence) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_review_stage(tutor_item_supply_private_native_quality_evidence) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_review_stage(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_review_stage(tutor_item_supply_private_native_quality_evidence) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_task_enhancement(uuid,uuid,bigint,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_task_enhancement(uuid,uuid,bigint,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_task_enhancement(uuid,uuid,bigint,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_base_union_current(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_base_union_current(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_base_union_current(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_public_artifact_union(tutor_learning_artifacts,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_public_artifact_union(tutor_learning_artifacts,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_public_artifact_union(tutor_learning_artifacts,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_persistent_normal_repair(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_normal_repair(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_persistent_normal_repair(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.persistent_registered_family_revision_matches(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.persistent_registered_family_revision_matches(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.persistent_registered_family_revision_matches(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_resume_review(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_resume_review(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_resume_review(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_resume_review(uuid,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_resume_review(uuid,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_resume_review(uuid,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_resume_current(uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_resume_current(uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_resume_current(uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_review_evidence_job(uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_review_evidence_job(uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_review_evidence_job(uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_historical_investigation(tutor_item_supply_private_native_quality_evidence,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_historical_investigation(tutor_item_supply_private_native_quality_evidence,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_historical_investigation(tutor_item_supply_private_native_quality_evidence,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_resume_investigation(uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_resume_investigation(uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_resume_investigation(uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_inherit_generation(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_inherit_generation(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_inherit_generation(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_successor_candidate(uuid,uuid,uuid,text,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_candidate(uuid,uuid,uuid,text,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_successor_candidate(uuid,uuid,uuid,text,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_successor_selected(uuid,uuid,uuid,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_selected(uuid,uuid,uuid,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_successor_selected(uuid,uuid,uuid,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_successor_delivery_current(uuid,uuid,uuid,text,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_delivery_current(uuid,uuid,uuid,text,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_successor_delivery_current(uuid,uuid,uuid,text,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_successor_creation_current(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_creation_current(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_successor_creation_current(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_relation_actual_content(uuid,uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_relation_actual_content(uuid,uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_relation_actual_content(uuid,uuid,bigint) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_relation_repair(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_relation_repair(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_relation_repair(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_request_relation_repair(uuid,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_request_relation_repair(uuid,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_request_relation_repair(uuid,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_relation_repair_current(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_relation_repair_current(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_relation_repair_current(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_native_public_fallback_frame(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_public_fallback_frame(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_native_public_fallback_frame(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_public_fallback_record(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_public_fallback_record(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_public_fallback_record(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_public_fallback_for_creation(tutor_item_supply_native_consumer_receipts,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_public_fallback_for_creation(tutor_item_supply_native_consumer_receipts,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_public_fallback_for_creation(tutor_item_supply_native_consumer_receipts,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.public_normal_mapping_current(uuid,uuid,bigint) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.public_normal_mapping_current(uuid,uuid,bigint) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.public_normal_mapping_current(uuid,uuid,bigint) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.public_native_source_current(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.public_native_source_current(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.public_native_source_current(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_persistent_prestart_recovery(jsonb,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_prestart_recovery(jsonb,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_persistent_prestart_recovery(jsonb,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_persistent_explicit_recovery(jsonb,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_explicit_recovery(jsonb,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_persistent_explicit_recovery(jsonb,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_committed_revision_execution(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_revision_execution(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_committed_revision_execution(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.fresh_committed_revision_matches(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.fresh_committed_revision_matches(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.fresh_committed_revision_matches(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_revision_generation_output_current(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_revision_generation_output_current(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_revision_generation_output_current(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.confirmed_source_successor_allowed(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.confirmed_source_successor_allowed(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.confirmed_source_successor_allowed(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_source_mapping_successor(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_source_mapping_successor(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_source_mapping_successor(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.revision_source_successor_matches(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.revision_source_successor_matches(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.revision_source_successor_matches(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_committed_child_history(uuid,uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_history(uuid,uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_committed_child_history(uuid,uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.committed_child_version_data_matches(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.committed_child_version_data_matches(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.committed_child_version_data_matches(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_committed_child_recheck(jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_recheck(jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_committed_child_recheck(jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_normal_revision_readmission_v2(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission_v2(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_normal_revision_readmission_v2(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_committed_child_quality(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_quality(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_committed_child_quality(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_committed_child_admission(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_admission(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_committed_child_admission(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.committed_child_admission_for_job(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.committed_child_admission_for_job(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.committed_child_admission_for_job(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_normal_revision_readmission_v3(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission_v3(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_normal_revision_readmission_v3(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.committed_child_evaluation_matches(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.committed_child_evaluation_matches(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.committed_child_evaluation_matches(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.current_pack_public_materials_current(jsonb,timestamptz) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_public_materials_current(jsonb,timestamptz) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.current_pack_public_materials_current(jsonb,timestamptz) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.current_pack_source_receipts_match(jsonb,jsonb,timestamptz) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_source_receipts_match(jsonb,jsonb,timestamptz) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.current_pack_source_receipts_match(jsonb,jsonb,timestamptz) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.current_pack_source_origin_payload_current(jsonb,uuid,bigint,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_source_origin_payload_current(jsonb,uuid,bigint,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.current_pack_source_origin_payload_current(jsonb,uuid,bigint,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.current_pack_source_origin_current(uuid,uuid,bigint,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.current_pack_source_origin_current(uuid,uuid,bigint,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.current_pack_source_origin_current(uuid,uuid,bigint,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.native_consumer_source_context_current(uuid,jsonb,uuid,bigint,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.native_consumer_source_context_current(uuid,jsonb,uuid,bigint,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.native_consumer_source_context_current(uuid,jsonb,uuid,bigint,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_development_accounting_batch_current(tutor_item_supply_private_development_model_accounting_batches) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_development_accounting_batch_current(tutor_item_supply_private_development_model_accounting_batches) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_development_accounting_batch_current(tutor_item_supply_private_development_model_accounting_batches) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.m03_p2_normal_loop_for_job(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.m03_p2_normal_loop_for_job(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.m03_p2_normal_loop_for_job(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_m03_p2_investigation(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_m03_p2_investigation(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_m03_p2_investigation(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_reports(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_reports(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_reports(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_blind_original(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_blind_original(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_blind_original(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_binding(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_binding(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_binding(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_blind_score(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_blind_score(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_blind_score(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_changed_paths(jsonb,jsonb,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_changed_paths(jsonb,jsonb,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_changed_paths(jsonb,jsonb,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_primary_dependency(jsonb,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_primary_dependency(jsonb,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_primary_dependency(jsonb,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_shared_source_deadline(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_shared_source_deadline(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_shared_source_deadline(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_shared_source_current(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_shared_source_current(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_shared_source_current(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_incremental_shared_current(jsonb,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_incremental_shared_current(jsonb,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_incremental_shared_current(jsonb,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.incremental_material_failure(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.incremental_material_failure(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.incremental_material_failure(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_incremental_direct_revision(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_incremental_direct_revision(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_incremental_direct_revision(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_incremental_local_diff(jsonb,jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_incremental_local_diff(jsonb,jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_incremental_local_diff(jsonb,jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_shared_incremental_coverage(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_incremental_coverage(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_shared_incremental_coverage(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.persist_shared_incremental_coverage(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.persist_shared_incremental_coverage(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.persist_shared_incremental_coverage(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.require_shared_incremental_coverage(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.require_shared_incremental_coverage(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.require_shared_incremental_coverage(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_normal_committed_review_frame(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_committed_review_frame(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_normal_committed_review_frame(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_incremental_frame(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_incremental_frame(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_incremental_frame(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_incremental_committed_action(jsonb,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_incremental_committed_action(jsonb,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_incremental_committed_action(jsonb,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.private_native_incremental_evidence_v1(text,jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_incremental_evidence_v1(text,jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.private_native_incremental_evidence_v1(text,jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_incremental_blind_rescore(jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_incremental_blind_rescore(jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_incremental_blind_rescore(jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_incremental_coverage(jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_incremental_coverage(jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_incremental_coverage(jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_shared_review_probe_frame(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_review_probe_frame(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_shared_review_probe_frame(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_review_probe_event_v1(text,jsonb,jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_review_probe_event_v1(text,jsonb,jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_review_probe_event_v1(text,jsonb,jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.require_private_incremental_coverage(jsonb,uuid,bigint,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.require_private_incremental_coverage(jsonb,uuid,bigint,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.require_private_incremental_coverage(jsonb,uuid,bigint,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_shared_blind_applicability(jsonb,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_blind_applicability(jsonb,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_shared_blind_applicability(jsonb,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_shared_review_adjudication(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_review_adjudication(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_shared_review_adjudication(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.original_review_counterexample_statement(text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.original_review_counterexample_statement(text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.original_review_counterexample_statement(text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_shared_adjudicated_facts(tutor_item_supply_shared_admission_facts) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_adjudicated_facts(tutor_item_supply_shared_admission_facts) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_shared_adjudicated_facts(tutor_item_supply_shared_admission_facts) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_adjudicated_evaluation_matches(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_adjudicated_evaluation_matches(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_adjudicated_evaluation_matches(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_direct_preparation(uuid,uuid,uuid,jsonb,timestamptz) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_direct_preparation(uuid,uuid,uuid,jsonb,timestamptz) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_direct_preparation(uuid,uuid,uuid,jsonb,timestamptz) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_private_incremental_normal(tutor_item_supply_private_native_quality_evidence) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_incremental_normal(tutor_item_supply_private_native_quality_evidence) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_private_incremental_normal(tutor_item_supply_private_native_quality_evidence) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_adjudicated_import_action(jsonb,uuid,uuid,uuid,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_adjudicated_import_action(jsonb,uuid,uuid,uuid,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_adjudicated_import_action(jsonb,uuid,uuid,uuid,text) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_shared_validation_applicability(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_validation_applicability(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_shared_validation_applicability(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.persist_shared_validation_applicability(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.persist_shared_validation_applicability(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.persist_shared_validation_applicability(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_continuation_validation_inherited(uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_continuation_validation_inherited(uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_continuation_validation_inherited(uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_validation_inherited_receipt_matches(uuid,uuid,uuid) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_validation_inherited_receipt_matches(uuid,uuid,uuid) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_validation_inherited_receipt_matches(uuid,uuid,uuid) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.assert_shared_committed_same_child_coverage(jsonb) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.assert_shared_committed_same_child_coverage(jsonb) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.assert_shared_committed_same_child_coverage(jsonb) TO aearn_cb_runtime_20261027;

ALTER FUNCTION item_supply_internal.shared_review_probe_intent_for_reservation(uuid,uuid,integer,text) OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON FUNCTION item_supply_internal.shared_review_probe_intent_for_reservation(uuid,uuid,integer,text) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

GRANT EXECUTE ON FUNCTION item_supply_internal.shared_review_probe_intent_for_reservation(uuid,uuid,integer,text) TO aearn_cb_runtime_20261027;

GRANT EXECUTE ON FUNCTION completion_baseline_internal.contract_identity() TO aearn_cb_verifier_20261027;
-- BEGIN finite ordinary-consumer and schema-definer base privileges
-- No background worker/operator grant is implied by a shared Python module.
-- app/services/learning/artifacts/repository.py:1160 | app/services/repositories/local_user_data_repository.py:1915
GRANT SELECT,DELETE ON TABLE public.attempts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1952
GRANT SELECT,DELETE ON TABLE public.code_blanks TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1913
GRANT SELECT,DELETE ON TABLE public.exercise_variant_cache TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1940 | app/services/repositories/local_user_data_repository.py:1964
GRANT SELECT,DELETE ON TABLE public.exercises TO aearn_cb_runtime_20261027;
-- app/services/grounding/grounding_index_repository.py:297 [_load_grounding_chunks_for_languages]
GRANT SELECT ON TABLE public.grounding_chunks TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:425 | app/services/tutor/cutover.py:552 | app/services/tutor/cutover.py:563 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.harness_cutovers TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1882
GRANT SELECT,DELETE ON TABLE public.idempotency_records TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1917 | app/services/repositories/local_user_data_repository.py:1976
GRANT SELECT,UPDATE,DELETE ON TABLE public.knowledge_points TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1995
GRANT SELECT,DELETE ON TABLE public.learner_profiles TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1884
GRANT SELECT,DELETE ON TABLE public.learning_messages TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1917 | app/services/repositories/local_user_data_repository.py:1974 | app/services/repositories/local_user_data_repository.py:1994
GRANT SELECT,UPDATE,DELETE ON TABLE public.learning_plans TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1884 | app/services/repositories/local_user_data_repository.py:1927
GRANT SELECT,DELETE ON TABLE public.learning_sessions TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1914
GRANT SELECT,DELETE ON TABLE public.notes TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1902 | app/services/repositories/local_user_data_repository.py:1996
GRANT SELECT,DELETE ON TABLE public.onboarding_conversations TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1902
GRANT SELECT,DELETE ON TABLE public.onboarding_messages TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1917 | app/services/repositories/local_user_data_repository.py:1986
GRANT SELECT,DELETE ON TABLE public.plan_modules TO aearn_cb_runtime_20261027;
-- app/services/grounding/autonomous/context_repository.py:330 [export_user_refs] | app/services/grounding/autonomous/context_repository.py:364 [unlink_user]
GRANT SELECT,DELETE ON TABLE public.rag_candidate_private_refs TO aearn_cb_runtime_20261027;
-- app/services/grounding/autonomous/context_repository.py:325 [export_user_refs] | app/services/grounding/autonomous/context_repository.py:353 [unlink_user] [row lock] | app/services/grounding/autonomous/context_repository.py:369 [unlink_user]
GRANT SELECT,UPDATE,DELETE ON TABLE public.rag_discovery_actor_owners TO aearn_cb_runtime_20261027;
-- app/services/grounding/autonomous/context_repository.py:325 [export_user_refs] | app/services/grounding/autonomous/context_repository.py:367 [unlink_user]
GRANT SELECT,DELETE ON TABLE public.rag_discovery_job_refs TO aearn_cb_runtime_20261027;
-- app/services/grounding/material_binding_repository.py:159 | app/services/grounding/material_binding_repository.py:159 [row lock]
GRANT SELECT,UPDATE ON TABLE public.rag_discovery_jobs TO aearn_cb_runtime_20261027;
-- app/services/grounding/autonomous/context_repository.py:360 [unlink_user]
GRANT SELECT,DELETE ON TABLE public.rag_discovery_private_contexts TO aearn_cb_runtime_20261027;
-- app/services/grounding/material_binding_repository.py:189 | app/services/grounding/material_binding_repository.py:201 | app/services/grounding/material_binding_repository.py:189 [row lock] | app/services/repositories/local_user_data_repository.py:1739
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.rag_material_selections TO aearn_cb_runtime_20261027;
-- app/services/learning/material_selection.py:517 [review_decision] | app/services/learning/material_selection.py:548 [review_decision] | app/services/learning/material_selection.py:517 [review_decision] [row lock] | app/services/repositories/local_user_data_repository.py:1738
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.rag_material_semantic_reviews TO aearn_cb_runtime_20261027;
-- app/services/grounding/material_binding_repository.py:365 | app/services/grounding/material_binding_repository.py:384 | app/services/grounding/material_binding_repository.py:365 [row lock] | app/services/repositories/local_user_data_repository.py:1737
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.rag_plan_material_bindings TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1910
GRANT SELECT,DELETE ON TABLE public.review_logs TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1893
GRANT SELECT,DELETE ON TABLE public.review_messages TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1912
GRANT SELECT,DELETE ON TABLE public.review_seed_banks TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1911
GRANT SELECT,DELETE ON TABLE public.review_states TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1929
GRANT SELECT,DELETE ON TABLE public.teaching_chunks TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1940
GRANT SELECT,DELETE ON TABLE public.test_cases TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1591
GRANT SELECT,DELETE ON TABLE public.tutor_action_attempts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1584 | app/services/repositories/local_user_data_repository.py:1615
GRANT SELECT,DELETE ON TABLE public.tutor_action_invocations TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1326 | app/services/repositories/local_user_data_repository.py:1578
GRANT SELECT,DELETE ON TABLE public.tutor_action_receipts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1584
GRANT SELECT,DELETE ON TABLE public.tutor_action_verifications TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:192 | app/services/tutor/learner_state.py:260 | app/services/tutor/learner_state.py:218 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_active_plans TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:198 | app/services/tutor/learner_state.py:457
GRANT SELECT,INSERT ON TABLE public.tutor_activity_records TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_service.py:220 | app/services/learning/lesson_service.py:232 | app/services/learning/lesson_service.py:220 [row lock] | app/services/repositories/local_user_data_repository.py:1796
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_api_idempotency_records TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:176 | app/services/tutor/persistence/effects.py:368 | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_capability_invocations TO aearn_cb_runtime_20261027;
-- app/services/tutor/persistence/effects.py:1100 | app/services/tutor/persistence/repository.py:94
GRANT SELECT,INSERT ON TABLE public.tutor_catalog_snapshots TO aearn_cb_runtime_20261027;
-- app/services/tutor/runtime_selection.py:128 | app/services/tutor/runtime_selection.py:94
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_codex_runtime_health TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:196 | app/services/tutor/learner_state.py:1014
GRANT SELECT,INSERT ON TABLE public.tutor_context_summaries TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1141 | app/services/tutor/continuation.py:780 | app/services/repositories/local_user_data_repository.py:1529
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_continuation_intent_events TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1072 | app/services/tutor/continuation.py:215 | app/services/tutor/continuation.py:173 [row lock] | app/services/repositories/local_user_data_repository.py:1533
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_continuation_intents TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1060 | app/services/tutor/branching.py:501 | app/services/repositories/local_user_data_repository.py:1545
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_conversation_branch_events TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1589 | app/services/tutor/branching.py:901 | app/services/repositories/local_user_data_repository.py:1537
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_conversation_branch_items TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1589 | app/services/tutor/branching.py:665 | app/services/learning/teaching_sessions.py:272 [row lock] | app/services/repositories/local_user_data_repository.py:1549
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_conversation_branches TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1553 | app/services/tutor/persistence/conversation.py:1281
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_conversation_events TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:141 | app/services/learning/track_repository.py:484 | app/services/learning/track_repository.py:479 [row lock] | app/services/repositories/local_user_data_repository.py:1762
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_conversation_learning_scopes TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:160 | app/services/tutor/runtime_projection.py:232 | app/services/tutor/runtime_projection.py:219 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_conversation_runtime_threads TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1001 | app/services/tutor/persistence/conversation.py:17 | app/services/learning/artifacts/repository.py:1001 [row lock] | app/services/repositories/local_user_data_repository.py:1867
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_conversations TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:189
GRANT SELECT ON TABLE public.tutor_curation_jobs TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:197 | app/services/tutor/learner_state.py:1269
GRANT SELECT,INSERT ON TABLE public.tutor_curation_projection_receipts TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:182 | app/services/tutor/learner_state.py:1541 [row lock]
GRANT SELECT,UPDATE ON TABLE public.tutor_curation_proposals TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1569
GRANT SELECT,DELETE ON TABLE public.tutor_demonstration_completion_receipts TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:177 | app/services/tutor/persistence/effects.py:1196 | app/services/tutor/learner_state.py:1520 [row lock] | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_effects TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1628
GRANT SELECT,DELETE ON TABLE public.tutor_execution_attempts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1639
GRANT SELECT,DELETE ON TABLE public.tutor_execution_intents TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:195 | app/services/repositories/local_user_data_repository.py:1619 | app/services/repositories/local_user_data_repository.py:1638
GRANT SELECT,UPDATE,DELETE ON TABLE public.tutor_execution_jobs TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1160 | app/services/repositories/local_user_data_repository.py:1680
GRANT SELECT,DELETE ON TABLE public.tutor_exercise_attempt_results TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1204 | app/services/repositories/local_user_data_repository.py:1681
GRANT SELECT,DELETE ON TABLE public.tutor_exercise_attempt_submissions TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1160 | app/services/repositories/local_user_data_repository.py:1682
GRANT SELECT,DELETE ON TABLE public.tutor_exercise_attempts TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:195 | app/services/repositories/local_user_data_repository.py:1637
GRANT SELECT,DELETE ON TABLE public.tutor_exercise_execution_links TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1687
GRANT SELECT,DELETE ON TABLE public.tutor_exercise_hint_receipts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1177
GRANT SELECT ON TABLE public.tutor_exercise_versions TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:199 | app/services/tutor/learner_state.py:480 | app/services/tutor/learner_state.py:1408
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_inbox_items TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1411 | app/services/tutor/persistence/interaction.py:932 | app/services/tutor/persistence/interaction.py:167 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_interaction_requests TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:561 | app/services/tutor/persistence/dispatch.py:276 | app/services/tutor/persistence/dispatch.py:101 | app/services/repositories/local_user_data_repository.py:1811
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_interactive_dispatch_jobs TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1023 | app/services/repositories/local_user_data_repository.py:1563
GRANT SELECT,DELETE ON TABLE public.tutor_knowledge_check_assistance_receipts TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1166 | app/services/repositories/local_user_data_repository.py:1564
GRANT SELECT,DELETE ON TABLE public.tutor_knowledge_check_response_receipts TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1342 | app/services/learning/artifacts/repository.py:1366 | app/services/repositories/local_user_data_repository.py:1568
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_learning_artifact_attempt_links TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1411 | app/services/repositories/local_user_data_repository.py:1566
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_learning_artifact_events TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1693 | app/services/learning/artifacts/repository.py:686 | app/services/repositories/local_user_data_repository.py:1567
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_learning_artifact_references TO aearn_cb_runtime_20261027;
-- app/services/learning/artifacts/repository.py:1026 | app/services/learning/artifacts/repository.py:602 | app/services/learning/artifacts/repository.py:1239 | app/services/repositories/local_user_data_repository.py:1570
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_learning_artifacts TO aearn_cb_runtime_20261027;
-- deployed invoker public.enforce_tutor_learning_artifact_owner_scope() [runtime]
GRANT SELECT ON TABLE public.tutor_learning_item_practice_materializations TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1039
GRANT SELECT ON TABLE public.tutor_learning_item_public_contents TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1039
GRANT SELECT ON TABLE public.tutor_learning_item_publication_events TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1039
GRANT SELECT ON TABLE public.tutor_learning_item_versions TO aearn_cb_runtime_20261027;
-- app/services/grounding/material_binding_repository.py:106 | app/services/learning/plan_repository.py:184 | app/services/grounding/material_binding_repository.py:106 [row lock] | app/services/repositories/local_user_data_repository.py:1759
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_learning_plan_drafts TO aearn_cb_runtime_20261027;
-- app/services/grounding/material_binding_repository.py:250 | app/services/learning/plan_repository.py:54 | app/services/learning/plan_repository.py:230 | app/services/repositories/local_user_data_repository.py:1760
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_learning_plan_sessions TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:115 | app/services/learning/track_repository.py:88 | app/services/learning/lesson_repository.py:648 | app/services/repositories/local_user_data_repository.py:1795
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_learning_tracks TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:388 | app/services/learning/lesson_repository.py:808 | app/services/learning/lesson_repository.py:618 [row lock] | app/services/repositories/local_user_data_repository.py:1695
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_lesson_assignments TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:432 | app/services/repositories/local_user_data_repository.py:1693
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_lesson_authoring_attempt_receipts TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:181 | app/services/learning/lesson_repository.py:191 | app/services/learning/lesson_repository.py:181 [row lock] | app/services/repositories/local_user_data_repository.py:1694
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_lesson_authoring_runs TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:241 | app/services/learning/lesson_repository.py:360 | app/services/learning/lesson_repository.py:388 | app/services/tutor/completion_data.py:67
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_lesson_authoring_stage_attempts TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:773 | app/services/repositories/local_user_data_repository.py:1696
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_lesson_block_citations TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:388 | app/services/learning/lesson_repository.py:723 | app/services/repositories/local_user_data_repository.py:1699
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_lesson_documents TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1177 | app/services/repositories/local_user_data_repository.py:1691
GRANT SELECT,DELETE ON TABLE public.tutor_lesson_gate_bindings TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:778 | app/services/repositories/local_user_data_repository.py:1697
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_lesson_gate_slots TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1177 | app/services/repositories/local_user_data_repository.py:1688
GRANT SELECT,DELETE ON TABLE public.tutor_lesson_gate_states TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:608 | app/services/learning/lesson_repository.py:752 | app/services/repositories/local_user_data_repository.py:1698
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_lesson_source_snapshots TO aearn_cb_runtime_20261027;
-- app/services/learning/track_repository.py:659 | app/services/learning/track_repository.py:706 | app/services/learning/track_repository.py:659 [row lock] | app/services/repositories/local_user_data_repository.py:1764
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_mastery_evidence TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:115 | app/services/learning/track_repository.py:405 | app/services/learning/track_repository.py:956 | app/services/repositories/local_user_data_repository.py:1763
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_mastery_states TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:181 | app/services/tutor/persistence/curation.py:277 [_upsert_outbox_locked] | app/services/tutor/learner_state.py:1541 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_memory_curation_outbox TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:195 | app/services/tutor/learner_state.py:1180 | app/services/tutor/learner_state.py:604 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_memory_entries TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:194 | app/services/tutor/learner_state.py:529 | app/services/tutor/learner_state.py:517 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_memory_preferences TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:148 | app/services/learning/context_references.py:96 | app/services/repositories/local_user_data_repository.py:1576
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_message_context_references TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:176 | app/services/tutor/persistence/public_process.py:604 | app/services/repositories/local_user_data_repository.py:1863
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_messages TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1293 | app/services/repositories/local_user_data_repository.py:1565
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_artifact_receipts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1672
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_authoring_attempt_receipts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1364 | app/services/repositories/local_user_data_repository.py:1673
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_authoring_runs TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1383 | app/services/repositories/local_user_data_repository.py:1671
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_candidates TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1448 | app/services/repositories/local_user_data_repository.py:1655
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_evidence_receipts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1430 | app/services/repositories/local_user_data_repository.py:1669
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_publications TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1401 | app/services/repositories/local_user_data_repository.py:1656
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_validation_checks TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1401 | app/services/repositories/local_user_data_repository.py:1670
GRANT SELECT,DELETE ON TABLE public.tutor_model_review_validation_runs TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1239 | app/services/repositories/local_user_data_repository.py:1689
GRANT SELECT,DELETE ON TABLE public.tutor_module_diagnostic_items TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1239 | app/services/repositories/local_user_data_repository.py:1690
GRANT SELECT,DELETE ON TABLE public.tutor_module_diagnostic_sessions TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1239
GRANT SELECT ON TABLE public.tutor_module_diagnostic_versions TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:193 | app/services/tutor/learner_state.py:269
GRANT SELECT,INSERT ON TABLE public.tutor_plan_revision_actions TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:191 | app/services/tutor/learner_state.py:233 | app/services/tutor/learner_state.py:304 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_plan_revisions TO aearn_cb_runtime_20261027;
-- app/services/learning/planning_facts.py:300 | app/services/repositories/local_user_data_repository.py:1732
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_planning_intake_facts TO aearn_cb_runtime_20261027;
-- app/services/learning/planning_facts.py:489 | app/services/learning/planning_facts.py:699 | app/services/repositories/local_user_data_repository.py:1718
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_planning_question_events TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:188
GRANT SELECT ON TABLE public.tutor_proactive_candidates TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:186
GRANT SELECT ON TABLE public.tutor_proactive_preferences TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:187
GRANT SELECT ON TABLE public.tutor_proactive_signals TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:178 | app/services/tutor/persistence/effects.py:649
GRANT SELECT,INSERT ON TABLE public.tutor_provider_attempt_receipts TO aearn_cb_runtime_20261027;
-- app/services/tutor/continuation.py:881 | app/services/tutor/queue_control.py:616 | app/services/tutor/queue_control.py:138 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_queued_inputs TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1309 | app/services/repositories/local_user_data_repository.py:1652
GRANT SELECT,DELETE ON TABLE public.tutor_review_finalizations TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1653
GRANT SELECT,DELETE ON TABLE public.tutor_review_hint_receipts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1284 | app/services/repositories/local_user_data_repository.py:1683
GRANT SELECT,DELETE ON TABLE public.tutor_review_items TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1685
GRANT SELECT,DELETE ON TABLE public.tutor_review_schedule_events TO aearn_cb_runtime_20261027;
-- app/services/learning/track_repository.py:240 | app/services/repositories/local_user_data_repository.py:1686
GRANT SELECT,DELETE ON TABLE public.tutor_review_schedule_states TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:592 | app/services/repositories/local_user_data_repository.py:1684
GRANT SELECT,DELETE ON TABLE public.tutor_review_sessions TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1654
GRANT SELECT,DELETE ON TABLE public.tutor_review_warmup_receipts TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1081 | app/services/tutor/branching.py:196 | app/services/repositories/local_user_data_repository.py:1541
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_branch_scopes TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:173 | app/services/tutor/persistence/curation.py:171 [_persist_checkpoint_and_outbox_locked] | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_checkpoints TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:172 | app/services/tutor/persistence/run.py:1044 | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_events TO aearn_cb_runtime_20261027;
-- app/services/tutor/completion_execution.py:278 | app/services/tutor/completion_execution.py:296 | app/services/tutor/completion_execution.py:278 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_run_execution_batches TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:176 | app/services/tutor/persistence/run.py:406 | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_input_events TO aearn_cb_runtime_20261027;
-- app/services/grounding/material_binding_repository.py:256 | app/services/learning/teaching_sessions.py:1565 | app/services/grounding/material_binding_repository.py:256 [row lock] | app/services/repositories/local_user_data_repository.py:1761
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_run_learning_scopes TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:180 | app/services/tutor/persistence/public_process.py:42 | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_public_process_steps TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:176 | app/services/tutor/persistence/public_process.py:21 | app/services/tutor/persistence/interaction.py:1164 | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_run_public_processes TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:161 | app/services/tutor/runtime_projection.py:382 | app/services/tutor/runtime_projection.py:1055 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_run_runtime_bindings TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:175 | app/services/tutor/persistence/effects.py:183 | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_skill_selections TO aearn_cb_runtime_20261027;
-- app/services/tutor/completion_execution.py:254 | app/services/tutor/completion_execution.py:355 | app/services/tutor/completion_execution.py:254 [row lock]
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_run_step_attempts TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1507 | app/services/learning/teaching_sessions.py:1520 | app/services/repositories/local_user_data_repository.py:1573
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_stimulus_events TO aearn_cb_runtime_20261027;
-- app/services/learning/context_references.py:176 | app/services/learning/teaching_sessions.py:1535 | app/services/repositories/local_user_data_repository.py:1572
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_teaching_scopes TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:174 | app/services/tutor/persistence/effects.py:1285 | app/services/repositories/local_user_data_repository.py:1826 [fixed table loop]
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_run_traces TO aearn_cb_runtime_20261027;
-- app/services/grounding/material_binding_repository.py:106 | app/services/tutor/persistence/run.py:62 | app/services/grounding/material_binding_repository.py:106 [row lock] | app/services/repositories/local_user_data_repository.py:1847
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_runs TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:163 | app/services/tutor/runtime_projection.py:1188
GRANT SELECT,INSERT ON TABLE public.tutor_runtime_item_receipts TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:164 | app/services/tutor/runtime_projection.py:1152
GRANT SELECT,INSERT ON TABLE public.tutor_runtime_public_errors TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:162 | app/services/tutor/runtime_projection.py:705 | app/services/tutor/runtime_projection.py:1013
GRANT SELECT,INSERT,UPDATE ON TABLE public.tutor_runtime_text_items TO aearn_cb_runtime_20261027;
-- app/services/tutor/cutover.py:190
GRANT SELECT ON TABLE public.tutor_scheduler_audit TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:853 | app/services/tutor/persistence/effects.py:1051 | app/services/repositories/local_user_data_repository.py:1571
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_teaching_action_receipts TO aearn_cb_runtime_20261027;
-- app/services/learning/teaching_sessions.py:1491 | app/services/repositories/local_user_data_repository.py:1574
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_teaching_session_checkpoints TO aearn_cb_runtime_20261027;
-- app/services/learning/catalog_scope.py:27 | app/services/learning/teaching_sessions.py:239 | app/services/learning/teaching_sessions.py:220 [row lock] | app/services/repositories/local_user_data_repository.py:1575
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_teaching_sessions TO aearn_cb_runtime_20261027;
-- app/services/tutor/thread_turn_cutover.py:350 [_ensure_record]
GRANT SELECT ON TABLE public.tutor_thread_turn_cutovers TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:115 | app/services/learning/track_repository.py:110 | app/services/learning/track_repository.py:380 | app/services/repositories/local_user_data_repository.py:1770
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_track_active_plans TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:115 | app/services/learning/track_repository.py:396 | app/services/learning/lesson_repository.py:631 | app/services/repositories/local_user_data_repository.py:1766
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_track_node_progress TO aearn_cb_runtime_20261027;
-- app/services/learning/track_repository.py:223 | app/services/learning/track_repository.py:319 | app/services/learning/track_repository.py:366 [row lock] | app/services/repositories/local_user_data_repository.py:1767
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_track_plan_migrations TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:115 | app/services/learning/track_repository.py:773 | app/services/repositories/local_user_data_repository.py:1769
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_track_plan_modules TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:115 | app/services/learning/track_repository.py:786 | app/services/repositories/local_user_data_repository.py:1768
GRANT SELECT,INSERT,DELETE ON TABLE public.tutor_track_plan_nodes TO aearn_cb_runtime_20261027;
-- app/services/learning/track_repository.py:223 | app/services/learning/track_repository.py:746 | app/services/learning/track_repository.py:355 [row lock] | app/services/repositories/local_user_data_repository.py:1792
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_track_plan_revisions TO aearn_cb_runtime_20261027;
-- app/services/repositories/local_user_data_repository.py:1815 | app/services/tutor/persistence/public_process.py:294 | app/services/tutor/persistence/public_process.py:287 [row lock]
GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.tutor_turn_public_thinking_streams TO aearn_cb_runtime_20261027;
-- app/services/learning/lesson_repository.py:210 | app/services/repositories/user_repository.py:40 | app/services/repositories/local_user_data_repository.py:269
GRANT SELECT,INSERT,UPDATE ON TABLE public.users TO aearn_cb_runtime_20261027;
-- thread_turn_cutover._ensure_record inserts only the singleton identity;
-- prepare/enable/rollback mutation remains unavailable to runtime.
GRANT INSERT(cutover_version) ON TABLE public.tutor_thread_turn_cutovers TO aearn_cb_runtime_20261027;
-- Trusted NOLOGIN definer: only reached guard/maintenance accesses.
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_source_review_guard()
GRANT SELECT ON TABLE public.rag_candidate_captures TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_actual_d_private_purge(uuid)
GRANT SELECT ON TABLE public.rag_material_selections TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_actual_d_private_purge(uuid)
GRANT SELECT ON TABLE public.rag_material_semantic_reviews TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_actual_d_private_purge(uuid)
GRANT SELECT ON TABLE public.rag_plan_material_bindings TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_source_review_guard()
GRANT SELECT ON TABLE public.rag_registered_source_captures TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_source_review_guard()
GRANT SELECT ON TABLE public.rag_registered_source_policies TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_closed_native_consumer() | app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_source_claim_guard() [row lock] | app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_actual_d_private_purge(uuid)
GRANT SELECT,UPDATE,DELETE ON TABLE public.rag_source_admissions TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_actual_d_private_purge(uuid)
GRANT SELECT,DELETE ON TABLE public.rag_source_claim_receipts TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_closed_native_consumer() | app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_source_claim_guard() [row lock] | app/db/schema/599_completion_non_b1d_baseline.sql:public.rag_actual_d_private_purge(uuid)
GRANT SELECT,UPDATE,DELETE ON TABLE public.rag_source_reviews TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_technical_origin()
GRANT SELECT ON TABLE public.tutor_exercise_attempts TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_technical_origin()
GRANT SELECT ON TABLE public.tutor_exercise_hint_receipts TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:item_supply_internal.purge_private_native_on_epoch_advance()
GRANT SELECT,DELETE ON TABLE public.tutor_exercise_private_rubrics TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:item_supply_internal.purge_private_native_on_epoch_advance()
GRANT SELECT,DELETE ON TABLE public.tutor_exercise_versions TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_technical_origin()
GRANT SELECT ON TABLE public.tutor_knowledge_check_assistance_receipts TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:item_supply_internal.purge_private_native_kc_on_epoch()
GRANT SELECT,DELETE ON TABLE public.tutor_knowledge_check_response_receipts TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_technical_origin()
GRANT SELECT ON TABLE public.tutor_learning_artifact_events TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.capture_native_exposure_origin()
GRANT SELECT ON TABLE public.tutor_learning_artifacts TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.capture_native_exposure_origin()
GRANT SELECT ON TABLE public.tutor_learning_item_practice_materializations TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.enforce_item_supply_private_epoch()
GRANT SELECT ON TABLE public.tutor_learning_tracks TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.capture_native_exposure_origin()
GRANT SELECT ON TABLE public.tutor_lesson_documents TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_technical_origin()
GRANT SELECT ON TABLE public.tutor_lesson_gate_bindings TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.capture_native_exposure_origin()
GRANT SELECT ON TABLE public.tutor_teaching_sessions TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.enforce_item_supply_private_epoch() | app/db/schema/599_completion_non_b1d_baseline.sql:public.enforce_item_supply_private_epoch() [row lock]
GRANT SELECT,UPDATE ON TABLE public.tutor_track_active_plans TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:public.enforce_item_supply_private_epoch() | app/db/schema/599_completion_non_b1d_baseline.sql:public.enforce_item_supply_private_epoch() [row lock]
GRANT SELECT,UPDATE ON TABLE public.tutor_track_plan_nodes TO aearn_cb_schema_20261027;
-- app/db/schema/599_completion_non_b1d_baseline.sql:completion_baseline_internal.enforce_technical_origin() | app/db/schema/599_completion_non_b1d_baseline.sql:item_supply_internal.native_exposure_lock(uuid,bigint) [row lock]
GRANT SELECT,UPDATE ON TABLE public.users TO aearn_cb_schema_20261027;
-- END finite ordinary-consumer and schema-definer base privileges

-- Keep all three completion tables under their existing owners/guards; neither
-- supply purge nor its epoch hooks deletes Tutor runs/batches/steps/sidecar audit.
-- Lesson deletion remains the pre-existing original user purge path (597).
REVOKE ALL ON TABLE completion_baseline_internal.installation_identity,completion_baseline_internal.validation_permits,item_supply_internal.reset_permits FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;

-- All new/replaced callable bodies have an explicit lookup path, including
-- preserved invoker source guards; body text and original nonassessment rules remain.
ALTER FUNCTION public.rag_actual_d_finite_storage_profile(text) SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
ALTER FUNCTION public.rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz) SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
ALTER FUNCTION public.rag_course_material_proof_lifetime_allowed(jsonb,text,timestamptz,timestamptz) SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
ALTER FUNCTION public.rag_actual_d_private_reference_guard() SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
ALTER FUNCTION public.rag_source_review_guard() SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
ALTER FUNCTION public.rag_source_admission_guard() SET search_path=pg_catalog,public,item_supply_internal,pg_temp;
ALTER FUNCTION public.rag_source_claim_guard() SET search_path=pg_catalog,public,item_supply_internal,pg_temp;

-- Both implicit sequences are finite managed objects, not ignored namespace extras.
ALTER SEQUENCE public.tutor_item_supply_native_exposure_inbox_sequence_seq OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON SEQUENCE public.tutor_item_supply_native_exposure_inbox_sequence_seq FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
ALTER SEQUENCE public.tutor_item_supply_private_native_exposure_origins_sequence_seq OWNER TO aearn_cb_schema_20261027;
REVOKE ALL ON SEQUENCE public.tutor_item_supply_private_native_exposure_origins_sequence_seq FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;
