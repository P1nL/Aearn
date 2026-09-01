-- Child 11 Learning Item Bank shared authority: immutable Git-owned content,
-- deterministic import receipts, append-only publication history, and safe candidate lookup.

CREATE TABLE IF NOT EXISTS tutor_learning_item_blueprints (
  id uuid PRIMARY KEY,
  blueprint_key text NOT NULL CHECK (blueprint_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  item_kind text NOT NULL CHECK (item_kind IN ('code','sql','demo','knowledge_check','model_review')),
  purpose text NOT NULL CHECK (purpose IN ('exercise','demonstration','knowledge_check','remediation','transfer_check','code_review','sql_exploration')),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  difficulty text NOT NULL CHECK (difficulty IN ('D1','D2','D3','D4','D5')),
  risk_tier text NOT NULL CHECK (risk_tier IN ('low','medium','high')),
  runtime_profile_key text CHECK (runtime_profile_key IS NULL OR runtime_profile_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  required_capabilities_json jsonb NOT NULL CHECK (
    jsonb_typeof(required_capabilities_json)='array'
    AND jsonb_array_length(required_capabilities_json) BETWEEN 1 AND 24
    AND octet_length(required_capabilities_json::text) <= 8192
  ),
  blueprint_json jsonb NOT NULL CHECK (jsonb_typeof(blueprint_json)='object' AND octet_length(blueprint_json::text) <= 65536),
  blueprint_hash text NOT NULL CHECK (blueprint_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_item_blueprints_identity UNIQUE (blueprint_key, version),
  CONSTRAINT uq_tutor_learning_item_blueprints_hash_scope UNIQUE (id, blueprint_hash),
  CONSTRAINT chk_tutor_learning_item_blueprints_runtime CHECK (
    (item_kind IN ('code','sql','demo') AND runtime_profile_key IS NOT NULL)
    OR (item_kind IN ('knowledge_check','model_review') AND runtime_profile_key IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_learning_items (
  id uuid PRIMARY KEY,
  item_key text NOT NULL UNIQUE CHECK (item_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  item_kind text NOT NULL CHECK (item_kind IN ('code','sql','demo','knowledge_check','model_review')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_items_scope UNIQUE (id, item_key, item_kind)
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_versions (
  id uuid PRIMARY KEY,
  item_id uuid NOT NULL,
  blueprint_id uuid NOT NULL,
  item_key text NOT NULL CHECK (item_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  item_kind text NOT NULL CHECK (item_kind IN ('code','sql','demo','knowledge_check','model_review')),
  purpose text NOT NULL CHECK (purpose IN ('exercise','demonstration','knowledge_check','remediation','transfer_check','code_review','sql_exploration')),
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  difficulty text NOT NULL CHECK (difficulty IN ('D1','D2','D3','D4','D5')),
  risk_tier text NOT NULL CHECK (risk_tier IN ('low','medium','high')),
  runtime_profile_key text CHECK (runtime_profile_key IS NULL OR runtime_profile_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  required_capabilities_json jsonb NOT NULL CHECK (
    jsonb_typeof(required_capabilities_json)='array'
    AND jsonb_array_length(required_capabilities_json) BETWEEN 1 AND 24
    AND octet_length(required_capabilities_json::text) <= 8192
  ),
  source_schema_version text NOT NULL CHECK (source_schema_version='learning_item_source_v1'),
  compiler_version text NOT NULL CHECK (compiler_version='learning_item_compiler_v1'),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  blueprint_hash text NOT NULL CHECK (blueprint_hash ~ '^[0-9a-f]{64}$'),
  public_hash text NOT NULL CHECK (public_hash ~ '^[0-9a-f]{64}$'),
  private_hash text NOT NULL CHECK (private_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  handle text NOT NULL UNIQUE CHECK (handle ~ '^li:[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_item_versions_identity UNIQUE (item_key, version),
  CONSTRAINT uq_tutor_learning_item_versions_handle_scope UNIQUE (id, handle, content_hash),
  CONSTRAINT uq_tutor_learning_item_versions_public_scope UNIQUE (id, public_hash),
  CONSTRAINT uq_tutor_learning_item_versions_private_scope UNIQUE (id, private_hash),
  CONSTRAINT fk_tutor_learning_item_versions_item FOREIGN KEY (item_id,item_key,item_kind)
    REFERENCES tutor_learning_items(id,item_key,item_kind) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_versions_blueprint FOREIGN KEY (blueprint_id,blueprint_hash)
    REFERENCES tutor_learning_item_blueprints(id,blueprint_hash) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_learning_item_versions_runtime CHECK (
    (item_kind IN ('code','sql','demo') AND runtime_profile_key IS NOT NULL)
    OR (item_kind IN ('knowledge_check','model_review') AND runtime_profile_key IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_public_contents (
  version_id uuid PRIMARY KEY,
  schema_version text NOT NULL CHECK (schema_version='learning_item_public_v1'),
  public_json jsonb NOT NULL CHECK (jsonb_typeof(public_json)='object' AND octet_length(public_json::text) <= 131072),
  public_hash text NOT NULL CHECK (public_hash ~ '^[0-9a-f]{64}$'),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  candidate_summary text NOT NULL CHECK (char_length(candidate_summary) BETWEEN 1 AND 480),
  allowed_interactions_json jsonb NOT NULL CHECK (
    jsonb_typeof(allowed_interactions_json)='array' AND jsonb_array_length(allowed_interactions_json) BETWEEN 1 AND 6
  ),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_learning_item_public_hash FOREIGN KEY (version_id,public_hash)
    REFERENCES tutor_learning_item_versions(id,public_hash) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_private_contents (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL UNIQUE,
  schema_version text NOT NULL CHECK (schema_version='learning_item_private_v1'),
  private_json jsonb NOT NULL CHECK (jsonb_typeof(private_json)='object' AND octet_length(private_json::text) <= 262144),
  private_hash text NOT NULL CHECK (private_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_learning_item_private_hash FOREIGN KEY (version_id,private_hash)
    REFERENCES tutor_learning_item_versions(id,private_hash) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_validation_receipts (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL,
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  policy_version text NOT NULL CHECK (policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  compiler_version text NOT NULL CHECK (compiler_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  receipt_json jsonb NOT NULL CHECK (jsonb_typeof(receipt_json)='object' AND octet_length(receipt_json::text) <= 65536),
  receipt_hash text NOT NULL UNIQUE CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  passed boolean NOT NULL CHECK (passed),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_item_validation_policy UNIQUE (version_id,policy_version,compiler_version),
  CONSTRAINT uq_tutor_learning_item_validation_scope UNIQUE (id,version_id),
  CONSTRAINT fk_tutor_learning_item_validation_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_publication_events (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL,
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  predecessor_event_id uuid,
  state_version integer NOT NULL CHECK (state_version >= 1),
  state text NOT NULL CHECK (state IN ('machine_verified','agent_reviewed','pilot','published','quarantined','retired')),
  transition_key text NOT NULL CHECK (transition_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  authority_kind text NOT NULL CHECK (authority_kind IN ('validation','agent_review','pilot','human_approval','operator')),
  authority_hash text NOT NULL CHECK (authority_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL CHECK (policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  reason_code text CHECK (reason_code IS NULL OR reason_code ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_item_publication_version UNIQUE (version_id,state_version),
  CONSTRAINT uq_tutor_learning_item_publication_transition UNIQUE (version_id,transition_key),
  CONSTRAINT uq_tutor_learning_item_publication_scope UNIQUE (id,version_id),
  CONSTRAINT fk_tutor_learning_item_publication_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_publication_predecessor FOREIGN KEY (predecessor_event_id,version_id)
    REFERENCES tutor_learning_item_publication_events(id,version_id) ON DELETE NO ACTION DEFERRABLE INITIALLY IMMEDIATE,
  CONSTRAINT chk_tutor_learning_item_publication_reason CHECK ((state IN ('quarantined','retired')) = (reason_code IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_import_receipts (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL,
  validation_receipt_id uuid NOT NULL,
  initial_publication_event_id uuid NOT NULL,
  import_key text NOT NULL UNIQUE CHECK (import_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_path text NOT NULL CHECK (char_length(source_path) BETWEEN 1 AND 320),
  source_file_hash text NOT NULL CHECK (source_file_hash ~ '^[0-9a-f]{64}$'),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  importer_version text NOT NULL CHECK (importer_version='learning_item_repository_v1'),
  imported_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_learning_item_import_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_import_validation FOREIGN KEY (validation_receipt_id,version_id)
    REFERENCES tutor_learning_item_validation_receipts(id,version_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_import_publication FOREIGN KEY (initial_publication_event_id,version_id)
    REFERENCES tutor_learning_item_publication_events(id,version_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_tutor_learning_item_versions_candidate
  ON tutor_learning_item_versions(knowledge_key,purpose,difficulty,item_key,version);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_item_versions_capabilities
  ON tutor_learning_item_versions USING gin(required_capabilities_json);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_item_publication_current
  ON tutor_learning_item_publication_events(version_id,state_version DESC);

CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_bank_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Learning Item Bank authority rows are immutable or append-only' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_publication_insert()
RETURNS trigger AS $$
DECLARE current_event tutor_learning_item_publication_events%ROWTYPE;
BEGIN
  PERFORM 1 FROM tutor_learning_item_versions WHERE id=NEW.version_id FOR UPDATE;
  SELECT * INTO current_event FROM tutor_learning_item_publication_events
  WHERE version_id=NEW.version_id ORDER BY state_version DESC LIMIT 1;
  IF current_event.id IS NULL THEN
    IF NEW.state_version<>1 OR NEW.predecessor_event_id IS NOT NULL OR NEW.state<>'machine_verified' OR NEW.authority_kind<>'validation' THEN
      RAISE EXCEPTION 'Learning Item publication must begin with validated machine state' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.predecessor_event_id IS DISTINCT FROM current_event.id OR NEW.state_version<>current_event.state_version+1 THEN
    RAISE EXCEPTION 'Learning Item publication lineage is stale or forked' USING ERRCODE='23514';
  END IF;
  IF current_event.state='retired' OR current_event.state=NEW.state THEN
    RAISE EXCEPTION 'Learning Item publication state cannot advance' USING ERRCODE='23514';
  END IF;
  IF (current_event.state='machine_verified' AND NEW.state IN ('agent_reviewed','pilot','published','quarantined','retired'))
     OR (current_event.state='agent_reviewed' AND NEW.state IN ('pilot','published','quarantined','retired'))
     OR (current_event.state='pilot' AND NEW.state IN ('published','quarantined','retired'))
     OR (current_event.state='published' AND NEW.state IN ('quarantined','retired'))
     OR (current_event.state='quarantined' AND NEW.state IN ('pilot','published','retired')) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Learning Item publication transition is invalid' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_learning_item_blueprints_immutable ON tutor_learning_item_blueprints;
CREATE TRIGGER trg_tutor_learning_item_blueprints_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_blueprints FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
DROP TRIGGER IF EXISTS trg_tutor_learning_items_immutable ON tutor_learning_items;
CREATE TRIGGER trg_tutor_learning_items_immutable BEFORE UPDATE OR DELETE ON tutor_learning_items FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_versions_immutable ON tutor_learning_item_versions;
CREATE TRIGGER trg_tutor_learning_item_versions_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_versions FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_public_contents_immutable ON tutor_learning_item_public_contents;
CREATE TRIGGER trg_tutor_learning_item_public_contents_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_public_contents FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_private_contents_immutable ON tutor_learning_item_private_contents;
CREATE TRIGGER trg_tutor_learning_item_private_contents_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_private_contents FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_validation_receipts_immutable ON tutor_learning_item_validation_receipts;
CREATE TRIGGER trg_tutor_learning_item_validation_receipts_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_validation_receipts FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_publication_events_lineage ON tutor_learning_item_publication_events;
CREATE TRIGGER trg_tutor_learning_item_publication_events_lineage BEFORE INSERT ON tutor_learning_item_publication_events FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_publication_insert();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_publication_events_immutable ON tutor_learning_item_publication_events;
CREATE TRIGGER trg_tutor_learning_item_publication_events_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_publication_events FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_import_receipts_immutable ON tutor_learning_item_import_receipts;
CREATE TRIGGER trg_tutor_learning_item_import_receipts_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_import_receipts FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();
