-- RAG phase-I versioned corpus authority. Legacy grounding tables are unchanged.
CREATE OR REPLACE FUNCTION corpus_safe_summary(payload jsonb, max_fields integer, counts_only boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE entry record;
BEGIN
  IF payload IS NULL OR jsonb_typeof(payload)<>'object' OR
     (SELECT count(*) FROM jsonb_each(payload)) > max_fields THEN RETURN false; END IF;
  FOR entry IN SELECT key, value FROM jsonb_each(payload) LOOP
    IF entry.key !~ '^[a-zA-Z][a-zA-Z0-9_]{0,79}$' OR
       lower(entry.key) ~ '(token|secret|credential|password|header|prompt|body|url|path)' THEN RETURN false; END IF;
    IF jsonb_typeof(entry.value)='number' THEN
      IF entry.value::text !~ '^(0|[1-9][0-9]{0,8})$' THEN RETURN false; END IF;
    ELSIF NOT counts_only AND jsonb_typeof(entry.value)='string' THEN
      IF (entry.value #>> '{}') !~ '^[a-zA-Z0-9._-]{1,80}$' THEN RETURN false; END IF;
    ELSIF counts_only OR jsonb_typeof(entry.value)<>'boolean' THEN RETURN false;
    END IF;
  END LOOP;
  RETURN true;
END;
$$;
CREATE OR REPLACE FUNCTION corpus_safe_text_array(payload jsonb, min_items integer, max_items integer,
                                                   max_chars integer, item_pattern text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE item jsonb;
DECLARE value text;
BEGIN
  IF payload IS NULL OR jsonb_typeof(payload)<>'array' OR
     jsonb_array_length(payload) NOT BETWEEN min_items AND max_items THEN RETURN false; END IF;
  FOR item IN SELECT entry FROM jsonb_array_elements(payload) AS items(entry) LOOP
    IF jsonb_typeof(item)<>'string' THEN RETURN false; END IF;
    value := item #>> '{}';
    IF length(value) NOT BETWEEN 1 AND max_chars OR value !~ item_pattern THEN RETURN false; END IF;
  END LOOP;
  RETURN true;
END;
$$;

CREATE TABLE IF NOT EXISTS grounding_corpus_versions (
  id uuid PRIMARY KEY,
  subject_id text NOT NULL CHECK (subject_id ~ '^[a-z][a-z0-9.-]{2,99}$'),
  subject_version text NOT NULL CHECK (subject_version ~ '^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$'),
  registry_digest text NOT NULL CHECK (registry_digest ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'candidate' CHECK (state IN ('candidate','validated','published','failed','retired')),
  generation integer NOT NULL DEFAULT 0 CHECK (generation >= 0),
  source_set_hash text CHECK (source_set_hash IS NULL OR source_set_hash ~ '^[0-9a-f]{64}$'),
  content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
  summary_hash text CHECK (summary_hash IS NULL OR summary_hash ~ '^[0-9a-f]{64}$'),
  retrieval_policy_version text NOT NULL CHECK (retrieval_policy_version ~ '^[a-z0-9][a-z0-9._-]{0,79}$'),
  coverage_policy_version text NOT NULL CHECK (coverage_policy_version ~ '^[a-z0-9][a-z0-9._-]{0,79}$'),
  coverage_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(coverage_summary_json)='object' AND octet_length(coverage_summary_json::text)<=8192 AND corpus_safe_summary(coverage_summary_json,32)),
  validation_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(validation_summary_json)='object' AND octet_length(validation_summary_json::text)<=8192 AND corpus_safe_summary(validation_summary_json,32)),
  created_at timestamptz NOT NULL DEFAULT now(),
  validated_at timestamptz,
  published_at timestamptz,
  retired_at timestamptz,
  CONSTRAINT uq_grounding_corpus_versions_subject UNIQUE (id,subject_id),
  CONSTRAINT uq_grounding_corpus_versions_scope UNIQUE (id,subject_id,subject_version),
  CONSTRAINT chk_grounding_corpus_seal CHECK (
    (state='candidate' AND summary_hash IS NULL AND validated_at IS NULL AND published_at IS NULL)
    OR (state='failed' AND summary_hash IS NULL AND published_at IS NULL)
    OR (state='retired' AND summary_hash IS NULL AND validated_at IS NULL AND published_at IS NULL)
    OR (state IN ('validated','published','retired') AND source_set_hash IS NOT NULL AND content_hash IS NOT NULL AND summary_hash IS NOT NULL AND validated_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS grounding_corpus_source_snapshots (
  corpus_version_id uuid NOT NULL,
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  source_id text NOT NULL CHECK (source_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  trust_tier text NOT NULL CHECK (trust_tier IN ('official','trusted_de_facto')),
  source_kind text NOT NULL CHECK (source_kind ~ '^[a-z0-9][a-z0-9._-]{0,79}$'),
  source_version text NOT NULL CHECK (length(source_version) BETWEEN 1 AND 80),
  allowed_domains_json jsonb NOT NULL CHECK (jsonb_typeof(allowed_domains_json)='array' AND jsonb_array_length(allowed_domains_json) BETWEEN 1 AND 24 AND octet_length(allowed_domains_json::text)<=4096 AND allowed_domains_json::text !~ '[@/?#:]'),
  seed_urls_json jsonb NOT NULL CHECK (jsonb_typeof(seed_urls_json)='array' AND jsonb_array_length(seed_urls_json)<=24 AND octet_length(seed_urls_json::text)<=8192 AND seed_urls_json::text !~ '[@?#]'),
  facets_json jsonb NOT NULL CHECK (jsonb_typeof(facets_json)='array' AND jsonb_array_length(facets_json) BETWEEN 1 AND 24 AND octet_length(facets_json::text)<=4096),
  PRIMARY KEY (corpus_version_id,source_id),
  CONSTRAINT uq_grounding_corpus_sources_lineage UNIQUE (corpus_version_id,source_id,subject_id,subject_version,source_hash,trust_tier),
  CONSTRAINT fk_grounding_corpus_sources_scope FOREIGN KEY (corpus_version_id,subject_id,subject_version) REFERENCES grounding_corpus_versions(id,subject_id,subject_version) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS grounding_corpus_documents (
  corpus_version_id uuid NOT NULL,
  document_id text NOT NULL CHECK (document_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_id text NOT NULL,
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  source_hash text NOT NULL,
  trust_tier text NOT NULL,
  canonical_url text NOT NULL CHECK (length(canonical_url) BETWEEN 8 AND 2048 AND canonical_url ~ '^https://' AND canonical_url !~ '[@?#]'),
  final_url text NOT NULL CHECK (length(final_url) BETWEEN 8 AND 2048 AND final_url ~ '^https://' AND final_url !~ '[@?#]'),
  content_type text NOT NULL CHECK (length(content_type) BETWEEN 1 AND 100),
  document_version text NOT NULL CHECK (length(document_version) BETWEEN 1 AND 80),
  fetched_at timestamptz NOT NULL,
  document_hash text NOT NULL CHECK (document_hash ~ '^[0-9a-f]{64}$'),
  parse_status text NOT NULL CHECK (parse_status IN ('parsed','failed','empty')),
  diagnostic_code text CHECK (diagnostic_code IS NULL OR diagnostic_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  PRIMARY KEY (corpus_version_id,document_id),
  CONSTRAINT uq_grounding_corpus_documents_lineage UNIQUE (corpus_version_id,document_id,source_id,subject_id,subject_version,source_hash,trust_tier,document_hash),
  CONSTRAINT fk_grounding_corpus_documents_source FOREIGN KEY (corpus_version_id,source_id,subject_id,subject_version,source_hash,trust_tier) REFERENCES grounding_corpus_source_snapshots(corpus_version_id,source_id,subject_id,subject_version,source_hash,trust_tier) ON DELETE RESTRICT,
  CONSTRAINT chk_grounding_corpus_parse CHECK ((parse_status='failed' AND diagnostic_code IS NOT NULL) OR (parse_status<>'failed' AND diagnostic_code IS NULL))
);

CREATE TABLE IF NOT EXISTS grounding_corpus_chunks (
  corpus_version_id uuid NOT NULL,
  chunk_id text NOT NULL CHECK (chunk_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  document_id text NOT NULL,
  source_id text NOT NULL,
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  source_hash text NOT NULL,
  trust_tier text NOT NULL,
  document_hash text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
  section_path text NOT NULL CHECK (length(section_path) BETWEEN 1 AND 1000),
  content text NOT NULL CHECK (length(content) BETWEEN 1 AND 8000),
  facets_json jsonb NOT NULL CHECK (jsonb_typeof(facets_json)='array' AND jsonb_array_length(facets_json) BETWEEN 1 AND 24 AND octet_length(facets_json::text)<=4096),
  topic_tags_json jsonb NOT NULL CHECK (jsonb_typeof(topic_tags_json)='array' AND jsonb_array_length(topic_tags_json)<=24 AND octet_length(topic_tags_json::text)<=4096),
  chunk_hash text NOT NULL CHECK (chunk_hash ~ '^[0-9a-f]{64}$'),
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, title || ' ' || section_path || ' ' || content)) STORED,
  PRIMARY KEY (corpus_version_id,chunk_id),
  CONSTRAINT uq_grounding_corpus_chunk_position UNIQUE (corpus_version_id,document_id,ordinal),
  CONSTRAINT fk_grounding_corpus_chunk_document FOREIGN KEY (corpus_version_id,document_id,source_id,subject_id,subject_version,source_hash,trust_tier,document_hash) REFERENCES grounding_corpus_documents(corpus_version_id,document_id,source_id,subject_id,subject_version,source_hash,trust_tier,document_hash) ON DELETE RESTRICT
);
-- Replaying this fragment preserves existing tables while tightening the stored text digest.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_grounding_corpus_chunk_content_hash') THEN
    ALTER TABLE grounding_corpus_chunks ADD CONSTRAINT chk_grounding_corpus_chunk_content_hash
      CHECK (chunk_hash=encode(digest(content,'sha256'),'hex')) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM grounding_corpus_chunks WHERE chunk_hash<>encode(digest(content,'sha256'),'hex')) THEN
    ALTER TABLE grounding_corpus_chunks VALIDATE CONSTRAINT chk_grounding_corpus_chunk_content_hash;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_grounding_corpus_chunks_search ON grounding_corpus_chunks USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_grounding_corpus_chunks_scope ON grounding_corpus_chunks(corpus_version_id,subject_id,subject_version,source_id);

CREATE TABLE IF NOT EXISTS grounding_corpus_events (
  id uuid PRIMARY KEY,
  corpus_version_id uuid NOT NULL,
  subject_id text NOT NULL,
  event_kind text NOT NULL CHECK (event_kind IN ('reindex_started','reindex_completed','validation_passed','validation_failed','diff_generated','activated','rolled_back','retired')),
  operation_id uuid NOT NULL,
  idempotency_key text NOT NULL CHECK (idempotency_key ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  summary_hash text CHECK (summary_hash IS NULL OR summary_hash ~ '^[0-9a-f]{64}$'),
  expected_generation integer CHECK (expected_generation IS NULL OR expected_generation >= 0),
  observed_generation integer CHECK (observed_generation IS NULL OR observed_generation >= 0),
  counts_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts_json)='object' AND octet_length(counts_json::text)<=4096 AND corpus_safe_summary(counts_json,16,true)),
  reason_code text CHECK (reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_grounding_corpus_event_operation UNIQUE (operation_id),
  CONSTRAINT uq_grounding_corpus_event_replay UNIQUE (event_kind,idempotency_key),
  CONSTRAINT uq_grounding_corpus_event_pointer UNIQUE (id,corpus_version_id,subject_id,event_kind,observed_generation),
  CONSTRAINT fk_grounding_corpus_event_scope FOREIGN KEY (corpus_version_id,subject_id) REFERENCES grounding_corpus_versions(id,subject_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_grounding_corpus_events_history ON grounding_corpus_events(subject_id,created_at,id);

CREATE TABLE IF NOT EXISTS grounding_active_corpora (
  subject_id text PRIMARY KEY,
  corpus_version_id uuid NOT NULL,
  generation integer NOT NULL CHECK (generation >= 1),
  activation_event_id uuid NOT NULL,
  activation_event_kind text NOT NULL CHECK (activation_event_kind IN ('activated','rolled_back')),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_grounding_active_corpus_subject FOREIGN KEY (corpus_version_id,subject_id) REFERENCES grounding_corpus_versions(id,subject_id) ON DELETE RESTRICT,
  CONSTRAINT fk_grounding_active_corpus_event FOREIGN KEY (activation_event_id,corpus_version_id,subject_id,activation_event_kind,generation) REFERENCES grounding_corpus_events(id,corpus_version_id,subject_id,event_kind,observed_generation) ON DELETE RESTRICT
);

-- Repeat bootstrap tightens pre-existing installations without replacing historical rows.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_grounding_corpus_operator_summary_safe') THEN
    ALTER TABLE grounding_corpus_versions ADD CONSTRAINT chk_grounding_corpus_operator_summary_safe
      CHECK (corpus_safe_summary(coverage_summary_json,32) AND corpus_safe_summary(validation_summary_json,32)) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_grounding_corpus_event_counts_safe') THEN
    ALTER TABLE grounding_corpus_events ADD CONSTRAINT chk_grounding_corpus_event_counts_safe
      CHECK (corpus_safe_summary(counts_json,16,true)) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM grounding_corpus_versions
                 WHERE NOT corpus_safe_summary(coverage_summary_json,32) OR NOT corpus_safe_summary(validation_summary_json,32)) THEN
    ALTER TABLE grounding_corpus_versions VALIDATE CONSTRAINT chk_grounding_corpus_operator_summary_safe;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM grounding_corpus_events WHERE NOT corpus_safe_summary(counts_json,16,true)) THEN
    ALTER TABLE grounding_corpus_events VALIDATE CONSTRAINT chk_grounding_corpus_event_counts_safe;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_grounding_corpus_source_arrays_safe') THEN
    ALTER TABLE grounding_corpus_source_snapshots ADD CONSTRAINT chk_grounding_corpus_source_arrays_safe CHECK (
      corpus_safe_text_array(allowed_domains_json,1,24,160,'^[a-z0-9][a-z0-9.-]{0,159}$') AND
      corpus_safe_text_array(seed_urls_json,0,24,2048,'^https://[a-zA-Z0-9.-]+(/[^@?#]*)?$') AND
      corpus_safe_text_array(facets_json,1,24,160,'^[a-z0-9][a-z0-9._-]{0,159}$')) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_grounding_corpus_chunk_arrays_safe') THEN
    ALTER TABLE grounding_corpus_chunks ADD CONSTRAINT chk_grounding_corpus_chunk_arrays_safe CHECK (
      corpus_safe_text_array(facets_json,1,24,160,'^[a-z0-9][a-z0-9._-]{0,159}$') AND
      corpus_safe_text_array(topic_tags_json,0,24,160,'^[a-z0-9][a-z0-9._-]{0,159}$')) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM grounding_corpus_source_snapshots WHERE NOT (
      corpus_safe_text_array(allowed_domains_json,1,24,160,'^[a-z0-9][a-z0-9.-]{0,159}$') AND
      corpus_safe_text_array(seed_urls_json,0,24,2048,'^https://[a-zA-Z0-9.-]+(/[^@?#]*)?$') AND
      corpus_safe_text_array(facets_json,1,24,160,'^[a-z0-9][a-z0-9._-]{0,159}$'))) THEN
    ALTER TABLE grounding_corpus_source_snapshots VALIDATE CONSTRAINT chk_grounding_corpus_source_arrays_safe;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM grounding_corpus_chunks WHERE NOT (
      corpus_safe_text_array(facets_json,1,24,160,'^[a-z0-9][a-z0-9._-]{0,159}$') AND
      corpus_safe_text_array(topic_tags_json,0,24,160,'^[a-z0-9][a-z0-9._-]{0,159}$'))) THEN
    ALTER TABLE grounding_corpus_chunks VALIDATE CONSTRAINT chk_grounding_corpus_chunk_arrays_safe;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_grounding_corpus_source_urls_safe') THEN
    ALTER TABLE grounding_corpus_source_snapshots ADD CONSTRAINT chk_grounding_corpus_source_urls_safe
      CHECK (allowed_domains_json::text !~ '[@/?#:]' AND seed_urls_json::text !~ '[@?#]') NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_grounding_corpus_document_urls_safe') THEN
    ALTER TABLE grounding_corpus_documents ADD CONSTRAINT chk_grounding_corpus_document_urls_safe
      CHECK (canonical_url !~ '[@?#]' AND final_url !~ '[@?#]') NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM grounding_corpus_source_snapshots
                 WHERE allowed_domains_json::text ~ '[@/?#:]' OR seed_urls_json::text ~ '[@?#]') THEN
    ALTER TABLE grounding_corpus_source_snapshots VALIDATE CONSTRAINT chk_grounding_corpus_source_urls_safe;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM grounding_corpus_documents WHERE canonical_url ~ '[@?#]' OR final_url ~ '[@?#]') THEN
    ALTER TABLE grounding_corpus_documents VALIDATE CONSTRAINT chk_grounding_corpus_document_urls_safe;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_grounding_corpus_version_mutation() RETURNS trigger AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'candidate' OR NEW.generation<>0 OR NEW.summary_hash IS NOT NULL OR NEW.validated_at IS NOT NULL THEN
      RAISE EXCEPTION 'new corpus must begin as candidate' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'corpus history cannot be deleted' USING ERRCODE='23514'; END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.subject_id IS DISTINCT FROM OLD.subject_id OR NEW.subject_version IS DISTINCT FROM OLD.subject_version OR NEW.registry_digest IS DISTINCT FROM OLD.registry_digest OR NEW.retrieval_policy_version IS DISTINCT FROM OLD.retrieval_policy_version OR NEW.coverage_policy_version IS DISTINCT FROM OLD.coverage_policy_version OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'corpus identity is immutable' USING ERRCODE='23514';
  END IF;
  IF NOT ((OLD.state='candidate' AND NEW.state IN ('candidate','validated','failed','retired')) OR (OLD.state='validated' AND NEW.state IN ('published','retired')) OR (OLD.state='published' AND NEW.state='retired')) THEN
    RAISE EXCEPTION 'invalid corpus lifecycle transition' USING ERRCODE='23514';
  END IF;
  IF NEW.generation<>OLD.generation+1 THEN RAISE EXCEPTION 'corpus generation is stale' USING ERRCODE='23514'; END IF;
  IF OLD.state<>'candidate' AND (NEW.source_set_hash IS DISTINCT FROM OLD.source_set_hash OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.summary_hash IS DISTINCT FROM OLD.summary_hash OR NEW.coverage_summary_json IS DISTINCT FROM OLD.coverage_summary_json OR NEW.validation_summary_json IS DISTINCT FROM OLD.validation_summary_json OR NEW.validated_at IS DISTINCT FROM OLD.validated_at OR NEW.published_at IS DISTINCT FROM OLD.published_at) THEN
    IF NOT (OLD.state='validated' AND NEW.state='published' AND NEW.published_at IS NOT NULL AND NEW.source_set_hash=OLD.source_set_hash AND NEW.content_hash=OLD.content_hash AND NEW.summary_hash=OLD.summary_hash AND NEW.coverage_summary_json=OLD.coverage_summary_json AND NEW.validation_summary_json=OLD.validation_summary_json AND NEW.validated_at=OLD.validated_at) THEN
      RAISE EXCEPTION 'sealed corpus metadata is immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.state='retired' AND EXISTS(SELECT 1 FROM grounding_active_corpora WHERE corpus_version_id=OLD.id) THEN
    RAISE EXCEPTION 'active corpus cannot retire' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_grounding_corpus_child_mutation() RETURNS trigger AS $$
DECLARE parent_state text;
DECLARE owner_id uuid;
BEGIN
  -- Reject reparenting before checking either parent's state: moving a sealed row to a candidate must not bypass the guard.
  IF TG_OP='UPDATE' AND NEW.corpus_version_id IS DISTINCT FROM OLD.corpus_version_id THEN
    RAISE EXCEPTION 'corpus child identity cannot change' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN owner_id:=OLD.corpus_version_id; ELSE owner_id:=NEW.corpus_version_id; END IF;
  SELECT state INTO parent_state FROM grounding_corpus_versions WHERE id=owner_id FOR UPDATE;
  IF parent_state IS DISTINCT FROM 'candidate' THEN RAISE EXCEPTION 'sealed corpus content is immutable' USING ERRCODE='23514'; END IF;
  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_grounding_corpus_active_pointer() RETURNS trigger AS $$
DECLARE corpus_state text;
DECLARE event_expected integer;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'active pointer cannot be deleted' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND (NEW.subject_id<>OLD.subject_id OR NEW.generation<>OLD.generation+1) THEN
    RAISE EXCEPTION 'active generation must advance exactly once' USING ERRCODE='23514';
  END IF;
  IF TG_OP='INSERT' AND NEW.generation<>1 THEN RAISE EXCEPTION 'initial generation must be one' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' AND NEW.activation_event_kind<>'activated' THEN
    RAISE EXCEPTION 'initial pointer requires activation receipt' USING ERRCODE='23514';
  END IF;
  SELECT state INTO corpus_state FROM grounding_corpus_versions WHERE id=NEW.corpus_version_id AND subject_id=NEW.subject_id FOR UPDATE;
  IF corpus_state IS DISTINCT FROM 'published' THEN RAISE EXCEPTION 'active pointer requires same-subject published corpus' USING ERRCODE='23514'; END IF;
  SELECT expected_generation INTO event_expected FROM grounding_corpus_events
    WHERE id=NEW.activation_event_id AND corpus_version_id=NEW.corpus_version_id
      AND subject_id=NEW.subject_id AND event_kind=NEW.activation_event_kind
      AND observed_generation=NEW.generation;
  IF event_expected IS DISTINCT FROM NEW.generation-1 THEN
    RAISE EXCEPTION 'active pointer requires matching expected generation receipt' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_grounding_corpus_event_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'corpus event is append-only' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_grounding_corpus_versions_guard ON grounding_corpus_versions;
CREATE TRIGGER trg_grounding_corpus_versions_guard BEFORE INSERT OR UPDATE OR DELETE ON grounding_corpus_versions FOR EACH ROW EXECUTE FUNCTION enforce_grounding_corpus_version_mutation();
DROP TRIGGER IF EXISTS trg_grounding_corpus_sources_guard ON grounding_corpus_source_snapshots;
CREATE TRIGGER trg_grounding_corpus_sources_guard BEFORE INSERT OR UPDATE OR DELETE ON grounding_corpus_source_snapshots FOR EACH ROW EXECUTE FUNCTION enforce_grounding_corpus_child_mutation();
DROP TRIGGER IF EXISTS trg_grounding_corpus_documents_guard ON grounding_corpus_documents;
CREATE TRIGGER trg_grounding_corpus_documents_guard BEFORE INSERT OR UPDATE OR DELETE ON grounding_corpus_documents FOR EACH ROW EXECUTE FUNCTION enforce_grounding_corpus_child_mutation();
DROP TRIGGER IF EXISTS trg_grounding_corpus_chunks_guard ON grounding_corpus_chunks;
CREATE TRIGGER trg_grounding_corpus_chunks_guard BEFORE INSERT OR UPDATE OR DELETE ON grounding_corpus_chunks FOR EACH ROW EXECUTE FUNCTION enforce_grounding_corpus_child_mutation();
DROP TRIGGER IF EXISTS trg_grounding_corpus_events_guard ON grounding_corpus_events;
CREATE TRIGGER trg_grounding_corpus_events_guard BEFORE UPDATE OR DELETE ON grounding_corpus_events FOR EACH ROW EXECUTE FUNCTION enforce_grounding_corpus_event_immutable();
DROP TRIGGER IF EXISTS trg_grounding_active_corpora_guard ON grounding_active_corpora;
CREATE TRIGGER trg_grounding_active_corpora_guard BEFORE INSERT OR UPDATE OR DELETE ON grounding_active_corpora FOR EACH ROW EXECUTE FUNCTION enforce_grounding_corpus_active_pointer();
