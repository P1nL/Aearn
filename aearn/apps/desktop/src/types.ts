export type ApiHealth = {
  status: "ok";
  service: string;
};

export type LanguageCourse = {
  id: string;
  title: string;
  language: string;
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

export type HarnessCutoverState =
  | "summary_ready"
  | "verified"
  | "blocked_target_state"
  | "blocked_checkpoint_scope";

export type HarnessCutoverSummary = {
  legacy_categories: Array<{ id: string; count: number }>;
  legacy_profile_fields: Array<{ id: string; will_clear: true }>;
  checkpoint: { state: "not_configured" | "scoped" | "unresolved"; record_count: number };
  retained_categories: string[];
  target_state_present: boolean;
};

export type HarnessCutoverDecision = {
  cutover_version: string;
  rollout_active: true;
  state: HarnessCutoverState;
  summary_version?: number;
  preview_nonce?: string;
  summary_hash?: string;
  summary?: HarnessCutoverSummary;
  code?: string;
  verified_at?: string | null;
  idempotent_replayed?: boolean;
  next_action: "confirm_cutover" | "enter_tutor" | "resolve_cutover_block";
};

export type ApiError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
  request_id: string;
  recoverable: boolean;
};

export type TutorRunStatus =
  | "queued"
  | "leased"
  | "running"
  | "waiting_for_input"
  | "waiting_for_capability"
  | "awaiting_effect_commit"
  | "completed"
  | "model_unavailable"
  | "blocked_policy"
  | "budget_exhausted"
  | "cancelled"
  | "failed";

export type TutorTerminalOutcome =
  | "completed"
  | "model_unavailable"
  | "blocked_policy"
  | "budget_exhausted"
  | "cancelled"
  | "failed";

export type TutorContinuationKind = "clarification" | "planning_input" | "approval" | "capability_result" | "external_result";
export type TutorInteractionProtocolVersion = "legacy_v1" | "thread_turn_v2";
export type TutorTurnCompletionReason = "awaiting_user" | "awaiting_approval" | "awaiting_authority";

export type TutorRunState = {
  run_id: string;
  conversation_id: string;
  origin: "interactive" | "proactive";
  status: TutorRunStatus;
  input_revision: number;
  cancelled: boolean;
  iteration_count: number;
  model_call_count: number;
  capability_call_count: number;
  effect_count: number;
  terminal_outcome: TutorTerminalOutcome | null;
  continuation_kind: TutorContinuationKind | null;
  interaction_protocol_version: TutorInteractionProtocolVersion;
  retry_of_turn_id: string | null;
  retry_root_turn_id: string | null;
  response_to_request_id: string | null;
  completion_reason: TutorTurnCompletionReason | null;
  created_at: string | null;
  updated_at: string | null;
};

export type TutorConversationSummary = {
  conversation_id: string;
  title: string;
  last_public_activity_at: string | null;
  active_run: TutorForegroundRun | null;
};

export type TutorForegroundRun = {
  run_id: string;
  status: TutorRunStatus;
  continuation_kind: TutorContinuationKind | null;
};

export type TutorConversationListResponse = {
  items: TutorConversationSummary[];
  next_cursor: string | null;
  has_more: boolean;
};

export type TutorPublicProcessStep = {
  key: "input_received" | "context_prepared" | "authorized_resource_checked" | "learning_reply_generated" | "replaced_by_newer_input";
  state: "completed" | "current";
  label: string;
};

export type TutorPublicProcess = {
  kind: "process";
  id: string;
  run_id: string;
  display_state: "thinking" | "waiting_input" | "waiting_approval" | "waiting_authority" | "completed" | "interrupted" | "superseded" | "unavailable" | "failed";
  steps: TutorPublicProcessStep[];
  elapsed_seconds: number;
  created_at: string | null;
  finished_at: string | null;
};

export type TutorHistoryMessage = {
  kind: "message";
  id: string;
  role: "learner" | "tutor";
  content: string;
  public_thinking_steps: string[];
  context_references: TutorContextReference[];
  in_reply_to_item_id: string | null;
  created_at: string | null;
};

export type TutorRequestOption = { value: string; label: string };

export type TutorRequestPresentation =
  | { type: "text"; field_key: string | null; minimum_length: number; maximum_length: number; multiline: boolean }
  | { type: "integer"; field_key: string; minimum: number; maximum: number; step: number; recommended: number | null; unit: string }
  | { type: "single_select"; field_key: string; options: TutorRequestOption[]; recommended: string | null }
  | { type: "multi_select"; field_key: string; options: TutorRequestOption[]; recommended: string[]; maximum_selections: number }
  | { type: "approval"; proposal_id: string; authority_key: string; risk_level: "low" | "medium" | "high"; summary: string };

export type TutorElicitationItem = {
  kind: "elicitation";
  id: string;
  request_id: string;
  turn_id: string;
  request_kind: Exclude<TutorContinuationKind, "approval">;
  actor: "learner" | "authority";
  state: "pending" | "answered" | "cancelled" | "expired";
  version: number;
  required: true;
  prompt: string;
  presentation: TutorRequestPresentation;
  allowed_actions: "respond"[];
  answer_turn_id: string | null;
  created_at: string | null;
  resolved_at: string | null;
};

export type TutorApprovalItem = {
  kind: "approval";
  id: string;
  request_id: string;
  turn_id: string;
  request_kind: "approval";
  actor: "learner";
  state: "pending" | "answered" | "denied" | "cancelled" | "expired";
  version: number;
  required: true;
  prompt: string;
  presentation: Extract<TutorRequestPresentation, { type: "approval" }>;
  allowed_actions: ("approve" | "deny")[];
  answer_turn_id: string | null;
  created_at: string | null;
  resolved_at: string | null;
};

export type TutorInteractionRequestItem = TutorElicitationItem | TutorApprovalItem;
export type TutorHistoryItem = TutorHistoryMessage | TutorPublicProcess | TutorInteractionRequestItem;

export type TutorConversationHistoryResponse = {
  items: TutorHistoryItem[];
  next_cursor: string | null;
  has_more: boolean;
  active_run: TutorForegroundRun | null;
};

export type TutorConversationResponse = {
  conversation_id: string;
  created: boolean;
  idempotent_replayed: boolean;
};

export type TutorInputAcceptedResponse = {
  conversation_id: string;
  run_id: string;
  input_revision: number;
  message_id: string;
  event_cursor: number;
  dispatch_job_id: string | null;
  merged: boolean;
  input_replayed: boolean;
  idempotent_replayed: boolean;
  run: TutorRunState;
  process: TutorPublicProcess | null;
  replaced_run_id: string | null;
  replaced_process: TutorPublicProcess | null;
  context_references: TutorContextReference[];
};

export type TutorConversationControlState = "idle" | "running" | "waiting" | "queue_paused";
export type TutorQueuePauseReason = "pending_request" | "interrupted" | "failed" | null;

export type TutorQueuedInput = {
  item_id: string;
  state: "pending" | "claimed" | "cancelled";
  position: number;
  version: number;
  content: string;
  created_at: string;
  updated_at: string;
};

export type TutorQueuedInputAcceptedResponse = {
  conversation_id: string;
  queued: true;
  queue_item: TutorQueuedInput;
  control_version: number;
  pending_count: number;
  max_pending: number;
  idempotent_replayed: boolean;
};

export type TutorConversationInputResponse = TutorInputAcceptedResponse | TutorQueuedInputAcceptedResponse;
export type TutorControlledTurnResponse = TutorInputAcceptedResponse & { control_version: number };
export type TutorQueueSteerResponse = TutorControlledTurnResponse & { queue_item: TutorQueuedInput };
export type TutorQueueResumeResponse = TutorControlledTurnResponse | TutorQueueStateResponse;

export type TutorQueueStateResponse = {
  conversation_id: string;
  control_version: number;
  control_state: TutorConversationControlState;
  queue_paused: boolean;
  queue_pause_reason: TutorQueuePauseReason;
  pending_count: number;
  max_pending: number;
  items: TutorQueuedInput[];
  active_turn: TutorPublicTurn | null;
  pending_request: TutorInteractionRequestItem | null;
  idempotent_replayed?: boolean;
};

export type TutorInteractionResponseDraft =
  | { kind: "clarification"; answer_text: string }
  | { kind: "planning_input"; question_key: "language_id" | "goal_text" | "target_level" | "weekly_minutes" | "experience_level" | "teaching_preferences" | "pace_constraints"; catalog_version: "tutor_planning_questions_v1"; value: unknown }
  | { kind: "approval"; proposal_identity: string; decision: "approve" | "deny"; reason?: string | null };

export type TutorInteractionResponseAccepted = TutorInputAcceptedResponse & {
  request: TutorInteractionRequestItem;
  response_replayed: boolean;
};

export type TutorPublicTurn = {
  turn_id: string;
  conversation_id: string;
  interaction_protocol_version: TutorInteractionProtocolVersion;
  status: "in_progress" | "completed" | "interrupted" | "failed";
  retry_of_turn_id: string | null;
  retry_root_turn_id: string | null;
  completion_reason: TutorTurnCompletionReason | null;
  created_at: string | null;
  updated_at: string | null;
};

export type TutorConversationSnapshotResponse = {
  snapshot_version: "tutor_conversation_snapshot_v1";
  conversation: {
    conversation_id: string;
    title: string;
    control_version: number;
    control_state: TutorConversationControlState;
    queue_paused: boolean;
    queue_pause_reason: TutorQueuePauseReason;
    pending_count: number;
    max_pending: number;
  };
  active_turn: TutorPublicTurn | null;
  pending_requests: TutorInteractionRequestItem[];
  queue: TutorQueuedInput[];
  timeline: TutorHistoryItem[];
  next_cursor: string | null;
  has_more: boolean;
  stream_cursor: string;
};

export type TutorActivityItem = {
  activity_id: string;
  category: string;
  reason: string;
  evidence: string[];
  created_at: string | null;
};

export type TutorInboxItem = {
  inbox_id: string;
  activity_id: string;
  message: string;
  state: "unread" | "read" | "dismissed";
  read_at: string | null;
  dismissed_at: string | null;
  created_at: string | null;
};

export type TutorMemoryItem = {
  entry_id: string;
  memory_kind: "objective_fact" | "inference";
  state: "active" | "replaced" | "deleted";
  category: string;
  statement: string;
  confidence: string | null;
  provenance: string;
  replaced_entry_id: string | null;
  evidence: string[];
  retention_until: string | null;
  stale_after: string | null;
  created_at: string | null;
};

export type TutorPlanRevision = {
  revision_id: string;
  predecessor_revision_id: string | null;
  title: string;
  outline: string[];
  diff: string[];
  learner_reason: string;
  evidence: string[];
  created_at: string | null;
};

export type TutorPlanRevisionList = {
  active_revision_id: string | null;
  items: TutorPlanRevision[];
};

export type TutorPreferences = {
  inferred_memory_enabled: boolean;
  memory_setting_version: string;
  proactive_paused: boolean;
  proactive_enabled: boolean;
};

export type TutorInputAcceptedSseEvent = {
  id: number;
  type: "input_accepted";
  data: {
    run_id: string;
    input_revision: number;
    event_sequence: number;
    message_id: string | null;
    status: "accepted";
  };
};

export type TutorToolStatusSseEvent = {
  id: number;
  type: "tool_status";
  data: {
    run_id: string;
    input_revision: number;
    event_sequence: number;
    status: string;
    tool: string;
    message: string;
  };
};

export type TutorActivitySseEvent = {
  id: number;
  type: "activity";
  data: {
    run_id: string;
    input_revision: number;
    event_sequence: number;
    category: string;
    status: string;
  };
};

export type TutorRunStateSseEvent = {
  id: number;
  type: "run_state";
  data: {
    run_id: string;
    input_revision: number;
    event_sequence: number;
    status: TutorRunStatus;
    terminal_outcome: TutorTerminalOutcome | null;
    public_message?: string | null;
  };
};

export type TutorDoneSseEvent = {
  id: number;
  type: "done";
  data: {
    run_id: string;
    input_revision: number;
    event_sequence: number;
    result_ref: { type: "TutorRun"; id: string };
    public_message: string | null;
  };
};

export type TutorErrorSseEvent = {
  id: number | null;
  type: "error";
  data: {
    error: ApiError;
    public_message?: string | null;
  };
};

export type TutorSseEvent =
  | TutorInputAcceptedSseEvent
  | TutorToolStatusSseEvent
  | TutorActivitySseEvent
  | TutorRunStateSseEvent
  | TutorDoneSseEvent
  | TutorErrorSseEvent;

export type LearningScopeInput = {
  scope_kind: "general" | "plan_drafting" | "learning_track";
  learning_track_id?: string | null;
  task_kind?:
    | "general_tutor"
    | "plan_drafting"
    | "lesson_teaching"
    | "exercise_feedback"
    | "review_coaching"
    | "model_code_review"
    | "remediation";
  knowledge_key?: string | null;
};

export type LessonSelectionReferenceDraft = {
  kind: "lesson_selection";
  learning_track_id: string;
  knowledge_key: string;
  document_id: string;
  document_content_hash: string;
  block_id: string;
  start_offset: number;
  end_offset: number;
  excerpt: string;
};

export type ExerciseFeedbackReferenceDraft = {
  kind: "exercise_feedback";
  learning_track_id: string;
  knowledge_key: string;
  attempt_id: string;
};

export type ExecutionResultReferenceDraft = {
  kind: "execution_result";
  learning_track_id: string;
  knowledge_key: string;
  attempt_id: string;
};

export type ReviewFeedbackReferenceDraft = {
  kind: "review_feedback";
  learning_track_id: string;
  knowledge_key: string;
  review_session_id: string;
  attempt_id: string;
};

export type TutorContextReferenceDraft =
  | LessonSelectionReferenceDraft
  | ExerciseFeedbackReferenceDraft
  | ExecutionResultReferenceDraft
  | ReviewFeedbackReferenceDraft;

type TutorContextReferenceBase = {
  reference_id: string;
  schema_version: "tutor_context_reference_v1";
  learning_track_id: string;
  knowledge_key: string;
  source_version: string;
  source_hash: string;
  safe_payload_hash: string;
  created_at: string | null;
};

export type LessonSelectionContextReference = TutorContextReferenceBase & {
  kind: "lesson_selection";
  document_id: string;
  document_content_hash: string;
  content_standard_version: string;
  assignment_version: number;
  block_id: string;
  start_offset: number;
  end_offset: number;
  safe_excerpt: string;
};

export type ExerciseFeedbackContextReference = TutorContextReferenceBase & {
  kind: "exercise_feedback";
  attempt_id: string;
  attempt_type: "run" | "submit";
  exercise_version_id: string;
  outcome: ExerciseAttemptOutcome;
  score: number;
  assistance_kind: ModelReviewAssistanceKind;
  feedback_summary: string;
  capability_scores: Record<string, number>;
  terminal_at: string | null;
};

export type ExecutionResultContextReference = Omit<ExerciseFeedbackContextReference, "kind"> & {
  kind: "execution_result";
  execution_job_id: string;
  execution_job_state: string;
};

export type ReviewFeedbackContextReference = TutorContextReferenceBase & {
  kind: "review_feedback";
  review_session_id: string;
  review_item_id: string;
  attempt_id: string;
  exercise_version_id: string;
  session_version: number;
  outcome: ExerciseAttemptOutcome;
  score: number;
  assistance_kind: ModelReviewAssistanceKind;
  feedback_summary: string;
  capability_scores: Record<string, number>;
  terminal_at: string | null;
};

export type TutorContextReference =
  | LessonSelectionContextReference
  | ExerciseFeedbackContextReference
  | ExecutionResultContextReference
  | ReviewFeedbackContextReference;

export type LearningTrackSummary = {
  track_id: string;
  language_id: string;
  language_display_name: string;
  goal_text: string;
  target_level: string;
  status: "active" | "paused" | "completed" | "archived";
  version: number;
  active_revision_id: string;
  active_plan_title: string;
  current_knowledge_key: string | null;
  current_knowledge_title: string | null;
  progress: {
    total: number;
    completed: number;
    in_progress: number;
    review_due: number;
    percent: number;
  };
  review_due_count: number;
  execution_tier: "teaching_local" | "container_verified" | "static_only" | "unavailable";
  execution_disclosure: string;
  last_learned_at: string | null;
  updated_at: string | null;
};

export type LearningTrackDetail = LearningTrackSummary & {
  created_at: string | null;
  archived_at: string | null;
};

export type LearningRoadmapNode = {
  node_id: string;
  knowledge_key: string;
  title: string;
  description: string;
  order_index: number;
  is_core: boolean;
  prerequisite_keys: string[];
  required_capabilities: string[];
  progress_status: "locked" | "available" | "in_progress" | "completed" | "review_due" | "diagnostic_skipped";
  progress_version: number;
  mastery_level: string;
  mastery_confidence: number;
};

export type LearningRoadmapModule = {
  module_id: string;
  module_key: string;
  title: string;
  description: string;
  order_index: number;
  is_core: boolean;
  is_skippable: boolean;
  nodes: LearningRoadmapNode[];
};

export type LearningRoadmap = {
  track_id: string;
  active_revision_id: string;
  title: string;
  target_level: string;
  modules: LearningRoadmapModule[];
};

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

export type LearningLanguageCatalogItem = {
  language_id: string;
  display_name: string;
  selection_tier: "core" | "extended" | "degraded" | "unavailable";
  selectable: boolean;
  lesson_generation_state: "full" | "partial" | "planned" | "unsupported";
  execution_tier: LearningTrackSummary["execution_tier"];
  execution_disclosure: string;
  source_trust_policy: "official" | "trusted_de_facto" | "internal";
};

export type LearningPlanProfile = {
  language_id: string;
  goal_text: string;
  target_level: string;
  weekly_minutes: number;
  experience_level: "new" | "beginner" | "intermediate" | "advanced";
  teaching_preferences: string[];
  pace_summary: string;
  title: string;
};

export type LearningPlanNode = {
  knowledge_key: string;
  title: string;
  description: string;
  order_index: number;
  is_core: boolean;
  prerequisite_keys: string[];
  required_capabilities: string[];
};

export type LearningPlanModule = {
  module_key: string;
  title: string;
  description: string;
  order_index: number;
  is_core: boolean;
  is_skippable: boolean;
  nodes: LearningPlanNode[];
};

export type LearningPlanDraft = {
  draft_id: string;
  draft_version: number;
  content_hash: string;
  profile: LearningPlanProfile;
  plan: {
    title: string;
    target_level: string;
    modules: LearningPlanModule[];
  };
  sources: Array<{ source_id: string; display_name: string; trust_tier: string }>;
  generator_version: string;
  policy_version: string;
  created_at: string | null;
};

export type LearningPlanSession = {
  session_id: string;
  conversation_id: string;
  status: "collecting" | "draft_ready" | "confirmed" | "cancelled";
  preferred_language_id: string | null;
  version: number;
  current_draft: LearningPlanDraft | null;
  confirmed_track_id: string | null;
  last_error: { code: string; at: string | null } | null;
  created_at: string | null;
  updated_at: string | null;
  confirmed_at: string | null;
  cancelled_at: string | null;
};

export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(`${apiError.code}: ${apiError.message}`);
    this.apiError = apiError;
  }
}
