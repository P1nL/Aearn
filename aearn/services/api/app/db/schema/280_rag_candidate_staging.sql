-- B2 quarantine: no FK to active corpus or formal consumers.
CREATE TABLE IF NOT EXISTS rag_candidate_captures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_id uuid NOT NULL UNIQUE,
  job_id uuid NOT NULL,
  evidence_level text NOT NULL CHECK (evidence_level IN ('offline_protocol_only','live_egress_attested')),
  final_url text NOT NULL CHECK (char_length(final_url) BETWEEN 9 AND 2048),
  request_chain jsonb NOT NULL CHECK (jsonb_typeof(request_chain)='array' AND jsonb_array_length(request_chain) BETWEEN 1 AND 6),
  chain_sha256 text NOT NULL CHECK (chain_sha256 ~ '^[0-9a-f]{64}$'),
  media_type text NOT NULL CHECK (media_type IN ('text/html','text/plain','text/markdown')),
  fetched_sha256 text NOT NULL CHECK (fetched_sha256 ~ '^[0-9a-f]{64}$'),
  capture_kind text NOT NULL CHECK (capture_kind IN ('none','prefix','full')),
  captured_bytes integer NOT NULL CHECK (captured_bytes BETWEEN 0 AND 10000000),
  prefix_sha256 text CHECK (prefix_sha256 ~ '^[0-9a-f]{64}$'),
  full_sha256 text CHECK (full_sha256 ~ '^[0-9a-f]{64}$'),
  captured_body bytea,
  policy_id text NOT NULL,
  policy_generation integer NOT NULL CHECK (policy_generation > 0),
  retention_until timestamptz NOT NULL,
  cleared_at timestamptz,
  license_id text CHECK (license_id ~ '^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$'),
  author_name text CHECK (char_length(author_name) BETWEEN 1 AND 160),
  origin_sha256 text CHECK (origin_sha256 ~ '^[0-9a-f]{64}$'),
  repo_commit text CHECK (repo_commit ~ '^[0-9a-f]{40}$'),
  repo_path text CHECK (char_length(repo_path) BETWEEN 1 AND 400),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(candidate_id,job_id) REFERENCES rag_discovery_candidates(id,job_id) ON DELETE RESTRICT,
  CHECK ((capture_kind='none' AND captured_bytes=0 AND prefix_sha256 IS NULL AND full_sha256 IS NULL AND captured_body IS NULL)
     OR (capture_kind='prefix' AND captured_bytes>0 AND prefix_sha256 IS NOT NULL AND full_sha256 IS NULL)
     OR (capture_kind='full' AND captured_bytes>0 AND prefix_sha256 IS NULL AND full_sha256 IS NOT NULL)),
  CHECK ((cleared_at IS NULL AND (capture_kind='none' OR (captured_body IS NOT NULL AND octet_length(captured_body)=captured_bytes)))
     OR (cleared_at IS NOT NULL AND captured_body IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_rag_candidate_captures_retention ON rag_candidate_captures(retention_until,id) WHERE cleared_at IS NULL;
CREATE TABLE IF NOT EXISTS rag_candidate_fragments (
  capture_id uuid NOT NULL REFERENCES rag_candidate_captures(id) ON DELETE RESTRICT,
  ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 511),
  kind text NOT NULL CHECK (kind IN ('heading','paragraph','list_item','table_row','code')),
  depth integer NOT NULL CHECK (depth BETWEEN 0 AND 16),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  text_content text CHECK (char_length(text_content) BETWEEN 1 AND 16384),
  PRIMARY KEY(capture_id,ordinal)
);
-- Actor references are private; shared capture/receipt rows contain no learner material.
CREATE TABLE IF NOT EXISTS rag_candidate_private_refs (
  actor_id text NOT NULL CHECK (actor_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  candidate_id uuid NOT NULL REFERENCES rag_discovery_candidates(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(actor_id,candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_rag_candidate_private_refs_candidate ON rag_candidate_private_refs(candidate_id);
CREATE OR REPLACE FUNCTION rag_candidate_capture_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.cleared_at IS NOT NULL THEN
      RAISE EXCEPTION 'capture cannot start cleared' USING ERRCODE='23514';
    END IF;
    IF NEW.retention_until<=clock_timestamp() AND NEW.captured_body IS NOT NULL THEN
      RAISE EXCEPTION 'capture retention expired' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.cleared_at IS NOT NULL OR
     (to_jsonb(NEW)-'captured_body'-'cleared_at') IS DISTINCT FROM (to_jsonb(OLD)-'captured_body'-'cleared_at') OR
     NEW.cleared_at IS NULL OR NEW.captured_body IS NOT NULL THEN
    RAISE EXCEPTION 'capture immutable or cleared' USING ERRCODE='23514';
  END IF;
  -- A direct SQL clear must not strand readable fragment text. The repository
  -- scrubs child text first, then clears the parent in the same transaction.
  IF EXISTS (SELECT 1 FROM rag_candidate_fragments
             WHERE capture_id=NEW.id AND text_content IS NOT NULL) THEN
    RAISE EXCEPTION 'capture fragments not cleared' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_candidate_capture_guard ON rag_candidate_captures;
CREATE TRIGGER trg_rag_candidate_capture_guard BEFORE INSERT OR UPDATE ON rag_candidate_captures
 FOR EACH ROW EXECUTE FUNCTION rag_candidate_capture_guard();
CREATE OR REPLACE FUNCTION rag_candidate_fragment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent rag_candidate_captures%ROWTYPE;
BEGIN
  SELECT * INTO parent FROM rag_candidate_captures WHERE id=NEW.capture_id FOR UPDATE;
  IF NOT FOUND OR parent.capture_kind<>'full' OR parent.cleared_at IS NOT NULL
     OR (TG_OP='INSERT' AND parent.retention_until<=clock_timestamp()) THEN
    RAISE EXCEPTION 'fragment unavailable' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' AND ((OLD.capture_id,OLD.ordinal,OLD.kind,OLD.depth,OLD.sha256)
       IS DISTINCT FROM (NEW.capture_id,NEW.ordinal,NEW.kind,NEW.depth,NEW.sha256)
       OR OLD.text_content IS NULL OR NEW.text_content IS NOT NULL) THEN
    RAISE EXCEPTION 'fragment immutable or cleared' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_candidate_fragment_guard ON rag_candidate_fragments;
CREATE TRIGGER trg_rag_candidate_fragment_guard BEFORE INSERT OR UPDATE ON rag_candidate_fragments
 FOR EACH ROW EXECUTE FUNCTION rag_candidate_fragment_guard();

-- A completed B1 discovery lease cannot authorize later B2 network/storage I/O.
-- Candidate-specific intake leases never reopen the one-shot discovery dispatch.
CREATE TABLE IF NOT EXISTS rag_candidate_intake_leases (
  candidate_id uuid PRIMARY KEY,
  job_id uuid NOT NULL,
  state text NOT NULL DEFAULT 'idle' CHECK (state IN ('idle','leased','done')),
  owner_id text CHECK (owner_id ~ '^[a-zA-Z0-9._:-]{3,120}$'),
  generation integer NOT NULL DEFAULT 0 CHECK (generation >= 0),
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(candidate_id,job_id) REFERENCES rag_discovery_candidates(id,job_id) ON DELETE RESTRICT,
  CHECK ((state = 'leased') = (owner_id IS NOT NULL AND expires_at IS NOT NULL)),
  CHECK (state <> 'leased' OR generation > 0)
);
CREATE INDEX IF NOT EXISTS idx_rag_candidate_intake_leases_claim
 ON rag_candidate_intake_leases(updated_at,candidate_id) WHERE state IN ('idle','leased');
CREATE OR REPLACE FUNCTION rag_candidate_intake_lease_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'intake lease deletion denied' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-'state'-'owner_id'-'generation'-'expires_at'-'updated_at')
      IS DISTINCT FROM (to_jsonb(OLD)-'state'-'owner_id'-'generation'-'expires_at'-'updated_at')
     OR OLD.state='done'
     OR (NEW.state='leased' AND NEW.expires_at<=clock_timestamp())
     OR (NEW.state='done' AND NOT EXISTS (
         SELECT 1 FROM rag_candidate_captures WHERE candidate_id=NEW.candidate_id))
     OR NOT (
       (OLD.state='idle' AND NEW.state='leased' AND NEW.generation=OLD.generation+1)
       OR (OLD.state='leased' AND NEW.state='leased' AND OLD.expires_at<=clock_timestamp()
           AND NEW.generation=OLD.generation+1)
       OR (OLD.state='leased' AND NEW.state IN ('idle','done')
           AND NEW.generation=OLD.generation)
     ) THEN
    RAISE EXCEPTION 'intake lease transition denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_candidate_intake_lease_guard ON rag_candidate_intake_leases;
CREATE TRIGGER trg_rag_candidate_intake_lease_guard BEFORE UPDATE OR DELETE ON rag_candidate_intake_leases
 FOR EACH ROW EXECUTE FUNCTION rag_candidate_intake_lease_guard();
