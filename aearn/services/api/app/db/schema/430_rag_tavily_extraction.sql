-- Provider-native Tavily extraction attempts for exact registered sources.
-- This is not origin TLS/redirect attestation and creates no corpus authority.
CREATE TABLE IF NOT EXISTS rag_provider_extraction_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL DEFAULT 'tavily' CHECK (provider='tavily'),
  policy_id text NOT NULL,
  generation integer NOT NULL CHECK (generation>=1),
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  operation_key text NOT NULL UNIQUE CHECK (operation_key ~ '^[a-zA-Z0-9._:-]{8,160}$'),
  requested_url text NOT NULL CHECK (char_length(requested_url) BETWEEN 9 AND 2048
    AND requested_url ~ '^https://' AND requested_url !~ '[@#]' AND position(chr(92) in requested_url)=0),
  request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  content_format text NOT NULL CHECK (content_format IN ('markdown','text')),
  extract_depth text NOT NULL CHECK (extract_depth IN ('advanced','basic')),
  state text NOT NULL DEFAULT 'dispatched'
    CHECK (state IN ('dispatched','settled','failed','unknown')),
  provider_request_id text CHECK (provider_request_id ~ '^[A-Za-z0-9_-]{8,128}$'),
  response_sha256 text CHECK (response_sha256 ~ '^[0-9a-f]{64}$'),
  content_sha256 text CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  content_bytes integer CHECK (content_bytes BETWEEN 1 AND 8388608),
  usage_credits numeric CHECK (usage_credits>=0),
  dispatched_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  received_at timestamptz,
  safe_error text CHECK (safe_error ~ '^[a-z][a-z0-9_]{2,79}$'),
  FOREIGN KEY(policy_id,generation)
    REFERENCES rag_registered_source_policies(policy_id,generation) ON DELETE RESTRICT,
  UNIQUE(id,policy_id,generation),
  CHECK (
    (state='dispatched' AND provider_request_id IS NULL AND response_sha256 IS NULL
      AND content_sha256 IS NULL AND content_bytes IS NULL AND usage_credits IS NULL
      AND received_at IS NULL AND safe_error IS NULL)
    OR
    (state='settled' AND provider_request_id IS NOT NULL AND response_sha256 IS NOT NULL
      AND content_sha256 IS NOT NULL AND content_bytes IS NOT NULL
      AND received_at IS NOT NULL AND received_at>=dispatched_at AND safe_error IS NULL)
    OR
    (state IN ('failed','unknown') AND provider_request_id IS NULL
      AND response_sha256 IS NULL AND content_sha256 IS NULL AND content_bytes IS NULL
      AND usage_credits IS NULL AND received_at IS NOT NULL AND safe_error IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_rag_provider_extraction_scope
  ON rag_provider_extraction_attempts(policy_id,generation,root_id,dispatched_at);

ALTER TABLE rag_registered_source_captures
  ALTER COLUMN fetch_attempt_id DROP NOT NULL;
ALTER TABLE rag_registered_source_captures
  ADD COLUMN IF NOT EXISTS provider_attempt_id uuid;
ALTER TABLE rag_registered_source_captures
  DROP CONSTRAINT IF EXISTS rag_registered_source_captures_evidence_level_check;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid='rag_registered_source_captures'::regclass
        AND conname='fk_rag_registered_capture_provider_attempt') THEN
    ALTER TABLE rag_registered_source_captures
      ADD CONSTRAINT fk_rag_registered_capture_provider_attempt
      FOREIGN KEY(provider_attempt_id,policy_id,generation)
      REFERENCES rag_provider_extraction_attempts(id,policy_id,generation) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid='rag_registered_source_captures'::regclass
        AND conname='uq_rag_registered_capture_provider_attempt') THEN
    ALTER TABLE rag_registered_source_captures
      ADD CONSTRAINT uq_rag_registered_capture_provider_attempt UNIQUE(provider_attempt_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid='rag_registered_source_captures'::regclass
        AND conname='chk_rag_registered_capture_attempt_xor') THEN
    ALTER TABLE rag_registered_source_captures
      ADD CONSTRAINT chk_rag_registered_capture_attempt_xor
      CHECK ((fetch_attempt_id IS NULL) <> (provider_attempt_id IS NULL));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid='rag_registered_source_captures'::regclass
        AND conname='chk_rag_registered_capture_evidence_level_v2') THEN
    ALTER TABLE rag_registered_source_captures
      ADD CONSTRAINT chk_rag_registered_capture_evidence_level_v2
      CHECK ((fetch_attempt_id IS NOT NULL AND evidence_level='live_egress_attested')
        OR (provider_attempt_id IS NOT NULL AND evidence_level='provider_extracted'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid='rag_registered_source_captures'::regclass
        AND conname='chk_rag_registered_provider_capture_shape') THEN
    ALTER TABLE rag_registered_source_captures
      ADD CONSTRAINT chk_rag_registered_provider_capture_shape CHECK (
        provider_attempt_id IS NULL OR (
          content_type IN ('text/markdown','text/plain')
          AND transport_proof IS NULL AND transport_proof_sha256 IS NULL
          AND attestor_key_sha256 IS NULL AND worker_image_sha256 IS NULL));
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_provider_extraction_attempt_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE used_units integer;
DECLARE db_now timestamptz;
BEGIN
  IF TG_OP='INSERT' THEN
    db_now := clock_timestamp();
    SELECT * INTO policy_row FROM rag_registered_source_policies
      WHERE policy_id=NEW.policy_id AND generation=NEW.generation FOR SHARE;
    SELECT * INTO root_row FROM rag_budget_authority_roots
      WHERE root_id=NEW.root_id FOR UPDATE;
    SELECT count(*) INTO used_units FROM rag_provider_extraction_attempts
      WHERE root_id=NEW.root_id;
    IF policy_row.policy_id IS NULL OR root_row.root_id IS NULL
       OR policy_row.enabled IS NOT TRUE OR policy_row.revoked_at IS NOT NULL
       OR policy_row.expires_at<=db_now OR policy_row.retention_until<=db_now
       OR policy_row.root_id<>NEW.root_id OR policy_row.canonical_url<>NEW.requested_url
       OR root_row.enabled IS NOT TRUE OR root_row.delegation_expires_at<=db_now
       OR NOT (root_row.period_start<=db_now AND db_now<root_row.period_end)
       OR root_row.policy_id<>NEW.policy_id OR root_row.policy_generation<>NEW.generation
       OR used_units>=root_row.cap_units THEN
      RAISE EXCEPTION 'provider extraction dispatch not authorized' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' OR OLD.state<>'dispatched'
     OR NEW.state NOT IN ('settled','failed','unknown')
     OR (to_jsonb(NEW)-'state'-'provider_request_id'-'response_sha256'-'content_sha256'
         -'content_bytes'-'usage_credits'-'received_at'-'safe_error') IS DISTINCT FROM
        (to_jsonb(OLD)-'state'-'provider_request_id'-'response_sha256'-'content_sha256'
         -'content_bytes'-'usage_credits'-'received_at'-'safe_error') THEN
    RAISE EXCEPTION 'provider extraction attempt immutable or terminal' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_provider_extraction_attempt_guard
  ON rag_provider_extraction_attempts;
CREATE TRIGGER trg_rag_provider_extraction_attempt_guard
  BEFORE INSERT OR UPDATE OR DELETE ON rag_provider_extraction_attempts
  FOR EACH ROW EXECUTE FUNCTION rag_provider_extraction_attempt_guard();

CREATE OR REPLACE FUNCTION rag_registered_capture_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE fetch_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE provider_row rag_provider_extraction_attempts%ROWTYPE;
DECLARE grant_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
BEGIN
  IF TG_OP='INSERT' THEN
    SELECT * INTO grant_row FROM rag_registered_source_policies
      WHERE policy_id=NEW.policy_id AND generation=NEW.generation;
    IF NEW.provider_attempt_id IS NULL THEN
      SELECT * INTO fetch_row FROM rag_registered_fetch_attempts WHERE id=NEW.fetch_attempt_id;
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
    SELECT * INTO provider_row FROM rag_provider_extraction_attempts
      WHERE id=NEW.provider_attempt_id;
    SELECT * INTO root_row FROM rag_budget_authority_roots
      WHERE root_id=grant_row.root_id;
    IF NEW.cleared_at IS NOT NULL OR NEW.retention_until<=clock_timestamp()
       OR provider_row.id IS NULL OR grant_row.policy_id IS NULL OR root_row.root_id IS NULL
       OR provider_row.state<>'settled' OR provider_row.provider_request_id IS NULL
       OR provider_row.policy_id<>NEW.policy_id OR provider_row.generation<>NEW.generation
       OR provider_row.root_id<>grant_row.root_id
       OR provider_row.requested_url<>grant_row.canonical_url
       OR provider_row.content_sha256<>NEW.fetched_sha256
       OR provider_row.content_bytes<>NEW.captured_bytes
       OR provider_row.content_format<>(CASE WHEN NEW.content_type='text/markdown' THEN 'markdown' ELSE 'text' END)
       OR grant_row.enabled IS NOT TRUE OR grant_row.revoked_at IS NOT NULL
       OR grant_row.expires_at<=clock_timestamp() OR grant_row.retention_until<=clock_timestamp()
       OR grant_row.license_id<>NEW.license_id OR NEW.retention_until>grant_row.retention_until
       OR NEW.captured_bytes>grant_row.max_captured_bytes
       OR NEW.final_url<>grant_row.canonical_url OR NEW.request_chain->>0<>grant_row.canonical_url
       OR root_row.enabled IS NOT TRUE OR root_row.delegation_expires_at<=clock_timestamp()
       OR NOT (root_row.period_start<=clock_timestamp() AND clock_timestamp()<root_row.period_end)
       OR root_row.policy_id<>NEW.policy_id OR root_row.policy_generation<>NEW.generation
       OR NEW.evidence_level<>'provider_extracted'
       OR NEW.transport_proof IS NOT NULL OR NEW.transport_proof_sha256 IS NOT NULL
       OR NEW.attestor_key_sha256 IS NOT NULL OR NEW.worker_image_sha256 IS NOT NULL
       OR encode(digest(NEW.captured_body,'sha256'),'hex')<>NEW.fetched_sha256 THEN
      RAISE EXCEPTION 'registered provider capture not authorized or inconsistent' USING ERRCODE='23514';
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
