export type ApiHealth = {
  status: "ok";
  service: string;
};

export type RuntimeTier = "browser_preview" | "python_stdout_test" | "compiled_sandbox_later";
export type LearningMode = "goal_based" | "material_based";
export type Language = "javascript" | "python" | "java" | "cpp" | "html_css";
export type RuntimeStatus = "success" | "runtime_error" | "timeout" | "unsupported";
export type NextAction = "retry_same" | "show_hint" | "explain_error" | "review_variant" | "schedule_review" | "advance_next";
export type FsrsRating = "Again" | "Hard" | "Good" | "Easy";
export type HintLevel = "nudge" | "concept" | "code_shape";
export type ExplanationFocus = "core_logic" | "boundary_condition" | "ai_generated_change";

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

export type CodeBlank = {
  id: string;
  blank_key: string;
  placeholder: string;
  expected_concept: string;
  acceptable_patterns_json: Record<string, unknown>[];
  is_core: boolean;
  order_index: number;
};

export type ExerciseTestCase = {
  id: string;
  case_type: "visible" | "hidden" | "preview_assertion";
  input_json: Record<string, unknown>;
  expected_output_json: Record<string, unknown>;
  assertion_code: string | null;
  weight: number;
  is_critical: boolean;
  timeout_ms: number;
  order_index: number;
};

export type LearningExercise = {
  id: string;
  knowledge_point_id: string;
  runtime_profile_id: string;
  title: string;
  exercise_type: "code_blank" | "fix_bug" | "implement_function" | "explain_code";
  prompt_markdown: string;
  starter_code: string;
  solution_reference: string | null;
  visible_test_policy: "visible_only" | "visible_and_hidden_summary" | "hidden_only";
  difficulty: number;
  estimated_minutes: number;
  requires_explanation: boolean;
  metadata_json: Record<string, unknown>;
  runtime_profile: RuntimeProfile;
  code_blanks: CodeBlank[];
  test_cases: ExerciseTestCase[];
};

export type LearningSessionResponse = {
  session_id: string;
  session_type: "learn";
  context_snapshot: {
    current_stage: string;
    LearningPlan: {
      id: string;
      current_module_id: string | null;
    };
    KnowledgePoint: {
      id: string;
      title: string;
      status: CreatedKnowledgePoint["status"];
    };
    RuntimeProfile: RuntimeProfile;
  };
  exercise: LearningExercise;
  initial_agent_message: string;
  session_state: "learning";
};

export type TestResult = {
  case_id: string;
  case_type: "visible" | "hidden" | "preview_assertion";
  passed: boolean;
  weight: number;
  is_critical: boolean;
  duration_ms: number;
  message: string;
};

export type RunExerciseResponse = {
  attempt_id: string;
  attempt_type: "run";
  runtime_status: RuntimeStatus;
  preview_html: string | null;
  stdout: string;
  stderr: string;
  test_pass_rate: number;
  passed_test_count: number;
  total_test_count: number;
  test_results: TestResult[];
  error_message: string | null;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type CodeCompletionResult = {
  result: "failed" | "partial" | "passed" | "easy";
  score: number;
  score_breakdown: {
    completion_correctness: number;
    runtime_and_tests: number;
    error_diagnosis: number;
    explanation_check: number;
  };
  hard_gates: {
    runtime_gate: boolean;
    test_gate: boolean;
    core_blank_gate: boolean;
    explanation_gate: boolean;
  };
  test_pass_rate: number;
  hint_usage_count: number;
  error_count: number;
  weak_points: string[];
  error_cause: string | null;
  feedback: string;
  next_action: NextAction;
  fsrs_rating: FsrsRating;
};

export type ReviewStateSummary = {
  knowledge_point_id: string;
  card_state: "new" | "learning" | "review" | "relearning";
  stability: number;
  difficulty: number;
  due_at: string | null;
  last_review_at: string | null;
  last_attempt_id: string | null;
  last_fsrs_rating: FsrsRating | null;
  scheduled_days: number;
  review_count: number;
  lapse_count: number;
  reps: number;
  lapses: number;
  scheduler_version?: string | null;
};

export type SubmitExerciseResponse = {
  attempt_id: string;
  code_completion_result: CodeCompletionResult;
  KnowledgePoint: {
    id: string;
    status: CreatedKnowledgePoint["status"];
    mastery_score: number;
    last_exercise_result: "failed" | "partial" | "passed" | "easy" | null;
    last_exercise_score: number | null;
  };
  ReviewState: ReviewStateSummary;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type HintResponse = {
  hint: {
    hint_level: HintLevel;
    content: string;
  };
  hint_usage_count: number;
  affected_score: {
    max_result: "passed" | "easy";
    score_penalty_hint: number;
  };
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type ExplainErrorResponse = {
  error_cause: string;
  explanation: string;
  fix_suggestion: string;
  related_knowledge_points: Array<{
    id: string;
    title: string;
  }>;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type ExplanationCheckResponse = {
  result: "passed" | "partial" | "failed";
  score: number;
  score_breakdown: {
    explanation_check: number;
  };
  follow_up_required: boolean;
  feedback: string;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type ReviewDueItem = {
  ReviewState: ReviewStateSummary;
  KnowledgePoint: {
    id: string;
    title: string;
    status: CreatedKnowledgePoint["status"];
    mastery_score: number;
    weak_points_json: string[];
  };
  forget_risk: "low" | "normal" | "high";
};

export type TodayReviewsResponse = {
  items: ReviewDueItem[];
  page_info: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
  timezone: "Asia/Shanghai";
  generated_at: string;
};

export type ReviewSessionResponse = {
  session_id: string;
  session_type: "review";
  knowledge_point: {
    id: string;
    title: string;
    status: CreatedKnowledgePoint["status"];
    weak_points_json: string[];
  };
  review_exercise: LearningExercise;
  ReviewState: ReviewStateSummary;
  variant_reason: string;
  initial_agent_message: string;
};

export type ReviewExerciseResultResponse = {
  attempt_id: string;
  result: CodeCompletionResult["result"];
  score: number;
  score_breakdown: CodeCompletionResult["score_breakdown"];
  fsrs_rating: FsrsRating;
  weak_points: string[];
  feedback: string;
  due_at: string | null;
  forget_risk: "low" | "normal" | "high";
  ReviewState: ReviewStateSummary;
  KnowledgePoint: SubmitExerciseResponse["KnowledgePoint"];
  code_completion_result: CodeCompletionResult;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(`${apiError.code}: ${apiError.message}`);
    this.apiError = apiError;
  }
}
