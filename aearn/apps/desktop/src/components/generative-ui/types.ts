import type { Language, RuntimeTier, NextAction, FsrsRating, ForgetRisk } from "../../types";
import type { LearningExercise, LearningHistoryResponse } from "../../types";

export type ToolUIProps<T> = {
  args: T;
  status: "pending" | "running" | "done" | "error";
  onAction?: (action: string, payload?: unknown) => void;
};

export type LearningRouteArgs = {
  plan_id: string;
  goal_text: string;
  language: Language;
  time_budget: {
    minutes_per_day: number;
    days_per_week: number;
  } | null;
  source_attribution: string[];
  modules: Array<{
    id: string;
    title: string;
    order_index: number;
    status: "pending" | "in_progress" | "completed" | "skipped";
    estimated_sessions: number;
    knowledge_points: Array<{
      id: string;
      title: string;
      status: "pending" | "learning" | "reviewing" | "mastered";
      mastery_score: number;
    }>;
  }>;
};

export type ExerciseCardArgs = {
  exercise_id: string;
  session_id: string;
  title: string;
  exercise_type: "code_blank" | "fix_bug" | "implement_function" | "explain_code" | "review_ai_patch";
  prompt_markdown: string;
  starter_code: string;
  language: Language;
  runtime_tier: RuntimeTier;
  blanks: Array<{
    blank_key: string;
    placeholder: string;
    expected_concept: string;
  }>;
  difficulty: number;
  estimated_minutes: number;
};

export type CodeExerciseToolArgs = {
  session_id: string;
  knowledge_point_id: string;
  exercise: LearningExercise;
  unlock_reason:
    | "early_request"
    | "feynman_passed"
    | "legacy_session"
    | "concept_check_passed"
    | "concept_check_skipped"
    | "concept_check_repair_limit"
    | string
    | null;
  learning_incomplete: boolean;
  concept_summary: string;
  notice: string;
};

export type LearningHistoryArgs = LearningHistoryResponse;

export type ConceptChoiceOption = {
  id: string;
  text: string;
};

export type ConceptCheck = {
  type: "single_choice";
  question: string;
  options: ConceptChoiceOption[];
  expected_focus: string;
};

export type ConceptIntroArgs = {
  session_id: string;
  knowledge_point_id: string;
  summary: string;
  example: {
    title: string;
    body: string;
    takeaway: string;
  };
  check: ConceptCheck;
};

export type ConceptCheckResultArgs = {
  session_id: string;
  knowledge_point_id: string;
  result: "correct" | "incorrect" | "unclear" | "skipped";
  confidence: "high" | "medium" | "low";
  explanation: string;
  next_prompt: string;
  answer_leakage_review?: {
    status: "clear" | "revised" | string;
    revealed_target_answer: boolean;
    next_prompt_requires_same_answer: boolean;
    reason: string;
  } | null;
  actions: Array<{
    id: string;
    label: string;
  }>;
  repair_check: ConceptCheck | null;
};

export type SubmitResultArgs = {
  attempt_id: string;
  result: "failed" | "partial" | "passed" | "easy";
  score: number;
  fsrs_rating: FsrsRating;
  feedback: string;
  weak_points: string[];
  next_action: NextAction;
  score_breakdown: Record<string, number>;
};

export type ReviewRecallArgs = {
  knowledge_point_id: string;
  knowledge_point_title: string;
  description: string | null;
  last_review_at: string | null;
  review_count: number;
  forget_risk: ForgetRisk;
  weak_points: string[];
};

export type ProgressSummaryArgs = {
  plan_id: string;
  overall_progress: number;
  modules_completed: number;
  modules_total: number;
  points_mastered: number;
  points_total: number;
  today_sessions: number;
  streak_days: number;
  next_review_at: string | null;
  next_action: NextAction;
};
