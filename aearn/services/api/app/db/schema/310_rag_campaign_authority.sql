-- Operator-provisioned service principals. Bootstrap creates structure only:
-- no principal, campaign, permission, period or cost authority is seeded.
CREATE TABLE IF NOT EXISTS rag_campaign_principals (
  actor_id text PRIMARY KEY CHECK (actor_id ~ '^service\.[a-z][a-z0-9._:-]{2,151}$'),
  operator_id text NOT NULL CHECK (operator_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  enabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rag_campaign_definitions (
  campaign_id text PRIMARY KEY CHECK (campaign_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  actor_id text NOT NULL REFERENCES rag_campaign_principals(actor_id) ON DELETE RESTRICT,
  revision integer NOT NULL CHECK (revision BETWEEN 1 AND 1000000),
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  facets text[] NOT NULL CHECK (cardinality(facets) BETWEEN 1 AND 24),
  purpose text NOT NULL CHECK (purpose IN ('main_teaching','supplementary_explanation','assessment_evidence')),
  reading_level text NOT NULL CHECK (reading_level IN ('beginner','intermediate','advanced')),
  language text NOT NULL CHECK (language IN ('zh','en')),
  demand_hash text NOT NULL UNIQUE CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  policy_id text NOT NULL CHECK (policy_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  policy_generation integer NOT NULL CHECK (policy_generation >= 1),
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  enabled boolean NOT NULL DEFAULT false,
  period_approved boolean NOT NULL DEFAULT false,
  cost_approved boolean NOT NULL DEFAULT false,
  intake_approved boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (campaign_id, actor_id)
);
-- Existing disposable deployments may already have the pre-intake campaign table.
ALTER TABLE rag_campaign_definitions ADD COLUMN IF NOT EXISTS intake_approved boolean NOT NULL DEFAULT false;
-- Persisted full demand and reviewed public projection, without users.id or
-- private learner references. Issuance is neither a job nor a provider receipt.
CREATE TABLE IF NOT EXISTS rag_campaign_issued_contexts (
  operation_key text PRIMARY KEY CHECK (operation_key ~ '^[a-zA-Z0-9._:-]{8,160}$'),
  campaign_id text NOT NULL,
  actor_id text NOT NULL,
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  facets text[] NOT NULL CHECK (cardinality(facets) BETWEEN 1 AND 24),
  purpose text NOT NULL,
  reading_level text NOT NULL,
  language text NOT NULL,
  draft_revision integer NOT NULL,
  reviewed_terms text[] NOT NULL CHECK (cardinality(reviewed_terms) BETWEEN 1 AND 8),
  query_hash text NOT NULL CHECK (query_hash ~ '^[0-9a-f]{64}$'),
  policy_id text NOT NULL,
  policy_generation integer NOT NULL,
  root_id text NOT NULL,
  delegation_id text NOT NULL,
  delegation_generation integer NOT NULL,
  issued_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (campaign_id, actor_id)
    REFERENCES rag_campaign_definitions(campaign_id, actor_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_rag_campaign_issued_campaign
  ON rag_campaign_issued_contexts(campaign_id);
CREATE OR REPLACE FUNCTION rag_campaign_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR TG_TABLE_NAME = 'rag_campaign_issued_contexts' THEN
    RAISE EXCEPTION 'campaign authority is append-only' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME = 'rag_campaign_principals' THEN
    IF (to_jsonb(NEW)-'enabled') IS DISTINCT FROM (to_jsonb(OLD)-'enabled') THEN
      RAISE EXCEPTION 'service principal identity is immutable' USING ERRCODE='23514';
    END IF;
  ELSIF (to_jsonb(NEW)-'enabled'-'period_approved'-'cost_approved'-'intake_approved')
       IS DISTINCT FROM (to_jsonb(OLD)-'enabled'-'period_approved'-'cost_approved'-'intake_approved') THEN
    RAISE EXCEPTION 'campaign definition is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_campaign_principal_guard ON rag_campaign_principals;
CREATE TRIGGER trg_rag_campaign_principal_guard BEFORE UPDATE OR DELETE
  ON rag_campaign_principals FOR EACH ROW EXECUTE FUNCTION rag_campaign_immutable_guard();
DROP TRIGGER IF EXISTS trg_rag_campaign_definition_guard ON rag_campaign_definitions;
CREATE TRIGGER trg_rag_campaign_definition_guard BEFORE UPDATE OR DELETE
  ON rag_campaign_definitions FOR EACH ROW EXECUTE FUNCTION rag_campaign_immutable_guard();
DROP TRIGGER IF EXISTS trg_rag_campaign_issued_guard ON rag_campaign_issued_contexts;
CREATE TRIGGER trg_rag_campaign_issued_guard BEFORE UPDATE OR DELETE
  ON rag_campaign_issued_contexts FOR EACH ROW EXECUTE FUNCTION rag_campaign_immutable_guard();
