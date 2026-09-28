-- D-only private semantic review audit. A model verdict never authorizes C evidence.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_d_selection_handle_digest
  ON rag_material_selections(handle,selection_digest);
CREATE TABLE IF NOT EXISTS rag_material_semantic_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL,
  run_id uuid NOT NULL,
  input_revision integer NOT NULL CHECK (input_revision >= 1),
  decision_iteration integer NOT NULL CHECK (decision_iteration >= 1),
  attempt_index integer NOT NULL CHECK (attempt_index BETWEEN 1 AND 2),
  selection_handle text NOT NULL,
  selection_digest text NOT NULL CHECK (selection_digest ~ '^[0-9a-f]{64}$'),
  parent_content_hash text NOT NULL CHECK (parent_content_hash ~ '^[0-9a-f]{64}$'),
  candidate_digest text NOT NULL CHECK (candidate_digest ~ '^[0-9a-f]{64}$'),
  authority_hash text NOT NULL CHECK (authority_hash ~ '^[0-9a-f]{64}$'),
  candidate_hash text NOT NULL CHECK (candidate_hash ~ '^[0-9a-f]{64}$'),
  request_binding_hash text NOT NULL CHECK (request_binding_hash ~ '^[0-9a-f]{64}$'),
  review_status text NOT NULL DEFAULT 'settled' CHECK (review_status IN ('dispatched','settled')),
  verdict text NOT NULL CHECK (verdict IN ('consistent','inconsistent','uncertain')),
  reason_code text NOT NULL CHECK (reason_code IN (
    'supported','facet_meaning_mismatch','readiness_overclaim','other_contradiction',
    'insufficient_context','provider_unavailable','invalid_response','request_binding_invalid'
  )),
  reviewer_model text CHECK (reviewer_model IS NULL OR char_length(reviewer_model) <= 120),
  usage_json jsonb CHECK (usage_json IS NULL OR jsonb_typeof(usage_json) = 'object'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_rag_d_semantic_attempt UNIQUE (run_id,input_revision,decision_iteration,attempt_index),
  CONSTRAINT fk_rag_d_semantic_run_user FOREIGN KEY (run_id,user_id)
    REFERENCES tutor_runs(id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_rag_d_semantic_run_conversation FOREIGN KEY (run_id,conversation_id)
    REFERENCES tutor_runs(id,conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_rag_d_semantic_selection FOREIGN KEY (selection_handle,selection_digest)
    REFERENCES rag_material_selections(handle,selection_digest) ON DELETE RESTRICT
);
ALTER TABLE rag_material_semantic_reviews ADD COLUMN IF NOT EXISTS authority_hash text;
ALTER TABLE rag_material_semantic_reviews ADD COLUMN IF NOT EXISTS candidate_hash text;
ALTER TABLE rag_material_semantic_reviews ALTER COLUMN authority_hash SET NOT NULL;
ALTER TABLE rag_material_semantic_reviews ALTER COLUMN candidate_hash SET NOT NULL;
ALTER TABLE rag_material_semantic_reviews ADD COLUMN IF NOT EXISTS review_status text NOT NULL DEFAULT 'settled';
-- An earlier review can be rejected by stream validation; only a provider-accepted
-- attempt may authorize append, so multiple consistent audits are permitted.
DROP INDEX IF EXISTS uq_rag_d_semantic_accepted;
CREATE INDEX IF NOT EXISTS idx_rag_d_semantic_user
  ON rag_material_semantic_reviews(user_id,run_id,input_revision);

CREATE OR REPLACE FUNCTION enforce_rag_d_semantic_append_only() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  IF TG_OP = 'UPDATE' AND OLD.review_status = 'dispatched' AND NEW.review_status = 'settled'
     AND (NEW.id,NEW.user_id,NEW.conversation_id,NEW.run_id,NEW.input_revision,
          NEW.decision_iteration,NEW.attempt_index,NEW.selection_handle,NEW.selection_digest,
          NEW.parent_content_hash,NEW.candidate_digest,NEW.authority_hash,NEW.candidate_hash,
          NEW.request_binding_hash,NEW.created_at)
         IS NOT DISTINCT FROM
         (OLD.id,OLD.user_id,OLD.conversation_id,OLD.run_id,OLD.input_revision,
          OLD.decision_iteration,OLD.attempt_index,OLD.selection_handle,OLD.selection_digest,
          OLD.parent_content_hash,OLD.candidate_digest,OLD.authority_hash,OLD.candidate_hash,
          OLD.request_binding_hash,OLD.created_at)
     THEN RETURN NEW;
  END IF;
  RAISE EXCEPTION 'RAG D semantic receipt is immutable after settlement' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_rag_d_semantic_append_only ON rag_material_semantic_reviews;
CREATE TRIGGER trg_rag_d_semantic_append_only
BEFORE UPDATE OR DELETE ON rag_material_semantic_reviews
FOR EACH ROW EXECUTE FUNCTION enforce_rag_d_semantic_append_only();
