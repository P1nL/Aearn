-- Explicit final fetch credit: an independently approved quota extension, not retry recovery.
-- Bootstrap grants nothing. Historical attempts and authorizations remain immutable.
CREATE TABLE IF NOT EXISTS rag_registered_final_followup_allowances (
  id uuid PRIMARY KEY,
  original_attempt_id uuid NOT NULL UNIQUE,
  latest_attempt_id uuid NOT NULL UNIQUE,
  authorization_id uuid NOT NULL UNIQUE,
  dispatch_id uuid NOT NULL UNIQUE,
  policy_id text NOT NULL,
  generation integer NOT NULL CHECK (generation=3),
  canonical_url_sha256 text NOT NULL,
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  expires_at timestamptz NOT NULL,
  approval_ref text NOT NULL CHECK (char_length(approval_ref) BETWEEN 16 AND 256
    AND approval_ref ~ '^[A-Za-z0-9 ._:/+-]+$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(original_attempt_id,canonical_url_sha256)
    REFERENCES rag_registered_fetch_attempts(id,canonical_url_sha256) ON DELETE RESTRICT,
  FOREIGN KEY(latest_attempt_id,canonical_url_sha256)
    REFERENCES rag_registered_fetch_attempts(id,canonical_url_sha256) ON DELETE RESTRICT,
  FOREIGN KEY(policy_id,generation,canonical_url_sha256)
    REFERENCES rag_registered_source_policies(policy_id,generation,canonical_url_sha256) ON DELETE RESTRICT,
  CHECK(original_attempt_id<>latest_attempt_id AND dispatch_id<>original_attempt_id
    AND dispatch_id<>latest_attempt_id),
  UNIQUE(id,authorization_id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,original_attempt_id)
);
ALTER TABLE rag_registered_supplemental_authorizations
  ADD COLUMN IF NOT EXISTS explicit_followup_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_final_followup_one_auth
  ON rag_registered_supplemental_authorizations(explicit_followup_id)
  WHERE explicit_followup_id IS NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rag_registered_supplemental_authorizations'::regclass
    AND conname='fk_rag_final_followup_exact_auth') THEN
    ALTER TABLE rag_registered_supplemental_authorizations ADD CONSTRAINT fk_rag_final_followup_exact_auth
      FOREIGN KEY(explicit_followup_id,id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,prior_attempt_id)
      REFERENCES rag_registered_final_followup_allowances
        (id,authorization_id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,original_attempt_id)
      ON DELETE RESTRICT;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_registered_final_followup_check(
  grant_row rag_registered_final_followup_allowances
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE db_now timestamptz;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'final followup requires read committed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO policy_row FROM rag_registered_source_policies
    WHERE policy_id=grant_row.policy_id FOR SHARE;
  SELECT * INTO root_row FROM rag_budget_authority_roots
    WHERE root_id=grant_row.root_id FOR SHARE;
  SELECT * INTO original_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.original_attempt_id FOR UPDATE;
  SELECT * INTO latest_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.latest_attempt_id FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
    WHERE id=latest_row.supplemental_authorization_id FOR SHARE;
  db_now := clock_timestamp();
  IF original_row.id IS NULL OR original_row.state<>'unknown' OR
     original_row.supplemental_authorization_id IS NOT NULL OR
     latest_row.id IS NULL OR latest_row.state<>'unknown' OR latest_auth.id IS NULL OR
     latest_auth.prior_attempt_id<>original_row.id OR latest_auth.explicit_followup_id IS NOT NULL OR
     original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     -- A final credit is not permission to change the historical teaching scope.
     -- These policy fields are immutable; no extra history-policy locks are needed.
     EXISTS (SELECT 1 FROM rag_registered_source_policies history_policy
       WHERE history_policy.policy_id IN (original_row.policy_id,latest_row.policy_id)
         AND (policy_row.subject_id IS DISTINCT FROM history_policy.subject_id OR
           policy_row.subject_version IS DISTINCT FROM history_policy.subject_version OR
           policy_row.facets IS DISTINCT FROM history_policy.facets OR
           NOT (policy_row.allowed_usages @> history_policy.allowed_usages) OR
           NOT (policy_row.allowed_usages <@ history_policy.allowed_usages) OR
           policy_row.max_captured_bytes>history_policy.max_captured_bytes)) OR
     grant_row.original_attempt_id=grant_row.latest_attempt_id OR grant_row.generation<>3 OR
     grant_row.policy_id IN (original_row.policy_id,latest_row.policy_id) OR
     grant_row.root_id IN (original_row.root_id,latest_row.root_id) OR
     (SELECT count(*) FROM rag_registered_fetch_attempts
       WHERE canonical_url_sha256=grant_row.canonical_url_sha256)<>2 OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations WHERE authorization_id=latest_auth.id) OR
     policy_row.policy_id IS NULL OR policy_row.generation<>grant_row.generation OR
     policy_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR policy_row.root_id<>grant_row.root_id OR
     NOT policy_row.enabled OR policy_row.revoked_at IS NOT NULL OR
     root_row.root_id IS NULL OR NOT root_row.enabled OR root_row.policy_id<>grant_row.policy_id OR
     root_row.policy_generation<>grant_row.generation OR root_row.period_start>db_now OR
     grant_row.expires_at<=db_now OR grant_row.expires_at>policy_row.expires_at OR
     grant_row.expires_at>policy_row.retention_until OR grant_row.expires_at>root_row.delegation_expires_at OR
     grant_row.expires_at>root_row.period_end OR
     EXISTS (SELECT 1 FROM rag_registered_fetch_attempts WHERE id=grant_row.dispatch_id OR
       (policy_id=grant_row.policy_id AND generation=grant_row.generation
         AND canonical_url_sha256=grant_row.canonical_url_sha256)) THEN
    RAISE EXCEPTION 'final followup history or target denied' USING ERRCODE='23514';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_registered_final_followup_allowance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'final followup allowance immutable' USING ERRCODE='23514';
  END IF;
  PERFORM rag_registered_final_followup_check(NEW);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_final_followup_allowance_guard ON rag_registered_final_followup_allowances;
CREATE TRIGGER trg_rag_final_followup_allowance_guard BEFORE INSERT OR UPDATE OR DELETE
  ON rag_registered_final_followup_allowances FOR EACH ROW
  EXECUTE FUNCTION rag_registered_final_followup_allowance_guard();

CREATE OR REPLACE FUNCTION rag_registered_final_followup_auth_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE grant_row rag_registered_final_followup_allowances%ROWTYPE;
BEGIN
  IF NEW.explicit_followup_id IS NULL THEN
    IF NEW.replaces_authorization_id IS NOT NULL AND EXISTS (
      SELECT 1 FROM rag_registered_supplemental_authorizations
      WHERE id=NEW.replaces_authorization_id AND explicit_followup_id IS NOT NULL) THEN
      RAISE EXCEPTION 'final followup cannot be replaced' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO grant_row FROM rag_registered_final_followup_allowances WHERE id=NEW.explicit_followup_id;
  IF grant_row.id IS NULL OR NEW.replaces_authorization_id IS NOT NULL OR
     ROW(NEW.id,NEW.dispatch_id,NEW.policy_id,NEW.generation,NEW.canonical_url_sha256,
         NEW.root_id,NEW.request_hash,NEW.prior_attempt_id,NEW.expires_at,NEW.approval_ref)
       IS DISTINCT FROM
     ROW(grant_row.authorization_id,grant_row.dispatch_id,grant_row.policy_id,grant_row.generation,
         grant_row.canonical_url_sha256,grant_row.root_id,grant_row.request_hash,
         grant_row.original_attempt_id,grant_row.expires_at,grant_row.approval_ref) THEN
    RAISE EXCEPTION 'final followup exact authorization denied' USING ERRCODE='23514';
  END IF;
  PERFORM rag_registered_final_followup_check(grant_row);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_000_rag_final_followup_auth_guard ON rag_registered_supplemental_authorizations;
CREATE TRIGGER trg_000_rag_final_followup_auth_guard BEFORE INSERT ON rag_registered_supplemental_authorizations
  FOR EACH ROW EXECUTE FUNCTION rag_registered_final_followup_auth_guard();

CREATE OR REPLACE FUNCTION rag_registered_final_followup_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE auth_row rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE grant_row rag_registered_final_followup_allowances%ROWTYPE;
BEGIN
  IF NEW.supplemental_authorization_id IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations WHERE id=NEW.supplemental_authorization_id;
  IF auth_row.explicit_followup_id IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO grant_row FROM rag_registered_final_followup_allowances WHERE id=auth_row.explicit_followup_id;
  IF grant_row.id IS NULL OR NEW.state<>'dispatched' OR
     ROW(NEW.id,NEW.policy_id,NEW.generation,NEW.canonical_url_sha256,NEW.root_id,NEW.request_hash)
     IS DISTINCT FROM ROW(grant_row.dispatch_id,grant_row.policy_id,grant_row.generation,
       grant_row.canonical_url_sha256,grant_row.root_id,grant_row.request_hash) THEN
    RAISE EXCEPTION 'final followup dispatch denied' USING ERRCODE='23514';
  END IF;
  PERFORM rag_registered_final_followup_check(grant_row);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_000_rag_final_followup_dispatch_guard ON rag_registered_fetch_attempts;
CREATE TRIGGER trg_000_rag_final_followup_dispatch_guard BEFORE INSERT ON rag_registered_fetch_attempts
  FOR EACH ROW EXECUTE FUNCTION rag_registered_final_followup_dispatch_guard();

CREATE OR REPLACE FUNCTION rag_registered_final_followup_revoke_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.authorization_id AND explicit_followup_id IS NOT NULL) THEN
    RAISE EXCEPTION 'final followup cannot be revoked or corrected' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_000_rag_final_followup_revoke_guard ON rag_registered_supplemental_revocations;
CREATE TRIGGER trg_000_rag_final_followup_revoke_guard BEFORE INSERT ON rag_registered_supplemental_revocations
  FOR EACH ROW EXECUTE FUNCTION rag_registered_final_followup_revoke_guard();

-- Extend only issuance: independent 400 triggers remain authoritative. Replaying
-- 390 overwrites this function and rejects final issuance until 400 is reapplied.
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
  IF NEW.explicit_followup_id IS NOT NULL THEN RETURN NEW; END IF;
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
-- Preserve the original index name so 390 CREATE IF NOT EXISTS never broadens it.
-- The independent 400 guard is already installed before changing this predicate.
DROP INDEX IF EXISTS uq_rag_supplemental_one_original;
CREATE UNIQUE INDEX uq_rag_supplemental_one_original
  ON rag_registered_supplemental_authorizations(prior_attempt_id)
  WHERE replaces_authorization_id IS NULL AND explicit_followup_id IS NULL;
