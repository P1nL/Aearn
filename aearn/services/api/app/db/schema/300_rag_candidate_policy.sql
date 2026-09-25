-- Operator-owned B2 permissions. Bootstrap never seeds or enables a policy.
CREATE TABLE IF NOT EXISTS rag_candidate_access_policies (
  policy_id text PRIMARY KEY CHECK (policy_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  current_generation integer NOT NULL DEFAULT 1 CHECK (current_generation >= 1),
  enabled boolean NOT NULL DEFAULT false,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (revoked_at IS NULL OR NOT enabled)
);
CREATE TABLE IF NOT EXISTS rag_candidate_access_rules (
  policy_id text NOT NULL REFERENCES rag_candidate_access_policies(policy_id) ON DELETE RESTRICT,
  generation integer NOT NULL CHECK (generation >= 1),
  host text NOT NULL CHECK (host ~ '^[a-z0-9-]+(\.[a-z0-9-]+)+$' AND char_length(host) <= 253),
  path_prefix text NOT NULL CHECK (
    path_prefix ~ '^/[A-Za-z0-9._~/-]*$'
    AND path_prefix !~ '(^|/)\.\.?(/|$)'
    AND path_prefix !~ '//'
    AND (path_prefix = '/' OR right(path_prefix, 1) <> '/')
  ),
  probe_allowed boolean NOT NULL DEFAULT false,
  store_allowed boolean NOT NULL DEFAULT false,
  allowed_capture text NOT NULL DEFAULT 'none' CHECK (allowed_capture IN ('none','prefix','full')),
  max_captured_bytes integer NOT NULL DEFAULT 0 CHECK (max_captured_bytes BETWEEN 0 AND 10000000),
  license_id text CHECK (license_id ~ '^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$'),
  valid_until timestamptz NOT NULL,
  retention_until timestamptz NOT NULL,
  revoked_at timestamptz,
  PRIMARY KEY(policy_id,generation,host,path_prefix),
  CHECK (NOT store_allowed OR (probe_allowed AND license_id IS NOT NULL)),
  CHECK (store_allowed OR (allowed_capture='none' AND max_captured_bytes=0 AND license_id IS NULL)),
  CHECK ((allowed_capture='none' AND max_captured_bytes=0)
      OR (allowed_capture<>'none' AND max_captured_bytes>0)),
  CHECK (retention_until <= valid_until)
);
CREATE INDEX IF NOT EXISTS idx_rag_candidate_access_rules_host
  ON rag_candidate_access_rules(policy_id,generation,host);

-- A revoked generation/rule cannot be revived. Existing permissions cannot be
-- widened in place; operators provision a new generation and recheck all jobs.
CREATE OR REPLACE FUNCTION rag_candidate_policy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.revoked_at IS NOT NULL OR NEW.current_generation < OLD.current_generation
     OR (OLD.enabled AND NEW.current_generation=OLD.current_generation
         AND NEW.expires_at > OLD.expires_at) THEN
    RAISE EXCEPTION 'policy revoked or widened' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_candidate_policy_guard ON rag_candidate_access_policies;
CREATE TRIGGER trg_rag_candidate_policy_guard BEFORE UPDATE ON rag_candidate_access_policies
  FOR EACH ROW EXECUTE FUNCTION rag_candidate_policy_guard();
CREATE OR REPLACE FUNCTION rag_candidate_rule_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' AND (OLD.revoked_at IS NOT NULL OR
      (to_jsonb(NEW)-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'revoked_at') OR
      NEW.revoked_at IS NULL) THEN
    RAISE EXCEPTION 'rule immutable or revoked' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_candidate_rule_guard ON rag_candidate_access_rules;
CREATE TRIGGER trg_rag_candidate_rule_guard BEFORE UPDATE ON rag_candidate_access_rules
  FOR EACH ROW EXECUTE FUNCTION rag_candidate_rule_guard();
