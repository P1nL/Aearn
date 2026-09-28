-- C registered-source lane: no Tavily receipt is forged for operator-provisioned seeds.
-- Bootstrap creates structure only; no registration, source, permit or fetch is enabled.
CREATE TABLE IF NOT EXISTS rag_registered_source_policies (
  policy_id text PRIMARY KEY CHECK (policy_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  generation integer NOT NULL CHECK (generation >= 1),
  source_handle text NOT NULL CHECK (source_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  facets text[] NOT NULL CHECK (cardinality(facets) BETWEEN 1 AND 24),
  origin text NOT NULL CHECK (origin IN ('official','maintainer','tutorial','repository','community','blog')),
  reading_level text NOT NULL CHECK (reading_level IN ('beginner','intermediate','advanced')),
  canonical_url text NOT NULL CHECK (char_length(canonical_url) BETWEEN 9 AND 2048
    AND canonical_url ~ '^https://' AND canonical_url !~ '[@?#]' AND position(chr(92) in canonical_url)=0),
  canonical_url_sha256 text NOT NULL CHECK (canonical_url_sha256 ~ '^[0-9a-f]{64}$'),
  host text NOT NULL CHECK (host ~ '^[a-z0-9-]+(\.[a-z0-9-]+)+$' AND char_length(host)<=253),
  path text NOT NULL CHECK (path ~ '^/[A-Za-z0-9._~/-]*$' AND path !~ '(^|/)\.\.?(/|$)' AND path !~ '//'),
  license_id text NOT NULL CHECK (license_id ~ '^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$'),
  allowed_usages text[] NOT NULL CHECK (cardinality(allowed_usages) BETWEEN 1 AND 3
    AND allowed_usages <@ ARRAY['main_teaching','supplementary_explanation','assessment_evidence']::text[]),
  immutable_history_allowed boolean NOT NULL DEFAULT false,
  max_captured_bytes integer NOT NULL CHECK (max_captured_bytes BETWEEN 1 AND 1048576),
  retention_until timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  enabled boolean NOT NULL DEFAULT false,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (retention_until<=expires_at AND (revoked_at IS NULL OR NOT enabled)),
  UNIQUE(policy_id,generation),
  UNIQUE(source_handle,subject_id,subject_version,generation),
  UNIQUE(policy_id,generation,canonical_url_sha256)
);
ALTER TABLE rag_registered_source_policies
 ADD COLUMN IF NOT EXISTS immutable_history_allowed boolean NOT NULL DEFAULT false;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_rag_c_registered_exact_url') THEN
    ALTER TABLE rag_registered_source_policies ADD CONSTRAINT chk_rag_c_registered_exact_url
      CHECK (canonical_url='https://' || host || path
        AND canonical_url_sha256=encode(digest(canonical_url,'sha256'),'hex'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_rag_registered_source_scope
 ON rag_registered_source_policies(subject_id,subject_version,source_handle);

-- INSERT dispatched is the one-shot durable CAS. A crashed/lost response is unknown
-- and cannot be retried by replacing the attempt key or relabeling its root.
CREATE TABLE IF NOT EXISTS rag_registered_fetch_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_id text NOT NULL,
  generation integer NOT NULL,
  canonical_url_sha256 text NOT NULL,
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  operation_key text NOT NULL UNIQUE CHECK (operation_key ~ '^[a-zA-Z0-9._:-]{8,160}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'dispatched' CHECK (state IN ('dispatched','settled','unknown')),
  response_sha256 text CHECK (response_sha256 ~ '^[0-9a-f]{64}$'),
  response_bytes integer CHECK (response_bytes BETWEEN 0 AND 1048576),
  error_code text CHECK (error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  dispatched_at timestamptz NOT NULL DEFAULT now(),
  settled_at timestamptz,
  FOREIGN KEY(policy_id,generation,canonical_url_sha256)
    REFERENCES rag_registered_source_policies(policy_id,generation,canonical_url_sha256) ON DELETE RESTRICT,
  UNIQUE(policy_id,generation,canonical_url_sha256),
  UNIQUE(id,policy_id,generation),
  CHECK ((state='settled') = (response_sha256 IS NOT NULL AND response_bytes IS NOT NULL AND settled_at IS NOT NULL)),
  CHECK (state<>'unknown' OR error_code IS NOT NULL)
);
-- This C operator lane is intentionally one request per exact URL in the
-- disposable database, even if a new policy ID or generation is invented.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_registered_one_attempt_per_url
 ON rag_registered_fetch_attempts(canonical_url_sha256);
CREATE TABLE IF NOT EXISTS rag_registered_source_captures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fetch_attempt_id uuid NOT NULL UNIQUE,
  policy_id text NOT NULL,
  generation integer NOT NULL,
  request_chain jsonb NOT NULL CHECK (jsonb_typeof(request_chain)='array'
    AND jsonb_array_length(request_chain)=1 AND octet_length(request_chain::text)<=4096),
  final_url text NOT NULL CHECK (char_length(final_url) BETWEEN 9 AND 2048
    AND final_url ~ '^https://' AND final_url !~ '[@?#]' AND position(chr(92) in final_url)=0),
  content_type text NOT NULL CHECK (content_type IN ('text/html','text/plain','text/markdown')),
  fetched_sha256 text NOT NULL CHECK (fetched_sha256 ~ '^[0-9a-f]{64}$'),
  captured_bytes integer NOT NULL CHECK (captured_bytes BETWEEN 1 AND 1048576),
  captured_body bytea,
  license_id text NOT NULL CHECK (license_id ~ '^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$'),
  retention_until timestamptz NOT NULL,
  evidence_level text NOT NULL DEFAULT 'live_egress_attested' CHECK (evidence_level='live_egress_attested'),
  fetched_at timestamptz NOT NULL DEFAULT now(),
  cleared_at timestamptz,
  FOREIGN KEY(fetch_attempt_id,policy_id,generation)
    REFERENCES rag_registered_fetch_attempts(id,policy_id,generation) ON DELETE RESTRICT,
  CHECK ((cleared_at IS NULL AND captured_body IS NOT NULL
          AND octet_length(captured_body)=captured_bytes)
      OR (cleared_at IS NOT NULL AND captured_body IS NULL))
);
-- Optional only for historical/synthetic fixtures. Real host settlement writes
-- the full bounded signed-pre-dial + authenticated-worker report and operator pins.
ALTER TABLE rag_registered_source_captures ADD COLUMN IF NOT EXISTS transport_proof bytea;
ALTER TABLE rag_registered_source_captures ADD COLUMN IF NOT EXISTS transport_proof_sha256 text;
ALTER TABLE rag_registered_source_captures ADD COLUMN IF NOT EXISTS attestor_key_sha256 text;
ALTER TABLE rag_registered_source_captures ADD COLUMN IF NOT EXISTS worker_image_sha256 text;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_rag_c_capture_transport_proof') THEN
    ALTER TABLE rag_registered_source_captures ADD CONSTRAINT chk_rag_c_capture_transport_proof CHECK (
      (transport_proof IS NULL AND transport_proof_sha256 IS NULL
       AND attestor_key_sha256 IS NULL AND worker_image_sha256 IS NULL)
      OR (transport_proof IS NOT NULL AND octet_length(transport_proof) BETWEEN 1 AND 4096
       AND transport_proof_sha256 IS NOT NULL AND transport_proof_sha256 ~ '^[0-9a-f]{64}$'
       AND transport_proof_sha256=encode(digest(transport_proof,'sha256'),'hex')
       AND attestor_key_sha256 IS NOT NULL AND attestor_key_sha256 ~ '^[0-9a-f]{64}$'
       AND worker_image_sha256 IS NOT NULL AND worker_image_sha256 ~ '^[0-9a-f]{64}$'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_rag_registered_capture_retention
 ON rag_registered_source_captures(retention_until,id) WHERE cleared_at IS NULL;

CREATE OR REPLACE FUNCTION rag_registered_policy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Switching an enabled generation off is terminal; a new reviewed policy
  -- is required rather than silently reviving an old dispatch authority.
  IF TG_OP='UPDATE' AND OLD.enabled AND NOT NEW.enabled AND NEW.revoked_at IS NULL THEN
    NEW.revoked_at := clock_timestamp();
  END IF;
  IF TG_OP='DELETE' OR OLD.revoked_at IS NOT NULL OR
     (to_jsonb(NEW)-'enabled'-'revoked_at') IS DISTINCT FROM
     (to_jsonb(OLD)-'enabled'-'revoked_at') OR
     (NEW.revoked_at IS NOT NULL AND NEW.enabled) THEN
    RAISE EXCEPTION 'registered source policy immutable or revoked' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_registered_policy_guard ON rag_registered_source_policies;
CREATE TRIGGER trg_rag_registered_policy_guard BEFORE UPDATE OR DELETE ON rag_registered_source_policies
 FOR EACH ROW EXECUTE FUNCTION rag_registered_policy_guard();
CREATE OR REPLACE FUNCTION rag_registered_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR OLD.state<>'dispatched' OR
     (to_jsonb(NEW)-'state'-'response_sha256'-'response_bytes'-'error_code'-'settled_at')
       IS DISTINCT FROM
     (to_jsonb(OLD)-'state'-'response_sha256'-'response_bytes'-'error_code'-'settled_at') OR
     NEW.state NOT IN ('settled','unknown') THEN
    RAISE EXCEPTION 'registered fetch attempt immutable or terminal' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_registered_attempt_guard ON rag_registered_fetch_attempts;
CREATE TRIGGER trg_rag_registered_attempt_guard BEFORE UPDATE OR DELETE ON rag_registered_fetch_attempts
 FOR EACH ROW EXECUTE FUNCTION rag_registered_attempt_guard();
CREATE OR REPLACE FUNCTION rag_registered_capture_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE fetch_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE grant_row rag_registered_source_policies%ROWTYPE;
BEGIN
  IF TG_OP='INSERT' THEN
    SELECT * INTO fetch_row FROM rag_registered_fetch_attempts WHERE id=NEW.fetch_attempt_id;
    SELECT * INTO grant_row FROM rag_registered_source_policies
      WHERE policy_id=NEW.policy_id AND generation=NEW.generation;
    IF NEW.cleared_at IS NOT NULL OR NEW.retention_until<=clock_timestamp() OR
       fetch_row.id IS NULL OR grant_row.policy_id IS NULL OR
       fetch_row.state<>'settled' OR fetch_row.policy_id<>NEW.policy_id OR
       fetch_row.generation<>NEW.generation OR
       fetch_row.response_sha256<>NEW.fetched_sha256 OR
       fetch_row.response_bytes<>NEW.captured_bytes OR
       grant_row.enabled IS NOT TRUE OR grant_row.revoked_at IS NOT NULL OR
       grant_row.expires_at<=clock_timestamp() OR
       grant_row.license_id<>NEW.license_id OR
       NEW.retention_until>grant_row.retention_until OR
       NEW.captured_bytes>grant_row.max_captured_bytes OR
       NEW.final_url<>grant_row.canonical_url OR
       NEW.request_chain->>0<>grant_row.canonical_url OR
       encode(digest(NEW.captured_body,'sha256'),'hex')<>NEW.fetched_sha256 THEN
      RAISE EXCEPTION 'registered capture not authorized or inconsistent' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' OR OLD.cleared_at IS NOT NULL OR NEW.cleared_at IS NULL OR
     NEW.captured_body IS NOT NULL OR
     (to_jsonb(NEW)-'captured_body'-'cleared_at') IS DISTINCT FROM
     (to_jsonb(OLD)-'captured_body'-'cleared_at') THEN
    RAISE EXCEPTION 'registered capture immutable or cleared' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_registered_capture_guard ON rag_registered_source_captures;
CREATE TRIGGER trg_rag_registered_capture_guard BEFORE INSERT OR UPDATE OR DELETE ON rag_registered_source_captures
 FOR EACH ROW EXECUTE FUNCTION rag_registered_capture_guard();
