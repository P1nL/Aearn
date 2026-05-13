export type ApiHealth = {
  status: "ok";
  service: string;
};

export type RuntimeTier = "browser_preview" | "python_stdout_test" | "compiled_sandbox_later";
export type LearningMode = "goal_based" | "material_based";
export type Language = "javascript" | "python" | "java" | "cpp" | "html_css";

export type RuntimeProfile = {
  id: string;
  slug: string;
  runtime_tier: RuntimeTier;
  language: Language;
  runner: "browser" | "python" | "sandbox";
  supports_realtime_preview: boolean;
  supports_stdout: boolean;
  supports_tests: boolean;
  compile_required: boolean;
  timeout_ms: number;
  memory_limit_mb: number;
  sandbox_policy: Record<string, unknown>;
};

export type LanguageCourse = {
  id: string;
  slug: string;
  language: Language;
  title: string;
  description: string | null;
  level: "beginner" | "intermediate" | "advanced";
  runtime_profile_id: string;
  runtime_profile: RuntimeProfile;
  supported_exercise_types_json: string[];
};

export type UserProfile = {
  id: string;
  display_name: string;
  learning_style: string | null;
  teaching_preference: string | null;
  encouragement_preference: string | null;
  profession: string | null;
  background_context: string | null;
  preferred_time_slots: Record<string, unknown>[];
  reminder_preference: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DraftKnowledgePoint = {
  temp_id: string;
  title: string;
  description: string | null;
  skill_tags: string[];
  source: "template" | "user_material" | "agent_generated";
  exercise_refs: string[];
};

export type DraftModule = {
  temp_id: string;
  title: string;
  description: string | null;
  order_index: number;
  is_skippable: boolean;
  is_adjustable: boolean;
  estimated_sessions: number;
  source: "template" | "user_material" | "agent_generated";
  knowledge_points: DraftKnowledgePoint[];
};

export type PlanDraft = {
  draft_id: string;
  user_id: string;
  language_course_id: string;
  goal_text: string;
  language: Language;
  target_level: string;
  mode: LearningMode;
  deadline: string | null;
  modules: DraftModule[];
  runtime_boundary: {
    runtime_tier: RuntimeTier;
    unsupported_languages: Language[];
    notice: string;
  };
  source_attribution: string[];
};

export type CreatedModule = {
  id: string;
  plan_id: string;
  title: string;
  description: string | null;
  order_index: number;
  status: "pending" | "in_progress" | "completed" | "skipped";
  is_skippable: boolean;
  is_adjustable: boolean;
  estimated_sessions: number;
};

export type CreatedKnowledgePoint = {
  id: string;
  module_id: string;
  language_course_id: string;
  title: string;
  description: string | null;
  order_index: number;
  skill_tags_json: string[];
  status: "pending" | "learning" | "reviewing" | "mastered";
  mastery_score: number;
};

export type CreatedPlanResponse = {
  LearningPlan: {
    id: string;
    user_id: string;
    language_course_id: string;
    goal_text: string;
    language: Language;
    target_level: string;
    mode: LearningMode;
    deadline: string | null;
    status: "active" | "paused" | "completed" | "archived";
    overall_progress: number;
    current_module_id: string | null;
  };
  modules: CreatedModule[];
  knowledge_points: CreatedKnowledgePoint[];
  next_entry_point: {
    type: "learning_session";
    plan_id: string;
    knowledge_point_id: string | null;
  };
  idempotency_replayed?: boolean;
};

export type ApiError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
  request_id: string;
  recoverable: boolean;
};

export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(`${apiError.code}: ${apiError.message}`);
    this.apiError = apiError;
  }
}
