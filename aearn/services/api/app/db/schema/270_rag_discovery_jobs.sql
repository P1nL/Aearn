-- B1 shared discovery accounting; no candidate is an admitted corpus document.
-- No source of spend authority is seeded by bootstrap. An approved server operator
-- must provision a disabled root, review cost/policy, then explicitly enable it.
CREATE TABLE IF NOT EXISTS rag_budget_authority_roots (
  root_id text PRIMARY KEY CHECK (root_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  delegation_id text NOT NULL CHECK (delegation_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  delegation_generation integer NOT NULL CHECK (delegation_generation >= 1),
  delegation_expires_at timestamptz NOT NULL,
  policy_id text NOT NULL CHECK (policy_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  policy_generation integer NOT NULL CHECK (policy_generation >= 1),
  period_key text NOT NULL CHECK (period_key ~ '^[a-zA-Z0-9._:-]{1,79}$'),
  period_start timestamptz NOT NULL,
  period_end timestamptz NOT NULL,
  cap_units integer NOT NULL CHECK (cap_units BETWEEN 1 AND 1000000),
  enabled boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (period_start < period_end AND delegation_expires_at > period_start)
);
CREATE TABLE IF NOT EXISTS rag_budget_periods (
  root_id text NOT NULL CHECK (root_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  period_key text NOT NULL CHECK (period_key ~ '^[a-zA-Z0-9._:-]{1,79}$'),
  cap_units integer NOT NULL CHECK (cap_units BETWEEN 1 AND 1000000),
  period_end timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (root_id, period_key)
);
CREATE TABLE IF NOT EXISTS rag_discovery_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operation_key text NOT NULL UNIQUE CHECK (operation_key ~ '^[a-zA-Z0-9._:-]{8,160}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  query_hash text NOT NULL CHECK (query_hash ~ '^[0-9a-f]{64}$'),
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  purpose text NOT NULL CHECK (purpose IN ('main_teaching','supplementary_explanation','assessment_evidence')),
  policy_id text NOT NULL,
  policy_generation integer NOT NULL CHECK (policy_generation >= 1),
  root_id text NOT NULL,
  delegation_id text NOT NULL,
  delegation_generation integer NOT NULL CHECK (delegation_generation >= 1),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','leased','completed','failed')),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, demand_hash, subject_id, subject_version),
  CHECK ((state = 'leased') = (lease_owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)),
  CHECK (state <> 'leased' OR lease_generation > 0),
  CHECK ((state IN ('completed','failed')) = (terminal_at IS NOT NULL)),
  CHECK (lease_owner_id IS NULL OR lease_owner_id ~ '^[a-zA-Z0-9._:-]{3,120}$')
);
CREATE INDEX IF NOT EXISTS idx_rag_discovery_jobs_claim ON rag_discovery_jobs(created_at,id)
  WHERE state IN ('pending','leased');
CREATE TABLE IF NOT EXISTS rag_discovery_job_refs (
  job_id uuid NOT NULL REFERENCES rag_discovery_jobs(id) ON DELETE RESTRICT,
  actor_id text NOT NULL CHECK (actor_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(job_id,actor_id,demand_hash)
);
CREATE INDEX IF NOT EXISTS idx_rag_discovery_job_refs_actor ON rag_discovery_job_refs(actor_id);
CREATE TABLE IF NOT EXISTS rag_budget_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id text NOT NULL,
  period_key text NOT NULL,
  operation_key text NOT NULL CHECK (operation_key ~ '^[a-zA-Z0-9._:-]{8,160}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  job_id uuid NOT NULL REFERENCES rag_discovery_jobs(id) ON DELETE RESTRICT,
  reserved_units integer NOT NULL CHECK (reserved_units BETWEEN 1 AND 1000000),
  state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','attempted','unknown','settled')),
  settled_units integer CHECK (settled_units BETWEEN 0 AND 1000000),
  settlement_receipt_hash text CHECK (settlement_receipt_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(root_id,period_key,operation_key),
  UNIQUE(id,job_id),
  FOREIGN KEY(root_id,period_key) REFERENCES rag_budget_periods(root_id,period_key) ON DELETE RESTRICT,
  CHECK ((state = 'settled') = (settled_units IS NOT NULL AND settlement_receipt_hash IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS rag_budget_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reservation_id uuid NOT NULL UNIQUE,
  job_id uuid NOT NULL,
  attempt_key text NOT NULL UNIQUE CHECK (attempt_key ~ '^[a-zA-Z0-9._:-]{8,160}$'),
  state text NOT NULL DEFAULT 'started' CHECK (state IN ('started','dispatched','unknown','settled')),
  dispatch_owner_id text CHECK (dispatch_owner_id ~ '^[a-zA-Z0-9._:-]{3,120}$'),
  dispatch_generation integer CHECK (dispatch_generation >= 1),
  dispatched_at timestamptz,
  error_code text CHECK (error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,job_id),
  CHECK ((state IN ('started','unknown') AND dispatch_owner_id IS NULL
          AND dispatch_generation IS NULL AND dispatched_at IS NULL)
     OR (state IN ('dispatched','unknown','settled') AND dispatch_owner_id IS NOT NULL
          AND dispatch_generation IS NOT NULL AND dispatched_at IS NOT NULL)),
  FOREIGN KEY(reservation_id,job_id) REFERENCES rag_budget_reservations(id,job_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS rag_discovery_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES rag_discovery_jobs(id) ON DELETE RESTRICT,
  attempt_id uuid NOT NULL UNIQUE,
  receipt_handle text NOT NULL UNIQUE CHECK (receipt_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  result_code text NOT NULL CHECK (result_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  response_hash text NOT NULL CHECK (response_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,job_id),
  FOREIGN KEY(attempt_id,job_id) REFERENCES rag_budget_attempts(id,job_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS rag_discovery_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES rag_discovery_jobs(id) ON DELETE RESTRICT,
  discovery_receipt_id uuid NOT NULL,
  canonical_url text NOT NULL CHECK (char_length(canonical_url) BETWEEN 9 AND 2048
    AND canonical_url ~ '^https://[a-z0-9.-]+(/.*)?$'
    AND position('?' in canonical_url)=0 AND position('#' in canonical_url)=0
    AND position('@' in canonical_url)=0 AND position(chr(92) in canonical_url)=0),
  canonical_url_hash text NOT NULL CHECK (canonical_url_hash ~ '^[0-9a-f]{64}$'),
  kind text NOT NULL CHECK (kind IN ('landing','document','repo_page','repo_file')),
  demand_hash text NOT NULL,
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  repo_commit text CHECK (repo_commit ~ '^[0-9a-f]{40}$'),
  repo_path text CHECK (char_length(repo_path) BETWEEN 1 AND 400),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,canonical_url_hash),
  UNIQUE(id,job_id),
  FOREIGN KEY(discovery_receipt_id,job_id) REFERENCES rag_discovery_receipts(id,job_id) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,demand_hash,subject_id,subject_version)
    REFERENCES rag_discovery_jobs(id,demand_hash,subject_id,subject_version) ON DELETE RESTRICT,
  CHECK ((kind = 'repo_file') = (repo_commit IS NOT NULL AND repo_path IS NOT NULL))
);



-- Accounting identities are immutable even if a future caller bypasses the repository.
CREATE OR REPLACE FUNCTION rag_budget_reservation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'reservation deletion denied' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-'state'-'settled_units'-'settlement_receipt_hash'-'updated_at')
      IS DISTINCT FROM (to_jsonb(OLD)-'state'-'settled_units'-'settlement_receipt_hash'-'updated_at')
     OR OLD.state='settled'
     OR NOT ((OLD.state='reserved' AND NEW.state='attempted')
          OR (OLD.state='attempted' AND NEW.state IN ('unknown','settled'))
          OR (OLD.state='unknown' AND NEW.state IN ('unknown','settled'))) THEN
    RAISE EXCEPTION 'reservation transition denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_budget_reservation_guard ON rag_budget_reservations;
CREATE TRIGGER trg_rag_budget_reservation_guard BEFORE UPDATE OR DELETE ON rag_budget_reservations
  FOR EACH ROW EXECUTE FUNCTION rag_budget_reservation_guard();

CREATE OR REPLACE FUNCTION rag_budget_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'attempt deletion denied' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-'state'-'error_code'-'updated_at'-'dispatch_owner_id'-'dispatch_generation'-'dispatched_at')
      IS DISTINCT FROM (to_jsonb(OLD)-'state'-'error_code'-'updated_at'-'dispatch_owner_id'-'dispatch_generation'-'dispatched_at')
     OR OLD.state='settled'
     OR (OLD.state<>'started' AND (NEW.dispatch_owner_id,NEW.dispatch_generation,NEW.dispatched_at)
         IS DISTINCT FROM (OLD.dispatch_owner_id,OLD.dispatch_generation,OLD.dispatched_at))
     OR NOT ((OLD.state='started' AND NEW.state IN ('dispatched','unknown'))
          OR (OLD.state='dispatched' AND NEW.state IN ('unknown','settled'))
          OR (OLD.state='unknown' AND NEW.state IN ('unknown','settled'))) THEN
    RAISE EXCEPTION 'attempt transition denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_budget_attempt_guard ON rag_budget_attempts;
CREATE TRIGGER trg_rag_budget_attempt_guard BEFORE UPDATE OR DELETE ON rag_budget_attempts
  FOR EACH ROW EXECUTE FUNCTION rag_budget_attempt_guard();

CREATE OR REPLACE FUNCTION rag_discovery_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'discovery fact immutable' USING ERRCODE='23514';
END $$;
DROP TRIGGER IF EXISTS trg_rag_discovery_receipt_immutable ON rag_discovery_receipts;
CREATE TRIGGER trg_rag_discovery_receipt_immutable BEFORE UPDATE OR DELETE ON rag_discovery_receipts
  FOR EACH ROW EXECUTE FUNCTION rag_discovery_immutable_guard();
DROP TRIGGER IF EXISTS trg_rag_discovery_candidate_immutable ON rag_discovery_candidates;
CREATE TRIGGER trg_rag_discovery_candidate_immutable BEFORE UPDATE OR DELETE ON rag_discovery_candidates
  FOR EACH ROW EXECUTE FUNCTION rag_discovery_immutable_guard();
DROP TRIGGER IF EXISTS trg_rag_budget_period_immutable ON rag_budget_periods;
CREATE TRIGGER trg_rag_budget_period_immutable BEFORE UPDATE OR DELETE ON rag_budget_periods
  FOR EACH ROW EXECUTE FUNCTION rag_discovery_immutable_guard();

CREATE OR REPLACE FUNCTION rag_discovery_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'job deletion denied' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-'state'-'lease_owner_id'-'lease_generation'-'lease_expires_at'-'terminal_at'-'updated_at')
      IS DISTINCT FROM (to_jsonb(OLD)-'state'-'lease_owner_id'-'lease_generation'-'lease_expires_at'-'terminal_at'-'updated_at')
     OR NOT ((OLD.state IN ('pending','leased') AND NEW.state='leased'
              AND NEW.lease_generation=OLD.lease_generation+1)
          OR (OLD.state='leased' AND NEW.state IN ('completed','failed')
              AND NEW.lease_generation=OLD.lease_generation)) THEN
    RAISE EXCEPTION 'job transition denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_discovery_job_guard ON rag_discovery_jobs;
CREATE TRIGGER trg_rag_discovery_job_guard BEFORE UPDATE OR DELETE ON rag_discovery_jobs
  FOR EACH ROW EXECUTE FUNCTION rag_discovery_job_guard();
