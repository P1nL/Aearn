CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL,
  learning_style text,
  teaching_preference text,
  encouragement_preference text,
  profession text,
  background_context text,
  preferred_time_slots jsonb NOT NULL DEFAULT '[]'::jsonb,
  reminder_preference jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS learner_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  weak_points jsonb NOT NULL DEFAULT '[]'::jsonb,
  error_patterns jsonb NOT NULL DEFAULT '[]'::jsonb,
  learning_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
  pace_indicators jsonb NOT NULL DEFAULT '{}'::jsonb,
  observations jsonb NOT NULL DEFAULT '[]'::jsonb,
  session_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT learner_profiles_user_id_key UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS runtime_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  runtime_tier text NOT NULL CHECK (runtime_tier IN ('browser_preview', 'python_stdout_test', 'node_typescript_test', 'sql_query_test', 'managed_compiled_test', 'compiled_sandbox_later')),
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'typescript', 'sql', 'java', 'go', 'csharp', 'cpp', 'html_css')),
  runner text NOT NULL CHECK (runner IN ('browser', 'python', 'node', 'sql', 'compiled', 'sandbox')),
  supports_realtime_preview boolean NOT NULL DEFAULT false,
  supports_stdout boolean NOT NULL DEFAULT false,
  supports_tests boolean NOT NULL DEFAULT false,
  compile_required boolean NOT NULL DEFAULT false,
  timeout_ms integer NOT NULL DEFAULT 5000 CHECK (timeout_ms BETWEEN 100 AND 60000),
  memory_limit_mb integer NOT NULL DEFAULT 128 CHECK (memory_limit_mb BETWEEN 16 AND 2048),
  sandbox_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz
);

CREATE TABLE IF NOT EXISTS language_courses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'typescript', 'sql', 'java', 'go', 'csharp', 'html_css')),
  title text NOT NULL,
  description text,
  level text NOT NULL CHECK (level IN ('beginner', 'intermediate', 'advanced')),
  runtime_profile_id uuid NOT NULL REFERENCES runtime_profiles(id) ON DELETE RESTRICT,
  supported_exercise_types_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz
);

CREATE TABLE IF NOT EXISTS learning_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  language_course_id uuid NOT NULL REFERENCES language_courses(id) ON DELETE RESTRICT,
  goal_text text NOT NULL,
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'typescript', 'sql', 'java', 'go', 'csharp', 'html_css')),
  target_level text NOT NULL CHECK (target_level IN ('beginner', 'intermediate', 'advanced')),
  mode text NOT NULL CHECK (mode IN ('goal_based', 'material_based')),
  deadline date,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
  overall_progress numeric(5,4) NOT NULL DEFAULT 0 CHECK (overall_progress >= 0 AND overall_progress <= 1),
  current_module_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  archived_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS plan_modules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  title text NOT NULL,
  description text,
  order_index integer NOT NULL CHECK (order_index >= 0),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'skipped')),
  is_skippable boolean NOT NULL DEFAULT true,
  is_adjustable boolean NOT NULL DEFAULT true,
  estimated_sessions integer NOT NULL DEFAULT 1 CHECK (estimated_sessions >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  archived_at timestamptz,
  deleted_at timestamptz
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'learning_plans_current_module_id_fkey'
  ) THEN
    ALTER TABLE learning_plans
      ADD CONSTRAINT learning_plans_current_module_id_fkey
      FOREIGN KEY (current_module_id) REFERENCES plan_modules(id) ON DELETE RESTRICT;
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS knowledge_points (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text UNIQUE,
  module_id uuid NOT NULL REFERENCES plan_modules(id) ON DELETE RESTRICT,
  language_course_id uuid NOT NULL REFERENCES language_courses(id) ON DELETE RESTRICT,
  title text NOT NULL,
  description text,
  order_index integer NOT NULL DEFAULT 0 CHECK (order_index >= 0),
  skill_tags_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  lesson_outline_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  lesson_sources_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'learning', 'reviewing', 'mastered')),
  mastery_score numeric(5,4) NOT NULL DEFAULT 0 CHECK (mastery_score >= 0 AND mastery_score <= 1),
  weak_points_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  effective_hint_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_exercise_result text CHECK (last_exercise_result IN ('failed', 'partial', 'passed', 'easy')),
  last_exercise_score smallint CHECK (last_exercise_score BETWEEN 0 AND 8),
  last_exercise_breakdown_json jsonb,
  last_explanation_check_result jsonb,
  last_session_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS exercises (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text UNIQUE,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  runtime_profile_id uuid NOT NULL REFERENCES runtime_profiles(id) ON DELETE RESTRICT,
  title text NOT NULL,
  exercise_type text NOT NULL CHECK (exercise_type IN ('code_blank', 'fix_bug', 'implement_function', 'explain_code', 'review_ai_patch')),
  prompt_markdown text NOT NULL,
  starter_code text NOT NULL,
  solution_reference text,
  visible_test_policy text NOT NULL DEFAULT 'visible_and_hidden_summary'
    CHECK (visible_test_policy IN ('visible_only', 'visible_and_hidden_summary', 'hidden_only')),
  difficulty smallint NOT NULL DEFAULT 1 CHECK (difficulty BETWEEN 1 AND 5),
  estimated_minutes integer NOT NULL DEFAULT 10 CHECK (estimated_minutes BETWEEN 1 AND 240),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS code_blanks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_id uuid NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
  blank_key text NOT NULL,
  placeholder text NOT NULL,
  expected_concept text NOT NULL,
  acceptable_patterns_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  is_core boolean NOT NULL DEFAULT true,
  order_index integer NOT NULL CHECK (order_index >= 0),
  CONSTRAINT code_blanks_exercise_blank_key_key UNIQUE (exercise_id, blank_key),
  CONSTRAINT code_blanks_exercise_order_key UNIQUE (exercise_id, order_index)
);

CREATE TABLE IF NOT EXISTS test_cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_id uuid NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
  case_type text NOT NULL CHECK (case_type IN ('visible', 'hidden', 'preview_assertion')),
  input_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  expected_output_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  assertion_code text,
  weight numeric(6,2) NOT NULL DEFAULT 1 CHECK (weight > 0),
  is_critical boolean NOT NULL DEFAULT false,
  timeout_ms integer NOT NULL DEFAULT 5000 CHECK (timeout_ms BETWEEN 100 AND 60000),
  order_index integer NOT NULL CHECK (order_index >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  CONSTRAINT test_cases_exercise_order_key UNIQUE (exercise_id, order_index)
);

CREATE TABLE IF NOT EXISTS learning_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  session_type text NOT NULL CHECK (session_type IN ('learn', 'review')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished', 'abandoned')),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  duration_seconds integer CHECK (duration_seconds >= 0),
  entry_point text NOT NULL,
  summary_text text,
  next_entry_point text,
  learning_stage text CHECK (learning_stage IS NULL OR learning_stage IN ('documentation_reading', 'concept_intro', 'concept_check', 'concept_repair', 'practice_offer', 'concept_qna', 'readiness_check', 'practice_support')),
  learning_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  review_stage text CHECK (review_stage IS NULL OR review_stage IN ('warmup', 'warmup_repair', 'variant_practice', 'exercise', 'exercise_feedback', 'final_summary', 'submitted')),
  review_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'knowledge_points_last_session_id_fkey'
  ) THEN
    ALTER TABLE knowledge_points
      ADD CONSTRAINT knowledge_points_last_session_id_fkey
      FOREIGN KEY (last_session_id) REFERENCES learning_sessions(id) ON DELETE SET NULL;
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  exercise_id uuid NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  attempt_type text NOT NULL CHECK (attempt_type IN ('run', 'submit', 'review_submit')),
  submit_version integer NOT NULL DEFAULT 1 CHECK (submit_version >= 1),
  submitted_code text NOT NULL,
  code_hash text NOT NULL,
  filled_blanks_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  runtime_status text NOT NULL CHECK (runtime_status IN ('success', 'missing_toolchain', 'unsupported', 'compile_error', 'runtime_error', 'timeout', 'test_failure')),
  test_pass_rate numeric(5,4) NOT NULL DEFAULT 0 CHECK (test_pass_rate >= 0 AND test_pass_rate <= 1),
  passed_test_count integer NOT NULL DEFAULT 0 CHECK (passed_test_count >= 0),
  total_test_count integer NOT NULL DEFAULT 0 CHECK (total_test_count >= 0),
  score smallint CHECK (score BETWEEN 0 AND 8),
  score_breakdown_json jsonb,
  code_completion_result jsonb,
  fsrs_rating text CHECK (fsrs_rating IN ('Again', 'Hard', 'Good', 'Easy')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_states (
  knowledge_point_id uuid PRIMARY KEY REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  card_state text NOT NULL DEFAULT 'new' CHECK (card_state IN ('new', 'learning', 'review', 'relearning')),
  stability numeric(10,4),
  difficulty numeric(10,4),
  due_at timestamptz,
  elapsed_days integer NOT NULL DEFAULT 0 CHECK (elapsed_days >= 0),
  scheduled_days integer NOT NULL DEFAULT 0 CHECK (scheduled_days >= 0),
  reps integer NOT NULL DEFAULT 0 CHECK (reps >= 0),
  lapses integer NOT NULL DEFAULT 0 CHECK (lapses >= 0),
  last_review_at timestamptz,
  last_attempt_id uuid REFERENCES attempts(id) ON DELETE RESTRICT,
  fsrs_parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_seed_banks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  generator_version text NOT NULL,
  status text NOT NULL DEFAULT 'generating' CHECK (status IN ('generating', 'ready', 'failed')),
  seed_count integer NOT NULL DEFAULT 0 CHECK (seed_count >= 0),
  seeds_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  quality_report_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  failure_code text,
  failure_message text,
  generated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exercise_variant_cache (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
  template_id text NOT NULL,
  template_version text NOT NULL,
  generator_version text NOT NULL,
  runner_key text NOT NULL,
  runtime_tier text NOT NULL,
  variant_hash text NOT NULL,
  status text NOT NULL CHECK (status IN ('validated')),
  exercise_payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  validation_report_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  failure_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS review_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  attempt_id uuid NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
  rating text NOT NULL CHECK (rating IN ('Again', 'Hard', 'Good', 'Easy')),
  previous_state_json jsonb NOT NULL,
  next_state_json jsonb NOT NULL,
  scheduled_due_at timestamptz NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  source text NOT NULL CHECK (source IN ('learn_submit', 'review_submit', 'manual_adjust')),
  request_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  title text NOT NULL,
  content_markdown text NOT NULL DEFAULT '',
  agent_draft_content text,
  is_user_edited boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS idempotency_records (
  key text PRIMARY KEY,
  operation text NOT NULL,
  request_hash text NOT NULL,
  response_json jsonb NOT NULL,
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  invalidated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE idempotency_records
  ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS invalidated_at timestamptz;

ALTER TABLE exercises
  ADD COLUMN IF NOT EXISTS requires_explanation boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE knowledge_points
  ADD COLUMN IF NOT EXISTS lesson_outline_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS lesson_sources_json jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE learning_sessions
  ADD COLUMN IF NOT EXISTS request_id text,
  ADD COLUMN IF NOT EXISTS learning_stage text,
  ADD COLUMN IF NOT EXISTS learning_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS review_stage text,
  ADD COLUMN IF NOT EXISTS review_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE attempts
  ADD COLUMN IF NOT EXISTS test_results_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS stdout text,
  ADD COLUMN IF NOT EXISTS stderr text,
  ADD COLUMN IF NOT EXISTS error_message text,
  ADD COLUMN IF NOT EXISTS error_cause text,
  ADD COLUMN IF NOT EXISTS hint_usage_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS error_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS explanation_text text,
  ADD COLUMN IF NOT EXISTS explanation_check_result jsonb,
  ADD COLUMN IF NOT EXISTS evaluation_status text NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS request_id text;

ALTER TABLE review_states
  ADD COLUMN IF NOT EXISTS last_fsrs_rating text,
  ADD COLUMN IF NOT EXISTS scheduler_version text NOT NULL DEFAULT 'fsrs_v1_default',
  ADD COLUMN IF NOT EXISTS suspended_at timestamptz;

DO $$
BEGIN
  ALTER TABLE runtime_profiles
    DROP CONSTRAINT IF EXISTS runtime_profiles_runtime_tier_check;
  ALTER TABLE runtime_profiles
    ADD CONSTRAINT runtime_profiles_runtime_tier_check
    CHECK (runtime_tier IN ('browser_preview', 'python_stdout_test', 'node_typescript_test', 'sql_query_test', 'managed_compiled_test', 'compiled_sandbox_later'));

  ALTER TABLE runtime_profiles
    DROP CONSTRAINT IF EXISTS runtime_profiles_language_check;
  ALTER TABLE runtime_profiles
    ADD CONSTRAINT runtime_profiles_language_check
    CHECK (language IN ('javascript', 'python', 'typescript', 'sql', 'java', 'go', 'csharp', 'cpp', 'html_css'));

  ALTER TABLE runtime_profiles
    DROP CONSTRAINT IF EXISTS runtime_profiles_runner_check;
  ALTER TABLE runtime_profiles
    ADD CONSTRAINT runtime_profiles_runner_check
    CHECK (runner IN ('browser', 'python', 'node', 'sql', 'compiled', 'sandbox'));

  UPDATE language_courses
    SET archived_at = COALESCE(archived_at, now())
    WHERE archived_at IS NULL
      AND (slug IN ('course_cpp_basic_placeholder') OR language IN ('cpp', 'rust'));

  ALTER TABLE language_courses
    DROP CONSTRAINT IF EXISTS language_courses_language_check;
  ALTER TABLE language_courses
    ADD CONSTRAINT language_courses_language_check
    CHECK (language IN ('javascript', 'python', 'typescript', 'sql', 'java', 'go', 'csharp', 'html_css')) NOT VALID;

  ALTER TABLE learning_plans
    DROP CONSTRAINT IF EXISTS learning_plans_language_check;
  ALTER TABLE learning_plans
    ADD CONSTRAINT learning_plans_language_check
    CHECK (language IN ('javascript', 'python', 'typescript', 'sql', 'java', 'go', 'csharp', 'html_css')) NOT VALID;

  ALTER TABLE exercises
    DROP CONSTRAINT IF EXISTS exercises_exercise_type_check;
  ALTER TABLE exercises
    ADD CONSTRAINT exercises_exercise_type_check
    CHECK (exercise_type IN ('code_blank', 'fix_bug', 'implement_function', 'explain_code', 'review_ai_patch'));
END;
$$;

DO $$
BEGIN
  ALTER TABLE learning_sessions
    DROP CONSTRAINT IF EXISTS learning_sessions_learning_stage_check;
  ALTER TABLE learning_sessions
    ADD CONSTRAINT learning_sessions_learning_stage_check
    CHECK (learning_stage IS NULL OR learning_stage IN ('documentation_reading', 'concept_intro', 'concept_check', 'concept_repair', 'practice_offer', 'concept_qna', 'readiness_check', 'practice_support'));
END;
$$;

DO $$
BEGIN
  ALTER TABLE learning_sessions
    DROP CONSTRAINT IF EXISTS learning_sessions_review_stage_check;
  ALTER TABLE learning_sessions
    ADD CONSTRAINT learning_sessions_review_stage_check
    CHECK (review_stage IS NULL OR review_stage IN ('warmup', 'warmup_repair', 'variant_practice', 'exercise', 'exercise_feedback', 'final_summary', 'submitted'));
END;
$$;

DO $$
BEGIN
  ALTER TABLE attempts
    DROP CONSTRAINT IF EXISTS attempts_runtime_status_check;
  ALTER TABLE attempts
    ADD CONSTRAINT attempts_runtime_status_check
    CHECK (runtime_status IN ('success', 'missing_toolchain', 'unsupported', 'compile_error', 'runtime_error', 'timeout', 'test_failure'));
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'attempts_evaluation_status_check'
  ) THEN
    ALTER TABLE attempts
      ADD CONSTRAINT attempts_evaluation_status_check
      CHECK (evaluation_status IN ('pending', 'evaluated', 'needs_manual_review'));
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'review_states_last_fsrs_rating_check'
  ) THEN
    ALTER TABLE review_states
      ADD CONSTRAINT review_states_last_fsrs_rating_check
      CHECK (last_fsrs_rating IS NULL OR last_fsrs_rating IN ('Again', 'Hard', 'Good', 'Easy'));
  END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);
CREATE INDEX IF NOT EXISTS idx_runtime_profiles_language ON runtime_profiles(language);
CREATE INDEX IF NOT EXISTS idx_language_courses_language_level ON language_courses(language, level);
CREATE INDEX IF NOT EXISTS idx_learning_plans_user_status ON learning_plans(user_id, status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_plan_modules_plan_status ON plan_modules(plan_id, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_points_module_status ON knowledge_points(module_id, status);
CREATE INDEX IF NOT EXISTS idx_exercises_knowledge_point ON exercises(knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_exercises_runtime_type ON exercises(runtime_profile_id, exercise_type);
CREATE INDEX IF NOT EXISTS idx_code_blanks_exercise ON code_blanks(exercise_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_exercise_type ON test_cases(exercise_id, case_type);
CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_plan ON learning_sessions(user_id, plan_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_sessions_request_id ON learning_sessions(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_attempts_user_exercise_created ON attempts(user_id, exercise_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attempts_session_created ON attempts(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_exercise_created ON attempts(exercise_id, created_at DESC);
DROP INDEX IF EXISTS uq_attempts_submit_identity;
CREATE UNIQUE INDEX IF NOT EXISTS uq_attempts_request_id ON attempts(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_review_states_user_due ON review_states(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_review_states_last_attempt ON review_states(last_attempt_id) WHERE last_attempt_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_seed_banks_scope ON review_seed_banks(user_id, knowledge_point_id, generator_version);
CREATE INDEX IF NOT EXISTS idx_review_seed_banks_status ON review_seed_banks(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_exercise_variant_cache_scope ON exercise_variant_cache(user_id, knowledge_point_id, template_id, template_version, status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_exercise_variant_cache_last_used ON exercise_variant_cache(user_id, last_used_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS teaching_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
  chunk_type text NOT NULL CHECK (chunk_type IN ('outline', 'example', 'explanation', 'source_note')),
  title text NOT NULL,
  content text NOT NULL,
  source_url text,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(content, '')), 'B')
  ) STORED,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_teaching_chunks_kp ON teaching_chunks(knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_teaching_chunks_search ON teaching_chunks USING GIN(search_vector);

CREATE TABLE IF NOT EXISTS grounding_chunks (
  chunk_id text PRIMARY KEY,
  source_id text NOT NULL,
  language_id text NOT NULL,
  title text NOT NULL,
  section_path_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  canonical_url text NOT NULL,
  source_type text NOT NULL CHECK (source_type IN ('tutorial', 'reference', 'spec', 'platform_docs', 'vendor_docs')),
  source_trust_tier text NOT NULL CHECK (source_trust_tier IN ('official', 'trusted_de_facto', 'internal')),
  fetched_at timestamptz NOT NULL,
  content_hash text NOT NULL,
  content text NOT NULL,
  topic_tags_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(content, '')), 'B')
  ) STORED,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS grounding_reindex_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mode text NOT NULL CHECK (mode IN ('fixture', 'fetch')),
  status text NOT NULL CHECK (status IN ('completed', 'completed_with_failures', 'failed')),
  total_sources integer NOT NULL DEFAULT 0 CHECK (total_sources >= 0),
  total_documents integer NOT NULL DEFAULT 0 CHECK (total_documents >= 0),
  total_chunks integer NOT NULL DEFAULT 0 CHECK (total_chunks >= 0),
  total_failures integer NOT NULL DEFAULT 0 CHECK (total_failures >= 0),
  source_reports_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_grounding_chunks_language ON grounding_chunks(language_id);
CREATE INDEX IF NOT EXISTS idx_grounding_chunks_source ON grounding_chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_grounding_chunks_search ON grounding_chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_grounding_reindex_runs_created ON grounding_reindex_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_logs_kp_reviewed ON review_logs(knowledge_point_id, reviewed_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_logs_request_id ON review_logs(request_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_logs_attempt_rating_source ON review_logs(attempt_id, rating, source);
CREATE INDEX IF NOT EXISTS idx_notes_user_updated ON notes(user_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_notes_knowledge_point ON notes(knowledge_point_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_notes_user_knowledge_point_active ON notes(user_id, knowledge_point_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_idempotency_records_operation ON idempotency_records(operation);
CREATE INDEX IF NOT EXISTS idx_idempotency_records_user_active ON idempotency_records(user_id) WHERE invalidated_at IS NULL;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_runtime_profiles_updated_at ON runtime_profiles;
CREATE TRIGGER trg_runtime_profiles_updated_at BEFORE UPDATE ON runtime_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_language_courses_updated_at ON language_courses;
CREATE TRIGGER trg_language_courses_updated_at BEFORE UPDATE ON language_courses
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_learning_plans_updated_at ON learning_plans;
CREATE TRIGGER trg_learning_plans_updated_at BEFORE UPDATE ON learning_plans
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_plan_modules_updated_at ON plan_modules;
CREATE TRIGGER trg_plan_modules_updated_at BEFORE UPDATE ON plan_modules
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_points_updated_at ON knowledge_points;
CREATE TRIGGER trg_knowledge_points_updated_at BEFORE UPDATE ON knowledge_points
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_exercises_updated_at ON exercises;
CREATE TRIGGER trg_exercises_updated_at BEFORE UPDATE ON exercises
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_test_cases_updated_at ON test_cases;
CREATE TRIGGER trg_test_cases_updated_at BEFORE UPDATE ON test_cases
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_learning_sessions_updated_at ON learning_sessions;
CREATE TRIGGER trg_learning_sessions_updated_at BEFORE UPDATE ON learning_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_review_states_updated_at ON review_states;
CREATE TRIGGER trg_review_states_updated_at BEFORE UPDATE ON review_states
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_review_seed_banks_updated_at ON review_seed_banks;
CREATE TRIGGER trg_review_seed_banks_updated_at BEFORE UPDATE ON review_seed_banks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_notes_updated_at ON notes;
CREATE TRIGGER trg_notes_updated_at BEFORE UPDATE ON notes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_grounding_chunks_updated_at ON grounding_chunks;
CREATE TRIGGER trg_grounding_chunks_updated_at BEFORE UPDATE ON grounding_chunks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Onboarding conversation tables
CREATE TABLE IF NOT EXISTS onboarding_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'plan_proposed', 'confirmed', 'abandoned')),
  extracted_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS onboarding_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES onboarding_conversations(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learning_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_conversations_user ON onboarding_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_messages_conversation ON onboarding_messages(conversation_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_onboarding_messages_client_id ON onboarding_messages(client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_review_messages_session ON review_messages(review_session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_messages_client_id ON review_messages(client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_learning_messages_kp_session_created ON learning_messages(knowledge_point_id, session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_messages_client_id ON learning_messages(client_message_id) WHERE client_message_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_onboarding_conversations_updated_at ON onboarding_conversations;
CREATE TRIGGER trg_onboarding_conversations_updated_at BEFORE UPDATE ON onboarding_conversations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

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
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_messages_id_conversation UNIQUE (id, conversation_id)
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
  priority integer NOT NULL DEFAULT 0 CHECK (priority BETWEEN 0 AND 100),
  retention_until timestamptz NOT NULL,
  stale_after timestamptz NOT NULL,
  state text NOT NULL CHECK (state IN ('pending', 'no_action', 'stale', 'failed')),
  idempotency_key text NOT NULL UNIQUE CHECK (char_length(idempotency_key) <= 160),
  envelope_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_outbox_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CHECK (stale_after <= retention_until)
);

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
  outbox_id uuid NOT NULL,
  proposal_id uuid NOT NULL,
  summary text NOT NULL CHECK (char_length(summary) BETWEEN 1 AND 280),
  policy_version text NOT NULL CHECK (char_length(policy_version) <= 160),
  memory_setting_version text NOT NULL CHECK (char_length(memory_setting_version) <= 160),
  retention_until timestamptz NOT NULL,
  stale_after timestamptz NOT NULL,
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_context_summary_outbox UNIQUE (outbox_id),
  CONSTRAINT uq_tutor_context_summary_proposal UNIQUE (proposal_id),
  CONSTRAINT fk_tutor_context_summary_run_user
    FOREIGN KEY (run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_outbox_run
    FOREIGN KEY (outbox_id, run_id)
    REFERENCES tutor_memory_curation_outbox(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_summary_proposal_outbox
    FOREIGN KEY (proposal_id, outbox_id)
    REFERENCES tutor_curation_proposals(id, outbox_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_context_summary_retention CHECK (stale_after <= retention_until)
);

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

-- Child 08-02 conversation TurnRun/history contract: additive and repeatable.
-- Legacy messages remain readable; only new interactive turns receive a public-process projection.
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS title text;
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS last_public_activity_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS superseded_by_run_id uuid;
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS continuation_kind text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'fk_tutor_runs_superseded_by_run'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT fk_tutor_runs_superseded_by_run
      FOREIGN KEY (superseded_by_run_id) REFERENCES tutor_runs(id) ON DELETE RESTRICT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_conversations'::regclass
      AND conname = 'chk_tutor_conversations_title'
  ) THEN
    ALTER TABLE tutor_conversations
      ADD CONSTRAINT chk_tutor_conversations_title
      CHECK (title IS NULL OR (char_length(title) BETWEEN 1 AND 48 AND title !~ '[\r\n\t]'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'chk_tutor_runs_continuation_kind'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT chk_tutor_runs_continuation_kind
      CHECK (continuation_kind IS NULL OR continuation_kind IN ('approval', 'capability_result', 'external_result'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_run_public_processes (
  run_id uuid PRIMARY KEY REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  projection_version text NOT NULL DEFAULT 'tutor_public_process_v1'
    CHECK (projection_version = 'tutor_public_process_v1'),
  display_state text NOT NULL CHECK (display_state IN ('thinking', 'completed', 'superseded', 'unavailable')),
  current_step_key text NOT NULL CHECK (current_step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'learning_reply_generated', 'replaced_by_newer_input'
  )),
  tutor_message_id uuid REFERENCES tutor_messages(id) ON DELETE RESTRICT,
  started_at timestamptz NOT NULL,
  last_public_activity_at timestamptz NOT NULL,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_public_process_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_public_process_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_public_process_message_conversation
    FOREIGN KEY (tutor_message_id, conversation_id) REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_public_process_finished_state CHECK (
    (display_state = 'thinking' AND finished_at IS NULL)
    OR (display_state IN ('completed', 'superseded', 'unavailable') AND finished_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_run_public_process_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  ordinal integer NOT NULL CHECK (ordinal >= 1),
  step_key text NOT NULL CHECK (step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'learning_reply_generated', 'replaced_by_newer_input'
  )),
  state text NOT NULL CHECK (state IN ('completed', 'current')),
  occurred_at timestamptz NOT NULL,
  UNIQUE (run_id, ordinal)
);

-- One live foreground interactive run is allowed per learner conversation.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runs_interactive_foreground
  ON tutor_runs (conversation_id)
  WHERE origin = 'interactive'
    AND terminal_outcome IS NULL
    AND cancelled_at IS NULL
    AND superseded_by_run_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_conversations_public_activity
  ON tutor_conversations (user_id, last_public_activity_at DESC, id DESC)
  WHERE visibility = 'learner' AND kind = 'interactive' AND status = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_public_processes_conversation_activity
  ON tutor_run_public_processes (conversation_id, last_public_activity_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_public_process_steps_run_ordinal
  ON tutor_run_public_process_steps (run_id, ordinal);

DROP TRIGGER IF EXISTS trg_tutor_public_processes_updated_at ON tutor_run_public_processes;
CREATE TRIGGER trg_tutor_public_processes_updated_at BEFORE UPDATE ON tutor_run_public_processes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- Child 08-04 LearningTrack domain: additive track-scoped teaching authority.
-- This state is isolated from retired learning_* tables and the user-level tutor_plan_revisions contract.
CREATE TABLE IF NOT EXISTS tutor_learning_tracks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  language_id text NOT NULL CHECK (char_length(language_id) BETWEEN 1 AND 80),
  goal_text text NOT NULL CHECK (char_length(goal_text) BETWEEN 1 AND 2000),
  target_level text NOT NULL CHECK (char_length(target_level) BETWEEN 1 AND 120),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
  current_knowledge_key text CHECK (
    current_knowledge_key IS NULL OR current_knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  last_learned_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  CONSTRAINT uq_tutor_learning_tracks_id_user UNIQUE (id, user_id),
  CONSTRAINT chk_tutor_learning_tracks_archive_state CHECK (
    (status = 'archived') = (archived_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_track_plan_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  predecessor_revision_id uuid,
  status text NOT NULL CHECK (status IN ('proposed', 'active', 'superseded', 'rejected')),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  target_level text NOT NULL CHECK (char_length(target_level) BETWEEN 1 AND 120),
  plan_json jsonb NOT NULL CHECK (jsonb_typeof(plan_json) = 'object'),
  generator_version text NOT NULL CHECK (char_length(generator_version) BETWEEN 1 AND 160),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  change_reason text NOT NULL CHECK (char_length(change_reason) BETWEEN 1 AND 600),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  CONSTRAINT uq_tutor_track_plan_revisions_id_scope UNIQUE (id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_revision_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_revision_predecessor_scope
    FOREIGN KEY (predecessor_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_track_plan_revision_predecessor_distinct CHECK (
    predecessor_revision_id IS NULL OR predecessor_revision_id <> id
  ),
  CONSTRAINT chk_tutor_track_plan_revision_activation CHECK (
    (status IN ('active', 'superseded')) = (activated_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_track_active_plans (
  track_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_track_active_plans_scope UNIQUE (track_id, user_id),
  CONSTRAINT fk_tutor_track_active_plan_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_active_plan_revision_scope
    FOREIGN KEY (revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_track_plan_modules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id uuid NOT NULL,
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  module_key text NOT NULL CHECK (module_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
  order_index integer NOT NULL CHECK (order_index >= 0),
  is_core boolean NOT NULL DEFAULT true,
  is_skippable boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_track_plan_modules_revision_key UNIQUE (revision_id, module_key),
  CONSTRAINT uq_tutor_track_plan_modules_revision_order UNIQUE (revision_id, order_index),
  CONSTRAINT uq_tutor_track_plan_modules_id_scope UNIQUE (id, revision_id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_module_revision_scope
    FOREIGN KEY (revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_track_plan_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  module_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
  order_index integer NOT NULL CHECK (order_index >= 0),
  is_core boolean NOT NULL DEFAULT true,
  prerequisite_keys_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(prerequisite_keys_json) = 'array'),
  required_capabilities_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_track_plan_nodes_revision_key UNIQUE (revision_id, knowledge_key),
  CONSTRAINT uq_tutor_track_plan_nodes_revision_scope_key UNIQUE (revision_id, track_id, user_id, knowledge_key),
  CONSTRAINT uq_tutor_track_plan_nodes_module_order UNIQUE (module_id, order_index),
  CONSTRAINT uq_tutor_track_plan_nodes_id_scope UNIQUE (id, revision_id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_node_module_scope
    FOREIGN KEY (module_id, revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_modules(id, revision_id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_node_revision_scope
    FOREIGN KEY (revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_track_node_progress (
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  status text NOT NULL CHECK (status IN (
    'locked', 'available', 'in_progress', 'completed', 'review_due', 'diagnostic_skipped'
  )),
  source_plan_revision_id uuid NOT NULL,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, knowledge_key),
  CONSTRAINT uq_tutor_track_node_progress_scope UNIQUE (track_id, user_id, knowledge_key),
  CONSTRAINT fk_tutor_track_node_progress_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_node_progress_revision_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_node_progress_source_node
    FOREIGN KEY (source_plan_revision_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_track_node_progress_times CHECK (
    (status IN ('in_progress', 'completed', 'review_due', 'diagnostic_skipped')) = (started_at IS NOT NULL)
    AND (status IN ('completed', 'review_due', 'diagnostic_skipped')) = (completed_at IS NOT NULL)
  )
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_learning_tracks'::regclass
      AND conname = 'fk_tutor_learning_track_current_progress'
  ) THEN
    ALTER TABLE tutor_learning_tracks
      ADD CONSTRAINT fk_tutor_learning_track_current_progress
      FOREIGN KEY (id, user_id, current_knowledge_key)
      REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key)
      ON DELETE RESTRICT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_track_plan_revisions'::regclass
      AND conname = 'chk_tutor_track_plan_revision_predecessor_distinct'
  ) THEN
    ALTER TABLE tutor_track_plan_revisions
      ADD CONSTRAINT chk_tutor_track_plan_revision_predecessor_distinct CHECK (
        predecessor_revision_id IS NULL OR predecessor_revision_id <> id
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_track_plan_nodes'::regclass
      AND conname = 'uq_tutor_track_plan_nodes_revision_scope_key'
  ) THEN
    ALTER TABLE tutor_track_plan_nodes
      ADD CONSTRAINT uq_tutor_track_plan_nodes_revision_scope_key
      UNIQUE (revision_id, track_id, user_id, knowledge_key);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_track_node_progress'::regclass
      AND conname = 'fk_tutor_track_node_progress_source_node'
  ) THEN
    ALTER TABLE tutor_track_node_progress
      ADD CONSTRAINT fk_tutor_track_node_progress_source_node
      FOREIGN KEY (source_plan_revision_id, track_id, user_id, knowledge_key)
      REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key)
      ON DELETE RESTRICT;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_track_plan_migrations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  from_revision_id uuid NOT NULL,
  to_revision_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'rejected', 'applied')),
  impact_json jsonb NOT NULL CHECK (jsonb_typeof(impact_json) = 'object'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  applied_at timestamptz,
  CONSTRAINT uq_tutor_track_plan_migrations_track_key UNIQUE (track_id, idempotency_key),
  CONSTRAINT uq_tutor_track_plan_migrations_revision UNIQUE (track_id, to_revision_id),
  CONSTRAINT uq_tutor_track_plan_migrations_id_scope UNIQUE (id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_migration_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_migration_from_scope
    FOREIGN KEY (from_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_migration_to_scope
    FOREIGN KEY (to_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_track_plan_migration_distinct CHECK (from_revision_id <> to_revision_id),
  CONSTRAINT chk_tutor_track_plan_migration_times CHECK (
    (status IN ('confirmed', 'applied')) = (confirmed_at IS NOT NULL)
    AND ((status = 'applied') = (applied_at IS NOT NULL))
  )
);

DO $$
BEGIN
  -- Upgrade databases bootstrapped by an earlier draft whose implication-only
  -- checks did not require lifecycle timestamps for progressed/applied rows.
  ALTER TABLE tutor_track_node_progress
    DROP CONSTRAINT IF EXISTS chk_tutor_track_node_progress_times;
  ALTER TABLE tutor_track_node_progress
    ADD CONSTRAINT chk_tutor_track_node_progress_times CHECK (
      (status IN ('in_progress', 'completed', 'review_due', 'diagnostic_skipped')) = (started_at IS NOT NULL)
      AND (status IN ('completed', 'review_due', 'diagnostic_skipped')) = (completed_at IS NOT NULL)
    );

  ALTER TABLE tutor_track_plan_migrations
    DROP CONSTRAINT IF EXISTS chk_tutor_track_plan_migration_times;
  ALTER TABLE tutor_track_plan_migrations
    ADD CONSTRAINT chk_tutor_track_plan_migration_times CHECK (
      (status IN ('confirmed', 'applied')) = (confirmed_at IS NOT NULL)
      AND ((status = 'applied') = (applied_at IS NOT NULL))
    );
END $$;

CREATE TABLE IF NOT EXISTS tutor_mastery_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind IN (
    'gate', 'module_diagnostic', 'review', 'model_code_review', 'trusted_import'
  )),
  source_receipt_id text NOT NULL CHECK (char_length(source_receipt_id) BETWEEN 1 AND 160),
  source_receipt_hash text NOT NULL CHECK (source_receipt_hash ~ '^[0-9a-f]{64}$'),
  independence text NOT NULL CHECK (independence IN ('independent', 'hinted', 'remediated')),
  score double precision NOT NULL CHECK (score >= 0 AND score <= 1),
  hint_count integer NOT NULL DEFAULT 0 CHECK (hint_count >= 0),
  attempt_count integer NOT NULL DEFAULT 1 CHECK (attempt_count >= 1),
  evidence_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence_summary_json) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_mastery_evidence_receipt UNIQUE (track_id, evidence_kind, source_receipt_id),
  CONSTRAINT uq_tutor_mastery_evidence_id_scope UNIQUE (id, track_id, user_id, knowledge_key),
  CONSTRAINT fk_tutor_mastery_evidence_progress_scope
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_mastery_states (
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  confidence double precision NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
  mastery_level text NOT NULL DEFAULT 'unseen' CHECK (mastery_level IN (
    'unseen', 'emerging', 'developing', 'proficient', 'durable'
  )),
  strengths_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(strengths_json) = 'array'),
  weaknesses_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(weaknesses_json) = 'array'),
  evidence_count integer NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
  last_evidence_id uuid,
  projector_version text NOT NULL CHECK (char_length(projector_version) BETWEEN 1 AND 160),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, knowledge_key),
  CONSTRAINT uq_tutor_mastery_states_scope UNIQUE (track_id, user_id, knowledge_key),
  CONSTRAINT fk_tutor_mastery_state_progress_scope
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_mastery_state_last_evidence_scope
    FOREIGN KEY (last_evidence_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_mastery_evidence(id, track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_mastery_state_evidence CHECK (
    (evidence_count = 0) = (last_evidence_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_conversation_learning_scopes (
  conversation_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  scope_kind text NOT NULL DEFAULT 'general' CHECK (scope_kind IN ('general', 'plan_drafting', 'learning_track')),
  learning_track_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversation_learning_scopes_scope UNIQUE (conversation_id, user_id),
  CONSTRAINT fk_tutor_conversation_learning_scope_conversation_user
    FOREIGN KEY (conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_conversation_learning_scope_track_user
    FOREIGN KEY (learning_track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_conversation_learning_scope_shape CHECK (
    (scope_kind = 'learning_track' AND learning_track_id IS NOT NULL)
    OR (scope_kind IN ('general', 'plan_drafting') AND learning_track_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_run_learning_scopes (
  run_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  scope_kind text NOT NULL CHECK (scope_kind IN ('general', 'plan_drafting', 'learning_track')),
  learning_track_id uuid,
  task_kind text NOT NULL CHECK (task_kind IN (
    'general_tutor', 'plan_drafting', 'lesson_teaching', 'exercise_feedback',
    'review_coaching', 'model_code_review', 'remediation'
  )),
  knowledge_key text CHECK (knowledge_key IS NULL OR knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  scope_version integer NOT NULL CHECK (scope_version >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_run_learning_scopes_scope UNIQUE (run_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_run_learning_scope_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_conversation_user
    FOREIGN KEY (conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_track_user
    FOREIGN KEY (learning_track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_progress
    FOREIGN KEY (learning_track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_run_learning_scope_shape CHECK (
    (scope_kind = 'general' AND learning_track_id IS NULL AND knowledge_key IS NULL AND task_kind = 'general_tutor')
    OR (scope_kind = 'plan_drafting' AND learning_track_id IS NULL AND knowledge_key IS NULL AND task_kind = 'plan_drafting')
    OR (
      scope_kind = 'learning_track'
      AND learning_track_id IS NOT NULL
      AND task_kind IN ('lesson_teaching', 'exercise_feedback', 'review_coaching', 'model_code_review', 'remediation')
    )
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_track_plan_revisions_one_active
  ON tutor_track_plan_revisions(track_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_learning_tracks_user_updated
  ON tutor_learning_tracks(user_id, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_track_plan_revisions_track_created
  ON tutor_track_plan_revisions(track_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_track_plan_nodes_revision_order
  ON tutor_track_plan_nodes(revision_id, module_id, order_index);
CREATE INDEX IF NOT EXISTS idx_tutor_track_node_progress_user_status
  ON tutor_track_node_progress(user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_track_plan_migrations_track_created
  ON tutor_track_plan_migrations(track_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_mastery_evidence_track_key_created
  ON tutor_mastery_evidence(track_id, knowledge_key, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tutor_conversation_learning_scopes_user_track
  ON tutor_conversation_learning_scopes(user_id, learning_track_id);
CREATE INDEX IF NOT EXISTS idx_tutor_run_learning_scopes_user_track
  ON tutor_run_learning_scopes(user_id, learning_track_id, created_at DESC);

CREATE OR REPLACE FUNCTION tutor_learning_track_purge_allowed(target_user_id uuid)
RETURNS boolean AS $$
BEGIN
  RETURN current_setting('aearn.learning_track_purge_user_id', true) = target_user_id::text;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_track_plan_revision_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'active' AND NEW.predecessor_revision_id IS NULL AND NEW.activated_at IS NOT NULL THEN
      RETURN NEW;
    END IF;
    IF NEW.status = 'proposed' AND NEW.predecessor_revision_id IS NOT NULL AND NEW.activated_at IS NULL THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Tutor track plan revision initial lifecycle is invalid' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF NOT tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RAISE EXCEPTION 'Tutor track plan revisions are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.predecessor_revision_id IS DISTINCT FROM OLD.predecessor_revision_id
     OR NEW.title IS DISTINCT FROM OLD.title
     OR NEW.target_level IS DISTINCT FROM OLD.target_level
     OR NEW.plan_json IS DISTINCT FROM OLD.plan_json
     OR NEW.generator_version IS DISTINCT FROM OLD.generator_version
     OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
     OR NEW.change_reason IS DISTINCT FROM OLD.change_reason
     OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Tutor track plan revision content is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status IN ('proposed', 'active', 'rejected') THEN
    NULL;
  ELSIF OLD.status = 'active' AND NEW.status IN ('active', 'superseded') THEN
    NULL;
  ELSIF OLD.status = NEW.status AND OLD.status IN ('superseded', 'rejected') THEN
    NULL;
  ELSE
    RAISE EXCEPTION 'Tutor track plan revision lifecycle transition is invalid' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = NEW.status AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
    RAISE EXCEPTION 'Tutor track plan revision activation timestamp is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'active'
     AND (OLD.activated_at IS NOT NULL OR NEW.activated_at IS NULL) THEN
    RAISE EXCEPTION 'Tutor track plan revision activation timestamp is invalid' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'rejected'
     AND NEW.activated_at IS NOT NULL THEN
    RAISE EXCEPTION 'Rejected Tutor track plan revision cannot be activated' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'active' AND NEW.status = 'superseded'
     AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
    RAISE EXCEPTION 'Superseded Tutor track plan revision must preserve activation time' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_track_plan_structure_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor track plan structure is immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_track_plan_migration_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'proposed' AND NEW.confirmed_at IS NULL AND NEW.applied_at IS NULL THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Tutor track plan migration initial lifecycle is invalid' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Tutor track plan migration evidence is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.from_revision_id IS DISTINCT FROM OLD.from_revision_id
     OR NEW.to_revision_id IS DISTINCT FROM OLD.to_revision_id
     OR NEW.impact_json IS DISTINCT FROM OLD.impact_json
     OR NEW.expected_track_version IS DISTINCT FROM OLD.expected_track_version
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Tutor track plan migration evidence is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = NEW.status
     AND (
       NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
       OR NEW.applied_at IS DISTINCT FROM OLD.applied_at
     ) THEN
    RAISE EXCEPTION 'Tutor track plan migration timestamps are immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'proposed' THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'confirmed'
     AND OLD.confirmed_at IS NULL AND NEW.confirmed_at IS NOT NULL AND NEW.applied_at IS NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'applied'
     AND OLD.confirmed_at IS NULL AND NEW.confirmed_at IS NOT NULL AND NEW.applied_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'rejected'
     AND NEW.confirmed_at IS NULL AND NEW.applied_at IS NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'confirmed' AND NEW.status = 'confirmed' THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'confirmed' AND NEW.status = 'applied'
     AND NEW.confirmed_at IS NOT DISTINCT FROM OLD.confirmed_at AND NEW.applied_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = NEW.status AND OLD.status IN ('applied', 'rejected') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Tutor track plan migration lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_mastery_evidence_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor mastery evidence is append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_run_learning_scope_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor run learning scope is immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_track_current_key_active()
RETURNS trigger AS $$
BEGIN
  IF NEW.current_knowledge_key IS NULL THEN
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM tutor_track_active_plans AS active
    JOIN tutor_track_plan_nodes AS nodes
      ON (nodes.revision_id, nodes.track_id, nodes.user_id) =
         (active.revision_id, active.track_id, active.user_id)
    JOIN tutor_track_node_progress AS progress
      ON (progress.track_id, progress.user_id, progress.knowledge_key) =
         (nodes.track_id, nodes.user_id, nodes.knowledge_key)
    WHERE active.track_id = NEW.id
      AND active.user_id = NEW.user_id
      AND nodes.knowledge_key = NEW.current_knowledge_key
  ) THEN
    RAISE EXCEPTION 'Tutor learning track current key must belong to the active plan' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_track_active_plan_consistency()
RETURNS trigger AS $$
DECLARE
  target_track_id uuid;
  target_user_id uuid;
  target_revision_id uuid;
  target_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Tutor track active pointer cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF TG_TABLE_NAME = 'tutor_track_active_plans' THEN
    target_track_id := NEW.track_id;
    target_user_id := NEW.user_id;
    target_revision_id := NEW.revision_id;
    SELECT status INTO target_status
    FROM tutor_track_plan_revisions
    WHERE id = target_revision_id AND track_id = target_track_id AND user_id = target_user_id;
    IF target_status IS DISTINCT FROM 'active' THEN
      RAISE EXCEPTION 'Tutor track active pointer must reference an active revision' USING ERRCODE = '23514';
    END IF;
  ELSE
    target_track_id := NEW.track_id;
    target_user_id := NEW.user_id;
    target_revision_id := NEW.id;
    target_status := NEW.status;
    IF target_status = 'active' AND NOT EXISTS (
      SELECT 1 FROM tutor_track_active_plans
      WHERE track_id = target_track_id AND user_id = target_user_id AND revision_id = target_revision_id
    ) THEN
      RAISE EXCEPTION 'Active Tutor track revision must be the active pointer' USING ERRCODE = '23514';
    END IF;
    IF target_status <> 'active' AND EXISTS (
      SELECT 1 FROM tutor_track_active_plans
      WHERE track_id = target_track_id AND user_id = target_user_id AND revision_id = target_revision_id
    ) THEN
      RAISE EXCEPTION 'Tutor track active pointer cannot reference a non-active revision' USING ERRCODE = '23514';
    END IF;
  END IF;
  IF target_status = 'active' AND EXISTS (
    SELECT 1
    FROM tutor_learning_tracks AS tracks
    WHERE tracks.id = target_track_id
      AND tracks.user_id = target_user_id
      AND tracks.current_knowledge_key IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM tutor_track_plan_nodes AS nodes
        WHERE nodes.revision_id = target_revision_id
          AND nodes.track_id = target_track_id
          AND nodes.user_id = target_user_id
          AND nodes.knowledge_key = tracks.current_knowledge_key
      )
  ) THEN
    RAISE EXCEPTION 'Tutor learning track current key must belong to the active revision' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_learning_tracks_updated_at ON tutor_learning_tracks;
CREATE TRIGGER trg_tutor_learning_tracks_updated_at BEFORE UPDATE ON tutor_learning_tracks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_learning_tracks_current_key_active ON tutor_learning_tracks;
CREATE TRIGGER trg_tutor_learning_tracks_current_key_active
BEFORE INSERT OR UPDATE OF current_knowledge_key ON tutor_learning_tracks
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_track_current_key_active();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_revisions_immutable ON tutor_track_plan_revisions;
CREATE TRIGGER trg_tutor_track_plan_revisions_immutable
BEFORE INSERT OR UPDATE OR DELETE ON tutor_track_plan_revisions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_revision_immutable();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_revisions_active_consistency ON tutor_track_plan_revisions;
CREATE CONSTRAINT TRIGGER trg_tutor_track_plan_revisions_active_consistency
AFTER INSERT OR UPDATE ON tutor_track_plan_revisions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_active_plan_consistency();

DROP TRIGGER IF EXISTS trg_tutor_track_active_plans_updated_at ON tutor_track_active_plans;
CREATE TRIGGER trg_tutor_track_active_plans_updated_at BEFORE UPDATE ON tutor_track_active_plans
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_track_active_plans_consistency ON tutor_track_active_plans;
CREATE CONSTRAINT TRIGGER trg_tutor_track_active_plans_consistency
AFTER INSERT OR UPDATE OR DELETE ON tutor_track_active_plans
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_active_plan_consistency();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_modules_immutable ON tutor_track_plan_modules;
CREATE TRIGGER trg_tutor_track_plan_modules_immutable
BEFORE UPDATE OR DELETE ON tutor_track_plan_modules
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_structure_immutable();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_nodes_immutable ON tutor_track_plan_nodes;
CREATE TRIGGER trg_tutor_track_plan_nodes_immutable
BEFORE UPDATE OR DELETE ON tutor_track_plan_nodes
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_structure_immutable();

DROP TRIGGER IF EXISTS trg_tutor_track_node_progress_updated_at ON tutor_track_node_progress;
CREATE TRIGGER trg_tutor_track_node_progress_updated_at BEFORE UPDATE ON tutor_track_node_progress
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_migrations_lifecycle ON tutor_track_plan_migrations;
CREATE TRIGGER trg_tutor_track_plan_migrations_lifecycle
BEFORE INSERT OR UPDATE OR DELETE ON tutor_track_plan_migrations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_migration_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_mastery_evidence_immutable ON tutor_mastery_evidence;
CREATE TRIGGER trg_tutor_mastery_evidence_immutable
BEFORE UPDATE OR DELETE ON tutor_mastery_evidence
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_mastery_evidence_immutable();

DROP TRIGGER IF EXISTS trg_tutor_mastery_states_updated_at ON tutor_mastery_states;
CREATE TRIGGER trg_tutor_mastery_states_updated_at BEFORE UPDATE ON tutor_mastery_states
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_conversation_learning_scopes_updated_at ON tutor_conversation_learning_scopes;
CREATE TRIGGER trg_tutor_conversation_learning_scopes_updated_at BEFORE UPDATE ON tutor_conversation_learning_scopes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_run_learning_scopes_immutable ON tutor_run_learning_scopes;
CREATE TRIGGER trg_tutor_run_learning_scopes_immutable
BEFORE UPDATE OR DELETE ON tutor_run_learning_scopes
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_learning_scope_immutable();
