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

-- Child 08-21 closed planning-intent taxonomy and published-course metadata.
CREATE TABLE IF NOT EXISTS tutor_learning_intents (
  intent_key text PRIMARY KEY CHECK (intent_key ~ '^[a-z][a-z0-9_]{1,63}$'),
  display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 120),
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'planned', 'retired')),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS language_course_intent_tags (
  course_id uuid NOT NULL REFERENCES language_courses(id) ON DELETE RESTRICT,
  intent_key text NOT NULL REFERENCES tutor_learning_intents(intent_key) ON DELETE RESTRICT,
  relevance_rank integer NOT NULL CHECK (relevance_rank BETWEEN 0 AND 100),
  is_primary boolean NOT NULL DEFAULT false,
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (course_id, intent_key)
);

CREATE INDEX IF NOT EXISTS idx_language_course_intent_tags_intent_rank
  ON language_course_intent_tags(intent_key, relevance_rank DESC, course_id);
CREATE INDEX IF NOT EXISTS idx_language_course_intent_tags_course_rank
  ON language_course_intent_tags(course_id, relevance_rank DESC, intent_key);

DROP TRIGGER IF EXISTS trg_tutor_learning_intents_updated_at ON tutor_learning_intents;
CREATE TRIGGER trg_tutor_learning_intents_updated_at
BEFORE UPDATE ON tutor_learning_intents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_language_course_intent_tags_updated_at ON language_course_intent_tags;
CREATE TRIGGER trg_language_course_intent_tags_updated_at
BEFORE UPDATE ON language_course_intent_tags
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION assert_language_course_intent_coverage()
RETURNS void AS $$
DECLARE
  missing_courses text;
  missing_intents text;
BEGIN
  SELECT string_agg(courses.slug, ',' ORDER BY courses.slug)
  INTO missing_courses
  FROM language_courses AS courses
  WHERE courses.archived_at IS NULL
    AND NOT EXISTS (
      SELECT 1
      FROM language_course_intent_tags AS tags
      JOIN tutor_learning_intents AS intents
        ON intents.intent_key = tags.intent_key AND intents.state = 'active'
      WHERE tags.course_id = courses.id
    );

  IF missing_courses IS NOT NULL THEN
    RAISE EXCEPTION 'language_course_intent_coverage_missing: active courses without tags: %', missing_courses
      USING ERRCODE = '23514';
  END IF;

  SELECT string_agg(intents.intent_key, ',' ORDER BY intents.intent_key)
  INTO missing_intents
  FROM tutor_learning_intents AS intents
  WHERE intents.state = 'active'
    AND NOT EXISTS (
      SELECT 1
      FROM language_course_intent_tags AS tags
      JOIN language_courses AS courses
        ON courses.id = tags.course_id AND courses.archived_at IS NULL
      WHERE tags.intent_key = intents.intent_key
    );

  IF missing_intents IS NOT NULL THEN
    RAISE EXCEPTION 'language_course_intent_coverage_missing: active intents without courses: %', missing_intents
      USING ERRCODE = '23514';
  END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_language_course_intent_coverage()
RETURNS trigger AS $$
BEGIN
  PERFORM assert_language_course_intent_coverage();
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_language_courses_intent_coverage ON language_courses;
CREATE CONSTRAINT TRIGGER trg_language_courses_intent_coverage
AFTER INSERT OR UPDATE OF archived_at ON language_courses
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_language_course_intent_coverage();

DROP TRIGGER IF EXISTS trg_learning_intents_course_coverage ON tutor_learning_intents;
CREATE CONSTRAINT TRIGGER trg_learning_intents_course_coverage
AFTER INSERT OR UPDATE OF state ON tutor_learning_intents
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_language_course_intent_coverage();

DROP TRIGGER IF EXISTS trg_language_course_intent_tags_coverage ON language_course_intent_tags;
CREATE CONSTRAINT TRIGGER trg_language_course_intent_tags_coverage
AFTER INSERT OR UPDATE OR DELETE ON language_course_intent_tags
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_language_course_intent_coverage();

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
  source_version_label text NOT NULL DEFAULT 'unversioned' CHECK (char_length(source_version_label) BETWEEN 1 AND 160),
  source_version_kind text NOT NULL DEFAULT 'rolling' CHECK (source_version_kind IN ('fixed', 'rolling')),
  document_content_hash text NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' CHECK (document_content_hash ~ '^[0-9a-f]{64}$'),
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


ALTER TABLE grounding_chunks
  ADD COLUMN IF NOT EXISTS source_version_label text NOT NULL DEFAULT 'unversioned',
  ADD COLUMN IF NOT EXISTS source_version_kind text NOT NULL DEFAULT 'rolling',
  ADD COLUMN IF NOT EXISTS document_content_hash text NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_grounding_chunks_source_version_kind') THEN
    ALTER TABLE grounding_chunks ADD CONSTRAINT chk_grounding_chunks_source_version_kind
      CHECK (source_version_kind IN ('fixed', 'rolling'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_grounding_chunks_document_content_hash') THEN
    ALTER TABLE grounding_chunks ADD CONSTRAINT chk_grounding_chunks_document_content_hash
      CHECK (document_content_hash ~ '^[0-9a-f]{64}$');
  END IF;
END;
$$;

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

  ALTER TABLE tutor_runs
    DROP CONSTRAINT IF EXISTS chk_tutor_runs_continuation_kind;
  ALTER TABLE tutor_runs
    ADD CONSTRAINT chk_tutor_runs_continuation_kind
    CHECK (
      continuation_kind IS NULL OR continuation_kind IN (
        'clarification', 'planning_input', 'approval', 'capability_result', 'external_result'
      )
    );
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
  evidence_effect text NOT NULL DEFAULT 'reinforcing' CHECK (evidence_effect IN (
    'reinforcing', 'observational_non_degrading'
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
  observation_count integer NOT NULL DEFAULT 0 CHECK (observation_count >= 0),
  last_observation_id uuid,
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

CREATE TABLE IF NOT EXISTS tutor_learning_plan_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'collecting' CHECK (status IN ('collecting', 'draft_ready', 'confirmed', 'cancelled')),
  preferred_language_id text CHECK (
    preferred_language_id IS NULL OR char_length(preferred_language_id) BETWEEN 1 AND 80
  ),
  current_draft_id uuid,
  confirmed_track_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  last_error_code text CHECK (
    last_error_code IS NULL OR last_error_code ~ '^[A-Z][A-Z0-9_]{2,79}$'
  ),
  last_error_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  cancelled_at timestamptz,
  CONSTRAINT uq_tutor_learning_plan_sessions_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_learning_plan_sessions_conversation_user UNIQUE (conversation_id, user_id),
  CONSTRAINT fk_tutor_learning_plan_session_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_plan_session_confirmed_track_user
    FOREIGN KEY (confirmed_track_id, user_id)
    REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_learning_plan_session_error_shape CHECK (
    (last_error_code IS NULL) = (last_error_at IS NULL)
  ),
  CONSTRAINT chk_tutor_learning_plan_session_status_shape CHECK (
    (status = 'collecting' AND current_draft_id IS NULL AND confirmed_track_id IS NULL
      AND confirmed_at IS NULL AND cancelled_at IS NULL)
    OR (status = 'draft_ready' AND current_draft_id IS NOT NULL AND confirmed_track_id IS NULL
      AND confirmed_at IS NULL AND cancelled_at IS NULL)
    OR (status = 'confirmed' AND current_draft_id IS NOT NULL AND confirmed_track_id IS NOT NULL
      AND confirmed_at IS NOT NULL AND cancelled_at IS NULL)
    OR (status = 'cancelled' AND confirmed_track_id IS NULL AND confirmed_at IS NULL
      AND cancelled_at IS NOT NULL)
  )
);

ALTER TABLE tutor_learning_plan_sessions
  ADD COLUMN IF NOT EXISTS facts_policy_version text CHECK (
    facts_policy_version IS NULL OR char_length(facts_policy_version) BETWEEN 1 AND 160
  );

CREATE TABLE IF NOT EXISTS tutor_planning_intake_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  field_key text NOT NULL CHECK (field_key IN (
    'language_id', 'goal_text', 'target_level', 'weekly_minutes',
    'experience_level', 'teaching_preferences', 'pace_constraints'
  )),
  value_json jsonb NOT NULL,
  value_hash text NOT NULL CHECK (value_hash ~ '^[0-9a-f]{64}$'),
  revision integer NOT NULL CHECK (revision >= 1),
  state text NOT NULL CHECK (state IN ('answered_unconfirmed', 'confirmed', 'withdrawn')),
  source_kind text NOT NULL CHECK (source_kind IN ('deterministic_input', 'explicit_input', 'explicit_confirmation')),
  source_message_id uuid NOT NULL,
  source_run_id uuid NOT NULL,
  source_input_revision integer NOT NULL CHECK (source_input_revision >= 1),
  supersedes_fact_id uuid,
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_planning_intake_facts_id_scope UNIQUE (id, session_id, user_id),
  CONSTRAINT uq_tutor_planning_intake_facts_session_field_revision UNIQUE (session_id, field_key, revision),
  CONSTRAINT uq_tutor_planning_intake_facts_source_value
    UNIQUE (session_id, field_key, source_run_id, source_input_revision, value_hash),
  CONSTRAINT fk_tutor_planning_intake_fact_session_user
    FOREIGN KEY (session_id, user_id)
    REFERENCES tutor_learning_plan_sessions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_message_conversation
    FOREIGN KEY (source_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_input_evidence
    FOREIGN KEY (source_run_id, source_message_id, source_input_revision)
    REFERENCES tutor_run_input_events(run_id, message_id, input_revision) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_predecessor_scope
    FOREIGN KEY (supersedes_fact_id, session_id, user_id)
    REFERENCES tutor_planning_intake_facts(id, session_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_planning_intake_fact_predecessor_distinct CHECK (
    supersedes_fact_id IS NULL OR supersedes_fact_id <> id
  ),
  CONSTRAINT chk_tutor_planning_intake_fact_revision_shape CHECK (
    (revision = 1 AND supersedes_fact_id IS NULL)
    OR (revision > 1 AND supersedes_fact_id IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_planning_intake_facts_user_session
  ON tutor_planning_intake_facts(user_id, session_id, field_key, revision DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_planning_intake_facts_message
  ON tutor_planning_intake_facts(source_message_id);

CREATE TABLE IF NOT EXISTS tutor_planning_question_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  field_key text NOT NULL CHECK (field_key IN (
    'language_id', 'goal_text', 'target_level', 'weekly_minutes',
    'experience_level', 'teaching_preferences', 'pace_constraints'
  )),
  question_key text NOT NULL CHECK (question_key = field_key),
  status text NOT NULL CHECK (status IN (
    'unasked', 'asked', 'answered_unconfirmed', 'confirmed',
    'superseded', 'reopened', 'withdrawn', 'reasked_blocked'
  )),
  source_run_id uuid,
  source_message_id uuid,
  source_input_revision integer CHECK (source_input_revision IS NULL OR source_input_revision >= 1),
  fact_id uuid,
  previous_event_id uuid,
  reason_code text NOT NULL CHECK (char_length(reason_code) BETWEEN 1 AND 120),
  event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_planning_question_events_session_hash UNIQUE (session_id, event_hash),
  CONSTRAINT uq_tutor_planning_question_events_id_scope UNIQUE (id, session_id, user_id),
  CONSTRAINT fk_tutor_planning_question_event_session_user
    FOREIGN KEY (session_id, user_id)
    REFERENCES tutor_learning_plan_sessions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_message_conversation
    FOREIGN KEY (source_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_fact_scope
    FOREIGN KEY (fact_id, session_id, user_id)
    REFERENCES tutor_planning_intake_facts(id, session_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_previous_scope
    FOREIGN KEY (previous_event_id, session_id, user_id)
    REFERENCES tutor_planning_question_events(id, session_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_planning_question_event_source_shape CHECK (
    (source_run_id IS NULL AND source_message_id IS NULL AND source_input_revision IS NULL)
    OR (source_run_id IS NOT NULL AND source_input_revision IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_planning_question_events_session_field
  ON tutor_planning_question_events(session_id, field_key, created_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_planning_question_events_previous
  ON tutor_planning_question_events(previous_event_id)
  WHERE previous_event_id IS NOT NULL;

ALTER TABLE tutor_planning_question_events
  DROP CONSTRAINT IF EXISTS tutor_planning_question_events_status_check;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_planning_question_events'::regclass
      AND conname = 'chk_tutor_planning_question_events_status'
  ) THEN
    ALTER TABLE tutor_planning_question_events
      ADD CONSTRAINT chk_tutor_planning_question_events_status CHECK (status IN (
        'unasked', 'asked', 'answered_unconfirmed', 'confirmed',
        'superseded', 'reopened', 'withdrawn', 'reasked_blocked'
      ));
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_tutor_planning_fact_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('aearn.learning_track_purge_user_id', true) = OLD.user_id::text THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor planning intake facts are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_planning_question_event_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('aearn.learning_track_purge_user_id', true) = OLD.user_id::text THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor planning question events are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_planning_intake_facts_immutable ON tutor_planning_intake_facts;
CREATE TRIGGER trg_tutor_planning_intake_facts_immutable
BEFORE UPDATE OR DELETE ON tutor_planning_intake_facts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_planning_fact_append_only();

DROP TRIGGER IF EXISTS trg_tutor_planning_question_events_immutable ON tutor_planning_question_events;
CREATE TRIGGER trg_tutor_planning_question_events_immutable
BEFORE UPDATE OR DELETE ON tutor_planning_question_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_planning_question_event_append_only();

CREATE TABLE IF NOT EXISTS tutor_learning_plan_drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  draft_version integer NOT NULL CHECK (draft_version >= 1),
  predecessor_draft_id uuid,
  language_id text NOT NULL CHECK (char_length(language_id) BETWEEN 1 AND 80),
  goal_text text NOT NULL CHECK (char_length(goal_text) BETWEEN 1 AND 2000),
  target_level text NOT NULL CHECK (char_length(target_level) BETWEEN 1 AND 120),
  weekly_minutes integer NOT NULL CHECK (weekly_minutes BETWEEN 15 AND 10080),
  experience_level text NOT NULL CHECK (experience_level IN ('new', 'beginner', 'intermediate', 'advanced')),
  teaching_preferences_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
    jsonb_typeof(teaching_preferences_json) = 'array'
    AND jsonb_array_length(teaching_preferences_json) <= 4
  ),
  pace_summary text NOT NULL CHECK (char_length(pace_summary) BETWEEN 1 AND 240),
  profile_json jsonb NOT NULL CHECK (jsonb_typeof(profile_json) = 'object'),
  plan_json jsonb NOT NULL CHECK (jsonb_typeof(plan_json) = 'object'),
  source_summary_json jsonb NOT NULL CHECK (
    jsonb_typeof(source_summary_json) = 'array'
    AND jsonb_array_length(source_summary_json) BETWEEN 1 AND 8
  ),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  generator_version text NOT NULL CHECK (char_length(generator_version) BETWEEN 1 AND 160),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  change_reason text NOT NULL CHECK (char_length(change_reason) BETWEEN 1 AND 600),
  source_run_id uuid NOT NULL,
  source_input_revision integer NOT NULL CHECK (source_input_revision >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_plan_drafts_id_scope UNIQUE (id, session_id, user_id),
  CONSTRAINT uq_tutor_learning_plan_drafts_session_version UNIQUE (session_id, draft_version),
  CONSTRAINT uq_tutor_learning_plan_drafts_source_revision UNIQUE (source_run_id, source_input_revision),
  CONSTRAINT fk_tutor_learning_plan_draft_session_user
    FOREIGN KEY (session_id, user_id)
    REFERENCES tutor_learning_plan_sessions(id, user_id) ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_learning_plan_draft_predecessor_scope
    FOREIGN KEY (predecessor_draft_id, session_id, user_id)
    REFERENCES tutor_learning_plan_drafts(id, session_id, user_id) ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_learning_plan_draft_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_learning_plan_draft_predecessor_distinct CHECK (
    predecessor_draft_id IS NULL OR predecessor_draft_id <> id
  ),
  CONSTRAINT chk_tutor_learning_plan_draft_version_shape CHECK (
    (draft_version = 1 AND predecessor_draft_id IS NULL)
    OR (draft_version > 1 AND predecessor_draft_id IS NOT NULL)
  )
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_learning_plan_session_current_draft_scope'
  ) THEN
    ALTER TABLE tutor_learning_plan_sessions
      ADD CONSTRAINT fk_tutor_learning_plan_session_current_draft_scope
      FOREIGN KEY (current_draft_id, id, user_id)
      REFERENCES tutor_learning_plan_drafts(id, session_id, user_id) ON DELETE RESTRICT
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_learning_plan_sessions_one_active
  ON tutor_learning_plan_sessions(user_id)
  WHERE status IN ('collecting', 'draft_ready');
CREATE INDEX IF NOT EXISTS idx_tutor_learning_plan_sessions_user_updated
  ON tutor_learning_plan_sessions(user_id, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_plan_drafts_session_version
  ON tutor_learning_plan_drafts(session_id, draft_version DESC);
ALTER TABLE tutor_learning_plan_drafts
  ADD COLUMN IF NOT EXISTS facts_fingerprint text CHECK (
    facts_fingerprint IS NULL OR facts_fingerprint ~ '^[0-9a-f]{64}$'
  );
ALTER TABLE tutor_learning_plan_drafts
  ADD COLUMN IF NOT EXISTS facts_revision integer NOT NULL DEFAULT 0 CHECK (facts_revision >= 0);


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

CREATE OR REPLACE FUNCTION enforce_tutor_learning_plan_draft_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor learning plan drafts are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_learning_plan_sessions_updated_at ON tutor_learning_plan_sessions;
CREATE TRIGGER trg_tutor_learning_plan_sessions_updated_at
BEFORE UPDATE ON tutor_learning_plan_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_learning_plan_drafts_immutable ON tutor_learning_plan_drafts;
CREATE TRIGGER trg_tutor_learning_plan_drafts_immutable
BEFORE UPDATE OR DELETE ON tutor_learning_plan_drafts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_plan_draft_immutable();

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


-- Child 08-04 LessonDocument authority: immutable documents, evidence snapshots,
-- user-scoped assignments, and recoverable server-owned authoring lifecycle.
CREATE TABLE IF NOT EXISTS tutor_lesson_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_kind text NOT NULL CHECK (document_kind IN ('standard', 'personalized')),
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  language_id text NOT NULL CHECK (char_length(language_id) BETWEEN 1 AND 80),
  active_plan_revision_id uuid,
  standard_document_id uuid,
  predecessor_document_id uuid,
  schema_version text NOT NULL CHECK (schema_version = 'lesson_document_v1'),
  content_standard_version text NOT NULL CHECK (content_standard_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  generator_version text NOT NULL CHECK (char_length(generator_version) BETWEEN 1 AND 160),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  source_set_hash text NOT NULL CHECK (source_set_hash ~ '^[0-9a-f]{64}$'),
  profile_hash text CHECK (profile_hash IS NULL OR profile_hash ~ '^[0-9a-f]{64}$'),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  coverage_keys_json jsonb NOT NULL CHECK (jsonb_typeof(coverage_keys_json) = 'array'),
  blocks_json jsonb NOT NULL CHECK (jsonb_typeof(blocks_json) = 'array'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  change_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(change_summary_json) = 'object'),
  quality_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(quality_summary_json) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_documents_id_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_document_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_revision_scope
    FOREIGN KEY (active_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_standard FOREIGN KEY (standard_document_id) REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_predecessor FOREIGN KEY (predecessor_document_id) REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_document_scope_shape CHECK (
    (document_kind = 'standard' AND user_id IS NULL AND track_id IS NULL
      AND active_plan_revision_id IS NULL AND standard_document_id IS NULL AND profile_hash IS NULL)
    OR
    (document_kind = 'personalized' AND user_id IS NOT NULL AND track_id IS NOT NULL
      AND active_plan_revision_id IS NOT NULL AND standard_document_id IS NOT NULL AND profile_hash IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_lesson_document_predecessor_distinct CHECK (
    predecessor_document_id IS NULL OR predecessor_document_id <> id
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_lesson_documents_standard_identity
  ON tutor_lesson_documents(
    language_id, knowledge_key, content_standard_version,
    generator_version, policy_version, source_set_hash, content_hash
  ) WHERE document_kind = 'standard';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_lesson_documents_personalized_identity
  ON tutor_lesson_documents(
    user_id, track_id, knowledge_key, standard_document_id,
    profile_hash, generator_version, policy_version, source_set_hash, content_hash
  ) WHERE document_kind = 'personalized';
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_documents_track_key_created
  ON tutor_lesson_documents(track_id, knowledge_key, created_at DESC)
  WHERE document_kind = 'personalized';

CREATE TABLE IF NOT EXISTS tutor_lesson_source_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  citation_id text NOT NULL CHECK (citation_id ~ '^cite_[0-9a-f]{16}$'),
  source_id text NOT NULL CHECK (char_length(source_id) BETWEEN 1 AND 160),
  display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 240),
  provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 240),
  trust_tier text NOT NULL CHECK (trust_tier IN ('official', 'trusted_de_facto', 'internal')),
  source_type text NOT NULL CHECK (source_type IN ('tutorial', 'reference', 'spec', 'platform_docs', 'vendor_docs')),
  source_version_label text NOT NULL CHECK (char_length(source_version_label) BETWEEN 1 AND 160),
  source_version_kind text NOT NULL CHECK (source_version_kind IN ('fixed', 'rolling')),
  canonical_url text NOT NULL CHECK (canonical_url ~ '^https?://'),
  section_path_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(section_path_json) = 'array'),
  grounding_chunk_id text NOT NULL CHECK (char_length(grounding_chunk_id) BETWEEN 1 AND 160),
  document_content_hash text NOT NULL CHECK (document_content_hash ~ '^[0-9a-f]{64}$'),
  chunk_content_hash text NOT NULL CHECK (chunk_content_hash ~ '^[0-9a-f]{64}$'),
  fetched_at timestamptz NOT NULL,
  snapshotted_at timestamptz NOT NULL,
  evidence_excerpt text NOT NULL CHECK (char_length(evidence_excerpt) BETWEEN 1 AND 1200),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_source_snapshots_document_citation UNIQUE (document_id, citation_id),
  CONSTRAINT uq_tutor_lesson_source_snapshots_id_scope UNIQUE (id, document_id, user_id, track_id, knowledge_key)
);
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_source_snapshots_document
  ON tutor_lesson_source_snapshots(document_id, citation_id);

CREATE TABLE IF NOT EXISTS tutor_lesson_block_citations (
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  block_id text NOT NULL CHECK (block_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  citation_id text NOT NULL CHECK (citation_id ~ '^cite_[0-9a-f]{16}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (document_id, block_id, citation_id),
  CONSTRAINT fk_tutor_lesson_block_citation_snapshot
    FOREIGN KEY (document_id, citation_id)
    REFERENCES tutor_lesson_source_snapshots(document_id, citation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_lesson_gate_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  block_id text NOT NULL CHECK (block_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  gate_key text NOT NULL CHECK (gate_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  gate_kind text NOT NULL CHECK (gate_kind IN ('knowledge_check', 'guided_practice', 'independent_practice')),
  assessment_contract_version text NOT NULL CHECK (assessment_contract_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  required_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  learner_prompt_hash text NOT NULL CHECK (learner_prompt_hash ~ '^[0-9a-f]{64}$'),
  learner_prompt text NOT NULL CHECK (char_length(learner_prompt) BETWEEN 1 AND 1200),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_gate_slots_document_key UNIQUE (document_id, gate_key),
  CONSTRAINT uq_tutor_lesson_gate_slots_document_block UNIQUE (document_id, block_id)
);

CREATE TABLE IF NOT EXISTS tutor_lesson_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  document_id uuid NOT NULL,
  source_plan_revision_id uuid NOT NULL,
  predecessor_assignment_id uuid,
  assignment_version integer NOT NULL CHECK (assignment_version >= 1),
  status text NOT NULL CHECK (status IN ('active', 'proposed', 'superseded')),
  impact_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(impact_json) = 'object'),
  expected_progress_version integer NOT NULL CHECK (expected_progress_version >= 1),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  started_at timestamptz,
  activated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_assignments_id_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_assignment_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_assignment_document_scope
    FOREIGN KEY (document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_documents(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_assignment_revision_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_assignment_predecessor FOREIGN KEY (predecessor_assignment_id) REFERENCES tutor_lesson_assignments(id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_assignment_predecessor_distinct CHECK (
    predecessor_assignment_id IS NULL OR predecessor_assignment_id <> id
  ),
  CONSTRAINT chk_tutor_lesson_assignment_activation CHECK (
    (status = 'proposed' AND activated_at IS NULL)
    OR (status IN ('active', 'superseded') AND activated_at IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_lesson_assignments_one_active
  ON tutor_lesson_assignments(track_id, knowledge_key) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_assignments_track_key_created
  ON tutor_lesson_assignments(track_id, knowledge_key, created_at DESC);

CREATE TABLE IF NOT EXISTS tutor_lesson_authoring_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  run_kind text NOT NULL CHECK (run_kind IN ('prepare', 'refresh')),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'claimed', 'running', 'completed', 'failed', 'cancelled')),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_progress_version integer NOT NULL CHECK (expected_progress_version >= 1),
  active_plan_revision_id uuid NOT NULL,
  source_set_hash text CHECK (source_set_hash IS NULL OR source_set_hash ~ '^[0-9a-f]{64}$'),
  profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_owner text,
  lease_expires_at timestamptz,
  failure_code text,
  failure_message text,
  standard_document_id uuid REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  personalized_document_id uuid REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  assignment_id uuid REFERENCES tutor_lesson_assignments(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  terminal_at timestamptz,
  CONSTRAINT uq_tutor_lesson_authoring_runs_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_lesson_authoring_runs_idempotency UNIQUE (user_id, run_kind, idempotency_key),
  CONSTRAINT fk_tutor_lesson_authoring_run_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_authoring_run_revision_scope
    FOREIGN KEY (active_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_authoring_run_lease CHECK (
    (state IN ('claimed', 'running')) = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_lesson_authoring_run_terminal CHECK (
    (state IN ('completed', 'failed', 'cancelled')) = (terminal_at IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_authoring_runs_claim
  ON tutor_lesson_authoring_runs(state, lease_expires_at, created_at)
  WHERE state IN ('pending', 'claimed', 'running');
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_authoring_runs_track_key
  ON tutor_lesson_authoring_runs(track_id, knowledge_key, created_at DESC);

CREATE TABLE IF NOT EXISTS tutor_lesson_authoring_attempt_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  attempt_index integer NOT NULL CHECK (attempt_index >= 1),
  provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 120),
  model text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 160),
  protocol text NOT NULL CHECK (char_length(protocol) BETWEEN 1 AND 80),
  outcome text NOT NULL CHECK (outcome IN ('success', 'unavailable', 'invalid', 'failed')),
  diagnostic_code text,
  usage_available boolean NOT NULL DEFAULT false,
  input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
  total_tokens integer CHECK (total_tokens IS NULL OR total_tokens >= 0),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  response_hash text CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_authoring_attempt_identity UNIQUE (run_id, attempt_index),
  CONSTRAINT fk_tutor_lesson_authoring_attempt_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_lesson_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_authoring_attempt_usage CHECK (
    (usage_available AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL)
    OR (NOT usage_available AND input_tokens IS NULL AND output_tokens IS NULL AND total_tokens IS NULL)
  )
);

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_document_lineage()
RETURNS trigger AS $$
DECLARE
  standard_row tutor_lesson_documents%ROWTYPE;
  predecessor_row tutor_lesson_documents%ROWTYPE;
BEGIN
  IF NEW.document_kind = 'personalized' THEN
    SELECT * INTO standard_row FROM tutor_lesson_documents WHERE id = NEW.standard_document_id;
    IF standard_row.id IS NULL OR standard_row.document_kind <> 'standard'
       OR standard_row.language_id <> NEW.language_id
       OR standard_row.knowledge_key <> NEW.knowledge_key THEN
      RAISE EXCEPTION 'Personalized LessonDocument must reference a matching standard document' USING ERRCODE = '23514';
    END IF;
  END IF;
  IF NEW.predecessor_document_id IS NOT NULL THEN
    SELECT * INTO predecessor_row FROM tutor_lesson_documents WHERE id = NEW.predecessor_document_id;
    IF predecessor_row.id IS NULL OR predecessor_row.document_kind <> NEW.document_kind
       OR predecessor_row.language_id <> NEW.language_id
       OR predecessor_row.knowledge_key <> NEW.knowledge_key
       OR predecessor_row.user_id IS DISTINCT FROM NEW.user_id
       OR predecessor_row.track_id IS DISTINCT FROM NEW.track_id THEN
      RAISE EXCEPTION 'LessonDocument predecessor scope is invalid' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.user_id IS NOT NULL AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Lesson authority rows are append-only' USING ERRCODE = '23514';
  END IF;
  RAISE EXCEPTION 'Lesson authority rows are immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_assignment_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Lesson assignments cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.document_id IS DISTINCT FROM OLD.document_id OR NEW.source_plan_revision_id IS DISTINCT FROM OLD.source_plan_revision_id
     OR NEW.predecessor_assignment_id IS DISTINCT FROM OLD.predecessor_assignment_id
     OR NEW.assignment_version IS DISTINCT FROM OLD.assignment_version
     OR NEW.impact_json IS DISTINCT FROM OLD.impact_json OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
     OR NEW.expected_progress_version IS DISTINCT FROM OLD.expected_progress_version
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Lesson assignment identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN
    RAISE EXCEPTION 'Started Lesson assignment is frozen' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'active'
     AND (OLD.activated_at IS NOT NULL OR NEW.activated_at IS NULL) THEN
    RAISE EXCEPTION 'Activated Lesson assignment requires a new activation timestamp' USING ERRCODE = '23514';
  END IF;
  IF OLD.status <> 'proposed' AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
    RAISE EXCEPTION 'Lesson assignment activation timestamp is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'active' AND NEW.status IN ('active', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.status = 'proposed' AND NEW.status IN ('proposed', 'active', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.status = NEW.status AND OLD.status = 'superseded' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Lesson assignment lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_authoring_run_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Lesson authoring runs cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('completed', 'failed', 'cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal Lesson authoring run is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'pending' AND NEW.state IN ('pending', 'claimed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'claimed' AND NEW.state IN ('claimed', 'running', 'pending', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('running', 'completed', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Lesson authoring run lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_lesson_documents_lineage ON tutor_lesson_documents;
CREATE TRIGGER trg_tutor_lesson_documents_lineage
BEFORE INSERT ON tutor_lesson_documents
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_document_lineage();

DROP TRIGGER IF EXISTS trg_tutor_lesson_documents_immutable ON tutor_lesson_documents;
CREATE TRIGGER trg_tutor_lesson_documents_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_documents
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_source_snapshots_immutable ON tutor_lesson_source_snapshots;
CREATE TRIGGER trg_tutor_lesson_source_snapshots_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_source_snapshots
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_block_citations_immutable ON tutor_lesson_block_citations;
CREATE TRIGGER trg_tutor_lesson_block_citations_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_block_citations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_slots_immutable ON tutor_lesson_gate_slots;
CREATE TRIGGER trg_tutor_lesson_gate_slots_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_gate_slots
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_assignments_updated_at ON tutor_lesson_assignments;
CREATE TRIGGER trg_tutor_lesson_assignments_updated_at
BEFORE UPDATE ON tutor_lesson_assignments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_lesson_assignments_lifecycle ON tutor_lesson_assignments;
CREATE TRIGGER trg_tutor_lesson_assignments_lifecycle
BEFORE UPDATE OR DELETE ON tutor_lesson_assignments
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_assignment_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_lesson_authoring_runs_updated_at ON tutor_lesson_authoring_runs;
CREATE TRIGGER trg_tutor_lesson_authoring_runs_updated_at
BEFORE UPDATE ON tutor_lesson_authoring_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_lesson_authoring_runs_lifecycle ON tutor_lesson_authoring_runs;
CREATE TRIGGER trg_tutor_lesson_authoring_runs_lifecycle
BEFORE UPDATE OR DELETE ON tutor_lesson_authoring_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_authoring_run_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_lesson_authoring_attempt_receipts_immutable ON tutor_lesson_authoring_attempt_receipts;
CREATE TRIGGER trg_tutor_lesson_authoring_attempt_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_authoring_attempt_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

-- Lesson exercise Gate, append-only attempt, and module diagnostic authority.
ALTER TABLE tutor_mastery_evidence
  ADD COLUMN IF NOT EXISTS evidence_effect text NOT NULL DEFAULT 'reinforcing';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_mastery_evidence'::regclass
      AND conname = 'chk_tutor_mastery_evidence_effect'
  ) THEN
    ALTER TABLE tutor_mastery_evidence
      ADD CONSTRAINT chk_tutor_mastery_evidence_effect
      CHECK (evidence_effect IN ('reinforcing', 'observational_non_degrading'));
  END IF;
END $$;

ALTER TABLE tutor_mastery_states
  ADD COLUMN IF NOT EXISTS observation_count integer NOT NULL DEFAULT 0;
ALTER TABLE tutor_mastery_states
  ADD COLUMN IF NOT EXISTS last_observation_id uuid;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_mastery_states'::regclass
      AND conname = 'chk_tutor_mastery_states_observation_count'
  ) THEN
    ALTER TABLE tutor_mastery_states
      ADD CONSTRAINT chk_tutor_mastery_states_observation_count CHECK (observation_count >= 0);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_exercise_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_key text NOT NULL CHECK (exercise_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_type text NOT NULL CHECK (exercise_type IN (
    'code_completion', 'sql_query', 'browser_preview', 'static_code_reasoning'
  )),
  version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_kind text NOT NULL CHECK (source_kind IN ('curated_fixture', 'registered_author')),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  learner_prompt_json jsonb NOT NULL CHECK (jsonb_typeof(learner_prompt_json) = 'object'),
  starter_artifact_json jsonb NOT NULL CHECK (jsonb_typeof(starter_artifact_json) = 'object'),
  required_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  runtime_profile_key text CHECK (
    runtime_profile_key IS NULL OR runtime_profile_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  execution_required boolean NOT NULL,
  public_feedback_policy_version text NOT NULL CHECK (
    public_feedback_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  validation_status text NOT NULL CHECK (validation_status IN ('ready', 'rejected')),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_versions_key_version UNIQUE (exercise_key, version),
  CONSTRAINT uq_tutor_exercise_versions_id_identity UNIQUE (id, language_id, exercise_key, version),
  CONSTRAINT chk_tutor_exercise_versions_execution_shape CHECK (
    execution_required = (runtime_profile_key IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_exercise_private_rubrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_version_id uuid NOT NULL UNIQUE REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  rubric_version text NOT NULL CHECK (rubric_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  private_test_bundle_json jsonb NOT NULL CHECK (jsonb_typeof(private_test_bundle_json) = 'array'),
  reference_answer_json jsonb NOT NULL CHECK (jsonb_typeof(reference_answer_json) = 'object'),
  score_policy_json jsonb NOT NULL CHECK (jsonb_typeof(score_policy_json) = 'object'),
  rubric_hash text NOT NULL CHECK (rubric_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_private_rubrics_id_exercise UNIQUE (id, exercise_version_id)
);

CREATE TABLE IF NOT EXISTS tutor_lesson_gate_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id uuid NOT NULL REFERENCES tutor_lesson_gate_slots(id) ON DELETE RESTRICT,
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  gate_key text NOT NULL CHECK (gate_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  requirement_kind text NOT NULL CHECK (requirement_kind IN ('required', 'recommended', 'diagnostic')),
  pass_policy_version text NOT NULL CHECK (pass_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  pass_threshold double precision NOT NULL CHECK (pass_threshold > 0 AND pass_threshold <= 1),
  execution_requirement text NOT NULL CHECK (execution_requirement IN ('required', 'optional', 'forbidden')),
  remediation_exercise_version_id uuid REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  slot_contract_hash text NOT NULL CHECK (slot_contract_hash ~ '^[0-9a-f]{64}$'),
  binding_contract_hash text NOT NULL CHECK (binding_contract_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_gate_bindings_document_key UNIQUE (document_id, gate_key),
  CONSTRAINT uq_tutor_lesson_gate_bindings_id_scope UNIQUE (id, document_id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_gate_binding_slot
    FOREIGN KEY (document_id, gate_key)
    REFERENCES tutor_lesson_gate_slots(document_id, gate_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_gate_binding_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_lesson_gate_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid NOT NULL,
  document_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL,
  state text NOT NULL CHECK (state IN ('available', 'in_progress', 'passed', 'remediation_required')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  best_score double precision NOT NULL DEFAULT 0 CHECK (best_score >= 0 AND best_score <= 1),
  latest_attempt_id uuid,
  passing_attempt_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  passed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_gate_states_assignment_binding UNIQUE (lesson_assignment_id, gate_binding_id),
  CONSTRAINT uq_tutor_lesson_gate_states_id_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_gate_state_assignment_scope
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_gate_state_binding_scope
    FOREIGN KEY (gate_binding_id, document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_gate_bindings(id, document_id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_gate_states_passed CHECK (
    (state = 'passed') = (passed_at IS NOT NULL AND passing_attempt_id IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_module_diagnostic_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  module_key text NOT NULL CHECK (module_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  policy_version text NOT NULL CHECK (policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  core_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(core_capabilities_json) = 'array'),
  pass_threshold double precision NOT NULL CHECK (pass_threshold > 0 AND pass_threshold <= 1),
  require_all_core boolean NOT NULL DEFAULT true,
  independent_only boolean NOT NULL DEFAULT true,
  cooldown_seconds integer NOT NULL CHECK (cooldown_seconds >= 0 AND cooldown_seconds <= 2678400),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_module_diagnostic_versions_identity UNIQUE (language_id, module_key, version),
  CONSTRAINT uq_tutor_module_diagnostic_versions_id_identity UNIQUE (id, language_id, module_key, version)
);

CREATE TABLE IF NOT EXISTS tutor_module_diagnostic_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  module_key text NOT NULL CHECK (module_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  diagnostic_version_id uuid NOT NULL REFERENCES tutor_module_diagnostic_versions(id) ON DELETE RESTRICT,
  source_plan_revision_id uuid NOT NULL,
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  state text NOT NULL CHECK (state IN ('active', 'failed', 'passed_pending_confirmation', 'confirmed', 'expired')),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  proposed_plan_revision_id uuid,
  impact_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(impact_json) = 'object'),
  weak_capabilities_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(weak_capabilities_json) = 'array'),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  started_at timestamptz NOT NULL,
  terminal_at timestamptz,
  cooldown_until timestamptz,
  confirmed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_module_diagnostic_sessions_id_scope UNIQUE (id, user_id, track_id),
  CONSTRAINT uq_tutor_module_diagnostic_sessions_idempotency UNIQUE (user_id, track_id, module_key, idempotency_key),
  CONSTRAINT fk_tutor_module_diagnostic_session_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_module_diagnostic_session_revision_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_module_diagnostic_session_proposed_scope
    FOREIGN KEY (proposed_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_module_diagnostic_sessions_terminal CHECK (
    (state = 'active') = (terminal_at IS NULL)
  ),
  CONSTRAINT chk_tutor_module_diagnostic_sessions_confirmation CHECK (
    (state = 'confirmed') = (confirmed_at IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_module_diagnostic_sessions_active
  ON tutor_module_diagnostic_sessions(user_id, track_id, module_key)
  WHERE state IN ('active', 'passed_pending_confirmation');

CREATE TABLE IF NOT EXISTS tutor_module_diagnostic_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  source_plan_revision_id uuid NOT NULL,
  item_key text NOT NULL CHECK (item_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  order_index integer NOT NULL CHECK (order_index >= 0),
  capability_key text NOT NULL CHECK (capability_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  threshold double precision NOT NULL CHECK (threshold > 0 AND threshold <= 1),
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_module_diagnostic_items_session_key UNIQUE (session_id, item_key),
  CONSTRAINT uq_tutor_module_diagnostic_items_session_order UNIQUE (session_id, order_index),
  CONSTRAINT uq_tutor_module_diagnostic_items_id_scope UNIQUE (id, session_id, user_id, track_id),
  CONSTRAINT fk_tutor_module_diagnostic_item_session_scope
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_module_diagnostic_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_module_diagnostic_item_node_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_exercise_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_type text NOT NULL CHECK (attempt_type IN ('run', 'submit', 'diagnostic_submit')),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  plan_revision_id uuid NOT NULL,
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_progress_version integer CHECK (expected_progress_version IS NULL OR expected_progress_version >= 1),
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid,
  document_id uuid,
  gate_binding_id uuid,
  diagnostic_session_id uuid,
  diagnostic_item_id uuid,
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  submission_hash text NOT NULL CHECK (submission_hash ~ '^[0-9a-f]{64}$'),
  hint_state_hash text NOT NULL CHECK (hint_state_hash ~ '^[0-9a-f]{64}$'),
  independence text NOT NULL CHECK (independence IN ('independent', 'hinted', 'remediated')),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  accepted_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_attempts_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_exercise_attempts_id_exercise UNIQUE (id, user_id, exercise_version_id),
  CONSTRAINT uq_tutor_exercise_attempts_id_scope UNIQUE (id, user_id, track_id, exercise_version_id),
  CONSTRAINT uq_tutor_exercise_attempts_idempotency UNIQUE (user_id, attempt_type, idempotency_key),
  CONSTRAINT fk_tutor_exercise_attempt_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_revision_scope
    FOREIGN KEY (plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_assignment_scope
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_binding_scope
    FOREIGN KEY (gate_binding_id, document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_gate_bindings(id, document_id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_diagnostic_item_scope
    FOREIGN KEY (diagnostic_item_id, diagnostic_session_id, user_id, track_id)
    REFERENCES tutor_module_diagnostic_items(id, session_id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_exercise_attempts_owner_shape CHECK (
    (
      attempt_type IN ('run', 'submit')
      AND lesson_assignment_id IS NOT NULL AND document_id IS NOT NULL AND gate_binding_id IS NOT NULL
      AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
      AND expected_progress_version IS NOT NULL
    )
    OR (
      attempt_type = 'diagnostic_submit'
      AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
      AND diagnostic_session_id IS NOT NULL AND diagnostic_item_id IS NOT NULL
      AND expected_progress_version IS NULL
    )
  )
);

CREATE TABLE IF NOT EXISTS tutor_exercise_attempt_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  exercise_version_id uuid NOT NULL,
  submission_kind text NOT NULL CHECK (submission_kind IN ('code', 'sql', 'structured_answer')),
  content_text text NOT NULL CHECK (char_length(content_text) BETWEEN 1 AND 48000),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_attempt_submissions_id_scope UNIQUE (id, attempt_id, user_id, exercise_version_id),
  CONSTRAINT fk_tutor_exercise_attempt_submission_scope
    FOREIGN KEY (attempt_id, user_id, exercise_version_id)
    REFERENCES tutor_exercise_attempts(id, user_id, exercise_version_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_exercise_attempt_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('passed', 'failed', 'timed_out', 'cancelled', 'unavailable', 'invalid')),
  score double precision NOT NULL CHECK (score >= 0 AND score <= 1),
  safe_feedback_json jsonb NOT NULL CHECK (jsonb_typeof(safe_feedback_json) = 'object'),
  capability_scores_json jsonb NOT NULL CHECK (jsonb_typeof(capability_scores_json) = 'object'),
  execution_receipt_hash text CHECK (execution_receipt_hash IS NULL OR execution_receipt_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL CHECK (policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  terminal_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_attempt_results_id_scope UNIQUE (id, attempt_id, user_id),
  CONSTRAINT fk_tutor_exercise_attempt_result_scope
    FOREIGN KEY (attempt_id, user_id) REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_exercise_hint_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL,
  hint_level integer NOT NULL CHECK (hint_level BETWEEN 1 AND 3),
  hint_policy_version text NOT NULL CHECK (hint_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  safe_hint_json jsonb NOT NULL CHECK (jsonb_typeof(safe_hint_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_hint_receipts_idempotency UNIQUE (user_id, lesson_assignment_id, gate_binding_id, idempotency_key),
  CONSTRAINT fk_tutor_exercise_hint_assignment_scope
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_hint_binding
    FOREIGN KEY (gate_binding_id) REFERENCES tutor_lesson_gate_bindings(id) ON DELETE RESTRICT
);

-- Add the Gate source/owner to the existing executor queue without weakening the legacy path.
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'tutor_message';
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS exercise_attempt_id uuid;
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS exercise_submission_id uuid;
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS exercise_version_id uuid;
ALTER TABLE tutor_execution_intents ALTER COLUMN conversation_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN run_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN source_message_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN exercise_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN input_revision DROP NOT NULL;
ALTER TABLE tutor_execution_intents DROP CONSTRAINT IF EXISTS tutor_execution_intents_origin_check;
ALTER TABLE tutor_execution_intents
  ADD CONSTRAINT tutor_execution_intents_origin_check CHECK (origin IN ('interactive', 'proactive', 'exercise_gate'));

DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'tutor_execution_intents'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%consumed_at IS NULL%consumed_by_effect_id IS NULL%'
  LOOP
    EXECUTE format('ALTER TABLE tutor_execution_intents DROP CONSTRAINT %I', item.conname);
  END LOOP;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'chk_tutor_execution_intents_source_shape'
  ) THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT chk_tutor_execution_intents_source_shape CHECK (
      (
        source_kind = 'tutor_message'
        AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND source_message_id IS NOT NULL
        AND exercise_id IS NOT NULL AND input_revision IS NOT NULL
        AND exercise_attempt_id IS NULL AND exercise_submission_id IS NULL AND exercise_version_id IS NULL
        AND origin IN ('interactive', 'proactive')
        AND ((consumed_at IS NULL) = (consumed_by_effect_id IS NULL))
      )
      OR (
        source_kind = 'exercise_submission'
        AND conversation_id IS NULL AND run_id IS NULL AND source_message_id IS NULL AND exercise_id IS NULL
        AND input_revision IS NULL AND origin = 'exercise_gate'
        AND exercise_attempt_id IS NOT NULL AND exercise_submission_id IS NOT NULL AND exercise_version_id IS NOT NULL
        AND consumed_by_effect_id IS NULL
      )
    ) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'uq_tutor_execution_intents_gate_scope'
  ) THEN
    ALTER TABLE tutor_execution_intents
      ADD CONSTRAINT uq_tutor_execution_intents_gate_scope UNIQUE (id, exercise_attempt_id, user_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'fk_tutor_execution_intent_gate_attempt'
  ) THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_gate_attempt
      FOREIGN KEY (exercise_attempt_id, user_id)
      REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'fk_tutor_execution_intent_gate_submission'
  ) THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_gate_submission
      FOREIGN KEY (exercise_submission_id, exercise_attempt_id, user_id, exercise_version_id)
      REFERENCES tutor_exercise_attempt_submissions(id, attempt_id, user_id, exercise_version_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

ALTER TABLE tutor_execution_jobs ADD COLUMN IF NOT EXISTS owner_kind text NOT NULL DEFAULT 'tutor_effect';
ALTER TABLE tutor_execution_jobs ADD COLUMN IF NOT EXISTS exercise_attempt_id uuid;
ALTER TABLE tutor_execution_jobs ALTER COLUMN effect_record_id DROP NOT NULL;
ALTER TABLE tutor_execution_jobs ALTER COLUMN effect_key DROP NOT NULL;
ALTER TABLE tutor_execution_jobs ALTER COLUMN conversation_id DROP NOT NULL;
ALTER TABLE tutor_execution_jobs ALTER COLUMN run_id DROP NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'chk_tutor_execution_jobs_owner_shape'
  ) THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT chk_tutor_execution_jobs_owner_shape CHECK (
      (
        owner_kind = 'tutor_effect'
        AND effect_record_id IS NOT NULL AND effect_key IS NOT NULL
        AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND exercise_attempt_id IS NULL
      )
      OR (
        owner_kind = 'exercise_attempt'
        AND effect_record_id IS NULL AND effect_key IS NULL
        AND conversation_id IS NULL AND run_id IS NULL AND exercise_attempt_id IS NOT NULL
      )
    ) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'uq_tutor_execution_jobs_gate_scope'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT uq_tutor_execution_jobs_gate_scope UNIQUE (id, exercise_attempt_id, user_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'fk_tutor_execution_job_gate_intent_scope'
  ) THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_gate_intent_scope
      FOREIGN KEY (intent_id, exercise_attempt_id, user_id)
      REFERENCES tutor_execution_intents(id, exercise_attempt_id, user_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'fk_tutor_execution_job_gate_attempt'
  ) THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_gate_attempt
      FOREIGN KEY (exercise_attempt_id, user_id)
      REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_exercise_execution_links (
  attempt_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  execution_intent_id uuid NOT NULL UNIQUE REFERENCES tutor_execution_intents(id) ON DELETE RESTRICT,
  execution_job_id uuid NOT NULL UNIQUE REFERENCES tutor_execution_jobs(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_exercise_execution_link_attempt
    FOREIGN KEY (attempt_id, user_id) REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_execution_link_intent_scope
    FOREIGN KEY (execution_intent_id, attempt_id, user_id)
    REFERENCES tutor_execution_intents(id, exercise_attempt_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_execution_link_job_scope
    FOREIGN KEY (execution_job_id, attempt_id, user_id)
    REFERENCES tutor_execution_jobs(id, exercise_attempt_id, user_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION enforce_tutor_practice_shared_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Practice shared authority rows are immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_practice_user_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Practice user facts are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_gate_state_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Lesson Gate state cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.lesson_assignment_id IS DISTINCT FROM OLD.lesson_assignment_id
     OR NEW.document_id IS DISTINCT FROM OLD.document_id OR NEW.gate_binding_id IS DISTINCT FROM OLD.gate_binding_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Lesson Gate state identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'passed' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Passed Lesson Gate state is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_module_diagnostic_session_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Module diagnostic session cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.module_key IS DISTINCT FROM OLD.module_key
     OR NEW.diagnostic_version_id IS DISTINCT FROM OLD.diagnostic_version_id
     OR NEW.source_plan_revision_id IS DISTINCT FROM OLD.source_plan_revision_id
     OR NEW.expected_track_version IS DISTINCT FROM OLD.expected_track_version
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
     OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Module diagnostic session identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('failed', 'confirmed', 'expired') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal module diagnostic session is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'active' AND NEW.state IN ('active', 'failed', 'passed_pending_confirmation', 'expired') THEN RETURN NEW; END IF;
  IF OLD.state = 'passed_pending_confirmation' AND NEW.state IN ('passed_pending_confirmation', 'confirmed', 'expired') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Module diagnostic session transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_exercise_versions_immutable ON tutor_exercise_versions;
CREATE TRIGGER trg_tutor_exercise_versions_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_versions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_shared_immutable();
DROP TRIGGER IF EXISTS trg_tutor_exercise_private_rubrics_immutable ON tutor_exercise_private_rubrics;
CREATE TRIGGER trg_tutor_exercise_private_rubrics_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_private_rubrics
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_shared_immutable();
DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_bindings_immutable ON tutor_lesson_gate_bindings;
CREATE TRIGGER trg_tutor_lesson_gate_bindings_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_gate_bindings
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_versions_immutable ON tutor_module_diagnostic_versions;
CREATE TRIGGER trg_tutor_module_diagnostic_versions_immutable
BEFORE UPDATE OR DELETE ON tutor_module_diagnostic_versions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_shared_immutable();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_items_immutable ON tutor_module_diagnostic_items;
CREATE TRIGGER trg_tutor_module_diagnostic_items_immutable
BEFORE UPDATE OR DELETE ON tutor_module_diagnostic_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_attempts_immutable ON tutor_exercise_attempts;
CREATE TRIGGER trg_tutor_exercise_attempts_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_attempts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_attempt_submissions_immutable ON tutor_exercise_attempt_submissions;
CREATE TRIGGER trg_tutor_exercise_attempt_submissions_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_attempt_submissions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_attempt_results_immutable ON tutor_exercise_attempt_results;
CREATE TRIGGER trg_tutor_exercise_attempt_results_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_attempt_results
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_hint_receipts_immutable ON tutor_exercise_hint_receipts;
CREATE TRIGGER trg_tutor_exercise_hint_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_hint_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_execution_links_immutable ON tutor_exercise_execution_links;
CREATE TRIGGER trg_tutor_exercise_execution_links_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_execution_links
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_states_updated_at ON tutor_lesson_gate_states;
CREATE TRIGGER trg_tutor_lesson_gate_states_updated_at BEFORE UPDATE ON tutor_lesson_gate_states
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_states_lifecycle ON tutor_lesson_gate_states;
CREATE TRIGGER trg_tutor_lesson_gate_states_lifecycle BEFORE UPDATE OR DELETE ON tutor_lesson_gate_states
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_gate_state_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_sessions_updated_at ON tutor_module_diagnostic_sessions;
CREATE TRIGGER trg_tutor_module_diagnostic_sessions_updated_at BEFORE UPDATE ON tutor_module_diagnostic_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_sessions_lifecycle ON tutor_module_diagnostic_sessions;
CREATE TRIGGER trg_tutor_module_diagnostic_sessions_lifecycle BEFORE UPDATE OR DELETE ON tutor_module_diagnostic_sessions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_module_diagnostic_session_lifecycle();

CREATE INDEX IF NOT EXISTS idx_tutor_lesson_gate_states_assignment
  ON tutor_lesson_gate_states(lesson_assignment_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_exercise_attempts_gate
  ON tutor_exercise_attempts(lesson_assignment_id, gate_binding_id, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_exercise_attempts_diagnostic
  ON tutor_exercise_attempts(diagnostic_session_id, diagnostic_item_id, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_module_diagnostic_sessions_track
  ON tutor_module_diagnostic_sessions(track_id, module_key, created_at DESC);


-- Unified controlled Action Runtime: orchestration metadata only. Domain truth remains in capability,
-- plan, effect, and execution owner tables referenced by authority_kind/authority_id.
CREATE TABLE IF NOT EXISTS tutor_action_invocations (
  id text PRIMARY KEY CHECK (char_length(id) BETWEEN 1 AND 160),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  lease_owner_id text NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation > 0),
  action_generation integer NOT NULL CHECK (action_generation > 0),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  stable_action_key text NOT NULL CHECK (char_length(stable_action_key) BETWEEN 1 AND 160),
  action_id text NOT NULL CHECK (char_length(action_id) BETWEEN 1 AND 120),
  action_version text NOT NULL CHECK (char_length(action_version) BETWEEN 1 AND 80),
  descriptor_hash text NOT NULL CHECK (descriptor_hash ~ '^[0-9a-f]{64}$'),
  owner_adapter_id text NOT NULL CHECK (char_length(owner_adapter_id) BETWEEN 1 AND 120),
  task_kind text NOT NULL CHECK (char_length(task_kind) BETWEEN 1 AND 120),
  origin text NOT NULL CHECK (origin IN ('interactive', 'proactive', 'exercise_gate')),
  catalog_digest text NOT NULL CHECK (catalog_digest ~ '^[0-9a-f]{64}$'),
  policy_fingerprint text NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  selected_skill_reference text CHECK (selected_skill_reference IS NULL OR char_length(selected_skill_reference) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  resource_profile_hash text NOT NULL CHECK (resource_profile_hash ~ '^[0-9a-f]{64}$'),
  resource_request_hash text NOT NULL CHECK (resource_request_hash ~ '^[0-9a-f]{64}$'),
  parent_invocation_id text,
  retry_index integer NOT NULL DEFAULT 0 CHECK (retry_index >= 0),
  status text NOT NULL CHECK (status IN (
    'requested', 'admitted', 'running', 'succeeded_unverified', 'verified',
    'retryable_failed', 'permanent_failed', 'denied', 'cancel_requested',
    'cancelled', 'timed_out', 'superseded'
  )),
  requested_at timestamptz NOT NULL,
  admitted_at timestamptz,
  started_at timestamptz,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_action_invocations_run_key UNIQUE (run_id, idempotency_key),
  CONSTRAINT uq_tutor_action_invocations_id_run UNIQUE (id, run_id),
  CONSTRAINT fk_tutor_action_invocation_parent_run
    FOREIGN KEY (parent_invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_invocation_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_invocation_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_invocations_parent_distinct CHECK (parent_invocation_id IS NULL OR parent_invocation_id <> id),
  CONSTRAINT chk_tutor_action_invocations_terminal CHECK (
    (status IN ('verified', 'retryable_failed', 'permanent_failed', 'denied', 'cancelled', 'timed_out', 'superseded'))
      = (terminal_at IS NOT NULL)
  )
);

ALTER TABLE tutor_action_invocations
  ADD COLUMN IF NOT EXISTS lease_owner_id text;
UPDATE tutor_action_invocations AS invocations
SET lease_owner_id = COALESCE(runs.active_lease_owner_id, 'legacy-action-owner')
FROM tutor_runs AS runs
WHERE invocations.run_id = runs.id AND invocations.lease_owner_id IS NULL;
ALTER TABLE tutor_action_invocations
  ALTER COLUMN lease_owner_id SET NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tutor_action_invocations_lease_owner'
  ) THEN
    ALTER TABLE tutor_action_invocations
      ADD CONSTRAINT chk_tutor_action_invocations_lease_owner
      CHECK (char_length(lease_owner_id) BETWEEN 1 AND 160);
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS tutor_action_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invocation_id text NOT NULL REFERENCES tutor_action_invocations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  attempt_index integer NOT NULL CHECK (attempt_index >= 1),
  status text NOT NULL CHECK (status IN (
    'succeeded', 'retryable_failed', 'permanent_failed', 'denied',
    'cancelled', 'timed_out', 'superseded'
  )),
  authority_kind text CHECK (authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result'
  )),
  authority_id text CHECK (authority_id IS NULL OR char_length(authority_id) BETWEEN 1 AND 160),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  safe_result_json jsonb NOT NULL,
  diagnostic_code text CHECK (diagnostic_code IS NULL OR char_length(diagnostic_code) BETWEEN 1 AND 160),
  duration_ms integer NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_action_attempts_identity UNIQUE (invocation_id, attempt_index),
  CONSTRAINT fk_tutor_action_attempt_invocation_run
    FOREIGN KEY (invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_attempt_authority CHECK ((authority_kind IS NULL) = (authority_id IS NULL))
);

CREATE TABLE IF NOT EXISTS tutor_action_verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invocation_id text NOT NULL UNIQUE REFERENCES tutor_action_invocations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  status text NOT NULL CHECK (status IN ('pending', 'verified', 'failed', 'not_required')),
  verifier_id text NOT NULL CHECK (char_length(verifier_id) BETWEEN 1 AND 120),
  verifier_version text NOT NULL CHECK (char_length(verifier_version) BETWEEN 1 AND 80),
  authority_kind text CHECK (authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result'
  )),
  authority_id text CHECK (authority_id IS NULL OR char_length(authority_id) BETWEEN 1 AND 160),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  verification_hash text NOT NULL CHECK (verification_hash ~ '^[0-9a-f]{64}$'),
  safe_verification_json jsonb NOT NULL,
  diagnostic_code text CHECK (diagnostic_code IS NULL OR char_length(diagnostic_code) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_action_verification_invocation_run
    FOREIGN KEY (invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_verification_authority CHECK ((authority_kind IS NULL) = (authority_id IS NULL))
);

CREATE TABLE IF NOT EXISTS tutor_action_receipts (
  invocation_id text PRIMARY KEY REFERENCES tutor_action_invocations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  stable_action_key text NOT NULL CHECK (char_length(stable_action_key) BETWEEN 1 AND 160),
  action_id text NOT NULL CHECK (char_length(action_id) BETWEEN 1 AND 120),
  action_version text NOT NULL CHECK (char_length(action_version) BETWEEN 1 AND 80),
  status text NOT NULL CHECK (status IN (
    'verified', 'retryable_failed', 'permanent_failed', 'denied',
    'cancelled', 'timed_out', 'superseded'
  )),
  authority_kind text CHECK (authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result'
  )),
  authority_id text CHECK (authority_id IS NULL OR char_length(authority_id) BETWEEN 1 AND 160),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  safe_summary text NOT NULL CHECK (char_length(safe_summary) <= 160),
  result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
  verification_status text NOT NULL CHECK (verification_status IN ('pending', 'verified', 'failed', 'not_required')),
  verification_hash text CHECK (verification_hash IS NULL OR verification_hash ~ '^[0-9a-f]{64}$'),
  diagnostic_code text CHECK (diagnostic_code IS NULL OR char_length(diagnostic_code) BETWEEN 1 AND 160),
  recovery_kind text NOT NULL CHECK (recovery_kind IN ('none', 'retry', 'rebuild_context', 'request_clarification', 'safe_stop')),
  recovery_code text NOT NULL CHECK (char_length(recovery_code) BETWEEN 1 AND 160),
  retry_after_seconds integer NOT NULL DEFAULT 0 CHECK (retry_after_seconds BETWEEN 0 AND 300),
  receipt_json jsonb NOT NULL,
  receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  terminal_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_action_receipt_invocation_run
    FOREIGN KEY (invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_receipt_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_receipt_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_receipt_authority CHECK ((authority_kind IS NULL) = (authority_id IS NULL)),
  CONSTRAINT chk_tutor_action_receipt_retry CHECK (
    (recovery_kind = 'retry' AND retry_after_seconds >= 0)
    OR (recovery_kind <> 'retry' AND retry_after_seconds = 0)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_action_invocations_run_created
  ON tutor_action_invocations(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_action_invocations_state_created
  ON tutor_action_invocations(status, created_at);
CREATE INDEX IF NOT EXISTS idx_tutor_action_receipts_run_terminal
  ON tutor_action_receipts(run_id, terminal_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_action_receipts_current_verified
  ON tutor_action_receipts(run_id, input_revision, stable_action_key)
  WHERE status = 'verified';

CREATE OR REPLACE FUNCTION tutor_action_purge_allowed(target_invocation_id text)
RETURNS boolean AS $$
DECLARE
  target_user_id uuid;
BEGIN
  SELECT user_id INTO target_user_id
  FROM tutor_action_invocations
  WHERE id = target_invocation_id;
  RETURN target_user_id IS NOT NULL AND tutor_learning_track_purge_allowed(target_user_id);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_action_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_action_purge_allowed(OLD.invocation_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor action attempt, verification, and receipt rows are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_action_invocation_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_action_purge_allowed(OLD.id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor action invocations cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id
     OR OLD.run_id IS DISTINCT FROM NEW.run_id
     OR OLD.conversation_id IS DISTINCT FROM NEW.conversation_id
     OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.input_revision IS DISTINCT FROM NEW.input_revision
     OR OLD.lease_owner_id IS DISTINCT FROM NEW.lease_owner_id
     OR OLD.lease_generation IS DISTINCT FROM NEW.lease_generation
     OR OLD.action_generation IS DISTINCT FROM NEW.action_generation
     OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
     OR OLD.stable_action_key IS DISTINCT FROM NEW.stable_action_key
     OR OLD.action_id IS DISTINCT FROM NEW.action_id
     OR OLD.action_version IS DISTINCT FROM NEW.action_version
     OR OLD.descriptor_hash IS DISTINCT FROM NEW.descriptor_hash
     OR OLD.owner_adapter_id IS DISTINCT FROM NEW.owner_adapter_id
     OR OLD.task_kind IS DISTINCT FROM NEW.task_kind
     OR OLD.origin IS DISTINCT FROM NEW.origin
     OR OLD.catalog_digest IS DISTINCT FROM NEW.catalog_digest
     OR OLD.policy_fingerprint IS DISTINCT FROM NEW.policy_fingerprint
     OR OLD.selected_skill_reference IS DISTINCT FROM NEW.selected_skill_reference
     OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
     OR OLD.resource_profile_hash IS DISTINCT FROM NEW.resource_profile_hash
     OR OLD.resource_request_hash IS DISTINCT FROM NEW.resource_request_hash
     OR OLD.parent_invocation_id IS DISTINCT FROM NEW.parent_invocation_id
     OR OLD.retry_index IS DISTINCT FROM NEW.retry_index
     OR OLD.requested_at IS DISTINCT FROM NEW.requested_at
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Tutor action invocation identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status IN ('verified', 'retryable_failed', 'permanent_failed', 'denied', 'cancelled', 'timed_out', 'superseded') THEN
    RAISE EXCEPTION 'Terminal Tutor action invocation is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'requested' AND NEW.status IN ('admitted', 'denied') THEN RETURN NEW; END IF;
  IF OLD.status = 'admitted' AND NEW.status IN ('running', 'cancel_requested', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.status = 'running' AND NEW.status IN (
    'succeeded_unverified', 'retryable_failed', 'permanent_failed', 'denied',
    'timed_out', 'cancel_requested', 'superseded'
  ) THEN RETURN NEW; END IF;
  IF OLD.status = 'cancel_requested' AND NEW.status IN ('cancelled', 'succeeded_unverified') THEN RETURN NEW; END IF;
  IF OLD.status = 'succeeded_unverified' AND NEW.status IN (
    'verified', 'retryable_failed', 'permanent_failed', 'cancel_requested', 'superseded'
  ) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Tutor action invocation lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_action_attempts_immutable ON tutor_action_attempts;
CREATE TRIGGER trg_tutor_action_attempts_immutable
BEFORE UPDATE OR DELETE ON tutor_action_attempts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_append_only();
DROP TRIGGER IF EXISTS trg_tutor_action_verifications_immutable ON tutor_action_verifications;
CREATE TRIGGER trg_tutor_action_verifications_immutable
BEFORE UPDATE OR DELETE ON tutor_action_verifications
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_append_only();
DROP TRIGGER IF EXISTS trg_tutor_action_receipts_immutable ON tutor_action_receipts;
CREATE TRIGGER trg_tutor_action_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_action_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_append_only();
DROP TRIGGER IF EXISTS trg_tutor_action_invocations_lifecycle ON tutor_action_invocations;
CREATE TRIGGER trg_tutor_action_invocations_lifecycle
BEFORE UPDATE OR DELETE ON tutor_action_invocations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_invocation_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_action_invocations_updated_at ON tutor_action_invocations;
CREATE TRIGGER trg_tutor_action_invocations_updated_at
BEFORE UPDATE ON tutor_action_invocations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- Model code-review exercise authoring and pre-publication validation authority.
-- Private candidate/rubric/test payloads stay in these user-scoped tables and are never public projections.
DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'tutor_exercise_versions'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%exercise_type%'
  LOOP
    EXECUTE format('ALTER TABLE tutor_exercise_versions DROP CONSTRAINT %I', item.conname);
  END LOOP;
  ALTER TABLE tutor_exercise_versions
    ADD CONSTRAINT chk_tutor_exercise_versions_type CHECK (exercise_type IN (
      'code_completion', 'sql_query', 'browser_preview', 'static_code_reasoning', 'model_code_review'
    ));
END $$;

CREATE TABLE IF NOT EXISTS tutor_model_review_authoring_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  plan_revision_id uuid NOT NULL,
  lesson_assignment_id uuid NOT NULL,
  document_id uuid NOT NULL,
  slot_id uuid NOT NULL REFERENCES tutor_lesson_gate_slots(id) ON DELETE RESTRICT,
  gate_key text NOT NULL CHECK (gate_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_progress_version integer NOT NULL CHECK (expected_progress_version >= 1),
  expected_assignment_version integer NOT NULL CHECK (expected_assignment_version >= 1),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  required_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  mastery_level text NOT NULL CHECK (mastery_level ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  mastery_confidence double precision NOT NULL CHECK (mastery_confidence BETWEEN 0 AND 1),
  misconception_tags_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(misconception_tags_json) = 'array'),
  validation_profile_version text NOT NULL CHECK (validation_profile_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('pending', 'claimed', 'running', 'validating', 'completed', 'failed', 'cancelled')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  internal_conversation_id uuid,
  internal_run_id uuid,
  candidate_id uuid,
  validation_run_id uuid,
  publication_id uuid,
  failure_code text CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{2,79}$'),
  failure_message text CHECK (failure_message IS NULL OR char_length(failure_message) BETWEEN 1 AND 320),
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_authoring_scope UNIQUE (user_id, lesson_assignment_id, gate_key, request_hash),
  CONSTRAINT uq_tutor_model_review_authoring_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_model_review_authoring_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_authoring_assignment
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_authoring_slot
    FOREIGN KEY (document_id, gate_key) REFERENCES tutor_lesson_gate_slots(document_id, gate_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_model_review_authoring_terminal CHECK (
    (state IN ('completed', 'failed', 'cancelled')) = (terminal_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_model_review_authoring_lease CHECK (
    (lease_owner_id IS NULL) = (lease_expires_at IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_model_review_authoring_attempt_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  attempt_index integer NOT NULL CHECK (attempt_index >= 1),
  provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 160),
  model text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 160),
  protocol text NOT NULL CHECK (char_length(protocol) BETWEEN 1 AND 80),
  outcome text NOT NULL CHECK (outcome IN ('success', 'invalid', 'unavailable')),
  diagnostic_code text CHECK (diagnostic_code IS NULL OR diagnostic_code ~ '^[A-Z][A-Z0-9_]{2,79}$'),
  input_tokens bigint CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens bigint CHECK (output_tokens IS NULL OR output_tokens >= 0),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  response_hash text CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_authoring_attempt UNIQUE (authoring_run_id, attempt_index),
  CONSTRAINT fk_tutor_model_review_authoring_attempt_run
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  public_payload_json jsonb NOT NULL CHECK (jsonb_typeof(public_payload_json) = 'object'),
  private_payload_json jsonb NOT NULL CHECK (jsonb_typeof(private_payload_json) = 'object'),
  public_hash text NOT NULL CHECK (public_hash ~ '^[0-9a-f]{64}$'),
  private_hash text NOT NULL CHECK (private_hash ~ '^[0-9a-f]{64}$'),
  candidate_hash text NOT NULL CHECK (candidate_hash ~ '^[0-9a-f]{64}$'),
  generator_version text NOT NULL CHECK (generator_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  prompt_schema_version text NOT NULL CHECK (prompt_schema_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  validation_profile_version text NOT NULL CHECK (validation_profile_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  state text NOT NULL CHECK (state IN ('draft', 'validating', 'verified', 'rejected', 'published')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_candidates_scope UNIQUE (user_id, candidate_hash),
  CONSTRAINT uq_tutor_model_review_candidates_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_model_review_candidate_run
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_candidate_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_validation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  validation_profile_version text NOT NULL CHECK (validation_profile_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  candidate_hash text NOT NULL CHECK (candidate_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('pending', 'running', 'verified', 'failed', 'stale')),
  action_invocation_id text,
  action_receipt_hash text CHECK (action_receipt_hash IS NULL OR action_receipt_hash ~ '^[0-9a-f]{64}$'),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  check_summary_code text CHECK (check_summary_code IS NULL OR check_summary_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'),
  failure_code text CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{2,79}$'),
  safe_summary text CHECK (safe_summary IS NULL OR char_length(safe_summary) BETWEEN 1 AND 320),
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_validation_candidate UNIQUE (candidate_id, validation_profile_version),
  CONSTRAINT uq_tutor_model_review_validation_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_model_review_validation_authoring
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_validation_candidate
    FOREIGN KEY (candidate_id, user_id)
    REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_validation_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_model_review_validation_terminal CHECK (
    (state IN ('verified', 'failed', 'stale')) = (terminal_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_model_review_validation_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  validation_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  check_type text NOT NULL CHECK (check_type IN (
    'schema', 'parser', 'compile_or_typecheck', 'visible_tests', 'hidden_tests',
    'finding_reachability', 'rubric_consistency', 'coverage', 'redaction'
  )),
  status text NOT NULL CHECK (status IN ('passed', 'failed', 'not_applicable')),
  execution_job_id uuid REFERENCES tutor_execution_jobs(id) ON DELETE RESTRICT,
  proof_hash text NOT NULL CHECK (proof_hash ~ '^[0-9a-f]{64}$'),
  safe_code text NOT NULL CHECK (safe_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_validation_check UNIQUE (validation_run_id, check_type),
  CONSTRAINT fk_tutor_model_review_validation_check_run
    FOREIGN KEY (validation_run_id, user_id)
    REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_publications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  validation_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL REFERENCES tutor_lesson_gate_bindings(id) ON DELETE RESTRICT,
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  validation_authority_hash text NOT NULL CHECK (validation_authority_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_publication_candidate UNIQUE (candidate_id),
  CONSTRAINT uq_tutor_model_review_publication_gate UNIQUE (user_id, lesson_assignment_id, gate_binding_id),
  CONSTRAINT uq_tutor_model_review_publication_evidence_scope UNIQUE (id, user_id, lesson_assignment_id, gate_binding_id),
  CONSTRAINT fk_tutor_model_review_publication_authoring
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_candidate
    FOREIGN KEY (candidate_id, user_id)
    REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_validation
    FOREIGN KEY (validation_run_id, user_id)
    REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_assignment
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_evidence_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  publication_id uuid NOT NULL REFERENCES tutor_model_review_publications(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL,
  lesson_assignment_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL,
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  evidence_json jsonb NOT NULL CHECK (jsonb_typeof(evidence_json) = 'object'),
  evidence_hash text NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_evidence_idempotency UNIQUE (user_id, gate_binding_id, idempotency_key),
  CONSTRAINT fk_tutor_model_review_evidence_publication_scope
    FOREIGN KEY (publication_id, user_id, lesson_assignment_id, gate_binding_id)
    REFERENCES tutor_model_review_publications(id, user_id, lesson_assignment_id, gate_binding_id)
    ON DELETE RESTRICT
);

-- Add deferred circular references only after all model-review authority tables exist.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_candidate') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_candidate
      FOREIGN KEY (candidate_id, user_id) REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE NO ACTION
      DEFERRABLE INITIALLY IMMEDIATE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_validation') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_validation
      FOREIGN KEY (validation_run_id, user_id) REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE NO ACTION
      DEFERRABLE INITIALLY IMMEDIATE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_publication') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_publication
      FOREIGN KEY (publication_id) REFERENCES tutor_model_review_publications(id) ON DELETE NO ACTION
      DEFERRABLE INITIALLY IMMEDIATE;
  END IF;
  ALTER TABLE tutor_model_review_authoring_runs
    ALTER CONSTRAINT fk_tutor_model_review_authoring_candidate DEFERRABLE INITIALLY IMMEDIATE;
  ALTER TABLE tutor_model_review_authoring_runs
    ALTER CONSTRAINT fk_tutor_model_review_authoring_validation DEFERRABLE INITIALLY IMMEDIATE;
  ALTER TABLE tutor_model_review_authoring_runs
    ALTER CONSTRAINT fk_tutor_model_review_authoring_publication DEFERRABLE INITIALLY IMMEDIATE;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_internal_conversation') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_internal_conversation
      FOREIGN KEY (internal_conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_internal_run') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_internal_run
      FOREIGN KEY (internal_run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT;
  END IF;
END $$;

ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS model_review_candidate_id uuid;
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS model_review_validation_id uuid;
ALTER TABLE tutor_execution_jobs ADD COLUMN IF NOT EXISTS model_review_validation_id uuid;

ALTER TABLE tutor_execution_intents DROP CONSTRAINT IF EXISTS chk_tutor_execution_intents_source_shape;
ALTER TABLE tutor_execution_intents ADD CONSTRAINT chk_tutor_execution_intents_source_shape CHECK (
  (
    source_kind = 'tutor_message'
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND source_message_id IS NOT NULL
    AND exercise_id IS NOT NULL AND input_revision IS NOT NULL
    AND exercise_attempt_id IS NULL AND exercise_submission_id IS NULL AND exercise_version_id IS NULL
    AND model_review_candidate_id IS NULL AND model_review_validation_id IS NULL
    AND origin IN ('interactive', 'proactive')
    AND ((consumed_at IS NULL) = (consumed_by_effect_id IS NULL))
  )
  OR (
    source_kind = 'exercise_submission'
    AND conversation_id IS NULL AND run_id IS NULL AND source_message_id IS NULL AND exercise_id IS NULL
    AND input_revision IS NULL AND origin = 'exercise_gate'
    AND exercise_attempt_id IS NOT NULL AND exercise_submission_id IS NOT NULL AND exercise_version_id IS NOT NULL
    AND model_review_candidate_id IS NULL AND model_review_validation_id IS NULL
    AND consumed_by_effect_id IS NULL
  )
  OR (
    source_kind = 'model_review_candidate'
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND source_message_id IS NULL AND exercise_id IS NULL
    AND input_revision IS NOT NULL AND origin = 'proactive'
    AND exercise_attempt_id IS NULL AND exercise_submission_id IS NULL AND exercise_version_id IS NULL
    AND model_review_candidate_id IS NOT NULL AND model_review_validation_id IS NOT NULL
    AND consumed_by_effect_id IS NULL
  )
) NOT VALID;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tutor_execution_intents_model_review_scope') THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT uq_tutor_execution_intents_model_review_scope
      UNIQUE (id, model_review_validation_id, user_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_intent_model_review_candidate') THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_model_review_candidate
      FOREIGN KEY (model_review_candidate_id, user_id)
      REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_intent_model_review_validation') THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_model_review_validation
      FOREIGN KEY (model_review_validation_id, user_id)
      REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

ALTER TABLE tutor_execution_jobs DROP CONSTRAINT IF EXISTS chk_tutor_execution_jobs_owner_shape;
ALTER TABLE tutor_execution_jobs ADD CONSTRAINT chk_tutor_execution_jobs_owner_shape CHECK (
  (
    owner_kind = 'tutor_effect'
    AND effect_record_id IS NOT NULL AND effect_key IS NOT NULL
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL
    AND exercise_attempt_id IS NULL AND model_review_validation_id IS NULL
  )
  OR (
    owner_kind = 'exercise_attempt'
    AND effect_record_id IS NULL AND effect_key IS NULL
    AND conversation_id IS NULL AND run_id IS NULL
    AND exercise_attempt_id IS NOT NULL AND model_review_validation_id IS NULL
  )
  OR (
    owner_kind = 'model_review_validation'
    AND effect_record_id IS NULL AND effect_key IS NULL
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL
    AND exercise_attempt_id IS NULL AND model_review_validation_id IS NOT NULL
  )
) NOT VALID;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tutor_execution_jobs_model_review_scope') THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT uq_tutor_execution_jobs_model_review_scope
      UNIQUE (id, model_review_validation_id, user_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_job_model_review_intent_scope') THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_model_review_intent_scope
      FOREIGN KEY (intent_id, model_review_validation_id, user_id)
      REFERENCES tutor_execution_intents(id, model_review_validation_id, user_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_job_model_review_validation') THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_model_review_validation
      FOREIGN KEY (model_review_validation_id, user_id)
      REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

-- Extend existing Action receipt authority without changing the lifecycle state machine.
ALTER TABLE tutor_action_attempts DROP CONSTRAINT IF EXISTS tutor_action_attempts_authority_kind_check;
ALTER TABLE tutor_action_attempts ADD CONSTRAINT tutor_action_attempts_authority_kind_check CHECK (
  authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result',
    'model_review_validation'
  )
);
ALTER TABLE tutor_action_verifications DROP CONSTRAINT IF EXISTS tutor_action_verifications_authority_kind_check;
ALTER TABLE tutor_action_verifications ADD CONSTRAINT tutor_action_verifications_authority_kind_check CHECK (
  authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result',
    'model_review_validation'
  )
);
ALTER TABLE tutor_action_receipts DROP CONSTRAINT IF EXISTS tutor_action_receipts_authority_kind_check;
ALTER TABLE tutor_action_receipts ADD CONSTRAINT tutor_action_receipts_authority_kind_check CHECK (
  authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result',
    'model_review_validation'
  )
);

CREATE OR REPLACE FUNCTION tutor_model_review_purge_allowed(target_user_id uuid)
RETURNS boolean AS $$
BEGIN
  RETURN tutor_learning_track_purge_allowed(target_user_id);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Model review receipt and publication rows are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_authoring_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Model review authoring run cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.track_id IS DISTINCT FROM NEW.track_id OR OLD.knowledge_key IS DISTINCT FROM NEW.knowledge_key
     OR OLD.plan_revision_id IS DISTINCT FROM NEW.plan_revision_id
     OR OLD.lesson_assignment_id IS DISTINCT FROM NEW.lesson_assignment_id
     OR OLD.document_id IS DISTINCT FROM NEW.document_id OR OLD.slot_id IS DISTINCT FROM NEW.slot_id
     OR OLD.gate_key IS DISTINCT FROM NEW.gate_key
     OR OLD.expected_track_version IS DISTINCT FROM NEW.expected_track_version
     OR OLD.expected_progress_version IS DISTINCT FROM NEW.expected_progress_version
     OR OLD.expected_assignment_version IS DISTINCT FROM NEW.expected_assignment_version
     OR OLD.language_id IS DISTINCT FROM NEW.language_id
     OR OLD.required_capabilities_json IS DISTINCT FROM NEW.required_capabilities_json
     OR OLD.mastery_level IS DISTINCT FROM NEW.mastery_level
     OR OLD.mastery_confidence IS DISTINCT FROM NEW.mastery_confidence
     OR OLD.misconception_tags_json IS DISTINCT FROM NEW.misconception_tags_json
     OR OLD.validation_profile_version IS DISTINCT FROM NEW.validation_profile_version
     OR OLD.request_hash IS DISTINCT FROM NEW.request_hash OR OLD.profile_hash IS DISTINCT FROM NEW.profile_hash
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Model review authoring identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('completed', 'failed', 'cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal model review authoring run is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'pending' AND NEW.state IN ('claimed', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'claimed' AND NEW.state IN ('running', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('validating', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'validating' AND NEW.state IN ('completed', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Model review authoring transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_candidate_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Model review candidate cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id OR OLD.authoring_run_id IS DISTINCT FROM NEW.authoring_run_id
     OR OLD.user_id IS DISTINCT FROM NEW.user_id OR OLD.track_id IS DISTINCT FROM NEW.track_id
     OR OLD.knowledge_key IS DISTINCT FROM NEW.knowledge_key
     OR OLD.public_payload_json IS DISTINCT FROM NEW.public_payload_json
     OR OLD.private_payload_json IS DISTINCT FROM NEW.private_payload_json
     OR OLD.public_hash IS DISTINCT FROM NEW.public_hash OR OLD.private_hash IS DISTINCT FROM NEW.private_hash
     OR OLD.candidate_hash IS DISTINCT FROM NEW.candidate_hash
     OR OLD.generator_version IS DISTINCT FROM NEW.generator_version
     OR OLD.prompt_schema_version IS DISTINCT FROM NEW.prompt_schema_version
     OR OLD.validation_profile_version IS DISTINCT FROM NEW.validation_profile_version
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Model review candidate payload is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('rejected', 'published') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal model review candidate is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'draft' AND NEW.state IN ('validating', 'rejected') THEN RETURN NEW; END IF;
  IF OLD.state = 'validating' AND NEW.state IN ('verified', 'rejected') THEN RETURN NEW; END IF;
  IF OLD.state = 'verified' AND NEW.state IN ('published', 'rejected') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Model review candidate transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_validation_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Model review validation run cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id OR OLD.authoring_run_id IS DISTINCT FROM NEW.authoring_run_id
     OR OLD.candidate_id IS DISTINCT FROM NEW.candidate_id OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.track_id IS DISTINCT FROM NEW.track_id
     OR OLD.validation_profile_version IS DISTINCT FROM NEW.validation_profile_version
     OR OLD.candidate_hash IS DISTINCT FROM NEW.candidate_hash OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Model review validation identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'verified' AND NEW.state = 'verified'
     AND OLD.action_receipt_hash IS NULL AND NEW.action_receipt_hash IS NOT NULL
     AND OLD.id IS NOT DISTINCT FROM NEW.id
     AND OLD.authoring_run_id IS NOT DISTINCT FROM NEW.authoring_run_id
     AND OLD.candidate_id IS NOT DISTINCT FROM NEW.candidate_id
     AND OLD.user_id IS NOT DISTINCT FROM NEW.user_id
     AND OLD.track_id IS NOT DISTINCT FROM NEW.track_id
     AND OLD.validation_profile_version IS NOT DISTINCT FROM NEW.validation_profile_version
     AND OLD.candidate_hash IS NOT DISTINCT FROM NEW.candidate_hash
     AND OLD.action_invocation_id IS NOT DISTINCT FROM NEW.action_invocation_id
     AND OLD.authority_hash IS NOT DISTINCT FROM NEW.authority_hash
     AND OLD.check_summary_code IS NOT DISTINCT FROM NEW.check_summary_code
     AND OLD.failure_code IS NOT DISTINCT FROM NEW.failure_code
     AND OLD.safe_summary IS NOT DISTINCT FROM NEW.safe_summary
     AND OLD.terminal_at IS NOT DISTINCT FROM NEW.terminal_at
     AND OLD.created_at IS NOT DISTINCT FROM NEW.created_at THEN
    RETURN NEW;
  END IF;
  IF OLD.state IN ('verified', 'failed', 'stale') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal model review validation run is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'pending' AND NEW.state IN ('running', 'failed', 'stale') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('verified', 'failed', 'stale') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Model review validation transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_model_review_authoring_runs_lifecycle ON tutor_model_review_authoring_runs;
CREATE TRIGGER trg_tutor_model_review_authoring_runs_lifecycle
BEFORE UPDATE OR DELETE ON tutor_model_review_authoring_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_authoring_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_model_review_authoring_runs_updated_at ON tutor_model_review_authoring_runs;
CREATE TRIGGER trg_tutor_model_review_authoring_runs_updated_at
BEFORE UPDATE ON tutor_model_review_authoring_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_model_review_candidates_lifecycle ON tutor_model_review_candidates;
CREATE TRIGGER trg_tutor_model_review_candidates_lifecycle
BEFORE UPDATE OR DELETE ON tutor_model_review_candidates
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_candidate_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_model_review_candidates_updated_at ON tutor_model_review_candidates;
CREATE TRIGGER trg_tutor_model_review_candidates_updated_at
BEFORE UPDATE ON tutor_model_review_candidates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_model_review_validation_runs_lifecycle ON tutor_model_review_validation_runs;
CREATE TRIGGER trg_tutor_model_review_validation_runs_lifecycle
BEFORE UPDATE OR DELETE ON tutor_model_review_validation_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_validation_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_model_review_validation_runs_updated_at ON tutor_model_review_validation_runs;
CREATE TRIGGER trg_tutor_model_review_validation_runs_updated_at
BEFORE UPDATE ON tutor_model_review_validation_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_model_review_authoring_attempts_immutable ON tutor_model_review_authoring_attempt_receipts;
CREATE TRIGGER trg_tutor_model_review_authoring_attempts_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_authoring_attempt_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_model_review_validation_checks_immutable ON tutor_model_review_validation_checks;
CREATE TRIGGER trg_tutor_model_review_validation_checks_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_validation_checks
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_model_review_publications_immutable ON tutor_model_review_publications;
CREATE TRIGGER trg_tutor_model_review_publications_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_publications
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_model_review_evidence_immutable ON tutor_model_review_evidence_receipts;
CREATE TRIGGER trg_tutor_model_review_evidence_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_evidence_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();

CREATE INDEX IF NOT EXISTS idx_tutor_model_review_authoring_active
  ON tutor_model_review_authoring_runs(user_id, track_id, knowledge_key, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_model_review_candidates_authoring
  ON tutor_model_review_candidates(authoring_run_id, state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_model_review_validation_state
  ON tutor_model_review_validation_runs(state, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_execution_intents_model_review_validation
  ON tutor_execution_intents(model_review_validation_id)
  WHERE model_review_validation_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_execution_jobs_model_review_validation
  ON tutor_execution_jobs(model_review_validation_id)
  WHERE model_review_validation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_model_review_publications_scope
  ON tutor_model_review_publications(user_id, track_id, knowledge_key, published_at DESC);


-- Detailed assistance records whether a model-review learner viewed prepublication evidence.
ALTER TABLE tutor_exercise_attempts
  ADD COLUMN IF NOT EXISTS assistance_kind text NOT NULL DEFAULT 'independent';
ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS tutor_exercise_attempts_assistance_kind_check;
ALTER TABLE tutor_exercise_attempts ADD CONSTRAINT tutor_exercise_attempts_assistance_kind_check CHECK (
  assistance_kind IN ('independent', 'hinted', 'validation_evidence_viewed', 'remediated')
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_model_review_publications'::regclass
      AND conname = 'uq_tutor_model_review_publications_id_user'
  ) THEN
    ALTER TABLE tutor_model_review_publications
      ADD CONSTRAINT uq_tutor_model_review_publications_id_user UNIQUE (id, user_id);
  END IF;
END $$;
ALTER TABLE tutor_model_review_authoring_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_model_review_authoring_candidate;
ALTER TABLE tutor_model_review_authoring_runs
  ADD CONSTRAINT fk_tutor_model_review_authoring_candidate
  FOREIGN KEY (candidate_id, user_id)
  REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE NO ACTION
  DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE tutor_model_review_authoring_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_model_review_authoring_validation;
ALTER TABLE tutor_model_review_authoring_runs
  ADD CONSTRAINT fk_tutor_model_review_authoring_validation
  FOREIGN KEY (validation_run_id, user_id)
  REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE NO ACTION
  DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE tutor_model_review_authoring_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_model_review_authoring_publication;
ALTER TABLE tutor_model_review_authoring_runs
  ADD CONSTRAINT fk_tutor_model_review_authoring_publication
  FOREIGN KEY (publication_id, user_id)
  REFERENCES tutor_model_review_publications(id, user_id) ON DELETE NO ACTION
  DEFERRABLE INITIALLY IMMEDIATE;


-- Track-scoped spaced review and finite ReviewSession authority.
-- This is additive and does not reopen the retired review_states/review_logs runtime.
CREATE TABLE IF NOT EXISTS tutor_review_schedule_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_plan_revision_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
  card_state text NOT NULL CHECK (card_state IN ('new', 'learning', 'review', 'relearning', 'suspended')),
  stability double precision NOT NULL CHECK (stability >= 0.1 AND stability <= 3650),
  difficulty double precision NOT NULL CHECK (difficulty BETWEEN 1 AND 10),
  due_at timestamptz NOT NULL,
  last_review_at timestamptz,
  review_count integer NOT NULL DEFAULT 0 CHECK (review_count >= 0),
  lapse_count integer NOT NULL DEFAULT 0 CHECK (lapse_count >= 0),
  last_rating text CHECK (last_rating IS NULL OR last_rating IN ('again', 'hard', 'good', 'easy')),
  risk_level text NOT NULL DEFAULT 'normal' CHECK (risk_level IN ('low', 'normal', 'high', 'critical')),
  scheduler_version text NOT NULL CHECK (scheduler_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_schedule_track_key UNIQUE (track_id, knowledge_key),
  CONSTRAINT uq_tutor_review_schedule_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_review_schedule_progress
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_schedule_revision
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_review_schedule_suspend_shape CHECK (
    (status = 'suspended') = (card_state = 'suspended')
  )
);

CREATE TABLE IF NOT EXISTS tutor_review_schedule_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  source_kind text NOT NULL CHECK (source_kind IN ('mastery_seed', 'diagnostic_skip', 'session_finalization', 'plan_migration')),
  source_receipt_id text NOT NULL CHECK (char_length(source_receipt_id) BETWEEN 1 AND 160),
  reason_codes_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reason_codes_json) = 'array'),
  previous_state_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(previous_state_json) = 'object'),
  next_state_json jsonb NOT NULL CHECK (jsonb_typeof(next_state_json) = 'object'),
  event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  scheduler_version text NOT NULL CHECK (scheduler_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_schedule_event_source UNIQUE (schedule_id, source_kind, source_receipt_id),
  CONSTRAINT uq_tutor_review_schedule_event_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_review_schedule_event_scope
    FOREIGN KEY (schedule_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_review_schedule_states(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_review_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  plan_revision_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_schedule_version integer NOT NULL CHECK (expected_schedule_version >= 1),
  state text NOT NULL CHECK (state IN ('blocked', 'active', 'ready_to_finalize', 'finalized', 'cancelled')),
  stage text NOT NULL CHECK (stage IN ('warmup', 'practice', 'final_summary')),
  failure_code text CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  context_snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(context_snapshot_json) = 'object'),
  context_snapshot_hash text NOT NULL CHECK (context_snapshot_hash ~ '^[0-9a-f]{64}$'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  started_at timestamptz NOT NULL,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_sessions_id_scope UNIQUE (id, user_id, track_id),
  CONSTRAINT uq_tutor_review_sessions_idempotency UNIQUE (user_id, track_id, idempotency_key),
  CONSTRAINT fk_tutor_review_session_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_session_revision
    FOREIGN KEY (plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_session_progress
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_review_session_terminal CHECK (
    (state IN ('finalized', 'cancelled')) = (terminal_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_review_session_failure CHECK (
    (state = 'blocked') = (failure_code IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_review_session_stage CHECK (
    (state = 'finalized') = (stage = 'final_summary')
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_review_sessions_one_active
  ON tutor_review_sessions(user_id, track_id)
  WHERE state IN ('blocked', 'active', 'ready_to_finalize');

CREATE TABLE IF NOT EXISTS tutor_review_warmup_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  response_kind text NOT NULL CHECK (response_kind IN ('answered', 'skipped')),
  response_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(response_summary_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_warmup_session UNIQUE (session_id),
  CONSTRAINT uq_tutor_review_warmup_idempotency UNIQUE (user_id, session_id, idempotency_key),
  CONSTRAINT fk_tutor_review_warmup_session
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_review_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  plan_revision_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  order_index integer NOT NULL CHECK (order_index >= 0),
  selection_reason_json jsonb NOT NULL CHECK (jsonb_typeof(selection_reason_json) = 'object'),
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  version integer NOT NULL DEFAULT 1 CHECK (version = 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_items_session_order UNIQUE (session_id, order_index),
  CONSTRAINT uq_tutor_review_items_session_exercise UNIQUE (session_id, exercise_version_id),
  CONSTRAINT uq_tutor_review_items_scope UNIQUE (
    id, session_id, user_id, track_id, knowledge_key, exercise_version_id
  ),
  CONSTRAINT fk_tutor_review_item_session
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_item_node
    FOREIGN KEY (plan_revision_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_review_hint_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  item_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  exercise_version_id uuid NOT NULL,
  hint_level integer NOT NULL CHECK (hint_level BETWEEN 1 AND 3),
  hint_policy_version text NOT NULL CHECK (hint_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  safe_hint_json jsonb NOT NULL CHECK (jsonb_typeof(safe_hint_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_hint_idempotency UNIQUE (user_id, item_id, idempotency_key),
  CONSTRAINT fk_tutor_review_hint_item
    FOREIGN KEY (item_id, session_id, user_id, track_id, knowledge_key, exercise_version_id)
    REFERENCES tutor_review_items(id, session_id, user_id, track_id, knowledge_key, exercise_version_id)
    ON DELETE RESTRICT
);

ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS review_session_id uuid;
ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS review_item_id uuid;
ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS expected_review_session_version integer;
ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS expected_review_item_version integer;

ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS tutor_exercise_attempts_attempt_type_check;
ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS chk_tutor_exercise_attempts_type;
ALTER TABLE tutor_exercise_attempts ADD CONSTRAINT chk_tutor_exercise_attempts_type CHECK (
  attempt_type IN ('run', 'submit', 'diagnostic_submit', 'review_submit')
);
ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS chk_tutor_exercise_attempts_owner_shape;
ALTER TABLE tutor_exercise_attempts ADD CONSTRAINT chk_tutor_exercise_attempts_owner_shape CHECK (
  (
    attempt_type IN ('run', 'submit')
    AND lesson_assignment_id IS NOT NULL AND document_id IS NOT NULL AND gate_binding_id IS NOT NULL
    AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
    AND review_session_id IS NULL AND review_item_id IS NULL
    AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
    AND expected_progress_version IS NOT NULL
  )
  OR (
    attempt_type = 'diagnostic_submit'
    AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
    AND diagnostic_session_id IS NOT NULL AND diagnostic_item_id IS NOT NULL
    AND review_session_id IS NULL AND review_item_id IS NULL
    AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
    AND expected_progress_version IS NULL
  )
  OR (
    attempt_type = 'review_submit'
    AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
    AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
    AND review_session_id IS NOT NULL AND review_item_id IS NOT NULL
    AND expected_review_session_version IS NOT NULL AND expected_review_session_version >= 1
    AND expected_review_item_version IS NOT NULL AND expected_review_item_version = 1
    AND expected_progress_version IS NULL
  )
);
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_exercise_attempts'::regclass
      AND conname = 'fk_tutor_exercise_attempt_review_item_scope'
  ) THEN
    ALTER TABLE tutor_exercise_attempts
      ADD CONSTRAINT fk_tutor_exercise_attempt_review_item_scope
      FOREIGN KEY (
        review_item_id, review_session_id, user_id, track_id, knowledge_key, exercise_version_id
      ) REFERENCES tutor_review_items(
        id, session_id, user_id, track_id, knowledge_key, exercise_version_id
      ) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_tutor_exercise_attempts_review
  ON tutor_exercise_attempts(review_session_id, review_item_id, accepted_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_exercise_attempts_review_item
  ON tutor_exercise_attempts(review_item_id) WHERE attempt_type = 'review_submit';

CREATE TABLE IF NOT EXISTS tutor_review_finalizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  mastery_evidence_id uuid NOT NULL,
  schedule_event_id uuid NOT NULL,
  rating text NOT NULL CHECK (rating IN ('again', 'hard', 'good', 'easy')),
  aggregate_json jsonb NOT NULL CHECK (jsonb_typeof(aggregate_json) = 'object'),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_finalization_session UNIQUE (session_id),
  CONSTRAINT uq_tutor_review_finalization_idempotency UNIQUE (user_id, session_id, idempotency_key),
  CONSTRAINT fk_tutor_review_finalization_session
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_finalization_mastery
    FOREIGN KEY (mastery_evidence_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_mastery_evidence(id, track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_finalization_schedule_event
    FOREIGN KEY (schedule_event_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_review_schedule_events(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT
);

-- Upgrade databases that bootstrapped an earlier draft of the ReviewSession schema.
ALTER TABLE tutor_review_sessions DROP CONSTRAINT IF EXISTS chk_tutor_review_session_terminal;
ALTER TABLE tutor_review_sessions ADD CONSTRAINT chk_tutor_review_session_terminal CHECK (
  (state IN ('finalized', 'cancelled')) = (terminal_at IS NOT NULL)
);
DROP INDEX IF EXISTS uq_tutor_review_sessions_one_active;
CREATE UNIQUE INDEX uq_tutor_review_sessions_one_active
  ON tutor_review_sessions(user_id, track_id)
  WHERE state IN ('blocked', 'active', 'ready_to_finalize');
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_review_schedule_events'::regclass
      AND conname = 'uq_tutor_review_schedule_event_scope'
  ) THEN
    ALTER TABLE tutor_review_schedule_events
      ADD CONSTRAINT uq_tutor_review_schedule_event_scope
      UNIQUE (id, user_id, track_id, knowledge_key);
  END IF;
END $$;
ALTER TABLE tutor_review_finalizations
  DROP CONSTRAINT IF EXISTS tutor_review_finalizations_schedule_event_id_fkey;
ALTER TABLE tutor_review_finalizations
  DROP CONSTRAINT IF EXISTS fk_tutor_review_finalization_schedule_event;
ALTER TABLE tutor_review_finalizations
  ADD CONSTRAINT fk_tutor_review_finalization_schedule_event
  FOREIGN KEY (schedule_event_id, user_id, track_id, knowledge_key)
  REFERENCES tutor_review_schedule_events(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION enforce_tutor_review_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Review receipts and items are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_review_schedule_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Review schedule cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Review schedule identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.version <> OLD.version + 1 THEN
    RAISE EXCEPTION 'Review schedule version must advance exactly once' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_review_session_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Review session cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.plan_revision_id IS DISTINCT FROM OLD.plan_revision_id
     OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.expected_track_version IS DISTINCT FROM OLD.expected_track_version
     OR NEW.expected_schedule_version IS DISTINCT FROM OLD.expected_schedule_version
     OR NEW.context_snapshot_json IS DISTINCT FROM OLD.context_snapshot_json
     OR NEW.context_snapshot_hash IS DISTINCT FROM OLD.context_snapshot_hash
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
     OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Review session identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('finalized', 'cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal review session is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.version <> OLD.version + 1 THEN
    RAISE EXCEPTION 'Review session version must advance exactly once' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'blocked' AND NEW.state IN ('blocked', 'active', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'active' AND NEW.state IN ('active', 'ready_to_finalize', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'ready_to_finalize' AND NEW.state IN ('active', 'ready_to_finalize', 'finalized', 'cancelled') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Review session transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_review_schedule_states_updated_at ON tutor_review_schedule_states;
CREATE TRIGGER trg_tutor_review_schedule_states_updated_at
BEFORE UPDATE ON tutor_review_schedule_states FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_review_schedule_states_lifecycle ON tutor_review_schedule_states;
CREATE TRIGGER trg_tutor_review_schedule_states_lifecycle
BEFORE UPDATE OR DELETE ON tutor_review_schedule_states
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_schedule_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_review_sessions_updated_at ON tutor_review_sessions;
CREATE TRIGGER trg_tutor_review_sessions_updated_at
BEFORE UPDATE ON tutor_review_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_review_sessions_lifecycle ON tutor_review_sessions;
CREATE TRIGGER trg_tutor_review_sessions_lifecycle
BEFORE UPDATE OR DELETE ON tutor_review_sessions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_session_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_review_schedule_events_immutable ON tutor_review_schedule_events;
CREATE TRIGGER trg_tutor_review_schedule_events_immutable
BEFORE UPDATE OR DELETE ON tutor_review_schedule_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_warmups_immutable ON tutor_review_warmup_receipts;
CREATE TRIGGER trg_tutor_review_warmups_immutable
BEFORE UPDATE OR DELETE ON tutor_review_warmup_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_items_immutable ON tutor_review_items;
CREATE TRIGGER trg_tutor_review_items_immutable
BEFORE UPDATE OR DELETE ON tutor_review_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_hints_immutable ON tutor_review_hint_receipts;
CREATE TRIGGER trg_tutor_review_hints_immutable
BEFORE UPDATE OR DELETE ON tutor_review_hint_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_finalizations_immutable ON tutor_review_finalizations;
CREATE TRIGGER trg_tutor_review_finalizations_immutable
BEFORE UPDATE OR DELETE ON tutor_review_finalizations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();

CREATE INDEX IF NOT EXISTS idx_tutor_review_schedule_due
  ON tutor_review_schedule_states(user_id, track_id, status, due_at, knowledge_key);
CREATE INDEX IF NOT EXISTS idx_tutor_review_schedule_events_created
  ON tutor_review_schedule_events(schedule_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tutor_review_sessions_scope
  ON tutor_review_sessions(user_id, track_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_review_items_session
  ON tutor_review_items(session_id, order_index);
CREATE INDEX IF NOT EXISTS idx_tutor_review_hints_item
  ON tutor_review_hint_receipts(item_id, created_at, id);

-- Child 08-04 workspace context references: immutable learner-safe snapshots
-- bound to one accepted learner message and exact TurnRun input revision.
CREATE TABLE IF NOT EXISTS tutor_message_context_references (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  run_id uuid NOT NULL,
  message_id uuid NOT NULL,
  input_revision integer NOT NULL CHECK (input_revision > 0),
  reference_index integer NOT NULL CHECK (reference_index BETWEEN 0 AND 5),
  reference_kind text NOT NULL CHECK (reference_kind IN (
    'lesson_selection', 'exercise_feedback', 'execution_result', 'review_feedback'
  )),
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  document_id uuid,
  attempt_id uuid,
  review_session_id uuid,
  exercise_version_id uuid,
  source_version text NOT NULL CHECK (char_length(source_version) BETWEEN 1 AND 160),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  safe_payload_json jsonb NOT NULL CHECK (jsonb_typeof(safe_payload_json) = 'object'),
  safe_payload_hash text NOT NULL CHECK (safe_payload_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_message_context_references_input_index
    UNIQUE (run_id, input_revision, reference_index),
  CONSTRAINT uq_tutor_message_context_references_message_index
    UNIQUE (message_id, reference_index),
  CONSTRAINT uq_tutor_message_context_references_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_context_reference_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_message_conversation
    FOREIGN KEY (message_id, conversation_id) REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_input_revision
    FOREIGN KEY (run_id, input_revision) REFERENCES tutor_run_input_events(run_id, input_revision) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_document_scope
    FOREIGN KEY (document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_documents(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_attempt_scope
    FOREIGN KEY (attempt_id, user_id, track_id, exercise_version_id)
    REFERENCES tutor_exercise_attempts(id, user_id, track_id, exercise_version_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_review_scope
    FOREIGN KEY (review_session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_message_context_reference_shape CHECK (
    (reference_kind = 'lesson_selection'
      AND document_id IS NOT NULL AND attempt_id IS NULL
      AND review_session_id IS NULL AND exercise_version_id IS NULL)
    OR
    (reference_kind IN ('exercise_feedback', 'execution_result')
      AND document_id IS NULL AND attempt_id IS NOT NULL
      AND review_session_id IS NULL AND exercise_version_id IS NOT NULL)
    OR
    (reference_kind = 'review_feedback'
      AND document_id IS NULL AND attempt_id IS NOT NULL
      AND review_session_id IS NOT NULL AND exercise_version_id IS NOT NULL)
  )
);

CREATE OR REPLACE FUNCTION enforce_tutor_message_context_reference_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Tutor message context references are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_message_context_references_immutable
  ON tutor_message_context_references;
CREATE TRIGGER trg_tutor_message_context_references_immutable
BEFORE UPDATE OR DELETE ON tutor_message_context_references
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_message_context_reference_immutable();

CREATE INDEX IF NOT EXISTS idx_tutor_message_context_references_message
  ON tutor_message_context_references(user_id, conversation_id, message_id, reference_index);
CREATE INDEX IF NOT EXISTS idx_tutor_message_context_references_input
  ON tutor_message_context_references(user_id, run_id, input_revision, reference_index);

-- Child 08-13 Tutor Thread/Turn v2 foundation: versioned public event and durable dispatch authority.
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS next_public_event_sequence bigint NOT NULL DEFAULT 1;
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS control_version bigint NOT NULL DEFAULT 1;
ALTER TABLE tutor_conversations
  DROP CONSTRAINT IF EXISTS chk_tutor_conversations_next_public_event_sequence;
ALTER TABLE tutor_conversations
  ADD CONSTRAINT chk_tutor_conversations_next_public_event_sequence
  CHECK (next_public_event_sequence >= 1);
ALTER TABLE tutor_conversations
  DROP CONSTRAINT IF EXISTS chk_tutor_conversations_control_version;
ALTER TABLE tutor_conversations
  ADD CONSTRAINT chk_tutor_conversations_control_version
  CHECK (control_version >= 1);

ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS interaction_protocol_version text;
UPDATE tutor_runs
SET interaction_protocol_version = 'legacy_v1'
WHERE interaction_protocol_version IS NULL;
ALTER TABLE tutor_runs
  ALTER COLUMN interaction_protocol_version SET NOT NULL;
ALTER TABLE tutor_runs
  ALTER COLUMN interaction_protocol_version SET DEFAULT 'thread_turn_v2';
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS retry_of_turn_id uuid;
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS retry_root_turn_id uuid;
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_interaction_protocol_version;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_interaction_protocol_version
  CHECK (interaction_protocol_version IN ('legacy_v1', 'thread_turn_v2'));
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_retry_lineage_distinct;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_retry_lineage_distinct
  CHECK (
    (retry_of_turn_id IS NULL OR retry_of_turn_id <> id)
    AND (retry_root_turn_id IS NULL OR retry_root_turn_id <> id)
  );

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'uq_tutor_runs_id_user_conversation'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT uq_tutor_runs_id_user_conversation UNIQUE (id, user_id, conversation_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'fk_tutor_runs_retry_of_turn_scope'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT fk_tutor_runs_retry_of_turn_scope
      FOREIGN KEY (retry_of_turn_id, user_id, conversation_id)
      REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'fk_tutor_runs_retry_root_turn_scope'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT fk_tutor_runs_retry_root_turn_scope
      FOREIGN KEY (retry_root_turn_id, user_id, conversation_id)
      REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT;
  END IF;
END $$;

ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS tutor_run_public_processes_display_state_check;
ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_display_state;
ALTER TABLE tutor_run_public_processes
  ADD CONSTRAINT chk_tutor_public_process_display_state
  CHECK (display_state IN (
    'thinking', 'waiting_input', 'waiting_approval', 'waiting_authority',
    'completed', 'interrupted', 'superseded', 'unavailable', 'failed'
  ));
ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_finished_state;
ALTER TABLE tutor_run_public_processes
  ADD CONSTRAINT chk_tutor_public_process_finished_state CHECK (
    (display_state IN ('thinking', 'waiting_input', 'waiting_approval', 'waiting_authority') AND finished_at IS NULL)
    OR
    (display_state IN ('completed', 'interrupted', 'superseded', 'unavailable', 'failed') AND finished_at IS NOT NULL)
  );

CREATE TABLE IF NOT EXISTS tutor_conversation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  event_sequence bigint NOT NULL CHECK (event_sequence > 0),
  event_key text NOT NULL CHECK (char_length(event_key) BETWEEN 1 AND 160),
  kind text NOT NULL CHECK (kind IN (
    'turn_created', 'turn_updated', 'item_added', 'item_updated', 'turn_output',
    'control_updated', 'dispatch_delayed', 'dispatch_dead'
  )),
  turn_id uuid,
  item_id uuid,
  item_kind text CHECK (item_kind IS NULL OR item_kind IN (
    'message', 'process', 'elicitation', 'approval', 'error'
  )),
  projection_version text NOT NULL DEFAULT 'tutor_conversation_event_v2'
    CHECK (projection_version IN ('tutor_conversation_event_v1', 'tutor_conversation_event_v2')),
  payload_json jsonb NOT NULL CHECK (jsonb_typeof(payload_json) = 'object'),
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversation_events_sequence UNIQUE (conversation_id, event_sequence),
  CONSTRAINT uq_tutor_conversation_events_key UNIQUE (conversation_id, event_key),
  CONSTRAINT uq_tutor_conversation_events_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_conversation_event_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_conversation_event_turn_scope
    FOREIGN KEY (turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_conversation_event_item_shape CHECK (
    (item_id IS NULL AND item_kind IS NULL)
    OR (item_id IS NOT NULL AND item_kind IS NOT NULL)
  )
);

ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS tutor_conversation_events_kind_check;
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_events_kind;
ALTER TABLE tutor_conversation_events
  ADD CONSTRAINT chk_tutor_conversation_events_kind CHECK (kind IN (
    'turn_created', 'turn_updated', 'item_added', 'item_updated', 'turn_output',
    'control_updated', 'dispatch_delayed', 'dispatch_dead'
  ));
ALTER TABLE tutor_conversation_events
  ALTER COLUMN projection_version SET DEFAULT 'tutor_conversation_event_v2';
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS tutor_conversation_events_projection_version_check;
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_events_projection_version;
ALTER TABLE tutor_conversation_events
  ADD CONSTRAINT chk_tutor_conversation_events_projection_version CHECK (
    projection_version IN ('tutor_conversation_event_v1', 'tutor_conversation_event_v2')
  );

CREATE TABLE IF NOT EXISTS tutor_turn_public_thinking_streams (
  run_id uuid PRIMARY KEY REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  decision_iteration integer NOT NULL CHECK (decision_iteration >= 1),
  generation bigint NOT NULL CHECK (generation >= 1),
  provider_attempt integer NOT NULL CHECK (provider_attempt >= 1),
  state text NOT NULL CHECK (state IN ('active', 'complete', 'discarded', 'accepted')),
  thinking_text text NOT NULL DEFAULT '' CHECK (char_length(thinking_text) <= 1280),
  next_chunk_sequence bigint NOT NULL DEFAULT 1 CHECK (next_chunk_sequence >= 1),
  last_public_event_sequence bigint,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  discarded_at timestamptz,
  accepted_at timestamptz,
  CONSTRAINT uq_tutor_turn_public_thinking_streams_scope UNIQUE (run_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_turn_public_thinking_stream_run_scope
    FOREIGN KEY (run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_turn_public_thinking_stream_event
    FOREIGN KEY (conversation_id, last_public_event_sequence)
    REFERENCES tutor_conversation_events(conversation_id, event_sequence) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_turn_public_thinking_stream_timestamps CHECK (
    (state = 'active' AND completed_at IS NULL AND discarded_at IS NULL AND accepted_at IS NULL)
    OR (state = 'complete' AND completed_at IS NOT NULL AND discarded_at IS NULL AND accepted_at IS NULL)
    OR (state = 'discarded' AND discarded_at IS NOT NULL AND accepted_at IS NULL)
    OR (state = 'accepted' AND completed_at IS NOT NULL AND accepted_at IS NOT NULL AND discarded_at IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_interactive_dispatch_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL UNIQUE REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  state text NOT NULL DEFAULT 'pending' CHECK (state IN (
    'pending', 'leased', 'retry_wait', 'completed', 'dead'
  )),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  last_error_code text CHECK (
    last_error_code IS NULL OR char_length(last_error_code) BETWEEN 1 AND 120
  ),
  completed_at timestamptz,
  dead_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_interactive_dispatch_jobs_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_interactive_dispatch_job_run_scope
    FOREIGN KEY (run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_interactive_dispatch_job_lease CHECK (
    (state = 'leased' AND lease_owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)
    OR (state <> 'leased' AND lease_owner_id IS NULL AND lease_expires_at IS NULL)
  ),
  CONSTRAINT chk_tutor_interactive_dispatch_job_terminal CHECK (
    (state = 'completed' AND completed_at IS NOT NULL AND dead_at IS NULL)
    OR (state = 'dead' AND dead_at IS NOT NULL AND completed_at IS NULL)
    OR (state NOT IN ('completed', 'dead') AND completed_at IS NULL AND dead_at IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_conversation_events_replay
  ON tutor_conversation_events(conversation_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_tutor_conversation_events_turn
  ON tutor_conversation_events(turn_id, event_sequence) WHERE turn_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_public_thinking_streams_conversation_state
  ON tutor_turn_public_thinking_streams(conversation_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_interactive_dispatch_jobs_claim
  ON tutor_interactive_dispatch_jobs(available_at, created_at, id)
  WHERE state IN ('pending', 'retry_wait', 'leased');
CREATE INDEX IF NOT EXISTS idx_tutor_interactive_dispatch_jobs_user_state
  ON tutor_interactive_dispatch_jobs(user_id, state, updated_at);

CREATE OR REPLACE FUNCTION enforce_tutor_conversation_event_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('aearn.learning_track_purge_user_id', true) = OLD.user_id::text THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor conversation events are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_conversation_events_immutable ON tutor_conversation_events;
CREATE TRIGGER trg_tutor_conversation_events_immutable
BEFORE UPDATE OR DELETE ON tutor_conversation_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_conversation_event_append_only();

DROP TRIGGER IF EXISTS trg_tutor_public_thinking_streams_updated_at ON tutor_turn_public_thinking_streams;
CREATE TRIGGER trg_tutor_public_thinking_streams_updated_at
BEFORE UPDATE ON tutor_turn_public_thinking_streams
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_interactive_dispatch_jobs_updated_at ON tutor_interactive_dispatch_jobs;
CREATE TRIGGER trg_tutor_interactive_dispatch_jobs_updated_at
BEFORE UPDATE ON tutor_interactive_dispatch_jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Child 08-14 Tutor typed interaction requests and fresh authority turns.
CREATE TABLE IF NOT EXISTS tutor_interaction_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  source_turn_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN (
    'clarification', 'planning_input', 'approval', 'capability_result', 'external_result'
  )),
  actor text NOT NULL CHECK (actor IN ('learner', 'authority')),
  schema_version text NOT NULL DEFAULT 'tutor_interaction_request_v1'
    CHECK (schema_version = 'tutor_interaction_request_v1'),
  catalog_version text,
  question_key text,
  descriptor_json jsonb NOT NULL CHECK (jsonb_typeof(descriptor_json) = 'object'),
  presentation_json jsonb NOT NULL CHECK (jsonb_typeof(presentation_json) = 'object'),
  descriptor_hash text NOT NULL CHECK (descriptor_hash ~ '^[0-9a-f]{64}$'),
  proposal_identity text,
  authority_key text,
  risk_level text CHECK (risk_level IS NULL OR risk_level IN ('low', 'medium', 'high')),
  authority_issuer text,
  authority_subject text,
  authority_scope_json jsonb,
  authority_request_hash text CHECK (authority_request_hash IS NULL OR authority_request_hash ~ '^[0-9a-f]{64}$'),
  authority_result_hash text CHECK (authority_result_hash IS NULL OR authority_result_hash ~ '^[0-9a-f]{64}$'),
  authority_verification_result text CHECK (
    authority_verification_result IS NULL OR authority_verification_result IN ('verified', 'ambiguous', 'rejected')
  ),
  receipt_identity text,
  receipt_hash text CHECK (receipt_hash IS NULL OR receipt_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN (
    'pending', 'answered', 'denied', 'cancelled', 'expired'
  )),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  response_hash text CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
  answer_turn_id uuid,
  answer_message_id uuid,
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_interaction_requests_item UNIQUE (item_id),
  CONSTRAINT uq_tutor_interaction_requests_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT uq_tutor_interaction_requests_item_scope UNIQUE (item_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_interaction_request_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_interaction_request_source_turn_scope
    FOREIGN KEY (source_turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE CASCADE,
  CONSTRAINT fk_tutor_interaction_request_answer_turn_scope
    FOREIGN KEY (answer_turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE SET NULL (answer_turn_id),
  CONSTRAINT fk_tutor_interaction_request_answer_message_scope
    FOREIGN KEY (answer_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE SET NULL (answer_message_id),
  CONSTRAINT chk_tutor_interaction_request_actor_kind CHECK (
    (actor = 'learner' AND kind IN ('clarification', 'planning_input', 'approval'))
    OR (actor = 'authority' AND kind IN ('capability_result', 'external_result'))
  ),
  CONSTRAINT chk_tutor_interaction_request_planning_shape CHECK (
    (kind = 'planning_input' AND question_key IN (
      'language_id', 'goal_text', 'target_level', 'weekly_minutes',
      'experience_level', 'teaching_preferences', 'pace_constraints'
    ) AND catalog_version = 'tutor_planning_questions_v1')
    OR (kind <> 'planning_input' AND question_key IS NULL AND catalog_version IS NULL)
  ),
  CONSTRAINT chk_tutor_interaction_request_approval_shape CHECK (
    (kind = 'approval' AND proposal_identity IS NOT NULL AND authority_key IS NOT NULL AND risk_level IS NOT NULL)
    OR (kind <> 'approval' AND proposal_identity IS NULL AND risk_level IS NULL)
  ),
  CONSTRAINT chk_tutor_interaction_request_authority_shape CHECK (
    (actor = 'authority' AND authority_request_hash IS NOT NULL)
    OR (actor = 'learner' AND authority_issuer IS NULL AND authority_subject IS NULL
      AND authority_scope_json IS NULL AND authority_result_hash IS NULL
      AND authority_verification_result IS NULL AND receipt_identity IS NULL AND receipt_hash IS NULL)
  ),
  CONSTRAINT chk_tutor_interaction_request_resolution CHECK (
    (state = 'pending' AND response_hash IS NULL AND receipt_hash IS NULL
      AND answer_turn_id IS NULL AND answer_message_id IS NULL AND resolved_at IS NULL)
    OR (state <> 'pending' AND resolved_at IS NOT NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_interaction_requests_pending_conversation
  ON tutor_interaction_requests(conversation_id)
  WHERE state = 'pending';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_interaction_requests_receipt_identity
  ON tutor_interaction_requests(user_id, receipt_identity)
  WHERE receipt_identity IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_interaction_requests_conversation_history
  ON tutor_interaction_requests(conversation_id, created_at DESC, item_id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_interaction_requests_source_turn
  ON tutor_interaction_requests(source_turn_id);

ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS response_to_request_id uuid;
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS completion_reason text;
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_completion_reason;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_completion_reason CHECK (
    completion_reason IS NULL OR completion_reason IN (
      'awaiting_user', 'awaiting_approval', 'awaiting_authority'
    )
  );
ALTER TABLE tutor_interaction_requests
  DROP CONSTRAINT IF EXISTS fk_tutor_interaction_request_answer_turn_scope;
ALTER TABLE tutor_interaction_requests
  ADD CONSTRAINT fk_tutor_interaction_request_answer_turn_scope
  FOREIGN KEY (answer_turn_id, user_id, conversation_id)
  REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE SET NULL (answer_turn_id);
ALTER TABLE tutor_interaction_requests
  DROP CONSTRAINT IF EXISTS fk_tutor_interaction_request_answer_message_scope;
ALTER TABLE tutor_interaction_requests
  ADD CONSTRAINT fk_tutor_interaction_request_answer_message_scope
  FOREIGN KEY (answer_message_id, conversation_id)
  REFERENCES tutor_messages(id, conversation_id) ON DELETE SET NULL (answer_message_id);
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_runs_response_request_scope;
ALTER TABLE tutor_runs
  ADD CONSTRAINT fk_tutor_runs_response_request_scope
  FOREIGN KEY (response_to_request_id, user_id, conversation_id)
  REFERENCES tutor_interaction_requests(id, user_id, conversation_id)
  ON DELETE SET NULL (response_to_request_id);
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_request_lineage_shape;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_request_lineage_shape CHECK (
    (response_to_request_id IS NULL OR interaction_protocol_version = 'thread_turn_v2')
    AND (completion_reason IS NULL OR terminal_outcome = 'completed')
  );

DROP TRIGGER IF EXISTS trg_tutor_interaction_requests_updated_at ON tutor_interaction_requests;
CREATE TRIGGER trg_tutor_interaction_requests_updated_at
BEFORE UPDATE ON tutor_interaction_requests
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_interaction_requests_source_turn
  ON tutor_interaction_requests(source_turn_id);

-- Child 08-13 Tutor Queue, Steer, Interrupt, Resume, Execute, and Retry control.
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS queue_paused boolean NOT NULL DEFAULT false;
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS queue_pause_reason text;
ALTER TABLE tutor_conversations
  DROP CONSTRAINT IF EXISTS chk_tutor_conversations_queue_pause;
ALTER TABLE tutor_conversations
  ADD CONSTRAINT chk_tutor_conversations_queue_pause CHECK (
    (queue_paused = false AND queue_pause_reason IS NULL)
    OR (queue_paused = true AND queue_pause_reason IN ('pending_request', 'interrupted', 'failed'))
  );

CREATE TABLE IF NOT EXISTS tutor_queued_inputs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  content text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 16000),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'claimed', 'cancelled')),
  position integer NOT NULL CHECK (position >= 1),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  enqueue_key text NOT NULL CHECK (char_length(enqueue_key) BETWEEN 1 AND 160),
  claimed_turn_id uuid,
  claimed_input_revision integer CHECK (claimed_input_revision IS NULL OR claimed_input_revision >= 1),
  claimed_mode text CHECK (claimed_mode IS NULL OR claimed_mode IN ('drain', 'steer', 'execute')),
  claimed_at timestamptz,
  cancelled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_queued_inputs_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT uq_tutor_queued_inputs_enqueue UNIQUE (conversation_id, enqueue_key),
  CONSTRAINT fk_tutor_queued_input_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_queued_input_claimed_turn_scope
    FOREIGN KEY (claimed_turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_queued_input_resolution CHECK (
    (state = 'pending' AND claimed_turn_id IS NULL AND claimed_input_revision IS NULL
      AND claimed_mode IS NULL AND claimed_at IS NULL AND cancelled_at IS NULL)
    OR (state = 'claimed' AND claimed_turn_id IS NOT NULL AND claimed_input_revision IS NOT NULL
      AND claimed_mode IS NOT NULL AND claimed_at IS NOT NULL AND cancelled_at IS NULL)
    OR (state = 'cancelled' AND claimed_turn_id IS NULL AND claimed_input_revision IS NULL
      AND claimed_mode IS NULL AND claimed_at IS NULL AND cancelled_at IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_queued_inputs_pending_position
  ON tutor_queued_inputs(conversation_id, position) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS idx_tutor_queued_inputs_pending
  ON tutor_queued_inputs(conversation_id, position, created_at, id) WHERE state = 'pending';
DROP TRIGGER IF EXISTS trg_tutor_queued_inputs_updated_at ON tutor_queued_inputs;
CREATE TRIGGER trg_tutor_queued_inputs_updated_at
BEFORE UPDATE ON tutor_queued_inputs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE tutor_effects
  ADD COLUMN IF NOT EXISTS logical_action_key text;
ALTER TABLE tutor_effects
  DROP CONSTRAINT IF EXISTS chk_tutor_effects_logical_action_key;
ALTER TABLE tutor_effects
  ADD CONSTRAINT chk_tutor_effects_logical_action_key CHECK (
    logical_action_key IS NULL OR logical_action_key ~ '^[0-9a-f]{64}$'
  );
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_effects_committed_logical_action
  ON tutor_effects(logical_action_key)
  WHERE logical_action_key IS NOT NULL AND status = 'committed';
ALTER TABLE tutor_queued_inputs
  ADD COLUMN IF NOT EXISTS input_metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tutor_queued_inputs
  DROP CONSTRAINT IF EXISTS chk_tutor_queued_inputs_metadata;
ALTER TABLE tutor_queued_inputs
  ADD CONSTRAINT chk_tutor_queued_inputs_metadata CHECK (jsonb_typeof(input_metadata_json) = 'object');


-- Child 08-14 Tutor thread/turn v2 global protocol cutover authority.
CREATE TABLE IF NOT EXISTS tutor_thread_turn_cutovers (
  cutover_version text PRIMARY KEY CHECK (char_length(cutover_version) BETWEEN 1 AND 120),
  state text NOT NULL DEFAULT 'idle' CHECK (state IN ('idle','preparing','blocked','ready','enabled')),
  generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
  summary_hash text CHECK (summary_hash IS NULL OR summary_hash ~ '^[0-9a-f]{64}$'),
  counts_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts_json) = 'object'),
  block_code text CHECK (block_code IS NULL OR char_length(block_code) BETWEEN 1 AND 160),
  last_operation text CHECK (last_operation IS NULL OR last_operation IN ('prepare','enable','rollback')),
  last_idempotency_key text CHECK (last_idempotency_key IS NULL OR char_length(last_idempotency_key) BETWEEN 1 AND 160),
  last_request_hash text CHECK (last_request_hash IS NULL OR last_request_hash ~ '^[0-9a-f]{64}$'),
  prepared_at timestamptz,
  ready_at timestamptz,
  enabled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT chk_tutor_thread_turn_cutover_block CHECK ((state = 'blocked') = (block_code IS NOT NULL)),
  CONSTRAINT chk_tutor_thread_turn_cutover_ready_hash CHECK (state NOT IN ('ready','enabled') OR summary_hash IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS tutor_thread_turn_cutover_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cutover_version text NOT NULL REFERENCES tutor_thread_turn_cutovers(cutover_version) ON DELETE RESTRICT,
  generation bigint NOT NULL CHECK (generation >= 0),
  event_key text NOT NULL CHECK (char_length(event_key) BETWEEN 1 AND 160),
  kind text NOT NULL CHECK (kind IN ('preparing','preflight','enabled','rollback')),
  state text NOT NULL CHECK (state IN ('preparing','blocked','ready','enabled')),
  counts_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts_json) = 'object'),
  block_code text CHECK (block_code IS NULL OR char_length(block_code) BETWEEN 1 AND 160),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cutover_version, event_key)
);

INSERT INTO tutor_thread_turn_cutovers (cutover_version)
VALUES ('tutor_thread_turn_v2_global_v1')
ON CONFLICT (cutover_version) DO NOTHING;

DROP TRIGGER IF EXISTS trg_tutor_thread_turn_cutovers_updated_at ON tutor_thread_turn_cutovers;
CREATE TRIGGER trg_tutor_thread_turn_cutovers_updated_at
BEFORE UPDATE ON tutor_thread_turn_cutovers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_thread_turn_cutover_event_append_only()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Tutor thread/turn cutover events are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_thread_turn_cutover_events_immutable ON tutor_thread_turn_cutover_events;
CREATE TRIGGER trg_tutor_thread_turn_cutover_events_immutable
BEFORE UPDATE OR DELETE ON tutor_thread_turn_cutover_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_thread_turn_cutover_event_append_only();


-- Child 08-17 Codex runtime durable correlation and safe public projection.
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS runtime_kind text NOT NULL DEFAULT 'harness_v1';
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_runtime_kind;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_runtime_kind
  CHECK (runtime_kind IN ('harness_v1', 'codex_sidecar_v1'));

CREATE OR REPLACE FUNCTION enforce_tutor_run_runtime_kind_immutable()
RETURNS trigger AS $$
BEGIN
  IF NEW.runtime_kind IS DISTINCT FROM OLD.runtime_kind THEN
    RAISE EXCEPTION 'Tutor run runtime kind is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runs_runtime_kind_immutable ON tutor_runs;
CREATE TRIGGER trg_tutor_runs_runtime_kind_immutable
BEFORE UPDATE ON tutor_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_runtime_kind_immutable();

CREATE TABLE IF NOT EXISTS tutor_codex_runtime_health (
  worker_id text PRIMARY KEY CHECK (char_length(worker_id) BETWEEN 1 AND 160),
  status text NOT NULL CHECK (status IN ('stopped', 'starting', 'ready', 'unavailable', 'failed')),
  generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
  runtime_version text CHECK (runtime_version IS NULL OR char_length(runtime_version) BETWEEN 1 AND 120),
  model text CHECK (model IS NULL OR char_length(model) BETWEEN 1 AND 120),
  model_provider text CHECK (model_provider IS NULL OR char_length(model_provider) BETWEEN 1 AND 120),
  protocol text CHECK (protocol IS NULL OR char_length(protocol) BETWEEN 1 AND 40),
  safe_error_code text CHECK (
    safe_error_code IS NULL OR safe_error_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$'
  ),
  observed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tutor_codex_runtime_health_observed
  ON tutor_codex_runtime_health(observed_at DESC, updated_at DESC);
DROP TRIGGER IF EXISTS trg_tutor_codex_runtime_health_updated_at ON tutor_codex_runtime_health;
CREATE TRIGGER trg_tutor_codex_runtime_health_updated_at
BEFORE UPDATE ON tutor_codex_runtime_health
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS tutor_conversation_runtime_threads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  runtime_kind text NOT NULL CHECK (runtime_kind = 'codex_sidecar_v1'),
  runtime_version text NOT NULL CHECK (char_length(runtime_version) BETWEEN 1 AND 120),
  protocol_version text NOT NULL CHECK (char_length(protocol_version) BETWEEN 1 AND 120),
  model text NOT NULL CHECK (model = 'deepseek-v4-flash'),
  model_provider text NOT NULL CHECK (model_provider = 'aearn_deepseek'),
  external_thread_id text NOT NULL UNIQUE CHECK (char_length(external_thread_id) BETWEEN 1 AND 240),
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'unavailable', 'retired')),
  migration_mode text NOT NULL DEFAULT 'native' CHECK (migration_mode IN ('native', 'adopted_legacy', 'legacy_reseed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  last_resumed_at timestamptz,
  last_compacted_at timestamptz,
  CONSTRAINT uq_tutor_conversation_runtime_threads_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_conversation_runtime_thread_conversation_scope
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_conversation_runtime_threads_active
  ON tutor_conversation_runtime_threads(user_id, conversation_id, runtime_kind)
  WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_conversation_runtime_threads_owner
  ON tutor_conversation_runtime_threads(user_id, conversation_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS tutor_run_runtime_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL UNIQUE REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  conversation_runtime_thread_id uuid,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  runtime_kind text NOT NULL CHECK (runtime_kind = 'codex_sidecar_v1'),
  runtime_version text NOT NULL CHECK (char_length(runtime_version) BETWEEN 1 AND 120),
  protocol_version text NOT NULL CHECK (char_length(protocol_version) BETWEEN 1 AND 120),
  external_thread_id text NOT NULL CHECK (char_length(external_thread_id) BETWEEN 1 AND 240),
  external_turn_id text CHECK (external_turn_id IS NULL OR char_length(external_turn_id) BETWEEN 1 AND 240),
  connection_generation bigint NOT NULL CHECK (connection_generation >= 1),
  state text NOT NULL CHECK (state IN (
    'thread_bound', 'running', 'completed', 'interrupted', 'unavailable', 'failed'
  )),
  final_message_id uuid,
  final_message_blocked boolean NOT NULL DEFAULT false,
  safe_error_code text CHECK (safe_error_code IS NULL OR safe_error_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$'),
  started_at timestamptz,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_runtime_bindings_scope UNIQUE (id, run_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_runtime_binding_run_scope
    FOREIGN KEY (run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_runtime_binding_message_scope
    FOREIGN KEY (final_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_runtime_binding_terminal CHECK (
    (state IN ('thread_bound', 'running') AND terminal_at IS NULL)
    OR (state IN ('completed', 'interrupted', 'unavailable', 'failed') AND terminal_at IS NOT NULL)
  )
);
ALTER TABLE tutor_run_runtime_bindings
  ADD COLUMN IF NOT EXISTS conversation_runtime_thread_id uuid;
ALTER TABLE tutor_run_runtime_bindings
  DROP CONSTRAINT IF EXISTS uq_tutor_runtime_bindings_thread;
-- Existing installations may already have immutable/update-timestamp triggers from
-- a prior bootstrap. Disable them while the additive conversation-thread backfill runs;
-- both triggers are recreated below after all migration updates are complete.
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_lifecycle ON tutor_run_runtime_bindings;
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_updated_at ON tutor_run_runtime_bindings;

INSERT INTO tutor_conversation_runtime_threads (
  user_id, conversation_id, runtime_kind, runtime_version, protocol_version,
  model, model_provider, external_thread_id, state, migration_mode,
  created_at, updated_at, last_resumed_at
)
SELECT legacy.user_id, legacy.conversation_id, 'codex_sidecar_v1',
       min(legacy.runtime_version), min(legacy.protocol_version),
       'deepseek-v4-flash', 'aearn_deepseek', min(legacy.external_thread_id),
       'active', 'adopted_legacy', min(legacy.created_at), max(legacy.updated_at), max(legacy.updated_at)
FROM tutor_run_runtime_bindings AS legacy
WHERE NOT EXISTS (
  SELECT 1 FROM tutor_conversation_runtime_threads AS existing
  WHERE existing.user_id = legacy.user_id
    AND existing.conversation_id = legacy.conversation_id
    AND existing.runtime_kind = 'codex_sidecar_v1'
)
GROUP BY legacy.user_id, legacy.conversation_id
HAVING count(DISTINCT legacy.external_thread_id) = 1
ON CONFLICT DO NOTHING;

UPDATE tutor_run_runtime_bindings AS bindings
SET conversation_runtime_thread_id = threads.id
FROM tutor_conversation_runtime_threads AS threads
WHERE bindings.conversation_runtime_thread_id IS NULL
  AND threads.user_id = bindings.user_id
  AND threads.conversation_id = bindings.conversation_id
  AND threads.runtime_kind = bindings.runtime_kind
  AND threads.external_thread_id = bindings.external_thread_id;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_tutor_runtime_binding_conversation_thread_scope'
  ) THEN
    ALTER TABLE tutor_run_runtime_bindings
      ADD CONSTRAINT fk_tutor_runtime_binding_conversation_thread_scope
      FOREIGN KEY (conversation_runtime_thread_id, user_id, conversation_id)
      REFERENCES tutor_conversation_runtime_threads(id, user_id, conversation_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
END;
$$;
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_bindings_conversation_thread
  ON tutor_run_runtime_bindings(conversation_runtime_thread_id, created_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runtime_bindings_turn
  ON tutor_run_runtime_bindings(runtime_kind, external_turn_id)
  WHERE external_turn_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_bindings_run_state
  ON tutor_run_runtime_bindings(user_id, run_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS tutor_runtime_text_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id uuid NOT NULL REFERENCES tutor_run_runtime_bindings(id) ON DELETE RESTRICT,
  conversation_runtime_thread_id uuid NOT NULL REFERENCES tutor_conversation_runtime_threads(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  external_item_hash text NOT NULL CHECK (external_item_hash ~ '^[0-9a-f]{64}$'),
  channel text NOT NULL CHECK (channel IN ('reasoning', 'final_answer')),
  state text NOT NULL CHECK (state IN ('streaming', 'completed', 'discarded', 'blocked')),
  text text NOT NULL DEFAULT '' CHECK (char_length(text) <= 1000000),
  last_event_sequence integer NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
  content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
  connection_generation bigint NOT NULL CHECK (connection_generation >= 1),
  public_message_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CONSTRAINT uq_tutor_runtime_text_items_identity UNIQUE (binding_id, external_item_hash, channel),
  CONSTRAINT uq_tutor_runtime_text_items_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_runtime_text_item_binding_scope
    FOREIGN KEY (binding_id, run_id, user_id, conversation_id)
    REFERENCES tutor_run_runtime_bindings(id, run_id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_runtime_text_item_conversation_thread_scope
    FOREIGN KEY (conversation_runtime_thread_id, user_id, conversation_id)
    REFERENCES tutor_conversation_runtime_threads(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_runtime_text_item_message_scope
    FOREIGN KEY (public_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_runtime_text_item_terminal CHECK (
    (state = 'streaming' AND completed_at IS NULL)
    OR (state IN ('completed', 'discarded', 'blocked') AND completed_at IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_text_items_active
  ON tutor_runtime_text_items(user_id, conversation_id, run_id, channel, state, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_text_items_message
  ON tutor_runtime_text_items(user_id, public_message_id, channel, created_at, id)
  WHERE public_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tutor_runtime_item_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id uuid NOT NULL REFERENCES tutor_run_runtime_bindings(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  event_key text NOT NULL CHECK (event_key ~ '^[0-9a-f]{64}$'),
  event_kind text NOT NULL CHECK (event_kind IN (
    'turn_started', 'message_delta', 'message_completed', 'tool_started',
    'tool_completed', 'turn_completed', 'warning'
  )),
  external_item_hash text CHECK (external_item_hash IS NULL OR external_item_hash ~ '^[0-9a-f]{64}$'),
  event_sequence integer NOT NULL CHECK (event_sequence >= 1),
  projection_sequence integer NOT NULL CHECK (projection_sequence >= 1),
  source_sequence_start bigint,
  source_sequence_end bigint,
  source_delta_count integer,
  source_content_hash text CHECK (source_content_hash IS NULL OR source_content_hash ~ '^[0-9a-f]{64}$'),
  item_kind text CHECK (item_kind IS NULL OR item_kind IN ('turn', 'message', 'tool', 'warning')),
  item_status text CHECK (item_status IS NULL OR char_length(item_status) BETWEEN 1 AND 80),
  tool_name text CHECK (tool_name IS NULL OR tool_name ~ '^[A-Za-z0-9_-]{1,64}$'),
  input_hash text CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
  result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
  content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
  safe_code text CHECK (safe_code IS NULL OR safe_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$'),
  projection_status text NOT NULL CHECK (projection_status IN (
    'applied', 'ignored_nonpublic', 'ignored_stale', 'blocked_unsafe'
  )),
  public_item_id uuid,
  public_item_kind text CHECK (public_item_kind IS NULL OR public_item_kind IN ('message', 'process', 'error', 'runtime_output')),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_runtime_item_receipts_event UNIQUE (binding_id, event_key),
  CONSTRAINT uq_tutor_runtime_item_receipts_sequence UNIQUE (binding_id, event_sequence),
  CONSTRAINT chk_tutor_runtime_receipt_projection_sequence
    CHECK (event_sequence = projection_sequence),
  CONSTRAINT chk_tutor_runtime_receipt_source_range CHECK (
    (
      source_sequence_start IS NULL
      AND source_sequence_end IS NULL
      AND source_delta_count IS NULL
      AND source_content_hash IS NULL
    )
    OR (
      source_sequence_start IS NOT NULL
      AND source_sequence_end IS NOT NULL
      AND source_delta_count IS NOT NULL
      AND source_content_hash IS NOT NULL
      AND source_sequence_start >= 1
      AND source_sequence_end >= source_sequence_start
      AND source_delta_count >= 1
      AND source_delta_count = source_sequence_end - source_sequence_start + 1
      AND source_content_hash ~ '^[0-9a-f]{64}$'
    )
  ),
  CONSTRAINT fk_tutor_runtime_receipt_binding_scope
    FOREIGN KEY (binding_id, run_id, user_id, conversation_id)
    REFERENCES tutor_run_runtime_bindings(id, run_id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_runtime_receipt_public_item CHECK (
    (public_item_id IS NULL AND public_item_kind IS NULL)
    OR (public_item_id IS NOT NULL AND public_item_kind IS NOT NULL)
  )
);
DROP TRIGGER IF EXISTS trg_tutor_runtime_receipts_immutable
  ON tutor_runtime_item_receipts;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS projection_sequence integer;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_sequence_start bigint;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_sequence_end bigint;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_delta_count integer;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_content_hash text;
UPDATE tutor_runtime_item_receipts
SET projection_sequence = event_sequence
WHERE projection_sequence IS NULL;
ALTER TABLE tutor_runtime_item_receipts
  ALTER COLUMN projection_sequence SET NOT NULL;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_receipt_projection_sequence;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_receipt_projection_sequence
  CHECK (event_sequence = projection_sequence);
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_receipt_source_range;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_receipt_source_range CHECK (
    (
      source_sequence_start IS NULL
      AND source_sequence_end IS NULL
      AND source_delta_count IS NULL
      AND source_content_hash IS NULL
    )
    OR (
      source_sequence_start IS NOT NULL
      AND source_sequence_end IS NOT NULL
      AND source_delta_count IS NOT NULL
      AND source_content_hash IS NOT NULL
      AND source_sequence_start >= 1
      AND source_sequence_end >= source_sequence_start
      AND source_delta_count >= 1
      AND source_delta_count = source_sequence_end - source_sequence_start + 1
      AND source_content_hash ~ '^[0-9a-f]{64}$'
    )
  );
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runtime_item_receipts_projection_sequence
  ON tutor_runtime_item_receipts(binding_id, projection_sequence);
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS tutor_runtime_item_receipts_event_kind_check;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_item_receipts_event_kind;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_item_receipts_event_kind CHECK (event_kind IN (
    'turn_started',
    'reasoning_started', 'reasoning_delta', 'reasoning_completed',
    'reasoning_summary_started', 'reasoning_summary_delta', 'reasoning_summary_completed',
    'message_started', 'message_delta', 'message_completed',
    'context_compaction_started', 'context_compaction_completed',
    'tool_started', 'tool_completed', 'turn_completed', 'warning'
  ));
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS tutor_runtime_item_receipts_public_item_kind_check;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_item_receipts_public_item_kind;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_item_receipts_public_item_kind CHECK (
    public_item_kind IS NULL OR public_item_kind IN ('message', 'process', 'error', 'runtime_output')
  );
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS tutor_runtime_item_receipts_item_kind_check;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_item_receipts_item_kind;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_item_receipts_item_kind CHECK (
    item_kind IS NULL OR item_kind IN ('turn', 'reasoning', 'reasoning_summary', 'message', 'context_compaction', 'tool', 'warning')
  );
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_receipts_run_sequence
  ON tutor_runtime_item_receipts(user_id, run_id, projection_sequence, created_at);

CREATE TABLE IF NOT EXISTS tutor_runtime_public_errors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id uuid NOT NULL UNIQUE REFERENCES tutor_run_runtime_bindings(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  code text NOT NULL CHECK (code ~ '^[A-Z][A-Z0-9_]{0,119}$'),
  recoverable boolean NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT fk_tutor_runtime_error_binding_scope
    FOREIGN KEY (binding_id, run_id, user_id, conversation_id)
    REFERENCES tutor_run_runtime_bindings(id, run_id, user_id, conversation_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_errors_conversation
  ON tutor_runtime_public_errors(user_id, conversation_id, created_at DESC);

CREATE OR REPLACE FUNCTION enforce_tutor_conversation_runtime_thread_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor conversation runtime threads are retained private state' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
     OR NEW.runtime_kind IS DISTINCT FROM OLD.runtime_kind
     OR NEW.runtime_version IS DISTINCT FROM OLD.runtime_version
     OR NEW.protocol_version IS DISTINCT FROM OLD.protocol_version
     OR NEW.model IS DISTINCT FROM OLD.model
     OR NEW.model_provider IS DISTINCT FROM OLD.model_provider
     OR NEW.external_thread_id IS DISTINCT FROM OLD.external_thread_id
     OR NEW.migration_mode IS DISTINCT FROM OLD.migration_mode THEN
    RAISE EXCEPTION 'Tutor conversation runtime thread identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'retired' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Retired Tutor conversation runtime thread is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_conversation_runtime_threads_lifecycle ON tutor_conversation_runtime_threads;
CREATE TRIGGER trg_tutor_conversation_runtime_threads_lifecycle
BEFORE UPDATE OR DELETE ON tutor_conversation_runtime_threads
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_conversation_runtime_thread_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_conversation_runtime_threads_updated_at ON tutor_conversation_runtime_threads;
CREATE TRIGGER trg_tutor_conversation_runtime_threads_updated_at
BEFORE UPDATE ON tutor_conversation_runtime_threads
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_runtime_text_item_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor runtime text items are private retained state' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.binding_id IS DISTINCT FROM OLD.binding_id
     OR NEW.conversation_runtime_thread_id IS DISTINCT FROM OLD.conversation_runtime_thread_id
     OR NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
     OR NEW.external_item_hash IS DISTINCT FROM OLD.external_item_hash
     OR NEW.channel IS DISTINCT FROM OLD.channel
     OR NEW.connection_generation IS DISTINCT FROM OLD.connection_generation
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Tutor runtime text item identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'completed'
     AND OLD.public_message_id IS NULL
     AND NEW.public_message_id IS NOT NULL
     AND NEW.state IS NOT DISTINCT FROM OLD.state
     AND NEW.text IS NOT DISTINCT FROM OLD.text
     AND NEW.last_event_sequence IS NOT DISTINCT FROM OLD.last_event_sequence
     AND NEW.content_hash IS NOT DISTINCT FROM OLD.content_hash
     AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at THEN
    RETURN NEW;
  END IF;
  IF OLD.state IN ('completed', 'discarded', 'blocked') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal Tutor runtime text item is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runtime_text_items_lifecycle ON tutor_runtime_text_items;
CREATE TRIGGER trg_tutor_runtime_text_items_lifecycle
BEFORE UPDATE OR DELETE ON tutor_runtime_text_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_text_item_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_runtime_text_items_updated_at ON tutor_runtime_text_items;
CREATE TRIGGER trg_tutor_runtime_text_items_updated_at
BEFORE UPDATE ON tutor_runtime_text_items
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_runtime_binding_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor runtime bindings are retained audit state' USING ERRCODE = '23514';
  END IF;
  IF NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.conversation_runtime_thread_id IS DISTINCT FROM OLD.conversation_runtime_thread_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
     OR NEW.runtime_kind IS DISTINCT FROM OLD.runtime_kind
     OR NEW.runtime_version IS DISTINCT FROM OLD.runtime_version
     OR NEW.protocol_version IS DISTINCT FROM OLD.protocol_version
     OR NEW.external_thread_id IS DISTINCT FROM OLD.external_thread_id
     OR NEW.connection_generation IS DISTINCT FROM OLD.connection_generation THEN
    RAISE EXCEPTION 'Tutor runtime binding identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('completed', 'interrupted', 'unavailable', 'failed') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Tutor runtime terminal binding is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_lifecycle ON tutor_run_runtime_bindings;
CREATE TRIGGER trg_tutor_runtime_bindings_lifecycle
BEFORE UPDATE OR DELETE ON tutor_run_runtime_bindings
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_binding_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_updated_at ON tutor_run_runtime_bindings;
CREATE TRIGGER trg_tutor_runtime_bindings_updated_at
BEFORE UPDATE ON tutor_run_runtime_bindings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_runtime_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Tutor runtime receipts and public errors are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runtime_receipts_immutable ON tutor_runtime_item_receipts;
CREATE TRIGGER trg_tutor_runtime_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_runtime_item_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_append_only();
DROP TRIGGER IF EXISTS trg_tutor_runtime_errors_immutable ON tutor_runtime_public_errors;
CREATE TRIGGER trg_tutor_runtime_errors_immutable
BEFORE UPDATE OR DELETE ON tutor_runtime_public_errors
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_append_only();

ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS tutor_run_public_processes_current_step_key_check;
ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_current_step_key;
ALTER TABLE tutor_run_public_processes
  ADD CONSTRAINT chk_tutor_public_process_current_step_key CHECK (current_step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'runtime_started', 'domain_tool_running', 'domain_tool_completed',
    'learning_reply_generated', 'replaced_by_newer_input'
  ));
ALTER TABLE tutor_run_public_process_steps
  DROP CONSTRAINT IF EXISTS tutor_run_public_process_steps_step_key_check;
ALTER TABLE tutor_run_public_process_steps
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_step_key;
ALTER TABLE tutor_run_public_process_steps
  ADD CONSTRAINT chk_tutor_public_process_step_key CHECK (step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'runtime_started', 'domain_tool_running', 'domain_tool_completed',
    'learning_reply_generated', 'replaced_by_newer_input'
  ));
