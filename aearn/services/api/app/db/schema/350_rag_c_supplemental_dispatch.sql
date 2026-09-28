-- Operator-provisioned one-more-dispatch exception for an exact URL already spent.
-- This does not revive or mutate the original unknown/settled attempt. No row is
-- inserted by bootstrap: possession of a DB writer alone is not a network grant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_registered_attempt_id_url
  ON rag_registered_fetch_attempts(id, canonical_url_sha256);
CREATE TABLE IF NOT EXISTS rag_registered_supplemental_authorizations (
  id uuid PRIMARY KEY,
  dispatch_id uuid NOT NULL UNIQUE,
  policy_id text NOT NULL,
  generation integer NOT NULL,
  canonical_url_sha256 text NOT NULL,
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  prior_attempt_id uuid NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  approval_ref text NOT NULL CHECK (char_length(approval_ref) BETWEEN 16 AND 256
    AND approval_ref ~ '^[A-Za-z0-9 ._:/+-]+$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(policy_id, generation, canonical_url_sha256)
    REFERENCES rag_registered_source_policies(policy_id,generation,canonical_url_sha256) ON DELETE RESTRICT,
  FOREIGN KEY(prior_attempt_id, canonical_url_sha256)
    REFERENCES rag_registered_fetch_attempts(id,canonical_url_sha256) ON DELETE RESTRICT,
  UNIQUE(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash)
);
CREATE OR REPLACE FUNCTION rag_registered_supplemental_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'supplemental authorization immutable' USING ERRCODE='23514';
  END IF;
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=NEW.prior_attempt_id FOR SHARE;
  IF prior_row.id IS NULL OR prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR
     prior_row.canonical_url_sha256<>NEW.canonical_url_sha256 OR
     NEW.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'supplemental authorization needs terminal original attempt' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
-- The 320 fragment is intentionally retained unchanged for old bootstraps.
-- It will see this column and the partial index on all future full bootstraps.
ALTER TABLE rag_registered_fetch_attempts
  ADD COLUMN IF NOT EXISTS supplemental_authorization_id uuid;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rag_registered_fetch_attempts'::regclass
      AND conname='uq_rag_registered_attempt_supplemental') THEN
    ALTER TABLE rag_registered_fetch_attempts ADD CONSTRAINT uq_rag_registered_attempt_supplemental
      UNIQUE(supplemental_authorization_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rag_registered_fetch_attempts'::regclass
      AND conname='fk_rag_registered_attempt_supplemental') THEN
    ALTER TABLE rag_registered_fetch_attempts ADD CONSTRAINT fk_rag_registered_attempt_supplemental
      FOREIGN KEY(supplemental_authorization_id,id,policy_id,generation,canonical_url_sha256,root_id,request_hash)
      REFERENCES rag_registered_supplemental_authorizations
        (id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash)
      ON DELETE RESTRICT;
  END IF;
END $$;
DROP TRIGGER IF EXISTS trg_rag_registered_supplemental_guard ON rag_registered_supplemental_authorizations;
CREATE TRIGGER trg_rag_registered_supplemental_guard
  BEFORE INSERT OR UPDATE OR DELETE ON rag_registered_supplemental_authorizations
  FOR EACH ROW EXECUTE FUNCTION rag_registered_supplemental_guard();
CREATE OR REPLACE FUNCTION rag_registered_supplemental_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE auth_row rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
BEGIN
  IF NEW.supplemental_authorization_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.supplemental_authorization_id FOR SHARE;
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=auth_row.prior_attempt_id FOR SHARE;
  IF auth_row.id IS NULL OR auth_row.expires_at<=clock_timestamp() OR
     NEW.id<>auth_row.dispatch_id OR NEW.policy_id<>auth_row.policy_id OR
     NEW.generation<>auth_row.generation OR NEW.canonical_url_sha256<>auth_row.canonical_url_sha256 OR
     NEW.root_id<>auth_row.root_id OR NEW.request_hash<>auth_row.request_hash OR
     NEW.state<>'dispatched' OR prior_row.id IS NULL OR
     prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR
     prior_row.canonical_url_sha256<>NEW.canonical_url_sha256 THEN
    RAISE EXCEPTION 'supplemental dispatch denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_registered_supplemental_dispatch_guard ON rag_registered_fetch_attempts;
CREATE TRIGGER trg_rag_registered_supplemental_dispatch_guard BEFORE INSERT ON rag_registered_fetch_attempts
  FOR EACH ROW EXECUTE FUNCTION rag_registered_supplemental_dispatch_guard();
-- 320's old named global index would block the explicit exception. Retain its
-- name with a partial predicate so 320 CREATE IF NOT EXISTS is a no-op on replay.
DROP INDEX IF EXISTS uq_rag_registered_one_attempt_per_url;
CREATE UNIQUE INDEX uq_rag_registered_one_attempt_per_url
  ON rag_registered_fetch_attempts(canonical_url_sha256)
  WHERE supplemental_authorization_id IS NULL;
