-- Child 05 learner-state projections: additive, feature-disabled, and isolated from legacy learner tables.
-- Generic curation outbox/proposal rows remain redacted evidence; final product-domain
-- state is recorded only in the target tables below.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_curation_proposals'::regclass
      AND conname = 'uq_tutor_curation_proposals_id_outbox'
  ) THEN
    ALTER TABLE tutor_curation_proposals
      ADD CONSTRAINT uq_tutor_curation_proposals_id_outbox UNIQUE (id, outbox_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_plan_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  predecessor_revision_id uuid,
  source_run_id uuid,
  source_effect_record_id uuid,
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
  outline_json jsonb NOT NULL,
  diff_json jsonb NOT NULL,
  learner_reason text NOT NULL CHECK (char_length(learner_reason) BETWEEN 1 AND 160),
  evidence_ids_json jsonb NOT NULL,
  evidence_hashes_json jsonb NOT NULL,
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_plan_revisions_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_plan_revision_predecessor_user
    FOREIGN KEY (predecessor_revision_id, user_id)
    REFERENCES tutor_plan_revisions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_plan_revision_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_plan_revision_effect_run
    FOREIGN KEY (source_effect_record_id, source_run_id)
    REFERENCES tutor_effects(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_plan_revision_effect_scope CHECK (
    (source_run_id IS NULL) = (source_effect_record_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_active_plans (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  revision_id uuid NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_active_plan_revision_user
    FOREIGN KEY (revision_id, user_id)
    REFERENCES tutor_plan_revisions(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_plan_revision_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  action text NOT NULL CHECK (action IN ('activate', 'rollback')),
  current_revision_id uuid,
  target_revision_id uuid NOT NULL,
  predecessor_revision_id uuid,
  source_run_id uuid,
  source_effect_record_id uuid,
  learner_reason text NOT NULL CHECK (char_length(learner_reason) BETWEEN 1 AND 160),
  evidence_ids_json jsonb NOT NULL,
  evidence_hashes_json jsonb NOT NULL,
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_plan_action_current_user
    FOREIGN KEY (current_revision_id, user_id)
    REFERENCES tutor_plan_revisions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_plan_action_target_user
    FOREIGN KEY (target_revision_id, user_id)
    REFERENCES tutor_plan_revisions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_plan_action_predecessor_user
    FOREIGN KEY (predecessor_revision_id, user_id)
    REFERENCES tutor_plan_revisions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_plan_action_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_plan_action_effect_run
    FOREIGN KEY (source_effect_record_id, source_run_id)
    REFERENCES tutor_effects(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_plan_action_effect_scope CHECK (
    (source_run_id IS NULL) = (source_effect_record_id IS NULL)
  ),
  CONSTRAINT chk_tutor_plan_action_shape CHECK (
    action = 'activate'
    OR (action = 'rollback' AND current_revision_id IS NOT NULL AND predecessor_revision_id IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_memory_preferences (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  inferred_memory_enabled boolean NOT NULL DEFAULT false,
  setting_version text NOT NULL DEFAULT 'memory_settings_v1' CHECK (char_length(setting_version) <= 160),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_memory_preferences_user_version UNIQUE (user_id, setting_version)
);

CREATE TABLE IF NOT EXISTS tutor_memory_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  memory_kind text NOT NULL CHECK (memory_kind IN ('objective_fact', 'inference')),
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'corrected', 'deleted', 'expired')),
  category text NOT NULL CHECK (char_length(category) BETWEEN 1 AND 120),
  statement text NOT NULL CHECK (char_length(statement) BETWEEN 1 AND 180),
  confidence text CHECK (confidence IS NULL OR confidence IN ('low', 'medium', 'high')),
  provenance_kind text NOT NULL CHECK (provenance_kind IN ('effect', 'curator', 'learner_control', 'trusted_service')),
  source_run_id uuid,
  source_effect_record_id uuid,
  source_outbox_id uuid,
  source_proposal_id uuid,
  replaced_entry_id uuid,
  evidence_ids_json jsonb NOT NULL,
  evidence_hashes_json jsonb NOT NULL,
  policy_version text,
  memory_setting_version text,
  retention_until timestamptz,
  stale_after timestamptz,
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_memory_entries_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_memory_entries_source_proposal UNIQUE (source_proposal_id),
  CONSTRAINT fk_tutor_memory_entry_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_memory_entry_effect_run
    FOREIGN KEY (source_effect_record_id, source_run_id)
    REFERENCES tutor_effects(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_memory_entry_outbox_run
    FOREIGN KEY (source_outbox_id, source_run_id)
    REFERENCES tutor_memory_curation_outbox(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_memory_entry_proposal_outbox
    FOREIGN KEY (source_proposal_id, source_outbox_id)
    REFERENCES tutor_curation_proposals(id, outbox_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_memory_entry_replaced_user
    FOREIGN KEY (replaced_entry_id, user_id)
    REFERENCES tutor_memory_entries(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_memory_entry_deleted CHECK (
    (state = 'deleted') = (deleted_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_memory_entry_provenance CHECK (
    (provenance_kind = 'effect' AND memory_kind = 'objective_fact'
      AND source_run_id IS NOT NULL AND source_effect_record_id IS NOT NULL
      AND source_outbox_id IS NULL AND source_proposal_id IS NULL)
    OR (provenance_kind = 'curator' AND memory_kind = 'inference'
      AND source_run_id IS NOT NULL AND source_effect_record_id IS NULL
      AND source_outbox_id IS NOT NULL AND source_proposal_id IS NOT NULL)
    OR (provenance_kind IN ('learner_control', 'trusted_service')
      AND memory_kind = 'objective_fact' AND source_run_id IS NULL
      AND source_effect_record_id IS NULL AND source_outbox_id IS NULL AND source_proposal_id IS NULL)
  ),
  CONSTRAINT chk_tutor_memory_entry_inference_metadata CHECK (
    (memory_kind = 'inference' AND confidence IS NOT NULL
      AND policy_version IS NOT NULL AND memory_setting_version IS NOT NULL
      AND retention_until IS NOT NULL AND stale_after IS NOT NULL
      AND stale_after <= retention_until)
    OR (memory_kind = 'objective_fact' AND confidence IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_context_summaries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL,
  conversation_id uuid,
  outbox_id uuid NOT NULL,
  proposal_id uuid NOT NULL,
  summary text NOT NULL CHECK (char_length(summary) BETWEEN 1 AND 280),
  summary_schema_version text,
  summary_policy_version text,
  summary_json jsonb,
  covered_through_created_at timestamptz,
  covered_through_message_id uuid,
  source_hash text,
  prior_summary_id uuid,
  prior_summary_hash text,
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  memory_setting_version text NOT NULL CHECK (char_length(memory_setting_version) <= 160),
  retention_until timestamptz NOT NULL,
  stale_after timestamptz NOT NULL,
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_context_summary_outbox UNIQUE (outbox_id),
  CONSTRAINT uq_tutor_context_summary_proposal UNIQUE (proposal_id),
  CONSTRAINT uq_tutor_context_summary_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_context_summary_run_user
    FOREIGN KEY (run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_outbox_run
    FOREIGN KEY (outbox_id, run_id)
    REFERENCES tutor_memory_curation_outbox(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_outbox_conversation
    FOREIGN KEY (outbox_id, conversation_id)
    REFERENCES tutor_memory_curation_outbox(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_proposal_outbox
    FOREIGN KEY (proposal_id, outbox_id)
    REFERENCES tutor_curation_proposals(id, outbox_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_covered_message
    FOREIGN KEY (covered_through_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_prior_scope
    FOREIGN KEY (prior_summary_id, user_id, conversation_id)
    REFERENCES tutor_context_summaries(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_context_summary_v2_shape CHECK (
    (summary_schema_version IS NULL
      AND summary_policy_version IS NULL
      AND summary_json IS NULL
      AND covered_through_created_at IS NULL
      AND covered_through_message_id IS NULL
      AND source_hash IS NULL
      AND prior_summary_id IS NULL
      AND prior_summary_hash IS NULL
      AND conversation_id IS NULL)
    OR (summary_schema_version = 'tutor_context_summary_v2'
      AND summary_policy_version = 'tutor_context_summary_policy_v2'
      AND summary_json IS NOT NULL
      AND jsonb_typeof(summary_json) = 'object'
      AND conversation_id IS NOT NULL
      AND covered_through_created_at IS NOT NULL
      AND covered_through_message_id IS NOT NULL
      AND source_hash ~ '^[0-9a-f]{64}$'
      AND (prior_summary_hash IS NULL OR prior_summary_hash ~ '^[0-9a-f]{64}$')
      AND ((prior_summary_id IS NULL) = (prior_summary_hash IS NULL)))
  ),
  CONSTRAINT chk_tutor_context_summary_retention CHECK (stale_after <= retention_until)
);

ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS conversation_id uuid;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS summary_schema_version text;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS summary_policy_version text;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS summary_json jsonb;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS covered_through_created_at timestamptz;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS covered_through_message_id uuid;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS source_hash text;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS prior_summary_id uuid;
ALTER TABLE tutor_context_summaries
  ADD COLUMN IF NOT EXISTS prior_summary_hash text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_memory_curation_outbox'::regclass
      AND conname = 'chk_tutor_outbox_summary_evidence'
  ) THEN
    ALTER TABLE tutor_memory_curation_outbox
      ADD CONSTRAINT chk_tutor_outbox_summary_evidence CHECK (
        (projection_kind = 'memory_or_summary'
          AND summary_schema_version IS NULL
          AND summary_policy_version IS NULL
          AND summary_source_hash IS NULL
          AND prior_summary_id IS NULL
          AND prior_summary_hash IS NULL
          AND covered_through_created_at IS NULL
          AND covered_through_message_id IS NULL)
        OR (projection_kind = 'context_summary'
          AND summary_schema_version = 'tutor_context_summary_v2'
          AND summary_policy_version = 'tutor_context_summary_policy_v2'
          AND summary_source_hash ~ '^[0-9a-f]{64}$'
          AND (prior_summary_hash IS NULL OR prior_summary_hash ~ '^[0-9a-f]{64}$')
          AND jsonb_typeof(source_ids_json) = 'array'
          AND jsonb_array_length(source_ids_json) > 0
          AND jsonb_typeof(source_hashes_json) = 'array'
          AND jsonb_array_length(source_hashes_json) = jsonb_array_length(source_ids_json)
          AND covered_through_created_at IS NOT NULL
          AND covered_through_message_id IS NOT NULL
          AND ((prior_summary_id IS NULL) = (prior_summary_hash IS NULL)))
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_context_summaries'::regclass
      AND conname = 'chk_tutor_context_summary_v2_shape'
  ) THEN
    ALTER TABLE tutor_context_summaries
      ADD CONSTRAINT chk_tutor_context_summary_v2_shape CHECK (
        (summary_schema_version IS NULL
          AND summary_policy_version IS NULL
          AND summary_json IS NULL
          AND covered_through_created_at IS NULL
          AND covered_through_message_id IS NULL
          AND source_hash IS NULL
          AND prior_summary_id IS NULL
          AND prior_summary_hash IS NULL
          AND conversation_id IS NULL)
        OR (summary_schema_version = 'tutor_context_summary_v2'
          AND summary_policy_version = 'tutor_context_summary_policy_v2'
          AND summary_json IS NOT NULL
          AND jsonb_typeof(summary_json) = 'object'
          AND conversation_id IS NOT NULL
          AND covered_through_created_at IS NOT NULL
          AND covered_through_message_id IS NOT NULL
          AND source_hash ~ '^[0-9a-f]{64}$'
          AND (prior_summary_hash IS NULL OR prior_summary_hash ~ '^[0-9a-f]{64}$')
          AND ((prior_summary_id IS NULL) = (prior_summary_hash IS NULL)))
      );
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_memory_curation_outbox'::regclass
      AND conname = 'uq_tutor_outbox_id_conversation'
  ) THEN
    ALTER TABLE tutor_memory_curation_outbox
      ADD CONSTRAINT uq_tutor_outbox_id_conversation UNIQUE (id, conversation_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_context_summaries'::regclass
      AND conname = 'uq_tutor_context_summary_id_scope'
  ) THEN
    ALTER TABLE tutor_context_summaries
      ADD CONSTRAINT uq_tutor_context_summary_id_scope UNIQUE (id, user_id, conversation_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_curation_projection_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL,
  outbox_id uuid NOT NULL,
  proposal_id uuid NOT NULL,
  state text NOT NULL CHECK (state IN ('committed', 'no_action', 'stale', 'failed')),
  target_kind text NOT NULL CHECK (target_kind IN ('context_summary', 'memory_entry', 'none')),
  target_id uuid,
  code text NOT NULL CHECK (char_length(code) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_curation_projection_receipt_proposal UNIQUE (proposal_id),
  CONSTRAINT fk_tutor_curation_receipt_run_user
    FOREIGN KEY (run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_curation_receipt_outbox_run
    FOREIGN KEY (outbox_id, run_id)
    REFERENCES tutor_memory_curation_outbox(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_curation_receipt_proposal_outbox
    FOREIGN KEY (proposal_id, outbox_id)
    REFERENCES tutor_curation_proposals(id, outbox_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_curation_receipt_target CHECK (
    (state = 'committed' AND target_kind <> 'none' AND target_id IS NOT NULL)
    OR (state <> 'committed' AND target_kind = 'none' AND target_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_activity_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  source_run_id uuid,
  source_effect_record_id uuid,
  category text NOT NULL CHECK (char_length(category) BETWEEN 1 AND 120),
  learner_reason text NOT NULL CHECK (char_length(learner_reason) BETWEEN 1 AND 160),
  evidence_ids_json jsonb NOT NULL,
  evidence_hashes_json jsonb NOT NULL,
  policy_version text,
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_activity_records_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_activity_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_activity_effect_run
    FOREIGN KEY (source_effect_record_id, source_run_id)
    REFERENCES tutor_effects(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_activity_effect_scope CHECK (
    (source_run_id IS NULL) = (source_effect_record_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_inbox_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  activity_id uuid NOT NULL,
  message text NOT NULL CHECK (char_length(message) BETWEEN 1 AND 160),
  state text NOT NULL DEFAULT 'unread' CHECK (state IN ('unread', 'read', 'dismissed')),
  read_at timestamptz,
  dismissed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_inbox_items_activity UNIQUE (activity_id),
  CONSTRAINT fk_tutor_inbox_activity_user
    FOREIGN KEY (activity_id, user_id)
    REFERENCES tutor_activity_records(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_inbox_lifecycle CHECK (
    (state = 'unread' AND read_at IS NULL AND dismissed_at IS NULL)
    OR (state = 'read' AND read_at IS NOT NULL AND dismissed_at IS NULL)
    OR (state = 'dismissed' AND dismissed_at IS NOT NULL)
  )
);

-- Child 06 public adapter idempotency.  This table stores only a request hash
-- and learner-safe response projection; it is never a raw Tutor message store.
CREATE TABLE IF NOT EXISTS tutor_api_idempotency_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  operation text NOT NULL CHECK (char_length(operation) BETWEEN 1 AND 120),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  response_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_api_idempotency_user_operation_key UNIQUE (user_id, operation, idempotency_key)
);

-- Child 07 cutover receipt. This is intentionally separate from ordinary
-- local-user reset records: it holds only a safe summary fingerprint and the
-- one-time gate state, never legacy learner content or target Tutor state.
CREATE TABLE IF NOT EXISTS harness_cutovers (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  cutover_version text NOT NULL CHECK (char_length(cutover_version) BETWEEN 1 AND 120),
  state text NOT NULL DEFAULT 'required' CHECK (state IN (
    'required', 'summary_ready', 'verified', 'verification_failed',
    'blocked_target_state', 'blocked_checkpoint_scope'
  )),
  summary_hash text CHECK (summary_hash IS NULL OR summary_hash ~ '^[0-9a-f]{64}$'),
  preview_nonce text CHECK (preview_nonce IS NULL OR char_length(preview_nonce) BETWEEN 1 AND 160),
  summary_version integer NOT NULL DEFAULT 0 CHECK (summary_version >= 0),
  confirmation_idempotency_key text CHECK (
    confirmation_idempotency_key IS NULL
    OR char_length(confirmation_idempotency_key) BETWEEN 1 AND 160
  ),
  confirmation_request_hash text CHECK (
    confirmation_request_hash IS NULL
    OR confirmation_request_hash ~ '^[0-9a-f]{64}$'
  ),
  confirmed_at timestamptz,
  verified_at timestamptz,
  failure_code text CHECK (failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 160),
  failure_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, cutover_version)
);

CREATE INDEX IF NOT EXISTS idx_harness_cutovers_state_updated
  ON harness_cutovers (state, updated_at DESC);

DROP TRIGGER IF EXISTS trg_harness_cutovers_updated_at ON harness_cutovers;
CREATE TRIGGER trg_harness_cutovers_updated_at BEFORE UPDATE ON harness_cutovers
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_tutor_plan_revisions_user_created
  ON tutor_plan_revisions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_plan_actions_user_created
  ON tutor_plan_revision_actions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_memory_entries_user_state
  ON tutor_memory_entries (user_id, state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_memory_entries_inference_stale
  ON tutor_memory_entries (user_id, stale_after) WHERE memory_kind = 'inference' AND state = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_context_summaries_user_created
  ON tutor_context_summaries (user_id, created_at DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_memory_curation_outbox'::regclass
      AND conname = 'fk_tutor_outbox_covered_message'
  ) THEN
    ALTER TABLE tutor_memory_curation_outbox
      ADD CONSTRAINT fk_tutor_outbox_covered_message
      FOREIGN KEY (covered_through_message_id, conversation_id)
      REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_context_summaries'::regclass
      AND conname = 'fk_tutor_context_summary_conversation_user'
  ) THEN
    ALTER TABLE tutor_context_summaries
      ADD CONSTRAINT fk_tutor_context_summary_conversation_user
      FOREIGN KEY (conversation_id, user_id)
      REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_context_summaries'::regclass
      AND conname = 'fk_tutor_context_summary_outbox_conversation'
  ) THEN
    ALTER TABLE tutor_context_summaries
      ADD CONSTRAINT fk_tutor_context_summary_outbox_conversation
      FOREIGN KEY (outbox_id, conversation_id)
      REFERENCES tutor_memory_curation_outbox(id, conversation_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_context_summaries'::regclass
      AND conname = 'fk_tutor_context_summary_covered_message'
  ) THEN
    ALTER TABLE tutor_context_summaries
      ADD CONSTRAINT fk_tutor_context_summary_covered_message
      FOREIGN KEY (covered_through_message_id, conversation_id)
      REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_context_summaries'::regclass
      AND conname = 'fk_tutor_context_summary_prior_scope'
  ) THEN
    ALTER TABLE tutor_context_summaries
      ADD CONSTRAINT fk_tutor_context_summary_prior_scope
      FOREIGN KEY (prior_summary_id, user_id, conversation_id)
      REFERENCES tutor_context_summaries(id, user_id, conversation_id) ON DELETE RESTRICT;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tutor_context_summaries_conversation_coverage
  ON tutor_context_summaries (
    user_id, conversation_id, covered_through_created_at DESC, covered_through_message_id DESC
  );
CREATE INDEX IF NOT EXISTS idx_tutor_curation_projection_receipts_user_created
  ON tutor_curation_projection_receipts (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_activity_records_user_created
  ON tutor_activity_records (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_inbox_items_user_state
  ON tutor_inbox_items (user_id, state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_api_idempotency_user_created
  ON tutor_api_idempotency_records (user_id, created_at DESC);

CREATE OR REPLACE FUNCTION enforce_tutor_plan_revision_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor plan revisions are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_plan_action_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor plan revision actions are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_memory_entry_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF OLD.memory_kind IS DISTINCT FROM NEW.memory_kind
       OR OLD.category IS DISTINCT FROM NEW.category
       OR OLD.statement IS DISTINCT FROM NEW.statement
       OR OLD.confidence IS DISTINCT FROM NEW.confidence
       OR OLD.provenance_kind IS DISTINCT FROM NEW.provenance_kind
       OR OLD.source_run_id IS DISTINCT FROM NEW.source_run_id
       OR OLD.source_effect_record_id IS DISTINCT FROM NEW.source_effect_record_id
       OR OLD.source_outbox_id IS DISTINCT FROM NEW.source_outbox_id
       OR OLD.source_proposal_id IS DISTINCT FROM NEW.source_proposal_id
       OR OLD.replaced_entry_id IS DISTINCT FROM NEW.replaced_entry_id
       OR OLD.evidence_ids_json IS DISTINCT FROM NEW.evidence_ids_json
       OR OLD.evidence_hashes_json IS DISTINCT FROM NEW.evidence_hashes_json
       OR OLD.policy_version IS DISTINCT FROM NEW.policy_version
       OR OLD.memory_setting_version IS DISTINCT FROM NEW.memory_setting_version
       OR OLD.retention_until IS DISTINCT FROM NEW.retention_until
       OR OLD.stale_after IS DISTINCT FROM NEW.stale_after
       OR OLD.content_hash IS DISTINCT FROM NEW.content_hash THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor memory evidence is immutable';
    END IF;
    IF OLD.state <> 'active' OR NEW.state NOT IN ('corrected', 'deleted', 'expired') THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor memory lifecycle transition is invalid';
    END IF;
  ELSIF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor memory entries are not deleted physically';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_context_summary_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor context summaries are append-only';
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION enforce_tutor_activity_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor activity records are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_inbox_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF OLD.user_id IS DISTINCT FROM NEW.user_id
       OR OLD.activity_id IS DISTINCT FROM NEW.activity_id
       OR OLD.message IS DISTINCT FROM NEW.message
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor inbox identity is immutable';
    END IF;
    IF OLD.state <> 'unread' OR NEW.state NOT IN ('read', 'dismissed') THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor inbox lifecycle transition is invalid';
    END IF;
  ELSIF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Tutor inbox items are not deleted physically';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_plan_revisions_immutable ON tutor_plan_revisions;
CREATE TRIGGER trg_tutor_plan_revisions_immutable
BEFORE UPDATE OR DELETE ON tutor_plan_revisions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_plan_revision_immutable();

DROP TRIGGER IF EXISTS trg_tutor_plan_actions_immutable ON tutor_plan_revision_actions;
CREATE TRIGGER trg_tutor_plan_actions_immutable
BEFORE UPDATE OR DELETE ON tutor_plan_revision_actions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_plan_action_immutable();

DROP TRIGGER IF EXISTS trg_tutor_memory_entries_lifecycle ON tutor_memory_entries;
CREATE TRIGGER trg_tutor_memory_entries_lifecycle
BEFORE UPDATE OR DELETE ON tutor_memory_entries
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_memory_entry_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_context_summaries_immutable ON tutor_context_summaries;
CREATE TRIGGER trg_tutor_context_summaries_immutable
BEFORE UPDATE ON tutor_context_summaries
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_context_summary_immutable();
DROP TRIGGER IF EXISTS trg_tutor_activity_records_immutable ON tutor_activity_records;
CREATE TRIGGER trg_tutor_activity_records_immutable
BEFORE UPDATE OR DELETE ON tutor_activity_records
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_activity_immutable();

DROP TRIGGER IF EXISTS trg_tutor_inbox_items_lifecycle ON tutor_inbox_items;
CREATE TRIGGER trg_tutor_inbox_items_lifecycle
BEFORE UPDATE OR DELETE ON tutor_inbox_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_inbox_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_active_plans_updated_at ON tutor_active_plans;
CREATE TRIGGER trg_tutor_active_plans_updated_at BEFORE UPDATE ON tutor_active_plans
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_memory_preferences_updated_at ON tutor_memory_preferences;
CREATE TRIGGER trg_tutor_memory_preferences_updated_at BEFORE UPDATE ON tutor_memory_preferences
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_memory_entries_updated_at ON tutor_memory_entries;
CREATE TRIGGER trg_tutor_memory_entries_updated_at BEFORE UPDATE ON tutor_memory_entries
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_inbox_items_updated_at ON tutor_inbox_items;
CREATE TRIGGER trg_tutor_inbox_items_updated_at BEFORE UPDATE ON tutor_inbox_items
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
