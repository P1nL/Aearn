export type LessonCitation = {
  citation_id: string;
  source_id: string;
  display_name: string;
  provider: string;
  trust_tier: "official" | "trusted_de_facto" | "internal";
  source_type: "tutorial" | "reference" | "spec" | "platform_docs" | "vendor_docs";
  source_version_label: string;
  source_version_kind: "fixed" | "rolling";
  canonical_url: string;
  section_path: string[];
  fetched_at: string;
  snapshotted_at: string;
  evidence_excerpt: string;
};

type LessonBlockBase = {
  block_id: string;
  order_index: number;
  citation_ids: string[];
};

export type LessonHeadingBlock = LessonBlockBase & { type: "heading"; title: string; subtitle: string };
export type LessonObjectivesBlock = LessonBlockBase & { type: "learning_objectives"; items: string[]; coverage_keys: string[] };
export type LessonConceptBlock = LessonBlockBase & { type: "concept"; title: string; paragraphs: string[]; coverage_keys: string[] };
export type LessonAuthorityNoteBlock = LessonBlockBase & { type: "authority_note"; title: string; statement: string };
export type LessonCodeExampleBlock = LessonBlockBase & { type: "code_example"; title: string; language_id: string; code: string; explanation: string[]; execution_claim: "not_run" };
export type LessonComparisonBlock = LessonBlockBase & { type: "comparison"; title: string; columns: string[]; rows: string[][]; conclusion: string };
export type LessonHintBlock = LessonBlockBase & { type: "hint"; title: string; steps: string[] };
export type LessonExerciseGateBlock = LessonBlockBase & {
  type: "exercise_gate";
  gate_key: string;
  gate_kind: "knowledge_check" | "guided_practice" | "independent_practice";
  assessment_contract_version: string;
  required_capabilities: string[];
  learner_prompt: string;
};
export type LessonSummaryBlock = LessonBlockBase & { type: "summary"; points: string[]; coverage_keys: string[] };
export type LessonNextStepsBlock = LessonBlockBase & { type: "next_steps"; items: string[] };

export type LessonBlock =
  | LessonHeadingBlock
  | LessonObjectivesBlock
  | LessonConceptBlock
  | LessonAuthorityNoteBlock
  | LessonCodeExampleBlock
  | LessonComparisonBlock
  | LessonHintBlock
  | LessonExerciseGateBlock
  | LessonSummaryBlock
  | LessonNextStepsBlock;

export type LessonDocument = {
  schema_version: "lesson_document_v1";
  title: string;
  language_id: string;
  knowledge_key: string;
  content_standard_version: string;
  coverage_keys: string[];
  blocks: LessonBlock[];
  content_hash: string;
};

export type LessonAssignment = {
  assignment_id: string;
  document_id: string;
  assignment_version: number;
  status: "active" | "proposed" | "superseded";
  content_hash: string;
  started_at: string | null;
  activated_at: string | null;
  progress_status: string | null;
  progress_version: number | null;
};

export type LessonAuthoringRun = {
  run_id: string;
  state: "pending" | "claimed" | "running" | "completed" | "failed" | "cancelled";
  run_kind: "prepare" | "refresh";
  attempt_count: number;
  failure_code: string | null;
  failure_message: string | null;
  created_at: string;
  updated_at: string;
  terminal_at: string | null;
};

export type LessonUpdateProposal = {
  assignment_id: string;
  assignment_version: number;
  document_id: string;
  status: "proposed";
  impact: {
    source_changes: string[];
    blocks_added: string[];
    blocks_removed: string[];
    blocks_reordered: string[];
    examples_changed: string[];
    gates_changed: string[];
    retained_blocks: string[];
  };
};

export type LessonDocumentState = {
  status: "missing" | "preparing" | "ready" | "failed";
  track_id: string;
  module_key: string;
  module_diagnostic_allowed: boolean;
  knowledge_key: string;
  track_version: number;
  progress_version: number;
  progress_status: string;
  assignment: LessonAssignment | null;
  document: LessonDocument | null;
  sources: LessonCitation[];
  update: LessonUpdateProposal | null;
  authoring_run: LessonAuthoringRun | null;
};

export type LessonPrepareResponse = {
  status: "missing" | "preparing" | "ready" | "failed";
  track_id: string;
  knowledge_key: string;
  authoring_run: LessonAuthoringRun | null;
  idempotent_replayed: boolean;
};

export type ExecutionTier = "teaching_local" | "container_verified" | "static_only" | "unavailable";
export type ExerciseType = "code_completion" | "sql_query" | "browser_preview" | "static_code_reasoning" | "model_code_review";
export type GateRequirementKind = "required" | "recommended" | "diagnostic";
export type LessonGateState = "available" | "in_progress" | "passed" | "remediation_required";
export type LessonGateAction = "prepare" | "hint" | "run" | "submit";
export type ExerciseAttemptType = "run" | "submit" | "diagnostic_submit";
export type ExerciseAttemptOutcome = "passed" | "failed" | "timed_out" | "cancelled" | "unavailable" | "invalid";
export type ExerciseIndependence = "independent" | "hinted" | "remediated";
export type ModelReviewAssistanceKind = ExerciseIndependence | "validation_evidence_viewed";
export type ModelReviewVerdict = "correctness_issue" | "no_correctness_issue" | "improvement_only" | "uncertain";
export type ModelReviewFindingKind = "correctness" | "improvement";
export type ModelReviewSeverity = "info" | "low" | "medium" | "high" | "critical";
export type ModelReviewFindingStatus = "supported" | "partial" | "unsupported" | "duplicate";

export type ModelReviewPrompt = {
  schema_version: "model_code_review_prompt_v1";
  requirements: string[];
  review_scope: string[];
  evidence_boundary: "prepublication_verified";
  learner_instruction: string;
};

export type ModelReviewArtifact = {
  schema_version: "model_code_review_artifact_v1";
  language_id: string;
  runtime_label: string;
  model_code: string;
  code_hash: string;
  line_count: number;
};

export type ModelReviewFinding = {
  client_finding_id: string;
  finding_kind: ModelReviewFindingKind;
  start_line: number;
  end_line: number;
  category: string;
  severity: ModelReviewSeverity;
  trigger_condition: string;
  principle: string;
  impact: string;
  validation_method: string;
  suggested_fix: string;
  supplemental_note: string | null;
};

export type ModelCodeReviewSubmission = {
  schema_version: "model_code_review_submission_v1";
  verdict: ModelReviewVerdict;
  findings: ModelReviewFinding[];
  supplemental_note: string | null;
};

export type ModelReviewFindingFeedback = {
  client_finding_id: string;
  status: ModelReviewFindingStatus;
  safe_reason_code: string;
};

export type ModelReviewScoreBreakdown = {
  policy_version: "model_code_review_score_v1";
  verdict: number;
  discovery: number;
  omission: number;
  severity: number;
  evidence: number;
  validation_method: number;
  suggested_fix: number;
  false_positive: number;
  duplicate: number;
};

export type ModelReviewSafeFeedback = {
  status: "model_code_review_evaluated";
  message: string;
  execution_claim: "not_run";
  assistance_kind: ModelReviewAssistanceKind;
  score_breakdown: ModelReviewScoreBreakdown;
  finding_feedback: ModelReviewFindingFeedback[];
  omission_band: "none" | "limited" | "major";
  next_action: "advance_next" | "review_variant" | "show_hint";
};

export type ModelReviewVisibleEvidence = {
  schema_version: "model_code_review_visible_evidence_v1";
  execution_claim: "prepublication_only";
  checks: Array<{
    check_type: "parser" | "compile_or_typecheck" | "visible_tests" | "hidden_tests" | "coverage";
    status: "passed" | "not_applicable";
    safe_code: string;
  }>;
};

export type ModelReviewEvidenceResponse = {
  evidence_id: string;
  evidence: ModelReviewVisibleEvidence;
  assistance_kind: "validation_evidence_viewed";
  gate_version: number;
  created_at: string | null;
  idempotent_replayed: boolean;
};

export type ModelReviewAuthoringRun = {
  run_id: string;
  state: "pending" | "claimed" | "running" | "validating" | "completed" | "failed" | "cancelled";
  attempt_count: number;
  failure_code: string | null;
  failure_message: string | null;
};

type LessonGateExerciseBase = {
  exercise_version_id: string;
  exercise_key: string;
  version: string;
  title: string;
  required_capabilities?: string[];
  content_hash?: string;
};

export type ModelCodeReviewExercise = LessonGateExerciseBase & {
  exercise_type: "model_code_review";
  learner_prompt: ModelReviewPrompt;
  starter_artifact: ModelReviewArtifact;
};

export type LessonGateExercise =
  | ModelCodeReviewExercise
  | (LessonGateExerciseBase & {
      exercise_type: Exclude<ExerciseType, "model_code_review">;
      learner_prompt: Record<string, unknown>;
      starter_artifact: Record<string, unknown>;
    });

export type LessonGateResult = {
  outcome: ExerciseAttemptOutcome;
  score: number;
  safe_feedback: Record<string, unknown> | ModelReviewSafeFeedback;
  capability_scores?: Record<string, number>;
  terminal_at: string | null;
};

export type LessonGateUnboundItem = {
  gate_key: string;
  gate_kind: LessonExerciseGateBlock["gate_kind"];
  assessment_contract_version: string;
  required_capabilities: string[];
  learner_prompt: string;
  status: "unbound" | "preparing" | "failed";
  allowed_actions: LessonGateAction[];
  exercise: null;
  review_authoring_run: ModelReviewAuthoringRun | null;
};

export type LessonGateBoundItem = {
  gate_key: string;
  gate_kind: LessonExerciseGateBlock["gate_kind"];
  assessment_contract_version: string;
  required_capabilities: string[];
  learner_prompt: string;
  binding_id: string;
  binding_contract_hash: string;
  requirement_kind: GateRequirementKind;
  pass_policy_version: string;
  pass_threshold: number;
  execution_requirement: "required" | "optional" | "forbidden";
  status: LessonGateState;
  gate_version: number;
  attempt_count: number;
  best_score: number;
  latest_attempt_id: string | null;
  passed_at: string | null;
  execution_tier: ExecutionTier;
  execution_disclosure: string;
  allowed_actions: LessonGateAction[];
  exercise: LessonGateExercise;
  latest_result: LessonGateResult | null;
};

export type LessonGateItem = LessonGateUnboundItem | LessonGateBoundItem;

export type LessonGateList = {
  track_id: string;
  knowledge_key: string;
  track_version: number;
  progress_version: number;
  assignment_id: string;
  assignment_version: number;
  items: LessonGateItem[];
};

export type LessonGatePrepareResponse =
  | { status: "ready"; gate: LessonGateItem; idempotent_replayed: boolean }
  | {
      status: "preparing" | "failed";
      gate: LessonGateItem | null;
      review_authoring_run: ModelReviewAuthoringRun;
      idempotent_replayed: boolean;
    };

export type LessonGateHint = {
  hint_id: string;
  hint_level: number;
  hint_policy_version: string;
  safe_hint: Record<string, unknown>;
  gate_version: number;
  created_at: string | null;
  idempotent_replayed: boolean;
};

export type ExerciseAttemptState = {
  attempt_id: string;
  attempt_type: ExerciseAttemptType;
  track_id: string;
  knowledge_key: string;
  exercise_version_id: string;
  submission_hash: string;
  independence: ExerciseIndependence;
  assistance_kind: ModelReviewAssistanceKind;
  accepted_at: string | null;
  status: "pending" | "terminal";
  execution_job_id: string | null;
  execution_job_state: string | null;
  result: LessonGateResult | null;
  projected: boolean | null;
  route_changed: boolean;
  mastery: {
    confidence: number;
    mastery_level: string;
    evidence_count: number;
    observation_count: number;
  } | null;
  idempotent_replayed: boolean;
  execution_tier?: ExecutionTier;
  execution_disclosure?: string;
};

export type ModuleDiagnosticStateValue = "active" | "failed" | "passed_pending_confirmation" | "confirmed" | "expired";

export type ModuleDiagnosticImpact = {
  kind: "diagnostic_skipped_module";
  module_key: string;
  diagnostic_session_id: string;
  policy_version: string;
  affected_knowledge_keys: string[];
  capability_scores: Record<string, number>;
  source_plan_revision_id: string;
  proposed_plan_revision_id: string;
  expected_track_version: number;
};

export type ModuleDiagnosticItem = {
  item_id: string;
  item_key: string;
  order_index: number;
  capability_key: string;
  knowledge_key: string;
  threshold: number;
  exercise: LessonGateExercise;
  attempt_id: string | null;
  execution_job_state: string | null;
  result: LessonGateResult | null;
};

export type ModuleDiagnosticState = {
  session_id: string;
  track_id: string;
  module_key: string;
  diagnostic_version: string;
  policy_version: string;
  core_capabilities: string[];
  pass_threshold: number;
  require_all_core: boolean;
  independent_only: boolean;
  cooldown_seconds: number;
  state: ModuleDiagnosticStateValue;
  version: number;
  source_plan_revision_id: string;
  proposed_plan_revision_id: string | null;
  impact: ModuleDiagnosticImpact | null;
  weak_capabilities: string[];
  started_at: string | null;
  terminal_at: string | null;
  cooldown_until: string | null;
  confirmed_at: string | null;
  items: ModuleDiagnosticItem[];
  idempotent_replayed: boolean;
};
