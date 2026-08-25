import type { ExecutionTier, ExerciseIndependence, ExerciseType, LessonGateResult, ModelReviewArtifact, ModelReviewAssistanceKind, ModelReviewPrompt } from "./lesson";

export type ReviewQueueItem = {
  schedule_id: string;
  knowledge_key: string;
  title: string;
  due_at: string | null;
  risk_level: "low" | "normal" | "high" | "critical";
  critical_prerequisite_gate: boolean;
  mastery: Record<string, unknown>;
  required_capabilities: string[];
  schedule_version: number;
};

export type ReviewQueue = {
  track_id: string;
  as_of: string | null;
  due_count: number;
  items: ReviewQueueItem[];
  critical_prerequisite_gate: ReviewQueueItem | null;
};

type ReviewExerciseBase = {
  exercise_version_id: string;
  title: string;
  required_capabilities: string[];
  content_hash: string;
  execution_tier: ExecutionTier;
  execution_disclosure: string;
};

export type ReviewExercise =
  | (ReviewExerciseBase & {
      exercise_type: "model_code_review";
      learner_prompt: ModelReviewPrompt;
      starter_artifact: ModelReviewArtifact;
    })
  | (ReviewExerciseBase & {
      exercise_type: Exclude<ExerciseType, "model_code_review">;
      learner_prompt: Record<string, unknown>;
      starter_artifact: Record<string, unknown>;
    });

export type ReviewSessionAttemptSummary = {
  attempt_id: string;
  status: "pending" | "terminal";
  independence: ExerciseIndependence;
  assistance_kind: ModelReviewAssistanceKind;
  execution_job_id: string | null;
  execution_job_state: string | null;
  result: LessonGateResult | null;
};

export type ReviewSessionItem = {
  item_id: string;
  order_index: number;
  version: number;
  exercise: ReviewExercise;
  attempt: ReviewSessionAttemptSummary | null;
};

export type ReviewSession = {
  session_id: string;
  track_id: string;
  knowledge_key: string;
  plan_revision_id: string;
  state: "blocked" | "active" | "ready_to_finalize" | "finalized" | "cancelled";
  stage: "warmup" | "practice" | "final_summary";
  failure_code: string | null;
  recoverable: boolean;
  version: number;
  context_snapshot: Record<string, unknown>;
  context_snapshot_hash: string;
  items: ReviewSessionItem[];
  finalization: { rating: "again" | "hard" | "good" | "easy"; aggregate: Record<string, unknown>; result_hash: string } | null;
  started_at: string | null;
  terminal_at: string | null;
  idempotent_replayed: boolean;
};

export type ReviewHint = {
  hint_id: string;
  hint_level: number;
  safe_hint: Record<string, unknown>;
  created_at: string | null;
};

export type ReviewAttempt = {
  attempt_id: string;
  attempt_type: "review_submit";
  track_id: string;
  session_id: string;
  item_id: string;
  knowledge_key: string;
  session_version: number;
  exercise_version_id: string;
  submission_hash: string;
  independence: ExerciseIndependence;
  assistance_kind: ModelReviewAssistanceKind;
  accepted_at: string | null;
  status: "pending" | "terminal";
  execution_job_id: string | null;
  execution_job_state: string | null;
  result: LessonGateResult | null;
  idempotent_replayed: boolean;
  execution_tier?: ExecutionTier;
  execution_disclosure?: string;
};
