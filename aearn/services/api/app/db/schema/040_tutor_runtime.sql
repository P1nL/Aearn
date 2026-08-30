-- Tutor Harness target persistence (Child 02): additive and feature-off.
-- These tables are never read by legacy routes, Graphs, SSE, desktop, or workers.
CREATE TABLE IF NOT EXISTS tutor_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'cancelled')),
  visibility text NOT NULL DEFAULT 'learner',
  kind text NOT NULL DEFAULT 'interactive',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversations_id_user UNIQUE (id, user_id),
  CONSTRAINT chk_tutor_conversations_visibility_kind CHECK (
    (visibility = 'learner' AND kind = 'interactive')
    OR (visibility = 'internal' AND kind = 'proactive')
  )
);

CREATE TABLE IF NOT EXISTS tutor_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('learner', 'tutor')),
  content text NOT NULL,
  public_thinking_text text NOT NULL DEFAULT ''
    CONSTRAINT chk_tutor_messages_public_thinking_text
    CHECK (char_length(public_thinking_text) <= 1280),
  public_thinking_steps_json jsonb NOT NULL DEFAULT '[]'::jsonb
    CONSTRAINT chk_tutor_messages_public_thinking_steps
    CHECK (jsonb_typeof(public_thinking_steps_json) = 'array'
      AND jsonb_array_length(public_thinking_steps_json) <= 4),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT chk_tutor_messages_public_thinking_single_representation CHECK (
    public_thinking_text = '' OR jsonb_array_length(public_thinking_steps_json) = 0
  ),
  CONSTRAINT uq_tutor_messages_id_conversation UNIQUE (id, conversation_id)
);

ALTER TABLE tutor_messages
  ADD COLUMN IF NOT EXISTS public_thinking_steps_json jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE tutor_messages
  ADD COLUMN IF NOT EXISTS public_thinking_text text NOT NULL DEFAULT '';
ALTER TABLE tutor_messages
  DROP CONSTRAINT IF EXISTS chk_tutor_messages_public_thinking_text;
ALTER TABLE tutor_messages
  ADD CONSTRAINT chk_tutor_messages_public_thinking_text
  CHECK (char_length(public_thinking_text) <= 1280);
ALTER TABLE tutor_messages
  DROP CONSTRAINT IF EXISTS chk_tutor_messages_public_thinking_single_representation;
ALTER TABLE tutor_messages
  ADD CONSTRAINT chk_tutor_messages_public_thinking_single_representation CHECK (
    public_thinking_text = '' OR jsonb_array_length(public_thinking_steps_json) = 0
  );

CREATE TABLE IF NOT EXISTS tutor_catalog_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  manifest_json jsonb NOT NULL,
  redaction_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  origin text NOT NULL CHECK (origin IN ('interactive', 'proactive')),
  status text NOT NULL CHECK (status IN (
    'queued', 'leased', 'running', 'waiting_for_input', 'waiting_for_capability',
    'awaiting_effect_commit', 'completed', 'model_unavailable', 'blocked_policy',
    'budget_exhausted', 'cancelled', 'failed'
  )),
  policy_json jsonb NOT NULL,
  policy_version text NOT NULL,
  policy_fingerprint text NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  catalog_digest text NOT NULL REFERENCES tutor_catalog_snapshots(digest) ON DELETE RESTRICT,
  input_revision integer NOT NULL DEFAULT 0 CHECK (input_revision >= 0),
  iteration_count integer NOT NULL DEFAULT 0 CHECK (iteration_count >= 0),
  model_call_count integer NOT NULL DEFAULT 0 CHECK (model_call_count >= 0),
  capability_call_count integer NOT NULL DEFAULT 0 CHECK (capability_call_count >= 0),
  effect_count integer NOT NULL DEFAULT 0 CHECK (effect_count >= 0),
  active_lease_owner_id text,
  active_lease_generation integer NOT NULL DEFAULT 0 CHECK (active_lease_generation >= 0),
  active_lease_expires_at timestamptz,
  cancelled_at timestamptz,
  terminal_outcome text CHECK (terminal_outcome IS NULL OR terminal_outcome IN (
    'completed', 'model_unavailable', 'blocked_policy', 'budget_exhausted', 'cancelled', 'failed'
  )),
  terminal_diagnostic_code text,
  terminal_at timestamptz,
  next_event_sequence integer NOT NULL DEFAULT 1 CHECK (next_event_sequence >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_runs_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_runs_id_conversation UNIQUE (id, conversation_id),
  CONSTRAINT fk_tutor_runs_conversation_user
    FOREIGN KEY (conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CHECK ((terminal_outcome IS NULL) = (terminal_at IS NULL))
);

CREATE TABLE IF NOT EXISTS tutor_provider_attempt_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  decision_iteration integer NOT NULL CHECK (decision_iteration >= 1),
  attempt_index integer NOT NULL CHECK (attempt_index >= 1),
  provider_type text NOT NULL CHECK (char_length(provider_type) BETWEEN 1 AND 160),
  model text CHECK (model IS NULL OR char_length(model) BETWEEN 1 AND 160),
  protocol text NOT NULL CHECK (protocol IN ('responses', 'deepseek_responses', 'deepseek_chat_completions')),
  outcome text NOT NULL CHECK (outcome IN (
    'accepted', 'repairable_rejected', 'terminal_rejected', 'transport_failed'
  )),
  diagnostic_code text CHECK (diagnostic_code IS NULL OR char_length(diagnostic_code) BETWEEN 1 AND 120),
  input_tokens bigint CHECK (input_tokens IS NULL OR input_tokens >= 0),
  cached_input_tokens bigint CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0),
  uncached_input_tokens bigint CHECK (uncached_input_tokens IS NULL OR uncached_input_tokens >= 0),
  output_tokens bigint CHECK (output_tokens IS NULL OR output_tokens >= 0),
  reported_total_tokens bigint CHECK (reported_total_tokens IS NULL OR reported_total_tokens >= 0),
  calculated_total_tokens bigint CHECK (calculated_total_tokens IS NULL OR calculated_total_tokens >= 0),
  reasoning_tokens bigint CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
  usage_available boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_provider_attempt_receipts_identity
    UNIQUE (run_id, input_revision, decision_iteration, attempt_index),
  CONSTRAINT fk_tutor_provider_attempt_receipt_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_provider_attempt_receipt_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_provider_attempt_receipt_cached_input CHECK (
    (input_tokens IS NULL AND cached_input_tokens IS NULL AND uncached_input_tokens IS NULL)
    OR (
      input_tokens IS NOT NULL
      AND cached_input_tokens IS NOT NULL
      AND cached_input_tokens <= input_tokens
      AND uncached_input_tokens = input_tokens - cached_input_tokens
    )
    OR (
      input_tokens IS NOT NULL
      AND cached_input_tokens IS NULL
      AND uncached_input_tokens = input_tokens
    )
  ),
  CONSTRAINT chk_tutor_provider_attempt_receipt_calculated_total CHECK (
    (calculated_total_tokens IS NULL AND (input_tokens IS NULL OR output_tokens IS NULL))
    OR (
      input_tokens IS NOT NULL
      AND output_tokens IS NOT NULL
      AND calculated_total_tokens = input_tokens + output_tokens
    )
  ),
  CONSTRAINT chk_tutor_provider_attempt_receipt_usage_availability CHECK (
    usage_available = (
      input_tokens IS NOT NULL
      OR cached_input_tokens IS NOT NULL
      OR output_tokens IS NOT NULL
      OR reported_total_tokens IS NOT NULL
      OR reasoning_tokens IS NOT NULL
    )
  ),
  CONSTRAINT chk_tutor_provider_attempt_receipt_outcome_diagnostic CHECK (
    (outcome = 'accepted' AND diagnostic_code IS NULL)
    OR (outcome <> 'accepted' AND diagnostic_code IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_provider_attempt_receipt_transport_usage CHECK (
    outcome <> 'transport_failed' OR usage_available = false
  )
);

CREATE TABLE IF NOT EXISTS tutor_run_skill_selections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  skill_id text NOT NULL,
  skill_version text NOT NULL,
  manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
  instruction_hash text NOT NULL CHECK (instruction_hash ~ '^[0-9a-f]{64}$'),
  evaluation_hash text NOT NULL CHECK (evaluation_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, input_revision),
  UNIQUE (run_id, input_revision, skill_id, skill_version)
);

CREATE TABLE IF NOT EXISTS tutor_run_input_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  message_id uuid NOT NULL REFERENCES tutor_messages(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision > 0),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) <= 160),
  body_hash text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  source text NOT NULL CHECK (char_length(source) <= 120),
  accepted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, input_revision),
  UNIQUE (run_id, idempotency_key),
  UNIQUE (run_id, message_id),
  CONSTRAINT fk_tutor_input_event_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_input_event_message_conversation
    FOREIGN KEY (message_id, conversation_id) REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_run_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  reason text NOT NULL CHECK (reason IN ('safe_progress', 'capability_result', 'terminal')),
  status text NOT NULL CHECK (status IN (
    'queued', 'leased', 'running', 'waiting_for_input', 'waiting_for_capability',
    'awaiting_effect_commit', 'completed', 'model_unavailable', 'blocked_policy',
    'budget_exhausted', 'cancelled', 'failed'
  )),
  metadata_json jsonb NOT NULL,
  metadata_hash text NOT NULL CHECK (metadata_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, input_revision, reason, status)
);

CREATE TABLE IF NOT EXISTS tutor_run_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  event_sequence integer NOT NULL CHECK (event_sequence > 0),
  event_key text NOT NULL CHECK (char_length(event_key) <= 160),
  kind text NOT NULL CHECK (char_length(kind) <= 120),
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  payload_json jsonb NOT NULL,
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, event_sequence),
  UNIQUE (run_id, event_key)
);

CREATE TABLE IF NOT EXISTS tutor_capability_invocations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  event_id uuid NOT NULL REFERENCES tutor_run_events(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  invocation_key text NOT NULL CHECK (char_length(invocation_key) <= 160),
  capability_id text NOT NULL,
  capability_version text NOT NULL,
  catalog_digest text NOT NULL CHECK (catalog_digest ~ '^[0-9a-f]{64}$'),
  policy_fingerprint text NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  skill_id text,
  skill_version text,
  manifest_hash text,
  instruction_hash text,
  lease_owner_id text NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation > 0),
  status text NOT NULL CHECK (status IN ('completed', 'denied', 'unavailable')),
  diagnostic_code text,
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  duration_ms integer NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, invocation_key)
);

CREATE TABLE IF NOT EXISTS tutor_effects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  effect_id text NOT NULL,
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) <= 160),
  effect_type text NOT NULL,
  expected_input_revision integer NOT NULL CHECK (expected_input_revision >= 0),
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  lease_owner_id text NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation > 0),
  status text NOT NULL CHECK (status IN ('proposed', 'committed', 'denied', 'stale_rejected')),
  commit_id text,
  safe_outcome_json jsonb NOT NULL,
  safe_outcome_hash text NOT NULL CHECK (safe_outcome_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, effect_id),
  UNIQUE (run_id, idempotency_key)
);

-- Container executor target persistence (Child 03): additive, feature-off, and safe-projection-only.
CREATE TABLE IF NOT EXISTS tutor_execution_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  source_message_id uuid NOT NULL REFERENCES tutor_messages(id) ON DELETE RESTRICT,
  exercise_id uuid NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  origin text NOT NULL CHECK (origin IN ('interactive', 'proactive')),
  action text NOT NULL CHECK (action IN ('run', 'test', 'debug', 'explain')),
  catalog_digest text NOT NULL CHECK (catalog_digest ~ '^[0-9a-f]{64}$'),
  policy_fingerprint text NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  budget_fingerprint text NOT NULL CHECK (budget_fingerprint ~ '^[0-9a-f]{64}$'),
  budget_execution_count integer NOT NULL CHECK (budget_execution_count = 1),
  issued_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  consumed_by_effect_id uuid REFERENCES tutor_effects(id) ON DELETE RESTRICT,
  cancelled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_execution_intent_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_execution_intent_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_execution_intent_message_conversation
    FOREIGN KEY (source_message_id, conversation_id) REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CHECK (expires_at > issued_at),
  CHECK ((consumed_at IS NULL) = (consumed_by_effect_id IS NULL))
);

CREATE TABLE IF NOT EXISTS tutor_execution_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  effect_record_id uuid NOT NULL UNIQUE REFERENCES tutor_effects(id) ON DELETE RESTRICT,
  effect_key text NOT NULL CHECK (char_length(effect_key) <= 160),
  intent_id uuid NOT NULL UNIQUE REFERENCES tutor_execution_intents(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  runtime_id text NOT NULL CHECK (char_length(runtime_id) <= 120),
  lock_fingerprint text NOT NULL CHECK (lock_fingerprint ~ '^[0-9a-f]{64}$'),
  source_reference_hash text NOT NULL CHECK (source_reference_hash ~ '^[0-9a-f]{64}$'),
  test_reference_hash text NOT NULL CHECK (test_reference_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN (
    'pending', 'claimed', 'launch_reserved', 'running', 'completed', 'timed_out',
    'cancelled', 'unavailable', 'launch_uncertain', 'failed'
  )),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  launch_token text UNIQUE CHECK (launch_token IS NULL OR char_length(launch_token) <= 160),
  launch_generation integer NOT NULL DEFAULT 0 CHECK (launch_generation >= 0),
  launch_reserved_at timestamptz,
  started_at timestamptz,
  cancellation_requested_at timestamptz,
  cleanup_state text NOT NULL DEFAULT 'pending' CHECK (cleanup_state IN ('pending', 'completed', 'failed', 'not_required')),
  result_json jsonb,
  result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
  safe_diagnostic_code text,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_execution_job_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_execution_job_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CHECK ((result_json IS NULL) = (result_hash IS NULL)),
  CHECK ((launch_token IS NULL) = (launch_reserved_at IS NULL))
);

CREATE TABLE IF NOT EXISTS tutor_execution_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES tutor_execution_jobs(id) ON DELETE RESTRICT,
  attempt_sequence integer NOT NULL CHECK (attempt_sequence >= 1),
  executor_id text NOT NULL CHECK (char_length(executor_id) <= 160),
  lease_generation integer NOT NULL CHECK (lease_generation >= 0),
  launch_generation integer NOT NULL CHECK (launch_generation >= 0),
  stage text NOT NULL CHECK (stage IN ('claimed', 'preflight', 'launch_reserved', 'running', 'cleanup', 'terminal')),
  lock_fingerprint text NOT NULL CHECK (lock_fingerprint ~ '^[0-9a-f]{64}$'),
  safe_diagnostic_code text,
  duration_ms integer NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  output_bytes integer NOT NULL DEFAULT 0 CHECK (output_bytes >= 0),
  cleanup_state text NOT NULL DEFAULT 'pending' CHECK (cleanup_state IN ('pending', 'completed', 'failed', 'not_required')),
  result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, attempt_sequence)
);

CREATE TABLE IF NOT EXISTS tutor_executor_health (
  executor_id text PRIMARY KEY CHECK (char_length(executor_id) <= 160),
  service_version text NOT NULL CHECK (char_length(service_version) <= 120),
  registry_fingerprint text NOT NULL CHECK (registry_fingerprint ~ '^[0-9a-f]{64}$'),
  verified_runtime_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL CHECK (status IN ('available', 'unavailable', 'quarantined')),
  availability_code text NOT NULL CHECK (char_length(availability_code) <= 120),
  last_heartbeat_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_run_traces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  event_from_sequence integer NOT NULL CHECK (event_from_sequence > 0),
  event_to_sequence integer NOT NULL CHECK (event_to_sequence >= event_from_sequence),
  kind text NOT NULL CHECK (char_length(kind) <= 120),
  trace_json jsonb NOT NULL,
  trace_hash text NOT NULL CHECK (trace_hash ~ '^[0-9a-f]{64}$'),
  redaction_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_memory_curation_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  trigger text NOT NULL CHECK (trigger IN ('terminal', 'safe_checkpoint', 'context_high_water')),
  event_from_sequence integer NOT NULL CHECK (event_from_sequence > 0),
  event_to_sequence integer NOT NULL CHECK (event_to_sequence >= event_from_sequence),
  trace_id uuid NOT NULL REFERENCES tutor_run_traces(id) ON DELETE RESTRICT,
  source_ids_json jsonb NOT NULL,
  source_hashes_json jsonb NOT NULL,
  policy_version text NOT NULL,
  memory_setting_version text NOT NULL,
  projection_kind text NOT NULL DEFAULT 'memory_or_summary'
    CHECK (projection_kind IN ('memory_or_summary', 'context_summary')),
  summary_schema_version text,
  summary_policy_version text,
  summary_source_hash text,
  prior_summary_id uuid,
  prior_summary_hash text,
  covered_through_created_at timestamptz,
  covered_through_message_id uuid,
  priority integer NOT NULL DEFAULT 0 CHECK (priority BETWEEN 0 AND 100),
  retention_until timestamptz NOT NULL,
  stale_after timestamptz NOT NULL,
  state text NOT NULL CHECK (state IN ('pending', 'no_action', 'stale', 'failed')),
  idempotency_key text NOT NULL UNIQUE CHECK (char_length(idempotency_key) <= 160),
  envelope_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_outbox_id_conversation UNIQUE (id, conversation_id),
  CONSTRAINT fk_tutor_outbox_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_outbox_summary_evidence CHECK (
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
  ),
  CHECK (stale_after <= retention_until)
);

ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS projection_kind text NOT NULL DEFAULT 'memory_or_summary';
ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS summary_schema_version text;
ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS summary_policy_version text;
ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS summary_source_hash text;
ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS prior_summary_id uuid;
ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS prior_summary_hash text;
ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS covered_through_created_at timestamptz;
ALTER TABLE tutor_memory_curation_outbox
  ADD COLUMN IF NOT EXISTS covered_through_message_id uuid;

CREATE TABLE IF NOT EXISTS tutor_curation_proposals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  outbox_id uuid NOT NULL UNIQUE REFERENCES tutor_memory_curation_outbox(id) ON DELETE RESTRICT,
  event_id uuid NOT NULL REFERENCES tutor_run_events(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK (kind IN ('context_summary', 'memory_entry')),
  state text NOT NULL CHECK (state IN ('pending', 'no_action', 'stale', 'failed')),
  event_from_sequence integer NOT NULL CHECK (event_from_sequence > 0),
  event_to_sequence integer NOT NULL CHECK (event_to_sequence >= event_from_sequence),
  provenance_json jsonb NOT NULL,
  payload_json jsonb NOT NULL,
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  confidence text NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
  policy_version text NOT NULL,
  memory_setting_version text NOT NULL,
  retention_until timestamptz NOT NULL,
  stale_after timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (stale_after <= retention_until)
);


-- Tutor proactive scheduler (Child 04): additive, feature-disabled, and safe-reference-only.
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'learner';
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'interactive';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_conversations'::regclass
      AND conname = 'chk_tutor_conversations_visibility_kind'
  ) THEN
    ALTER TABLE tutor_conversations
      ADD CONSTRAINT chk_tutor_conversations_visibility_kind CHECK (
        (visibility = 'learner' AND kind = 'interactive')
        OR (visibility = 'internal' AND kind = 'proactive')
      );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_proactive_preferences (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  enabled boolean NOT NULL DEFAULT true,
  hard_paused boolean NOT NULL DEFAULT false,
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  setting_version text NOT NULL CHECK (char_length(setting_version) <= 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Earlier scheduler slices created unpaused preferences with enabled=false.
-- The public control is pause/resume, so preserve explicit pauses but migrate
-- the former default into the verified-only, controlled-delivery default.
ALTER TABLE tutor_proactive_preferences
  ALTER COLUMN enabled SET DEFAULT true;
UPDATE tutor_proactive_preferences
SET enabled = true,
    updated_at = now()
WHERE enabled = false
  AND hard_paused = false;

CREATE TABLE IF NOT EXISTS tutor_proactive_signals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  signal_kind text NOT NULL CHECK (char_length(signal_kind) <= 160),
  source_type text NOT NULL CHECK (char_length(source_type) <= 160),
  source_id text NOT NULL CHECK (char_length(source_id) <= 160),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  dedupe_key text NOT NULL CHECK (char_length(dedupe_key) <= 160),
  dedupe_bucket_at timestamptz NOT NULL,
  dedupe_window_seconds integer NOT NULL CHECK (dedupe_window_seconds > 0),
  source_reference_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  disposition text NOT NULL CHECK (disposition IN ('received', 'accepted', 'suppressed', 'no_action')),
  disposition_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_proactive_signals_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_proactive_signal_source UNIQUE (user_id, source_type, source_id, source_hash)
);

CREATE TABLE IF NOT EXISTS tutor_proactive_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id uuid NOT NULL UNIQUE REFERENCES tutor_proactive_signals(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  candidate_kind text NOT NULL CHECK (char_length(candidate_kind) <= 160),
  dedupe_key text NOT NULL CHECK (char_length(dedupe_key) <= 160),
  dedupe_bucket_at timestamptz NOT NULL,
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  policy_fingerprint text NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('pending', 'leased', 'completed', 'no_action', 'failed', 'stale')),
  no_action_code text,
  last_error_code text,
  not_before timestamptz NOT NULL,
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  run_id uuid,
  run_started_at timestamptz,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_proactive_candidates_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_proactive_candidate_dedupe UNIQUE (user_id, dedupe_key, dedupe_bucket_at),
  CONSTRAINT fk_tutor_proactive_candidate_signal_user
    FOREIGN KEY (signal_id, user_id) REFERENCES tutor_proactive_signals(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_proactive_candidate_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_proactive_candidate_terminal CHECK (
    (state IN ('completed', 'no_action', 'failed', 'stale')) = (terminal_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_proactive_candidate_lease CHECK (
    (state = 'leased' AND lease_owner_id IS NOT NULL AND lease_generation > 0 AND lease_expires_at IS NOT NULL)
    OR (state <> 'leased' AND lease_owner_id IS NULL AND lease_expires_at IS NULL)
  )
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_memory_curation_outbox'::regclass
      AND conname = 'uq_tutor_outbox_id_run'
  ) THEN
    ALTER TABLE tutor_memory_curation_outbox
      ADD CONSTRAINT uq_tutor_outbox_id_run UNIQUE (id, run_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_curation_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  outbox_id uuid NOT NULL UNIQUE REFERENCES tutor_memory_curation_outbox(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  memory_setting_version text NOT NULL CHECK (char_length(memory_setting_version) <= 160),
  projection_kind text NOT NULL DEFAULT 'memory_or_summary'
    CHECK (projection_kind IN ('memory_or_summary', 'context_summary')),
  state text NOT NULL CHECK (state IN ('pending', 'leased', 'completed', 'no_action', 'failed', 'stale')),
  no_action_code text,
  last_error_code text,
  not_before timestamptz NOT NULL,
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  processor_started_at timestamptz,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_curation_jobs_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_curation_job_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_curation_job_outbox_run
    FOREIGN KEY (outbox_id, run_id) REFERENCES tutor_memory_curation_outbox(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_curation_job_terminal CHECK (
    (state IN ('completed', 'no_action', 'failed', 'stale')) = (terminal_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_curation_job_lease CHECK (
    (state = 'leased' AND lease_owner_id IS NOT NULL AND lease_generation > 0 AND lease_expires_at IS NOT NULL)
    OR (state <> 'leased' AND lease_owner_id IS NULL AND lease_expires_at IS NULL)
  )
);

ALTER TABLE tutor_curation_jobs
  ADD COLUMN IF NOT EXISTS projection_kind text NOT NULL DEFAULT 'memory_or_summary';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_curation_jobs'::regclass
      AND conname = 'chk_tutor_curation_jobs_projection_kind'
  ) THEN
    ALTER TABLE tutor_curation_jobs
      ADD CONSTRAINT chk_tutor_curation_jobs_projection_kind
      CHECK (projection_kind IN ('memory_or_summary', 'context_summary'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_scheduler_audit (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  queue text NOT NULL CHECK (queue IN ('proactive', 'curation')),
  candidate_id uuid,
  curation_job_id uuid,
  decision text NOT NULL CHECK (char_length(decision) <= 160),
  code text NOT NULL CHECK (char_length(code) <= 160),
  details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_scheduler_audit_candidate_user
    FOREIGN KEY (candidate_id, user_id) REFERENCES tutor_proactive_candidates(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_scheduler_audit_curation_user
    FOREIGN KEY (curation_job_id, user_id) REFERENCES tutor_curation_jobs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_scheduler_audit_target CHECK (
    (candidate_id IS NULL) <> (curation_job_id IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_proactive_candidates_pending
  ON tutor_proactive_candidates (not_before, created_at, id)
  WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS idx_tutor_proactive_candidates_user_state
  ON tutor_proactive_candidates (user_id, state, terminal_at);
CREATE INDEX IF NOT EXISTS idx_tutor_curation_jobs_pending
  ON tutor_curation_jobs (not_before, created_at, id)
  WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS idx_tutor_curation_jobs_user_state
  ON tutor_curation_jobs (user_id, state, terminal_at);
CREATE INDEX IF NOT EXISTS idx_tutor_scheduler_audit_user_created
  ON tutor_scheduler_audit (user_id, created_at DESC);

CREATE OR REPLACE FUNCTION enforce_tutor_scheduler_queue_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF NEW.state = 'leased' THEN
    IF NEW.lease_owner_id IS NULL OR NEW.lease_generation <= 0 OR NEW.lease_expires_at IS NULL THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'leased scheduler row requires a lease shape';
    END IF;
  ELSIF NEW.lease_owner_id IS NOT NULL OR NEW.lease_expires_at IS NOT NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'non-leased scheduler row cannot retain a lease';
  END IF;
  IF (NEW.state IN ('completed', 'no_action', 'failed', 'stale')) <> (NEW.terminal_at IS NOT NULL) THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'scheduler terminal state requires terminal_at';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.state IN ('completed', 'no_action', 'failed', 'stale') AND NEW.state <> OLD.state THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'terminal scheduler row cannot return to work';
    END IF;
    IF NEW.lease_generation < OLD.lease_generation THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'scheduler lease generation cannot decrease';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_proactive_candidates_lifecycle ON tutor_proactive_candidates;
CREATE TRIGGER trg_tutor_proactive_candidates_lifecycle
BEFORE INSERT OR UPDATE ON tutor_proactive_candidates
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_scheduler_queue_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_curation_jobs_lifecycle ON tutor_curation_jobs;
CREATE TRIGGER trg_tutor_curation_jobs_lifecycle
BEFORE INSERT OR UPDATE ON tutor_curation_jobs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_scheduler_queue_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_proactive_preferences_updated_at ON tutor_proactive_preferences;
CREATE TRIGGER trg_tutor_proactive_preferences_updated_at BEFORE UPDATE ON tutor_proactive_preferences
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_proactive_candidates_updated_at ON tutor_proactive_candidates;
CREATE TRIGGER trg_tutor_proactive_candidates_updated_at BEFORE UPDATE ON tutor_proactive_candidates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_curation_jobs_updated_at ON tutor_curation_jobs;
CREATE TRIGGER trg_tutor_curation_jobs_updated_at BEFORE UPDATE ON tutor_curation_jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_conversations'::regclass AND conname = 'uq_tutor_conversations_id_user'
  ) THEN
    ALTER TABLE tutor_conversations
      ADD CONSTRAINT uq_tutor_conversations_id_user UNIQUE (id, user_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_messages'::regclass AND conname = 'uq_tutor_messages_id_conversation'
  ) THEN
    ALTER TABLE tutor_messages
      ADD CONSTRAINT uq_tutor_messages_id_conversation UNIQUE (id, conversation_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_messages'::regclass AND conname = 'chk_tutor_messages_public_thinking_steps'
  ) THEN
    ALTER TABLE tutor_messages
      ADD CONSTRAINT chk_tutor_messages_public_thinking_steps CHECK (
        jsonb_typeof(public_thinking_steps_json) = 'array'
        AND jsonb_array_length(public_thinking_steps_json) <= 4
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass AND conname = 'uq_tutor_runs_id_user'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT uq_tutor_runs_id_user UNIQUE (id, user_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass AND conname = 'uq_tutor_runs_id_conversation'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT uq_tutor_runs_id_conversation UNIQUE (id, conversation_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass AND conname = 'fk_tutor_runs_conversation_user'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT fk_tutor_runs_conversation_user
      FOREIGN KEY (conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_run_input_events'::regclass AND conname = 'fk_tutor_input_event_run_conversation'
  ) THEN
    ALTER TABLE tutor_run_input_events
      ADD CONSTRAINT fk_tutor_input_event_run_conversation
      FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_run_input_events'::regclass AND conname = 'fk_tutor_input_event_message_conversation'
  ) THEN
    ALTER TABLE tutor_run_input_events
      ADD CONSTRAINT fk_tutor_input_event_message_conversation
      FOREIGN KEY (message_id, conversation_id) REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_memory_curation_outbox'::regclass AND conname = 'fk_tutor_outbox_run_conversation'
  ) THEN
    ALTER TABLE tutor_memory_curation_outbox
      ADD CONSTRAINT fk_tutor_outbox_run_conversation
      FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT;
  END IF;
END $$;

-- Child 03 execution scope and lifecycle guards.  These are additive because
-- bootstrap_database() is the only schema applier and is intentionally repeatable.
DO $$
BEGIN
  -- Parent keys required by Child 03's cross-table scope foreign keys.
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_effects'::regclass AND conname = 'uq_tutor_effects_id_run'
  ) THEN
    ALTER TABLE tutor_effects
      ADD CONSTRAINT uq_tutor_effects_id_run UNIQUE (id, run_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_effects'::regclass AND conname = 'uq_tutor_effects_id_run_effect'
  ) THEN
    ALTER TABLE tutor_effects
      ADD CONSTRAINT uq_tutor_effects_id_run_effect UNIQUE (id, run_id, effect_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_run_input_events'::regclass
      AND conname = 'uq_tutor_input_events_run_message_revision'
  ) THEN
    ALTER TABLE tutor_run_input_events
      ADD CONSTRAINT uq_tutor_input_events_run_message_revision
      UNIQUE (run_id, message_id, input_revision);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'uq_tutor_execution_intents_id_scope'
  ) THEN
    ALTER TABLE tutor_execution_intents
      ADD CONSTRAINT uq_tutor_execution_intents_id_scope
      UNIQUE (id, run_id, user_id, conversation_id);
  END IF;

  -- NOT VALID keeps this additive for an already-bootstrapped local database
  -- while PostgreSQL still enforces every new write or mutation.
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'fk_tutor_execution_intent_consumed_effect_run'
  ) THEN
    ALTER TABLE tutor_execution_intents
      ADD CONSTRAINT fk_tutor_execution_intent_consumed_effect_run
      FOREIGN KEY (consumed_by_effect_id, run_id)
      REFERENCES tutor_effects(id, run_id) ON DELETE RESTRICT NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'fk_tutor_execution_intent_accepted_input'
  ) THEN
    ALTER TABLE tutor_execution_intents
      ADD CONSTRAINT fk_tutor_execution_intent_accepted_input
      FOREIGN KEY (run_id, source_message_id, input_revision)
      REFERENCES tutor_run_input_events(run_id, message_id, input_revision)
      ON DELETE RESTRICT NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'fk_tutor_execution_job_intent_scope'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT fk_tutor_execution_job_intent_scope
      FOREIGN KEY (intent_id, run_id, user_id, conversation_id)
      REFERENCES tutor_execution_intents(id, run_id, user_id, conversation_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'fk_tutor_execution_job_effect_scope'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT fk_tutor_execution_job_effect_scope
      FOREIGN KEY (effect_record_id, run_id, effect_key)
      REFERENCES tutor_effects(id, run_id, effect_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'chk_tutor_execution_jobs_terminal_result'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT chk_tutor_execution_jobs_terminal_result
      CHECK (
        (
          state IN ('completed', 'timed_out', 'cancelled', 'unavailable', 'launch_uncertain', 'failed')
          AND terminal_at IS NOT NULL
          AND result_json IS NOT NULL
          AND result_hash IS NOT NULL
        )
        OR (
          state NOT IN ('completed', 'timed_out', 'cancelled', 'unavailable', 'launch_uncertain', 'failed')
          AND terminal_at IS NULL
          AND result_json IS NULL
          AND result_hash IS NULL
        )
      ) NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'chk_tutor_execution_jobs_claimed_lease'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT chk_tutor_execution_jobs_claimed_lease
      CHECK (
        state <> 'claimed'
        OR (
          lease_owner_id IS NOT NULL
          AND lease_generation > 0
          AND lease_expires_at IS NOT NULL
          AND launch_token IS NULL
          AND launch_generation = 0
          AND launch_reserved_at IS NULL
        )
      ) NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'chk_tutor_execution_jobs_launch_reservation'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT chk_tutor_execution_jobs_launch_reservation
      CHECK (
        (launch_token IS NULL AND launch_generation = 0 AND launch_reserved_at IS NULL)
        OR (launch_token IS NOT NULL AND launch_generation > 0 AND launch_reserved_at IS NOT NULL)
      ) NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'chk_tutor_execution_jobs_reserved_running'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT chk_tutor_execution_jobs_reserved_running
      CHECK (
        state NOT IN ('launch_reserved', 'running')
        OR (
          launch_token IS NOT NULL
          AND launch_generation > 0
          AND launch_reserved_at IS NOT NULL
          AND lease_owner_id IS NOT NULL
          AND lease_generation > 0
          AND lease_expires_at IS NOT NULL
        )
      ) NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'chk_tutor_execution_jobs_running_started'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT chk_tutor_execution_jobs_running_started
      CHECK (state <> 'running' OR started_at IS NOT NULL) NOT VALID;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_tutor_execution_job_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF OLD.launch_token IS NOT NULL
       AND (
         NEW.launch_token IS DISTINCT FROM OLD.launch_token
         OR NEW.launch_generation IS DISTINCT FROM OLD.launch_generation
         OR NEW.launch_reserved_at IS DISTINCT FROM OLD.launch_reserved_at
       )
    THEN
      RAISE EXCEPTION USING
        ERRCODE = '23514',
        MESSAGE = 'execution launch reservation is immutable';
    END IF;

    IF OLD.launch_token IS NULL
       AND NEW.launch_token IS NOT NULL
       AND NOT (OLD.state = 'claimed' AND NEW.state = 'launch_reserved')
    THEN
      RAISE EXCEPTION USING
        ERRCODE = '23514',
        MESSAGE = 'execution launch token may only be allocated during reservation';
    END IF;

    IF OLD.state IN ('completed', 'timed_out', 'cancelled', 'unavailable', 'launch_uncertain', 'failed') THEN
      IF NEW.state NOT IN ('completed', 'timed_out', 'cancelled', 'unavailable', 'launch_uncertain', 'failed') THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514',
          MESSAGE = 'execution terminal state cannot become non-terminal';
      END IF;

      IF NEW.state <> OLD.state AND NEW.state <> 'failed' THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514',
          MESSAGE = 'execution terminal state may only converge to failed during cleanup';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_provider_attempt_receipt_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Tutor provider attempt receipts are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE INDEX IF NOT EXISTS idx_tutor_conversations_user ON tutor_conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_messages_conversation ON tutor_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tutor_runs_user_status ON tutor_runs(user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_runs_conversation ON tutor_runs(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_input_events_run_revision ON tutor_run_input_events(run_id, input_revision);
CREATE INDEX IF NOT EXISTS idx_tutor_provider_attempt_receipts_run_created
  ON tutor_provider_attempt_receipts(run_id, created_at, decision_iteration, attempt_index);
CREATE INDEX IF NOT EXISTS idx_tutor_checkpoints_run_created ON tutor_run_checkpoints(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_events_run_sequence ON tutor_run_events(run_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_tutor_capability_invocations_run_created ON tutor_capability_invocations(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_effects_run_created ON tutor_effects(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_execution_intents_run_expiry ON tutor_execution_intents(run_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_tutor_execution_jobs_claim ON tutor_execution_jobs(state, lease_expires_at, created_at);
CREATE INDEX IF NOT EXISTS idx_tutor_execution_jobs_run_created ON tutor_execution_jobs(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_execution_attempts_job_created ON tutor_execution_attempts(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tutor_executor_health_heartbeat ON tutor_executor_health(last_heartbeat_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_traces_run_sequence ON tutor_run_traces(run_id, event_from_sequence);
CREATE INDEX IF NOT EXISTS idx_tutor_curation_outbox_state_created ON tutor_memory_curation_outbox(state, created_at);
CREATE INDEX IF NOT EXISTS idx_tutor_curation_proposals_state_created ON tutor_curation_proposals(state, created_at);

DROP TRIGGER IF EXISTS trg_tutor_provider_attempt_receipts_immutable ON tutor_provider_attempt_receipts;
CREATE TRIGGER trg_tutor_provider_attempt_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_provider_attempt_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_provider_attempt_receipt_immutable();

DROP TRIGGER IF EXISTS trg_tutor_conversations_updated_at ON tutor_conversations;
CREATE TRIGGER trg_tutor_conversations_updated_at BEFORE UPDATE ON tutor_conversations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_runs_updated_at ON tutor_runs;
CREATE TRIGGER trg_tutor_runs_updated_at BEFORE UPDATE ON tutor_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_effects_updated_at ON tutor_effects;
CREATE TRIGGER trg_tutor_effects_updated_at BEFORE UPDATE ON tutor_effects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_execution_jobs_updated_at ON tutor_execution_jobs;
CREATE TRIGGER trg_tutor_execution_jobs_updated_at BEFORE UPDATE ON tutor_execution_jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_execution_jobs_lifecycle_guard ON tutor_execution_jobs;
CREATE TRIGGER trg_tutor_execution_jobs_lifecycle_guard
BEFORE INSERT OR UPDATE ON tutor_execution_jobs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_execution_job_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_executor_health_updated_at ON tutor_executor_health;
CREATE TRIGGER trg_tutor_executor_health_updated_at BEFORE UPDATE ON tutor_executor_health
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_memory_curation_outbox_updated_at ON tutor_memory_curation_outbox;
CREATE TRIGGER trg_tutor_memory_curation_outbox_updated_at BEFORE UPDATE ON tutor_memory_curation_outbox
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_curation_proposals_updated_at ON tutor_curation_proposals;
CREATE TRIGGER trg_tutor_curation_proposals_updated_at BEFORE UPDATE ON tutor_curation_proposals
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
