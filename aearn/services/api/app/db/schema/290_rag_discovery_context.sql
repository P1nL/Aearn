-- B1 job context is server-issued. Shared rows contain reviewed, de-identified
-- search terms only; plan/node/revision and actor ownership remain private.
-- An actor is never inferred from a UUID or retroactively bound to legacy refs.
CREATE TABLE IF NOT EXISTS rag_discovery_actor_owners (
  actor_id text PRIMARY KEY CHECK (actor_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  bound_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (actor_id,user_id)
);
CREATE INDEX IF NOT EXISTS idx_rag_discovery_actor_owners_user ON rag_discovery_actor_owners(user_id);

CREATE TABLE IF NOT EXISTS rag_discovery_query_contexts (
  job_id uuid PRIMARY KEY REFERENCES rag_discovery_jobs(id) ON DELETE RESTRICT,
  reviewed_terms text[] NOT NULL CHECK (cardinality(reviewed_terms) BETWEEN 1 AND 8),
  query_hash text NOT NULL CHECK (query_hash ~ '^[0-9a-f]{64}$'),
  issued_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_discovery_private_contexts (
  job_id uuid NOT NULL,
  actor_id text NOT NULL,
  user_id uuid NOT NULL,
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  plan_ref text NOT NULL CHECK (plan_ref ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  node_ref text NOT NULL CHECK (node_ref ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  draft_revision integer NOT NULL CHECK (draft_revision BETWEEN 1 AND 1000000),
  reading_level text NOT NULL CHECK (reading_level IN ('beginner','intermediate','advanced')),
  language text NOT NULL CHECK (language IN ('zh','en')),
  facets text[] NOT NULL CHECK (cardinality(facets) BETWEEN 1 AND 24),
  issued_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id,actor_id),
  FOREIGN KEY (job_id,actor_id,demand_hash)
    REFERENCES rag_discovery_job_refs(job_id,actor_id,demand_hash) ON DELETE RESTRICT,
  FOREIGN KEY (actor_id,user_id) REFERENCES rag_discovery_actor_owners(actor_id,user_id) ON DELETE RESTRICT,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_rag_discovery_private_contexts_user
  ON rag_discovery_private_contexts(user_id,job_id);

-- Prevent a second actor/user binding via direct SQL; an owner row is the only
-- route for later context. Shared projections may never be silently rewritten.
CREATE OR REPLACE FUNCTION rag_discovery_context_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'discovery context is immutable' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME = 'rag_discovery_private_contexts' AND NOT EXISTS (
    SELECT 1 FROM rag_discovery_actor_owners o
    WHERE o.actor_id=NEW.actor_id AND o.user_id=NEW.user_id
  ) THEN
    RAISE EXCEPTION 'actor owner mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_discovery_query_context_guard ON rag_discovery_query_contexts;
CREATE TRIGGER trg_rag_discovery_query_context_guard BEFORE UPDATE OR DELETE
  ON rag_discovery_query_contexts FOR EACH ROW EXECUTE FUNCTION rag_discovery_context_guard();
DROP TRIGGER IF EXISTS trg_rag_discovery_private_context_guard ON rag_discovery_private_contexts;
CREATE TRIGGER trg_rag_discovery_private_context_guard BEFORE INSERT OR UPDATE
  ON rag_discovery_private_contexts FOR EACH ROW EXECUTE FUNCTION rag_discovery_context_guard();

-- Do not reassign an actor handle. Remove refs first during explicit owner
-- reset/delete; a dangling actor-only ref must remain unclaimed.
CREATE OR REPLACE FUNCTION rag_discovery_actor_owner_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' OR EXISTS (
    SELECT 1 FROM rag_discovery_job_refs WHERE actor_id=OLD.actor_id
  ) OR EXISTS (
    SELECT 1 FROM rag_candidate_private_refs WHERE actor_id=OLD.actor_id
  ) THEN
    RAISE EXCEPTION 'actor owner change denied while referenced' USING ERRCODE='23514';
  END IF;
  RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS trg_rag_discovery_actor_owner_guard ON rag_discovery_actor_owners;
CREATE TRIGGER trg_rag_discovery_actor_owner_guard BEFORE UPDATE OR DELETE
  ON rag_discovery_actor_owners FOR EACH ROW EXECUTE FUNCTION rag_discovery_actor_owner_guard();
