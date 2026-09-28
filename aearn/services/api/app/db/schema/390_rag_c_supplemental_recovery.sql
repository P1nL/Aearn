-- Append-only operator correction of an unused, misconfigured supplemental authority.
-- Neither the terminal original nor the old authorization is updated or deleted.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_supplemental_auth_original_pair
  ON rag_registered_supplemental_authorizations(id,prior_attempt_id);
CREATE TABLE IF NOT EXISTS rag_registered_supplemental_revocations (
  authorization_id uuid PRIMARY KEY,
  prior_attempt_id uuid NOT NULL UNIQUE,
  approval_ref text NOT NULL CHECK (char_length(approval_ref) BETWEEN 16 AND 256
    AND approval_ref ~ '^[A-Za-z0-9 ._:/+-]+$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (authorization_id,prior_attempt_id)
    REFERENCES rag_registered_supplemental_authorizations(id,prior_attempt_id) ON DELETE RESTRICT
);
ALTER TABLE rag_registered_supplemental_authorizations
  ADD COLUMN IF NOT EXISTS replaces_authorization_id uuid;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rag_registered_supplemental_authorizations'::regclass
      AND conname='fk_rag_supplemental_replacement') THEN
    ALTER TABLE rag_registered_supplemental_authorizations
      ADD CONSTRAINT fk_rag_supplemental_replacement FOREIGN KEY (replaces_authorization_id)
      REFERENCES rag_registered_supplemental_revocations(authorization_id) ON DELETE RESTRICT;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_supplemental_one_original
  ON rag_registered_supplemental_authorizations(prior_attempt_id)
  WHERE replaces_authorization_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_supplemental_one_replacement
  ON rag_registered_supplemental_authorizations(replaces_authorization_id)
  WHERE replaces_authorization_id IS NOT NULL;
-- The old unique prior key prohibited any correction. Retain the original URL
-- and same-policy/generation uniqueness on attempts, plus the new serialized
-- two-authority maximum enforced by the insertion trigger below.


CREATE OR REPLACE FUNCTION rag_registered_supplemental_recovery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE old_row rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE auth_count integer;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'supplemental authorization immutable' USING ERRCODE='23514';
  END IF;
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'supplemental correction requires read committed' USING ERRCODE='23514';
  END IF;
  -- This row is the common serialization point for issue, revoke and dispatch.
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=NEW.prior_attempt_id FOR UPDATE;
  IF prior_row.id IS NULL OR prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR
     prior_row.canonical_url_sha256<>NEW.canonical_url_sha256 OR
     NEW.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'supplemental authorization needs terminal original attempt' USING ERRCODE='23514';
  END IF;
  SELECT count(*) INTO auth_count FROM rag_registered_supplemental_authorizations
    WHERE prior_attempt_id=NEW.prior_attempt_id;
  IF auth_count=0 THEN
    IF NEW.replaces_authorization_id IS NOT NULL THEN
      RAISE EXCEPTION 'replacement has no original authorization' USING ERRCODE='23514';
    END IF;
  ELSIF auth_count=1 AND NEW.replaces_authorization_id IS NOT NULL THEN
    SELECT * INTO old_row FROM rag_registered_supplemental_authorizations
      WHERE id=NEW.replaces_authorization_id AND prior_attempt_id=NEW.prior_attempt_id FOR SHARE;
    IF old_row.id IS NULL OR old_row.replaces_authorization_id IS NOT NULL OR
       EXISTS (SELECT 1 FROM rag_registered_fetch_attempts a
         WHERE a.policy_id=NEW.policy_id AND a.generation=NEW.generation
           AND a.canonical_url_sha256=NEW.canonical_url_sha256) OR
       NOT EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations r
         WHERE r.authorization_id=old_row.id AND r.prior_attempt_id=NEW.prior_attempt_id) OR
       EXISTS (SELECT 1 FROM rag_registered_fetch_attempts a
         WHERE a.supplemental_authorization_id=old_row.id) THEN
      RAISE EXCEPTION 'supplemental replacement denied' USING ERRCODE='23514';
    END IF;
  ELSE
    RAISE EXCEPTION 'supplemental limit exceeded' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_00_rag_registered_supplemental_recovery_guard ON rag_registered_supplemental_authorizations;
CREATE TRIGGER trg_00_rag_registered_supplemental_recovery_guard
  BEFORE INSERT ON rag_registered_supplemental_authorizations
  FOR EACH ROW EXECUTE FUNCTION rag_registered_supplemental_recovery_guard();

CREATE OR REPLACE FUNCTION rag_registered_supplemental_revoke_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE auth_row rag_registered_supplemental_authorizations%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'supplemental revocation immutable' USING ERRCODE='23514';
  END IF;
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'supplemental correction requires read committed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=NEW.prior_attempt_id FOR UPDATE;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.authorization_id FOR SHARE;
  IF prior_row.id IS NULL OR prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR auth_row.id IS NULL OR
     auth_row.prior_attempt_id<>NEW.prior_attempt_id OR
     auth_row.replaces_authorization_id IS NOT NULL OR
     EXISTS (SELECT 1 FROM rag_registered_fetch_attempts a
       WHERE a.supplemental_authorization_id=NEW.authorization_id) THEN
    RAISE EXCEPTION 'supplemental revocation denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_registered_supplemental_revoke_guard ON rag_registered_supplemental_revocations;
CREATE TRIGGER trg_rag_registered_supplemental_revoke_guard
  BEFORE INSERT OR UPDATE OR DELETE ON rag_registered_supplemental_revocations
  FOR EACH ROW EXECUTE FUNCTION rag_registered_supplemental_revoke_guard();

CREATE OR REPLACE FUNCTION rag_registered_supplemental_recovery_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE auth_row rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
BEGIN
  IF NEW.supplemental_authorization_id IS NULL THEN RETURN NEW; END IF;
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'supplemental dispatch requires read committed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.supplemental_authorization_id;
  IF auth_row.id IS NULL THEN
    RAISE EXCEPTION 'supplemental dispatch denied' USING ERRCODE='23514';
  END IF;
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=auth_row.prior_attempt_id FOR UPDATE;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.supplemental_authorization_id FOR SHARE;
  IF auth_row.id IS NULL OR auth_row.expires_at<=clock_timestamp() OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations r
       WHERE r.authorization_id=auth_row.id) OR
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

DROP TRIGGER IF EXISTS trg_00_rag_registered_supplemental_recovery_dispatch_guard ON rag_registered_fetch_attempts;
CREATE TRIGGER trg_00_rag_registered_supplemental_recovery_dispatch_guard
  BEFORE INSERT ON rag_registered_fetch_attempts
  FOR EACH ROW EXECUTE FUNCTION rag_registered_supplemental_recovery_dispatch_guard();
DO $$ DECLARE old_key text; BEGIN
  SELECT c.conname INTO old_key FROM pg_constraint c
    WHERE c.conrelid='rag_registered_supplemental_authorizations'::regclass
      AND c.contype='u' AND c.conkey=ARRAY[
        (SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='prior_attempt_id')
      ]::smallint[];
  IF old_key IS NOT NULL THEN
    EXECUTE format('ALTER TABLE rag_registered_supplemental_authorizations DROP CONSTRAINT %I',old_key);
  END IF;
END $$;
