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

CREATE TABLE IF NOT EXISTS runtime_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  runtime_tier text NOT NULL CHECK (runtime_tier IN ('browser_preview', 'python_stdout_test', 'compiled_sandbox_later')),
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'java', 'cpp', 'html_css')),
  runner text NOT NULL CHECK (runner IN ('browser', 'python', 'sandbox')),
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
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'java', 'cpp', 'html_css')),
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
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'java', 'cpp', 'html_css')),
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
  exercise_type text NOT NULL CHECK (exercise_type IN ('code_blank', 'fix_bug', 'implement_function', 'explain_code')),
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
  runtime_status text NOT NULL CHECK (runtime_status IN ('success', 'runtime_error', 'timeout', 'unsupported')),
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

CREATE TABLE IF NOT EXISTS idempotency_records (
  key text PRIMARY KEY,
  operation text NOT NULL,
  request_hash text NOT NULL,
  response_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);
CREATE INDEX IF NOT EXISTS idx_runtime_profiles_language ON runtime_profiles(language);
CREATE INDEX IF NOT EXISTS idx_language_courses_language_level ON language_courses(language, level);
CREATE INDEX IF NOT EXISTS idx_learning_plans_user_status ON learning_plans(user_id, status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_plan_modules_plan_status ON plan_modules(plan_id, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_points_module_status ON knowledge_points(module_id, status);
CREATE INDEX IF NOT EXISTS idx_exercises_knowledge_point ON exercises(knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_plan ON learning_sessions(user_id, plan_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user_exercise_created ON attempts(user_id, exercise_id, created_at);
CREATE INDEX IF NOT EXISTS idx_review_states_user_due ON review_states(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_idempotency_records_operation ON idempotency_records(operation);

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

DROP TRIGGER IF EXISTS trg_learning_sessions_updated_at ON learning_sessions;
CREATE TRIGGER trg_learning_sessions_updated_at BEFORE UPDATE ON learning_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_review_states_updated_at ON review_states;
CREATE TRIGGER trg_review_states_updated_at BEFORE UPDATE ON review_states
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
